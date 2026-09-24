"""Read only explicitly selected attachment bytes under opaque public names."""

import hashlib
import posixpath

from .blog import require

EXTENSIONS = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/gif": "gif",
    "image/webp": "webp",
    "application/pdf": "pdf",
    "text/plain": "txt",
}


def asset_url(asset):
    return "assets/{}.{}".format(asset["id"], EXTENSIONS[asset["media_type"]])


def link_names(document, snapshot):
    """Every way this document's text can name one stored attachment.

    A published body is never rewritten, so it still refers to a picture by the
    path it had where it was written — ``images/cat.png``, ``../../assets/cat.png``.
    The renderer serves that picture under an opaque public name instead, and
    cannot connect the two unless it is told; this is what tells it.
    """
    names = {snapshot}
    source = document.get("source") or {}
    for asset in source.get("assets", []):
        archive = asset.get("archive_path")
        if asset["snapshot"] != snapshot or not archive:
            continue
        names.add(archive)
        if source.get("relative_path"):
            names.add(posixpath.relpath(archive, posixpath.dirname(source["relative_path"])))
    return sorted(posixpath.normpath(name) for name in names)


def selected_assets(state, read_bytes):
    assets, descriptors = {}, {}
    for doc in state["documents"].values():
        pair_id = doc["publication"]["selected_pair"]
        if pair_id is None:
            continue
        for asset in doc["publication_pairs"][pair_id]["attachments"]:
            previous = descriptors.get(asset["id"])
            require(previous is None or previous == asset, "Conflicting public attachment ID")
            if previous is not None:
                continue
            descriptors[asset["id"]] = asset
            content = read_bytes(asset["path"])
            require(hashlib.sha256(content).hexdigest() == asset["sha256"], "Publication attachment changed")
            assets[asset_url(asset)] = content
    return assets
