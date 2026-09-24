"""An author may write in either language; the other becomes the translation.

Which side of a post is its revision is recorded in immutable variants, so these
tests follow the cases where getting it wrong would be permanent: a fresh root that
has never said, a setting changed after posts exist, and a draft already begun.
"""

import json
import tempfile
import unittest
from pathlib import Path

from stemma_studio.blog import site_settings
from stemma_studio.blog.admin import Admin
from stemma_studio.blog.preview import static_files
from stemma_studio.core.application import Studio
from stemma_studio.core.domain import empty_state
from stemma_studio.core.repository import FileRepository
from stemma_studio.editor.service import Editor


class WritingLanguageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "studio"
        Studio(self.root).save(empty_state())
        self.editor, self.admin = Editor(self.root), Admin(self.root)

    def write(self, title, body, parent=None, questions=(), new_questions=(), note=""):
        selections = []
        if parent:
            source = self.editor.detail(parent)
            selections.append(
                {
                    "id": parent,
                    "revision": source["revision"],
                    "sha256": source["sha256"],
                    "title": source["title"],
                    "role": "parent",
                    "questions": list(questions),
                    "new_questions": list(new_questions),
                    "note": note,
                    "archive": False,
                }
            )
        work = self.editor.new()
        work = self.editor.update(
            work["id"],
            {"version": work["version"], "title": title, "body": body, "note": "", "selections": selections},
        )
        return self.editor.commit(work["id"], work["version"], confirm=True)["document_id"]

    def publish(self, did, text, labels=()):
        state = FileRepository(self.root).load()
        candidate = self.admin.action(
            "preview",
            {
                "document": did,
                "revision": state["documents"][did]["current_revision"],
                "token": self.admin.catalog()["token"],
                "planned_at": "2026-09-23T00:00:00Z",
                "text": text,
                "labels": list(labels),
            },
        )
        self.admin.action("select", {"preview": candidate["id"], "token": candidate["token"]})
        return candidate

    def variants(self, did):
        doc = FileRepository(self.root).load()["documents"][did]
        pair = doc["publication_pairs"][doc["publication"]["selected_pair"]]
        return {lang: doc["language_variants"][vid] for lang, vid in pair["variants"].items()}

    def test_an_english_author_publishes_english_with_a_korean_translation(self):
        site_settings.save(self.root, {"language": "en"})
        did = self.write("On reading again", "I open a text I have read before.")
        detail = self.admin.detail(did)
        self.assertEqual((detail["language"], detail["translation"]), ("en", "ko"))
        self.publish(
            did,
            {
                "en": {"title": "On reading again", "summary": ""},
                "ko": {"title": "다시 읽는다는 것", "summary": "", "body": "한 번 읽은 글을 다시 펼친다."},
            },
        )
        variants = self.variants(did)
        # The English is the revision itself; the Korean is stored as a translation of it.
        self.assertEqual(variants["en"]["body"]["kind"], "base_revision")
        self.assertEqual(variants["ko"]["body"]["kind"], "translation")
        public = self.admin.public_output(FileRepository(self.root).load())["documents"][0]["translations"]
        self.assertIn("I open a text I have read before", public["en"]["body"])
        self.assertIn("한 번 읽은 글을 다시 펼친다", public["ko"]["body"])
        self.assertEqual(public["en"]["title"], "On reading again")
        # Readers arriving at the root are sent to the language the author writes in.
        public = self.admin.public_output(FileRepository(self.root).load())
        home = static_files(public, site=site_settings.load(self.root))["index.html"].decode()
        self.assertIn('<html lang="en">', home)
        self.assertIn('en/">Read in English', home)

    def test_a_root_that_never_said_is_asked_before_anything_is_recorded(self):
        did = self.write("글", "본문")
        detail = self.admin.detail(did)
        self.assertIsNone(detail["language"])
        text = {"ko": {"title": "글", "summary": ""}, "en": {"title": "Post", "summary": "", "body": "Body"}}
        with self.assertRaisesRegex(ValueError, "Choose the language you write in"):
            self.publish(did, text)
        with self.assertRaisesRegex(ValueError, "Choose the language you write in"):
            self.admin.action(
                "draft",
                {
                    "document": did,
                    "token": detail["token"],
                    "version": 0,
                    "draft": {"revision": detail["revision"], **text},
                },
            )
        self.assertEqual(FileRepository(self.root).load()["documents"][did]["language_variants"], {})
        self.assertIsNone(self.admin.site_settings()["writing_language"])

    def test_changing_the_setting_never_turns_round_a_post_already_published(self):
        site_settings.save(self.root, {"language": "ko"})
        korean = self.write("다시 읽기", "본문")
        self.publish(
            korean,
            {"ko": {"title": "다시 읽기", "summary": ""}, "en": {"title": "Reading", "summary": "", "body": "Text"}},
        )
        site_settings.save(self.root, {"language": "en"})
        self.assertEqual(self.admin.detail(korean)["language"], "ko")
        english = self.write("Reading", "Text")
        self.assertEqual(self.admin.detail(english)["language"], "en")
        # The published Korean post still takes a Korean original and an English translation.
        state = FileRepository(self.root).load()
        self.admin.action(
            "draft",
            {
                "document": korean,
                "token": self.admin.catalog()["token"],
                "version": 0,
                "draft": {
                    "revision": state["documents"][korean]["current_revision"],
                    "ko": {"title": "다시 읽기", "summary": ""},
                    "en": {"title": "Reading again", "summary": "", "body": "Text, revised"},
                },
            },
        )
        with self.assertRaisesRegex(ValueError, "translation input"):
            self.admin.action(
                "draft",
                {
                    "document": english,
                    "token": self.admin.catalog()["token"],
                    "version": 0,
                    "draft": {
                        "revision": state["documents"][english]["current_revision"],
                        "ko": {"title": "읽기", "summary": ""},
                        "en": {"title": "Reading", "summary": "", "body": "The English is the revision"},
                    },
                },
            )

    def test_a_draft_already_begun_keeps_its_sides_when_the_setting_changes(self):
        site_settings.save(self.root, {"language": "ko"})
        did = self.write("글", "본문")
        detail = self.admin.detail(did)
        self.admin.action(
            "draft",
            {
                "document": did,
                "token": detail["token"],
                "version": 0,
                "draft": {
                    "revision": detail["revision"],
                    "ko": {"title": "글", "summary": ""},
                    "en": {"title": "Post", "summary": "", "body": "Started"},
                },
            },
        )
        site_settings.save(self.root, {"language": "en"})
        self.assertEqual(self.admin.detail(did)["language"], "ko")

    def test_a_root_published_before_the_choice_existed_keeps_writing_in_korean(self):
        site_settings.save(self.root, {"language": "ko"})
        did = self.write("글", "본문")
        self.publish(did, {"ko": {"title": "글", "summary": ""}, "en": {"title": "Post", "summary": "", "body": "B"}})
        # A root from before this setting has no language in its site file at all.
        path = site_settings.settings_path(self.root)
        stored = json.loads(path.read_text(encoding="utf-8"))
        del stored["language"]
        path.write_text(json.dumps(stored), encoding="utf-8")
        state = FileRepository(self.root).load()
        self.assertEqual(self.admin.writing_language(state), "ko")
        self.assertEqual(self.admin.detail(self.write("새 글", "본문"))["language"], "ko")

    def test_reverting_an_english_post_leaves_a_korean_translation_to_fill(self):
        site_settings.save(self.root, {"language": "en"})
        did = self.write("A note", "Text")
        self.publish(
            did, {"en": {"title": "A note", "summary": ""}, "ko": {"title": "메모", "summary": "", "body": "본문"}}
        )
        self.admin.action("revert", {"token": self.admin.catalog()["token"], "kind": "post", "target": did})
        draft = self.admin.draft(did)
        self.assertEqual(draft["en"], {"title": "A note", "summary": ""})
        self.assertEqual(draft["ko"], {"title": "", "summary": "", "body": ""})

    def korean_question_then_english_successor(self):
        """A Korean post asks a question and translates it; then the author writes in English."""
        site_settings.save(self.root, {"language": "ko"})
        first = self.write("처음", "본문")
        second = self.write("둘째", "이어 쓴 본문", first, new_questions=["무엇을 배웠나?"], note="다시 읽었다")
        state = FileRepository(self.root).load()
        question = next(q for q, v in state["questions"].items() if v["text"] == "무엇을 배웠나?")
        text = {"ko": {"title": "둘째", "summary": ""}, "en": {"title": "Second", "summary": "", "body": "Text"}}
        label = {
            "kind": "question",
            "target": question,
            "translations": {"ko": "무엇을 배웠나?", "en": "What did we learn?"},
        }
        self.publish(second, text, [label])
        site_settings.save(self.root, {"language": "en"})
        third = self.write("Third", "Carried on", second, questions=[question], note="Read it once more")
        return question, third

    def test_shared_wording_keeps_its_own_language_under_an_english_post(self):
        question, third = self.korean_question_then_english_successor()
        detail = self.admin.detail(third)
        self.assertEqual(detail["language"], "en")
        # The question was asked in Korean; the change note was written with this English post.
        self.assertEqual(detail["label_languages"]["question"][question], "ko")
        edge = next(e["id"] for e in detail["edges"] if e["child"] == third)
        self.assertEqual(detail["label_languages"]["edge"][edge], "en")
        text = {"en": {"title": "Third", "summary": ""}, "ko": {"title": "셋째", "summary": "", "body": "본문"}}
        # Filing the Korean wording as the English side would overwrite every post's genealogy.
        wrong = {"kind": "question", "target": question, "translations": {"en": "무엇을 배웠나?", "ko": "무엇을"}}
        with self.assertRaisesRegex(ValueError, "language it was written in"):
            self.publish(third, text, [wrong])
        right = {
            "kind": "question",
            "target": question,
            "translations": {"ko": "무엇을 배웠나?", "en": "What was learned?"},
        }
        note = {"kind": "edge", "target": edge, "translations": {"en": "Read it once more", "ko": "한 번 더 읽었다"}}
        self.publish(third, text, [right, note])
        labels = FileRepository(self.root).load()["blog"]
        self.assertEqual(labels["question_labels"][question]["translations"], right["translations"])
        self.assertEqual(labels["edge_labels"][edge]["translations"], note["translations"])

    def test_an_existing_manuscript_is_previewed_in_its_own_language(self):
        question, third = self.korean_question_then_english_successor()
        state = FileRepository(self.root).load()
        korean = next(d for d, doc in state["documents"].items() if doc["title"] == "둘째")
        self.assertEqual(self.editor.manuscript_language(self.editor.new(korean)["id"]), "ko")
        self.assertEqual(self.editor.manuscript_language(self.editor.new(third)["id"]), "en")
        self.assertEqual(self.editor.manuscript_language(self.editor.new()["id"]), "en")

    def test_an_english_posts_genealogy_preview_opens_in_english(self):
        site_settings.save(self.root, {"language": "en"})
        did = self.write("Alone", "Text")
        state = FileRepository(self.root).load()
        candidate = self.admin.action(
            "preview",
            {
                "document": did,
                "revision": state["documents"][did]["current_revision"],
                "token": self.admin.catalog()["token"],
                "planned_at": "2026-09-23T00:00:00Z",
                "text": {
                    "en": {"title": "Alone", "summary": ""},
                    "ko": {"title": "홀로", "summary": "", "body": "본문"},
                },
            },
        )
        self.assertIn("/en/posts/alone/genealogy/", candidate["graph_url"])


if __name__ == "__main__":
    unittest.main()
