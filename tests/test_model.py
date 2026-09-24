"""Integration regressions for Studio workflows and source preservation.

All writes use temporary fixtures, never the approved corpus or published state."""

import copy
import tempfile
import unittest
from pathlib import Path

from blog_test_support import reviewed_pair
from stemma_studio.core.application import Studio as Store
from stemma_studio.core.domain import (
    ModelError,
    confirm,
    empty_state,
    genealogy,
    set_publication,
    set_representatives,
    validate,
)


class ModelTests(unittest.TestCase):
    """Exercise application workflows with temporary files and synthetic documents."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name) / "studio")
        self.state = empty_state()
        self.state["questions"] = {q: {"text": q + "?", "representatives": [], "public": False} for q in ("q", "other")}
        for docid in ("a", "b"):
            self.state = self.store.create_draft(
                self.state, docid, docid, ["q", "other"], docid + " body", [], "initial"
            )
            self.state = confirm(self.state, docid)
        self.store.save(self.state)

    def failing_save(self):
        """Break the metadata save the way a full disk would, leaving the snapshot behind."""
        from stemma_studio.core.repository import FileRepository

        original = FileRepository.save

        def fail(repository, state):
            raise OSError("simulated metadata save failure")

        FileRepository.save = fail
        self.addCleanup(setattr, FileRepository, "save", original)
        return lambda: setattr(FileRepository, "save", original)

    def test_a_draft_retried_after_a_failed_save_reuses_its_own_snapshot(self):
        # The snapshot and the metadata that names it are separate writes, so the retry
        # of an identical request has to finish rather than collide with its own orphan.
        restore = self.failing_save()
        with self.assertRaises(OSError):
            self.store.create_draft(self.state, "d", "d", ["q"], "d body", [], "initial")
        restore()
        self.assertEqual(self.store.repository.read_text("data/revisions/d/r1.md"), "d body")
        state = self.store.create_draft(self.state, "d", "d", ["q"], "d body", [], "initial")
        self.assertIn("d", state["documents"])

    def test_a_retry_with_different_text_is_refused_rather_than_overwriting(self):
        restore = self.failing_save()
        with self.assertRaises(OSError):
            self.store.create_draft(self.state, "d", "d", ["q"], "d body", [], "initial")
        restore()
        with self.assertRaisesRegex(ModelError, "different text"):
            self.store.create_draft(self.state, "d", "d", ["q"], "a different body", [], "initial")
        # An immutable snapshot is never rewritten, not even by its own retry.
        self.assertEqual(self.store.repository.read_text("data/revisions/d/r1.md"), "d body")

    def test_a_revision_retried_after_a_failed_save_reuses_its_own_snapshot(self):
        restore = self.failing_save()
        with self.assertRaises(OSError):
            self.store.add_revision(self.state, "a", "a second body", "expression edit")
        restore()
        state = self.store.add_revision(self.state, "a", "a second body", "expression edit")
        self.assertEqual(state["documents"]["a"]["current_revision"], "r2")

    def child(self, docid="c", parents=("a", "b"), question="q"):
        self.state = self.store.create_draft(
            self.state,
            docid,
            docid,
            [question],
            docid + " body",
            [{"parent": p, "question": question} for p in parents],
            "정리",
        )

    def test_initial_nodes_are_roots_and_terminals(self):
        view = genealogy(self.state, "q")
        self.assertEqual(view["roots"], ["a", "b"])
        self.assertEqual(view["terminals"], ["a", "b"])

    def test_draft_does_not_retire_parents(self):
        self.child()
        self.assertEqual(genealogy(self.state, "q")["terminals"], ["a", "b"])

    def test_multiple_parents_confirm_and_question_scope(self):
        self.child()
        self.state = confirm(self.state, "c")
        self.assertEqual(genealogy(self.state, "q")["terminals"], ["c"])
        self.assertEqual(genealogy(self.state, "other")["terminals"], ["a", "b"])

    def test_branch_and_merge(self):
        self.child("c", ("a",))
        self.state = confirm(self.state, "c")
        self.child("d", ("a",))
        self.state = confirm(self.state, "d")
        self.assertEqual(genealogy(self.state, "q")["terminals"], ["b", "c", "d"])
        self.child("e", ("c", "d"))
        self.state = confirm(self.state, "e")
        self.assertEqual(genealogy(self.state, "q")["terminals"], ["b", "e"])

    def test_cycle_rejected(self):
        self.child("c", ("a",))
        edge = copy.deepcopy(self.state["edges"][0])
        edge.update(id="reverse", parent="c", child="a")
        self.state["edges"].append(edge)
        with self.assertRaisesRegex(ModelError, "acyclic"):
            validate(self.state)

    def test_self_edge_rejected(self):
        self.child("c", ("a",))
        self.state["edges"][0]["parent"] = "c"
        with self.assertRaises(ModelError):
            validate(self.state)

    def test_duplicate_and_missing_endpoints_rejected(self):
        self.child()
        broken = copy.deepcopy(self.state)
        edge = copy.deepcopy(broken["edges"][0])
        edge["id"] = "duplicate"
        broken["edges"].append(edge)
        with self.assertRaises(ModelError):
            validate(broken)
        self.state["edges"][0]["parent"] = "missing"
        with self.assertRaises(ModelError):
            validate(self.state)

    def test_duplicate_pair_rejected_even_for_different_questions(self):
        self.child("c", ("a",))
        self.state["documents"]["c"]["questions"].append("other")
        edge = copy.deepcopy(self.state["edges"][0])
        edge.update(id="other-edge", questions=["other"])
        self.state["edges"].append(edge)
        with self.assertRaises(ModelError):
            validate(self.state)

    def test_revision_keeps_genealogy_and_pinned_publication(self):
        self.child()
        self.state = confirm(self.state, "c")
        self.state = reviewed_pair(self.store, self.state, "c", "r1")
        before = copy.deepcopy(genealogy(self.state, "q"))
        self.state = self.store.add_revision(self.state, "c", "polished body", "문장 다듬기")
        self.assertEqual(before, genealogy(self.state, "q"))
        self.assertEqual(self.state["documents"]["c"]["publication"]["selected_pair"], "pair-r1")
        self.assertEqual(self.store.read_pair(self.state, "c", "pair-r1")["ko"]["body"], "c body")
        self.assertEqual(self.store.load(), self.state)

    def test_confirm_pins_final_draft_revision(self):
        self.child()
        self.state = self.store.add_revision(self.state, "c", "draft v2", "다듬기")
        self.state = confirm(self.state, "c")
        self.assertEqual({e["child_revision"] for e in self.state["edges"]}, {"r2"})

    def test_representative_is_independent_and_stale_is_reported(self):
        self.state = set_representatives(self.state, "q", ["a"])
        self.assertFalse(self.state["documents"]["a"]["publication"]["selected_pair"])
        self.child("c", ("a",))
        self.state = confirm(self.state, "c")
        self.assertEqual(genealogy(self.state, "q")["representatives_needing_review"], ["a"])

    def test_draft_cannot_publish_or_represent(self):
        self.child()
        with self.assertRaises(ModelError):
            set_publication(self.state, "c", "r1")
        with self.assertRaises(ModelError):
            set_representatives(self.state, "q", ["c"])

    def test_tamper_detection(self):
        path = self.state["documents"]["a"]["revisions"][0]["path"]
        self.store.path(path).write_text("tampered", encoding="utf-8")
        with self.assertRaisesRegex(ModelError, "content changed"):
            self.store.load()

    def test_unsafe_id_and_path_rejected(self):
        with self.assertRaises(ModelError):
            self.store.path("../escape")
        with self.assertRaises(ModelError):
            self.store.create_draft(self.state, "../evil", "bad", ["q"], "body", [], "note")


if __name__ == "__main__":
    unittest.main()
