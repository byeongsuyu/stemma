"""The desk speaks the author's language: one catalog per language, used by every screen."""

import copy
import http.client
import json
import re
import tempfile
import threading
import unittest
from pathlib import Path

import stemma_studio
from stemma_studio.core.application import Studio
from stemma_studio.core.domain import empty_state
from stemma_studio.editor.workspace_server import Server
from stemma_studio.locale import (
    LANGUAGES,
    Message,
    carried,
    catalog,
    interface_language,
    localise,
    negotiate,
    page,
    save_language,
    stored_language,
    translate,
)

SOURCE = Path(stemma_studio.__file__).resolve().parent
PLACEHOLDER = re.compile(r"\{(\w+)\}")


def sources():
    for path in sorted(SOURCE.rglob("*")):
        if path.suffix in (".py", ".js", ".html") and "vendor" not in path.parts:
            yield path, path.read_text(encoding="utf-8")


class CatalogTests(unittest.TestCase):
    def test_every_language_says_every_message_with_the_same_placeholders(self):
        english = catalog("en")
        for language in LANGUAGES:
            table = catalog(language)
            self.assertEqual(set(table), set(english), language)
            for key, text in table.items():
                self.assertTrue(text.strip(), (language, key))
                self.assertEqual(
                    sorted(PLACEHOLDER.findall(text)), sorted(PLACEHOLDER.findall(english[key])), (language, key)
                )

    def test_every_key_the_code_names_exists(self):
        """A missing key shows its own name to the author, which only a person would notice."""
        patterns = [
            r'Message\("([\w.]+)"',
            r'translate\([\w.]+, "([\w.]+)"',
            r"\bt\('([\w.]+)'",
            r"\{\{([\w.]+)\}\}",
        ]
        named = set()
        for path, text in sources():
            if path.name == "__init__.py" and path.parent.name == "locale":
                continue
            for pattern in patterns:
                named |= {(path.name, key) for key in re.findall(pattern, text)}
        self.assertGreater(len(named), 500)
        known = set(catalog("en")) | {"lang", "messages"}
        self.assertEqual(sorted(k for k in named if k[1] not in known), [])

    def test_interface_pages_carry_no_untranslated_wording(self):
        # Korean text left in a page is wording one language never sees translated.
        for path in [*(SOURCE / "editor/frontend").glob("*"), *(SOURCE / "blog/admin_frontend").glob("*")]:
            if path.suffix not in (".js", ".html"):
                continue
            text = path.read_text(encoding="utf-8")
            if path.name == "index.html" and "admin_frontend" in path.parts:
                # The custom licence field's example is written in the language it asks for.
                text = text.replace('placeholder="예: 인용 시 출처를 밝혀 주세요"', "")
            self.assertIsNone(re.search(r"[가-힣]", text), path.name)

    def test_both_frontends_share_one_translator(self):
        # Each frontend serves its own copy; they must never drift apart.
        self.assertEqual(
            (SOURCE / "editor/frontend/i18n.js").read_bytes(), (SOURCE / "blog/admin_frontend/i18n.js").read_bytes()
        )


class MessageTests(unittest.TestCase):
    def test_a_message_is_english_until_a_screen_chooses(self):
        message = Message("error.editor.upload_unreadable", name="cat.png")
        self.assertEqual(message, "Could not read the picture: cat.png")
        self.assertEqual(localise(message, "ko"), "사진을 읽지 못했습니다: cat.png")
        self.assertEqual(localise({"error": [message]}, "ko"), {"error": ["사진을 읽지 못했습니다: cat.png"]})
        self.assertEqual(carried(ValueError(message)).key, "error.editor.upload_unreadable")
        self.assertEqual(carried(KeyError("id")), "'id'")

    def test_a_copied_message_keeps_its_key(self):
        message = Message("error.too_large", size=4)
        copied = copy.deepcopy(message)
        self.assertEqual((copied.key, copied.params), ("error.too_large", {"size": 4}))
        self.assertEqual(localise(copied, "ko"), "요청 크기는 4MB 이하여야 합니다.")

    def test_stored_text_is_a_key_now_and_prose_before(self):
        self.assertEqual(localise(Message.stored("error.deploy.pages"), "ko"), translate("ko", "error.deploy.pages"))
        legacy = "배포 준비 또는 push에 실패했습니다."
        self.assertEqual(Message.stored(legacy), legacy)
        self.assertNotIsInstance(Message.stored(legacy), Message)


class PreferenceTests(unittest.TestCase):
    def test_the_browser_decides_until_the_author_does(self):
        self.assertEqual(negotiate("ko-KR,ko;q=0.9,en-US;q=0.8"), "ko")
        self.assertEqual(negotiate("fr-FR, en;q=0.5"), "en")
        self.assertEqual(negotiate("ko;q=0, en"), "en")
        self.assertIsNone(negotiate("fr, de"))
        with tempfile.TemporaryDirectory() as root:
            self.assertIsNone(stored_language(root))
            self.assertEqual(interface_language(root, "ko-KR"), "ko")
            self.assertEqual(interface_language(root, "fr"), "en")
            save_language(root, "ko")
            self.assertEqual(interface_language(root, "en-US"), "ko")
            with self.assertRaises(ValueError):
                save_language(root, "fr")
            self.assertEqual(stored_language(root), "ko")

    def test_a_page_is_filled_escaped_and_carries_its_catalog_inertly(self):
        html = page(SOURCE / "blog/admin_frontend/index.html", "en").decode()
        self.assertIn('<html lang="en">', html)
        self.assertNotIn("{{", html)
        # Markup is kept only where the key says it carries markup.
        self.assertIn("on the <b>Site</b> screen", html)
        self.assertIn("Search titles and text (library included)", html)
        carried_catalog = re.search(r'<script type="application/json" id="messages">(.*?)</script>', html).group(1)
        self.assertNotIn("<", carried_catalog)
        self.assertEqual(json.loads(carried_catalog), catalog("en"))


class ServerLanguageTests(unittest.TestCase):
    def request(self, client, method, path, body=None, headers=None):
        client.request(method, path, body, headers or {})
        response = client.getresponse()
        return response.status, response.read().decode("utf-8")

    def test_the_desk_answers_in_the_chosen_language(self):
        with tempfile.TemporaryDirectory() as root:
            Studio(root).repository.save(empty_state())
            server = Server(root, 0)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            try:
                client = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=10)
                english = {"Accept-Language": "en-US,en;q=0.9"}
                status, html = self.request(client, "GET", "/", headers=english)
                self.assertEqual(status, 200)
                self.assertIn('<html lang="en">', html)
                self.assertIn("New piece", html)
                status, html = self.request(client, "GET", "/publish/", headers={"Accept-Language": "ko"})
                self.assertIn('<html lang="ko">', html)
                self.assertIn("공개 목록", html)
                # A refusal raised as a key is worded for the request that received it.
                status, body = self.request(client, "GET", "/api/work?id=bad", headers=english)
                self.assertEqual((status, json.loads(body)["error"]), (400, "That work ID is not valid."))
                status, body = self.request(client, "GET", "/api/work?id=bad", headers={"Accept-Language": "ko"})
                self.assertEqual(json.loads(body)["error"], "잘못된 작업 ID입니다.")
                # Choosing a language outranks what the browser asks for, on both sides.
                write = {"Content-Type": "application/json", "X-Editor-Token": server.token, **english}
                status, body = self.request(client, "POST", "/api/interface-language", '{"language": "ko"}', write)
                self.assertEqual((status, json.loads(body)), (200, {"language": "ko"}))
                self.assertIn('<html lang="ko">', self.request(client, "GET", "/publish/", headers=english)[1])
                write = {"Content-Type": "application/json", "X-Blog-Token": server.token}
                status, body = self.request(
                    client, "POST", "/publish/api/interface-language", '{"language": "en"}', write
                )
                self.assertEqual(status, 200)
                self.assertIn('<html lang="en">', self.request(client, "GET", "/")[1])
                status, body = self.request(
                    client, "POST", "/publish/api/interface-language", '{"language": "fr"}', write
                )
                self.assertEqual((status, json.loads(body)["error"]), (400, "That language is not supported."))
                client.close()
            finally:
                server.shutdown()
                server.server_close()

    def test_a_default_revision_note_is_written_in_the_desks_language(self):
        from stemma_studio.editor.service import Editor

        with tempfile.TemporaryDirectory() as root:
            Studio(root).repository.save(empty_state())
            editor = Editor(root)
            editor.language = "ko"
            work = editor.new(None)
            work = editor.update(work["id"], dict(work, title="제목", body="본문"))
            saved = editor.commit(work["id"], work["version"], False)
            doc = editor.state()["documents"][saved["document_id"]]
            self.assertEqual(doc["revisions"][-1]["note"], "작성기 판본 저장")


if __name__ == "__main__":
    unittest.main()
