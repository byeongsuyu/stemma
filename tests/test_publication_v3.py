"""Prospective public v3 output is tested only against disposable synthetic data."""

import copy
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from blog_fixtures import EDGE_IDS, IDS, PUBLIC_IDS, RELEASE_TIME, SERIES_IDS, make_fixture
from blog_test_support import reviewed_pair
from stemma_studio.core.application import Studio
from stemma_studio.core.blog import fingerprint, pair_input
from stemma_studio.core.disclosure import document_date, month_date
from stemma_studio.core.domain import ModelError
from stemma_studio.core.repository import FileRepository, MemoryRepository


def phase_three(fixture):
    state = copy.deepcopy(fixture["future"])
    state["blog"]["releases"] = {}
    state["blog"]["release_attempts"] = []
    return state


class PublicV3Tests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.fixture = make_fixture(self.root)
        self.state = phase_three(self.fixture)
        self.repo = FileRepository(self.root)
        self.app = Studio(repository=self.repo)
        self.repo.save(self.state)

    def export(self, state=None):
        return self.app.export_public(self.state if state is None else state, RELEASE_TIME)

    def graph(self, result, name="C"):
        return next(g for g in result["genealogies"] if g["document"] == PUBLIC_IDS[name])

    def label(self, kind, target, translations, public=True):
        value = {"public": public, "translations": translations}
        self.state = self.app.save_public_label(self.state, kind, target, value, fingerprint(value))
        self.state = self.app.prepare_public_identities(self.state)

    def test_removing_wording_hides_it_without_changing_question_publicity(self):
        self.label("question", "q", {"ko": "공개 질문", "en": "Public question"})
        shown = lambda: [q for g in self.export()["genealogies"] for e in g["edges"] for q in e["questions"]]
        self.assertTrue(shown())
        self.state = self.app.remove_public_label(self.state, "question", "q")
        self.assertEqual(shown(), [])
        self.assertTrue(self.state["questions"]["q"]["public"])
        self.assertNotIn("q", self.state["blog"]["question_labels"])

    def test_same_release_uses_private_creation_time_for_public_order_only(self):
        from stemma_studio.blog.render import render_site

        selected = [i for i, d in self.state["documents"].items() if d["publication"]["selected_pair"]]
        for i in selected:
            self.state["documents"][i]["created_at"] = "2026-09-19T10:30:00+09:00"
        latest = selected[-1]
        self.state["documents"][latest]["created_at"] = "2026-09-19T02:00:00Z"
        # Structure dates have their own approval contract; isolate this ordering test.
        self.state["blog"]["selected_structure_approvals"] = []
        public = self.export()
        expected = self.state["blog"]["identities"]["documents"][latest]["id"]
        self.assertEqual(public["documents"][0]["id"], expected)
        self.assertNotIn("10:30:00", json.dumps(public))
        self.assertNotIn("02:00:00", json.dumps(public))
        html = render_site(public)["ko/index.html"].decode()
        slugs = [d["slug"] for d in public["documents"]]
        listing = html.split('<ul class="posts">')[1]
        self.assertLess(listing.index("/posts/" + slugs[0] + "/"), listing.index("/posts/" + slugs[1] + "/"))

    def test_actual_export_matches_independent_golden_and_does_not_write(self):
        original = copy.deepcopy(self.state)
        files = {str(p): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        self.assertEqual(self.export(), self.fixture["expected"])
        self.assertEqual(self.state, original)
        self.assertEqual(files, {str(p): p.read_bytes() for p in self.root.rglob("*") if p.is_file()})
        self.assertIsNone(self.state["blog"]["active_release"])
        for doc in self.state["documents"].values():
            self.assertIsNone(doc["publication"]["first_published_at"])
        serialized = json.dumps(self.export(), ensure_ascii=False)
        for sentinel in self.fixture["sentinels"]:
            self.assertNotIn(sentinel, serialized)

    def test_805_unrelated_nodes_do_not_change_export_or_read_set(self):
        with tempfile.TemporaryDirectory() as folder:
            small = make_fixture(folder, unrelated=0)
            app = Studio(folder)
            app.save(phase_three(small))
            self.assertEqual(self.export(), app.export_public(phase_three(small), RELEASE_TIME))
        with patch.object(self.repo, "read_text", wraps=self.repo.read_text) as reads:
            self.export()
        paths = {args[0] for args, _ in reads.call_args_list}
        expected = {
            v["body"]["path"]
            for did in ("A", "C", "D", "S")
            for vid, v in self.state["documents"][IDS[did]]["language_variants"].items()
            if vid in self.state["documents"][IDS[did]]["publication_pairs"]["pair-" + did]["variants"].values()
        }
        self.assertEqual(paths, expected)

    def test_unpublish_removes_both_bodies_and_series_members_but_keeps_placeholder(self):
        old = self.export()
        self.state = self.app.select_publication(self.state, IDS["C"], None)
        result = self.export()
        self.assertNotIn(PUBLIC_IDS["C"], {d["id"] for d in result["documents"]})
        self.assertNotIn(PUBLIC_IDS["C"], {g["document"] for g in result["genealogies"]})
        node = next(n for n in self.graph(result, "A")["nodes"] if n["id"] == PUBLIC_IDS["C"])
        self.assertEqual(node, {"id": PUBLIC_IDS["C"], "kind": "unpublished", "month": "2021-07"})
        self.assertEqual([s["documents"] for s in result["series"]], [[PUBLIC_IDS["A"]], [PUBLIC_IDS["D"]]])
        for lang in ("ko", "en"):
            body = next(d for d in old["documents"] if d["id"] == PUBLIC_IDS["C"])["translations"][lang]["body"]
            self.assertNotIn(body, json.dumps(result, ensure_ascii=False))
        for name in ("A", "D", "S"):
            self.state = self.app.select_publication(self.state, IDS[name], None)
        self.assertEqual(self.export(), {"schema_version": 3, "documents": [], "genealogies": [], "series": []})

    def test_missing_structure_means_isolated_public_nodes_not_inferred_edges(self):
        self.state = self.app.select_structures(self.state, [])
        result = self.export()
        for graph in result["genealogies"]:
            self.assertEqual(graph["nodes"], [{"id": graph["document"], "kind": "public"}])
            self.assertEqual(graph["edges"], [])

    def test_partial_chain_does_not_bypass_hidden_middle(self):
        snapshot = {
            "anchor": IDS["A"],
            "nodes": [{"document": IDS[n], "date": month_date(self.state["documents"][IDS[n]])} for n in "ABCD"],
            "edges": [
                copy.deepcopy(e)
                for e in self.state["blog"]["structure_approvals"]["structure-one"]["edges"]
                if e["id"] in ("PRIVATE-EDGE-ab", "PRIVATE-EDGE-bc", "PRIVATE-EDGE-cd")
            ],
        }
        self.state = self.app.approve_structure(self.state, "chain", snapshot, fingerprint(snapshot))
        self.state = self.app.select_structures(self.state, ["chain"])
        edges = self.graph(self.export(), "A")["edges"]
        self.assertEqual({e["id"] for e in edges}, {EDGE_IDS[n] for n in ("ab", "bc", "cd")})
        snapshot["nodes"] = [n for n in snapshot["nodes"] if n["document"] != IDS["B"]]
        snapshot["edges"] = [e for e in snapshot["edges"] if e["id"] == "PRIVATE-EDGE-cd"]
        self.state = self.app.approve_structure(self.state, "partial", snapshot, fingerprint(snapshot))
        self.state = self.app.select_structures(self.state, ["partial"])
        self.assertEqual(self.graph(self.export(), "A")["edges"], [])
        self.assertEqual({e["id"] for e in self.graph(self.export())["edges"]}, {EDGE_IDS["cd"]})

    def test_later_edges_stay_hidden_until_approved_and_revision_compatible(self):
        original = self.export()
        self.assertNotIn(PUBLIC_IDS["F"], json.dumps(original))
        self.assertNotIn(PUBLIC_IDS["G"], json.dumps(original))
        self.state = reviewed_pair(self.app, self.state, IDS["D"], "r2")
        result = self.export()
        self.assertIn(PUBLIC_IDS["G"], json.dumps(result))
        edge = next(e for e in self.graph(result)["edges"] if e["id"] == EDGE_IDS["dg"])
        self.assertEqual(edge["change_note"], {})
        self.assertNotIn(PUBLIC_IDS["F"], json.dumps(result))
        snapshot = {
            "anchor": IDS["E"],
            "nodes": [{"document": IDS[n], "date": month_date(self.state["documents"][IDS[n]])} for n in "EF"],
            "edges": [
                {k: e[k] for k in ("id", "parent", "parent_revision", "child", "child_revision", "questions")}
                for e in self.state["edges"]
                if e["id"] == "PRIVATE-EDGE-ef"
            ],
        }
        self.state = self.app.approve_structure(self.state, "new-branch", snapshot, fingerprint(snapshot))
        self.state = self.app.select_structures(self.state, ["structure-one", "new-branch"])
        self.assertIn(PUBLIC_IDS["F"], json.dumps(self.export()))

    def test_proposed_or_changed_edges_and_stale_months_are_rejected(self):
        for change in ("proposed", "revision", "month"):
            broken = copy.deepcopy(self.state)
            if change == "proposed":
                broken["edges"][0]["state"] = "proposed"
            elif change == "revision":
                next(e for e in broken["edges"] if e["id"] == "PRIVATE-EDGE-cd")["parent_revision"] = "r2"
            else:
                broken["documents"][IDS["E"]]["created_at"] = "2022-09-19T23:45:06Z"
            with self.subTest(change=change), self.assertRaisesRegex(ModelError, "changed; review again"):
                self.export(broken)

    def test_approval_rejects_unrelated_nodes_bad_dates_and_missing_endpoints(self):
        original = self.state["blog"]["structure_approvals"]["structure-one"]
        for change in ("unrelated", "day", "endpoint", "fingerprint"):
            snapshot = {k: copy.deepcopy(original[k]) for k in ("anchor", "nodes", "edges")}
            if change == "unrelated":
                snapshot["nodes"].append({"document": IDS["S"], "date": month_date(self.state["documents"][IDS["S"]])})
            elif change == "day":
                snapshot["nodes"][0]["date"]["value"] = "2020-01-02"
            elif change == "endpoint":
                snapshot["nodes"] = [n for n in snapshot["nodes"] if n["document"] != IDS["B"]]
            fp = "0" * 64 if change == "fingerprint" else fingerprint(snapshot)
            with self.subTest(change=change), self.assertRaises(ModelError):
                self.app.approve_structure(self.state, "bad", snapshot, fp)

    def test_structure_and_identity_records_cannot_be_overwritten(self):
        for kind in ("structure", "identity"):
            broken = copy.deepcopy(self.state)
            if kind == "identity":
                broken["blog"]["identities"]["documents"][IDS["A"]]["slug"] = "changed-slug"
            else:
                broken["blog"]["structure_approvals"]["structure-one"]["approved_at"] = "2020-01-01T00:00:00Z"
            with self.subTest(kind=kind), self.assertRaisesRegex(ModelError, "Immutable"):
                self.repo.save(broken)

    def test_questions_and_notes_require_explicit_labels_and_never_fallback(self):
        self.assertTrue(all(not e["questions"] for e in self.graph(self.export())["edges"]))
        self.state = reviewed_pair(self.app, self.state, IDS["C"], "r1", prefix="next-")
        self.label("question", "q", {"ko": "공개 질문", "en": "Public question"})
        self.label("edge", "PRIVATE-EDGE-ac", {"ko": "공개 설명", "en": "Public explanation"})
        edge = next(e for e in self.graph(self.export())["edges"] if e["id"] == EDGE_IDS["ac"])
        self.assertEqual(len(edge["questions"]), 1)
        self.assertEqual(edge["change_note"], {})
        self.label("question", "other", {"ko": "두 번째 질문"})
        edge = next(e for e in self.graph(self.export())["edges"] if e["id"] == EDGE_IDS["ac"])
        self.assertEqual(edge["change_note"], {"ko": "공개 설명"})
        self.assertEqual(len(edge["questions"]), 2)
        self.assertNotIn("PRIVATE-QUESTION", json.dumps(edge))
        self.label("question", "q", {}, public=False)
        edge = next(e for e in self.graph(self.export())["edges"] if e["id"] == EDGE_IDS["ac"])
        self.assertEqual(edge["change_note"], {})

    def test_nonpublic_endpoint_and_expression_revision_hide_explanations(self):
        self.label("question", "q", {"ko": "질문", "en": "Question"})
        self.label("edge", "PRIVATE-EDGE-cd", {"ko": "설명", "en": "Note"})
        edge = next(e for e in self.graph(self.export())["edges"] if e["id"] == EDGE_IDS["cd"])
        self.assertEqual(edge["change_note"], {})
        self.state = reviewed_pair(self.app, self.state, IDS["C"], "r1", prefix="next-")
        edge = next(e for e in self.graph(self.export())["edges"] if e["id"] == EDGE_IDS["cd"])
        self.assertEqual(edge["change_note"], {"ko": "설명", "en": "Note"})
        self.state = self.app.select_publication(self.state, IDS["D"], None)
        edge = next(e for e in self.graph(self.export())["edges"] if e["id"] == EDGE_IDS["cd"])
        self.assertEqual(edge["change_note"], {})

    def test_export_checks_body_and_attachment_integrity_and_only_returns_allowed_assets(self):
        doc = self.state["documents"][IDS["A"]]
        path = "data/assets/PRIVATE-FILENAME.txt"
        content = b"Synthetic public attachment"
        self.repo.write_bytes_new(path, content)
        self.repo.write_bytes_new("data/assets/PRIVATE-UNSELECTED.txt", b"PRIVATE-ASSET")
        asset = {
            "id": "8b4726bf69a14c2289de710b394d2edc",
            "path": path,
            "sha256": hashlib.sha256(content).hexdigest(),
            "media_type": "text/plain",
        }
        pair = {
            "base_revision": "r1",
            "variants": doc["publication_pairs"]["pair-A"]["variants"],
            "attachments": [asset],
        }
        self.state = self.app.approve_pair(
            self.state, IDS["A"], "with-asset", "r1", pair["variants"], fingerprint(pair_input(doc, pair)), [asset]
        )
        self.state = self.app.select_publication(self.state, IDS["A"], "with-asset")
        bundle = self.app.export_bundle(self.state, RELEASE_TIME)
        self.assertEqual(bundle["assets"], {"assets/" + asset["id"] + ".txt": content})
        self.assertNotIn("PRIVATE-FILENAME", json.dumps(bundle["public"]))
        self.repo.path(path).write_bytes(b"Tampered")
        with self.assertRaisesRegex(ModelError, "attachment changed"):
            self.export()
        self.repo.path(path).write_bytes(content)
        self.state = self.app.select_publication(self.state, IDS["A"], None)
        self.assertEqual(self.app.export_bundle(self.state, RELEASE_TIME)["assets"], {})
        body_path = self.state["documents"][IDS["C"]]["language_variants"]["en-r2"]["body"]["path"]
        self.repo.path(body_path).write_text("Tampered", encoding="utf-8")
        with self.assertRaisesRegex(ModelError, "Variant body changed"):
            self.export()

    def test_identity_creation_is_random_stable_and_export_does_not_assign_ids(self):
        state = copy.deepcopy(self.state)
        state["blog"]["identities"] = {"documents": {}, "edges": {}, "questions": {}}
        memory = MemoryRepository()
        for path in self.root.rglob("*"):
            if path.is_file():
                memory.write_bytes_new(str(path.relative_to(self.root)), path.read_bytes())
        memory.save(state)
        app = Studio(repository=memory)
        with self.assertRaisesRegex(ModelError, "identity missing"):
            app.export_public(state, RELEASE_TIME)
        state = app.prepare_public_identities(state, {IDS["A"]: "synthetic-first"})
        self.assertEqual(app.prepare_public_identities(state), state)
        identities = state["blog"]["identities"]["documents"]
        self.assertEqual(set(identities), {IDS[n] for n in "ABCDEGS"})
        self.assertEqual(identities[IDS["A"]]["slug"], "synthetic-first")
        self.assertNotEqual(identities[IDS["A"]]["id"], PUBLIC_IDS["A"])
        self.assertNotIn(IDS["A"], json.dumps(app.export_public(state, RELEASE_TIME)))

    def test_duplicate_public_ids_and_private_slugs_are_rejected(self):
        for change in ("collision", "slug", "path"):
            broken = copy.deepcopy(self.state)
            identity = broken["blog"]["identities"]["documents"][IDS["A"]]
            if change == "collision":
                identity["id"] = PUBLIC_IDS["B"]
            elif change == "slug":
                identity["slug"] = "q"
            else:
                identity["slug"] = "../private"
            with self.subTest(change=change), self.assertRaises(ModelError):
                self.export(broken)

    def test_cli_export_uses_explicit_time_and_does_not_save(self):
        before = self.repo.metadata.read_bytes()
        command = [
            sys.executable,
            "-B",
            str(Path(__file__).resolve().parents[1] / "scripts/dev.py"),
            "studio",
            "--root",
            str(self.root),
            "export-public",
        ]
        result = subprocess.run(command + ["--planned-at", RELEASE_TIME], capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), self.fixture["expected"])
        self.assertEqual(self.repo.metadata.read_bytes(), before)
        result = subprocess.run(command, capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.repo.metadata.read_bytes(), before)

    def test_series_changes_do_not_change_graph_or_post_order(self):
        before = self.export()
        series = copy.deepcopy(self.state["blog"]["series"][SERIES_IDS[0]])
        series["documents"].reverse()
        series["reviewed_fingerprint"] = fingerprint({k: v for k, v in series.items() if k != "reviewed_fingerprint"})
        self.state = self.app.save_series(self.state, series)
        after = self.export()
        self.assertEqual(before["documents"], after["documents"])
        self.assertEqual(before["genealogies"], after["genealogies"])
        self.assertEqual(after["series"][0]["documents"], list(reversed(before["series"][0]["documents"])))

    def test_dates_keep_precision_and_never_guess_invalid_or_missing_values(self):
        for source, expected in [
            ("2020-02", ("month", "2020-02")),
            ("2020-02-29", ("day", "2020-02-29")),
            ("2020-02-29T23:45:01+09:00", ("day", "2020-02-29")),
            ("2020-02-29T23:45:01Z", ("day", "2020-02-29")),
            ("2020-02-29T24:45:01Z", ("unknown", None)),
            ("2021-02-29", ("unknown", None)),
            ("PRIVATE-DATE", ("unknown", None)),
        ]:
            value = document_date({"source": {"date": source}, "created_at": "2026-01-01T00:00:00Z"})
            self.assertEqual((value["precision"], value["value"]), expected)
        self.assertEqual(document_date({}), {"kind": "unknown", "value": None, "precision": "unknown"})


if __name__ == "__main__":
    unittest.main()
