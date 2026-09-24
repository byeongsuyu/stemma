"""Publishing to a plain folder: the delivery that needs no service and no account."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from blog_fixtures import make_fixture
from stemma_studio.blog import local_folder
from stemma_studio.blog.admin import Admin
from stemma_studio.blog.local_folder import MANIFEST, PARTIAL, LocalFolder, inspect, read_manifest
from stemma_studio.core.blog import fingerprint
from stemma_studio.core.repository import FileRepository
from test_publication_v3 import phase_three


class FolderValidationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "studio"
        self.root.mkdir()

    def test_destination_must_be_absolute(self):
        with self.assertRaisesRegex(Exception, "absolute"):
            inspect("relative/path", self.root)

    def test_destination_may_not_overlap_the_data_root(self):
        for candidate in (self.root, self.root / "inside"):
            with self.assertRaisesRegex(Exception, "overlaps"):
                inspect(str(candidate), self.root)

    def test_destination_may_not_be_a_file(self):
        path = Path(self.temp.name) / "a-file"
        path.write_text("x")
        with self.assertRaisesRegex(Exception, "must be a folder"):
            inspect(str(path), self.root)

    def test_base_must_be_slash_delimited(self):
        with self.assertRaisesRegex(Exception, "Base must"):
            inspect(str(Path(self.temp.name) / "site"), self.root, "blog")

    def test_a_missing_folder_is_accepted_and_described(self):
        target = Path(self.temp.name).resolve() / "not-yet"
        self.assertEqual(inspect(str(target), self.root), {"mode": "local-folder", "path": str(target), "base": "/"})

    def test_unreadable_manifest_reads_as_never_published(self):
        target = Path(self.temp.name) / "site"
        target.mkdir()
        for content in ("{broken", json.dumps({"files": "not a mapping"})):
            (target / MANIFEST).write_text(content)
            self.assertIsNone(read_manifest(target))


class LocalPublishTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "studio"
        self.root.mkdir()
        self.site = Path(self.temp.name).resolve() / "public-site"
        self.fixture = make_fixture(self.root, unrelated=0)
        FileRepository(self.root).save(phase_three(self.fixture))
        self.admin = Admin(self.root)
        self.service = LocalFolder(self.root)

    def token(self):
        return fingerprint(self.admin.state())

    def publish(self):
        release = self.service.freeze_configured(self.token())
        self.service.start(release["id"])
        return release

    def test_a_release_is_written_verified_and_recorded_without_git(self):
        self.service.configure(str(self.site))
        release = self.publish()
        status = self.service.status()
        self.assertEqual(status["active_release"], release["id"])
        self.assertEqual(status["attempts"][-1]["status"], "succeeded")
        # Every frozen byte is on disk, and the receipt names the release.
        for name in release["files"]:
            self.assertTrue((self.site / name).is_file(), name)
        self.assertEqual(read_manifest(self.site)["release"], release["id"])
        self.assertIn("index.html", release["files"])
        self.assertTrue((self.site / "ko/index.html").read_bytes())

    def test_the_site_is_served_at_the_configured_base(self):
        self.service.configure(str(self.site), "/blog/")
        release = self.publish()
        self.assertEqual(release["base"], "/blog/")
        self.assertIn(b'href="/blog/ko/', (self.site / "ko/index.html").read_bytes())

    def test_publishing_refuses_a_folder_holding_somebody_elses_work(self):
        self.site.mkdir(parents=True)
        (self.site / "index.html").write_text("my other website")
        self.service.configure(str(self.site))
        with self.assertRaisesRegex(Exception, "already contains"):
            self.publish()
        self.assertEqual((self.site / "index.html").read_text(), "my other website")

    def test_files_this_tool_never_wrote_are_left_alone(self):
        self.site.mkdir(parents=True)
        (self.site / "CNAME").write_text("example.com")
        self.service.configure(str(self.site))
        self.publish()
        self.assertEqual((self.site / "CNAME").read_text(), "example.com")

    def test_a_changed_destination_blocks_the_next_release(self):
        self.service.configure(str(self.site))
        self.publish()
        (self.site / MANIFEST).write_text(json.dumps({"release": "x", "commit": "y", "files": {"a": "b"}}))
        state = self.admin.state()
        state["documents"][next(iter(state["documents"]))]["title"] = "changed"
        FileRepository(self.root).save(state)
        with self.assertRaisesRegex(Exception, "destination folder changed"):
            self.publish()

    def test_verification_fails_when_a_published_file_is_altered(self):
        self.service.configure(str(self.site))
        release = self.publish()
        (self.site / "index.html").write_text("tampered")
        with self.assertRaisesRegex(Exception, "differs from the frozen release"):
            LocalFolder(self.root).verify_commit(release, read_manifest(self.site)["commit"])

    def test_configuring_a_folder_replaces_a_homepage_connection(self):
        from stemma_studio.blog.homepage import Homepage

        homepage = Homepage(self.root)
        homepage.settings.parent.mkdir(parents=True, exist_ok=True)
        homepage.settings.write_text(json.dumps({"mode": "homepage-pr", "path": "/tmp/x", "branch": "main"}))
        self.admin.configure_destination({"mode": "local-folder", "destination": str(self.site)})
        self.assertIsNone(homepage.configuration())
        self.assertEqual(self.admin.release_service().__class__.__name__, "LocalFolder")
        self.assertEqual(self.admin.release_status()["destination"]["mode"], "local-folder")

    def test_a_path_published_for_the_first_time_never_lands_on_another_file(self):
        """The collision guard applies to every release, not only the first."""
        self.service.configure(str(self.site))
        self.publish()
        # Withdraw a post so its pages leave both the folder and the receipt.
        state = self.admin.state()
        target_id = next(d for d, doc in state["documents"].items() if doc["publication"]["selected_pair"])
        pair = state["documents"][target_id]["publication"]["selected_pair"]
        state["documents"][target_id]["publication"]["selected_pair"] = None
        FileRepository(self.root).save(state)
        self.publish()
        # The author puts their own file where that post used to live.
        state = self.admin.state()
        state["documents"][target_id]["publication"]["selected_pair"] = pair
        FileRepository(self.root).save(state)
        planned = self.service.freeze_configured(self.token())
        returning = sorted(p for p in planned["files"] if p not in read_manifest(self.site)["files"])
        victim = self.site / returning[0]
        victim.parent.mkdir(parents=True, exist_ok=True)
        victim.write_text("MY OWN FILE")
        with self.assertRaisesRegex(Exception, "already contains"):
            self.service.start(planned["id"])
        self.assertEqual(victim.read_text(), "MY OWN FILE")

    def outside_file(self, name="victim.txt", content="somebody else's file\n"):
        """A file that has nothing to do with this tool, to prove it stays untouched."""
        path = Path(self.temp.name).resolve() / name
        path.write_text(content)
        return path

    def interrupt_writes_at(self, stop):
        """Fail the write of one output, the way a full disk or a pulled drive would.

        Returns the call that puts the real writer back, so the rest of the test can
        inspect the destination and retry the same release."""
        original = local_folder.place

        def failing(target, name, content, suffix):
            if Path(name).name.startswith(stop):
                raise OSError("simulated failure while writing " + stop)
            return original(target, name, content, suffix)

        local_folder.place = failing
        self.addCleanup(setattr, local_folder, "place", original)
        return lambda: setattr(local_folder, "place", original)

    def test_a_symlinked_folder_inside_the_destination_is_refused(self):
        # Checking only the destination root leaves every folder below it free to point
        # somewhere else, which would publish the site into a stranger's directory.
        outside = Path(self.temp.name).resolve() / "elsewhere"
        outside.mkdir()
        self.site.mkdir(parents=True)
        (self.site / "ko").symlink_to(outside, target_is_directory=True)
        self.service.configure(str(self.site))
        with self.assertRaisesRegex(Exception, "escapes the destination"):
            self.publish()
        self.assertEqual(sorted(outside.iterdir()), [])

    def test_a_published_file_replaced_by_a_symlink_is_refused_before_the_write(self):
        self.service.configure(str(self.site))
        self.publish()
        victim = self.outside_file()
        (self.site / "index.html").unlink()
        (self.site / "index.html").symlink_to(victim)
        state = self.admin.state()
        state["documents"][next(iter(state["documents"]))]["title"] = "changed"
        FileRepository(self.root).save(state)
        with self.assertRaisesRegex(Exception, "escapes the destination"):
            self.publish()
        # Verification alone is too late: the bytes would already be gone.
        self.assertEqual(victim.read_text(), "somebody else's file\n")

    def test_a_link_or_file_at_a_temporary_looking_name_is_never_written_through(self):
        # Every output is written through a sibling only its own attempt names, created
        # exclusively. A link or a stranger's file under a name that merely looks like one
        # is neither followed nor carried off by the move; it stays exactly where it was.
        victim = self.outside_file()
        self.site.mkdir(parents=True)
        (self.site / ("index.html" + PARTIAL)).symlink_to(victim)
        (self.site / (MANIFEST + PARTIAL)).write_text("somebody else's file\n")
        self.service.configure(str(self.site))
        self.publish()
        self.assertEqual(victim.read_text(), "somebody else's file\n")
        self.assertTrue((self.site / ("index.html" + PARTIAL)).is_symlink())
        self.assertEqual((self.site / (MANIFEST + PARTIAL)).read_text(), "somebody else's file\n")

    def test_the_temporary_file_is_created_exclusively(self):
        # Even a file sitting at the exact name an attempt writes through is refused
        # rather than written through; creating the temporary file is the check.
        target = self.site
        target.mkdir(parents=True)
        (target / ("index.html.x")).write_text("somebody else's file\n")
        with self.assertRaises(FileExistsError):
            local_folder.place(target.resolve(), "index.html", b"new", ".x")
        self.assertEqual((target / "index.html.x").read_text(), "somebody else's file\n")
        self.assertFalse((target / "index.html").exists())

    def test_a_crash_between_write_and_move_can_be_retried(self):
        # A process that dies after writing a temporary file never reaches its cleanup.
        # The attempt is recorded as interrupted, and the retry must neither collide with
        # that leftover nor assume ownership of it merely from the failed attempt.
        self.service.configure(str(self.site))
        release = self.service.freeze_configured(self.token())
        original = local_folder.place

        def crashing(target, name, content, suffix):
            safe = target / (name + suffix)
            safe.parent.mkdir(parents=True, exist_ok=True)
            safe.write_bytes(content)
            raise KeyboardInterrupt  # not caught by the attempt: nothing is recorded

        local_folder.place = crashing
        self.addCleanup(setattr, local_folder, "place", original)
        with self.assertRaises(KeyboardInterrupt):
            self.service.start(release["id"])
        local_folder.place = original
        leftovers = [p for p in self.site.rglob("*") if PARTIAL in p.name]
        self.assertEqual(len(leftovers), 1)
        service = LocalFolder(self.root)
        service.interrupt()
        service.start(release["id"])
        self.assertEqual(service.status()["active_release"], release["id"])
        self.assertEqual([p for p in self.site.rglob("*") if PARTIAL in p.name], leftovers)

    def test_retry_preserves_a_temporary_file_the_previous_attempt_refused(self):
        self.service.configure(str(self.site))
        self.site.mkdir(parents=True)
        original = local_folder.place
        for name in (".nojekyll", MANIFEST):
            with self.subTest(name=name):
                release = self.service.freeze_configured(self.token())
                foreign = None

                def collide(target, path, content, suffix):
                    nonlocal foreign
                    if path == name:
                        foreign = target / (path + suffix)
                        foreign.write_bytes(b"unrelated file")
                    return original(target, path, content, suffix)

                with patch.object(local_folder, "place", side_effect=collide):
                    with self.assertRaises(FileExistsError):
                        self.service.start(release["id"])
                self.assertEqual(foreign.read_bytes(), b"unrelated file")
                # A new service has only the persisted failure record, which must not
                # grant permission to delete the file whose exclusive creation failed.
                service = LocalFolder(self.root)
                service.start(release["id"])
                self.assertEqual(service.status()["active_release"], release["id"])
                self.assertEqual(foreign.read_bytes(), b"unrelated file")

    def test_a_stale_file_replaced_by_a_symlink_is_left_alone(self):
        self.service.configure(str(self.site))
        self.publish()
        stale = next(p for p in read_manifest(self.site)["files"] if p.startswith("ko/posts/"))
        victim = self.outside_file()
        (self.site / stale).unlink()
        (self.site / stale).symlink_to(victim)
        state = self.admin.state()
        for doc in state["documents"].values():
            doc["publication"]["selected_pair"] = None
        FileRepository(self.root).save(state)
        self.publish()
        # Cleanup removes only what it can still vouch for owning; it never follows a link out.
        self.assertTrue(victim.is_file())
        self.assertEqual(victim.read_text(), "somebody else's file\n")

    def test_an_interrupted_first_deployment_can_retry_its_own_files(self):
        self.service.configure(str(self.site))
        release = self.service.freeze_configured(self.token())
        restore = self.interrupt_writes_at("404.html")
        with self.assertRaises(OSError):
            self.service.start(release["id"])
        restore()
        self.assertTrue((self.site / ".nojekyll").is_file())
        self.assertIsNone(read_manifest(self.site))
        # The same frozen release must be able to finish what it started.
        service = LocalFolder(self.root)
        service.start(release["id"])
        self.assertEqual(service.status()["active_release"], release["id"])
        for name in release["files"]:
            self.assertTrue((self.site / name).is_file(), name)

    def test_a_retry_still_refuses_a_foreign_file_at_a_release_path(self):
        self.service.configure(str(self.site))
        release = self.service.freeze_configured(self.token())
        restore = self.interrupt_writes_at("404.html")
        with self.assertRaises(OSError):
            self.service.start(release["id"])
        restore()
        (self.site / "index.html").write_text("MY OWN PAGE")
        # Resuming adopts this release's own bytes, never a stranger's at the same path.
        with self.assertRaisesRegex(Exception, "already contains"):
            LocalFolder(self.root).start(release["id"])
        self.assertEqual((self.site / "index.html").read_text(), "MY OWN PAGE")

    def test_identical_bytes_are_not_adopted_without_an_attempt_receipt(self):
        # A folder that happens to hold a matching file is not this tool's to manage:
        # adopting it would mean deleting it as stale at some later release.
        self.site.mkdir(parents=True)
        (self.site / ".nojekyll").write_bytes(b"")
        self.service.configure(str(self.site))
        with self.assertRaisesRegex(Exception, "already contains"):
            self.publish()

    def freeze_through_admin(self, admin=None):
        admin = admin or Admin(self.root)
        return admin.release_action("release-freeze-home", {"token": fingerprint(admin.state())})

    def configure_through_admin(self, path, base="/"):
        admin = Admin(self.root)
        return admin.release_action(
            "release-configure",
            {"token": fingerprint(admin.state()), "mode": "local-folder", "destination": str(path), "base": base},
        )

    def deploy_through_admin(self):
        """Freeze and send, the way the screen does it, and name the release that went."""
        frozen = self.freeze_through_admin()["frozen"]
        admin = Admin(self.root)
        admin.release_action("release-deploy", {"token": fingerprint(admin.state()), "release": frozen})
        return frozen

    def test_a_release_frozen_for_another_folder_is_not_sent_here(self):
        # Freezing names a destination and delivery obeys that name, not the screen's. So
        # choosing another folder has to end the frozen release: offering it again would
        # write the site into the folder nothing on the screen mentions any more.
        other = Path(self.temp.name).resolve() / "second-folder"
        self.service.configure(str(self.site))
        release = self.service.freeze_configured(self.token())
        self.configure_through_admin(other)
        admin = Admin(self.root)
        pending = admin.release_status()["pending"]
        self.assertEqual(pending["release"], release["id"])
        self.assertFalse(pending["current"])
        self.assertFalse(pending["deployable"])
        with self.assertRaisesRegex(Exception, "different destination"):
            admin.release_action("release-deploy", {"token": fingerprint(admin.state()), "release": release["id"]})
        self.assertFalse(self.site.exists())
        self.assertFalse(other.exists())

    def test_a_folder_published_to_before_can_be_published_to_again(self):
        # Publishing to a second folder leaves the first one at an older release. That is
        # still this tool's own receipt rather than somebody else's content, so returning
        # to the first folder publishes to it instead of refusing to touch it.
        other = Path(self.temp.name).resolve() / "second-folder"
        self.configure_through_admin(self.site)
        self.deploy_through_admin()
        self.configure_through_admin(other)
        admin = Admin(self.root)
        settings = admin.site_settings()["settings"]
        admin.save_site_settings({"settings": {**settings, "ko": {**settings["ko"], "name": "새 블로그 이름"}}})
        second = self.deploy_through_admin()
        self.configure_through_admin(self.site)
        third = self.deploy_through_admin()
        self.assertEqual(read_manifest(self.site)["release"], third)
        self.assertEqual(read_manifest(other)["release"], second)
        # The folder left behind is not rewritten by the return, and the folder returned
        # to now carries the newer identity.
        self.assertIn("새 블로그 이름".encode(), (self.site / "ko/index.html").read_bytes())

    def test_a_destination_without_the_site_says_so_even_when_nothing_changed(self):
        # The screen has to tell 'nothing changed' from 'this folder does not have it yet',
        # or a freshly chosen folder is unreachable however willing the model is to fill it.
        other = Path(self.temp.name).resolve() / "second-folder"
        self.configure_through_admin(self.site)
        self.deploy_through_admin()
        self.assertFalse(Admin(self.root).release_status()["destination_missing_site"])
        self.configure_through_admin(other)
        status = Admin(self.root).release_status()
        self.assertTrue(status["changes"]["empty"])
        self.assertTrue(status["destination_missing_site"])

    def test_a_no_op_deployment_reports_no_changes_at_any_base(self):
        # The screen compared a render hardcoded to /blog/ against a release frozen at the
        # configured base, so publishing to "/" made every page look rewritten forever.
        for base in ("/", "/blog/", "/writing/notes/"):
            with self.subTest(base=base):
                site = Path(self.temp.name).resolve() / ("site" + base.replace("/", "-"))
                service = LocalFolder(self.root)
                service.configure(str(site), base)
                release = service.freeze_configured(fingerprint(Admin(self.root).state()))
                service.start(release["id"])
                admin = Admin(self.root)
                state = admin.state()
                self.assertEqual(release["base"], base)
                self.assertEqual(admin.local_render(state)["files"], release["files"])
                with self.assertRaisesRegex(ValueError, "already has this content"):
                    self.freeze_through_admin(admin)

    def test_a_freshly_chosen_destination_receives_the_whole_site(self):
        # Unchanged writing is not a reason to refuse a destination that has never had it.
        other = Path(self.temp.name).resolve() / "second-folder"
        self.service.configure(str(self.site), "/blog/")
        self.publish()
        admin = Admin(self.root)
        admin.release_action(
            "release-configure",
            {
                "token": fingerprint(admin.state()),
                "mode": "local-folder",
                "destination": str(other),
                "base": "/blog/",
            },
        )
        frozen = self.freeze_through_admin()["frozen"]
        admin = Admin(self.root)
        admin.release_action("release-deploy", {"token": fingerprint(admin.state()), "release": frozen})
        self.assertTrue((other / "index.html").is_file())
        self.assertEqual(read_manifest(other)["release"], frozen)
        # The folder left behind keeps what it was given; moving is not a takedown.
        self.assertTrue((self.site / "index.html").is_file())
        # And once this destination does have the content, unchanged writing is refused again.
        with self.assertRaisesRegex(ValueError, "already has this content"):
            self.freeze_through_admin()

    def test_a_folder_destination_refuses_a_build_step_cleanly(self):
        # Only the pull-request path builds; asking a folder to build used to raise
        # AttributeError straight out of the route.
        self.service.configure(str(self.site))
        release = self.publish()
        admin = Admin(self.root)
        with self.assertRaisesRegex(ValueError, "no build step"):
            admin.release_action("release-build", {"token": fingerprint(admin.state()), "release": release["id"]})

    def test_an_unknown_release_action_is_refused(self):
        admin = Admin(self.root)
        with self.assertRaisesRegex(ValueError, "Unknown deployment action"):
            admin.release_action("release-teleport", {"token": fingerprint(admin.state())})

    def export_reader(self, folder):
        from stemma_studio.cli import add_commands, read_export
        from stemma_studio.core.__main__ import build_parser

        parser, sub = build_parser()
        add_commands(sub)
        return read_export(str(folder), parser)

    def test_an_exported_folder_can_be_checked_against_its_own_receipt(self):
        """A published site links its assets absolutely, so opening it as a file shows an
        unstyled page and no way to tell a good export from a broken one. The receipt
        names every file and its bytes, so the question has an exact answer."""
        self.service.configure(str(self.site), "/")
        release = self.publish()
        target, record, files, missing, differing, base = self.export_reader(self.site)
        self.assertEqual(record["release"], release["id"])
        self.assertEqual((missing, differing), ([], []))
        self.assertEqual(set(files), set(release["files"]))
        # The page itself says which base it was built for; nothing else is consulted.
        self.assertEqual(base, "/")

    def test_the_base_is_read_back_from_the_pages_that_were_published(self):
        self.service.configure(str(self.site), "/blog/")
        self.publish()
        self.assertEqual(self.export_reader(self.site)[5], "/blog/")

    def test_a_changed_or_missing_file_is_named_rather_than_served_as_if_it_were_fine(self):
        self.service.configure(str(self.site), "/")
        self.publish()
        (self.site / "index.html").write_text("edited by hand")
        (self.site / "404.html").unlink()
        _, _, files, missing, differing, _ = self.export_reader(self.site)
        self.assertEqual(missing, ["404.html"])
        self.assertEqual(differing, ["index.html"])
        self.assertNotIn("index.html", files)

    def test_a_folder_this_tool_never_published_is_refused(self):
        stranger = Path(self.temp.name).resolve() / "not-ours"
        stranger.mkdir()
        (stranger / "index.html").write_text("somebody else's site")
        with self.assertRaises(SystemExit):
            self.export_reader(stranger)

    def test_a_frozen_release_can_be_read_locally_before_it_reaches_anyone(self):
        """The same question for both destinations: is this what I want to publish?

        A folder can be looked at after the fact, but a pull request has to be judged
        before it is merged, and neither release can be read at its own links from here.
        """
        self.service.configure(str(self.site), "/blog/")
        release = self.service.freeze_configured(self.token())
        preview = self.admin.release_preview(release["id"])
        # Nothing was deployed to reach this; the release is still only frozen.
        self.assertIsNone(self.service.status()["active_release"])
        self.assertTrue(preview["faithful"])
        page = preview["files"]["index.html"].decode("utf-8")
        self.assertIn("/release/" + release["id"] + "/", page)
        self.assertNotIn('href="/blog/', page)
        self.assertIn("아직 반영 전", page)
        self.assertNotIn("디자인이 바뀌었습니다", page)

    def test_a_release_preview_is_marked_as_unfaithful_when_the_skin_has_moved_on(self):
        from stemma_studio.blog import site_settings

        self.service.configure(str(self.site), "/blog/")
        release = self.service.freeze_configured(self.token())
        settings = site_settings.load(self.root)
        settings["ko"]["name"] = "이름을 바꾼 블로그"
        site_settings.save(self.root, settings)
        # Rendering the same snapshot no longer reproduces the release, so the page must
        # not present today's design as though it were what that release would send.
        preview = Admin(self.root).release_preview(release["id"])
        self.assertFalse(preview["faithful"])
        self.assertIn("디자인이 바뀌었습니다", preview["files"]["index.html"].decode("utf-8"))

    def test_the_release_offered_for_reading_is_the_one_still_waiting(self):
        """A screen offering to open a release should mean the one a decision is pending
        on. Only when nothing is waiting does the live site become the thing to read."""
        admin = Admin(self.root)
        self.assertIsNone(admin.latest_release(admin.state()))
        self.service.configure(str(self.site), "/blog/")
        frozen = self.service.freeze_configured(self.token())
        self.assertEqual(Admin(self.root).catalog()["latest_release"], frozen["id"])
        self.service.start(frozen["id"])
        # Once it is sent, the release readers actually have is the one to open.
        state = Admin(self.root).state()
        self.assertEqual(state["blog"]["active_release"], frozen["id"])
        self.assertEqual(Admin(self.root).catalog()["latest_release"], frozen["id"])

    def test_withdrawn_pages_are_removed_from_the_destination(self):
        self.service.configure(str(self.site))
        self.publish()
        published = sorted(p for p in read_manifest(self.site)["files"] if p.startswith("ko/posts/"))
        self.assertTrue(published)
        state = self.admin.state()
        for doc in state["documents"].values():
            doc["publication"]["selected_pair"] = None
        FileRepository(self.root).save(state)
        self.publish()
        for name in published:
            self.assertFalse((self.site / name).exists(), name)
        self.assertTrue((self.site / "index.html").is_file())
