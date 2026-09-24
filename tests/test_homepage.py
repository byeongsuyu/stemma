"""Homepage PR integration is exercised only against temporary local repositories."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from blog_fixtures import make_fixture, make_homepage
from stemma_studio.blog.deploy import git
from stemma_studio.blog.homepage import GitHub, Homepage
from stemma_studio.core.blog import fingerprint
from stemma_studio.core.repository import FileRepository
from test_publication_v3 import phase_three


class Remote:
    def __init__(self):
        self.result = "running"
        self.pushes = []
        self.fail = False

    def config(self, r):
        pass

    def fetch(self, target, r):
        git(target, "update-ref", "refs/remotes/origin/master", git(target, "rev-parse", "master"))

    def pr(self, r, record):
        self.pushes.append(record["commit"])
        if self.fail:
            raise OSError("interrupted request")
        return "https://github.com/example/example.github.io/pull/1"

    def status(self, r, record, service):
        return self.result


class HomepageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "studio"
        self.root.mkdir()
        fixture = make_fixture(self.root, unrelated=0)
        FileRepository(self.root).save(phase_three(fixture))
        self.home = make_homepage(Path(self.tmp.name) / "home")
        self.remote = Remote()
        self.service = Homepage(self.root, self.remote)
        self.service.configure(str(self.home))

    def freeze(self):
        return self.service.freeze_configured(fingerprint(self.service.state()))

    def test_config_freeze_and_build_preserve_dirty_homepage(self):
        r = self.freeze()
        head = git(self.home, "rev-parse", "HEAD")
        (self.home / "index.html").write_text("unsaved homepage edits")
        (self.home / "private.txt").write_text("do not publish")
        before = git(self.home, "status", "--porcelain")
        record = self.service.build(r["id"])
        self.assertEqual(git(self.home, "rev-parse", "HEAD"), head)
        self.assertEqual(git(self.home, "status", "--porcelain"), before)
        self.assertEqual((self.home / "index.html").read_text(), "unsaved homepage edits")
        self.assertFalse((Path(record["worktree"]) / "private.txt").exists())
        self.assertEqual((Path(record["worktree"]) / "index.html").read_text(), "existing homepage")
        self.assertTrue((Path(record["worktree"]) / "blog/ko/index.html").exists())
        self.assertEqual(record, self.service.build(r["id"]))
        self.assertEqual(Homepage(self.root).configuration()["path"], str(self.home.resolve()))

    def test_retry_reuses_commit_and_only_success_marks_publication(self):
        r = self.freeze()
        self.remote.fail = True
        with self.assertRaises(OSError):
            self.service.start(r["id"])
        self.remote.fail = False
        self.service.start(r["id"])
        self.assertEqual(self.remote.pushes[0], self.remote.pushes[1])
        self.assertIsNone(self.service.status()["active_release"])
        self.assertEqual(self.service.record(r)["url"], "https://github.com/example/example.github.io/pull/1")
        self.remote.result = "succeeded"
        self.service.check()
        self.assertEqual(self.service.status()["active_release"], r["id"])

    def test_interrupted_local_build_resumes_without_new_branch(self):
        r = self.freeze()
        original = Path.write_bytes

        def fail_css(path, data):
            if path.name == "site.css":
                raise OSError("interrupted artifact write")
            return original(path, data)

        with patch.object(Path, "write_bytes", fail_css):
            with self.assertRaises(OSError):
                self.service.build(r["id"])
        self.assertIsNone(self.service.record(r)["commit"])
        record = self.service.build(r["id"])
        self.service.verify_commit(r, record["commit"])

    def test_unknown_blog_and_symlink_root_rejected(self):
        (self.home / "blog").symlink_to(self.root, target_is_directory=True)
        git(self.home, "add", "blog")
        git(self.home, "commit", "-m", "Foreign blog")
        r = self.freeze()
        with self.assertRaises(ValueError):
            self.service.build(r["id"])

    def test_unpushed_base_is_never_pushed(self):
        self.remote.fetch(self.home, {})
        remote_head = git(self.home, "rev-parse", "master")
        (self.home / "secret.txt").write_text("unpublished local commit")
        git(self.home, "add", ".")
        git(self.home, "commit", "-m", "Local only")
        r = self.freeze()
        self.service.build(r["id"])
        with patch.object(
            self.remote,
            "fetch",
            side_effect=lambda target, r: git(target, "update-ref", "refs/remotes/origin/master", remote_head),
        ):
            with self.assertRaises(ValueError):
                self.service.start(r["id"])
        self.assertEqual(self.remote.pushes, [])

    def test_frozen_artifact_tampering_rejected(self):
        r = self.freeze()
        record = self.service.build(r["id"])
        git(self.home, "update-ref", "refs/heads/" + record["branch"], record["base"])
        # The verified commit, not the current mutable branch tip, is the only push input.
        self.service.verify_commit(r, record["commit"])
        path = Path(record["worktree"]) / "blog/site.css"
        path.write_text("changed worktree")
        self.service.verify_commit(r, record["commit"])

    def test_success_requires_merged_head_and_matching_pages_commit(self):
        r = self.freeze()
        record = self.service.build(r["id"])
        commit = record["commit"]
        remote = GitHub()
        config = {"build_type": "legacy", "source": {"branch": "master", "path": "/"}}
        merged = {"merged": True, "head": {"sha": commit}, "merge_commit_sha": commit}
        with (
            patch("stemma_studio.blog.homepage.command", return_value=json.dumps([{"number": 1}])),
            patch.object(remote, "fetch"),
            patch.object(remote, "api", side_effect=[config, merged, {"commit": "0" * 40, "status": "built"}]),
        ):
            self.assertEqual(remote.status(r, record, self.service), "running")
        with (
            patch("stemma_studio.blog.homepage.command", return_value=json.dumps([{"number": 1}])),
            patch.object(remote, "fetch"),
            patch.object(remote, "api", side_effect=[config, merged, {"commit": commit, "status": "built"}]),
        ):
            self.assertEqual(remote.status(r, record, self.service), "succeeded")
