"""Pictures attached while writing, from the upload to the published page."""

import base64
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from stemma_studio.blog import site_settings
from stemma_studio.blog.admin import Admin
from stemma_studio.blog.attachments import referenced_attachments
from stemma_studio.blog.render import render_site
from stemma_studio.core import uploads
from stemma_studio.core.application import Studio
from stemma_studio.core.domain import ModelError, empty_state
from stemma_studio.core.repository import FileRepository, verify_contents
from stemma_studio.editor.service import Editor

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)
GIF = b"GIF89a" + b"\x01\x00\x01\x00\x00\x00\x00;"
DIGEST = hashlib.sha256(PNG).hexdigest()


class NamingTests(unittest.TestCase):
    def test_a_name_keeps_its_letters_and_loses_its_path(self):
        self.assertEqual(uploads.clean_name("/tmp/../My Photo.PNG"), "My-Photo")
        self.assertEqual(uploads.clean_name("사진/고양이.png"), "고양이")
        self.assertEqual(uploads.clean_name("..."), "image")
        self.assertEqual(uploads.clean_name(""), "image")

    def test_the_stored_name_is_the_pictures_own_hash(self):
        asset = uploads.describe("cat.png", PNG)
        self.assertEqual(asset["archive_path"], "images/cat-" + DIGEST[:8] + ".png")
        self.assertEqual(asset["snapshot"], "data/assets/" + DIGEST + ".png")
        self.assertEqual(asset["media_type"], "image/png")
        self.assertEqual(asset, uploads.describe("cat.png", PNG))

    def test_two_pictures_with_one_name_do_not_collide(self):
        self.assertNotEqual(
            uploads.describe("a.png", PNG)["archive_path"], uploads.describe("a.gif", GIF)["archive_path"]
        )

    def test_a_file_that_is_not_what_it_claims_is_refused(self):
        for name, content in [("cat.png", GIF), ("cat.txt", PNG), ("cat.svg", PNG), ("cat.png", b"")]:
            with self.assertRaises(ModelError):
                uploads.describe(name, content)

    def test_a_picture_over_the_size_limit_is_refused(self):
        with self.assertRaisesRegex(ModelError, "8MB"):
            uploads.describe("big.png", PNG[:8] + b"x" * uploads.MAX_BYTES)


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "studio"
        Studio(self.root).save(empty_state())
        self.repo = FileRepository(self.root)

    def test_the_same_picture_is_stored_once(self):
        first = uploads.store(self.repo, "cat.png", PNG)
        second = uploads.store(self.repo, "other-name.png", PNG)
        self.assertEqual(first["snapshot"], second["snapshot"])
        self.assertNotEqual(first["archive_path"], second["archive_path"])
        self.assertEqual((self.root / "data" / "assets").glob("*.png").__next__().read_bytes(), PNG)

    def test_a_record_the_browser_invented_is_refused(self):
        asset = uploads.store(self.repo, "cat.png", PNG)
        uploads.verify(self.repo, asset)
        for broken in [
            {**asset, "snapshot": "data/studio.json"},
            {**asset, "archive_path": "images/../../escape-" + DIGEST[:8] + ".png"},
            {**asset, "archive_path": "notimages/cat-" + DIGEST[:8] + ".png"},
            {**asset, "media_type": "image/gif"},
            {**asset, "sha256": "0" * 64},
            {**asset, "sha256": "nonsense"},
        ]:
            with self.assertRaises(ModelError):
                uploads.verify(self.repo, broken)

    def test_attachments_accumulate_without_duplicating(self):
        one, two = uploads.describe("a.png", PNG), uploads.describe("b.gif", GIF)
        self.assertEqual(uploads.merge([one], [one, two]), sorted([one, two], key=lambda a: a["archive_path"]))
        with self.assertRaises(ModelError):
            uploads.merge([one], [{**two, "archive_path": one["archive_path"]}])


class EditorPictureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "studio"
        Studio(self.root).save(empty_state())
        self.editor = Editor(self.root)

    def upload(self, work, name, content):
        payload = {"name": name, "data": base64.b64encode(content).decode()}
        return self.editor.attach(work["id"], [payload])["attachments"][0]

    def write(self, title="바다", body=None, attachments=()):
        work = self.editor.new()
        asset = self.upload(work, "cat.png", PNG)
        work = self.editor.update(
            work["id"],
            {
                "version": work["version"],
                "title": title,
                "body": body if body is not None else "![](" + asset["archive_path"] + ")\n\n본문\n",
                "note": "",
                "selections": [],
                "attachments": [asset],
            },
        )
        return work, asset

    def test_a_picture_survives_from_the_editor_to_the_published_page(self):
        work, asset = self.write()
        result = self.editor.commit(work["id"], work["version"], confirm=True)
        state = FileRepository(self.root).load()
        document = state["documents"][result["document_id"]]
        self.assertEqual(document["source"]["origin"], "editor")
        self.assertEqual([a["archive_path"] for a in document["source"]["assets"]], [asset["archive_path"]])
        body = (self.root / document["revisions"][0]["path"]).read_text(encoding="utf-8")
        found = referenced_attachments(state, document, body)
        self.assertEqual([a["sha256"] for a in found], [asset["sha256"]])
        self.assertEqual([a["media_type"] for a in found], ["image/png"])

    def test_a_document_with_pictures_and_no_import_still_verifies(self):
        work, _ = self.write()
        self.editor.commit(work["id"], work["version"], confirm=True)
        repo = FileRepository(self.root)
        verify_contents(repo.load(), repo.read_text, repo.read_bytes)

    def test_a_picture_nothing_links_to_is_kept_but_not_published(self):
        work, asset = self.write(body="사진 없는 본문\n")
        result = self.editor.commit(work["id"], work["version"], confirm=True)
        state = FileRepository(self.root).load()
        document = state["documents"][result["document_id"]]
        self.assertEqual(len(document["source"]["assets"]), 1)
        body = (self.root / document["revisions"][0]["path"]).read_text(encoding="utf-8")
        self.assertEqual(referenced_attachments(state, document, body), [])

    def test_saving_a_record_that_was_never_stored_is_refused(self):
        work = self.editor.new()
        invented = uploads.describe("cat.png", PNG)
        with self.assertRaises(ValueError):
            self.editor.update(
                work["id"],
                {
                    "version": work["version"],
                    "title": "t",
                    "body": "b",
                    "note": "",
                    "selections": [],
                    "attachments": [invented],
                },
            )

    def test_uploading_needs_a_work_and_a_sane_batch(self):
        work = self.editor.new()
        with self.assertRaises(ValueError):
            self.editor.attach(work["id"], [])
        with self.assertRaises(ValueError):
            self.editor.attach(work["id"], [{"name": "a.png", "data": "not base64!!"}])
        with self.assertRaises(ModelError):
            self.editor.attach(work["id"], [{"name": "a.png", "data": base64.b64encode(GIF).decode()}])

    def test_reopening_a_document_keeps_the_pictures_it_already_has(self):
        work, asset = self.write()
        result = self.editor.commit(work["id"], work["version"], confirm=False)
        reopened = self.editor.new(result["document_id"])
        self.assertEqual([a["archive_path"] for a in reopened["attachments"]], [asset["archive_path"]])


class PublishedPictureTests(unittest.TestCase):
    """A picture is useless if it cannot reach a reader, so follow it all the way."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "studio"
        Studio(self.root).save(empty_state())
        site_settings.save(self.root, {"language": "ko"})
        self.editor, self.admin = Editor(self.root), Admin(self.root)

    def publish(self, body, english):
        work = self.editor.new()
        asset = self.editor.attach(work["id"], [{"name": "cat.png", "data": base64.b64encode(PNG).decode()}])[
            "attachments"
        ][0]
        work = self.editor.update(
            work["id"],
            {
                "version": work["version"],
                "title": "사진 글",
                "body": body(asset),
                "note": "",
                "selections": [],
                "attachments": [asset],
            },
        )
        done = self.editor.commit(work["id"], work["version"], confirm=True)
        did = done["document_id"]
        state = FileRepository(self.root).load()
        candidate = self.admin.action(
            "preview",
            {
                "document": did,
                "revision": state["documents"][did]["current_revision"],
                "token": self.admin.catalog()["token"],
                "planned_at": "2026-09-20T00:00:00Z",
                "text": {
                    "ko": {"title": "사진 글", "summary": ""},
                    "en": {"title": "A post", "summary": "", "body": english(asset)},
                },
            },
        )
        self.admin.action("select", {"preview": candidate["id"], "token": candidate["token"]})
        bundle = Studio(self.root).export_bundle(FileRepository(self.root).load(), "2026-09-20T00:00:00Z")
        files = render_site(bundle["public"], bundle["assets"], base="/blog/")
        return bundle, files, bundle["public"]["documents"][0], asset

    def test_an_attached_picture_reaches_the_published_page(self):
        bundle, files, doc, asset = self.publish(
            lambda a: "앞\n\n![](" + a["archive_path"] + ")\n\n뒤\n",
            lambda a: "Front\n\n![](" + a["archive_path"] + ")\n\nBack\n",
        )
        url = doc["assets"][0]["url"]
        self.assertEqual(bundle["assets"][url], PNG)
        # The body is never rewritten; the payload says which link means which asset.
        self.assertIn("![](" + asset["archive_path"] + ")", doc["translations"]["ko"]["body"])
        for page in ("ko/posts/" + doc["slug"] + "/index.html", "en/posts/" + doc["slug"] + "/index.html"):
            self.assertIn('<img src="/blog/' + url + '"', files[page].decode())

    def test_a_link_written_with_a_leading_dot_still_resolves(self):
        _, files, doc, _ = self.publish(
            lambda a: "![](./" + a["archive_path"] + ")\n",
            lambda a: "![](./" + a["archive_path"] + ")\n",
        )
        self.assertIn(
            '<img src="/blog/' + doc["assets"][0]["url"] + '"',
            files["ko/posts/" + doc["slug"] + "/index.html"].decode(),
        )

    def test_a_private_path_never_travels_in_the_payload(self):
        bundle, files, doc, asset = self.publish(
            lambda a: "본문에 사진을 걸지 않습니다\n", lambda a: "No picture linked here\n"
        )
        self.assertEqual(doc["assets"], [])
        self.assertNotIn(asset["snapshot"], json.dumps(bundle["public"]))
        self.assertNotIn("data/assets", json.dumps(bundle["public"]))


if __name__ == "__main__":
    unittest.main()
