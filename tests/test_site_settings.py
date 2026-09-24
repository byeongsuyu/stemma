"""The blog's identity lives in the author's data root, never in the code."""

import json
import tempfile
import unittest
from pathlib import Path

from stemma_studio.blog import site_settings
from stemma_studio.blog.homepage import private_locations


class SiteSettingsTests(unittest.TestCase):
    def test_missing_file_yields_neutral_placeholders(self):
        with tempfile.TemporaryDirectory() as folder:
            site = site_settings.load(folder)
            self.assertEqual({lang: site[lang] for lang in site_settings.LANGUAGES}, site_settings.DEFAULTS)
            for language in site_settings.LANGUAGES:
                self.assertEqual(set(site[language]), set(site_settings.FIELDS))

    def test_stored_values_override_only_the_fields_given(self):
        with tempfile.TemporaryDirectory() as folder:
            site_settings.save(folder, {"en": {"name": "Field Notes", "author": "Ada"}})
            site = site_settings.load(folder)
            self.assertEqual(site["en"]["name"], "Field Notes")
            self.assertEqual(site["en"]["author"], "Ada")
            self.assertEqual(site["en"]["byline"], site_settings.DEFAULTS["en"]["byline"])
            self.assertEqual(site["ko"], site_settings.DEFAULTS["ko"])

    def test_blank_and_unknown_entries_fall_back(self):
        for given in ({"en": {"name": "   ", "nope": "x"}, "de": {"name": "x"}}, "not a mapping"):
            site = site_settings.normalise(given)
            self.assertEqual({lang: site[lang] for lang in site_settings.LANGUAGES}, site_settings.DEFAULTS)

    def test_settings_live_beside_the_other_blog_settings(self):
        self.assertEqual(site_settings.settings_path("/tmp/root"), Path("/tmp/root/data/blog/site.json"))

    def test_invalid_json_is_reported_with_its_path(self):
        with tempfile.TemporaryDirectory() as folder:
            path = site_settings.settings_path(folder)
            path.parent.mkdir(parents=True)
            path.write_text("{not json")
            with self.assertRaisesRegex(ValueError, "Invalid site settings"):
                site_settings.load(folder)

    def test_saved_file_is_readable_json(self):
        with tempfile.TemporaryDirectory() as folder:
            site_settings.save(folder, {"ko": {"name": "기록"}})
            stored = json.loads(site_settings.settings_path(folder).read_text(encoding="utf-8"))
            self.assertEqual(stored["ko"]["name"], "기록")


class PrivateLocationTests(unittest.TestCase):
    """The homepage guard reads the archive path from the data root, not from a constant."""

    def test_archive_path_comes_from_the_data_root(self):
        with tempfile.TemporaryDirectory() as folder:
            metadata = Path(folder) / "data" / "studio.json"
            metadata.parent.mkdir(parents=True)
            archive = Path(folder) / "somewhere-else"
            archive.mkdir()
            metadata.write_text(json.dumps({"archive": {"path": str(archive)}}))
            self.assertIn(archive.resolve(), private_locations(folder))

    def test_no_metadata_and_no_archive_still_guards_root_and_code(self):
        with tempfile.TemporaryDirectory() as folder:
            locations = private_locations(folder)
            self.assertIn(Path(folder).resolve(), locations)
            self.assertTrue(any(p.name == "stemma_studio" for p in locations))

    def test_unreadable_metadata_does_not_crash_the_guard(self):
        with tempfile.TemporaryDirectory() as folder:
            metadata = Path(folder) / "data" / "studio.json"
            metadata.parent.mkdir(parents=True)
            metadata.write_text("{broken")
            self.assertIn(Path(folder).resolve(), private_locations(folder))


class ContentLicenceTests(unittest.TestCase):
    """The code is MIT; the writing's terms belong to whoever wrote it."""

    def test_default_reserves_all_rights(self):
        site = site_settings.normalise(None)
        self.assertEqual(site["license"]["id"], site_settings.DEFAULT_LICENSE)
        copyright_text, label, url = site_settings.rights(site, "en")
        self.assertEqual(copyright_text, "© Author.")
        self.assertEqual(label, "All rights reserved")
        self.assertEqual(url, "")

    def test_preset_supplies_its_own_label_and_link(self):
        site = site_settings.normalise({"license": {"id": "cc-by-4.0"}})
        for language, expected in (("ko", "CC BY 4.0"), ("en", "CC BY 4.0")):
            _, label, url = site_settings.rights(site, language)
            self.assertEqual(label, expected)
            self.assertEqual(url, "https://creativecommons.org/licenses/by/4.0/")

    def test_a_stale_stored_label_never_overrides_a_preset(self):
        site = site_settings.normalise({"license": {"id": "cc0-1.0", "en": "Whatever", "url": "https://evil.test"}})
        _, label, url = site_settings.rights(site, "en")
        self.assertNotEqual(label, "Whatever")
        self.assertEqual(url, site_settings.LICENSES["cc0-1.0"]["url"])

    def test_custom_terms_are_kept_per_language(self):
        site = site_settings.normalise(
            {
                "license": {
                    "id": "custom",
                    "ko": "출처를 밝혀 주세요",
                    "en": "Please credit",
                    "url": "https://example.com/t",
                }
            }
        )
        self.assertEqual(site_settings.rights(site, "ko")[1], "출처를 밝혀 주세요")
        self.assertEqual(site_settings.rights(site, "en")[1], "Please credit")
        self.assertEqual(site_settings.rights(site, "en")[2], "https://example.com/t")

    def test_empty_custom_terms_fall_back_to_reserving_rights(self):
        site = site_settings.normalise({"license": {"id": "custom"}})
        self.assertEqual(site_settings.rights(site, "en")[1], "All rights reserved")

    def test_unknown_licence_id_falls_back(self):
        self.assertEqual(
            site_settings.normalise({"license": {"id": "made-up"}})["license"]["id"], site_settings.DEFAULT_LICENSE
        )

    def test_only_http_links_are_accepted(self):
        for bad in ("javascript:alert(1)", "data:text/html,x", "file:///etc/passwd", "ftp://x/y", "  "):
            site = site_settings.normalise({"license": {"id": "custom", "en": "Terms", "url": bad}})
            self.assertEqual(site_settings.rights(site, "en")[2], "", bad)

    def test_stored_file_keeps_only_the_choice_for_presets(self):
        with tempfile.TemporaryDirectory() as folder:
            site_settings.save(folder, {"license": {"id": "cc-by-sa-4.0", "en": "stale"}})
            stored = json.loads(site_settings.settings_path(folder).read_text(encoding="utf-8"))
            self.assertEqual(stored["license"], {"id": "cc-by-sa-4.0"})

    def test_stored_file_keeps_custom_wording(self):
        with tempfile.TemporaryDirectory() as folder:
            site_settings.save(
                folder, {"license": {"id": "custom", "ko": "조건", "en": "Terms", "url": "https://example.com/t"}}
            )
            stored = json.loads(site_settings.settings_path(folder).read_text(encoding="utf-8"))
            self.assertEqual(
                stored["license"], {"id": "custom", "ko": "조건", "en": "Terms", "url": "https://example.com/t"}
            )

    def test_every_preset_is_offered_with_both_labels(self):
        offered = site_settings.choices()
        self.assertEqual([c["id"] for c in offered], list(site_settings.LICENSES))
        for entry in offered:
            self.assertTrue(entry["ko"] and entry["en"])


class AdminSettingsTests(unittest.TestCase):
    """The settings screen is how an author configures a site without editing JSON."""

    def setUp(self):
        import sys

        sys.path.insert(0, str(Path(__file__).parent))
        from blog_fixtures import make_fixture
        from stemma_studio.blog.admin import Admin

        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        make_fixture(self.root, unrelated=0)
        self.admin = Admin(self.root)

    def test_read_offers_current_settings_and_every_preset(self):
        payload = self.admin.site_settings()
        self.assertEqual(payload["settings"]["ko"], site_settings.DEFAULTS["ko"])
        self.assertEqual(payload["settings"]["license"]["id"], site_settings.DEFAULT_LICENSE)
        self.assertEqual([c["id"] for c in payload["licenses"]], list(site_settings.LICENSES))
        self.assertEqual(payload["custom_id"], site_settings.CUSTOM)

    def test_saving_persists_identity_and_licence(self):
        given = {
            "ko": {"name": "숲의 기록", "author": "김하늘", "byline": "김하늘 씀", "intro": "천천히 읽습니다"},
            "en": {
                "name": "Forest Notes",
                "author": "Haneul Kim",
                "byline": "by Haneul Kim",
                "intro": "Reading slowly",
            },
            "license": {"id": "cc-by-nc-4.0"},
        }
        returned = self.admin.action("site-settings", {"settings": given})
        self.assertEqual(returned["settings"]["ko"]["name"], "숲의 기록")
        self.assertEqual(returned["settings"]["license"]["id"], "cc-by-nc-4.0")
        # A second Admin over the same root reads what the first one wrote.
        from stemma_studio.blog.admin import Admin

        self.assertEqual(Admin(self.root).site_settings()["settings"], returned["settings"])

    def test_saving_requires_a_settings_object(self):
        for bad in ({}, {"settings": "text"}, {"settings": None}):
            with self.assertRaises(ValueError):
                self.admin.action("site-settings", bad)

    def test_read_only_mode_refuses_to_save(self):
        from stemma_studio.blog.admin import Admin

        reader = Admin(self.root, read_only=True)
        self.assertEqual(reader.site_settings()["settings"]["ko"], site_settings.DEFAULTS["ko"])
        with self.assertRaisesRegex(ValueError, "read-only"):
            reader.action("site-settings", {"settings": {"ko": {"name": "x"}}})

    def test_changed_identity_reaches_the_rendered_site(self):
        """Settings are a site change: the deployable files must differ afterwards."""
        before = self.admin.local_render(self.admin.state())["files"]
        self.admin.action("site-settings", {"settings": {"en": {"name": "Forest Notes"}}})
        after = self.admin.local_render(self.admin.state())["files"]
        self.assertNotEqual(before, after)
