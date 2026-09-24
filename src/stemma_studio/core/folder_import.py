"""Import an existing folder of Markdown and its pictures, without Git.

``sync_archive`` expects a Git repository in one particular layout. Most
people's writing is just a folder: Markdown files with their pictures beside
them or in a subfolder. This reads such a folder directly, so nobody has to
reshape their archive before they can use it.

Nothing in the folder is written to or moved. Image links are never rewritten
either: an asset is recorded at the path it occupies relative to the document
that references it, which is exactly how ``blog.attachments`` resolves it back.
Preserving the folder's shape is what makes ``![](images/cat.png)`` keep
working, so the shape is the contract.

Finding links needs a Markdown parser, which lives in the blog package, and the
core may not import it. Callers inject one; the regex fallback here is enough
for a plain scan.
"""

import hashlib
import mimetypes
import posixpath
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import unquote

from .archive_sync import scalar
from .blog import document_fields
from .containment import contained
from .domain import ModelError

MEDIA_TYPES = ("image/png", "image/jpeg", "image/gif", "image/webp", "application/pdf", "text/plain")
REMOTE = ("http://", "https://", "//", "data:", "mailto:", "#")
# Markdown inline and reference links, enough to find picture targets without a parser.
LINK = re.compile(r"!?\[[^\]]*\]\(\s*<?([^)\s>]+)>?[^)]*\)|^\s*\[[^\]]+\]:\s*<?(\S+)>?", re.M)
FRONT = re.compile(r"\A---\r?\n(.*?)\r?\n---(?:\r?\n|\Z)", re.S)
SCALAR_FIELDS = ("id", "date", "title")


@dataclass
class ImportPlan:
    state: dict
    writes: dict
    report: dict
    rows: list = field(default_factory=list)


def slugify(value):
    """An ASCII identifier, or '' when the text carries none."""
    text = unicodedata.normalize("NFKD", value)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"-+", "-", re.sub(r"[^A-Za-z0-9_-]+", "-", text)).strip("-_").lower()


def derive_id(relative_path, rule):
    """A stable identifier for a file, the same on every re-scan of the same folder.

    Hangul and other non-ASCII names carry no identifier, so they fall back to a
    digest of the path rather than being transliterated into something lossy.
    """
    stem = posixpath.splitext(relative_path)[0]
    slug = slugify(stem.replace("/", "-") if rule == "path" else posixpath.basename(stem))
    return slug or "doc-" + hashlib.sha256(relative_path.encode("utf-8")).hexdigest()[:10]


def read_front_matter(text):
    """Split optional frontmatter from the body; a file without any is still valid.

    Values are decoded by the same rule the Git route uses, so that both routes
    read one archive the same way: ``null``, ``~`` and an empty value all mean
    absent, rather than becoming the four-letter title "null". Anything that
    rule cannot decode is kept as written instead of failing the whole import.
    """
    match = FRONT.match(text)
    if not match:
        return {}, text.strip() + "\n"
    metadata = {}
    for key in SCALAR_FIELDS:
        found = re.search(r"^" + key + r":([^\n]*)$", match.group(1), re.M)
        if found:
            try:
                metadata[key] = scalar(found.group(1))
            except ModelError:
                metadata[key] = found.group(1).strip() or None
    return metadata, text[match.end() :].strip() + "\n"


def find_links_basic(text):
    return [m.group(1) or m.group(2) for m in LINK.finditer(text)]


def display_title(metadata, body, relative_path):
    """The frontmatter title, else the first heading, else a label naming the post.

    Untitled posts are the normal case in an exported archive, so the last
    resort is the label the Git route builds — the date and the opening words —
    rather than a filename nobody wrote. Both routes then name one post alike.
    """
    if metadata.get("title"):
        return metadata["title"], "file"
    for line in body.splitlines():
        if line.startswith("#"):
            heading = line.lstrip("#").strip()
            if heading:
                return heading, "heading"
    opening = (body.splitlines() or [posixpath.basename(relative_path)])[0][:70]
    if opening.strip():
        return (metadata.get("date") or "undated") + " \u00b7 " + opening, "label"
    return posixpath.splitext(posixpath.basename(relative_path))[0], "filename"


def local_targets(links):
    """Link targets that could name a file in this folder.

    A Markdown parser percent-encodes non-ASCII targets, so a picture named in
    Hangul arrives as %EA%B7%B8..., which names no file on disk. The reader's
    site decodes before it resolves (``blog.attachments``); so must this, or
    every picture whose name is not ASCII is reported missing. Decoding first
    also means the checks below see the path the link really means.
    """
    for url in links:
        cleaned = unquote(url.split("#")[0].split("?")[0].strip())
        if cleaned and not cleaned.startswith(REMOTE) and not cleaned.startswith("/"):
            yield cleaned


def resolve_target(relative, target):
    """Where a link written in `relative` points, as a path relative to the folder root."""
    return posixpath.normpath(posixpath.join(posixpath.dirname(relative), target))


def resolve_links(root, relative, links):
    """The pictures a document's links name inside the folder, and the ones they do not.

    A first import and a later re-scan ask exactly the same question of the same folder,
    so they ask it here rather than each in their own way. Returns the attachments in the
    order the document links them, the bytes to store for each, and the targets that name
    nothing here — kept apart as missing and as outside the chosen folder, because those
    are different mistakes with different fixes.
    """
    assets, contents, missing, outside = [], {}, [], []
    for target in local_targets(links):
        resolved = resolve_target(relative, target)
        if resolved.startswith(".."):
            # The picture may well exist, just above the folder that was chosen.
            # Saying so is the difference between a puzzle and one obvious fix.
            outside.append(target)
            continue
        candidate = contained(root, resolved)
        if candidate is None:
            # A symlinked component leads out of the chosen folder just as surely as
            # `..` does. A link in somebody's writing must not widen what may be read.
            outside.append(target)
            continue
        media = mimetypes.guess_type(resolved)[0]
        if not candidate.is_file() or media not in MEDIA_TYPES:
            missing.append(target)
            continue
        content = candidate.read_bytes()
        digest = hashlib.sha256(content).hexdigest()
        snapshot = "data/assets/" + digest + posixpath.splitext(resolved)[1].lower()
        assets.append({"archive_path": resolved, "snapshot": snapshot, "sha256": digest})
        contents[snapshot] = content
    return assets, contents, missing, outside


def scan(state, folder, rule="path", find_links=None):
    """Plan an append-only import of a folder, without writing anything."""
    find_links = find_links or find_links_basic
    root = Path(folder).expanduser()
    if not root.is_absolute() or root.is_symlink():
        raise ModelError("An absolute folder is required")
    root = root.resolve()
    if not root.is_dir():
        raise ModelError("Not a folder: " + str(root))
    documents = sorted(
        p
        for p in root.rglob("*.md")
        if p.is_file() and ".git" not in p.parts and contained(root, p.relative_to(root).as_posix()) is not None
    )
    if not documents:
        raise ModelError("No Markdown files found in " + str(root))

    report = {
        "folder": str(root),
        "rule": rule,
        "new": [],
        "unchanged": [],
        "skipped": [],
        "warnings": [],
        "remote_links": 0,
        "orphan_assets": [],
        "recovered": [],
    }
    seen, used_assets, writes, additions, repairs, restored = {}, set(), {}, {}, {}, set()
    for path in documents:
        relative = path.relative_to(root).as_posix()
        try:
            raw = path.read_bytes()
            text = raw.decode("utf-8")
        except (OSError, UnicodeDecodeError):
            report["skipped"].append({"path": relative, "reason": "unreadable"})
            continue
        metadata, body = read_front_matter(text)
        if not body.strip():
            report["skipped"].append({"path": relative, "reason": "empty"})
            continue
        given = metadata.get("id")
        docid = given if given and re.fullmatch(r"[A-Za-z0-9_-]+", given) else derive_id(relative, rule)
        if docid in seen:
            report["skipped"].append({"path": relative, "id": docid, "reason": "duplicate_id", "detail": seen[docid]})
            continue
        seen[docid] = relative

        fingerprint = hashlib.sha256(raw).hexdigest()
        existing = state["documents"].get(docid)
        if existing is not None:
            source = existing.get("source") or {}
            if source.get("sha256") != fingerprint:
                report["skipped"].append({"path": relative, "id": docid, "reason": "content_changed"})
                continue
            report["unchanged"].append({"id": docid, "path": relative})
            # The writing has not moved, but the pictures beside it may have. One that was
            # missing when this document arrived can be attached now without touching a
            # byte of the writing, and one that is already attached must stop being counted
            # as a picture no document uses. Only a document this same folder produced is
            # repaired: an attachment is recorded relative to the document's own path, so
            # the two have to have come from one place to mean anything together.
            if source.get("origin") != "folder" or source.get("relative_path") != relative:
                continue
            assets, contents, _, _ = resolve_links(root, relative, find_links(body))
            used_assets.update(a["archive_path"] for a in assets)
            attached = {a["archive_path"] for a in source.get("assets") or []}
            found = [a for a in assets if a["archive_path"] not in attached]
            if found:
                recovered = {a["archive_path"] for a in found}
                restored.update(a["snapshot"] for a in found)
                writes.update({a["snapshot"]: contents[a["snapshot"]] for a in found})
                repairs[docid] = {
                    **existing,
                    "source": {
                        **source,
                        "assets": [*(source.get("assets") or []), *found],
                        "missing_assets": [
                            target
                            for target in source.get("missing_assets") or []
                            if resolve_target(relative, target) not in recovered
                        ],
                    },
                }
                report["recovered"].append({"id": docid, "path": relative, "images": len(found)})
            continue

        links = find_links(body)
        report["remote_links"] += sum(1 for url in links if url.startswith(REMOTE))
        assets, contents, missing, outside = resolve_links(root, relative, links)
        writes.update(contents)
        used_assets.update(a["archive_path"] for a in assets)
        for target in outside:
            report["warnings"].append({"path": relative, "reason": "image_outside_folder", "detail": target})
        for target in missing:
            report["warnings"].append({"path": relative, "reason": "image_not_found", "detail": target})
        unresolved = sorted(set(missing) | set(outside))

        title, origin = display_title(metadata, body, relative)
        snapshot = "data/imports/" + docid + ".md"
        body_path = "data/revisions/" + docid + "/r1.md"
        writes[snapshot] = raw
        writes[body_path] = body.encode("utf-8")
        additions[docid] = {
            "title": title,
            "kind": "imported",
            "state": "confirmed",
            "archived": False,
            "questions": [],
            "source": {
                # Folder imports are not archive checkpoints; sync_archive must ignore them.
                "origin": "folder",
                "archive_id": docid,
                "relative_path": relative,
                "date": metadata.get("date"),
                "snapshot": snapshot,
                "sha256": fingerprint,
                "title_origin": "archive" if origin == "file" else "generated_display_label",
                "assets": assets,
                "missing_assets": unresolved,
            },
            "current_revision": "r1",
            **document_fields(),
            "revisions": [
                {
                    "id": "r1",
                    "path": body_path,
                    "sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
                    "note": "Imported from a folder of Markdown.",
                }
            ],
        }
        report["new"].append(
            {
                "id": docid,
                "path": relative,
                "title": title,
                "title_from": origin,
                "date": metadata.get("date"),
                "images": len(assets),
                "missing": unresolved,
            }
        )

    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.is_symlink() or ".git" in path.parts:
            continue
        relative = path.relative_to(root).as_posix()
        if relative.endswith(".md") or relative in used_assets:
            continue
        # Only pictures are worth reporting as unused; stray text files are not assets.
        media = mimetypes.guess_type(relative)[0] or ""
        if media.startswith("image/"):
            report["orphan_assets"].append(relative)

    result = {**state, "documents": {**state["documents"], **repairs, **additions}}
    report["counts"] = {
        "new": len(report["new"]),
        "unchanged": len(report["unchanged"]),
        "skipped": len(report["skipped"]),
        "warnings": len(report["warnings"]),
        # Pictures this import would store: the new posts' and the ones it puts back.
        "images": len({a["snapshot"] for d in additions.values() for a in d["source"]["assets"]} | restored),
        "orphan_assets": len(report["orphan_assets"]),
        "recovered": len(report["recovered"]),
    }
    return ImportPlan(result, writes, report)


def apply_import(repository, plan):
    """Write the planned snapshots and save, reusing any identical existing bytes."""
    if not plan.report["counts"]["new"] and not plan.report["counts"]["recovered"]:
        return plan.state, {**plan.report, "status": "nothing_to_import"}
    absent = {}
    for path, content in plan.writes.items():
        try:
            saved = repository.read_bytes(path)
        except (FileNotFoundError, KeyError):
            absent[path] = content
            continue
        if saved != content:
            raise ModelError("Snapshot destination differs: " + path)
    for path, content in absent.items():
        repository.write_bytes_new(path, content)
    repository.save(plan.state)
    return plan.state, {**plan.report, "status": "imported"}
