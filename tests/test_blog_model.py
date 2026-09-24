"""Bilingual storage/migration regressions use disposable roots and fake bodies."""

import copy
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from blog_fixtures import make_fixture
from blog_test_support import reviewed_pair
from stemma_studio.core import blog
from stemma_studio.core.adapters import to_genealogy
from stemma_studio.core.application import Studio
from stemma_studio.core.domain import ModelError, empty_state, set_publication
from stemma_studio.core.migrations import upgrade
from stemma_studio.core.repository import FileRepository, MemoryRepository


class BlogModelTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.repo = FileRepository(self.root)
        self.app = Studio(repository=self.repo)
        state = empty_state()
        state["questions"]["q"] = {"text": "Synthetic question?", "public": False, "representatives": []}
        state = self.app.create_draft(state, "a", "Synthetic A", ["q"], "기준 본문\r\n", [], "Initial")
        self.state = self.app.confirm(state, "a")

    def variant(self, lang="ko", vid=None, revision="r1", body=None, review=True):
        vid = vid or lang + "-" + revision
        if lang == "en" and body is None:
            body = "English text\r\n"
        self.state = self.app.save_variant(self.state, "a", vid, revision, lang, "Title " + lang, body)
        if review:
            value = self.state["documents"]["a"]["language_variants"][vid]
            self.state = self.app.review_variant(self.state, "a", vid, blog.fingerprint(value))
        return vid

    def approve(self, variants=None, revision="r1", pid="pair-one", attachments=()):
        variants = variants or {"ko": "ko-r1", "en": "en-r1"}
        pair = {"base_revision": revision, "variants": variants, "attachments": list(attachments)}
        fp = blog.fingerprint(blog.pair_input(self.state["documents"]["a"], pair))
        self.state = self.app.approve_pair(self.state, "a", pid, revision, variants, fp, attachments)

    def test_storage_review_selection_preserve_graph_and_original_bytes(self):
        before = copy.deepcopy(self.state)
        original = self.repo.read_bytes("data/revisions/a/r1.md")
        self.variant()
        self.variant("en")
        self.approve()
        self.assertIsNone(self.state["documents"]["a"]["publication"]["selected_pair"])
        self.state = self.app.select_publication(self.state, "a", "pair-one")
        self.assertEqual(self.app.read_pair(self.state, "a", "pair-one")["en"]["body"], "English text\r\n")
        self.assertEqual(self.repo.read_bytes("data/revisions/a/r1.md"), original)
        self.assertEqual(to_genealogy(before), to_genealogy(self.state))
        self.assertEqual(self.state["documents"]["a"]["revisions"], before["documents"]["a"]["revisions"])
        self.assertIsNone(self.state["blog"]["active_release"])
        self.assertIsNone(self.state["documents"]["a"]["publication"]["first_published_at"])
        self.assertEqual(self.app.load(auto_sync=False), self.state)

    def test_one_language_unreviewed_and_cross_revision_pairs_are_rejected(self):
        self.variant()
        for variants in ({"ko": "ko-r1"}, {"en": "ko-r1"}):
            with self.assertRaisesRegex(ModelError, "both ko and en"):
                self.approve(variants)
        self.variant("en", review=False)
        with self.assertRaisesRegex(ModelError, "reviewed variants"):
            self.approve()
        self.state = self.app.add_revision(self.state, "a", "두 번째 판본", "Polish")
        self.variant("en", revision="r2")
        with self.assertRaisesRegex(ModelError, "same base revision"):
            self.approve({"ko": "ko-r1", "en": "en-r2"})
        self.assertEqual(self.state["documents"]["a"]["publication_pairs"], {})

    def test_blank_title_body_language_and_path_ids_fail_before_writes(self):
        baseline = {str(p.relative_to(self.root)) for p in self.root.rglob("*") if p.is_file()}
        for vid, lang, title, body in [
            ("bad-title", "en", " ", "text"),
            ("bad-body", "en", "Title", " \n"),
            ("bad-lang", "fr", "Title", "text"),
            ("../escape", "en", "Title", "text"),
        ]:
            with self.subTest(vid=vid), self.assertRaises(ModelError):
                self.app.save_variant(self.state, "a", vid, "r1", lang, title, body)
        self.assertEqual({str(p.relative_to(self.root)) for p in self.root.rglob("*") if p.is_file()}, baseline)

    def test_same_variant_retry_is_idempotent_and_different_bytes_are_rejected(self):
        original_request = self.state
        self.variant("en", review=False)
        saved = self.state
        self.assertEqual(
            self.app.save_variant(original_request, "a", "en-r1", "r1", "en", "Title en", "English text\r\n"), saved
        )
        with self.assertRaisesRegex(ModelError, "different content"):
            self.app.save_variant(saved, "a", "en-r1", "r1", "en", "Title en", "different")
        self.assertEqual(self.app.load(auto_sync=False), saved)

    def test_failed_metadata_save_reuses_identical_orphan_translation(self):
        with patch.object(self.repo, "save", side_effect=OSError("Synthetic failure")):
            with self.assertRaises(OSError):
                self.variant("en", review=False)
        self.assertEqual(self.app.load(auto_sync=False), self.state)
        path = "data/translations/a/en-r1.md"
        self.assertEqual(self.repo.read_text(path), "English text\r\n")
        with self.assertRaisesRegex(ModelError, "destination differs"):
            self.app.save_variant(self.state, "a", "en-r1", "r1", "en", "Title en", "Different orphan")
        self.variant("en", review=False)
        self.assertEqual(self.repo.read_text(path), "English text\r\n")

    def test_stale_state_and_review_fingerprints_are_rejected(self):
        old = self.state
        self.state = self.app.add_revision(self.state, "a", "New base", "Polish")
        with self.assertRaisesRegex(ModelError, "Studio changed"):
            self.app.save_variant(old, "a", "stale", "r1", "en", "Old draft", "Text")
        self.variant("en", review=False)
        with self.assertRaisesRegex(ModelError, "review again"):
            self.app.review_variant(self.state, "a", "en-r1", "0" * 64)
        self.assertFalse(self.repo.path("data/translations/a/stale.md").exists())

    def test_pair_approval_fingerprint_and_retries(self):
        self.variant()
        self.variant("en")
        with self.assertRaisesRegex(ModelError, "fingerprint changed"):
            self.app.approve_pair(self.state, "a", "pair-one", "r1", {"ko": "ko-r1", "en": "en-r1"}, "0" * 64)
        old = self.state
        self.approve()
        pair = self.state["documents"]["a"]["publication_pairs"]["pair-one"]
        self.assertEqual(
            self.app.approve_pair(old, "a", "pair-one", "r1", pair["variants"], pair["fingerprint"]), self.state
        )

    def test_new_translation_does_not_replace_selected_pair_or_reuse_review(self):
        self.state = reviewed_pair(self.app, self.state, "a", "r1")
        previous = copy.deepcopy(self.state["documents"]["a"]["publication"])
        old_text = self.app.read_pair(self.state, "a", "pair-r1")
        self.variant("en", vid="en-new", body="New English", review=False)
        self.assertNotIn("en-new", self.state["documents"]["a"]["variant_reviews"])
        self.assertEqual(self.state["documents"]["a"]["publication"], previous)
        self.assertEqual(self.app.read_pair(self.state, "a", "pair-r1"), old_text)
        self.state = self.app.select_publication(self.state, "a", None)
        self.assertIsNone(self.state["documents"]["a"]["publication"]["selected_pair"])
        self.assertEqual(self.app.read_pair(self.state, "a", "pair-r1"), old_text)

    def test_repository_rejects_immutable_metadata_rewrite_or_removal(self):
        self.variant("en", review=False)
        for remove in (True, False):
            broken = copy.deepcopy(self.state)
            variants = broken["documents"]["a"]["language_variants"]
            if remove:
                variants.clear()
            else:
                variants["en-r1"]["title"] = "Changed title"
            with self.assertRaisesRegex(ModelError, "Immutable blog record changed"):
                self.repo.save(broken)
        self.assertEqual(self.app.load(auto_sync=False), self.state)

    def test_reviews_pairs_and_legacy_records_cannot_be_rewritten(self):
        self.state = reviewed_pair(self.app, self.state, "a", "r1")
        for kind in ("review", "pair", "legacy"):
            broken = copy.deepcopy(self.state)
            doc = broken["documents"]["a"]
            if kind == "review":
                doc["variant_reviews"]["en-r1"]["reviewed_at"] = "2020-01-01T00:00:00Z"
            elif kind == "pair":
                doc["publication_pairs"]["pair-r1"]["approved_at"] = "2020-01-01T00:00:00Z"
            else:
                doc["publication"]["legacy_v3"] = {"published": False, "revision": None}
            with self.subTest(kind=kind), self.assertRaisesRegex(ModelError, "immutable|Immutable"):
                self.repo.save(broken)

    def test_unknown_release_and_malformed_structure_approval_are_rejected(self):
        for key, value in (("active_release", "made-up-release"), ("structure_approvals", {"made-up": {}})):
            broken = copy.deepcopy(self.state)
            broken["blog"][key] = value
            with self.subTest(key=key), self.assertRaises(ModelError):
                self.repo.save(broken)

    def test_tampered_translation_is_detected_on_load_and_local_pair_read(self):
        self.state = reviewed_pair(self.app, self.state, "a", "r1")
        self.repo.path("data/translations/a/en-r1.md").write_text("Tampered", encoding="utf-8")
        with self.assertRaisesRegex(ModelError, "Variant body changed"):
            self.app.load(auto_sync=False)
        with self.assertRaisesRegex(ModelError, "Variant body changed"):
            self.app.read_pair(self.state, "a", "pair-r1")

    def test_pair_attachments_require_existing_bytes_matching_hash(self):
        self.variant()
        self.variant("en")
        asset = {
            "id": "a" * 32,
            "path": "data/assets/synthetic.txt",
            "sha256": hashlib.sha256(b"asset").hexdigest(),
            "media_type": "text/plain",
        }
        with self.assertRaises(FileNotFoundError):
            self.approve(attachments=[asset])
        self.repo.write_bytes_new(asset["path"], b"asset")
        wrong = dict(asset, sha256="0" * 64)
        with self.assertRaisesRegex(ModelError, "attachment changed"):
            self.approve(attachments=[wrong])
        self.approve(attachments=[asset])
        self.assertEqual(self.app.load(auto_sync=False), self.state)

    def series(self, public=False):
        value = {
            "id": "b" * 32,
            "slug": "test-series",
            "public": public,
            "translations": {lang: {"title": lang + " series", "summary": None} for lang in ("ko", "en")},
            "documents": ["a"],
        }
        value["reviewed_fingerprint"] = blog.fingerprint(value) if public else None
        return value

    def test_series_review_duplicate_members_and_manual_order(self):
        before = copy.deepcopy(self.state)
        series = self.series(public=True)
        for field, value in [
            ("documents", ["a", "a"]),
            ("translations", {"ko": {"title": "Only ko", "summary": None}}),
            ("reviewed_fingerprint", None),
        ]:
            broken = copy.deepcopy(series)
            broken[field] = value
            with self.subTest(field=field), self.assertRaises(ModelError):
                self.app.save_series(self.state, broken)
        self.state = self.app.save_series(self.state, series)
        self.assertEqual(to_genealogy(self.state), to_genealogy(before))
        self.assertEqual(self.state["documents"], before["documents"])
        changed = copy.deepcopy(series)
        changed["translations"]["en"]["title"] = "Edited name"
        with self.assertRaisesRegex(ModelError, "Stale series review"):
            self.app.save_series(self.state, changed)
        second = self.series()
        second.update(id="c" * 32, slug="second")
        self.state = self.app.save_series(self.state, second)
        self.state = self.app.order_series(self.state, [second["id"], series["id"]])
        self.assertEqual(self.state["blog"]["series_order"], [second["id"], series["id"]])
        with self.assertRaisesRegex(ModelError, "Invalid series order"):
            self.app.order_series(self.state, [series["id"], series["id"]])

    def test_summary_pair_and_draft_pair_are_rejected(self):
        self.state = self.app.save_variant(self.state, "a", "ko-r1", "r1", "ko", "KO", summary="소개")
        value = self.state["documents"]["a"]["language_variants"]["ko-r1"]
        self.state = self.app.review_variant(self.state, "a", "ko-r1", blog.fingerprint(value))
        self.variant("en")
        with self.assertRaisesRegex(ModelError, "summaries require both"):
            self.approve()
        draft = self.app.create_draft(self.state, "draft", "Draft", [], "Draft body", [], "Initial")
        with self.assertRaisesRegex(ModelError, "confirmed document"):
            self.app.approve_pair(draft, "draft", "pair-draft", "r1", {}, "0" * 64)

    def test_revision_only_publish_and_undated_export_fail_closed(self):
        with self.assertRaisesRegex(ModelError, "bilingual pair ID"):
            set_publication(self.state, "a", "r1")
        self.assertEqual(
            self.app.export_public(self.state), {"schema_version": 3, "documents": [], "genealogies": [], "series": []}
        )
        self.state = reviewed_pair(self.app, self.state, "a", "r1")
        with self.assertRaisesRegex(ModelError, "explicit planned publication time"):
            self.app.export_public(self.state)
        command = [
            sys.executable,
            "-B",
            str(Path(__file__).resolve().parents[1] / "scripts/dev.py"),
            "studio",
            "--root",
            str(self.root),
            "--no-sync",
        ]
        before = self.repo.metadata.read_bytes()
        result = subprocess.run(command + ["publish", "a", "--revision", "r1"], capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.repo.metadata.read_bytes(), before)
        result = subprocess.run(command + ["unpublish", "a"], capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        result = subprocess.run(command + ["publish", "a", "--pair", "pair-r1"], capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(json.loads(result.stdout)["deployed"])

    def test_repository_paths_reject_unsafe_and_symlink_escape(self):
        for path in ("/tmp/outside", "../escape", "data/../escape", "data\\escape", "data//escape"):
            with self.subTest(path=path), self.assertRaises(ModelError):
                self.repo.read_text(path)
        with tempfile.TemporaryDirectory() as outside:
            (self.root / "outside").symlink_to(outside, target_is_directory=True)
            with self.assertRaises(ModelError):
                self.repo.write_new("outside/file.md", "No escape")
            self.assertEqual(list(Path(outside).iterdir()), [])

    def test_memory_repository_has_same_bilingual_workflow_and_immutability(self):
        memory = MemoryRepository()
        for doc in self.state["documents"].values():
            for revision in doc["revisions"]:
                memory.write_new(revision["path"], self.repo.read_text(revision["path"]))
        memory.save(self.state)
        app = Studio(repository=memory)
        state = reviewed_pair(app, self.state, "a", "r1")
        self.assertEqual(app.read_pair(state, "a", "pair-r1")["ko"]["body"], "기준 본문\r\n")
        broken = copy.deepcopy(state)
        broken["documents"]["a"]["publication_pairs"].clear()
        broken["documents"]["a"]["publication"]["selected_pair"] = None
        with self.assertRaisesRegex(ModelError, "Immutable blog record"):
            memory.save(broken)


class BlogMigrationTests(unittest.TestCase):
    def test_v3_fixture_migration_is_lossless_and_backup_is_exact(self):
        with tempfile.TemporaryDirectory() as folder:
            fixture = make_fixture(folder, unrelated=0)
            repo = FileRepository(folder)
            original = repo.metadata.read_bytes()
            files = {str(p.relative_to(folder)): p.read_bytes() for p in Path(folder).rglob("*") if p.is_file()}
            state = repo.load()
            self.assertEqual(state["schema_version"], 4)
            self.assertEqual(repo.metadata.read_bytes(), original)
            self.assertFalse(repo.path("data/migrations/studio-v3.json").exists())
            self.assertEqual(to_genealogy(state), to_genealogy(fixture["legacy"]))
            for did, doc in state["documents"].items():
                self.assertEqual(doc["publication"]["legacy_v3"], fixture["legacy"]["documents"][did]["publication"])
                self.assertIsNone(doc["publication"]["selected_pair"])
            self.assertEqual(Studio(repository=repo).export_public(state)["documents"], [])
            repo.save(state)
            self.assertEqual(repo.read_bytes("data/migrations/studio-v3.json"), original)
            for path, content in files.items():
                if path != "data/studio.json":
                    self.assertEqual(repo.read_bytes(path), content)
            self.assertEqual(repo.load(), state)
            repo.save(state)
            self.assertEqual(repo.read_bytes("data/migrations/studio-v3.json"), original)

    def test_conflicting_v3_backup_blocks_metadata_replacement(self):
        with tempfile.TemporaryDirectory() as folder:
            make_fixture(folder, unrelated=0)
            repo = FileRepository(folder)
            original = repo.metadata.read_bytes()
            repo.write_new("data/migrations/studio-v3.json", "different backup")
            with self.assertRaisesRegex(ModelError, "Migration backup differs"):
                repo.save(repo.load())
            self.assertEqual(repo.metadata.read_bytes(), original)

    def test_cannot_erase_blog_state_by_downgrading_version(self):
        state = empty_state()
        state["schema_version"] = 3
        with self.assertRaisesRegex(ModelError, "already contains blog"):
            upgrade(state)


if __name__ == "__main__":
    unittest.main()
