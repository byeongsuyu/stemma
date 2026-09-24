"""Contracts the shipped interface markup has to keep for people not using a mouse.

These read the HTML the wheel serves rather than a copy, so a screen that grows a new
dialog or tab strip cannot quietly ship without the parts that make it operable.
"""

import re
import unittest
from pathlib import Path

import stemma_studio

SOURCE = Path(stemma_studio.__file__).resolve().parent
PAGES = [
    SOURCE / "editor" / "frontend" / "index.html",
    SOURCE / "editor" / "frontend" / "genealogy.html",
    SOURCE / "blog" / "admin_frontend" / "index.html",
]


def ids(markup):
    return set(re.findall(r'\bid="([^"]+)"', markup))


class InterfaceAccessTests(unittest.TestCase):
    def pages(self):
        for path in PAGES:
            self.assertTrue(path.is_file(), path)
            yield path.name, path.read_text(encoding="utf-8")

    def test_every_dialog_is_named_by_a_heading_that_exists(self):
        """A dialog without a name is announced as just 'dialog' when it opens."""
        found = 0
        for name, markup in self.pages():
            for opening in re.findall(r"<dialog\b[^>]*>", markup):
                found += 1
                match = re.search(r'aria-labelledby="([^"]+)"', opening)
                self.assertIsNotNone(match, f"{name}: dialog without an accessible name: {opening}")
                self.assertIn(match.group(1), ids(markup), f"{name}: aria-labelledby names a missing element")
        self.assertGreaterEqual(found, 3, "expected to have checked every dialog the interface ships")

    def test_every_tab_controls_a_panel_that_exists(self):
        found = 0
        for name, markup in self.pages():
            for tab in re.findall(r'<button\b[^>]*role="tab"[^>]*>', markup):
                found += 1
                match = re.search(r'aria-controls="([^"]+)"', tab)
                self.assertIsNotNone(match, f"{name}: tab without aria-controls: {tab}")
                self.assertIn(match.group(1), ids(markup), f"{name}: aria-controls names a missing panel")
        self.assertGreaterEqual(found, 3, "expected to have checked the publication preview tabs")

    def test_a_tablist_always_says_what_it_is_for(self):
        for name, markup in self.pages():
            for tablist in re.findall(r'<[^>]*role="tablist"[^>]*>', markup):
                self.assertRegex(tablist, r'aria-label(?:ledby)?="', f"{name}: unnamed tablist: {tablist}")

    def test_zooming_is_never_disabled(self):
        """Pinch zoom is how somebody reads small text; the page may not take it away."""
        for name, markup in self.pages():
            viewport = re.search(r'<meta name="viewport" content="([^"]+)"', markup)
            self.assertIsNotNone(viewport, f"{name}: no viewport declaration")
            self.assertNotIn("user-scalable=no", viewport.group(1), name)
            self.assertNotIn("maximum-scale", viewport.group(1), name)
