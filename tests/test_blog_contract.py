"""Check phase-one examples without claiming to implement v4 persistence/export.

These tests establish fixture integrity and golden output boundaries. Later phases
must compare the actual migration and publisher against the same examples.
"""

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from blog_fixtures import EDGE_IDS, IDS, PUBLIC_IDS, RELEASE_TIME, SERIES_IDS, fingerprint, make_fixture, pair_input
from stemma_studio.core.adapters import to_genealogy
from stemma_studio.core.domain import validate
from stemma_studio.core.migrations import upgrade
from stemma_studio.core.repository import FileRepository


class BlogContractTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.fixture = make_fixture(self.root)
        self.legacy = self.fixture["legacy"]
        self.future = self.fixture["future"]
        self.public = self.fixture["expected"]

    def test_fixture_requires_empty_explicit_destination(self):
        before = (self.root / "data/studio.json").read_bytes()
        with self.assertRaisesRegex(ValueError, "empty temporary"):
            make_fixture(self.root)
        self.assertEqual((self.root / "data/studio.json").read_bytes(), before)

    def test_legacy_snapshot_is_valid_and_future_example_does_not_migrate_it(self):
        validate(upgrade(self.legacy))
        self.assertEqual(FileRepository(self.root).load(), upgrade(self.legacy))
        self.assertEqual(self.legacy["schema_version"], 3)
        self.assertEqual(self.future["schema_version"], 4)
        self.assertEqual(to_genealogy(self.legacy), to_genealogy(self.future))
        for did, old in self.legacy["documents"].items():
            new = self.future["documents"][did]
            for key in ("revisions", "current_revision", "archived", "source", "questions"):
                self.assertEqual(new[key], old[key])
            self.assertEqual(new["publication"]["legacy_v3"], old["publication"])
        self.assertEqual(self.future["edges"], self.legacy["edges"])

    def test_branch_merge_private_middle_and_unrelated_components(self):
        graph = to_genealogy(self.legacy)
        component = graph.connected_components([IDS["C"]])[0]
        self.assertEqual(set(component["nodes"]), {IDS[n] for n in "ABCDEFG"})
        self.assertEqual(len(component["edges"]), 7)
        pairs = {(e.parent.document, e.child.document) for e in component["edges"]}
        for parent, child in ("AB", "AC", "BC", "CD", "CE"):
            self.assertIn((IDS[parent], IDS[child]), pairs)
        self.assertEqual(graph.connected_components([IDS["S"]])[0]["nodes"], (IDS["S"],))
        self.assertEqual(len(self.legacy["documents"]), 813)
        self.assertTrue(self.legacy["documents"][IDS["B"]]["archived"])
        self.assertEqual(self.legacy["questions"]["other"]["representatives"], [IDS["B"]])
        self.assertTrue(self.legacy["questions"]["q"]["public"])
        self.assertFalse(self.legacy["questions"]["other"]["public"])

    def test_variant_bytes_reviews_and_pairs_are_pinned_to_exact_revisions(self):
        repository = FileRepository(self.root)
        for doc in self.future["documents"].values():
            revisions = {r["id"]: r for r in doc["revisions"]}
            for vid, variant in doc["language_variants"].items():
                self.assertEqual(vid, variant["id"])
                self.assertIn(variant["base_revision"], revisions)
                body = repository.read_bytes(variant["body"]["path"])
                self.assertTrue(body.decode("utf-8").strip())
                self.assertEqual(hashlib.sha256(body).hexdigest(), variant["body"]["sha256"])
                if variant["body"]["kind"] == "base_revision":
                    revision = revisions[variant["base_revision"]]
                    self.assertEqual(variant["body"]["path"], revision["path"])
                    self.assertEqual(variant["body"]["sha256"], revision["sha256"])
            for pair in doc["publication_pairs"].values():
                self.assertEqual(set(pair["variants"]), {"ko", "en"})
                for lang, vid in pair["variants"].items():
                    variant = doc["language_variants"][vid]
                    self.assertEqual(variant["language"], lang)
                    self.assertEqual(variant["base_revision"], pair["base_revision"])
                    self.assertEqual(doc["variant_reviews"][vid]["fingerprint"], fingerprint(variant))
                self.assertEqual(pair["fingerprint"], fingerprint(pair_input(doc, pair)))
        doc = self.future["documents"][IDS["C"]]
        self.assertNotIn("en-r2-draft", doc["variant_reviews"])
        self.assertEqual(doc["publication_pairs"]["pair-C"]["variants"]["en"], "en-r2")
        self.assertEqual(doc["language_variants"]["en-r1"]["base_revision"], "r1")
        changed = copy.deepcopy(doc)
        changed["language_variants"]["en-r2"]["title"] = "Changed after review"
        self.assertNotEqual(
            fingerprint(pair_input(changed, changed["publication_pairs"]["pair-C"])),
            doc["publication_pairs"]["pair-C"]["fingerprint"],
        )

    def test_structure_snapshot_excludes_later_edge_and_pins_dates(self):
        approval = self.future["blog"]["structure_approvals"]["structure-one"]
        self.assertEqual(
            approval["fingerprint"], fingerprint({key: approval[key] for key in ("anchor", "nodes", "edges")})
        )
        self.assertNotIn("PRIVATE-EDGE-ef", {edge["id"] for edge in approval["edges"]})
        self.assertNotIn(IDS["F"], {node["document"] for node in approval["nodes"]})
        dates = {node["document"]: node["date"] for node in approval["nodes"]}
        self.assertEqual(dates[IDS["B"]], {"kind": "unknown", "value": None})
        self.assertEqual(dates[IDS["E"]], {"kind": "created", "value": "2022-08"})
        edge = next(e for e in approval["edges"] if e["id"] == "PRIVATE-EDGE-dg")
        self.assertEqual(edge["parent_revision"], "r2")
        doc = self.future["documents"][IDS["D"]]
        self.assertEqual(doc["publication_pairs"]["pair-D"]["base_revision"], "r1")

    def test_release_example_freezes_review_and_retry_timestamp(self):
        blog = self.future["blog"]
        release = blog["releases"]["release-one"]
        self.assertEqual(release["input_fingerprint"], fingerprint(self.fixture["review_input"]))
        content = FileRepository(self.root).read_bytes(release["public_snapshot"])
        self.assertEqual(hashlib.sha256(content).hexdigest(), release["public_sha256"])
        self.assertEqual(json.loads(content), self.public)
        self.assertEqual(release["planned_published_at"], RELEASE_TIME)
        self.assertEqual([a["status"] for a in blog["release_attempts"]], ["failed", "running"])
        self.assertEqual({a["release"] for a in blog["release_attempts"]}, {"release-one"})
        self.assertIsNone(blog["active_release"])
        self.assertTrue(all(d["publication"]["first_published_at"] is None for d in self.future["documents"].values()))
        previous = copy.deepcopy(release["series_snapshot"])
        blog["series"][SERIES_IDS[0]]["documents"].reverse()
        self.assertEqual(release["series_snapshot"], previous)

    def test_golden_has_exact_public_allowlists_and_no_private_sentinels(self):
        self.assertEqual(set(self.public), {"schema_version", "documents", "genealogies", "series"})
        self.assertEqual(self.public["schema_version"], 3)
        serialized = json.dumps(self.public, ensure_ascii=False)
        for sentinel in self.fixture["sentinels"]:
            self.assertNotIn(sentinel, serialized)
        for doc in self.public["documents"]:
            self.assertEqual(
                set(doc), {"id", "slug", "translations", "date", "first_published_at", "published_updated_at", "assets"}
            )
            self.assertRegex(doc["id"], r"^[0-9a-f]{32}$")
            self.assertEqual(set(doc["translations"]), {"ko", "en"})
            for text in doc["translations"].values():
                self.assertEqual(set(text), {"title", "summary", "body"})
                self.assertTrue(text["title"].strip())
                self.assertTrue(text["body"].strip())
            self.assertEqual(set(doc["date"]), {"kind", "value", "precision"})
            did = next(
                did
                for did, identity in self.future["blog"]["identities"]["documents"].items()
                if identity["id"] == doc["id"]
            )
            private = self.future["documents"][did]
            pair = private["publication_pairs"][private["publication"]["selected_pair"]]
            for lang, vid in pair["variants"].items():
                variant = private["language_variants"][vid]
                self.assertEqual(
                    doc["translations"][lang],
                    {
                        "title": variant["title"],
                        "summary": variant["summary"],
                        "body": FileRepository(self.root).read_text(variant["body"]["path"]),
                    },
                )
        for graph in self.public["genealogies"]:
            self.assertEqual(set(graph), {"document", "scope_label", "nodes", "edges"})
            self.assertEqual(graph["scope_label"], "approved_genealogy")
            for node in graph["nodes"]:
                self.assertEqual(set(node), {"id", "kind"} if node["kind"] == "public" else {"id", "kind", "month"})
            for edge in graph["edges"]:
                self.assertEqual(set(edge), {"id", "parent", "child", "questions", "change_note"})
                self.assertEqual(edge["questions"], [])
                self.assertEqual(edge["change_note"], {})
        for series in self.public["series"]:
            self.assertEqual(set(series), {"id", "slug", "translations", "documents"})

    def test_golden_components_preserve_middle_without_late_or_unrelated_nodes(self):
        graphs = {g["document"]: g for g in self.public["genealogies"]}
        public_ids = {d["id"] for d in self.public["documents"]}
        self.assertEqual(set(graphs), public_ids)
        for name in ("A", "C", "D"):
            graph = graphs[PUBLIC_IDS[name]]
            self.assertEqual({n["id"] for n in graph["nodes"]}, {PUBLIC_IDS[n] for n in "ABCDE"})
            self.assertEqual({e["id"] for e in graph["edges"]}, {EDGE_IDS[n] for n in ("ab", "ac", "bc", "cd", "ce")})
            for edge in graph["edges"]:
                self.assertIn(edge["parent"], {n["id"] for n in graph["nodes"]})
                self.assertIn(edge["child"], {n["id"] for n in graph["nodes"]})
            self.assertEqual([n["id"] for n in graph["nodes"]], sorted(n["id"] for n in graph["nodes"]))
            middle = next(n for n in graph["nodes"] if n["id"] == PUBLIC_IDS["B"])
            self.assertEqual(middle, {"id": PUBLIC_IDS["B"], "kind": "unpublished", "month": None})
        self.assertEqual(graphs[PUBLIC_IDS["S"]]["edges"], [])
        self.assertEqual(len(graphs[PUBLIC_IDS["S"]]["nodes"]), 1)

    def test_golden_series_filters_private_gaps_and_preserves_author_order(self):
        series = self.public["series"]
        self.assertEqual([s["id"] for s in series], list(SERIES_IDS[:2]))
        self.assertEqual(series[0]["documents"], [PUBLIC_IDS["C"], PUBLIC_IDS["A"]])
        self.assertEqual(series[1]["documents"], [PUBLIC_IDS["D"], PUBLIC_IDS["C"]])
        for item in self.future["blog"]["series"].values():
            payload = {k: v for k, v in item.items() if k != "reviewed_fingerprint"}
            self.assertEqual(item["reviewed_fingerprint"], fingerprint(payload))
            self.assertEqual(len(item["documents"]), len(set(item["documents"])))
        # Publication times tie: creation/source dates order posts, with unknown last.
        documents = self.public["documents"]
        self.assertEqual([d["id"] for d in documents], [PUBLIC_IDS[i] for i in ("D", "C", "A", "S")])
        self.assertNotEqual(series[0]["documents"], [d["id"] for d in documents[:2]])


if __name__ == "__main__":
    unittest.main()
