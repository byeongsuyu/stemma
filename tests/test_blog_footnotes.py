"""Footnote navigation and private-link policy survive the export boundary."""

import unittest

from stemma_studio.blog.attachments import referenced_attachments
from stemma_studio.blog.footnotes import footnotes
from stemma_studio.blog.input import LinkRewriter
from stemma_studio.blog.markdown import external_url, markdown
from stemma_studio.blog.math_support import tex_plugin
from stemma_studio.blog.vendor.mistune import create_markdown


class FootnoteTests(unittest.TestCase):
    def test_repeated_refs_have_unique_targets_and_backlinks(self):
        output = markdown("One[^2], again[^2].\n\n[^2]: **Note**.", external_url)
        self.assertIn('id="fnref-1"', output)
        self.assertIn('id="fnref-1-2"', output)
        self.assertIn('href="#fnref-1-2"', output)
        self.assertEqual(output.count('id="fn-1"'), 1)
        self.assertIn("<strong>Note</strong>", output)

    def test_projection_preserves_notes_math_and_reference_links(self):
        source = "Text[^private-label].\n\n[^private-label]: [site][a], [secret](file:///private). $x^2$\n\n    Second paragraph.\n\n[a]: https://example.com\n\n[^unused]: HIDDEN\n"
        projected = create_markdown(renderer=LinkRewriter({}), plugins=[tex_plugin, footnotes])(source)
        output = markdown(projected, external_url)
        self.assertNotIn("private-label", projected)
        self.assertNotIn("file:", projected)
        self.assertNotIn("HIDDEN", projected)
        self.assertIn('href="https://example.com"', output)
        self.assertIn("Second paragraph.", output)
        self.assertIn("<math ", output)
        self.assertIn('id="fn-1"', output)

    def test_missing_definition_and_code_remain_literal(self):
        output = markdown("Missing[^9] and `[^1]`.\n\n[^1]: Unused.", external_url)
        self.assertIn("Missing[^9]", output)
        self.assertIn("<code>[^1]</code>", output)
        self.assertNotIn("Unused", output)

    def test_used_note_attachments_are_discovered(self):
        asset = {"snapshot": "data/assets/image.jpg", "archive_path": "image.jpg", "sha256": "a" * 64}
        doc = {"source": {"assets": [asset]}}
        state = {"documents": {"doc": doc}}
        result = referenced_attachments(state, doc, "Photo[^1].\n\n[^1]: ![image](image.jpg)\n")
        self.assertEqual([a["path"] for a in result], ["data/assets/image.jpg"])
