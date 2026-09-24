"""Resolve preserved attachments referenced by one revision without filesystem lookup."""

import mimetypes
import posixpath
from urllib.parse import unquote

from .footnotes import footnotes
from .vendor.mistune import create_markdown


def normalise(url):
    """Compare link targets by the path they mean, not by how they were typed.

    Real archives write ./image.png and a/../a/image.png for what is one file.
    """
    if not url or url.startswith(("http://", "https://", "//", "data:", "mailto:")):
        return url
    return posixpath.normpath(url)


def asset_aliases(state, document):
    aliases = {}
    source = document.get("source") or {}
    for doc in state["documents"].values():
        for asset in (doc.get("source") or {}).get("assets", []):
            aliases[normalise(asset["snapshot"])] = asset
    for asset in source.get("assets", []):
        archive = asset.get("archive_path")
        if not archive:
            continue
        aliases[normalise(archive)] = asset
        if source.get("relative_path"):
            aliases[normalise(posixpath.relpath(archive, posixpath.dirname(source["relative_path"])))] = asset
    for pair in document.get("publication_pairs", {}).values():
        for asset in pair["attachments"]:
            aliases.setdefault(normalise(asset["path"]), dict(asset, snapshot=asset["path"]))
    return aliases


def referenced_attachments(state, document, body):
    aliases = asset_aliases(state, document)
    result = {}

    def visit(tokens):
        for token in tokens:
            if token["type"] in ("image", "link"):
                url = normalise(unquote(token["attrs"]["url"]))
                asset = aliases.get(url)
                if asset is not None:
                    path = asset["snapshot"]
                    mime = mimetypes.guess_type(path)[0]
                    if mime in ("image/png", "image/jpeg", "image/gif", "image/webp", "application/pdf", "text/plain"):
                        result[path] = {"path": path, "sha256": asset["sha256"], "media_type": mime}
            visit(token.get("children", []))

    visit(create_markdown(renderer="ast", plugins=[footnotes])(body))
    return list(result.values())
