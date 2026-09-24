"""Persistence adapters for the Studio application, separate from graph algorithms.

FileRepository stores JSON and immutable text files; MemoryRepository uses values
in memory. Both verify snapshot contents and satisfy the same workflow interface."""

import copy
import hashlib
import json
from pathlib import Path
from typing import Protocol

from .blog import preserve_records, storage_path
from .domain import _require, digest, validate
from .migrations import upgrade


class Repository(Protocol):
    """The structural interface required by the application.

    write_new must refuse replacement of an existing snapshot. load/save work with
    Studio state dictionaries. Paths are storage keys; no graph operation uses them."""

    def load(self): ...
    def save(self, state): ...
    def read_text(self, path): ...
    def write_new(self, path, text): ...
    def read_bytes(self, path): ...
    def write_bytes_new(self, path, content): ...


def reuse_or_create(repository, path, content, message=None):
    """Create an immutable snapshot, or accept one already there with identical bytes.

    A snapshot and the metadata that refers to it are separate writes. When the metadata
    save fails, the snapshot stays behind at its deterministic path, and retrying the same
    request has to be able to finish rather than collide with its own earlier attempt.

    Different bytes at that path are still refused: an immutable snapshot is never
    rewritten, and a mismatch means the path already describes something else. Batch
    importers apply the same rule in two phases instead, checking every path before they
    write any, so one conflict stops the whole import rather than half of it.
    """
    binary = isinstance(content, bytes)
    try:
        saved = (repository.read_bytes if binary else repository.read_text)(path)
    except (FileNotFoundError, KeyError):
        (repository.write_bytes_new if binary else repository.write_new)(path, content)
        return
    _require(saved == content, message or "Snapshot destination already holds different text: " + path)


def verify_contents(state, read_text, read_bytes=None):
    """Validate metadata and compare each stored fingerprint with the actual text.

    read_text is injected so this integrity check works with both repository types."""
    validate(state)
    for doc in state["documents"].values():
        if doc.get("source"):
            source = doc["source"]
            # A post written here has pictures but no imported snapshot to check.
            if source.get("snapshot"):
                _require(digest(read_text(source["snapshot"])) == source["sha256"], "Imported source snapshot changed")
            for asset in source.get("assets", []):
                _require(read_bytes is not None, "Binary reader required for assets")
                _require(hashlib.sha256(read_bytes(asset["snapshot"])).hexdigest() == asset["sha256"], "Asset changed")
        for revision in doc["revisions"]:
            _require(
                digest(read_text(revision["path"])) == revision["sha256"],
                "Revision content changed: " + revision["path"],
            )
        for variant in doc["language_variants"].values():
            body = read_text(variant["body"]["path"])
            _require(bool(body.strip()), "Variant body must not be blank")
            _require(digest(body) == variant["body"]["sha256"], "Variant body changed")
        for pair in doc["publication_pairs"].values():
            for asset in pair["attachments"]:
                _require(read_bytes is not None, "Binary reader required for attachments")
                _require(
                    hashlib.sha256(read_bytes(asset["path"])).hexdigest() == asset["sha256"],
                    "Publication attachment changed",
                )

    for rid, release in state["blog"]["releases"].items():
        _require(read_bytes is not None, "Binary reader required for releases")
        raw = read_bytes(release["public_snapshot"])
        _require(hashlib.sha256(raw).hexdigest() == release["public_sha256"], "Release snapshot changed")
        public = json.loads(raw)
        identities = state["blog"]["identities"]["documents"]
        output = {d["id"]: d for d in public["documents"]}
        _require(set(output) == {identities[d]["id"] for d in release["selections"]}, "Release selection mismatch")
        for did, dates in release["dates"].items():
            _require(all(output[identities[did]["id"]][k] == v for k, v in dates.items()), "Release dates mismatch")
        for path, expected in release["files"].items():
            data = read_bytes("data/blog/releases/" + rid + "/site/" + path)
            _require(hashlib.sha256(data).hexdigest() == expected, "Release artifact changed")


class FileRepository:
    """Store snapshots and one JSON metadata file for a single local writer.

    There is no concurrent-writer locking or multi-file transaction in this adapter."""

    def __init__(self, root):
        self.root = Path(root).resolve()
        self.metadata = self.root / "data" / "studio.json"

    def path(self, relative):
        """Resolve a storage key and reject paths that escape the configured project root."""
        storage_path(relative)
        path = (self.root / relative).resolve()
        _require(path != self.root and self.root in path.parents, "Path escapes studio")
        return path

    def read_bytes(self, path):
        return self.path(path).read_bytes()

    def write_bytes_new(self, path, content):
        target = self.path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as handle:
            handle.write(content)

    def read_text(self, path):
        """Decode exact UTF-8 bytes without newline normalization that could change hashes."""
        return self.path(path).read_bytes().decode("utf-8")

    def write_new(self, path, text):
        """Create a snapshot exclusively; fail rather than overwrite an existing revision."""
        target = self.path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as handle:
            handle.write(text.encode("utf-8"))

    def load(self):
        """Read state and verify that its referenced snapshots still match their hashes."""
        state = upgrade(json.loads(self.metadata.read_text(encoding="utf-8")))
        verify_contents(state, self.read_text, self.read_bytes)
        return state

    def save(self, state):
        """Verify referenced text, then replace the metadata file through a temporary file.

        This replaces one metadata file; it does not make earlier snapshot writes atomic."""
        verify_contents(state, self.read_text, self.read_bytes)
        self.metadata.parent.mkdir(parents=True, exist_ok=True)
        if self.metadata.exists():
            previous = self.metadata.read_bytes()
            previous_state = json.loads(previous)
            preserve_records(upgrade(previous_state), state)
            previous_version = previous_state["schema_version"]
            if previous_version in (1, 2, 3):
                relative = f"data/migrations/studio-v{previous_version}.json"
                backup = self.path(relative)
                if backup.exists():
                    _require(backup.read_bytes() == previous, "Migration backup differs")
                else:
                    self.write_bytes_new(relative, previous)
        temporary = self.metadata.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(self.metadata)


class MemoryRepository:
    """An interchangeable in-memory store for tests and embedded application use."""

    def __init__(self):
        self._state = None
        self._text = {}

    def read_bytes(self, path):
        value = self._text[path]
        return value.encode("utf-8") if isinstance(value, str) else value

    def write_bytes_new(self, path, content):
        _require(path not in self._text, "Snapshot already exists")
        self._text[path] = content

    def read_text(self, path):
        return self.read_bytes(path).decode("utf-8")

    def write_new(self, path, text):
        _require(path not in self._text, "Snapshot already exists")
        self._text[path] = text

    def load(self):
        """Return a detached state so callers cannot mutate the saved state accidentally."""
        _require(self._state is not None, "No saved state")
        verify_contents(self._state, self.read_text, self.read_bytes)
        return copy.deepcopy(self._state)

    def save(self, state):
        """Verify and copy the state, keeping ownership inside the repository."""
        verify_contents(state, self.read_text, self.read_bytes)
        if self._state is not None:
            preserve_records(upgrade(self._state), state)
        self._state = copy.deepcopy(state)
