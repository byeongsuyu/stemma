"""Global future-use state is independent of confirmed, question-scoped lineage."""

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from stemma_graph import Genealogy, GraphError, RevisionRef, Succession

from blog_test_support import legacy_v3, reviewed_pair
from stemma_studio.core.adapters import to_genealogy
from stemma_studio.core.application import Studio
from stemma_studio.core.domain import empty_state, genealogy, set_representatives
from stemma_studio.core.migrations import upgrade
from stemma_studio.core.repository import FileRepository, MemoryRepository

PLANNED = "2026-02-01T09:00:00Z"


class ArchivingTests(unittest.TestCase):
    def setUp(self):
        self.repo = MemoryRepository()
        self.app = Studio(repository=self.repo)
        state = empty_state()
        state["questions"] = {q: {"text": q, "public": False, "representatives": []} for q in ("q", "other")}
        self.app.save(state)
        for doc in ("a", "b"):
            state = self.app.create_draft(state, doc, doc, ["q", "other"], doc + " text", [], "original")
            state = self.app.confirm(state, doc)
        self.state = state

    def draft(self, state, doc="c", parents=("a", "b")):
        return self.app.create_draft(
            state,
            doc,
            doc,
            ["q", "other"],
            doc + " text",
            [{"parent": p, "questions": ["q"]} for p in parents],
            "continued",
        )

    def test_confirm_and_archive_selected_parent_without_changing_question_history(self):
        draft = self.draft(self.state)
        before = copy.deepcopy(draft)
        self.assertFalse(draft["documents"]["a"]["archived"])
        self.assertEqual(genealogy(draft, "q")["terminals"], ["a", "b"])
        state = self.app.confirm(draft, "c", archive_parents=["a"])
        self.assertEqual(draft, before)
        self.assertTrue(state["documents"]["a"]["archived"])
        self.assertFalse(state["documents"]["b"]["archived"])
        self.assertEqual(genealogy(state, "q")["terminals"], ["c"])
        # Global use can end even while a document remains a terminal elsewhere.
        self.assertIn("a", genealogy(state, "other")["terminals"])
        self.assertIn("a", genealogy(state, "q")["roots"])
        graph = to_genealogy(state)
        self.assertEqual(graph.ancestors("c", "q"), ("a", "b"))
        self.assertNotIn("a", graph.available_documents())
        self.assertEqual(self.repo.load(), state)

    def test_ordinary_succession_does_not_archive_any_parent(self):
        state = self.app.confirm(self.draft(self.state), "c")
        self.assertFalse(any(d["archived"] for d in state["documents"].values()))

    def test_invalid_archive_parent_selection_leaves_saved_state_unchanged(self):
        state = self.draft(self.state, parents=("a",))
        for parents in (["b"], ["c"], ["unknown"], ["a", "a"], "a"):
            with self.subTest(parents=parents):
                with self.assertRaises(GraphError):
                    self.app.confirm(state, "c", archive_parents=parents)
                self.assertEqual(self.repo.load(), state)
        with self.assertRaises(GraphError):
            self.app.set_archived(state, "c")

    def test_archived_parent_cannot_start_or_confirm_new_succession_until_restored(self):
        pending = self.draft(self.state, parents=("a",))
        archived = self.app.set_archived(pending, "a")
        with self.assertRaises(GraphError):
            self.draft(archived, doc="d", parents=("a",))
        with self.assertRaises(GraphError):
            self.app.confirm(archived, "c")
        restored = self.app.set_archived(archived, "a", False)
        confirmed = self.app.confirm(restored, "c")
        self.assertEqual(genealogy(confirmed, "q")["terminals"], ["b", "c"])

    def test_core_archive_is_immutable_and_rejects_new_edges(self):
        graph = to_genealogy(self.state)
        archived = graph.set_archived("a")
        self.assertIn("a", graph.available_documents())
        edge = Succession("e", RevisionRef("a", "r1"), RevisionRef("b", "r1"), ("q",), "new")
        with self.assertRaises(GraphError):
            archived.add_edge(edge)
        for value in (1, "yes", None):
            with self.assertRaises(GraphError):
                graph.set_archived("a", value)
        with self.assertRaises(GraphError):
            graph.set_archived("unknown")

    def test_branch_and_merge_history_survives_global_archiving(self):
        state = self.app.confirm(self.draft(self.state, "c", ("a",)), "c")
        state = self.app.confirm(self.draft(state, "d", ("a",)), "d")
        state = self.app.confirm(self.draft(state, "e", ("c", "d")), "e")
        before = to_genealogy(state)
        archived = before.set_archived("a").set_archived("c")
        self.assertEqual(before.view("q"), archived.view("q"))
        self.assertEqual(archived.descendants("a", "q"), ("c", "d", "e"))
        self.assertIn("d", archived.available_documents())
        self.assertIn("e", archived.available_documents())

    def test_revision_and_parent_archive_save_together_preserving_pinned_edges(self):
        state = self.app.confirm(self.draft(self.state), "c")
        original_edges = copy.deepcopy(state["edges"])
        original_body = self.repo.read_text("data/revisions/c/r1.md")
        result = self.app.add_revision(
            state, "c", original_body + "\n\n" + "a text", "append original", archive_parents=["a"]
        )
        self.assertEqual(result["documents"]["c"]["current_revision"], "r2")
        self.assertTrue(result["documents"]["a"]["archived"])
        self.assertEqual(result["edges"], original_edges)
        self.assertEqual(self.repo.read_text("data/revisions/c/r1.md"), original_body)
        self.assertEqual(self.repo.load(), result)
        # Expression changes do not silently restore a globally archived document.
        result = self.app.add_revision(result, "a", "corrected historical text", "typo")
        self.assertTrue(result["documents"]["a"]["archived"])

    def test_failed_parent_choice_does_not_write_new_revision(self):
        state = self.app.confirm(self.draft(self.state, parents=("a",)), "c")
        with self.assertRaises(GraphError):
            self.app.add_revision(state, "c", "new text", "note", archive_parents=["b"])
        with self.assertRaises(KeyError):
            self.repo.read_text("data/revisions/c/r2.md")
        self.assertEqual(self.repo.load(), state)

    def test_publication_and_representatives_do_not_change_or_disclose_archive_state(self):
        # The real v3 exporter is the only public boundary; archiving must be invisible to it.
        state = reviewed_pair(self.app, self.state, "a", "r1")
        state = set_representatives(state, "q", ["a"])
        self.app.save(state)
        state = self.app.prepare_public_identities(state)
        public = self.app.export_public(state, PLANNED)
        self.assertEqual(len(public["documents"]), 1)
        archived = self.app.set_archived(state, "a")
        self.assertEqual(public, self.app.export_public(archived, PLANNED))
        self.assertEqual(archived["questions"]["q"]["representatives"], ["a"])
        self.assertNotIn("archived", json.dumps(self.app.export_public(archived, PLANNED)))

    def test_a_retired_document_is_not_published_anew_through_the_core(self):
        # The admin screen refuses this, but `stemma publish --pair` reaches the same
        # decision without passing through it, so the rule has to hold here.
        state = reviewed_pair(self.app, self.state, "a", "r1")
        state = self.app.select_publication(state, "a", None)
        state = self.app.set_archived(state, "a")
        pair = next(iter(state["documents"]["a"]["publication_pairs"]))
        with self.assertRaisesRegex(GraphError, "retired piece is not published anew"):
            self.app.select_publication(state, "a", pair)
        self.assertIsNone(self.repo.load()["documents"]["a"]["publication"]["selected_pair"])

    def test_a_retired_document_that_is_already_selected_can_still_be_withdrawn(self):
        state = reviewed_pair(self.app, self.state, "a", "r1")
        pair = state["documents"]["a"]["publication"]["selected_pair"]
        self.assertIsNotNone(pair)
        archived = self.app.set_archived(state, "a")
        # Retirement is not a takedown: the live selection survives it and can be cleared.
        kept = self.app.select_publication(archived, "a", pair)
        self.assertEqual(kept["documents"]["a"]["publication"]["selected_pair"], pair)
        cleared = self.app.select_publication(kept, "a", None)
        self.assertIsNone(cleared["documents"]["a"]["publication"]["selected_pair"])

    def test_v2_graph_migrates_without_archiving_and_v3_round_trips(self):
        graph = to_genealogy(self.state)
        legacy = graph.to_dict()
        legacy["schema_version"] = 2
        for node in legacy["nodes"]:
            del node["archived"]
        restored = Genealogy.from_dict(legacy)
        self.assertEqual(restored, graph)
        archived = restored.set_archived("a")
        self.assertEqual(archived.to_dict()["schema_version"], 3)
        self.assertEqual(Genealogy.from_dict(archived.to_dict()), archived)
        missing = archived.to_dict()
        del missing["nodes"][0]["archived"]
        with self.assertRaises(GraphError):
            Genealogy.from_dict(missing)

    def test_v2_studio_backup_is_exact_and_read_only_load_does_not_migrate_on_disk(self):
        legacy = legacy_v3(self.state)
        legacy["schema_version"] = 2
        for doc in legacy["documents"].values():
            del doc["archived"]
        raw = (json.dumps(legacy, ensure_ascii=False, indent=4) + "\n").encode()
        with tempfile.TemporaryDirectory() as folder:
            repo = FileRepository(folder)
            for doc in legacy["documents"].values():
                for rev in doc["revisions"]:
                    repo.write_new(rev["path"], self.repo.read_text(rev["path"]))
            repo.metadata.write_bytes(raw)
            state = repo.load()
            self.assertEqual(state["schema_version"], 4)
            self.assertFalse(any(d["archived"] for d in state["documents"].values()))
            self.assertEqual(repo.metadata.read_bytes(), raw)
            self.assertFalse(repo.path("data/migrations/studio-v2.json").exists())
            repo.save(state)
            self.assertEqual(repo.read_bytes("data/migrations/studio-v2.json"), raw)
            self.assertEqual(repo.load(), state)
            self.assertEqual(upgrade(state), state)

    def test_cli_confirm_with_parent_archive_and_restore(self):
        state = self.draft(self.state, parents=("a",))
        with tempfile.TemporaryDirectory() as folder:
            repo = FileRepository(folder)
            for doc in state["documents"].values():
                for rev in doc["revisions"]:
                    repo.write_new(rev["path"], self.repo.read_text(rev["path"]))
            repo.save(state)
            script = Path(__file__).resolve().parents[1] / "scripts/dev.py"
            base = [sys.executable, "-B", str(script), "studio", "--root", folder, "--no-sync"]
            subprocess.check_output(base + ["confirm", "c", "--archive-parent", "a"])
            self.assertTrue(repo.load()["documents"]["a"]["archived"])
            subprocess.check_output(base + ["restore", "a"])
            self.assertFalse(repo.load()["documents"]["a"]["archived"])


if __name__ == "__main__":
    unittest.main()
