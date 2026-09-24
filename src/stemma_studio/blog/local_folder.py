"""Publish the reviewed site into a plain folder, with no service and no account.

A folder of static files is the generic case: it is what every static host
consumes, so the same output feeds a hand-copied directory, rsync, an object
store, or a drag-and-drop deploy. The GitHub pull-request path in homepage.py
is one delivery among several rather than the foundation, and an author who
does not want to connect an account can still publish.

Delivery here is a write and a read-back. There is no build to wait for, so an
attempt succeeds the moment every frozen byte is verified on disk.
"""

import json
import os
import uuid
from pathlib import Path

from stemma_studio.core.blog import require
from stemma_studio.core.containment import contained, safe_path
from stemma_studio.core.releases import output_path

from .deploy import Releases, encoded, private_locations, sha, write_marker

# Records which files this tool wrote, so a later release can remove the ones it
# no longer publishes without ever touching a file it did not create.
MANIFEST = ".stemma-release.json"

# Written beside each output and moved into place, so an interrupted attempt leaves whole
# files rather than truncated ones a retry would have to distinguish from foreign bytes.
PARTIAL = ".stemma-part-"


def place(target, name, content, suffix):
    """Write `name` inside `target` whole, through a temporary sibling.

    The temporary name belongs to somebody else's folder just as much as the final one
    does, so it is resolved by the same primitive and created exclusively. A link there
    would carry the write outside the destination, and a stranger's file there would be
    written through and then carried off by the move — both before verification has any
    bytes to object to. Creating the temporary file is therefore the check, and only a
    file this call made itself is ever removed.
    """
    destination = safe_path(target, name)
    temp = safe_path(target, name + suffix)
    handle = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        with os.fdopen(handle, "wb") as opened:
            opened.write(content)
        temp.replace(destination)
    finally:
        temp.unlink(missing_ok=True)


def inspect(path, root, base="/"):
    """Validate a destination folder without writing anything to it."""
    original = Path(path).expanduser()
    require(original.is_absolute() and not original.is_symlink(), "An absolute destination folder is required")
    target = original.resolve()
    for private in private_locations(root):
        require(
            target != private and private not in target.parents and target not in private.parents,
            "Destination overlaps private workspace",
        )
    require(not target.exists() or target.is_dir(), "Destination must be a folder")
    require(base.startswith("/") and base.endswith("/"), "Base must start and end with /")
    return {"mode": "local-folder", "path": str(target), "base": base}


def read_manifest(target):
    """What this tool last wrote here, or None if it has never published here."""
    path = Path(target) / MANIFEST
    if not path.is_file() or path.is_symlink():
        return None
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    files = record.get("files")
    return record if isinstance(files, dict) else None


class LocalFolder(Releases):
    """Write a frozen release into a folder and verify it byte for byte."""

    def __init__(self, root):
        super().__init__(root)
        self.settings = self.root / "data/blog/local.json"

    def configuration(self):
        return json.loads(self.settings.read_text(encoding="utf-8")) if self.settings.exists() else None

    def configure(self, path, base="/"):
        require(
            not any(a["status"] == "running" for a in self.status()["attempts"]),
            "Finish the pending deployment first",
        )
        config = inspect(path, self.root, base)
        self.settings.parent.mkdir(parents=True, exist_ok=True)
        write_marker(self.settings, config)
        return config

    def freeze_configured(self, token, rollback=None):
        config = self.configuration()
        require(config is not None, "Choose a destination folder first")
        require(inspect(config["path"], self.root, config["base"]) == config, "Destination configuration changed")
        return self.freeze(token, config, base=config["base"], rollback=rollback)

    def target(self, r):
        require(r["destination"].get("mode") == "local-folder", "This release was not published to a folder")
        config = inspect(r["destination"]["path"], self.root, r["destination"].get("base", "/"))
        require(config == r["destination"], "Destination folder or configuration changed")
        return Path(config["path"])

    def resumable(self, blog, r):
        """Whether an earlier attempt at this same release already began writing here.

        An attempt records its commit before the first byte moves, so that receipt is
        what proves this tool wrote into the folder. Nothing weaker will do: adopting a
        file merely because its bytes match would put this tool in charge of deleting
        somebody else's identical file at the next release.
        """
        return any(
            a["release"] == r["id"] and a["commit"] and a["status"] == "failed" for a in blog["release_attempts"]
        )

    def commit(self, r):
        """Check the destination is safe to write, and name this release's content."""
        target = self.target(r)
        previous = read_manifest(target)
        blog = self.state()["blog"]
        owned = set((previous or {}).get("files", {}))
        # A receipt naming this release is an earlier attempt at it that got as far as
        # finishing; the folder has not moved on to somebody else's content. Otherwise the
        # receipt has to name a release this tool made and still match it byte for byte.
        # The comparison is against that release rather than this one's parent, because a
        # site published to two folders in turn leaves each of them at a different release
        # and neither of them has been taken over by anybody.
        if previous is not None and previous.get("release") != r["id"]:
            written = blog["releases"].get(previous.get("release"))
            require(
                written is not None and previous["files"] == written["files"],
                "The destination folder changed since the last release; review before publishing",
            )
        # Every path this release will write is resolved before any byte moves, so a
        # symlinked folder or leaf cannot carry the write outside the chosen destination.
        planned = {name: safe_path(target, name) for name in r["files"]}
        safe_path(target, MANIFEST)
        if self.resumable(blog, r):
            # This release's own unfinished work is its to finish. Only bytes matching
            # what it intends are adopted, so a foreign file at the same path still stops
            # the release instead of being silently taken over.
            owned |= {n for n, p in planned.items() if p.is_file() and sha(p.read_bytes()) == r["files"][n]}
        if target.exists():
            # Only paths a previous release wrote may be replaced. A path this tool is
            # publishing for the first time must not land on somebody else's file, whether
            # the folder is new or has been published to before.
            clashes = sorted(p for p, path in planned.items() if p not in owned and path.exists())
            require(not clashes, "Destination already contains: " + ", ".join(clashes[:5]))
        for name in r["files"]:
            output_path(name)
        return sha(encoded({"release": r["id"], "files": r["files"]}))

    def write(self, r, commit):
        """Write every frozen file, then drop the files a previous release left behind."""
        target = self.target(r)
        files = self.artifact(r)
        previous = read_manifest(target)
        # A failed attempt may have refused an existing temporary file, so its receipt
        # proves no ownership of that path. Fresh names let retries proceed without
        # deleting unverified leftovers, even when attempts start in the same second.
        suffix = PARTIAL + uuid.uuid4().hex
        target.mkdir(parents=True, exist_ok=True)
        for name, content in sorted(files.items()):
            safe_path(target, name).parent.mkdir(parents=True, exist_ok=True)
            place(target, name, content, suffix)
        for name in sorted((previous or {}).get("files", {})):
            if name in files:
                continue
            stale = contained(target, name)
            # A file that no longer resolves inside the folder is left alone rather than
            # followed: this tool removes only what it can still vouch for owning.
            if stale is None or not stale.is_file():
                continue
            stale.unlink()
            for parent in stale.parents:
                if parent == target or any(parent.iterdir()):
                    break
                parent.rmdir()
        place(target, MANIFEST, encoded({"release": r["id"], "commit": commit, "files": r["files"]}), suffix)

    def verify_commit(self, r, commit):
        """Re-read the destination; a release is delivered only if every byte matches."""
        target = self.target(r)
        record = read_manifest(target)
        require(record is not None and record.get("commit") == commit, "Missing release receipt in the destination")
        require(record["files"] == r["files"], "Destination receipt differs from the frozen release")
        for name, digest in r["files"].items():
            written = safe_path(target, name)
            require(written.is_file(), "Missing published file: " + name)
            require(sha(written.read_bytes()) == digest, "Published file differs from the frozen release: " + name)

    def start(self, rid):
        service = self

        class Transport:
            def push(self, r, target, commit):
                service.write(r, commit)

            def status(self, r, commit):
                # A local write is complete once verified; there is no build to wait for.
                service.verify_commit(r, commit)
                return "succeeded"

        self.transport = Transport()
        return super().start(rid)

    def check(self):
        service = self

        class Transport:
            def status(self, r, commit):
                service.verify_commit(r, commit)
                return "succeeded"

        self.transport = Transport()
        return super().check()
