"""Release lifecycle tests use disposable corpora, local repositories and a fake remote.

Delivery is the homepage PR path; these cover what every release shares with it:
frozen bytes, publication dates, failure recovery, rollback and immutable receipts.
"""

import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from blog_fixtures import IDS, RELEASE_TIME, make_fixture, make_homepage
from stemma_studio.blog.deploy import git
from stemma_studio.blog.homepage import Homepage, inspect
from stemma_studio.core.blog import fingerprint
from stemma_studio.core.repository import FileRepository
from test_publication_v3 import phase_three


class Remote:
    """A local stand-in for GitHub; merging the reviewed commit is what succeeds."""

    def __init__(self, home):
        self.home = home
        self.result = "succeeded"
        self.fail = False
        self.pushes = []

    def config(self, r):
        pass

    def fetch(self, target, r):
        git(target, "update-ref", "refs/remotes/origin/master", git(target, "rev-parse", "master"))

    def pr(self, r, record):
        self.pushes.append(record["commit"])
        if self.fail:
            raise OSError("synthetic remote failure")
        return "https://github.com/example/example.github.io/pull/1"

    def status(self, r, record, service):
        if self.result == "succeeded":
            git(self.home, "update-ref", "refs/heads/master", record["commit"])
        return self.result


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.root = self.folder / "studio"
        self.root.mkdir()
        self.fixture = make_fixture(self.root, unrelated=0)
        self.repo = FileRepository(self.root)
        self.repo.save(phase_three(self.fixture))
        self.home = make_homepage(self.folder / "home")
        self.remote = Remote(self.home)
        self.service = Homepage(self.root, self.remote)
        self.config = self.service.configure(str(self.home))

    def freeze(self, planned=RELEASE_TIME, **kwargs):
        return self.service.freeze(fingerprint(self.service.state()), self.config, planned_at=planned, **kwargs)

    def test_frozen_artifact_matches_release_and_leaks_nothing(self):
        before = self.service.state()
        r = self.freeze()
        files = self.service.artifact(r)
        self.assertEqual(set(files), set(r["files"]))
        content = b"".join(files.values()).decode("utf-8", errors="ignore")
        for sentinel in self.fixture["sentinels"]:
            self.assertNotIn(sentinel, content)
        self.assertIn("/blog/ko/", content)
        self.assertNotIn("admin.js", content)
        self.assertIsNone(self.service.state()["blog"]["active_release"])
        self.assertEqual(before["documents"], self.service.state()["documents"])

    def test_failure_retry_freezes_bytes_and_dates(self):
        r = self.freeze()
        self.remote.fail = True
        with self.assertRaises(OSError):
            self.service.start(r["id"])
        self.assertIsNone(self.service.state()["blog"]["active_release"])
        self.assertEqual(self.service.status()["attempts"][-1]["status"], "failed")
        state = self.service.state()
        self.service.studio.select_publication(state, IDS["S"], None)
        self.remote.fail = False
        self.service.start(r["id"])
        state = self.service.state()
        # A later withdrawal never changes the commit or the dates already frozen.
        self.assertEqual(self.remote.pushes[0], self.remote.pushes[1])
        self.assertEqual(state["blog"]["active_release"], r["id"])
        self.assertEqual(state["documents"][IDS["S"]]["publication"]["first_published_at"], RELEASE_TIME)
        self.assertIsNone(state["documents"][IDS["S"]]["publication"]["selected_pair"])
        before = copy.deepcopy(state)
        self.service.start(r["id"])
        self.assertEqual(before, self.service.state())

    def test_pending_restart_check_and_stale_release(self):
        r = self.freeze()
        other = self.freeze()
        self.remote.result = "running"
        self.service.start(r["id"])
        self.assertIsNone(self.service.state()["blog"]["active_release"])
        with self.assertRaises(ValueError):
            self.service.start(other["id"])
        resumed = Homepage(self.root, self.remote)
        self.remote.result = "succeeded"
        resumed.check()
        self.assertEqual(resumed.status()["active_release"], r["id"])
        with self.assertRaises(ValueError):
            resumed.start(other["id"])

    def test_unpublish_republish_and_unchanged_dates(self):
        r = self.freeze()
        self.service.start(r["id"])
        s = self.service.state()
        self.service.studio.select_publication(s, IDS["S"], None)
        second = self.freeze("2026-09-17T01:00:00Z")
        self.service.start(second["id"])
        self.assertNotIn("ko/posts/post-s/index.html", second["files"])
        self.assertEqual(
            self.service.state()["documents"][IDS["A"]]["publication"]["published_updated_at"], RELEASE_TIME
        )
        s = self.service.state()
        self.service.studio.select_publication(s, IDS["S"], r["selections"][IDS["S"]])
        third = self.freeze("2026-09-18T01:00:00Z")
        self.service.start(third["id"])
        pub = self.service.state()["documents"][IDS["S"]]["publication"]
        self.assertEqual(pub["first_published_at"], RELEASE_TIME)
        self.assertEqual(pub["published_updated_at"], "2026-09-18T01:00:00Z")

    def test_reviewed_rollback_creates_new_history(self):
        first = self.freeze()
        self.service.start(first["id"])
        self.service.studio.select_publication(self.service.state(), IDS["S"], None)
        second = self.freeze("2026-09-17T01:00:00Z")
        self.service.start(second["id"])
        self.assertNotIn("ko/posts/post-s/index.html", second["files"])
        rollback = self.freeze("2026-09-18T01:00:00Z", rollback=first["id"])
        self.assertNotEqual(first["id"], rollback["id"])
        self.service.start(rollback["id"])
        self.assertIn("ko/posts/post-s/index.html", rollback["files"])
        self.assertEqual(self.service.status()["active_release"], rollback["id"])

    def test_release_history_survives_a_checkout_that_is_no_longer_there(self):
        """Moving machines, or tidying a folder away, must not take the screen down with it.

        Reading a checkout-local PR receipt revalidates that checkout and its origin, so a
        historical release pointed the whole status response at a folder it no longer needs.
        """
        from stemma_studio.blog.admin import Admin

        r = self.freeze()
        self.service.start(r["id"])
        admin = Admin(self.root)
        self.assertIn(r["id"], admin.release_status()["pull_requests"])
        self.home.rename(self.folder / "moved-away")
        status = admin.release_status()
        self.assertEqual(status["active_release"], r["id"])
        self.assertEqual([x["id"] for x in status["releases"]], [r["id"]])
        # The PR detail is simply unavailable; everything else about the release still reads.
        self.assertEqual(status["pull_requests"], {})

    def test_homepage_destination_must_not_overlap_private_workspace(self):
        for path in (self.root, self.root / "output", self.folder):
            with self.assertRaises(ValueError):
                inspect(str(path), self.root)
        plain = self.folder / "plain"
        plain.mkdir()
        with self.assertRaises(ValueError):
            inspect(str(plain), self.root)

    def test_tampered_snapshot_and_artifact_fail_closed(self):
        r = self.freeze()
        name = next(iter(r["files"]))
        (self.root / "data/blog/releases" / r["id"] / "site" / name).write_bytes(b"tampered artifact")
        with self.assertRaises(ValueError):
            self.service.artifact(r)
        snapshot = self.root / r["public_snapshot"]
        snapshot.write_text("{}")
        with self.assertRaises(ValueError):
            self.service.state()

    def test_success_receipts_and_release_records_cannot_be_rewritten(self):
        r = self.freeze()
        self.service.start(r["id"])
        state = self.service.state()
        modified = copy.deepcopy(state)
        modified["blog"]["releases"][r["id"]]["base"] = "/other/"
        with self.assertRaises(ValueError):
            self.repo.save(modified)
        modified = copy.deepcopy(state)
        modified["blog"]["release_attempts"][0]["commit"] = "0" * 40
        with self.assertRaises(ValueError):
            self.repo.save(modified)
        modified = copy.deepcopy(state)
        modified["documents"][IDS["S"]]["publication"]["first_published_at"] = None
        with self.assertRaises(ValueError):
            self.repo.save(modified)

    def test_static_artifact_serves_without_studio(self):
        import functools
        import http.client
        import threading
        from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

        r = self.freeze()
        files = self.service.artifact(r)
        with tempfile.TemporaryDirectory() as isolated:
            web = Path(isolated) / "blog"
            web.mkdir()
            for name, data in files.items():
                p = web / name
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(data)

            class Quiet(SimpleHTTPRequestHandler):
                def log_message(self, *args):
                    pass

            server = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=isolated))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                for route in ("ko/posts/post-s/", "en/posts/post-s/genealogy/", "site.css", "404.html"):
                    conn = http.client.HTTPConnection("127.0.0.1", server.server_port)
                    conn.request("GET", "/blog/" + route)
                    response = conn.getresponse()
                    self.assertEqual(response.status, 200)
                    response.read()
                    conn.close()
                conn = http.client.HTTPConnection("127.0.0.1", server.server_port)
                conn.request("GET", "/data/studio.json")
                response = conn.getresponse()
                self.assertEqual(response.status, 404)
                response.read()
                conn.close()
            finally:
                server.shutdown()
                server.server_close()
                thread.join()

    def test_build_and_push_failure_do_not_mark_success(self):
        r = self.freeze()
        with patch.object(self.service, "build", side_effect=OSError("staging failure")):
            with self.assertRaises(OSError):
                self.service.start(r["id"])
        self.assertIsNone(self.service.status()["active_release"])
        self.assertEqual(self.remote.pushes, [])


if __name__ == "__main__":
    unittest.main()
