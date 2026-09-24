"""Coordinate use cases across pure domain rules, persistence, and publication policy.

A future editor can call this layer rather than reproduce the rules in its UI.
The repository is replaceable; domain operations remain free of I/O."""

import copy
import uuid
from datetime import UTC, datetime

from . import blog, domain
from .publication import project_public
from .repository import FileRepository, reuse_or_create


class Studio:
    """Run document workflows against a file or injected repository implementation."""

    def __init__(self, root=None, repository=None):
        """Use an injected repository when provided; otherwise open the supplied file root."""
        domain._require(root is not None or repository is not None, "Choose a repository")
        self.repository = repository if repository is not None else FileRepository(root)
        self.last_sync_report = None

    @property
    def metadata(self):
        """Expose the file repository metadata path for legacy callers only.

        This compatibility property is not supported by MemoryRepository."""
        return self.repository.metadata

    def path(self, relative):
        # File-only convenience for existing callers; not part of the Repository contract.
        return self.repository.path(relative)

    def load(self, auto_sync=True):
        """Load cached data, then check the configured committed archive on use.

        No background agent runs. Offline/conflicting sources leave the cache usable;
        callers can inspect last_sync_report. The CLI surfaces these diagnostics.
        """
        state = self.repository.load()
        self.last_sync_report = None
        if auto_sync and state.get("archive", {}).get("auto_sync"):
            from .archive_sync import apply_sync, plan_sync

            try:
                state, self.last_sync_report = apply_sync(self.repository, plan_sync(state))
            except (domain.ModelError, OSError) as error:
                self.last_sync_report = {"status": "error", "message": str(error)}
        return state

    def sync_archive(self, archive=None, dry_run=False):
        """Explicitly inspect or apply additions from the source's committed HEAD."""
        from .archive_sync import apply_sync, plan_sync

        state = self.repository.load()
        plan = plan_sync(state, archive)
        if dry_run:
            self.last_sync_report = plan.report
            return state, plan.report
        state, self.last_sync_report = apply_sync(self.repository, plan)
        return state, self.last_sync_report

    def save(self, state):
        self.repository.save(state)

    def _revision(self, docid, rid, text, note):
        """Prepare a storage descriptor without writing the new body.

        The path naming convention belongs to Studio, not to the graph contract."""
        domain._require(bool(text.strip()) and bool(note.strip()), "Revision needs body and note")
        return {
            "id": rid,
            "path": "data/revisions/" + docid + "/" + rid + ".md",
            "sha256": domain.digest(text),
            "note": note,
        }

    def create_draft(self, state, docid, title, questions, text, parents, note):
        """Validate the proposed state before creating a snapshot and saving metadata.

        Snapshot creation and metadata replacement are separate writes, not one transaction.
        A failed save may leave an unreferenced snapshot; retrying the identical request
        reuses it, and existing snapshots are never replaced."""
        revision = self._revision(docid, "r1", text, note)
        result = domain.create_draft(state, docid, title, questions, revision, parents)
        # Write the immutable body before metadata can refer to it.
        reuse_or_create(self.repository, revision["path"], text)
        self.repository.save(result)
        return result

    def confirm(self, state, docid, archive_parents=()):
        """Confirm succession and optionally end selected parents' future use in one save."""
        result = domain.confirm(state, docid, archive_parents)
        self.repository.save(result)
        return result

    def set_archived(self, state, docid, archived=True):
        result = domain.set_archived(state, docid, archived)
        self.repository.save(result)
        return result

    def add_revision(self, state, docid, text, note, archive_parents=()):
        """Persist a new body under the next local revision ID after domain validation."""
        domain._require(docid in state["documents"], "Unknown document")
        rid = "r" + str(len(state["documents"][docid]["revisions"]) + 1)
        revision = self._revision(docid, rid, text, note)
        result = domain.add_revision(state, docid, revision)
        if archive_parents:
            domain._require(
                state["documents"][docid]["state"] == "confirmed",
                "Confirm a draft explicitly before revising and archiving parents",
            )
            result = domain.confirm(result, docid, archive_parents)
        # Write the immutable body before metadata can refer to it.
        reuse_or_create(self.repository, revision["path"], text)
        self.repository.save(result)
        return result

    def export_public(self, state, planned_published_at=None):
        """Return a prospective public payload without writing metadata or files."""
        return self.export_bundle(state, planned_published_at)["public"]

    def export_bundle(self, state, planned_published_at=None):
        """Supply the renderer only public JSON and verified, opaque-named assets."""
        from .public_assets import selected_assets

        domain.validate(state)
        bodies = {
            did: self.read_pair(state, did, doc["publication"]["selected_pair"])
            for did, doc in state["documents"].items()
            if doc["publication"]["selected_pair"] is not None
        }
        public = project_public(state, planned_published_at, bodies)
        return {"public": public, "assets": selected_assets(state, self.repository.read_bytes)}

    def _fresh_blog_state(self, state):
        """Reject stale local writes; this is not a concurrent-writer lock."""
        current = self.repository.load()
        domain._require(current == state, "Studio changed; reload before changing blog metadata")
        return current

    def save_variant(self, state, docid, variant_id, base_revision, language, title, body=None, summary=None):
        """Store a new expression; None references the exact existing base body.

        A caller-supplied variant ID is also its retry key. A matching saved request
        returns current state; different content under that ID is never replaced.
        """
        current = self.repository.load()
        domain._require(docid in current["documents"], "Unknown document")
        blog.identifier(variant_id)
        doc = current["documents"][docid]
        revision = next((r for r in doc["revisions"] if r["id"] == base_revision), None)
        domain._require(revision is not None, "Unknown variant base revision")
        if body is None:
            body = self.repository.read_text(revision["path"])
            descriptor = {"kind": "base_revision", "path": revision["path"], "sha256": revision["sha256"]}
        else:
            blog.text(body)
            descriptor = {
                "kind": "translation",
                "path": f"data/translations/{docid}/{variant_id}.md",
                "sha256": domain.digest(body),
            }
        blog.text(body)
        previous = doc["language_variants"].get(variant_id)
        variant = {
            "id": variant_id,
            "base_revision": base_revision,
            "language": language,
            "title": title,
            "summary": summary,
            "body": descriptor,
            "created_at": previous["created_at"] if previous else datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        if previous is not None:
            domain._require(previous == variant, "Immutable variant ID already exists with different content")
            return current
        self._fresh_blog_state(state)
        result = copy.deepcopy(state)
        result["documents"][docid]["language_variants"][variant_id] = variant
        domain.validate(result)
        # Reuse only identical orphan bytes after a previous metadata-save failure.
        if descriptor["kind"] == "translation":
            reuse_or_create(self.repository, descriptor["path"], body, "Translation destination differs")
        self.repository.save(result)
        return result

    def review_variant(self, state, docid, variant_id, expected_fingerprint):
        """Record an explicit review of the exact title, summary and body descriptor."""
        current = self.repository.load()
        domain._require(docid in current["documents"], "Unknown document")
        doc = current["documents"][docid]
        domain._require(variant_id in doc["language_variants"], "Unknown variant")
        domain._require(
            blog.fingerprint(doc["language_variants"][variant_id]) == expected_fingerprint,
            "Variant changed; review again",
        )
        if variant_id in doc["variant_reviews"]:
            return current
        self._fresh_blog_state(state)
        result = copy.deepcopy(state)
        result["documents"][docid]["variant_reviews"][variant_id] = {
            "fingerprint": expected_fingerprint,
            "reviewed_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        self.repository.save(result)
        return result

    def approve_pair(self, state, docid, pair_id, base_revision, variants, expected_fingerprint, attachments=()):
        """Freeze a reviewed pair without selecting it or claiming deployment."""
        current = self.repository.load()
        domain._require(docid in current["documents"], "Unknown document")
        doc = current["documents"][docid]
        previous = doc["publication_pairs"].get(pair_id)
        pair = {
            "id": pair_id,
            "base_revision": base_revision,
            "variants": copy.deepcopy(variants),
            "attachments": copy.deepcopy(list(attachments)),
            "fingerprint": expected_fingerprint,
            "approved_at": previous["approved_at"] if previous else datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        blog.validate_pair(doc, pair)
        if previous is not None:
            domain._require(previous == pair, "Immutable pair ID already exists with different content")
            return current
        self._fresh_blog_state(state)
        result = copy.deepcopy(state)
        result["documents"][docid]["publication_pairs"][pair_id] = pair
        self.repository.save(result)
        return result

    def select_publication(self, state, docid, pair_id=None):
        self._fresh_blog_state(state)
        result = domain.set_publication(state, docid, pair_id)
        self.repository.save(result)
        return result

    def read_pair(self, state, docid, pair_id):
        """Read pinned bilingual text locally; this is not a public export."""
        domain.validate(state)
        doc = state["documents"][docid]
        pair = doc["publication_pairs"][pair_id]
        result = {}
        for lang, vid in pair["variants"].items():
            variant = doc["language_variants"][vid]
            body = self.repository.read_text(variant["body"]["path"])
            domain._require(domain.digest(body) == variant["body"]["sha256"], "Variant body changed")
            result[lang] = {"title": variant["title"], "summary": variant["summary"], "body": body}
        return result

    def save_series(self, state, series):
        """Replace editable series metadata; a public series requires its exact review."""
        self._fresh_blog_state(state)
        blog.validate_series(series, state["documents"])
        result = copy.deepcopy(state)
        sid = series["id"]
        if sid not in result["blog"]["series"]:
            result["blog"]["series_order"].append(sid)
        result["blog"]["series"][sid] = copy.deepcopy(series)
        self.repository.save(result)
        return result

    def order_series(self, state, series_ids):
        self._fresh_blog_state(state)
        result = copy.deepcopy(state)
        result["blog"]["series_order"] = list(series_ids)
        self.repository.save(result)
        return result

    def prepare_public_identities(self, state, document_slugs=None):
        """Assign random IDs only to selected bodies and explicitly approved structure."""
        self._fresh_blog_state(state)
        result = copy.deepcopy(state)
        config = result["blog"]
        documents = {d for d, doc in result["documents"].items() if doc["publication"]["selected_pair"] is not None}
        edges, questions = set(), set()
        for aid in config["selected_structure_approvals"]:
            approval = config["structure_approvals"][aid]
            documents.update(n["document"] for n in approval["nodes"])
            edges.update(e["id"] for e in approval["edges"])
            questions.update(
                q
                for e in approval["edges"]
                for q in e["questions"]
                if config["question_labels"].get(q, {}).get("public")
            )
        slugs = document_slugs or {}
        domain._require(set(slugs) <= documents, "Slug target is not selected for disclosure")
        for kind, selected in (("documents", documents), ("edges", edges), ("questions", questions)):
            for internal in sorted(selected):
                mapping = config["identities"][kind]
                if internal not in mapping:
                    public = uuid.uuid4().hex
                    mapping[internal] = (
                        {"id": public, "slug": slugs.get(internal, "post-" + public)} if kind == "documents" else public
                    )
                elif kind == "documents" and internal in slugs:
                    domain._require(mapping[internal]["slug"] == slugs[internal], "Public slug is already pinned")
        self.repository.save(result)
        return result

    def approve_structure(self, state, approval_id, snapshot, expected_fingerprint):
        """Store the exact reviewed node/month/edge set, without selecting it."""
        from .disclosure import validate_snapshot

        self._fresh_blog_state(state)
        blog.fields(snapshot, "anchor nodes edges")
        domain._require(blog.fingerprint(snapshot) == expected_fingerprint, "Structure changed; review again")
        result = copy.deepcopy(state)
        approvals = result["blog"]["structure_approvals"]
        previous = approvals.get(approval_id)
        value = dict(
            copy.deepcopy(snapshot),
            id=approval_id,
            fingerprint=expected_fingerprint,
            approved_at=previous["approved_at"] if previous else datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        )
        validate_snapshot(result, value, live=True)
        domain._require(previous is None or previous == value, "Immutable structure approval already exists")
        approvals[approval_id] = value
        self.repository.save(result)
        return result

    def select_structures(self, state, approval_ids):
        self._fresh_blog_state(state)
        result = copy.deepcopy(state)
        result["blog"]["selected_structure_approvals"] = list(approval_ids)
        self.repository.save(result)
        return result

    def save_public_label(self, state, kind, target, label, expected_fingerprint):
        """Explicitly approve language-specific wording; never copy private fallback text."""
        self._fresh_blog_state(state)
        domain._require(kind in ("question", "edge"), "Unknown public label kind")
        domain._require(blog.fingerprint(label) == expected_fingerprint, "Label changed; review again")
        result = copy.deepcopy(state)
        source = (
            result["questions"].get(target)
            if kind == "question"
            else next((e for e in result["edges"] if e["id"] == target), None)
        )
        domain._require(source is not None, "Unknown public label target")
        result["blog"][kind + "_labels"][target] = copy.deepcopy(label)
        source["public"] = label["public"]
        self.repository.save(result)
        return result

    def remove_public_label(self, state, kind, target):
        """Forget approved wording; the question's or relation's own publicity is unchanged."""
        self._fresh_blog_state(state)
        domain._require(kind in ("question", "edge"), "Unknown public label kind")
        result = copy.deepcopy(state)
        result["blog"][kind + "_labels"].pop(target, None)
        self.repository.save(result)
        return result
