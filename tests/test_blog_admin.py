"""Author management exercises only disposable corpora and loopback servers."""

import copy
import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from blog_fixtures import IDS, RELEASE_TIME, add_legacy_release, make_fixture, make_homepage
from stemma_studio.blog.admin import Admin, Conflict, public_changes, site_status
from stemma_studio.blog.admin_server import Server
from stemma_studio.blog.homepage import Homepage
from stemma_studio.core.blog import fingerprint
from stemma_studio.core.repository import FileRepository
from test_publication_v3 import phase_three


class AdminTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.fixture = make_fixture(self.root, unrelated=0)
        self.repo = FileRepository(self.root)
        self.repo.save(phase_three(self.fixture))
        self.admin = Admin(self.root)
        self.did = IDS["S"]

    def files(self):
        return {str(p.relative_to(self.root)): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}

    def request(self, did=None):
        detail = self.admin.detail(did or self.did)
        return {"document": detail["id"], "revision": detail["revision"], "token": detail["token"]}

    def text_of(self, did=None):
        # The screen sends the displayed text; for a selected post that is its pair's text.
        doc = self.admin.state()["documents"][did or self.did]
        pair = doc["publication_pairs"][doc["publication"]["selected_pair"] or next(iter(doc["publication_pairs"]))]
        v = {lang: doc["language_variants"][vid] for lang, vid in pair["variants"].items()}
        return {
            "ko": {"title": v["ko"]["title"], "summary": v["ko"]["summary"] or ""},
            "en": {
                "title": v["en"]["title"],
                "summary": v["en"]["summary"] or "",
                "body": self.admin.studio.repository.read_text(v["en"]["body"]["path"]),
            },
        }

    def preview_request(self, did=None, text=None):
        req = self.request(did)
        req.update(text=text or self.text_of(req["document"]), labels=[], planned_at=RELEASE_TIME)
        return req

    def apply(self, req):
        candidate = self.admin.action("preview", req)
        return self.admin.action("select", {"preview": candidate["id"], "token": candidate["token"]})

    def draft_request(self):
        req = self.request()
        req.update(
            version=0,
            draft={
                "revision": "r1",
                "ko": {"title": "새 한글 제목", "summary": ""},
                "en": {"title": "New English title", "summary": "", "body": "Reviewed synthetic body."},
            },
        )
        return req

    def test_catalog_detail_no_sync_or_writes(self):
        before = self.files()
        with patch("stemma_studio.core.archive_sync.apply_sync", side_effect=AssertionError("must not sync")):
            self.assertTrue(self.admin.catalog("가상")["documents"])
            d = self.admin.detail(IDS["C"])
            self.assertGreater(len(d["nodes"]), 1)
            self.assertIn("body", d)
            self.assertIn("missing_assets", d)
        self.assertEqual(before, self.files())

    def test_catalog_recent_studio_first_and_archived_posts_are_hidden(self):
        state = self.admin.state()
        recent = copy.deepcopy(state["documents"][IDS["S"]])
        recent["created_at"] = "2026-09-18T01:00:00Z"
        recent["title"] = "Newest draft"
        state["documents"][IDS["A"]]["source"]["date"] = None
        state["documents"]["studio-newest"] = recent
        mocked = patch.object(self.admin, "state", return_value=state)
        mocked.start()
        self.addCleanup(mocked.stop)
        items = self.admin.catalog()["documents"]
        self.assertEqual(items[0]["id"], "studio-newest")
        # A successor covers an archived post, so neither the list nor search offers it.
        self.assertNotIn(
            IDS["B"], [d["id"] for d in items] + [d["id"] for d in self.admin.catalog("PRIVATE-TITLE-B")["documents"]]
        )
        self.assertEqual(self.admin.catalog("Newest")["documents"][0]["id"], "studio-newest")

    def test_new_base_requires_new_translation_review_and_keeps_public_pair(self):
        before = self.admin.state()
        old = before["documents"][self.did]["publication"].copy()
        self.admin.studio.add_revision(before, self.did, "A revised base body.", "expression edit")
        detail = self.admin.detail(self.did)
        self.assertEqual(detail["site"]["work"], "revision")
        self.assertEqual(detail["selected_pair"], old["selected_pair"])
        self.assertFalse(any(v["base_revision"] == detail["revision"] for v in detail["variants"]))
        self.assertEqual(self.admin.state()["documents"][self.did]["publication"], old)

    def test_draft_version_restart_and_no_publication(self):
        before = self.admin.state()
        req = self.draft_request()
        saved = self.admin.action("draft", req)
        self.assertEqual(saved["version"], 1)
        self.assertEqual(Admin(self.root).draft(self.did), saved)
        self.assertEqual(before, self.admin.state())
        with self.assertRaises(Conflict):
            self.admin.action("draft", req)

    def test_confirmed_succession_alone_needs_its_own_review(self):
        # A post whose genealogy moved has something to confirm even with unchanged text.
        self.apply(self.preview_request())
        self.assertFalse(self.admin.detail(self.did)["structure_changed"])
        child = "PRIVATE-DOCUMENT-T"
        state = self.admin.studio.create_draft(
            self.admin.state(),
            child,
            "가상 후속 글",
            ["q"],
            "가상 후속 글 r1.\n",
            [{"parent": self.did, "questions": ["q"]}],
            "계승",
        )
        self.admin.studio.confirm(state, child)
        detail = self.admin.detail(self.did)
        self.assertTrue(detail["structure_changed"])
        self.assertEqual({n["id"] for n in detail["nodes"]}, {self.did, child})
        self.assertEqual(len(detail["selected_structures"][0]["nodes"]), 1)
        # Confirming the anchor records the relation without publishing the successor.
        after = self.apply(self.preview_request())
        self.assertFalse(after["structure_changed"])
        self.assertEqual(len(after["selected_structures"][0]["nodes"]), 2)
        self.assertIsNone(self.admin.state()["documents"][child]["publication"]["selected_pair"])

    def test_preview_stages_new_text_and_confirmation_records_its_review(self):
        text = self.text_of()
        text["en"]["body"] = "Edited synthetic body.\n"
        before_state = self.admin.state()
        before = self.files()
        candidate = self.admin.action("preview", self.preview_request(text=text))
        self.assertEqual(before, self.files())
        chosen = self.admin.action("select", {"preview": candidate["id"], "token": candidate["token"]})
        pair = chosen["pairs"][chosen["selected_pair"]]
        doc = self.admin.state()["documents"][self.did]
        self.assertNotEqual(
            chosen["selected_pair"], before_state["documents"][self.did]["publication"]["selected_pair"]
        )
        # Unchanged Korean text reuses its stored expression; only the edited English is new.
        self.assertEqual(
            pair["variants"]["ko"],
            before_state["documents"][self.did]["publication_pairs"][
                before_state["documents"][self.did]["publication"]["selected_pair"]
            ]["variants"]["ko"],
        )
        english = doc["language_variants"][pair["variants"]["en"]]
        self.assertEqual(self.admin.studio.repository.read_text(english["body"]["path"]), "Edited synthetic body.\n")
        self.assertTrue(all(vid in doc["variant_reviews"] for vid in pair["variants"].values()))
        self.assertIsNone(self.admin.state()["blog"]["active_release"])

    def test_same_text_reuses_pair_structure_and_variants(self):
        before = self.admin.state()["documents"][self.did]
        approvals = len(self.admin.state()["blog"]["structure_approvals"])
        req = self.preview_request()
        req["series"] = {"existing": None}
        chosen = self.apply(req)
        after = self.admin.state()
        self.assertEqual(chosen["selected_pair"], before["publication"]["selected_pair"])
        for key in ("language_variants", "publication_pairs"):
            self.assertEqual(after["documents"][self.did][key], before[key])
        count = len(after["blog"]["structure_approvals"])
        self.assertLessEqual(count, approvals + 1)
        self.apply(self.preview_request())
        self.assertEqual(len(self.admin.state()["blog"]["structure_approvals"]), count)

    def test_stale_review_and_preview_apply_are_rejected_without_write(self):
        req = self.preview_request()
        candidate = self.admin.action("preview", req)
        self.admin.action("unselect", self.request(IDS["A"]))
        before = self.files()
        with self.assertRaises(Conflict):
            self.admin.action("select", {"preview": candidate["id"], "token": candidate["token"]})
        self.assertEqual(before, self.files())

    def test_changed_current_revision_rejects_old_draft(self):
        req = self.draft_request()
        state = self.admin.state()
        state["documents"][IDS["C"]]["current_revision"] = "r1"
        self.repo.save(state)
        with self.assertRaises(Conflict):
            self.admin.action("draft", req)

    def test_single_node_preview_and_no_private_leaks(self):
        req = self.preview_request()
        before = self.files()
        candidate = self.admin.action("preview", req)
        output = self.admin.previews[candidate["id"]]["files"]
        data = b"".join(output.values()).decode("utf-8", errors="ignore")
        self.assertIn("single-node", data)
        for sentinel in self.fixture["sentinels"]:
            self.assertNotIn(sentinel, data)
        self.assertEqual(before, self.files())

    def test_unknown_and_missing_preview_fields_are_refused(self):
        before = self.files()
        for change in ("nodes", "edges", "slug", "attachments"):
            req = self.preview_request()
            req[change] = [] if change != "slug" else "chosen-by-hand"
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.admin.action("preview", req)
        req = self.preview_request()
        req.pop("planned_at")
        with self.assertRaises(ValueError):
            self.admin.action("preview", req)
        self.assertEqual(before, self.files())

    def test_invalid_text_is_refused_before_any_write(self):
        text = self.text_of()
        text["en"]["body"] = ""
        before = self.files()
        with self.assertRaises(ValueError):
            self.admin.action("preview", self.preview_request(text=text))
        text = self.text_of()
        text["en"].pop("summary")
        with self.assertRaises(ValueError):
            self.admin.action("preview", self.preview_request(text=text))
        self.assertEqual(before, self.files())

    def test_metadata_failure_on_confirm_reuses_orphan_translation_bytes(self):
        text = self.text_of()
        text["en"]["body"] = "Orphan retry body.\n"
        candidate = self.admin.action("preview", self.preview_request(text=text))
        confirm = {"preview": candidate["id"], "token": candidate["token"]}
        with patch.object(self.admin.studio.repository, "save", side_effect=OSError("fixture failure")):
            with self.assertRaises(OSError):
                self.admin.action("select", confirm)
        chosen = self.admin.action("select", confirm)
        english = self.admin.state()["documents"][self.did]["language_variants"][
            chosen["pairs"][chosen["selected_pair"]]["variants"]["en"]
        ]
        self.assertEqual(self.admin.studio.repository.read_text(english["body"]["path"]), "Orphan retry body.\n")

    def test_unselect_preserves_revisions_variants_and_structure(self):
        before = self.admin.state()
        self.admin.action("unselect", self.request())
        after = self.admin.state()
        self.assertIsNone(after["documents"][self.did]["publication"]["selected_pair"])
        for key in ("revisions", "language_variants", "publication_pairs"):
            self.assertEqual(before["documents"][self.did][key], after["documents"][self.did][key])
        self.assertEqual(before["blog"]["structure_approvals"], after["blog"]["structure_approvals"])

    def test_preserved_legacy_release_stays_readable_but_not_deployable(self):
        # The dedicated-repository mode is gone; its stored records must still list.
        record = add_legacy_release(self.root, self.admin.state())
        status = self.admin.release_status()
        self.assertIn(record["id"], {r["id"] for r in status["releases"]})
        self.assertEqual(status["active_release"], record["id"])
        self.assertNotIn(record["id"], status["pull_requests"])
        token = status["token"]
        with self.assertRaises(ValueError):
            self.admin.action("release-build", {"token": token, "release": record["id"]})
        # Already the active release, so deploying it is a no-op rather than a crash.
        again = self.admin.action("release-deploy", {"token": token, "release": record["id"]})
        self.assertEqual(again["active_release"], record["id"])

    def test_mixed_release_history_preserves_pr_and_rejects_legacy_retry(self):
        legacy = add_legacy_release(self.root, self.admin.state(), succeeded=False)
        with tempfile.TemporaryDirectory() as folder:
            home = make_homepage(Path(folder) / "homepage")
            service = Homepage(self.root)
            service.configure(str(home))
            release = service.freeze_configured(fingerprint(service.state()))
            record = service.build(release["id"])
            before = self.admin.state()
            files = self.files()
            status = self.admin.release_status()
            self.assertEqual({r["id"] for r in status["releases"]}, {legacy["id"], release["id"]})
            self.assertEqual(status["pull_requests"], {release["id"]: record})
            self.assertEqual(self.files(), files)
            # A failed legacy release reaches delivery validation, unlike the active-release no-op.
            with patch("stemma_studio.blog.homepage.GitHub.config") as remote:
                for action in ("release-build", "release-deploy"):
                    with self.subTest(action=action), self.assertRaisesRegex(ValueError, "past release was pinned"):
                        self.admin.action(action, {"token": fingerprint(self.admin.state()), "release": legacy["id"]})
                remote.assert_not_called()
            after = self.admin.state()
            self.assertEqual(after["documents"], before["documents"])
            self.assertEqual(after["blog"]["releases"], before["blog"]["releases"])
            self.assertEqual(after["blog"]["active_release"], before["blog"]["active_release"])
            self.assertEqual(after["blog"]["release_attempts"][:-1], before["blog"]["release_attempts"])
            self.assertEqual(after["blog"]["release_attempts"][-1]["status"], "failed")
            self.assertEqual(after["blog"]["release_attempts"][-1]["release"], legacy["id"])

    def test_read_only_rejects_writes_and_allows_preview(self):
        self.admin.read_only = True
        before = self.files()
        with self.assertRaises(ValueError):
            self.admin.action("draft", self.draft_request())
        self.admin.action("preview", self.preview_request())
        self.assertEqual(before, self.files())

    def test_exclusive_statuses_follow_draft_and_selection(self):
        self.admin.action("unselect", self.request())
        self.assertIn(self.did, [d["id"] for d in self.admin.catalog(status="private")["documents"]])
        self.admin.action("draft", self.draft_request())
        self.assertIn(self.did, [d["id"] for d in self.admin.catalog(status="draft")["documents"]])
        self.assertNotIn(self.did, [d["id"] for d in self.admin.catalog(status="private")["documents"]])
        candidate = self.admin.preview(self.preview_request())
        self.admin.apply_preview({"preview": candidate["id"], "token": candidate["token"]})
        self.assertNotIn(self.did, [d["id"] for d in self.admin.catalog(status="draft")["documents"]])
        self.assertIn(self.did, [d["id"] for d in self.admin.catalog(status="selected")["documents"]])

    def test_default_full_component_and_series_commit_together(self):
        req = self.preview_request(IDS["C"])
        req["series"] = {
            "slug": "together",
            "translations": {"ko": {"title": "함께", "summary": None}, "en": {"title": "Together", "summary": None}},
        }
        before = self.files()
        candidate = self.admin.preview(req)
        self.assertEqual(before, self.files())
        self.admin.apply_preview({"preview": candidate["id"], "token": candidate["token"]})
        state = self.admin.state()
        series = next(s for s in state["blog"]["series"].values() if s["slug"] == "together")
        self.assertEqual(series["documents"], [IDS["C"]])
        snapshot = state["blog"]["structure_approvals"][state["blog"]["selected_structure_approvals"][-1]]
        self.assertEqual(len(snapshot["nodes"]), len(self.admin.detail(IDS["C"])["nodes"]))
        req = self.preview_request()
        req["series"] = {"existing": series["id"]}
        candidate = self.admin.preview(req)
        self.admin.apply_preview({"preview": candidate["id"], "token": candidate["token"]})
        self.assertEqual(self.admin.state()["blog"]["series"][series["id"]]["documents"], [IDS["C"], self.did])

    def test_series_survives_revision_and_changes_only_when_explicitly_applied(self):
        from blog_test_support import reviewed_pair

        did = IDS["C"]
        app = self.admin.studio
        before = self.admin.state()
        memberships = self.admin.detail(did)["series"]
        self.assertGreater(len(memberships), 1)
        old_series = copy.deepcopy(before["blog"]["series"])
        state = app.add_revision(before, did, "New synthetic revision.", "expression edit")
        revision = state["documents"][did]["current_revision"]
        state = reviewed_pair(app, state, did, revision, "series-revision-")
        self.assertEqual(self.admin.detail(did)["series"], memberships)

        def request(series):
            return dict(self.preview_request(did), series=series)

        # No choice on a new revision must leave all memberships and reading order intact.
        candidate = self.admin.preview(request(None))
        self.admin.apply_preview({"preview": candidate["id"], "token": candidate["token"]})
        self.assertEqual(self.admin.state()["blog"]["series"], old_series)
        # A change can move an already selected revision; preview has no disk effect.
        files = self.files()
        candidate = self.admin.preview(request({"existing": memberships[-1]}))
        self.assertEqual(files, self.files())
        self.admin.apply_preview({"preview": candidate["id"], "token": candidate["token"]})
        self.assertEqual(self.admin.detail(did)["series"], [memberships[-1]])
        state = self.admin.state()
        for sid, series in old_series.items():
            self.assertEqual(
                [i for i in state["blog"]["series"][sid]["documents"] if i != did],
                [i for i in series["documents"] if i != did],
            )
        candidate = self.admin.preview(request({"existing": None}))
        self.admin.apply_preview({"preview": candidate["id"], "token": candidate["token"]})
        self.assertEqual(self.admin.detail(did)["series"], [])
        self.assertEqual(self.admin.state()["blog"]["active_release"], before["blog"]["active_release"])
        self.assertEqual(self.admin.state()["blog"]["releases"], before["blog"]["releases"])

    def test_automatic_slug_from_english_title_is_stable(self):
        # Start with v3 fixture metadata that has no assigned public identities.
        root = self.root / "slug-fixture"
        root.mkdir()
        make_fixture(root, unrelated=0)
        self.admin = Admin(root)
        did = IDS["E"]
        text = {
            "ko": {"title": "가상", "summary": ""},
            "en": {"title": "A Gentle Thought!", "summary": "", "body": "Synthetic body."},
        }
        req = self.preview_request(did, text)
        prior = self.admin.detail(did)["slug"]
        self.assertEqual(prior, "")
        candidate = self.admin.preview(req)
        self.assertIn("/" + (prior or "a-gentle-thought") + "/", candidate["url"])
        self.admin.apply_preview({"preview": candidate["id"], "token": candidate["token"]})
        self.assertEqual(self.admin.detail(did)["slug"], "a-gentle-thought")
        req["token"] = self.admin.detail(did)["token"]
        again = self.admin.preview(req)
        self.assertIn("/a-gentle-thought/", again["url"])

    def test_http_token_origin_allowlist_and_no_source_serve(self):
        server = Server(self.root, 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        port = server.server_port

        def request(path, body=None, headers=None):
            conn = http.client.HTTPConnection("127.0.0.1", port)
            conn.request("POST" if body else "GET", path, json.dumps(body) if body else None, headers or {})
            res = conn.getresponse()
            status = res.status
            data = res.read()
            conn.close()
            return status, data

        try:
            self.assertEqual(request("/")[0], 200)
            self.assertEqual(request("/data/studio.json")[0], 404)
            self.assertEqual(request("/../admin.py")[0], 404)
            self.assertEqual(request("/api/session", headers={"Host": "evil.test"})[0], 403)
            req = self.draft_request()
            self.assertEqual(request("/api/draft", req, {"Content-Type": "application/json"})[0], 403)
            headers = {"X-Blog-Token": server.token, "Content-Type": "application/json", "Origin": "http://evil.test"}
            self.assertEqual(request("/api/draft", req, headers)[0], 403)
            headers["Origin"] = "http://127.0.0.1:" + str(port)
            self.assertEqual(request("/api/draft", req, headers)[0], 200)
            self.assertEqual(request("/api/draft", req, headers)[0], 409)
            candidate = server.admin.preview(self.preview_request())
            status, data = request(candidate["url"])
            self.assertEqual(status, 200)
            self.assertNotIn(b"PRIVATE-DOCUMENT", data)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_site_status_compares_selection_with_live_pair_and_ignores_stale_drafts(self):
        state = self.admin.state()
        doc = copy.deepcopy(state["documents"][self.did])
        pair = doc["publication"]["selected_pair"]
        read = self.admin.studio.repository.read_text
        self.assertEqual(
            (site_status(doc, None, None, read)["group"], site_status(doc, None, None, read)["change"]),
            ("deploy", "new"),
        )
        live = site_status(doc, pair, None, read)
        self.assertEqual((live["group"], live["change"], live["work"]), ("live", None, None))
        variants = {
            lang: doc["language_variants"][vid] for lang, vid in doc["publication_pairs"][pair]["variants"].items()
        }
        same = {
            "revision": variants["en"]["base_revision"],
            "ko": {"title": variants["ko"]["title"], "summary": variants["ko"]["summary"] or ""},
            "en": {
                "title": variants["en"]["title"],
                "summary": variants["en"]["summary"] or "",
                "body": read(variants["en"]["body"]["path"]),
            },
        }
        self.assertIsNone(site_status(doc, pair, same, read)["work"])
        edited = copy.deepcopy(same)
        edited["en"]["body"] += "More.\n"
        self.assertEqual(
            (site_status(doc, pair, edited, read)["group"], site_status(doc, pair, edited, read)["work"]),
            ("prepare", "translation"),
        )
        # A draft kept for another revision is stale, not pending work.
        self.assertIsNone(site_status(doc, pair, dict(edited, revision="r0"), read)["work"])
        newer = copy.deepcopy(doc)
        newer["current_revision"] = "r9"
        self.assertEqual(site_status(newer, pair, None, read)["work"], "revision")
        doc["publication"]["selected_pair"] = None
        self.assertEqual(site_status(doc, pair, None, read)["change"], "withdraw")
        # Only a post some successful release carried is 'withdrawn'; a cancelled confirmation is not.
        gone = site_status(doc, None, None, read, published=True)
        self.assertEqual((gone["group"], gone["withdrawn"]), ("rest", True))
        self.assertEqual(
            (site_status(doc, None, None, read)["group"], site_status(doc, None, None, read)["withdrawn"]),
            ("prepare", False),
        )

    def test_default_catalog_keeps_publishing_roles_and_search_reaches_imports(self):
        state = self.admin.state()
        imported = copy.deepcopy(state["documents"][IDS["E"]])
        imported.update(kind="imported", title="Imported note")
        state["documents"]["imported-note"] = imported
        mocked = patch.object(self.admin, "state", return_value=state)
        mocked.start()
        self.addCleanup(mocked.stop)
        groups = {d["id"]: d["group"] for d in self.admin.catalog()["documents"]}
        self.assertNotIn("imported-note", groups)
        self.assertEqual((groups[IDS["E"]], groups[self.did]), ("prepare", "deploy"))
        self.assertNotIn(IDS["B"], groups)
        self.assertEqual(
            {d["id"]: d["group"] for d in self.admin.catalog("Imported")["documents"]}["imported-note"], "other"
        )

    def test_public_changes_name_parts_and_ignore_publication_times(self):
        before = self.admin.public_output(self.admin.state())
        after = copy.deepcopy(before)
        first, second = after["documents"][0], after["documents"][1]
        first["translations"]["en"]["body"] += "\nMore.\n"
        first["published_updated_at"] = "2030-01-01T00:00:00Z"
        second["first_published_at"] = "2030-01-01T00:00:00Z"
        after["documents"].remove(after["documents"][2])
        after["series"][0]["translations"]["ko"]["title"] = "새 이름"
        changes = public_changes(before, after)
        self.assertEqual(
            [
                (c["id"], c["change"], c["parts"])
                for c in changes["documents"]
                if c["change"] != "update" or "genealogy" not in c["parts"]
            ],
            [(first["id"], "update", ["en.body"]), (before["documents"][2]["id"], "withdraw", [])],
        )
        self.assertEqual([(s["change"], s["parts"]) for s in changes["series"]], [("update", ["translations"])])
        self.assertTrue(public_changes(before, copy.deepcopy(before))["empty"])

    def test_release_status_describes_changes_retry_and_rollback(self):
        from test_blog_release import Remote

        with tempfile.TemporaryDirectory() as folder:
            home = make_homepage(Path(folder) / "homepage")
            service = Homepage(self.root, Remote(home))
            config = service.configure(str(home))
            status = self.admin.release_status()
            self.assertEqual({c["change"] for c in status["changes"]["posts"]}, {"new"})
            self.assertIn(self.did, {c["document"] for c in status["changes"]["posts"]})
            # The screen deploys exactly the release it froze; an unstarted one is offered as is.
            frozen = self.admin.action("release-freeze-home", {"token": status["token"]})
            self.assertEqual(frozen["pending"]["release"], frozen["frozen"])
            self.assertTrue(frozen["pending"]["current"])
            self.assertFalse(frozen["pending"]["running"])
            first = frozen["frozen"]
            service.start(first)
            live = self.admin.release_status()
            self.assertTrue(live["changes"]["empty"])
            self.assertNotIn("pending", live)
            self.admin.action("unselect", self.request())
            status = self.admin.release_status()
            self.assertEqual(
                [
                    (c["change"], c["before"], c["after"])
                    for c in status["changes"]["posts"]
                    if c["document"] == self.did
                ],
                [("withdraw", "r1", None)],
            )
            self.assertEqual(
                {d["id"]: d["site"]["change"] for d in self.admin.catalog()["documents"]}[self.did], "withdraw"
            )
            self.assertEqual(self.admin.catalog()["site_changes"], status["changes"]["count"])
            second = service.freeze(status["token"], config)
            service.start(second["id"])
            with self.assertRaisesRegex(ValueError, "nothing to deploy"):
                self.admin.action("release-freeze-home", {"token": self.admin.release_status()["token"]})
            back = self.admin.release_status(first)["rollback"]["changes"]
            self.assertEqual([c["change"] for c in back["posts"] if c["document"] == self.did], ["new"])

    def test_series_metadata_and_order_edit_without_membership_changes(self):
        state = self.admin.state()
        sid = next(s for s in state["blog"]["series_order"] if len(state["blog"]["series"][s]["documents"]) > 1)
        series = state["blog"]["series"][sid]
        order = list(reversed(series["documents"]))
        names = {"ko": {"title": " 새 이름 ", "summary": ""}, "en": {"title": "New name", "summary": ""}}
        self.admin.action(
            "series-save", {"token": fingerprint(state), "series": sid, "translations": names, "documents": order}
        )
        saved = self.admin.state()["blog"]["series"][sid]
        self.assertEqual(
            (saved["translations"]["ko"]["title"], saved["documents"], saved["slug"]),
            ("새 이름", order, series["slug"]),
        )
        before = self.files()
        for bad in (
            {"documents": order[:-1]},
            {"translations": dict(names, en={"title": "New name", "summary": "Only English"})},
            {"translations": dict(names, en={"title": " ", "summary": ""})},
        ):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.admin.action(
                    "series-save",
                    dict(
                        {
                            "token": fingerprint(self.admin.state()),
                            "series": sid,
                            "translations": names,
                            "documents": order,
                        },
                        **bad,
                    ),
                )
        self.assertEqual(before, self.files())
        reordered = list(reversed(self.admin.state()["blog"]["series_order"]))
        self.admin.action("series-order", {"token": fingerprint(self.admin.state()), "order": reordered})
        self.assertEqual(self.admin.state()["blog"]["series_order"], reordered)
        with self.assertRaises(ValueError):
            self.admin.action("series-order", {"token": fingerprint(self.admin.state()), "order": reordered[1:]})

    def test_new_base_revision_is_compared_with_the_confirmed_one(self):
        self.assertIsNone(self.admin.detail(self.did)["compare"])
        state = self.admin.state()
        self.admin.studio.add_revision(state, self.did, "A revised base body.", "expression edit")
        detail = self.admin.detail(self.did)
        self.assertEqual(detail["compare"]["revision"], "r1")
        self.assertNotEqual(detail["compare"]["body"], detail["body"])

    def test_archived_post_is_not_newly_published(self):
        text = {"ko": {"title": "가상", "summary": ""}, "en": {"title": "Archived", "summary": "", "body": "Body."}}
        with self.assertRaisesRegex(ValueError, "retired piece is not published anew"):
            self.admin.action("preview", self.preview_request(IDS["B"], text))

    def live_site(self):
        """Deploy every current selection through a fake remote so reverts have a live release."""
        from test_blog_release import Remote

        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        home = make_homepage(Path(folder.name) / "homepage")
        service = Homepage(self.root, Remote(home))
        config = service.configure(str(home))
        service.start(service.freeze(fingerprint(service.state()), config)["id"])
        self.assertTrue(self.admin.release_status()["changes"]["empty"])

    def revert(self, kind, target):
        return self.admin.action("revert", {"token": fingerprint(self.admin.state()), "kind": kind, "target": target})

    def test_withdrawal_is_one_row_with_its_series_consequence_and_reverts(self):
        self.apply(
            dict(
                self.preview_request(),
                series={
                    "slug": "solo",
                    "translations": {
                        "ko": {"title": "혼자", "summary": None},
                        "en": {"title": "Solo", "summary": None},
                    },
                },
            )
        )
        self.live_site()
        live = self.admin.state()["documents"][self.did]["publication"]["selected_pair"]
        self.admin.action("unselect", self.request())
        rows = self.admin.release_status()["changes"]
        row = next(r for r in rows["posts"] if r["document"] == self.did)
        # S was the only public member of its series; that series vanishing belongs to S's row.
        self.assertEqual(row["change"], "withdraw")
        self.assertEqual(
            [e for e in row["effects"] if e["kind"] == "series-vanishes"],
            [{"kind": "series-vanishes", "title": "혼자"}],
        )
        self.assertEqual(rows["site"], [])
        after = self.revert("post", self.did)
        self.assertTrue(after["changes"]["empty"])
        self.assertEqual(self.admin.state()["documents"][self.did]["publication"]["selected_pair"], live)

    def test_revert_restores_text_series_and_draft_of_a_live_post(self):
        self.live_site()
        before = self.admin.state()
        sid = next(i for i, x in before["blog"]["series"].items() if self.did not in x["documents"])
        text = self.text_of()
        text["en"]["body"] = "Edited after publication.\n"
        self.apply(dict(self.preview_request(text=text), series={"existing": sid}))
        row = next(r for r in self.admin.release_status()["changes"]["posts"] if r["document"] == self.did)
        self.assertEqual((row["change"], row["text"]), ("update", ["en.body"]))
        self.assertIn("added", {x["change"] for x in row["series"]})
        result = self.revert("post", self.did)
        state = self.admin.state()
        self.assertTrue(result["changes"]["empty"])
        self.assertEqual(state["documents"][self.did]["publication"], before["documents"][self.did]["publication"])
        self.assertEqual(state["blog"]["series"][sid]["documents"], before["blog"]["series"][sid]["documents"])
        self.assertEqual(self.admin.draft(self.did)["en"]["body"], self.text_of()["en"]["body"])
        # The reverted variant stays recorded but is not pending work.
        self.assertEqual({d["id"]: d["group"] for d in self.admin.catalog()["documents"]}[self.did], "live")
        # The recorded variant stays; the screen gets the replaced input back once.
        self.assertEqual(
            result["discarded"]["en"]["body"] if "discarded" in result else text["en"]["body"], text["en"]["body"]
        )

    def test_revert_of_a_new_post_clears_its_translation_draft(self):
        self.live_site()
        text = {
            "ko": {"title": "가상 E", "summary": ""},
            "en": {"title": "Post E", "summary": "", "body": "English E.\n"},
        }
        self.admin.action("draft", dict(self.request(IDS["E"]), version=0, draft=dict(text, revision="r1")))
        self.apply(self.preview_request(IDS["E"], text))
        self.assertIn(
            IDS["E"], [r["document"] for r in self.admin.release_status()["changes"]["posts"] if r["change"] == "new"]
        )
        result = self.revert("post", IDS["E"])
        self.assertIsNone(self.admin.state()["documents"][IDS["E"]]["publication"]["selected_pair"])
        self.assertEqual(self.admin.draft(IDS["E"])["en"], {"title": "", "summary": "", "body": ""})
        self.assertEqual(result["discarded"]["en"]["body"], "English E.\n")
        self.assertTrue(result["changes"]["empty"])
        self.assertEqual({d["id"]: d["group"] for d in self.admin.catalog()["documents"]}[IDS["E"]], "prepare")

    def test_revert_of_shared_wording_and_site_series_settings(self):
        self.live_site()
        req = self.preview_request(IDS["C"])
        req["labels"] = [
            {
                "kind": "question",
                "target": "q",
                "public": True,
                "translations": {"ko": "PRIVATE-QUESTION-q", "en": "Asked again"},
            }
        ]
        self.apply(req)
        changes = self.admin.release_status()["changes"]
        edits = changes["labels"] + [e for r in changes["posts"] for e in r["labels"]]
        # C's confirmation owns both its wider structure approval and the wording shown in its genealogy.
        self.assertEqual(
            {(e["kind"], e["target"], e["after"]["en"]) for e in edits}, {("question", "q", "Asked again")}
        )
        owner = next(r for r in changes["posts"] if r["document"] == IDS["C"])
        self.assertEqual((owner["text"], len(owner["labels"])), (["graph"], 1))
        self.assertEqual([r["document"] for r in changes["posts"]], [IDS["C"]])
        self.assertTrue(self.revert("post", IDS["C"])["changes"]["empty"])
        # Reverting only the wording keeps the rest of C's decision.
        self.apply(dict(req, token=fingerprint(self.admin.state())))
        rows = self.revert("label", ["question", "q"])["changes"]["posts"]
        self.assertEqual([(r["document"], r["text"], r["labels"]) for r in rows], [(IDS["C"], ["graph"], [])])
        self.revert("post", IDS["C"])
        state = self.admin.state()
        sid = next(i for i, x in state["blog"]["series"].items() if len(x["documents"]) > 1)
        series = state["blog"]["series"][sid]
        self.admin.action(
            "series-save",
            {
                "token": fingerprint(state),
                "series": sid,
                "documents": list(reversed(series["documents"])),
                "translations": {
                    "ko": {"title": "바꾼 이름", "summary": ""},
                    "en": {"title": "Renamed", "summary": ""},
                },
            },
        )
        self.admin.action(
            "series-order",
            {
                "token": fingerprint(self.admin.state()),
                "order": list(reversed(self.admin.state()["blog"]["series_order"])),
            },
        )
        site = self.admin.release_status()["changes"]["site"]
        self.assertEqual({x["kind"] for x in site}, {"series", "home-order"})
        self.revert("series", sid)
        self.assertTrue(self.revert("home-order", None)["changes"]["empty"])
        self.assertEqual(self.admin.state()["blog"]["series"][sid]["translations"], series["translations"])

    def test_translating_wording_never_makes_a_private_question_public(self):
        # Earlier screens sent every row as public; the server now keeps each source's own flag.
        req = self.preview_request(IDS["C"])
        req["labels"] = [
            {
                "kind": "question",
                "target": "other",
                "public": True,
                "translations": {"ko": "PRIVATE-QUESTION-other", "en": "Other"},
            },
            {
                "kind": "edge",
                "target": IDS["C"].replace("DOCUMENT-C", "EDGE-ac"),
                "public": True,
                # The screen sends the wording as written under its own language.
                "translations": {"ko": "PRIVATE-NOTE-ac", "en": "Note"},
            },
        ]
        req["labels"] = [
            label
            for label in req["labels"]
            if label["target"] in {e["id"] for e in self.admin.state()["edges"]} | {"other"}
        ]
        candidate = self.admin.action("preview", req)
        output = b"".join(self.admin.previews[candidate["id"]]["files"].values()).decode("utf-8", errors="ignore")
        self.assertNotIn("PRIVATE-QUESTION-other", output)
        self.admin.action("select", {"preview": candidate["id"], "token": candidate["token"]})
        state = self.admin.state()
        self.assertFalse(state["questions"]["other"]["public"])
        self.assertEqual(state["blog"]["question_labels"]["other"]["translations"]["en"], "Other")
        self.assertNotIn("PRIVATE-QUESTION-other", json.dumps(self.admin.public_output(state), ensure_ascii=False))

    def test_skin_only_change_is_a_site_change_and_blocks_stale_retry(self):
        # A stylesheet change leaves the public JSON alone but changes deployed files.
        from stemma_studio.blog.preview import static_files as real

        def skinned(*args, **kwargs):
            files = real(*args, **kwargs)
            files["site.css"] += b"/* skin */"
            return files

        self.live_site()
        with patch("stemma_studio.blog.admin.static_files", side_effect=skinned):
            self.admin._rendered = None
            changes = self.admin.release_status()["changes"]
            self.assertFalse(changes["empty"])
            self.assertEqual(changes["posts"], [])
            self.assertEqual(
                [x for x in changes["site"] if x["kind"] == "skin"], [{"kind": "skin", "files": ["site.css"]}]
            )
            self.assertEqual(self.admin.catalog()["site_changes"], 1)
            # The guard compares files, so a skin-only release can be prepared.
            frozen = self.admin.action("release-freeze-home", {"token": fingerprint(self.admin.state())})
            # That release was frozen with the real stylesheet, so it no longer matches this skin.
            self.assertFalse(frozen["pending"]["current"])
