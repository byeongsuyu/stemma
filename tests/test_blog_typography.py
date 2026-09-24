"""Static tables and TeX must survive projection without weakening the HTML boundary."""

import unittest

from stemma_studio.blog.footnotes import footnotes
from stemma_studio.blog.input import LinkRewriter
from stemma_studio.blog.markdown import markdown
from stemma_studio.blog.math_support import tex_plugin
from stemma_studio.blog.vendor.mistune import create_markdown
from stemma_studio.blog.vendor.mistune.plugins.table import table


class TypographyTests(unittest.TestCase):
    def render(self, text):
        return markdown(text, lambda url: None)

    def test_inline_display_matrix_and_aligned_math(self):
        source = r"""Inline $x^2$ and \(\frac{a}{b}\).

\[
\begin{pmatrix}1&2\\3&4\end{pmatrix}
\]

$$
\begin{aligned}f(x)&=x^2\\f'(x)&=2x\end{aligned}
$$
"""
        output = self.render(source)
        self.assertEqual(output.count("<math "), 4)
        self.assertIn("<mfrac>", output)
        self.assertIn("<mtable", output)
        self.assertNotIn("<script", output)
        self.assertNotIn("cdn.", output)

    def test_tables_have_semantics_alignment_and_local_overflow(self):
        output = self.render("| Name | Value |\n| :--- | ---: |\n| **A** | $x^2$ |")
        self.assertIn("table-scroll", output)
        self.assertIn('scope="col"', output)
        self.assertIn("align-right", output)
        self.assertIn("<strong>A</strong>", output)
        self.assertIn("<math ", output)
        self.assertNotIn("style=", output)

    def test_adapter_preserves_tables_math_and_escaped_currency(self):
        source = r"""Cost \$5, then \$10. Inline \(\alpha+\beta\).

| Name | Value |
| --- | ---: |
| a\|b | $x^2$ |

$$
\int_0^1 x\,dx=\frac12
$$
"""
        projected = create_markdown(renderer=LinkRewriter({}), plugins=[table, tex_plugin])(source)
        output = self.render(projected)
        self.assertEqual(output.count("<math "), 3)
        self.assertIn("a|b", output)
        self.assertIn("Cost $5, then $10", output)

    def project(self, source):
        """The publication rewrite: parse, resolve destinations, serialise back to Markdown."""
        return create_markdown(renderer=LinkRewriter({}), plugins=[table, tex_plugin, footnotes])(source)

    def test_escaped_punctuation_survives_the_publication_rewrite(self):
        """What the author escaped stays literal after the release is prepared.

        The first parse consumes the escapes, so anything the serialiser does not put
        back is re-interpreted by the parse that renders the page: `\\*stars\\*` reached
        readers as emphasis, and `\\<b>` as a tag that then disappeared.
        """
        for source in (
            r"Literal \*stars\* and \_under\_",
            r"Literal \[label](https://example.com)",
            r"Literal \<b>text\</b>",
            r"A \# not a heading",
            r"Ampersand \& alone",
            r"Backtick \`not code\`",
            r"Bang \!\[not an image](x)",
        ):
            with self.subTest(source=source):
                self.assertEqual(self.render(self.project(source)), self.render(source))

    def test_the_rewrite_does_not_invent_mathematics_or_break_tables(self):
        """Escaping is deliberately incomplete where the escape *is* a delimiter.

        `\\(...\\)` is inline mathematics in this dialect and `\\[...\\]` display
        mathematics, so escaping parentheses and closing brackets would turn ordinary
        punctuation into formulas. A table escapes its own separators, so escaping
        pipes here as well would split the row.
        """
        for source in (
            "(parens) at line start and (more) after",
            "[a] and [b] at line start",
            "a] stray close bracket",
            "text with (a) and [b] and {c}",
            "| a \\* b | c \\| d |\n|---|---|\n| (1) | [2] |",
        ):
            with self.subTest(source=source):
                self.assertEqual(self.render(self.project(source)), self.render(source))

    def test_structure_and_inline_markup_survive_the_rewrite(self):
        for source in (
            "# Heading\n\nBody with \\*stars\\*.",
            "> a quote with \\*stars\\*",
            "- item \\*one\\*\n- item two",
            "1. first\n2. second",
            "*real emphasis* and **strong** and `code`",
            "`code with \\* star and | pipe`",
            "A footnote[^1].\n\n[^1]: The \\*note\\* text.",
            "[link](https://example.com) stays a link",
            "한국어 본문에 \\*별표\\*와 영어 mixed text.",
        ):
            with self.subTest(source=source):
                self.assertEqual(self.render(self.project(source)), self.render(source))

    def test_code_fences_and_code_spans_do_not_become_math(self):
        output = self.render("`$x$`\n\n```python\n$x$\n```\n\n```math\nx^2\n```")
        self.assertEqual(output.count("<math "), 1)
        self.assertIn("<code>$x$</code>", output)

    def test_invalid_math_blocks_generation_and_commands_cannot_inject(self):
        for source in (r"$\notARealCommand{x}$", r"$\href{file:///private}{x}$", r"$\htmlStyle{color:red}{x}$"):
            with self.assertRaises(ValueError):
                self.render(source)
        output = self.render("$x<y$\n\n<script>alert(1)</script>")
        self.assertNotIn("<script>", output)
        self.assertIn("&lt;", output)

    def test_english_spaces_survive_preview_and_export(self):
        source = "Read passage $A$, then ask: **high with respect to which texts?**"
        projected = create_markdown(renderer=LinkRewriter({}), plugins=[tex_plugin])(source)
        for body in (source, projected):
            output = self.render(body)
            self.assertIn('passage <span class="math-inline">', output)
            self.assertIn("ask: <strong>high", output)
            self.assertIn("</strong>", output)

    def test_summary_supports_emphasis_without_private_urls_or_html(self):
        from stemma_studio.blog.markdown import inline_markdown

        result = inline_markdown("*Italic* and **bold**, `code`, [private](file:///secret), <script>bad</script>")
        self.assertIn("<em>Italic</em>", result)
        self.assertIn("<strong>bold</strong>", result)
        self.assertIn("<code>code</code>", result)
        self.assertNotIn("file:", result)
        self.assertNotIn("<script>", result)


class AssetLinkResolutionTests(unittest.TestCase):
    """Real archives write the same file many ways; each must find its stored asset."""

    def document(self, archive_path):
        return {
            "source": {
                "relative_path": "2009/cat.md",
                "assets": [{"archive_path": archive_path, "snapshot": "data/assets/abc.png", "sha256": "0" * 64}],
            },
            "publication_pairs": {},
        }

    def resolves(self, body, archive_path):
        from stemma_studio.blog.attachments import referenced_attachments

        document = self.document(archive_path)
        return bool(referenced_attachments({"documents": {"d": document}}, document, body))

    def test_equivalent_spellings_of_one_path_all_resolve(self):
        for body, archive_path in (
            ("![](cat.png)", "2009/cat.png"),
            ("![](./cat.png)", "2009/cat.png"),
            ("![](images/cat.png)", "2009/images/cat.png"),
            ("![](./images/cat.png)", "2009/images/cat.png"),
            ("![](images/../images/cat.png)", "2009/images/cat.png"),
            ("![](../shared/cat.png)", "shared/cat.png"),
            ("![](my%20cat.png)", "2009/my cat.png"),
        ):
            self.assertTrue(self.resolves(body, archive_path), body)

    def test_remote_and_unknown_targets_are_not_attachments(self):
        for body in ("![](https://example.test/cat.png)", "![](//example.test/cat.png)", "![](other.png)"):
            self.assertFalse(self.resolves(body, "2009/cat.png"), body)
