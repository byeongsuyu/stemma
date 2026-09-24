"""Store pictures a writer attaches while drafting, beside the ones imports bring in.

A picture is written once under its own content hash, so the same picture used in
ten posts is stored once and a manuscript can never point at bytes that changed
underneath it. What goes into the manuscript is a readable name — ``images/cat-3f9a21b0.png``
— which ``blog.attachments`` maps back to the stored file. The hash in the name
is what makes it unique without anyone having to coordinate: the same picture
always gets the same name, two different pictures never collide, and a link
stays correct however the post is later revised.

Only the picture formats the published site actually renders are accepted, and
the bytes have to start the way that format says, so a mislabelled file is
refused here rather than becoming a broken image on someone's blog.
"""

import hashlib
import posixpath
import re
import unicodedata

from .domain import ModelError

# What blog.attachments will emit. Accepting more here would only store files
# that silently vanish at publication.
FORMATS = {
    "image/png": (".png", (b"\x89PNG\r\n\x1a\n",)),
    "image/jpeg": (".jpg", (b"\xff\xd8\xff",)),
    "image/gif": (".gif", (b"GIF87a", b"GIF89a")),
    "image/webp": (".webp", (b"RIFF",)),
    "application/pdf": (".pdf", (b"%PDF-",)),
    "text/plain": (".txt", ()),
}
EXTENSIONS = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".pdf": "application/pdf",
    ".txt": "text/plain",
}
# Pictures go in one folder and everything else in another, so a manuscript
# reads honestly: an image link belongs in images/, a document link in files/.
FOLDERS = ("images/", "files/")
MAX_BYTES = 8_000_000


def folder(media):
    return FOLDERS[0] if media.startswith("image/") else FOLDERS[1]


def clean_name(name):
    """A readable file name with no path in it, safe on any filesystem.

    Hangul and other letters are kept — the name is for the person writing.
    Only separators and characters that would change the meaning of a path go.
    """
    stem = posixpath.basename((name or "").replace("\\", "/")).strip()
    stem = unicodedata.normalize("NFC", stem)
    stem = posixpath.splitext(stem)[0]
    stem = re.sub(r"\s+", "-", stem)
    stem = "".join(c for c in stem if c.isalnum() or c in "-_.()[]")
    return re.sub(r"[-.]{2,}", "-", stem).strip("-._") or "image"


def inspect(name, content):
    """The media type this file really is, refusing anything the site cannot render."""
    if not content:
        raise ModelError("Empty file: " + (name or "?"))
    if len(content) > MAX_BYTES:
        raise ModelError("File is larger than 8MB: " + (name or "?"))
    extension = posixpath.splitext((name or "").lower())[1]
    media = EXTENSIONS.get(extension)
    if media is None:
        raise ModelError("Unsupported file type: " + (name or "?") + " (png, jpg, gif, webp, pdf, txt)")
    suffix, signatures = FORMATS[media]
    if signatures and not content.startswith(signatures):
        raise ModelError("File contents do not match its name: " + (name or "?"))
    if media == "image/webp" and content[8:12] != b"WEBP":
        raise ModelError("File contents do not match its name: " + (name or "?"))
    if media == "text/plain":
        # Plain text has no signature, so the only real check is that it is text.
        try:
            content.decode("utf-8")
        except UnicodeDecodeError as error:
            raise ModelError("Not UTF-8 text: " + (name or "?")) from error
    return media, suffix


def describe(name, content):
    """The record a document keeps for one attached picture. Pure; writes nothing."""
    media, suffix = inspect(name, content)
    digest = hashlib.sha256(content).hexdigest()
    return {
        "archive_path": folder(media) + clean_name(name) + "-" + digest[:8] + suffix,
        "snapshot": "data/assets/" + digest + suffix,
        "sha256": digest,
        "media_type": media,
    }


def store(repository, name, content):
    """Write the picture under its content hash, reusing identical bytes already there."""
    asset = describe(name, content)
    try:
        existing = repository.read_bytes(asset["snapshot"])
    except (FileNotFoundError, KeyError):
        repository.write_bytes_new(asset["snapshot"], content)
        return asset
    if existing != content:
        raise ModelError("A different picture is already stored at " + asset["snapshot"])
    return asset


def verify(repository, asset):
    """Check a record the browser sent back against the bytes actually stored.

    The browser is told what it attached and hands the record back on the next
    save; nothing about it is taken on trust. Every part of the record is
    derivable from the picture's own hash, so it can be rebuilt and compared.
    """
    if not isinstance(asset, dict) or not isinstance(asset.get("sha256"), str):
        raise ModelError("Malformed attachment record")
    digest = asset["sha256"]
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ModelError("Malformed attachment hash")
    path = asset.get("archive_path") or ""
    suffix = posixpath.splitext(path)[1].lower()
    media = EXTENSIONS.get(suffix)
    if media is None or asset.get("media_type") != media:
        raise ModelError("Unsupported attachment type: " + path)
    prefix = folder(media)
    if not path.startswith(prefix) or "/" in path[len(prefix) :] or not path.endswith("-" + digest[:8] + suffix):
        raise ModelError("Attachment name does not match its file: " + path)
    if asset.get("snapshot") != "data/assets/" + digest + FORMATS[media][0]:
        raise ModelError("Attachment is not stored under its own hash: " + path)
    try:
        content = repository.read_bytes(asset["snapshot"])
    except (FileNotFoundError, KeyError) as error:
        raise ModelError("Attachment was never stored: " + path) from error
    if hashlib.sha256(content).hexdigest() != digest:
        raise ModelError("Stored attachment does not match its hash: " + path)


def merge(existing, added):
    """Combine attachment lists, keeping one record per stored picture.

    Attachments accumulate rather than being replaced: removing a link from the
    body does not delete what was attached, and the published page only carries
    the pictures the text actually refers to.
    """
    result = {asset["archive_path"]: asset for asset in existing}
    for asset in added:
        kept = result.get(asset["archive_path"])
        if kept is not None and kept["sha256"] != asset["sha256"]:
            raise ModelError("Two different pictures claim " + asset["archive_path"])
        result[asset["archive_path"]] = asset
    return [result[key] for key in sorted(result)]
