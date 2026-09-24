"""Committed archive import and migration regressions using disposable repositories."""

import copy
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from stemma_graph import Genealogy, Node, RevisionRef, Succession

from blog_test_support import legacy_v3, reviewed_pair
from stemma_studio.core.application import Studio
from stemma_studio.core.archive_sync import apply_sync, parse_document, plan_sync
from stemma_studio.core.domain import ModelError, confirm, empty_state, genealogy
from stemma_studio.core.migrations import upgrade
from stemma_studio.core.repository import FileRepository, MemoryRepository


class ArchiveTests(unittest.TestCase):
    """Use real Git objects, while keeping every write outside the user's archive."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.archive = self.root / "archive"
        self.archive.mkdir()
        self.git("init", "-q")
        self.git("config", "user.name", "Fixture")
        self.git("config", "user.email", "fixture@example.invalid")
        self.store = Studio(self.root / "studio")
        self.store.save(empty_state())

    def git(self, *args):
        return subprocess.check_output(["git", "-C", str(self.archive), *args], stderr=subprocess.PIPE)

    def write(self, path, content):
        target = self.archive / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))
        return target

    def document(self, docid, body="original", extra="", path=None):
        return self.write(
            path or "corpus/test/" + docid + ".md",
            "---\nid: " + docid + "\ndate: null\nstatus: published\n" + extra + "---\n" + body + "\n",
        )

    def commit(self):
        self.git("add", ".")
        self.git("commit", "-qm", "fixture")
        return self.git("rev-parse", "HEAD").decode().strip()

    def initial(self, extra=""):
        self.document("a", extra=extra)
        commit = self.commit()
        state, report = self.store.sync_archive(self.archive)
        self.assertEqual(report["status"], "synced")
        return state, commit

    def test_only_committed_bytes_are_imported(self):
        source = self.document("a")
        raw = source.read_bytes()
        commit = self.commit()
        self.document("a", "dirty modification")
        self.document("untracked")
        before = self.git("status", "--porcelain")
        state, report = self.store.sync_archive(self.archive)
        self.assertEqual(set(state["documents"]), {"a"})
        doc = state["documents"]["a"]
        self.assertEqual(self.store.repository.read_bytes(doc["source"]["snapshot"]), raw)
        self.assertEqual(doc["source"]["commit"], commit)
        self.assertEqual(doc["source"]["metadata"]["status"], "published")
        self.assertFalse(doc["publication"]["selected_pair"])
        self.assertEqual(doc["questions"], [])
        self.assertEqual(state["edges"], [])
        self.assertEqual(self.git("status", "--porcelain"), before)

    def test_next_commit_imports_on_load_and_repeat_is_noop(self):
        state, commit = self.initial()
        original = copy.deepcopy(state["documents"]["a"])
        self.document("b")
        new_commit = self.commit()
        loaded = self.store.load()
        self.assertEqual(set(loaded["documents"]), {"a", "b"})
        self.assertEqual(loaded["archive"]["commit"], new_commit)
        self.assertEqual(loaded["documents"]["a"]["source"]["commit"], commit)
        self.assertEqual(loaded["documents"]["a"]["revisions"], original["revisions"])
        saved = self.store.metadata.read_bytes()
        with patch.object(self.store.repository, "save", side_effect=AssertionError("Unexpected save")):
            self.assertEqual(self.store.load(), loaded)
        self.assertEqual(self.store.metadata.read_bytes(), saved)
        self.assertEqual(self.store.last_sync_report["status"], "up_to_date")

    def test_dry_run_and_disabled_sync_do_not_write(self):
        self.initial()
        self.document("b")
        self.commit()
        before = self.store.metadata.read_bytes()
        state, report = self.store.sync_archive(dry_run=True)
        self.assertEqual(report["added"], ["b"])
        self.assertNotIn("b", state["documents"])
        self.assertNotIn("b", self.store.load(auto_sync=False)["documents"])
        self.assertEqual(before, self.store.metadata.read_bytes())
        self.assertFalse(self.store.path("data/imports/b.md").exists())

    def test_existing_text_mutation_blocks_entire_batch_and_keeps_cache(self):
        state, commit = self.initial()
        self.document("a", "changed")
        self.document("b")
        self.commit()
        self.assertEqual(self.store.load(), state)
        self.assertEqual(self.store.last_sync_report["status"], "blocked")
        self.assertEqual(self.store.load(auto_sync=False)["archive"]["commit"], commit)
        self.assertFalse(self.store.path("data/imports/b.md").exists())

    def test_deletion_blocks_but_rename_keeps_identity(self):
        state, _ = self.initial()
        old = self.archive / "corpus/test/a.md"
        old.rename(old.with_name("renamed.md"))
        self.commit()
        renamed, report = self.store.sync_archive()
        self.assertEqual(report["moved"], ["a"])
        self.assertEqual(renamed["documents"]["a"]["revisions"], state["documents"]["a"]["revisions"])
        old.with_name("renamed.md").unlink()
        self.commit()
        unchanged, report = self.store.sync_archive()
        self.assertEqual(report["status"], "blocked")
        self.assertEqual(unchanged, renamed)

    def test_duplicate_ids_and_malformed_sources_block_without_partial_files(self):
        self.document("a")
        self.document("a", path="corpus/test/duplicate.md")
        self.write("corpus/test/malformed.md", "no frontmatter")
        self.commit()
        _, report = self.store.sync_archive(self.archive)
        self.assertEqual(report["status"], "blocked")
        self.assertEqual(len(report["conflicts"]), 2)
        self.assertFalse(self.store.path("data/imports").exists())

    def test_missing_initial_asset_is_reported_and_later_commit_resolves_it(self):
        state, _ = self.initial("assets:\n  - path: assets/photo.jpg\n")
        self.assertEqual(state["documents"]["a"]["source"]["missing_assets"], ["assets/photo.jpg"])
        content = b"\x00\xffbinary\r\n"
        self.write("assets/photo.jpg", content)
        self.commit()
        updated = self.store.load()
        source = updated["documents"]["a"]["source"]
        self.assertEqual(source["missing_assets"], [])
        self.assertEqual(self.store.repository.read_bytes(source["assets"][0]["snapshot"]), content)
        self.assertEqual(self.store.last_sync_report["assets_added"], 1)

    def test_previously_imported_asset_cannot_change_or_disappear(self):
        self.write("assets/photo.jpg", b"original bytes")
        state, _ = self.initial("assets:\n  - path: assets/photo.jpg\n")
        self.write("assets/photo.jpg", b"changed bytes")
        self.commit()
        unchanged, report = self.store.sync_archive()
        self.assertEqual(unchanged, state)
        self.assertIn("existing_asset_changed", [c["reason"] for c in report["conflicts"]])
        (self.archive / "assets/photo.jpg").unlink()
        self.commit()
        unchanged, report = self.store.sync_archive()
        self.assertEqual(unchanged, state)
        self.assertIn("existing_asset_missing", [c["reason"] for c in report["conflicts"]])

    def test_local_asset_tampering_is_detected(self):
        self.write("assets/photo.jpg", b"original bytes")
        state, _ = self.initial("assets:\n  - path: assets/photo.jpg\n")
        asset = state["documents"]["a"]["source"]["assets"][0]
        self.store.path(asset["snapshot"]).write_bytes(b"tampered")
        with self.assertRaisesRegex(ModelError, "Asset changed"):
            self.store.load(auto_sync=False)

    def test_retry_after_checkpoint_failure_reuses_matching_snapshots(self):
        self.document("a")
        self.commit()
        plan = plan_sync(self.store.load(), self.archive)
        with patch.object(self.store.repository, "save", side_effect=OSError("simulated interruption")):
            with self.assertRaises(OSError):
                apply_sync(self.store.repository, plan)
        self.assertEqual(self.store.load()["documents"], {})
        state, report = self.store.sync_archive(self.archive)
        self.assertEqual(report["status"], "synced")
        self.assertEqual(set(state["documents"]), {"a"})

    def test_destination_collision_is_checked_before_any_write(self):
        self.document("a")
        self.document("b")
        self.commit()
        self.store.repository.write_bytes_new("data/revisions/b/r1.md", b"foreign")
        with self.assertRaisesRegex(ModelError, "destination differs"):
            self.store.sync_archive(self.archive)
        self.assertFalse(self.store.path("data/imports/a.md").exists())
        self.assertEqual(self.store.load()["documents"], {})

    def test_unavailable_archive_leaves_verified_cache_usable(self):
        state, _ = self.initial()
        self.archive.rename(self.root / "unavailable")
        self.assertEqual(self.store.load(), state)
        self.assertEqual(self.store.last_sync_report["status"], "error")

    def test_imported_document_cannot_be_revised_in_place(self):
        state, _ = self.initial()
        with self.assertRaisesRegex(ModelError, "Imported snapshots are immutable"):
            self.store.add_revision(state, "a", "rewritten", "edit")
        self.assertEqual(self.store.load(auto_sync=False), state)

    def test_sync_preserves_local_question_and_publication_choices(self):
        state, _ = self.initial()
        state["questions"]["q"] = {"text": "Question?", "public": False, "representatives": ["a"]}
        state["documents"]["a"]["questions"] = ["q"]
        state = self.store.set_archived(state, "a")
        self.document("b")
        self.commit()
        updated = self.store.load()
        self.assertEqual(updated["questions"], state["questions"])
        self.assertEqual(updated["documents"]["a"]["questions"], ["q"])
        self.assertEqual(updated["documents"]["a"]["publication"], state["documents"]["a"]["publication"])
        self.assertTrue(updated["documents"]["a"]["archived"])
        self.assertFalse(updated["documents"]["b"]["archived"])

    def test_imported_translation_and_pair_survive_sync_without_rewriting_source(self):
        state, _ = self.initial()
        original = copy.deepcopy(state["documents"]["a"])
        paths = [original["source"]["snapshot"], original["revisions"][0]["path"]]
        contents = {p: self.store.repository.read_bytes(p) for p in paths}
        archive_status = self.git("status", "--porcelain")
        state = reviewed_pair(self.store, state, "a", "r1")
        self.assertEqual(self.git("status", "--porcelain"), archive_status)
        self.assertEqual(state["documents"]["a"]["revisions"], original["revisions"])
        self.document("b")
        self.commit()
        updated = self.store.load()
        for key in ("language_variants", "variant_reviews", "publication_pairs", "publication"):
            self.assertEqual(updated["documents"]["a"][key], state["documents"]["a"][key])
        self.assertEqual(updated["documents"]["b"]["language_variants"], {})
        self.assertIsNone(updated["documents"]["b"]["publication"]["selected_pair"])
        for path, content in contents.items():
            self.assertEqual(self.store.repository.read_bytes(path), content)

    def test_undated_control_character_title_and_exact_crlf_snapshot(self):
        raw = b'---\r\nid: a\r\ndate: null\r\ntitle: "raw\x08title"\r\n---\r\nbody\r\n'
        metadata, body, assets = parse_document(raw)
        self.assertEqual(metadata["title"], "raw\x08title")
        self.assertIsNone(metadata["date"])
        self.write("corpus/test/a.md", raw)
        self.commit()
        state, _ = self.store.sync_archive(self.archive)
        self.assertEqual(self.store.repository.read_bytes(state["documents"]["a"]["source"]["snapshot"]), raw)
        self.store.load(auto_sync=False)


class ScopeAndMigrationTests(unittest.TestCase):
    def state(self):
        app = Studio(repository=MemoryRepository())
        state = empty_state()
        state["questions"] = {q: {"text": q, "public": False, "representatives": []} for q in ("q", "other")}
        state = app.create_draft(state, "a", "a", ["q", "other"], "a body", [], "initial")
        state = confirm(state, "a")
        state = app.create_draft(
            state, "b", "b", ["q", "other"], "b body", [{"parent": "a", "questions": ["q", "other"]}], "shared note"
        )
        return app, confirm(state, "b")

    def test_one_edge_applies_to_overlapping_questions(self):
        app, state = self.state()
        self.assertEqual(len(state["edges"]), 1)
        for question in ("q", "other"):
            self.assertEqual(genealogy(state, question)["terminals"], ["b"])
        app.save(state)
        self.assertEqual(app.load(), state)

    def test_core_rejects_parallel_pairs_and_invalid_scope_lists(self):
        a, b = RevisionRef("a", "r1"), RevisionRef("b", "r1")
        nodes = tuple(Node(d, ("r1",), ("q", "other")) for d in ("a", "b"))
        first = Succession("first", a, b, ("q",), "note")
        with self.assertRaises(ModelError):
            Genealogy(nodes, ("q", "other"), (first, Succession("second", a, b, ("other",), "note")))
        for scopes in ((), ("q", "q"), "q"):
            with self.assertRaises(ModelError):
                Succession("edge", a, b, scopes, "note")

    def legacy(self):
        app, state = self.state()
        state = legacy_v3(state)
        state["schema_version"] = 1
        edge = state["edges"].pop()
        for question in edge.pop("questions"):
            state["edges"].append({**edge, "id": question, "question": question, "change_note": question + " note"})
        return app, state

    def test_migration_merges_compatible_scopes_without_losing_notes(self):
        _, state = self.legacy()
        before = copy.deepcopy(state)
        upgraded = upgrade(state)
        self.assertEqual(state, before)
        self.assertEqual(len(upgraded["edges"]), 1)
        self.assertEqual(set(upgraded["edges"][0]["questions"]), {"q", "other"})
        self.assertEqual(upgraded["edges"][0]["legacy_edge_ids"], ["q", "other"])
        self.assertIn("[other] other note", upgraded["edges"][0]["change_note"])
        self.assertEqual(genealogy(upgraded, "q")["terminals"], ["b"])

    def test_migration_refuses_incompatible_approval_or_revision(self):
        for field, value in (("public", True), ("state", "proposed"), ("parent_revision", "r2")):
            _, legacy = self.legacy()
            legacy["edges"][1][field] = value
            with self.assertRaisesRegex(ModelError, "require review"):
                upgrade(legacy)

    def test_file_migration_is_backed_up_only_on_save(self):
        app, legacy = self.legacy()
        raw = (json.dumps(legacy, indent=4) + "\n").encode()
        with tempfile.TemporaryDirectory() as folder:
            repository = FileRepository(folder)
            for doc in legacy["documents"].values():
                for revision in doc["revisions"]:
                    repository.write_new(revision["path"], app.repository.read_text(revision["path"]))
            repository.metadata.write_bytes(raw)
            state = repository.load()
            self.assertEqual(repository.metadata.read_bytes(), raw)
            repository.save(state)
            self.assertEqual(repository.read_bytes("data/migrations/studio-v1.json"), raw)
            self.assertEqual(repository.load(), state)


if __name__ == "__main__":
    unittest.main()
