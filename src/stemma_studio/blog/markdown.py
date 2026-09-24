"""Render a deliberately closed Markdown vocabulary with explicit URL policy."""

import posixpath
import re
import uuid
from html import escape, unescape
from urllib.parse import unquote, urlsplit

from .footnotes import footnotes
from .math_support import render_formulas, tex_plugin
from .vendor.mistune import HTMLRenderer, create_markdown
from .vendor.mistune.plugins.table import table


class SafeRenderer(HTMLRenderer):
    def __init__(self, resolve, assets):
        super().__init__(escape=True)
        self.resolve = resolve
        self.assets = assets
        self.formulas = []
        self.marker = uuid.uuid4().hex

    def inline_math(self, text):
        return self.math(text, False)

    def block_math(self, text):
        return self.math(text, True)

    def math(self, text, display):
        token = "MATH" + self.marker + str(len(self.formulas)) + "END"
        self.formulas.append({"text": text, "display": display})
        return (
            '<span class="math-display" tabindex="0">' + token + "</span>"
            if display
            else '<span class="math-inline">' + token + "</span>"
        )

    def table(self, text):
        return (
            '<div class="table-scroll" role="region" aria-label="Table / 표" tabindex="0"><table>'
            + text
            + "</table></div>\n"
        )

    def table_cell(self, text, align=None, head=False):
        tag = "th" if head else "td"
        return (
            "<"
            + tag
            + (' scope="col"' if head else "")
            + ' class="align-'
            + (align or "left")
            + '">'
            + text
            + "</"
            + tag
            + ">\n"
        )

    def link(self, text, url, title=None):
        # Titles and rejected destinations never survive as hidden metadata.
        href = self.resolve(url)
        return f'<a href="{escape(href, quote=True)}" rel="noreferrer">{text}</a>' if href else text

    def image(self, text, url, title=None):
        # The parser percent-encodes a non-ASCII target, so a picture named in
        # Hangul has to be looked up decoded too — the way resolve() reads links.
        decoded = unquote(url)
        target = self.assets.get(url) or self.assets.get(decoded) or self.assets.get(posixpath.normpath(decoded))
        if target and target.endswith((".png", ".jpg", ".gif", ".webp")):
            return '<img src="{}" alt="{}" loading="lazy">'.format(
                escape(target, quote=True), escape(re.sub("<[^>]*>", "", text), quote=True)
            )
        href = external_url(url)
        return self.link(text or "Image", href, None) if href else text

    def block_html(self, html):
        return "<p>[HTML omitted]</p>\n"

    def inline_html(self, html):
        return ""

    def block_code(self, code, info=None):
        if info and info.strip() in ("math", "latex", "tex"):
            return self.block_math(code)
        # Do not emit arbitrary fence labels as CSS or metadata.
        return "<pre><code>" + escape(code) + "</code></pre>\n"


def external_url(value):
    value = unescape(value)
    decoded = unquote(value)
    if any(ord(c) < 33 for c in decoded) or "\\" in decoded:
        return None
    parts = urlsplit(value)
    if parts.scheme in ("https", "http") and parts.hostname and not parts.username and not parts.password:
        return value
    if parts.scheme == "mailto" and parts.path and not parts.query:
        return value
    return None


def markdown(body, resolve, assets=None):
    renderer = SafeRenderer(resolve, assets or {})
    output = create_markdown(renderer=renderer, plugins=[table, tex_plugin, footnotes])(body)
    for index, formula in enumerate(render_formulas(renderer.formulas)):
        output = output.replace("MATH" + renderer.marker + str(index) + "END", formula)
    return output


def inline_markdown(text):
    """Render summaries with emphasis/code only; destinations never leave this boundary."""
    parser = create_markdown(renderer=SafeRenderer(lambda url: None, {}))
    tokens = parser.inline(text or "", {})
    return parser.renderer(tokens, None)
