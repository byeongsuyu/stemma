"""Shared footnote parsing for previews, export rewriting, and attachments."""

from .vendor.mistune.core import BlockState
from .vendor.mistune.plugins.footnotes import (
    INLINE_FOOTNOTE,
    REF_FOOTNOTE,
    parse_footnote_item,
    parse_inline_footnote,
    parse_ref_footnote,
    render_footnotes,
)


def append_notes(md, result, state):
    notes = state.env.get("footnotes", [])
    if not notes:
        return result
    # Keep reference links available inside notes, but disallow recursive notes.
    child = BlockState()
    child.env = dict(state.env, ref_footnotes={})
    child.tokens = [
        {
            "type": "footnotes",
            "children": [parse_footnote_item(md.block, key, index + 1, state) for index, key in enumerate(notes)],
        }
    ]
    return result + md.render_state(child)


def render_ref(renderer, key, index):
    counts = getattr(renderer, "note_counts", {})
    counts[index] = counts.get(index, 0) + 1
    renderer.note_counts = counts
    suffix = "" if counts[index] == 1 else "-" + str(counts[index])
    return f'<sup class="footnote-ref" id="fnref-{index}{suffix}"><a href="#fn-{index}" role="doc-noteref">{index}</a></sup>'


def render_item(renderer, text, key, index):
    backs = []
    for occurrence in range(1, renderer.note_counts.get(index, 1) + 1):
        suffix = "" if occurrence == 1 else "-" + str(occurrence)
        backs.append(
            f'<a href="#fnref-{index}{suffix}" class="footnote-back" aria-label="Back to reference {occurrence} / 본문으로">↩</a>'
        )
    return '<li id="fn-{}">{} {}</li>\n'.format(index, text, " ".join(backs))


def footnotes(md):
    md.inline.register("footnote", INLINE_FOOTNOTE, parse_inline_footnote, before="link")
    # Accept the customary four-space continuation as well as legacy indentation.
    md.block.register("ref_footnote", REF_FOOTNOTE.replace("{1,3}", "{1,4}"), parse_ref_footnote, before="ref_link")
    md.after_render_hooks.append(append_notes)
    if md.renderer and md.renderer.NAME == "html":
        md.renderer.register("footnote_ref", render_ref)
        md.renderer.register("footnotes", render_footnotes)
        md.renderer.register("footnote_item", render_item)
