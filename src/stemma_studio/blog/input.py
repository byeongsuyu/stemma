"""Local adapter: resolve corpus destinations before the public renderer boundary."""

from copy import deepcopy
from urllib.parse import unquote

from .attachments import asset_aliases
from .footnotes import footnotes
from .markdown import external_url
from .math_support import tex_plugin
from .vendor.mistune import create_markdown
from .vendor.mistune.plugins.table import table
from .vendor.mistune.renderers.markdown import MarkdownRenderer

# CommonMark lets a backslash escape any ASCII punctuation, and whether this text stays
# literal is decided entirely by the parse that follows. Four marks are deliberately left
# alone, because escaping them would create the very syntax they are meant to suppress:
#
# `(` `)` `]`  `\(...\)` is inline mathematics here and `\[...\]` is display mathematics,
#              so escaping these would turn ordinary parentheses and brackets into
#              formulas. Escaping `[` alone is enough: no link or image can start without
#              one, which is what these marks needed protecting from.
# `|`          a table cell escapes its own separators after its children are rendered,
#              so escaping here as well would leave a literal backslash and split the row.
ESCAPABLE = frozenset("!\"#$%&'*+,-./:;<=>?@[\\^_`{}~")


class LinkRewriter(MarkdownRenderer):
    def __init__(self, aliases):
        super().__init__()
        self.aliases = aliases

    def footnote_ref(self, token, state):
        return "[^{}]".format(token["attrs"]["index"])

    def footnotes(self, token, state):
        return "\n" + self.render_children(token, state)

    def footnote_item(self, token, state):
        body = self.render_children(token, state).strip().replace("\n", "\n    ")
        return "[^{}]: {}\n\n".format(token["attrs"]["index"], body)

    def text(self, token, state):
        """Re-escape literal text so the second parse reads it as the first one did.

        The first parse consumed the author's escapes, and mistune's Markdown renderer
        emits `raw` unchanged, so `\\*literal\\*` came back as emphasis and `\\<b>` as a tag.
        Escaping every punctuation mark is verbose, but this text is an intermediate
        nobody reads: it is compared for equality and then rendered.
        """
        return "".join("\\" + c if c in ESCAPABLE else c for c in token["raw"])

    def inline_math(self, token, state):
        return r"\(" + token["raw"] + r"\)"

    def block_math(self, token, state):
        return "\n$$\n" + token["raw"] + "\n$$\n\n"

    def table(self, token, state):
        return self.render_children(token, state) + "\n"

    def table_head(self, token, state):
        cells = token["children"]
        row = "| " + " | ".join(self.render_children(c, state).replace("|", r"\|") for c in cells) + " |\n"
        return (
            row
            + "| "
            + " | ".join(
                {"left": ":---", "right": "---:", "center": ":---:"}.get(c["attrs"]["align"], "---") for c in cells
            )
            + " |\n"
        )

    def table_body(self, token, state):
        return self.render_children(token, state)

    def table_row(self, token, state):
        return "| " + " | ".join(self.render_children(c, state).replace("|", r"\|") for c in token["children"]) + " |\n"

    def render_referrences(self, state):
        # Reference definitions can contain private destinations even when unused.
        return iter(())

    def link(self, token, state):
        value = unquote(token["attrs"]["url"])
        destination = self.aliases.get(value) or external_url(value)
        if destination is None:
            return self.render_children(token, state)
        token = deepcopy(token)
        token.pop("label", None)
        token["attrs"] = {"url": destination}
        return super().link(token, state)

    def image(self, token, state):
        value = unquote(token["attrs"]["url"])
        if value not in self.aliases:
            return self.link(token, state)
        return "!" + self.link(token, state)


def prepare_input(studio, state, planned_at):
    """Read an approved bundle; private link aliases remain local to this adapter.

    Exact selected revision paths and document links resolve to public slugs.
    Unknown paths and older/newer revision links become plain author-written text.
    This does not alter the immutable source or approve any new body/attachment.
    """
    from stemma_studio.core.public_assets import asset_url

    bundle = studio.export_bundle(state, planned_at)
    aliases = {}
    for did, doc in state["documents"].items():
        selected = doc["publication"]["selected_pair"]
        if selected is None:
            continue
        pair = doc["publication_pairs"][selected]
        public_slug = state["blog"]["identities"]["documents"][did]["slug"]
        destination = "post:" + public_slug
        for name in (did, "studio:" + did, "document:" + did, "post:" + public_slug):
            aliases[name] = destination
        revision = next(r for r in doc["revisions"] if r["id"] == pair["base_revision"])
        aliases[revision["path"]] = destination
    for did, doc in state["documents"].items():
        selected = doc["publication"]["selected_pair"]
        if selected is None:
            continue
        local_aliases = dict(aliases)
        for asset in doc["publication_pairs"][selected]["attachments"]:
            local_aliases[asset["path"]] = asset_url(asset)
            local_aliases[asset_url(asset)] = asset_url(asset)
        approved = {a["path"]: asset_url(a) for a in doc["publication_pairs"][selected]["attachments"]}
        for alias, asset in asset_aliases(state, doc).items():
            if asset["snapshot"] in approved:
                local_aliases[alias] = approved[asset["snapshot"]]
        pid = state["blog"]["identities"]["documents"][did]["id"]
        output = next(d for d in bundle["public"]["documents"] if d["id"] == pid)
        parser = create_markdown(renderer=LinkRewriter(local_aliases), plugins=[table, tex_plugin, footnotes])
        for value in output["translations"].values():
            value["body"] = parser(value["body"])
    return bundle
