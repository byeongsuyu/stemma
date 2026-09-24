"""Append-only import from an immutable local Git commit, never from the worktree.

Planning reads committed blobs and compares stable IDs and hashes. Applying writes
new snapshots before saving one metadata checkpoint. Existing text is never replaced.
This adapter is independent of graph algorithms, editors, and publication rendering.
"""

import copy
import hashlib
import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .blog import document_fields
from .domain import ModelError, validate


def sha(content):
    return hashlib.sha256(content).hexdigest()


def git(archive, *args, input=None):
    """Use argument arrays and pinned object IDs; do not invoke a shell or change Git."""
    result = subprocess.run(["git", "-C", str(archive), *args], input=input, capture_output=True)
    if result.returncode:
        raise ModelError("Archive Git read failed: " + result.stderr.decode("utf-8", "replace").strip())
    return result.stdout


def scalar(value):
    """Decode the simple scalar subset emitted by the archive converters."""
    value = value.strip()
    if value in ("null", "~", ""):
        return None
    if value.startswith('"'):
        try:
            # Some archived titles contain literal control characters; preserve them.
            return json.loads(value, strict=False)
        except ValueError as error:
            raise ModelError("Unsupported quoted archive scalar: " + str(error)) from error
    if value.startswith("'") and value.endswith("'"):
        return value[1:-1].replace("''", "'")
    if value in ("|", ">"):
        raise ModelError("Multiline metadata scalar needs an explicit parser extension")
    return value


def parse_document(raw):
    """Preserve all source bytes while extracting known scalar fields and asset paths.

    This is deliberately not a general YAML loader. Unparsed metadata remains in
    the complete snapshot. No input text is evaluated as code or instructions.
    """
    text = raw.decode("utf-8")
    match = re.match(r"\A---\r?\n(.*?)\r?\n---(?:\r?\n|\Z)", text, re.S)
    if not match:
        raise ModelError("Missing archive frontmatter boundaries")
    front = match.group(1)
    metadata = {}
    for key in (
        "id",
        "date",
        "title",
        "source",
        "kind",
        "status",
        "visibility",
        "original_author",
        "original_url",
        "duplicate_of",
    ):
        field = re.search(r"^" + key + r":([^\n]*)$", front, re.M)
        metadata[key] = scalar(field.group(1)) if field else None
    if not isinstance(metadata["id"], str) or not re.fullmatch(r"[A-Za-z0-9_-]+", metadata["id"]):
        raise ModelError("Missing or unsafe archive ID")
    block = re.search(r"^assets:\s*\n((?:[ \t]+[^\n]*(?:\n|$))*)", front, re.M)
    assets = []
    if block:
        for item in re.finditer(r"^\s*-\s*path:\s*(.+)$", block.group(1), re.M):
            path = scalar(item.group(1))
            if not isinstance(path, str) or not path.startswith("assets/") or ".." in PurePosixPath(path).parts:
                raise ModelError("Unsafe asset reference")
            assets.append(path)
    return metadata, text[match.end() :].strip() + "\n", assets


def committed_files(archive, commit):
    """List only committed corpus documents and assets; reject symbolic links."""
    entries = {}
    for entry in git(archive, "ls-tree", "-r", "-z", commit, "--", "corpus", "assets").split(b"\0"):
        if not entry:
            continue
        info, path = entry.split(b"\t", 1)
        mode, kind, oid = info.decode("ascii").split()
        name = path.decode("utf-8")
        if not (name.startswith("assets/") or name.endswith(".md")):
            continue
        if mode not in ("100644", "100755") or kind != "blob":
            raise ModelError("Unsupported committed entry: " + name)
        entries[name] = oid
    return entries


def read_blobs(archive, ids):
    """Fetch selected Git blobs in one subprocess, including arbitrary binary assets."""
    ids = tuple(sorted(set(ids)))
    if not ids:
        return {}
    raw = git(archive, "cat-file", "--batch", input=("\n".join(ids) + "\n").encode("ascii"))
    result, offset = {}, 0
    for oid in ids:
        end = raw.index(b"\n", offset)
        header = raw[offset:end].decode("ascii").split()
        if len(header) != 3 or header[0] != oid or header[1] != "blob":
            raise ModelError("Unexpected Git object response")
        size = int(header[2])
        offset = end + 1
        result[oid] = raw[offset : offset + size]
        offset += size + 1
    return result


@dataclass
class SyncPlan:
    state: dict
    writes: dict
    report: dict


def plan_sync(state, archive=None):
    """Plan an append-only checkpoint. Any mutation/deletion conflict blocks the batch.

    Resolving HEAD once ensures that corpus and assets come from the same commit,
    even if another process commits during this operation.
    """
    validate(state)
    previous = state.get("archive")
    location = str(Path(archive or (previous or {}).get("path", "")).resolve())
    if archive is None and not previous:
        raise ModelError("Configure an archive path first")
    if previous and str(Path(previous["path"]).resolve()) != location:
        raise ModelError("Changing the archive binding requires explicit reconciliation")
    commit = git(location, "rev-parse", "--verify", "HEAD^{commit}").decode().strip()
    report = {
        "commit": commit,
        "added": [],
        "unchanged": 0,
        "moved": [],
        "conflicts": [],
        "warnings": [],
        "assets_added": 0,
    }
    if previous and previous["commit"] == commit:
        report.update(status="up_to_date", unchanged=len(previous["manifest"]))
        return SyncPlan(copy.deepcopy(state), {}, report)
    entries = committed_files(location, commit)
    documents = {p: oid for p, oid in entries.items() if p.startswith("corpus/") and p.endswith(".md")}
    raw_documents = read_blobs(location, documents.values())
    parsed, referenced_assets = {}, set()
    for path, oid in sorted(documents.items()):
        try:
            metadata, body, assets = parse_document(raw_documents[oid])
        except (ModelError, UnicodeError) as error:
            report["conflicts"].append({"path": path, "reason": str(error)})
            continue
        docid = metadata["id"]
        if docid in parsed:
            report["conflicts"].append({"id": docid, "reason": "duplicate_id", "path": path})
            continue
        parsed[docid] = (path, oid, metadata, body, assets)
        referenced_assets.update(assets)
    missing_assets = referenced_assets - set(entries)
    for path in sorted(missing_assets):
        report["warnings"].append({"path": path, "reason": "asset_not_committed"})
    asset_bytes = read_blobs(location, [entries[p] for p in referenced_assets if p in entries])
    result = copy.deepcopy(state)
    writes, manifest = {}, {}
    for docid, (path, oid, metadata, body, assets) in parsed.items():
        raw = raw_documents[oid]
        fingerprint = sha(raw)
        manifest[docid] = {"path": path, "blob": oid, "sha256": fingerprint}
        existing = result["documents"].get(docid)
        if existing:
            source = existing.get("source")
            if not source or source["sha256"] != fingerprint:
                report["conflicts"].append({"id": docid, "path": path, "reason": "existing_content_changed"})
                continue
            report["unchanged"] += 1
            if source["relative_path"] != path:
                report["moved"].append(docid)
        else:
            source = {
                "archive_id": docid,
                "relative_path": path,
                "date": metadata["date"],
                "commit": commit,
                "snapshot": "data/imports/" + docid + ".md",
                "sha256": fingerprint,
                "title_origin": "archive" if metadata["title"] else "generated_display_label",
            }
            body_path = "data/revisions/" + docid + "/r1.md"
            existing = {
                "title": metadata["title"]
                or ((metadata["date"] or "undated") + " · " + (body.splitlines() or [docid])[0][:70]),
                "kind": "imported",
                "state": "confirmed",
                "archived": False,
                "questions": [],
                "source": source,
                "current_revision": "r1",
                **document_fields(),
                "revisions": [
                    {
                        "id": "r1",
                        "path": body_path,
                        "sha256": sha(body.encode("utf-8")),
                        "note": "Imported from a committed archive snapshot.",
                    }
                ],
            }
            result["documents"][docid] = existing
            writes[source["snapshot"]] = raw
            writes[body_path] = body.encode("utf-8")
            report["added"].append(docid)
        old_assets = {a["archive_path"]: a for a in source.get("assets", [])}
        source_assets = []
        for asset_path in assets:
            if asset_path not in entries:
                # An original source gap is visible but does not discard the text.
                # Losing an asset already imported violates append-only integrity.
                if asset_path in old_assets:
                    report["conflicts"].append({"path": asset_path, "reason": "existing_asset_missing"})
                continue
            content = asset_bytes[entries[asset_path]]
            asset_sha = sha(content)
            if asset_path in old_assets and old_assets[asset_path]["sha256"] != asset_sha:
                report["conflicts"].append({"path": asset_path, "reason": "existing_asset_changed"})
            snapshot = "data/assets/" + asset_sha + PurePosixPath(asset_path).suffix
            source_assets.append(
                {"archive_path": asset_path, "blob": entries[asset_path], "snapshot": snapshot, "sha256": asset_sha}
            )
            if asset_path not in old_assets:
                writes[snapshot] = content
        source.update(
            relative_path=path,
            observed_commit=commit,
            blob=oid,
            metadata=metadata,
            assets=source_assets,
            missing_assets=sorted(set(assets) & missing_assets),
        )
    # Documents imported from a plain folder are not archive checkpoints, so their
    # absence from the archive is not a conflict; see core/folder_import.py.
    expected = (
        set(previous["manifest"])
        if previous
        else {
            d
            for d, doc in state["documents"].items()
            if doc.get("source") and (doc["source"].get("origin") or "archive") == "archive"
        }
    )
    for docid in sorted(expected - set(parsed)):
        report["conflicts"].append({"id": docid, "reason": "existing_document_missing"})
    if report["conflicts"]:
        report["status"] = "blocked"
        return SyncPlan(copy.deepcopy(state), {}, report)
    result["archive"] = {
        "path": location,
        "ref": "HEAD",
        "auto_sync": (previous or {}).get("auto_sync", True),
        "commit": commit,
        "manifest": manifest,
    }
    validate(result)
    report.update(status="ready", assets_added=sum(p.startswith("data/assets/") for p in writes))
    return SyncPlan(result, writes, report)


def apply_sync(repository, plan):
    """Apply validated additions, retrying safely after a partial snapshot write.

    Existing matching snapshots are reused; differing bytes are a hard error.
    The commit checkpoint advances only after all required content has been saved.
    """
    if plan.report["status"] == "blocked":
        return plan.state, plan.report
    if plan.report["status"] == "up_to_date":
        return plan.state, plan.report
    # Preflight all destination collisions before creating any files.
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
    return plan.state, {**plan.report, "status": "synced"}
