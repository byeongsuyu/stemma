"""Importing a plain folder of Markdown and its pictures, without Git."""

import base64
import hashlib
import tempfile
import unittest
from pathlib import Path

from stemma_studio.blog.admin import Admin, Conflict
from stemma_studio.blog.attachments import referenced_attachments
from stemma_studio.core.application import Studio
from stemma_studio.core.domain import ModelError, empty_state
from stemma_studio.core.folder_import import apply_import, derive_id, read_front_matter, scan
from stemma_studio.core.repository import FileRepository

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


class IdentityTests(unittest.TestCase):
    def test_path_and_name_rules(self):
        self.assertEqual(derive_id("posts/2009/cat.md", "path"), "posts-2009-cat")
        self.assertEqual(derive_id("posts/2009/cat.md", "name"), "cat")

    def test_a_name_with_no_ascii_gets_a_stable_digest(self):
        first = derive_id("글/고양이.md", "path")
        self.assertTrue(first.startswith("doc-"))
        self.assertEqual(first, derive_id("글/고양이.md", "path"))
        self.assertNotEqual(first, derive_id("글/강아지.md", "path"))

    def test_front_matter_is_optional(self):
        metadata, body = read_front_matter("# Just a heading\n\ntext\n")
        self.assertEqual(metadata, {})
        self.assertTrue(body.startswith("# Just a heading"))
        metadata, body = read_front_matter('---\nid: x\ntitle: "T"\n---\n\nbody\n')
        self.assertEqual(metadata["id"], "x")
        self.assertEqual(metadata["title"], "T")
        self.assertEqual(body.strip(), "body")


class FolderImportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.src = Path(self.temp.name).resolve() / "old-blog"
        (self.src / "posts" / "images").mkdir(parents=True)
        (self.src / "shared").mkdir()
        self.root = Path(self.temp.name) / "studio"
        Studio(self.root).save(empty_state())
        self.repo = FileRepository(self.root)

    def write(self, relative, text):
        path = self.src / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def picture(self, relative, salt=b""):
        path = self.src / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(PNG + salt)

    def scan(self, rule="path"):
        return scan(self.repo.load(), str(self.src), rule)

    def apply(self, rule="path"):
        return apply_import(self.repo, self.scan(rule))

    def test_a_folder_of_posts_and_pictures_is_imported(self):
        self.write("posts/a.md", '---\ntitle: "On reading again"\ndate: 2009-04-11\n---\n\n![](images/cat.png)\n')
        self.picture("posts/images/cat.png")
        report = self.scan().report
        self.assertEqual(report["counts"]["new"], 1)
        self.assertEqual(report["new"][0]["id"], "posts-a")
        self.assertEqual(report["new"][0]["title"], "On reading again")
        self.assertEqual(report["new"][0]["date"], "2009-04-11")
        self.assertEqual(report["new"][0]["images"], 1)

    def test_every_way_of_writing_a_picture_link_still_finds_it_after_import(self):
        """The point of the whole design: bodies are never rewritten."""
        self.write("posts/a.md", "# A\n\n![](images/cat.png)\n")
        self.write("posts/b.md", "# B\n\n![](./images/dog.png)\n")
        self.write("posts/c.md", "# C\n\n![](../shared/logo.jpg)\n")
        self.write("d.md", "# D\n\n![](posts/images/cat.png)\n")
        self.picture("posts/images/cat.png")
        self.picture("posts/images/dog.png", b"1")
        self.picture("shared/logo.jpg", b"2")
        state, _ = self.apply()
        self.assertEqual(len(state["documents"]), 4)
        for doc in state["documents"].values():
            body = self.repo.read_text(doc["revisions"][0]["path"])
            self.assertTrue(referenced_attachments(state, doc, body), doc["source"]["relative_path"])

    def test_identical_pictures_are_stored_once(self):
        self.write("posts/a.md", "# A\n\n![](images/cat.png)\n")
        self.write("posts/b.md", "# B\n\n![](images/copy.png)\n")
        self.picture("posts/images/cat.png")
        self.picture("posts/images/copy.png")
        state, _ = self.apply()
        stored = {a["snapshot"] for d in state["documents"].values() for a in d["source"]["assets"]}
        self.assertEqual(len(stored), 1)

    def test_a_missing_picture_warns_but_still_imports_the_post(self):
        self.write("posts/c.md", "# C\n\n![](images/nope.png)\n")
        report = self.scan().report
        self.assertEqual(report["counts"]["new"], 1)
        self.assertEqual(report["warnings"][0]["reason"], "image_not_found")
        self.assertEqual(report["warnings"][0]["detail"], "images/nope.png")

    def test_duplicate_identifiers_are_skipped_and_named(self):
        self.write("2009/cat.md", "# one\n\ntext\n")
        self.write("2011/cat.md", "# two\n\ntext\n")
        report = self.scan("name").report
        self.assertEqual(report["counts"]["new"], 1)
        skipped = report["skipped"][0]
        self.assertEqual(skipped["reason"], "duplicate_id")
        self.assertEqual(skipped["id"], "cat")
        self.assertTrue(skipped["detail"])

    def test_an_identifier_in_front_matter_wins(self):
        self.write("posts/a.md", "---\nid: my-own-id\n---\n\ntext\n")
        self.assertEqual(self.scan().report["new"][0]["id"], "my-own-id")

    def test_empty_and_unreadable_files_are_skipped(self):
        self.write("posts/blank.md", "   \n")
        (self.src / "posts" / "bytes.md").write_bytes(b"\xff\xfe not utf-8")
        self.write("posts/ok.md", "# ok\n\ntext\n")
        report = self.scan().report
        self.assertEqual(report["counts"]["new"], 1)
        self.assertEqual({s["reason"] for s in report["skipped"]}, {"empty", "unreadable"})

    def test_reimporting_is_idempotent_and_changed_content_is_refused(self):
        self.write("posts/a.md", "# A\n\ntext\n")
        self.apply()
        report = self.scan().report
        self.assertEqual((report["counts"]["new"], report["counts"]["unchanged"]), (0, 1))
        self.write("posts/a.md", "# A\n\nrewritten elsewhere\n")
        report = self.scan().report
        self.assertEqual(report["counts"]["new"], 0)
        self.assertEqual(report["skipped"][0]["reason"], "content_changed")

    def test_a_picture_added_after_the_import_is_attached_by_rescanning(self):
        # The obvious fix for a missing picture is to put it where the writing says it is
        # and scan again. Nothing else can attach it: the writing has not changed, so the
        # document is never re-imported, and the picture would be an orphan forever.
        self.write("posts/a.md", "# A\n\n![](images/cat.png)\n")
        state, first = self.apply()
        self.assertEqual(state["documents"]["posts-a"]["source"]["missing_assets"], ["images/cat.png"])
        self.assertEqual(first["warnings"][0]["reason"], "image_not_found")
        self.picture("posts/images/cat.png")
        state, report = self.apply()
        self.assertEqual(report["status"], "imported")
        self.assertEqual((report["counts"]["new"], report["counts"]["recovered"]), (0, 1))
        self.assertEqual(report["recovered"][0], {"id": "posts-a", "path": "posts/a.md", "images": 1})
        self.assertEqual(report["orphan_assets"], [])
        source = state["documents"]["posts-a"]["source"]
        self.assertEqual([a["archive_path"] for a in source["assets"]], ["posts/images/cat.png"])
        self.assertEqual(source["missing_assets"], [])
        # The writing is untouched and the link in it now finds the picture.
        document = state["documents"]["posts-a"]
        body = self.repo.read_text(document["revisions"][0]["path"])
        self.assertEqual(body, "# A\n\n![](images/cat.png)\n")
        self.assertTrue(referenced_attachments(state, document, body))

    def test_a_rescan_does_not_call_an_attached_picture_unused(self):
        self.write("posts/a.md", "# A\n\n![](images/cat.png)\n")
        self.picture("posts/images/cat.png")
        self.apply()
        report = self.scan().report
        self.assertEqual(report["counts"]["unchanged"], 1)
        self.assertEqual(report["counts"]["recovered"], 0)
        self.assertEqual(report["orphan_assets"], [])

    def test_a_rescan_never_replaces_a_picture_the_document_already_has(self):
        # Changing the bytes under an imported picture is a content change like any other,
        # and those are reported rather than applied. Only a link with nothing behind it
        # is repaired.
        self.write("posts/a.md", "# A\n\n![](images/cat.png)\n")
        self.picture("posts/images/cat.png")
        state, _ = self.apply()
        before = state["documents"]["posts-a"]["source"]["assets"]
        self.picture("posts/images/cat.png", b"different bytes")
        state, report = self.apply()
        self.assertEqual(report["status"], "nothing_to_import")
        self.assertEqual(report["counts"]["recovered"], 0)
        self.assertEqual(state["documents"]["posts-a"]["source"]["assets"], before)

    def test_unused_pictures_and_remote_links_are_reported_not_imported(self):
        self.write("posts/a.md", "# A\n\n![](https://example.test/x.png)\n")
        self.picture("posts/images/unused.png")
        report = self.scan().report
        self.assertEqual(report["orphan_assets"], ["posts/images/unused.png"])
        self.assertEqual(report["remote_links"], 1)
        state, _ = self.apply()
        self.assertEqual(state["documents"]["posts-a"]["source"]["assets"], [])

    def test_the_source_folder_is_never_modified(self):
        self.write("posts/a.md", "# A\n\n![](images/cat.png)\n")
        self.picture("posts/images/cat.png")
        before = {p: p.read_bytes() for p in sorted(self.src.rglob("*")) if p.is_file()}
        self.apply()
        after = {p: p.read_bytes() for p in sorted(self.src.rglob("*")) if p.is_file()}
        self.assertEqual(before, after)

    def test_the_original_file_is_preserved_byte_for_byte(self):
        original = "---\nid: keep\nkind: post\nvisibility: unreviewed\n---\n\n# Kept\n\ntext\n"
        self.write("posts/a.md", original)
        state, _ = self.apply()
        snapshot = state["documents"]["keep"]["source"]["snapshot"]
        self.assertEqual(self.repo.read_text(snapshot), original)
        self.assertEqual(state["documents"]["keep"]["source"]["sha256"], hashlib.sha256(original.encode()).hexdigest())

    def test_a_folder_must_be_an_absolute_directory_holding_markdown(self):
        with self.assertRaisesRegex(ModelError, "absolute"):
            scan(self.repo.load(), "relative/path")
        with self.assertRaisesRegex(ModelError, "Not a folder"):
            scan(self.repo.load(), str(self.src / "nope"))
        with self.assertRaisesRegex(ModelError, "No Markdown"):
            scan(self.repo.load(), str(self.src))

    def test_folder_imports_do_not_block_a_later_archive_sync(self):
        """Archive sync must not treat folder-imported documents as missing from the archive."""
        from stemma_studio.core.archive_sync import plan_sync

        self.write("posts/a.md", "# A\n\ntext\n")
        state, _ = self.apply()
        with self.assertRaises(ModelError) as caught:
            plan_sync(state, str(self.src))
        # It fails for the honest reason - no Git archive - not for a phantom conflict.
        self.assertNotIn("existing_document_missing", str(caught.exception))

    def test_null_metadata_is_absent_rather_than_the_word_null(self):
        """An exported archive writes `title: null` for a post that never had one."""
        self.write("posts/a.md", "---\ntitle: null\ndate: null\n---\n\nfirst line\nsecond\n")
        row = self.scan().report["new"][0]
        self.assertEqual(row["title"], "undated \u00b7 first line")
        self.assertIsNone(row["date"])
        self.write("posts/b.md", "---\ntitle: ~\ndate: 2011-09-27\n---\n\nopening words\n")
        row = next(r for r in self.scan().report["new"] if r["id"] == "posts-b")
        self.assertEqual(row["title"], "2011-09-27 \u00b7 opening words")

    def test_a_picture_reached_through_a_symlinked_folder_is_outside_too(self):
        # `..` is not the only way out. A link in somebody's writing must not widen the
        # set of files the import is allowed to read: the text is data, not instruction.
        elsewhere = Path(self.temp.name).resolve() / "not-mine"
        elsewhere.mkdir()
        (elsewhere / "private.png").write_bytes(PNG)
        (self.src / "posts" / "linked").symlink_to(elsewhere, target_is_directory=True)
        self.write("posts/a.md", "# A\n\n![](linked/private.png)\n")
        plan = self.scan()
        self.assertEqual([w["reason"] for w in plan.report["warnings"]], ["image_outside_folder"])
        self.assertEqual(plan.report["new"][0]["missing"], ["linked/private.png"])
        # Nothing from outside the chosen folder reaches the planned writes.
        self.assertFalse(any(value == PNG for value in plan.writes.values()))
        self.assertEqual(plan.state["documents"]["posts-a"]["source"]["assets"], [])

    def test_a_picture_above_the_chosen_folder_says_so(self):
        self.write("posts/a.md", "# A\n\n![](../../outside/cat.png)\n")
        report = self.scan().report
        self.assertEqual([w["reason"] for w in report["warnings"]], ["image_outside_folder"])
        self.assertEqual(report["new"][0]["missing"], ["../../outside/cat.png"])


class ImportScreenTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.src = Path(self.temp.name).resolve() / "old-blog"
        self.src.mkdir()
        (self.src / "a.md").write_text("# A\n\ntext\n", encoding="utf-8")
        self.root = Path(self.temp.name) / "studio"
        Studio(self.root).save(empty_state())
        self.admin = Admin(self.root)

    def confirm(self, report):
        """What the screen sends to apply a plan it has just shown, unchanged."""
        return {"folder": str(self.src), "rule": "path", "plan": report["plan"], "token": report["token"]}

    def test_scan_writes_nothing_and_apply_imports(self):
        before = FileRepository(self.root).load()
        report = self.admin.action("import-scan", {"folder": str(self.src)})
        self.assertEqual(report["counts"]["new"], 1)
        self.assertEqual(FileRepository(self.root).load(), before)
        done = self.admin.action("import-apply", self.confirm(report))
        self.assertEqual(done["status"], "imported")
        self.assertEqual(len(FileRepository(self.root).load()["documents"]), 1)

    def test_a_picture_named_in_hangul_is_found_through_the_real_parser(self):
        """The parser percent-encodes non-ASCII targets; both sides have to decode.

        Only the injected Markdown parser does this, so the plain regex scan
        cannot catch it: this has to go through the screen the way a person does.
        """
        (self.src / "사진").mkdir()
        (self.src / "사진" / "고양이.png").write_bytes(PNG)
        (self.src / "b.md").write_text("# B\n\n![](사진/고양이.png)\n", encoding="utf-8")
        report = self.admin.action("import-scan", {"folder": str(self.src)})
        self.assertEqual(report["counts"]["images"], 1)
        self.assertEqual(report["counts"]["warnings"], 0)
        self.assertEqual(report["orphan_assets"], [])
        self.admin.action("import-apply", self.confirm(report))
        state = FileRepository(self.root).load()
        document = state["documents"][derive_id("b.md", "path")]
        body = (self.root / document["revisions"][0]["path"]).read_text(encoding="utf-8")
        found = referenced_attachments(state, document, body)
        self.assertEqual([a["sha256"] for a in found], [hashlib.sha256(PNG).hexdigest()])

    def test_a_folder_is_required(self):
        for request in ({}, {"folder": "   "}, {"folder": 5}):
            with self.assertRaises(ValueError):
                self.admin.action("import-scan", request)

    def test_read_only_refuses_to_import(self):
        reader = Admin(self.root, read_only=True)
        with self.assertRaisesRegex(ValueError, "read-only"):
            reader.action("import-scan", {"folder": str(self.src)})

    def test_applying_against_stale_state_is_refused(self):
        report = self.admin.action("import-scan", {"folder": str(self.src)})
        # Something else wrote to the workspace between the review and the confirmation.
        other = FileRepository(self.root).load()
        other["questions"]["q"] = {"text": "q?", "public": False, "representatives": []}
        FileRepository(self.root).save(other)
        with self.assertRaises(Conflict):
            self.admin.action("import-apply", self.confirm(report))

    def test_a_reviewed_plan_is_consumed_and_cannot_be_applied_twice(self):
        report = self.admin.action("import-scan", {"folder": str(self.src)})
        self.admin.action("import-apply", self.confirm(report))
        with self.assertRaises(Conflict):
            self.admin.action("import-apply", self.confirm(report))
        self.assertEqual(len(FileRepository(self.root).load()["documents"]), 1)

    def test_apply_imports_the_folder_that_was_reviewed(self):
        """The screen shows one folder's additions; confirming must not import another.

        The folder box is an ordinary text input, so its value at the moment of the
        click is not evidence of what the author read on the way to clicking.
        """
        other = Path(self.temp.name).resolve() / "other-blog"
        other.mkdir()
        (other / "different.md").write_text("# Different\n\nelsewhere\n", encoding="utf-8")
        report = self.admin.action("import-scan", {"folder": str(self.src)})
        self.assertEqual([n["id"] for n in report["new"]], ["a"])
        with self.assertRaisesRegex(Conflict, "not the folder that was scanned"):
            self.admin.action(
                "import-apply",
                {"folder": str(other), "rule": "path", "plan": report["plan"], "token": report["token"]},
            )
        self.assertEqual(FileRepository(self.root).load()["documents"], {})

    def test_apply_writes_the_bytes_that_were_reviewed(self):
        report = self.admin.action("import-scan", {"folder": str(self.src)})
        # The file changes on disk after the author read the plan and before confirming.
        (self.src / "a.md").write_text("# A\n\nswapped after the review\n", encoding="utf-8")
        self.admin.action("import-apply", self.confirm(report))
        state = FileRepository(self.root).load()
        body = (self.root / state["documents"]["a"]["revisions"][0]["path"]).read_text(encoding="utf-8")
        self.assertIn("text", body)
        self.assertNotIn("swapped", body)

    def test_a_changed_rule_needs_another_review(self):
        report = self.admin.action("import-scan", {"folder": str(self.src), "rule": "path"})
        with self.assertRaisesRegex(Conflict, "not the folder that was scanned"):
            self.admin.action(
                "import-apply",
                {"folder": str(self.src), "rule": "name", "plan": report["plan"], "token": report["token"]},
            )
