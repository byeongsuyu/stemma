"""Attachment discovery is revision-scoped and public rendering preserves image links."""

import base64
import hashlib
import tempfile
import unittest
from pathlib import Path

from blog_fixtures import IDS, RELEASE_TIME, make_fixture
from stemma_studio.blog.admin import Admin
from stemma_studio.blog.attachments import referenced_attachments
from stemma_studio.core.application import Studio
from stemma_studio.core.blog import fingerprint
from test_publication_v3 import phase_three


class AttachmentTests(unittest.TestCase):
    def test_reference_resolution_and_code_exclusion(self):
        asset = {"archive_path": "assets/photo.JPG", "snapshot": "data/assets/photo.JPG", "sha256": "a" * 64}
        doc = {"source": {"relative_path": "corpus/posts/a.md", "assets": [asset]}, "publication_pairs": {}}
        state = {"documents": {"one": doc}}
        body = "![photo][ref]\n\n[ref]: ../../assets/photo.JPG\n\n`![code](data/assets/other.png)`\n"
        self.assertEqual([a["path"] for a in referenced_attachments(state, doc, body)], ["data/assets/photo.JPG"])
        self.assertEqual(referenced_attachments(state, doc, "No attachment in this revision."), [])
        self.assertEqual(referenced_attachments(state, doc, "![remote](https://example.org/photo.JPG)"), [])

    def test_automatic_preview_copies_only_referenced_asset_and_renders_both_languages(self):
        with tempfile.TemporaryDirectory() as folder:
            fixture = make_fixture(folder, unrelated=0)
            state = phase_three(fixture)
            app = Studio(folder)
            doc = state["documents"][IDS["A"]]
            image = base64.b64decode(
                "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aV1cAAAAASUVORK5CYII="
            )
            path = "data/assets/photo.png"
            app.repository.write_bytes_new(path, image)
            app.repository.write_bytes_new("data/assets/unrelated.png", b"PRIVATE-UNRELATED")
            asset = {"archive_path": "assets/photo.png", "snapshot": path, "sha256": hashlib.sha256(image).hexdigest()}
            doc["source"].update(
                relative_path="corpus/posts/a.md",
                assets=[
                    asset,
                    dict(
                        asset,
                        archive_path="assets/unrelated.png",
                        snapshot="data/assets/unrelated.png",
                        sha256=hashlib.sha256(b"PRIVATE-UNRELATED").hexdigest(),
                    ),
                ],
            )
            body = "![Photo][picture]\n\n[picture]: ../../assets/photo.png\n"
            new_path = "data/revisions/" + IDS["A"] + "/r-image.md"
            app.repository.write_new(new_path, body)
            doc["revisions"].append(
                {
                    "id": "r-image",
                    "path": new_path,
                    "sha256": hashlib.sha256(body.encode()).hexdigest(),
                    "note": "Fixture",
                }
            )
            doc["current_revision"] = "r-image"
            app.save(state)
            for lang in ("ko", "en"):
                state = app.save_variant(
                    state, IDS["A"], "image-" + lang, "r-image", lang, "Photo " + lang, None if lang == "ko" else body
                )
                state = app.review_variant(
                    state,
                    IDS["A"],
                    "image-" + lang,
                    fingerprint(state["documents"][IDS["A"]]["language_variants"]["image-" + lang]),
                )
            admin = Admin(folder)
            detail = admin.detail(IDS["A"])
            self.assertEqual(len(detail["attachments"]), 1)
            self.assertEqual(admin.detail(IDS["A"], "r1")["attachments"], [])
            before = {str(p): p.read_bytes() for p in Path(folder).rglob("*") if p.is_file()}
            text = {
                "ko": {"title": "Photo ko", "summary": ""},
                "en": {"title": "Photo en", "summary": "", "body": body},
            }
            preview = admin.preview(
                {
                    "document": IDS["A"],
                    "revision": "r-image",
                    "token": detail["token"],
                    "text": text,
                    "planned_at": RELEASE_TIME,
                }
            )
            staged = admin.previews[preview["id"]]["overlay"].state["documents"][IDS["A"]]
            # The displayed text matches the stored expressions, so the pair reuses them.
            self.assertEqual(
                staged["publication_pairs"][staged["publication"]["selected_pair"]]["variants"],
                {"ko": "image-ko", "en": "image-en"},
            )
            files = admin.previews[preview["id"]]["files"]
            assets = [p for p in files if p.startswith("assets/")]
            self.assertEqual(len(assets), 1)
            self.assertEqual(files[assets[0]], image)
            for lang in ("ko", "en"):
                page = files[lang + "/posts/post-a/index.html"].decode()
                self.assertIn('<img src="/preview/' + preview["id"] + "/" + assets[0] + '"', page)
                self.assertNotIn("../../assets", page)
            self.assertEqual(before, {str(p): p.read_bytes() for p in Path(folder).rglob("*") if p.is_file()})
