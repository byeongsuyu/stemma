"""Local author workflows. Preview candidates stay in memory until explicit selection."""

import copy
import hashlib
import json
import re
import unicodedata
import uuid
from datetime import UTC, datetime
from pathlib import Path

from stemma_studio.core.adapters import to_genealogy
from stemma_studio.core.application import Studio
from stemma_studio.core.blog import fingerprint, identifier, pair_input
from stemma_studio.core.disclosure import EDGE_FIELDS, chronology_key, document_date, month_date
from stemma_studio.core.domain import ModelError
from stemma_studio.core.repository import verify_contents
from stemma_studio.locale import FALLBACK, Message, carried

from .attachments import referenced_attachments
from .input import prepare_input
from .preview import static_files
from .site_settings import load as load_site

LANGUAGES = ("ko", "en")


def other(language):
    """The other side of a pair: the translation of an original, or the original of one."""
    return "en" if language == "ko" else "ko"


def base_language(doc, draft, fallback):
    """The language a document is written in: the side of its pairs that is its revision.

    A stored variant settles it, then a kept translation draft (the side it carries a
    body for is the translation), and only a document with neither follows `fallback`,
    the blog's setting. Changing that setting therefore never turns round a post that
    is already published or already being translated.
    """
    written = [v["language"] for v in doc["language_variants"].values() if v["body"]["kind"] == "base_revision"]
    if written:
        return written[-1]
    for language in LANGUAGES:
        if draft and "body" in (draft.get(language) or {}):
            return other(language)
    return fallback


def label_language(state, kind, target, document_language, fallback):
    """The language a question or change note was written in — its own, not the post's.

    Genealogy wording is shared by every post whose genealogy shows it, so a post written
    in English can carry a question first asked in Korean. The label says so once it has
    one: the side holding the wording exactly as written. Before that, a change note was
    written with its child, and a question with the first child that asked it, so each
    takes that document's language; `fallback` only when nothing records one.
    """
    if kind == "question":
        source = state["questions"][target]["text"]
        child = next((e["child"] for e in state["edges"] if target in e["questions"]), None)
    else:
        edge = next(e for e in state["edges"] if e["id"] == target)
        source, child = edge["change_note"], edge["child"]
    label = state["blog"][kind + "_labels"].get(target)
    for language in LANGUAGES:
        if label and label["translations"].get(language) == source:
            return language
    return (document_language(child) if child else None) or fallback


def translated_side(variants):
    """Which language of a pair has a body of its own, or None for a pair without one."""
    return next((lang for lang, v in variants.items() if v["body"]["kind"] == "translation"), None)


class Conflict(ValueError):
    """The author must reload before applying a review of obsolete state."""


class Overlay:
    """Read preserved bytes through the repository; stage writes without side effects."""

    def __init__(self, repository, state):
        self.repository, self.state, self.files = repository, copy.deepcopy(state), {}

    def read_bytes(self, path):
        return self.files[path] if path in self.files else self.repository.read_bytes(path)

    def read_text(self, path):
        return self.read_bytes(path).decode("utf-8")

    def write_new(self, path, text):
        self.write_bytes_new(path, text.encode("utf-8"))

    def write_bytes_new(self, path, data):
        try:
            self.read_bytes(path)
        except (FileNotFoundError, KeyError):
            self.files[path] = data
        else:
            raise ValueError(Message("error.admin.immutable_exists"))

    def load(self):
        return copy.deepcopy(self.state)

    def save(self, state):
        verify_contents(state, self.read_text, self.read_bytes)
        self.state = copy.deepcopy(state)

    def commit(self):
        # New orphan snapshots may survive a failed metadata write; retry reuses exact bytes.
        for path, data in self.files.items():
            try:
                previous = self.repository.read_bytes(path)
            except (FileNotFoundError, KeyError):
                self.repository.write_bytes_new(path, data)
            else:
                if previous != data:
                    raise Conflict(Message("error.admin.path_changed"))
        self.repository.save(self.state)


def same_pair(doc, first, second):
    """Distinct pair IDs can freeze identical text, e.g. after a series-only change."""
    if first is None or second is None:
        return first == second
    a, b = doc["publication_pairs"][first], doc["publication_pairs"][second]
    files = lambda pair: sorted((x["path"], x["sha256"]) for x in pair["attachments"])
    return (a["base_revision"], a["variants"], files(a)) == (b["base_revision"], b["variants"], files(b))


def draft_differs(doc, draft, pair, read_text):
    """A kept translation draft is pending work only when it departs from the selected pair.

    A draft for another revision is either stale or already reported as a newer revision.
    """
    if draft is None or draft["revision"] != pair["base_revision"]:
        return False
    variants = {lang: doc["language_variants"][vid] for lang, vid in pair["variants"].items()}
    for lang in LANGUAGES:
        if (draft[lang]["title"], draft[lang]["summary"] or None) != (
            variants[lang]["title"],
            variants[lang]["summary"],
        ):
            return True
    translated = translated_side(variants)
    return bool(translated) and draft[translated].get("body") != read_text(variants[translated]["body"]["path"])


def site_status(doc, live, draft, read_text, published=False):
    """Compare a post's local selection with the live release and name the next step.

    `change` is what the next deployment does to this post; `work` is local preparation
    that is not confirmed yet. Unconfirmed work lives only in the translation draft (a
    variant exists only once confirmed), and for a selected post the draft counts only
    when it differs from the pair. `published` means some successful release carried the
    post, so only such a post is 'withdrawn'. An archived post is covered by its
    successors, so it is hidden unless it is still selected or live.
    """
    selected = doc["publication"]["selected_pair"]
    pairs = doc["publication_pairs"]
    live_revision = pairs[live]["base_revision"] if live else None
    selected_revision = pairs[selected]["base_revision"] if selected else None
    if selected and not live:
        change = "new"
    elif live and not selected:
        change = "withdraw"
    elif selected and not same_pair(doc, live, selected):
        change = "revision" if live_revision != selected_revision else "translation"
    else:
        change = None
    if selected:
        work = (
            "revision"
            if doc["current_revision"] != selected_revision
            else "translation"
            if draft_differs(doc, draft, pairs[selected], read_text)
            else None
        )
    else:
        # Only the translated side is new work; the original's title is prefilled.
        translated = [draft[lang] for lang in LANGUAGES if draft and "body" in draft[lang]]
        work = (
            "translation" if translated and (translated[0]["title"].strip() or translated[0]["body"].strip()) else None
        )
    withdrawn = published and not selected and not live
    if change:
        group = "deploy"
    elif selected:
        group = "prepare" if work else "live"
    elif doc["archived"]:
        group = "archived"
    elif withdrawn:
        group = "rest"
    elif doc["kind"] == "original" or work:
        group = "prepare"
    else:
        group = "other"
    return {
        "group": group,
        "change": change,
        "work": work,
        "withdrawn": withdrawn,
        "live_revision": live_revision,
        "selected_revision": selected_revision,
        "current_revision": doc["current_revision"],
        "confirmed": doc["state"] == "confirmed",
    }


def structure_snapshot(state, anchor, nodes, edges):
    """The genealogy structure that confirming `anchor` would approve.

    The confirmed component as it stands now, with each node's month date and the whole
    record of each edge, in a fixed order so that two snapshots compare by fingerprint."""
    records = {edge["id"]: edge for edge in state["edges"]}
    return {
        "anchor": anchor,
        "nodes": [{"document": i, "date": month_date(state["documents"][i])} for i in sorted(nodes)],
        "edges": [{k: copy.deepcopy(records[i][k]) for k in EDGE_FIELDS} for i in sorted(edges)],
    }


def reviewed_series(series, **changes):
    # Editing on the author's screen is the review of this exact series metadata.
    value = copy.deepcopy(series)
    value.pop("reviewed_fingerprint", None)
    value.update(copy.deepcopy(changes))
    value["reviewed_fingerprint"] = fingerprint(value)
    return value


EMPTY_PUBLIC = {"documents": [], "genealogies": [], "series": []}
PUBLIC_TIMES = {"first_published_at", "published_updated_at"}


def public_changes(before, after, language="ko"):
    """Describe what replacing one public output with another changes for readers.

    Publication times are ignored because every release restamps them. Changed parts
    are returned as keys (e.g. `en.body`, `genealogy`); the screen words them. Things
    are named in `language`, the one the author writes in.
    """
    old, new = ({d["id"]: d for d in p["documents"]} for p in (before, after))
    old_graph, new_graph = ({g["document"]: g for g in p["genealogies"]} for p in (before, after))
    documents = []
    for pid in list(new) + [p for p in old if p not in new]:
        a, b = old.get(pid), new.get(pid)
        title = (b or a)["translations"][language]["title"]
        if a is None or b is None:
            documents.append({"id": pid, "title": title, "change": "new" if a is None else "withdraw", "parts": []})
            continue
        parts = [
            lang + "." + field
            for lang in LANGUAGES
            for field in ("title", "summary", "body")
            if a["translations"][lang][field] != b["translations"][lang][field]
        ]
        parts += [
            key
            for key in sorted(set(a) | set(b))
            if key not in PUBLIC_TIMES | {"id", "translations"} and a.get(key) != b.get(key)
        ]
        if old_graph.get(pid) != new_graph.get(pid):
            parts.append("genealogy")
        if parts:
            documents.append({"id": pid, "title": title, "change": "update", "parts": parts})
    old_series, new_series = ({s["id"]: s for s in p["series"]} for p in (before, after))
    series = []
    for sid in list(new_series) + [s for s in old_series if s not in new_series]:
        a, b = old_series.get(sid), new_series.get(sid)
        title = (b or a)["translations"][language]["title"]
        if a is None or b is None:
            series.append({"id": sid, "title": title, "change": "new" if a is None else "removed", "parts": []})
        elif a != b:
            parts = [key for key in sorted(set(a) | set(b)) if key != "id" and a.get(key) != b.get(key)]
            series.append({"id": sid, "title": title, "change": "update", "parts": parts})
    kept = [s for s in old_series if s in new_series]
    order = kept != [s for s in new_series if s in old_series]
    return {
        "documents": documents,
        "series": series,
        "series_order": order,
        "empty": not documents and not series and not order,
    }


def decisions(
    state,
    before,
    after,
    before_selections,
    after_selections,
    before_structures,
    after_structures,
    before_files=None,
    after_files=None,
    language="ko",
    label_languages=None,
):
    """Group a public diff by the author's decisions for the site screen.

    One row per post decided on (its text, series membership, genealogy structure and
    wording), shared wording edits no changed post explains, and site-level series
    settings. Consequences such as a series vanishing with its last post or another
    post's genealogy picture changing are attached to the post that caused them: a
    publication change for published/withdrawn nodes, the anchor of a changed structure
    approval for added or removed links. Given the deployed file hashes on both sides,
    a changed stylesheet, script, font or 404 page becomes a 'skin' row, and 'empty' means
    the site files are identical too (a skin-only change is still a change). Series are
    named in `language`, the one the author writes in; each piece of genealogy wording in
    its own, which `label_languages(kind, target)` answers.
    """
    ids = state["blog"]["identities"]
    local = {v["id"]: k for k, v in ids["documents"].items()}
    local_label = {
        "question": {v: k for k, v in ids["questions"].items()},
        "edge": {v: k for k, v in ids["edges"].items()},
    }
    title = lambda pid: state["documents"][local[pid]]["title"] if pid in local else pid
    raw = public_changes(before, after, language)
    rows = {}

    def revision(selections, did):
        pair = selections.get(did) if did else None
        return state["documents"][did]["publication_pairs"][pair]["base_revision"] if pair else None

    def row(pid, change="update"):
        if pid not in rows:
            did = local.get(pid)
            rows[pid] = {
                "document": did,
                "title": title(pid),
                "change": change,
                "before": revision(before_selections, did),
                "after": revision(after_selections, did),
                "text": [],
                "series": [],
                "labels": [],
                "effects": [],
            }
        return rows[pid]

    for item in raw["documents"]:
        parts = [p for p in item["parts"] if p != "genealogy"]
        if item["change"] != "update" or parts:
            row(item["id"], item["change"])["text"] = parts

    # Genealogy pictures change when a connected post is published or withdrawn, or when
    # a post's confirmation approved a different structure (its anchor decided that).
    public_id = lambda did: ids["documents"][did]["id"] if did in ids["documents"] else None
    approved = lambda structures: {a["anchor"]: a["fingerprint"] for a in structures}
    was_approved, now_approved = approved(before_structures), approved(after_structures)
    members = {}
    for a in before_structures + after_structures:
        members.setdefault(public_id(a["anchor"]), set()).update(public_id(n["document"]) for n in a["nodes"])
    anchors = {
        public_id(d) for d in set(was_approved) | set(now_approved) if was_approved.get(d) != now_approved.get(d)
    } - {None}
    old_graph, new_graph = ({g["document"]: g for g in p["genealogies"]} for p in (before, after))
    born, moved, touched = set(), set(), {}

    def touch(cause, pid):
        if cause == pid:
            if "graph" not in row(pid)["text"]:
                row(pid)["text"].append("graph")
        else:
            touched.setdefault(cause, set()).add(pid)

    for pid in set(old_graph) | set(new_graph):
        a, b = old_graph.get(pid), new_graph.get(pid)
        if a is None or b is None:
            born.add(pid)
            continue
        was, now = ({n["id"]: n["kind"] for n in g["nodes"]} for g in (a, b))
        published = [
            n
            for n in set(was) | set(now)
            if was.get(n) != now.get(n)
            and (n in was and n in now or rows.get(n, {}).get("change") in ("new", "withdraw"))
        ]
        links = lambda g: sorted((e["id"], e["parent"], e["child"]) for e in g["edges"])
        if published:
            moved.add(pid)
        for cause in published:
            if cause in rows:
                touch(cause, pid)
        if set(was) ^ set(now) - set(published) or not published and links(a) != links(b):
            owners = [x for x in anchors if x == pid or pid in members.get(x, ())] or [pid]
            for owner in owners:
                touch(owner, pid)
    for cause, affected in touched.items():
        if cause in rows or cause in anchors:
            owner = row(cause)
            if cause in anchors and "graph" not in owner["text"] and owner["change"] == "update":
                owner["text"].append("graph")
            owner["effects"].append({"kind": "genealogy", "titles": sorted(title(p) for p in affected)})

    # Series membership belongs to the post; names, summaries and order to the site.
    old_series, new_series = ({x["id"]: x for x in p["series"]} for p in (before, after))
    site = []
    for sid in list(new_series) + [x for x in old_series if x not in new_series]:
        a, b = old_series.get(sid), new_series.get(sid)
        name = (b or a)["translations"][language]["title"]
        was, now = (a["documents"] if a else []), (b["documents"] if b else [])
        for pid in now:
            if pid not in was:
                row(pid)["series"].append({"change": "added", "title": name})
        for pid in was:
            if pid not in now and rows.get(pid, {}).get("change") != "withdraw":
                row(pid)["series"].append({"change": "removed", "title": name})
        if a is None or b is None:
            owners = [p for p in (now if a is None else was) if p in rows]
            for pid in owners:
                rows[pid]["effects"].append(
                    {"kind": "series-appears" if a is None else "series-vanishes", "title": name}
                )
            if not owners:
                site.append(
                    {"kind": "series", "id": sid, "title": name, "parts": ["appears" if a is None else "vanishes"]}
                )
            continue
        parts = [k for k in ("translations", "slug") if a.get(k) != b.get(k)]
        order = ([p for p in was if p in now], [p for p in now if p in was])
        if order[0] != order[1]:
            parts.append("order")
        if parts:
            site.append(
                {
                    "kind": "series",
                    "id": sid,
                    "title": name,
                    "parts": parts,
                    "before": a["translations"],
                    "after": b["translations"],
                    "order": [[title(p) for p in order[0]], [title(p) for p in order[1]]],
                }
            )
    kept = ([x for x in old_series if x in new_series], [x for x in new_series if x in old_series])
    if kept[0] != kept[1]:
        names = lambda order, table: [table[x]["translations"][language]["title"] for x in order]
        site.append({"kind": "home-order", "before": names(kept[0], old_series), "after": names(kept[1], new_series)})

    # Wording is found at (genealogy, link) spots. It appearing or vanishing is a consequence
    # when every spot is a born genealogy, a link that itself came or went, or (for a change
    # note, which needs both ends published) a genealogy whose publication changed.
    def wording(public):
        found = {}
        for g in public["genealogies"]:
            for e in g["edges"]:
                if e["change_note"]:
                    found.setdefault(("edge", e["id"]), [e["change_note"], set()])[1].add((g["document"], e["id"]))
                for q in e["questions"]:
                    found.setdefault(("question", q["id"]), [q["translations"], set()])[1].add((g["document"], e["id"]))
        return found

    old_links, new_links = (
        {pid: {e["id"] for e in g["edges"]} for pid, g in graphs.items()} for graphs in (old_graph, new_graph)
    )
    explained = lambda key, spots, other: all(
        pid in born or eid not in other.get(pid, ()) or key[0] == "edge" and pid in moved for pid, eid in spots
    )
    old_words, new_words = wording(before), wording(after)
    loose = []
    for key in list(new_words) + [k for k in old_words if k not in new_words]:
        a, b = old_words.get(key), new_words.get(key)
        if a and b and a[0] == b[0]:
            continue
        if a is None and explained(key, b[1], old_links) or b is None and explained(key, a[1], new_links):
            continue
        where = {pid for pid, _ in (a[1] if a else set()) | (b[1] if b else set())}
        kind, pid = key
        target = local_label[kind].get(pid)
        written = label_languages(kind, target) if target and label_languages else language
        edit = {
            "kind": kind,
            "target": target,
            # The wording as written, and which side of it readers get as the translation.
            "original": (b or a)[0].get(written, ""),
            "language": other(written),
            "before": a[0] if a else None,
            "after": b[0] if b else None,
            "titles": sorted(title(p) for p in where),
        }
        owners = [rows[p] for p in where if p in rows]
        for owner in owners:
            owner["labels"].append(edit)
        if not owners:
            loose.append(edit)
    files = set(before_files or ()) | set(after_files or ())
    changed = {p for p in files if (before_files or {}).get(p) != (after_files or {}).get(p)}
    skin = sorted(p for p in changed if not p.endswith(".html") or p == "404.html")
    if before_files and skin:
        site.append({"kind": "skin", "files": skin})
    empty = raw["empty"] and not changed
    count = len(rows) + len(loose) + len(site)
    if not empty and not count:
        # Nothing here is attributable to a post, a label or a series. A root that has
        # never been deployed is the ordinary reason, and saying "something differs"
        # about a first deployment reads as a fault when it is just the starting state.
        site.append({"kind": "first" if not before_files else "other"})
        count = 1
    return {"posts": list(rows.values()), "labels": loose, "site": site, "empty": empty, "count": count}


class Admin:
    # The current screen sends exactly these; anything else is refused, never reinterpreted.
    PREVIEW_FIELDS = {"document", "revision", "token", "text", "planned_at", "labels", "series"}
    PREVIEW_REQUIRED = {"document", "revision", "token", "text", "planned_at"}

    def __init__(self, root, read_only=False):
        self.studio = Studio(root)
        self.root = Path(root).resolve()
        self.read_only = read_only
        self.previews = {}
        self.import_plans = {}
        self.release_previews = {}
        # The interface language of the request being served; the server sets it.
        self.language = FALLBACK

    def state(self):
        return self.studio.load(auto_sync=False)

    def check(self, state, token):
        if token != fingerprint(state):
            raise Conflict(Message("error.admin.stale"))

    def catalog(self, query="", status="all"):
        # Without a query the list keeps to posts with a publishing role: written in the
        # editor or already touched by publishing. Other archive imports are search-only.
        state = self.state()
        result = []
        words = query.casefold().split()
        drafts = self.draft_ids()
        live = self.live_selections(state)
        for did, doc in state["documents"].items():
            selected = doc["publication"]["selected_pair"]
            label = "selected" if selected else ("draft" if did in drafts else "private")
            if status != "all" and status != label:
                continue
            site = self.site(state, did, live, drafts)
            if site["group"] == "archived" or status == "all" and not words and site["group"] == "other":
                continue
            if words:
                revision = next(r for r in doc["revisions"] if r["id"] == doc["current_revision"])
                text = (doc["title"] + "\n" + self.studio.repository.read_text(revision["path"])).casefold()
                if not all(w in text for w in words):
                    continue
            result.append(
                {
                    "id": did,
                    "title": doc["title"],
                    "state": doc["state"],
                    "status": label,
                    "kind": doc["kind"],
                    "group": site["group"],
                    "site": site,
                    "revision": doc["current_revision"],
                    "archived": doc["archived"],
                    "created_at": doc.get("created_at") or (doc.get("source") or {}).get("date") or "",
                }
            )
        result.sort(key=lambda d: (chronology_key(state["documents"][d["id"]]), d["id"]), reverse=True)
        result.sort(key=lambda d: (d["archived"], not d["id"].startswith("studio-")))
        return {
            "documents": result,
            "token": fingerprint(state),
            "read_only": self.read_only,
            "series": [state["blog"]["series"][sid] for sid in state["blog"]["series_order"]],
            "deployment": state["blog"]["active_release"],
            "site_url": self.site_url(state),
            "site_changes": self.site_changes(state),
            "pending_deployment": any(a["status"] == "running" for a in state["blog"]["release_attempts"]),
            # The newest frozen release, so any screen can offer to read it. A release
            # waiting to be sent is the one worth looking at; otherwise it is the live one.
            "latest_release": self.latest_release(state),
        }

    def latest_release(self, state):
        blog = state["blog"]
        sent = {a["release"] for a in blog["release_attempts"] if a["status"] == "succeeded"}
        waiting = [rid for rid in blog["releases"] if rid not in sent]
        return waiting[-1] if waiting else blog["active_release"]

    def site_changes(self, state):
        # Rows of the site screen: one per decided post, loose wording edit or site setting.
        changes = self.local_changes(state)
        return changes["count"] if changes else None

    def local_changes(self, state):
        active = state["blog"]["active_release"]
        try:
            return self.describe(
                state,
                self.public_output(state, active) if active else EMPTY_PUBLIC,
                self.public_output(state),
                state["blog"]["releases"][active] if active else False,
            )
        except (ModelError, ValueError, KeyError):
            return None

    def live_selections(self, state):
        active = state["blog"]["releases"].get(state["blog"]["active_release"])
        return active["selections"] if active else {}

    def draft_ids(self):
        folder = self.studio.path("data/blog-workspaces")
        return {p.stem for p in folder.glob("*.json")} if folder.is_dir() else set()

    def site(self, state, did, live, drafts):
        blog = state["blog"]
        published = any(
            did in blog["releases"][a["release"]]["selections"]
            for a in blog["release_attempts"]
            if a["status"] == "succeeded"
        )
        return site_status(
            state["documents"][did],
            live.get(did),
            self.draft(did) if did in drafts else None,
            self.studio.repository.read_text,
            published,
        )

    def site_url(self, state):
        active = state["blog"]["releases"].get(state["blog"]["active_release"])
        return self.destination_url(active)

    @staticmethod
    def destination_url(release):
        """Where readers find a delivered release, or None when only the author knows."""
        if not release:
            return None
        destination = release["destination"]
        if destination.get("mode") == "homepage-pr":
            return "https://" + destination["repository"].split("/")[1] + release["base"]
        # A folder is copied wherever its author chooses, so the public address is theirs to give.
        return destination.get("site_url") or None

    def draft_path(self, did):
        identifier(did)
        return self.studio.path("data/blog-workspaces/" + did + ".json")

    def draft(self, did):
        try:
            return json.loads(self.draft_path(did).read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None

    def detail(self, did, revision=None):
        state = self.state()
        doc = state["documents"][did]
        revision = revision or doc["current_revision"]
        ref = next(r for r in doc["revisions"] if r["id"] == revision)
        variants = []
        for value in doc["language_variants"].values():
            v = copy.deepcopy(value)
            v["text"] = self.studio.repository.read_text(v["body"]["path"])
            v["reviewed"] = v["id"] in doc["variant_reviews"]
            v["fingerprint"] = fingerprint(value)
            variants.append(v)
        component = (
            to_genealogy(state).connected_components([did])[0]
            if doc["state"] == "confirmed"
            else {"nodes": [], "edges": []}
        )
        nodes = [
            {
                "id": i,
                "title": state["documents"][i]["title"],
                "month": month_date(state["documents"][i])["value"],
                "selected": state["documents"][i]["publication"]["selected_pair"] is not None,
            }
            for i in component["nodes"]
        ]
        ids = {n["id"] for n in nodes}
        edges = [e for e in state["edges"] if e["state"] == "confirmed" and e["parent"] in ids and e["child"] in ids]
        public_url = None
        active = state["blog"]["releases"].get(state["blog"]["active_release"])
        identity = state["blog"]["identities"]["documents"].get(did)
        site = self.destination_url(active)
        language = self.document_language(state, did)
        labels = self.label_languages(state, language or self.writing_language(state) or "ko")
        if active and did in active["selections"] and identity and site:
            public_url = site + (language or "ko") + "/posts/" + identity["slug"] + "/"
        body = self.studio.repository.read_text(ref["path"])
        attachments = referenced_attachments(state, doc, body)
        # A new base revision is translated against the confirmed one, so the screen shows what moved.
        selected = doc["publication"]["selected_pair"]
        base = doc["publication_pairs"][selected]["base_revision"] if selected else None
        compare = None
        if base and base != revision:
            compare = {
                "revision": base,
                "body": self.studio.repository.read_text(next(r for r in doc["revisions"] if r["id"] == base)["path"]),
            }
        approvals = state["blog"]["structure_approvals"]
        chosen = [approvals[i] for i in state["blog"]["selected_structure_approvals"] if approvals[i]["anchor"] == did]
        # Confirming approves the component as it stands, so a post whose genealogy moved since
        # its last confirmation has something to review even when every text is unchanged.
        snapshot = (
            structure_snapshot(state, did, ids, [e["id"] for e in edges]) if doc["state"] == "confirmed" else None
        )
        structure_changed = snapshot is not None and (not chosen or chosen[0]["fingerprint"] != fingerprint(snapshot))
        return {
            "id": did,
            "title": doc["title"],
            "kind": doc["kind"],
            "archived": doc["archived"],
            "state": doc["state"],
            "revision": revision,
            "current_revision": doc["current_revision"],
            "revisions": [r["id"] for r in doc["revisions"]],
            # Which side is the revision itself and which the translation; None until the
            # author has said which language they write in.
            "language": language,
            "translation": other(language) if language else None,
            "body": self.studio.repository.read_text(ref["path"]),
            "token": fingerprint(state),
            "draft": self.draft(did),
            "variants": variants,
            "pairs": doc["publication_pairs"],
            "selected_pair": doc["publication"]["selected_pair"],
            "published": bool(
                state["blog"]["active_release"]
                and did in state["blog"]["releases"][state["blog"]["active_release"]]["selections"]
            ),
            "slug": state["blog"]["identities"]["documents"].get(did, {}).get("slug", ""),
            "nodes": nodes,
            "edges": edges,
            "attachments": attachments,
            "missing_assets": (doc.get("source") or {}).get("missing_assets", []),
            "labels": {"question": state["blog"]["question_labels"], "edge": state["blog"]["edge_labels"]},
            "questions": {q: state["questions"][q]["text"] for e in edges for q in e["questions"]},
            # Each piece of wording's own language, which may not be this post's.
            "label_languages": {
                "question": {q: labels("question", q) for e in edges for q in e["questions"]},
                "edge": {e["id"]: labels("edge", e["id"]) for e in edges},
            },
            "public_questions": sorted({q for e in edges for q in e["questions"] if state["questions"][q]["public"]}),
            "selected_structures": chosen,
            "structure_changed": structure_changed,
            "series": [
                sid for sid in state["blog"]["series_order"] if did in state["blog"]["series"][sid]["documents"]
            ],
            "public_url": public_url,
            "date": document_date(doc),
            "read_only": self.read_only,
            "live_pair": self.live_selections(state).get(did),
            "compare": compare,
            "site_row": next(
                (r for r in (self.local_changes(state) or {"posts": []})["posts"] if r["document"] == did), None
            ),
            "site": self.site(state, did, self.live_selections(state), self.draft_ids()),
        }

    def writing_language(self, state):
        """The language the author writes in, or None while nothing has settled it.

        The blog settings say it once chosen. Before that, a root whose posts were all
        published from one language is taken to write in it, which is every root made
        before the choice existed. A root with neither has to be asked: the answer is
        written into immutable variants, so it is never guessed.
        """
        chosen = load_site(self.root)["language"]
        if chosen:
            return chosen
        written = {
            v["language"]
            for doc in state["documents"].values()
            for v in doc["language_variants"].values()
            if v["body"]["kind"] == "base_revision"
        }
        return written.pop() if len(written) == 1 else None

    def document_language(self, state, did):
        """The language `did` is written in; see `base_language`."""
        return base_language(state["documents"][did], self.draft(did), self.writing_language(state))

    def translation_language(self, state, did):
        """The language a translation of `did` is written in, refusing while that is unknown."""
        base = self.document_language(state, did)
        if base is None:
            raise ValueError(Message("error.admin.writing_language"))
        return other(base)

    @staticmethod
    def check_text(data, translation):
        # The translated side carries a body; the original's is its revision.
        for lang in LANGUAGES:
            fields = {"title", "summary"} | ({"body"} if lang == translation else set())
            if (
                not isinstance(data.get(lang), dict)
                or set(data[lang]) != fields
                or not all(isinstance(v, str) for v in data[lang].values())
            ):
                raise ValueError(Message("error.admin.text_shape"))

    def save_draft(self, request):
        state = self.state()
        self.check(state, request["token"])
        did = request["document"]
        doc = state["documents"][did]
        data = request["draft"]
        if set(data) != {"revision", *LANGUAGES}:
            raise ValueError(Message("error.admin.draft_shape"))
        if data["revision"] not in [r["id"] for r in doc["revisions"]]:
            raise ValueError(Message("error.admin.unknown_revision"))
        self.check_text(data, self.translation_language(state, did))
        previous = self.draft(did)
        if request["version"] != (previous["version"] if previous else 0):
            raise Conflict(Message("error.admin.draft_changed"))
        return self.write_draft(did, data)

    def write_draft(self, did, data):
        previous = self.draft(did)
        value = dict(copy.deepcopy(data), document=did, version=(previous["version"] if previous else 0) + 1)
        path = self.draft_path(did)
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(".json.tmp")
        temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temp.replace(path)
        return value

    def matching_variant(self, doc, revision, lang, title, summary, body):
        # The newest stored expression with identical text is reused instead of a duplicate.
        # No body means the revision's own, so only a variant that reuses it can match.
        kind = "base_revision" if body is None else "translation"
        for v in reversed(list(doc["language_variants"].values())):
            if (v["base_revision"], v["language"], v["title"], v["summary"]) != (revision, lang, title, summary):
                continue
            if v["body"]["kind"] != kind:
                continue
            if body is None or self.studio.repository.read_text(v["body"]["path"]) == body:
                return v["id"]
        return None

    def preview(self, request):
        if not set(request) <= self.PREVIEW_FIELDS:
            raise ValueError(Message("error.admin.preview_fields"))
        if not self.PREVIEW_REQUIRED <= set(request):
            raise ValueError(Message("error.admin.preview_missing"))
        state = self.state()
        self.check(state, request["token"])
        original = fingerprint(state)
        did = request["document"]
        revision = request["revision"]
        translation = self.translation_language(state, did)
        self.check_text(request["text"], translation)
        # domain.set_publication holds this rule for every interface; refusing here too
        # keeps the author from staging a whole preview that selection would then reject.
        if state["documents"][did]["archived"] and not (
            state["documents"][did]["publication"]["selected_pair"] or did in self.live_selections(state)
        ):
            raise ValueError(Message("error.publish_archived"))
        overlay = Overlay(self.studio.repository, state)
        app = Studio(repository=overlay)
        key = uuid.uuid4().hex
        # Everything below is staged in the overlay. Applying this preview is the author's
        # confirmation, so it also records the review of the exact expressions shown here.
        variants = {}
        for lang in LANGUAGES:
            value = request["text"][lang]
            body = value["body"] if lang == translation else None
            summary = value["summary"] or None
            vid = self.matching_variant(state["documents"][did], revision, lang, value["title"], summary, body)
            if vid is None:
                vid = lang + "-" + key
                state = app.save_variant(state, did, vid, revision, lang, value["title"], body, summary)
            state = app.review_variant(state, did, vid, fingerprint(state["documents"][did]["language_variants"][vid]))
            variants[lang] = vid
        doc = state["documents"][did]
        attachments = []
        available = {a["path"]: a for a in self.detail(did, request["revision"])["attachments"]}
        for path in available:
            a = available[path]
            data = overlay.read_bytes(path)
            if hashlib.sha256(data).hexdigest() != a["sha256"]:
                raise Conflict(Message("error.admin.attachment_changed"))
            attachments.append(
                {
                    "id": a.get("id", uuid.uuid4().hex),
                    "path": path,
                    "sha256": a["sha256"],
                    "media_type": a["media_type"],
                }
            )
        pair = {"base_revision": revision, "variants": variants, "attachments": attachments}
        assets_of = lambda p: sorted((a["path"], a["sha256"]) for a in p["attachments"])
        # Same text reuses its pair (and attachment IDs), so a series-only change adds no pair.
        same = [
            pid
            for pid, p in doc["publication_pairs"].items()
            if (p["base_revision"], p["variants"], assets_of(p)) == (revision, variants, assets_of(pair))
        ]
        selected = doc["publication"]["selected_pair"]
        pair_id = selected if selected in same else same[-1] if same else "pair-" + key
        if not same:
            state = app.approve_pair(
                state, did, pair_id, revision, variants, fingerprint(pair_input(doc, pair)), attachments
            )
        if pair_id != selected:
            state = app.select_publication(state, did, pair_id)
        component = self.detail(did, revision)
        # The confirmed component is the approved structure; the screen offers no manual subset.
        selected_nodes = [n["id"] for n in component["nodes"]]
        selected_edges = [e["id"] for e in component["edges"]]
        if did not in selected_nodes:
            raise ValueError(Message("error.admin.anchor_missing"))
        edges = {edge["id"]: edge for edge in state["edges"]}
        snapshot = structure_snapshot(state, did, selected_nodes, selected_edges)
        approval = next(
            (i for i, a in state["blog"]["structure_approvals"].items() if a["fingerprint"] == fingerprint(snapshot)),
            "structure-" + key,
        )
        state = app.approve_structure(state, approval, snapshot, fingerprint(snapshot))
        old = state["blog"]["structure_approvals"]
        choices = [i for i in state["blog"]["selected_structure_approvals"] if old[i]["anchor"] != did] + [approval]
        state = app.select_structures(state, choices)
        allowed_questions = {q for i in selected_edges for q in edges[i]["questions"]}
        for label in request.get("labels", []):
            if label["kind"] == "question" and label["target"] not in allowed_questions:
                raise ValueError(Message("error.admin.label_question"))
            if label["kind"] == "edge" and label["target"] not in selected_edges:
                raise ValueError(Message("error.admin.label_edge"))
            source = state["questions"][label["target"]] if label["kind"] == "question" else edges[label["target"]]
            # The wording as written must sit under its own language, whatever this post is
            # written in: the label is shared, and a wrong side would reach every post showing it.
            written = self.label_languages(state, other(translation))(label["kind"], label["target"])
            wording = source["text"] if label["kind"] == "question" else source["change_note"]
            if (
                not isinstance(label.get("translations"), dict)
                or not set(label["translations"]) <= set(LANGUAGES)
                or label["translations"].get(written) != wording
            ):
                raise ValueError(Message("error.admin.label_original"))
            existing = state["blog"][label["kind"] + "_labels"].get(label["target"])
            # The screen only translates; publicity stays the question's or relation's own flag.
            value = {
                "public": existing["public"] if existing else source["public"],
                "translations": label["translations"],
            }
            state = app.save_public_label(state, label["kind"], label["target"], value, fingerprint(value))
        existing = state["blog"]["identities"]["documents"].get(did)
        title = request["text"]["en"]["title"]
        slug = (
            re.sub(
                r"[^a-z0-9]+", "-", unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode().lower()
            ).strip("-")
            or "post"
        )
        used = {v["slug"] for v in state["blog"]["identities"]["documents"].values()}
        original_slug = slug
        suffix = 2
        while slug in used:
            slug = original_slug + "-" + str(suffix)
            suffix += 1
        slugs = None if existing else {did: slug}
        series_request = request.get("series")
        # Omitted/null keeps all document memberships across revisions. An explicit
        # choice replaces memberships only after the author applies this preview.
        if series_request is not None:
            if not isinstance(series_request, dict):
                raise ValueError(Message("error.admin.series_choice"))
            target = None
            if set(series_request) == {"existing"}:
                target = series_request["existing"]
                if target is not None and target not in state["blog"]["series"]:
                    raise ValueError(Message("error.admin.series_unknown"))
            elif set(series_request) == {"slug", "translations"}:
                target = uuid.uuid4().hex
                state = app.save_series(state, reviewed_series(series_request, id=target, public=True, documents=[did]))
            else:
                raise ValueError(Message("error.admin.series_choice"))
            for sid, previous in list(state["blog"]["series"].items()):
                members = previous["documents"]
                desired = (
                    members + ([did] if did not in members else [])
                    if sid == target
                    else [i for i in members if i != did]
                )
                if desired == members:
                    continue
                state = app.save_series(state, reviewed_series(previous, documents=desired))
        state = app.prepare_public_identities(state, slugs)
        base = "/preview/" + key + "/"
        bundle = prepare_input(app, state, request["planned_at"])
        files = static_files(
            bundle["public"],
            bundle["assets"],
            base=base,
            preview="로컬 검토 시안 · 미배포 / Local review preview",
            site=load_site(self.root),
        )
        slug = state["blog"]["identities"]["documents"][did]["slug"]
        self.previews[key] = {
            "overlay": overlay,
            "token": original,
            "document": did,
            "revision": revision,
            "files": files,
        }
        # Preview URLs are session-local; bound memory use without writing private artifacts.
        while len(self.previews) > 8:
            self.previews.pop(next(iter(self.previews)))
        return {
            "id": key,
            "url": base + "ko/posts/" + slug + "/",
            # The genealogy opens in the language the post is written in.
            "graph_url": base + other(translation) + "/posts/" + slug + "/genealogy/",
            "en_url": base + "en/posts/" + slug + "/",
            "token": original,
        }

    def apply_preview(self, request):
        review = self.previews.get(request["preview"])
        if review is None:
            raise Conflict(Message("error.admin.preview_expired"))
        current = self.state()
        self.check(current, review["token"])
        self.check(current, request["token"])
        review["overlay"].commit()
        result = self.detail(review["document"], review["revision"])
        self.previews.clear()
        return result

    def unselect(self, request):
        state = self.state()
        self.check(state, request["token"])
        self.studio.select_publication(state, request["document"], None)
        self.previews.clear()
        return self.detail(request["document"], request["revision"])

    def release_status(self, rollback=None):
        from .homepage import Homepage
        from .local_folder import LocalFolder

        home = Homepage(self.root)
        folder = LocalFolder(self.root)
        result = home.status()
        state = self.state()
        blog = state["blog"]
        active_id = blog["active_release"]
        active = blog["releases"].get(active_id, {})
        selected = {
            did: d["publication"]["selected_pair"]
            for did, d in state["documents"].items()
            if d["publication"]["selected_pair"]
        }
        result["selected"] = [state["documents"][did]["title"] for did in selected]
        result["selected_posts"] = [{"id": did, "title": state["documents"][did]["title"]} for did in selected]
        result["withdrawn"] = [
            state["documents"][did]["title"] for did in active.get("selections", {}) if did not in selected
        ]
        result["homepage"] = home.configuration()
        result["local_folder"] = folder.configuration()
        # One destination at a time; the screen shows whichever the author chose.
        result["destination"] = (
            {"mode": "local-folder", **result["local_folder"]}
            if result["local_folder"]
            else {"mode": "homepage-pr", **result["homepage"]}
            if result["homepage"]
            else None
        )
        result["pull_requests"] = {}
        for release in result["releases"]:
            # Preserved records from the removed dedicated-repository mode stay readable.
            if release["destination"].get("mode") != "homepage-pr":
                continue
            try:
                record = home.record(release)
            except (ModelError, ValueError, OSError, RuntimeError):
                # Reading a checkout-local receipt revalidates that checkout and its origin.
                # An old release's checkout may be gone, moved or no longer a repository;
                # that costs this screen one history detail, not the whole response. Only an
                # operation that actually touches the checkout may insist on finding it.
                continue
            if record:
                result["pull_requests"][release["id"]] = record
        # Every comparison is against what readers see now: the active release's frozen output.
        live = self.public_output(state, active_id) if active_id else EMPTY_PUBLIC
        live_release = active or False
        try:
            local = self.public_output(state)
            result["changes"] = self.describe(state, live, local, live_release)
        except (ModelError, ValueError, KeyError) as error:
            local = None
            result["changes"] = None
            result["changes_error"] = carried(error) or Message("error.admin.no_output")
        running = next((a for a in blog["release_attempts"] if a["status"] == "running"), None)
        latest = list(blog["releases"].values())[-1] if blog["releases"] else None
        waiting = (
            blog["releases"][running["release"]]
            if running
            else latest
            if latest and latest["id"] != active_id and latest["parent_release"] == active_id
            else None
        )
        if waiting:
            frozen = self.public_output(state, waiting["id"])
            last = [a for a in blog["release_attempts"] if a["release"] == waiting["id"]]
            # A frozen release names the destination it was made for, and deployment sends
            # it there whatever this screen now says. Offering it again after the
            # destination moved would write to the old one under the new one's name, so a
            # release frozen elsewhere is neither current nor deployable from here.
            here = waiting["destination"] == self.deployment_target()
            result["pending"] = {
                "release": waiting["id"],
                "running": running is not None,
                "status": last[-1]["status"] if last else None,
                "error": last[-1]["error"] if last else None,
                "deployable": here and waiting["destination"].get("mode") in ("homepage-pr", "local-folder"),
                "changes": self.describe(state, live, frozen, live_release, waiting),
                "current": here
                and local is not None
                and self.local_render(state, waiting["planned_published_at"])["files"] == waiting["files"],
                "next": self.describe(state, frozen, local, waiting) if local is not None else None,
            }
        if rollback:
            old = blog["releases"][rollback]
            result["rollback"] = {
                "release": rollback,
                "changes": self.describe(state, live, self.public_output(state, rollback), live_release, old),
            }
        result["series"] = [
            {
                "id": sid,
                "translations": s["translations"],
                "public": s["public"],
                "documents": [
                    {"id": did, "title": state["documents"][did]["title"], "selected": did in selected}
                    for did in s["documents"]
                ],
            }
            for sid in blog["series_order"]
            for s in [blog["series"][sid]]
        ]
        # Nothing changed and this destination already has it are separate facts: a folder
        # chosen today is empty however familiar the writing has become. The screen has to
        # know the difference, or it offers no way to reach a destination that is waiting
        # for a site the model is perfectly willing to send.
        result["destination_missing_site"] = bool(active_id) and not self.destination_holds_site(state)
        result["site_url"] = self.site_url(state)
        return result

    def destination_holds_site(self, state):
        """Whether the destination configured now is the one the live release went to."""
        active = state["blog"]["active_release"]
        return bool(active) and self.deployment_target() == state["blog"]["releases"][active]["destination"]

    def public_output(self, state, release=None):
        """A stored release's frozen public JSON, or the prospective one from local selections."""
        if release:
            return json.loads(self.studio.repository.read_bytes(state["blog"]["releases"][release]["public_snapshot"]))
        return self.local_render(state)["public"]

    def deployment_target(self):
        """The destination a release would be sent to now, shaped as a release record stores it.

        Comparisons need this because content is only 'already deployed' with respect to one
        destination, and the base a site is rendered at is part of the destination too.
        """
        from .homepage import Homepage
        from .local_folder import LocalFolder

        return LocalFolder(self.root).configuration() or Homepage(self.root).configuration()

    def deployment_base(self):
        """The base a prospective render must use: whatever the configured destination serves at.

        Rendering at one base and comparing against a release frozen at another reports every
        page as changed, which made a no-op deployment look like a complete rewrite of the site.
        """
        target = self.deployment_target()
        # The pull-request path always publishes under /blog/; a folder carries its own base.
        return target.get("base", "/blog/") if target else "/blog/"

    def local_render(self, state, planned=None):
        """The prospective public JSON and the hashes of the files a release would deploy.

        Rendering is how skin changes (CSS, scripts, fonts, templates) become visible; results
        are kept for the same state and day, since only a changed post takes the planned date.
        The base belongs to that identity: the same writing deployed at a different base is a
        different set of bytes, so a cached render must not outlive a destination change.
        """
        explicit = planned is not None
        planned = planned or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        site = load_site(self.root)
        base = self.deployment_base()
        key = (fingerprint(state), planned if explicit else planned[:10], fingerprint(site), base)
        cached = getattr(self, "_rendered", None)
        if cached and cached[0] == key:
            return cached[1]
        bundle = prepare_input(self.studio, state, planned)
        files = static_files(bundle["public"], bundle["assets"], base=base, preview=False, site=site)
        files[".nojekyll"] = b""
        result = {"public": bundle["public"], "files": {p: hashlib.sha256(b).hexdigest() for p, b in files.items()}}
        self._rendered = (key, result)
        return result

    def describe(self, state, before, after, before_release, after_release=None):
        # A release (or None for local selections) supplies selections, structure approvals and files.
        side = lambda release: (
            (release["selections"], release["structure_approvals"], release["files"])
            if release
            else (
                {
                    d: doc["publication"]["selected_pair"]
                    for d, doc in state["documents"].items()
                    if doc["publication"]["selected_pair"]
                },
                [state["blog"]["structure_approvals"][a] for a in state["blog"]["selected_structure_approvals"]],
                self.local_render(state)["files"],
            )
        )
        (bs, bst, bf), (as_, ast, af) = (
            side(before_release) if before_release is not False else ({}, [], {}),
            side(after_release),
        )
        writing = self.writing_language(state) or "ko"
        return decisions(state, before, after, bs, as_, bst, ast, bf, af, writing, self.label_languages(state, writing))

    def label_languages(self, state, fallback):
        """`label_language` for this root, as a function of (kind, target)."""
        return lambda kind, target: label_language(
            state, kind, target, lambda did: self.document_language(state, did), fallback
        )

    def save_series(self, request):
        # Site-level metadata: names, summaries and reading order. Membership is edited per post.
        state = self.state()
        self.check(state, request["token"])
        previous = state["blog"]["series"][request["series"]]
        if sorted(request["documents"]) != sorted(previous["documents"]):
            raise ValueError(Message("error.admin.series_members"))
        if set(request["translations"]) != {"ko", "en"}:
            raise ValueError(Message("error.admin.series_names"))
        translations = {}
        for lang in ("ko", "en"):
            value = request["translations"][lang]
            if set(value) != {"title", "summary"} or not all(isinstance(v, str) for v in value.values()):
                raise ValueError(Message("error.admin.series_shape"))
            if not value["title"].strip():
                raise ValueError(Message("error.admin.series_names"))
            translations[lang] = {"title": value["title"].strip(), "summary": value["summary"].strip() or None}
        if (translations["ko"]["summary"] is None) != (translations["en"]["summary"] is None):
            raise ValueError(Message("error.admin.series_summaries"))
        self.studio.save_series(
            state, reviewed_series(previous, translations=translations, documents=list(request["documents"]))
        )
        return self.release_status()

    def revert(self, request):
        """Return one row of the site screen to what readers see now, the active release.

        A post gets back its live pair, structure approval, series memberships and the
        wording attributed to its row; its translation draft shows the live text (or none).
        Immutable variants and pairs stay recorded; the replaced draft is returned so the
        screen can offer a one-time browser recovery.
        """
        state = self.state()
        self.check(state, request["token"])
        blog = state["blog"]
        if any(a["status"] == "running" for a in blog["release_attempts"]):
            raise ValueError(Message("flow.deploy.hint.running"))
        changes = self.local_changes(state)
        if changes is None:
            raise ValueError(Message("error.admin.revert_no_output"))
        active = blog["releases"].get(blog["active_release"], {})
        live_selection = active.get("selections", {})
        live_series = {x["id"]: x for x in active.get("series_snapshot", [])}
        overlay = Overlay(self.studio.repository, state)
        app = Studio(repository=overlay)
        kind, target = request["kind"], request.get("target")
        draft = None
        if kind == "post":
            row = next((r for r in changes["posts"] if r["document"] == target), None)
            if row is None:
                raise ValueError(Message("error.admin.revert_post_same"))
            live = live_selection.get(target)
            if state["documents"][target]["publication"]["selected_pair"] != live:
                state = app.select_publication(state, target, live)
            approvals = state["blog"]["structure_approvals"]
            chosen = [a for a in state["blog"]["selected_structure_approvals"] if approvals[a]["anchor"] != target]
            chosen += [a["id"] for a in active.get("structure_approvals", []) if a["anchor"] == target]
            if chosen != state["blog"]["selected_structure_approvals"]:
                state = app.select_structures(state, chosen)
            for sid, series in list(state["blog"]["series"].items()):
                want = sid in live_series and target in live_series[sid]["documents"]
                if want == (target in series["documents"]):
                    continue
                members = [d for d in series["documents"] if d != target]
                if want:
                    members.insert(min(live_series[sid]["documents"].index(target), len(members)), target)
                state = app.save_series(state, reviewed_series(series, documents=members))
            for edit in row["labels"]:
                state = self.restore_label(app, state, edit)
            draft = self.live_text(state, target, live)
        elif kind == "label":
            edits = changes["labels"] + [e for r in changes["posts"] for e in r["labels"]]
            edit = next((e for e in edits if [e["kind"], e["target"]] == target), None)
            if edit is None:
                raise ValueError(Message("error.admin.revert_label_same"))
            state = self.restore_label(app, state, edit)
        elif kind == "series":
            if target not in live_series or not any(
                x["kind"] == "series" and x.get("id") == target for x in changes["site"]
            ):
                raise ValueError(Message("error.admin.revert_series_same"))
            live = live_series[target]
            current = state["blog"]["series"][target]
            order = [d for d in live["documents"] if d in current["documents"]] + [
                d for d in current["documents"] if d not in live["documents"]
            ]
            state = app.save_series(
                state,
                reviewed_series(
                    current,
                    translations=live["translations"],
                    slug=live["slug"],
                    public=live["public"],
                    documents=order,
                ),
            )
        elif kind == "home-order":
            live = [x for x in live_series if x in blog["series_order"]]
            state = app.order_series(state, live + [x for x in blog["series_order"] if x not in live])
        else:
            raise ValueError(Message("error.admin.revert_kind"))
        overlay.commit()
        discarded = None
        if draft is not None:
            previous = self.draft(target)
            if previous and {k: previous[k] for k in ("revision", "ko", "en")} != draft:
                discarded = previous
            self.write_draft(target, draft)
        result = self.release_status()
        if discarded:
            result["discarded"] = discarded
        return result

    def restore_label(self, app, state, edit):
        # Wording readers saw is restored exactly; wording they did not see is forgotten.
        # Neither touches the question's or relation's own publicity beyond what was live.
        if edit["target"] is None:
            raise ValueError(Message("error.admin.label_missing"))
        if not edit["before"]:
            return app.remove_public_label(state, edit["kind"], edit["target"])
        value = {"public": True, "translations": copy.deepcopy(edit["before"])}
        return app.save_public_label(state, edit["kind"], edit["target"], value, fingerprint(value))

    def live_text(self, state, did, live):
        # After a revert the translation form shows the live text, or nothing for an unpublished post.
        doc = state["documents"][did]
        revision = doc["current_revision"]
        if not live:
            base = self.document_language(state, did)
            if base is None:
                return None
            return {
                "revision": revision,
                base: {"title": doc["title"], "summary": ""},
                other(base): {"title": "", "summary": "", "body": ""},
            }
        v = {lang: doc["language_variants"][vid] for lang, vid in doc["publication_pairs"][live]["variants"].items()}
        text = {lang: {"title": x["title"], "summary": x["summary"] or ""} for lang, x in v.items()}
        translated = translated_side(v)
        if translated:
            text[translated]["body"] = self.studio.repository.read_text(v[translated]["body"]["path"])
        return {"revision": revision, **text}

    def order_series(self, request):
        state = self.state()
        self.check(state, request["token"])
        if sorted(request["order"]) != sorted(state["blog"]["series_order"]):
            raise ValueError(Message("error.admin.series_order"))
        self.studio.order_series(state, request["order"])
        return self.release_status()

    def import_links(self, body):
        """Find link targets with the real Markdown parser the reader's site uses.

        Targets come back as written. The parser percent-encodes non-ASCII ones,
        and ``folder_import`` decodes them when it resolves; decoding here too
        would decode twice and lose a literal % from a filename.
        """
        from .footnotes import footnotes
        from .vendor.mistune import create_markdown

        found = []

        def visit(tokens):
            for token in tokens:
                if token["type"] in ("image", "link"):
                    found.append(token["attrs"]["url"])
                visit(token.get("children", []))

        visit(create_markdown(renderer="ast", plugins=[footnotes])(body))
        return found

    def import_scan(self, request):
        """Read a folder and report what importing it would do. Writes nothing.

        The plan is kept so that applying writes the bytes that were reviewed, rather
        than whatever the folder holds by then. The identifier is what the screen
        confirms with; re-reading the folder at that point would defeat the review.
        """
        from stemma_studio.core.folder_import import scan

        folder = request.get("folder")
        if not isinstance(folder, str) or not folder.strip():
            raise ValueError(Message("error.admin.import_folder"))
        rule = request.get("rule") if request.get("rule") in ("path", "name") else "path"
        token = fingerprint(self.state())
        plan = scan(self.state(), folder.strip(), rule, self.import_links)
        key = uuid.uuid4().hex
        self.import_plans[key] = {"plan": plan, "token": token, "folder": folder.strip(), "rule": rule}
        # Session-local, like previews: bound memory without writing anything private.
        while len(self.import_plans) > 4:
            self.import_plans.pop(next(iter(self.import_plans)))
        return {**plan.report, "plan": key, "token": token, "status": "scanned"}

    def import_apply(self, request):
        """Import exactly what the reviewed plan described, leaving its problems alone."""
        from stemma_studio.core.folder_import import apply_import

        reviewed = self.import_plans.get(request.get("plan"))
        if reviewed is None:
            raise Conflict(Message("error.admin.import_expired"))
        # The screen sends what it believes it reviewed. Disagreement means the controls
        # moved on without a rescan, which is exactly the case this refuses to guess at.
        for field in ("folder", "rule"):
            given = request.get(field)
            if given is not None and str(given).strip() != reviewed[field]:
                raise Conflict(Message("error.admin.import_mismatch"))
        state = self.state()
        # Both the token the screen holds and the one the scan was made against, so a
        # workspace that moved on since the review cannot be written from a stale plan.
        self.check(state, reviewed["token"])
        self.check(state, request["token"])
        _, report = apply_import(self.studio.repository, reviewed["plan"])
        self.import_plans.clear()
        return {**report, "token": fingerprint(self.state())}

    def release_preview(self, rid):
        """Render a frozen release so it can be read here before it reaches anybody.

        A release carries its destination's base in every link, so its own bytes cannot
        resolve in this window. The public snapshot it was frozen from can, and that is
        the part that decides what a reader sees. Rendering that snapshot at a local base
        lets a pull request be judged before it is merged, and a folder before anyone
        trusts it — the same question in both cases, answered the same way.

        Rendering it at the release's own base has to reproduce the release byte for
        byte. When it does not, the skin has changed since the freeze and this is no
        longer what that release would publish, which the screen has to say rather than
        quietly showing today's design over yesterday's writing.
        """
        from stemma_studio.core.public_assets import asset_url

        from .deploy import sha

        cached = self.release_previews.get(rid)
        if cached:
            return cached
        state = self.state()
        release = state["blog"]["releases"][rid]
        raw = self.studio.repository.read_bytes(release["public_snapshot"])
        if hashlib.sha256(raw).hexdigest() != release["public_sha256"]:
            raise ValueError(Message("error.admin.release_mismatch"))
        public = json.loads(raw)
        assets = {asset_url(a): self.studio.repository.read_bytes(a["path"]) for a in release["assets"]}
        site = load_site(self.root)
        frozen = static_files(public, assets, base=release["base"], preview=False, site=site)
        frozen[".nojekyll"] = b""
        faithful = {path: sha(data) for path, data in frozen.items()} == release["files"]
        # The page says which of the two things it is, because the difference matters and
        # the reader of this preview is deciding something on the strength of it.
        files = static_files(
            public,
            assets,
            base="/release/" + rid + "/",
            preview=(
                "배포본 미리보기 · 아직 반영 전 / Frozen release preview"
                if faithful
                else "배포본 미리보기 · 이 배포본을 만든 뒤 사이트 설정이나 디자인이 바뀌었습니다"
                " / Preview rendered with a newer design than this release"
            ),
            site=site,
        )
        result = {"files": files, "faithful": faithful}
        self.release_previews = {rid: result}
        return result

    def release_service(self):
        """The configured delivery. A folder is generic; the pull-request path is one option."""
        from .homepage import Homepage
        from .local_folder import LocalFolder

        local = LocalFolder(self.root)
        return local if local.configuration() else Homepage(self.root)

    def configure_destination(self, request):
        """Store one destination, replacing whichever was configured before."""
        from .homepage import Homepage
        from .local_folder import LocalFolder

        local, homepage = LocalFolder(self.root), Homepage(self.root)
        if request.get("mode") == "local-folder":
            chosen, other = local, homepage
            chosen.configure(request["destination"], request.get("base", "/"))
        else:
            chosen, other = homepage, local
            chosen.configure(request["destination"], request.get("branch", "master"))
        # Exactly one destination at a time, so the service is never ambiguous.
        other.settings.unlink(missing_ok=True)
        return chosen

    def release_action(self, name, request):
        self.check(self.state(), request["token"])
        frozen = None
        if name == "release-configure":
            self.configure_destination(request)
            return self.release_status()
        service = self.release_service()
        if name == "release-freeze-home":
            state = self.state()
            active = state["blog"]["active_release"]
            rollback = request.get("rollback")
            live = state["blog"]["releases"][active]["files"] if active else {}
            target = state["blog"]["releases"][rollback]["files"] if rollback else self.local_render(state)["files"]
            # Unchanged content is a reason to refuse only where the bytes already are. A
            # newly chosen destination is empty however familiar the site itself has become,
            # so 'nothing changed' and 'this destination already has it' are separate facts.
            if target == live and self.destination_holds_site(state):
                raise ValueError(Message("error.admin.nothing_to_deploy"))
            frozen = service.freeze_configured(request["token"], rollback)["id"]
        elif name == "release-build":
            # Not every delivery builds; a folder is live the moment its bytes are verified.
            if not service.builds:
                raise ValueError(Message("error.admin.no_build"))
            service.build(request["release"])
        elif name == "release-deploy":
            service.start(request["release"])
        elif name == "release-check":
            service.check()
        elif name == "release-interrupt":
            service.interrupt()
        else:
            raise ValueError(Message("error.admin.release_action"))
        result = self.release_status()
        # The screen deploys the release it just froze without guessing from the history order.
        if frozen:
            result["frozen"] = frozen
        return result

    def site_settings(self):
        """The author's blog identity and the licence their writing carries."""
        from . import site_settings

        return {
            "settings": site_settings.load(self.root),
            # What the author is taken to write in, even before choosing, so the screen
            # can say whether the choice is theirs yet.
            "writing_language": self.writing_language(self.state()),
            "licenses": site_settings.choices(),
            "custom_id": site_settings.CUSTOM,
        }

    def save_site_settings(self, request):
        """Store the identity and licence chosen on the settings panel.

        These change every rendered page, so the site screen shows the result as
        a pending change like any other before it reaches readers.
        """
        from . import site_settings

        given = request.get("settings")
        if not isinstance(given, dict):
            raise ValueError(Message("error.admin.settings_missing"))
        site_settings.save(self.root, given)
        self._rendered = None
        return self.site_settings()

    def action(self, name, request):
        # Preview itself is safe in read-only mode; draft/metadata writes are disabled.
        if self.read_only and name != "preview":
            raise ValueError(Message("error.admin.read_only"))
        if name.startswith("release-"):
            return self.release_action(name, request)
        methods = {
            "draft": self.save_draft,
            "preview": self.preview,
            "select": self.apply_preview,
            "unselect": self.unselect,
            "series-save": self.save_series,
            "series-order": self.order_series,
            "revert": self.revert,
            "site-settings": self.save_site_settings,
            "import-scan": self.import_scan,
            "import-apply": self.import_apply,
        }
        return methods[name](request)
