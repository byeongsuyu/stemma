"""Local work buffers and search adapters around the Studio application."""

import base64
import binascii
import copy
import datetime
import hashlib
import json
import re
import uuid
from pathlib import Path

from stemma_studio.core import domain, editing, uploads
from stemma_studio.core.adapters import to_genealogy
from stemma_studio.core.application import Studio
from stemma_studio.core.disclosure import chronology_key, document_date
from stemma_studio.core.repository import reuse_or_create
from stemma_studio.locale import FALLBACK, Message, translate


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def now():
    return datetime.datetime.now(datetime.UTC).isoformat()


class Conflict(ValueError):
    """Reject a stale work buffer instead of overwriting another saved state."""


class Editor:
    """Serialize requests in one local server; independent writers are unsupported."""

    def __init__(self, root):
        self.studio = Studio(root)
        self.root = Path(root).resolve()
        self.folder = self.root / "data" / "workspaces"
        # The interface language of the request being served; the server sets it.
        self.language = FALLBACK

    def state(self):
        return self.studio.load(auto_sync=False)

    def work_path(self, wid):
        if not re.fullmatch(r"work-[a-f0-9]{32}", wid):
            raise ValueError(Message("error.editor.work_id"))
        return self.studio.path("data/workspaces/" + wid + ".json")

    def work(self, wid):
        return json.loads(self.work_path(wid).read_text(encoding="utf-8"))

    def manuscript_language(self, wid):
        """The language a manuscript is written in, for setting its preview.

        A revision of an existing document is in that document's language, which the
        publication side records and a later change of setting does not move; only a
        new piece follows the blog's setting, and the desk's own language before that.
        """
        from stemma_studio.blog.admin import Admin

        admin, state = Admin(self.root), self.state()
        did = self.work(wid).get("document_id") if wid else None
        language = admin.document_language(state, did) if did in state["documents"] else None
        return language or admin.writing_language(state) or self.language

    def write_work(self, work):
        path = self.work_path(work["id"])
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(".json.tmp")
        temp.write_text(json.dumps(work, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temp.replace(path)
        return work

    def works(self):
        return sorted(
            [self.work(p.stem) for p in self.folder.glob("work-*.json")], key=lambda w: w["updated_at"], reverse=True
        )

    def delete_work(self, wid, version):
        """Discard only a mutable workspace after checking its observed version."""
        work = self.work(wid)
        self.check_version(work, version)
        self.work_path(wid).unlink()
        return {"deleted": wid}

    def detail(self, docid, revision=None, state=None):
        state = state if state is not None else self.state()
        doc = state["documents"][docid]
        rid = revision or doc["current_revision"]
        rev = next(r for r in doc["revisions"] if r["id"] == rid)
        dated = document_date(doc)
        return dict(
            doc,
            id=docid,
            revision=rid,
            date=dated["value"],
            date_kind=dated["kind"],
            sha256=rev["sha256"],
            body=self.studio.repository.read_text(rev["path"]),
            relations=[
                dict(
                    e,
                    parent_title=state["documents"][e["parent"]]["title"],
                    child_title=state["documents"][e["child"]]["title"],
                )
                for e in state["edges"]
                if docid in (e["parent"], e["child"])
            ],
        )

    def catalog(self, query="", archived=False, offset=0):
        """Match all casefolded substrings, preferring matches in titles.

        This intentionally supports Korean partial words without a tokenizer or
        an embedding index. Empty queries sort by available source/save dates.
        """
        state = self.state()
        terms = query.casefold().split()
        rows = []
        for docid, doc in state["documents"].items():
            if doc["archived"] != archived:
                continue
            rev = next(r for r in doc["revisions"] if r["id"] == doc["current_revision"])
            body = self.studio.repository.read_text(rev["path"])
            title, text = doc["title"].casefold(), body.casefold()
            if not all(t in title or t in text for t in terms):
                continue
            source = doc.get("source") or {}
            dated = document_date(doc)
            index = next((text.index(t) for t in terms if t in text), 0)
            rows.append(
                {
                    "id": docid,
                    "title": doc["title"],
                    "revision": rev["id"],
                    "sha256": rev["sha256"],
                    "kind": doc["kind"],
                    "state": doc["state"],
                    "archived": doc["archived"],
                    "date": dated["value"] or "",
                    "date_kind": dated["kind"],
                    "_chronology": chronology_key(doc),
                    "platform": source.get("metadata", {}).get("source", "Studio"),
                    "snippet": body[max(0, index - 35) : index + 145],
                    "_rank": sum(t in title for t in terms),
                }
            )
        rows.sort(key=lambda d: (d["_rank"], d["_chronology"], d["id"]), reverse=True)
        return {
            "total": len(rows),
            "documents": rows[offset : offset + 60],
            "questions": state["questions"],
            "document_questions": {i: d["questions"] for i, d in state["documents"].items()},
        }

    def components(self, ids, include_proposed=False):
        """Enrich core components with private reading metadata, without writes."""
        if len(ids) > 100:
            raise ValueError(Message("error.editor.too_many_components"))
        state = self.state()
        components = to_genealogy(state).connected_components(ids, include_proposed)
        selected = set(ids)
        output = []
        for component in components:
            nodes = []
            for docid in component["nodes"]:
                doc = state["documents"][docid]
                dated = document_date(doc)
                revision = next(r for r in doc["revisions"] if r["id"] == doc["current_revision"])
                body = self.studio.repository.read_text(revision["path"])
                nodes.append(
                    {
                        "id": docid,
                        "title": doc["title"],
                        "date": dated["value"],
                        "date_kind": dated["kind"],
                        "kind": doc["kind"],
                        "state": doc["state"],
                        "archived": doc["archived"],
                        "revision": revision["id"],
                        "revision_count": len(doc["revisions"]),
                        "selected": docid in selected,
                        "excerpt": body[:180],
                        "questions": list(doc["questions"]),
                    }
                )
            edge_ids = {edge.id for edge in component["edges"]}
            output.append(
                {
                    "id": component["nodes"][0],
                    "nodes": nodes,
                    "edges": [copy.deepcopy(e) for e in state["edges"] if e["id"] in edge_ids],
                }
            )
        return {
            "components": output,
            "questions": state["questions"],
            "include_proposed": include_proposed,
            "selected": sorted(selected),
        }

    def new(self, docid=None):
        state = self.state()
        document = state["documents"].get(docid) if docid else None
        if docid and (not document or document["kind"] != "original" or document["archived"]):
            raise ValueError(Message("error.editor.not_revisable"))
        # Reopening an existing document resumes its work instead of forking a stale buffer.
        if docid:
            existing = next(
                (w for w in self.works() if w["document_id"] == docid and w["base"] == fingerprint(document)), None
            )
            if existing:
                return existing
        selections = copy.deepcopy(document.get("editor_sources", [])) if document else []
        if document and document["state"] == "draft" and not selections:
            for edge in state["edges"]:
                if edge["child"] == docid:
                    d = self.detail(edge["parent"], edge["parent_revision"], state)
                    selections.append(
                        {
                            "id": d["id"],
                            "revision": d["revision"],
                            "sha256": d["sha256"],
                            "title": d["title"],
                            "role": "parent",
                            "questions": edge["questions"],
                            "new_questions": [],
                            "note": edge["change_note"],
                            "archive": False,
                        }
                    )
        work = {
            "schema_version": 1,
            "id": "work-" + uuid.uuid4().hex,
            "version": 1,
            "document_id": docid,
            "base": fingerprint(document) if document else None,
            "document_state": document["state"] if document else "draft",
            "title": document["title"] if document else "",
            "body": self.detail(docid, state=state)["body"] if document else "",
            "note": "",
            "selections": selections,
            "attachments": copy.deepcopy((document.get("source") or {}).get("assets", [])) if document else [],
            "updated_at": now(),
            "saved_revision": document["current_revision"] if document else None,
        }
        return self.write_work(work)

    def attach(self, wid, files):
        """Store attached pictures and describe them. The work is not touched.

        Saving the manuscript is what records an attachment, so the link in the
        body and the record of what it points at travel together in one save and
        cannot disagree. Storing the bytes first is safe on its own: they are
        named by their own hash, and nothing refers to them until a save does.
        """
        self.work(wid)
        if not isinstance(files, list) or not 0 < len(files) <= 20:
            raise ValueError(Message("error.editor.upload_count"))
        stored = []
        for item in files:
            if not isinstance(item, dict) or not isinstance(item.get("name"), str):
                raise ValueError(Message("error.editor.upload_shape"))
            try:
                content = base64.b64decode(item.get("data") or "", validate=True)
            except (ValueError, binascii.Error) as error:
                raise ValueError(Message("error.editor.upload_unreadable", name=item["name"])) from error
            stored.append(uploads.store(self.studio.repository, item["name"], content))
        return {"attachments": stored}

    def previewable(self, wid):
        """Where a draft's own attachments can be read while previewing it.

        Nothing outside this work is reachable, and a record whose bytes are not
        actually stored is left out rather than becoming a broken image.
        """
        if not isinstance(wid, str) or not re.fullmatch(r"work-[0-9a-f]{32}", wid):
            return {}
        try:
            work = self.work(wid)
        except (OSError, ValueError):
            return {}
        assets = {}
        for asset in work.get("attachments") or []:
            try:
                uploads.verify(self.studio.repository, asset)
            except domain.ModelError:
                continue
            assets[asset["archive_path"]] = "/attachments/" + asset["snapshot"].split("/")[-1]
        return assets

    def check_version(self, work, version):
        if type(version) is not int or work["version"] != version:
            raise Conflict(Message("error.editor.work_changed"))

    def update(self, wid, payload):
        work = self.work(wid)
        self.check_version(work, payload["version"])
        for key in ("title", "body", "note"):
            if not isinstance(payload[key], str):
                raise ValueError(Message("error.editor.work_shape"))
        selections = payload["selections"]
        if not isinstance(selections, list) or len(selections) > 100:
            raise ValueError(Message("error.editor.too_many_sources"))
        state = self.state()
        seen = set()
        for item in selections:
            if item["id"] in seen or item["role"] not in ("parent", "reference"):
                raise ValueError(Message("error.editor.bad_selection"))
            seen.add(item["id"])
            detail = self.detail(item["id"], item["revision"], state)
            if detail["sha256"] != item["sha256"]:
                raise Conflict(Message("error.editor.source_hash"))
            for key in ("questions", "new_questions"):
                if not isinstance(item[key], list) or not all(isinstance(v, str) for v in item[key]):
                    raise ValueError(Message("error.editor.questions_shape"))
            if not isinstance(item["note"], str) or type(item["archive"]) is not bool:
                raise ValueError(Message("error.editor.review_shape"))
            item["title"] = detail["title"]
        for key in ("title", "body", "note", "selections"):
            work[key] = copy.deepcopy(payload[key])
        # Attachments only ever accumulate, so a save from a screen that has not
        # seen the newest picture cannot drop it.
        attached = payload.get("attachments") or []
        if not isinstance(attached, list) or len(attached) > 200:
            raise ValueError(Message("error.editor.too_many_attachments"))
        for item in attached:
            if not isinstance(item, dict) or set(item) != {"archive_path", "snapshot", "sha256", "media_type"}:
                raise ValueError(Message("error.editor.attachment_shape"))
            uploads.verify(self.studio.repository, item)
        work["attachments"] = uploads.merge(work.get("attachments", []), attached)
        work.update(version=work["version"] + 1, updated_at=now())
        return self.write_work(work)

    def commit(self, wid, version, confirm=False):
        work, state = self.work(wid), self.state()
        self.check_version(work, version)
        docid = work["document_id"] or "studio-" + wid[5:]
        previous = state["documents"].get(docid)
        operation = f"{wid}:{version}:{confirm}"
        # A receipt in the metadata repairs a work-file write failure after commit.
        if previous and previous.get("editor_receipt") == operation:
            return self.finish(work, previous, docid)
        if (fingerprint(previous) if previous else None) != work["base"]:
            raise Conflict(Message("error.editor.document_changed"))
        domain._require(bool(work["title"].strip()) and bool(work["body"].strip()), Message("error.editor.empty"))
        changed = not previous or domain.digest(work["body"]) != next(
            r["sha256"] for r in previous["revisions"] if r["id"] == previous["current_revision"]
        )
        revision = None
        if changed:
            rid = "r" + str(1 + len(previous["revisions"]) if previous else 1)
            # A note is part of the author's own record, so the default is written in their language.
            note = work["note"].strip() or translate(self.language, "editor.default_note")
            revision = self.studio._revision(docid, rid, work["body"], note)
        parents, questions, archive = None, {}, []
        if confirm:
            domain._require(
                not previous or previous["state"] == "draft",
                Message("error.editor.already_confirmed"),
            )
            parents = []
            for item in work["selections"]:
                if item["role"] == "reference":
                    continue
                scopes = list(item["questions"])
                for text in item["new_questions"]:
                    text = text.strip()
                    if not text:
                        continue
                    qid = next(
                        (k for k, v in state["questions"].items() if v["text"] == text), "q-" + domain.digest(text)[:24]
                    )
                    questions[qid] = text
                    scopes.append(qid)
                parents.append(
                    {
                        "parent": item["id"],
                        "revision": item["revision"],
                        "questions": list(dict.fromkeys(scopes)),
                        "change_note": item["note"],
                    }
                )
                if item["archive"]:
                    archive.append(item["id"])
        result = editing.prepare(state, docid, work["title"].strip(), revision, parents, questions, confirm, archive)
        doc = result["documents"][docid]
        doc.update(editor_receipt=operation, edited_at=now())
        if previous is None:
            doc["created_at"] = doc["edited_at"]
        # Working references remain private and never enter the publication projection.
        doc["editor_sources"] = copy.deepcopy(work["selections"])
        # Pictures attached while writing are recorded the way imported ones are,
        # so blog.attachments resolves both by the same rule.
        attached = work.get("attachments") or []
        if attached or (doc.get("source") or {}).get("origin") == "editor":
            source = copy.deepcopy(doc.get("source") or {"origin": "editor", "assets": []})
            source["assets"] = uploads.merge(source.get("assets", []), attached)
            doc["source"] = source
        domain.validate(result)
        if revision:
            reuse_or_create(
                self.studio.repository, revision["path"], work["body"], Message("error.editor.revision_path")
            )
        self.studio.save(result)
        return self.finish(work, doc, docid)

    def finish(self, work, doc, docid):
        work.update(
            document_id=docid,
            base=fingerprint(doc),
            document_state=doc["state"],
            saved_revision=doc["current_revision"],
            version=work["version"] + 1,
            updated_at=now(),
        )
        return self.write_work(work)

    def restore(self, docid):
        state = self.state()
        self.studio.set_archived(state, docid, False)
        return {"restored": docid}
