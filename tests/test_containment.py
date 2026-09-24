"""Staying inside a folder this tool does not own, whatever the path looks like."""

import tempfile
import unittest
from pathlib import Path

from stemma_studio.core.containment import contained, safe_path
from stemma_studio.core.domain import ModelError


class ContainmentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve() / "owned"
        self.root.mkdir()
        self.outside = Path(self.temp.name).resolve() / "not-owned"
        self.outside.mkdir()

    def test_an_ordinary_relative_path_resolves_under_the_root(self):
        self.assertEqual(contained(self.root, "ko/posts/index.html"), self.root / "ko/posts/index.html")

    def test_a_path_that_does_not_exist_yet_is_allowed(self):
        # The ordinary case for a file about to be written for the first time.
        self.assertEqual(contained(self.root, "brand/new.html"), self.root / "brand/new.html")

    def test_upward_absolute_and_empty_paths_are_refused(self):
        for value in ("../escape", "ko/../../escape", "ko/../ok", "/etc/passwd", "", "."):
            self.assertIsNone(contained(self.root, value), value)

    def test_a_redundant_current_folder_segment_is_still_the_same_path(self):
        # "./x" and "ko/./x" name nothing outside the root, so they are not escapes.
        self.assertEqual(contained(self.root, "./here"), self.root / "here")
        self.assertEqual(contained(self.root, "ko/./x"), self.root / "ko/x")

    def test_a_symlinked_leaf_is_refused(self):
        victim = self.outside / "victim.txt"
        victim.write_text("theirs")
        (self.root / "page.html").symlink_to(victim)
        self.assertIsNone(contained(self.root, "page.html"))

    def test_a_symlinked_parent_is_refused(self):
        (self.root / "ko").symlink_to(self.outside, target_is_directory=True)
        # The leaf does not exist yet, so only the component check can catch this.
        self.assertIsNone(contained(self.root, "ko/index.html"))
        self.assertIsNone(contained(self.root, "ko/posts/deep/index.html"))

    def test_a_dangling_symlink_is_refused(self):
        (self.root / "gone.html").symlink_to(self.outside / "never-existed.txt")
        self.assertIsNone(contained(self.root, "gone.html"))

    def test_safe_path_refuses_loudly_and_names_the_path(self):
        (self.root / "ko").symlink_to(self.outside, target_is_directory=True)
        with self.assertRaisesRegex(ModelError, "ko/index.html"):
            safe_path(self.root, "ko/index.html")
        self.assertEqual(safe_path(self.root, "fine.html"), self.root / "fine.html")
