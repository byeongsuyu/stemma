"""Explicit release freezing and the deployment lifecycle shared by every delivery."""

import copy
import hashlib
import json
import os
import subprocess
import uuid
from datetime import UTC, datetime
from pathlib import Path

from stemma_studio.core.application import Studio
from stemma_studio.core.blog import fingerprint, require, timestamp
from stemma_studio.core.releases import output_path
from stemma_studio.locale import Message

from .admin import Conflict, Overlay
from .input import prepare_input
from .preview import static_files
from .site_settings import load as load_site


def private_locations(root):
    """Places a homepage checkout must never overlap.

    The Studio data root and the installed code are known from here; the Git
    archive is wherever this author bound it, so it is read from the data root
    rather than assumed.
    """
    locations = [Path(root).resolve(), Path(__file__).resolve().parents[1]]
    metadata = Path(root) / "data" / "studio.json"
    if metadata.exists():
        try:
            archive = json.loads(metadata.read_text(encoding="utf-8")).get("archive") or {}
        except (json.JSONDecodeError, OSError):
            archive = {}
        if archive.get("path"):
            locations.append(Path(archive["path"]).resolve())
    return locations


def now():
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def write_marker(path, value):
    temp = path.with_suffix(".tmp")
    temp.write_bytes(encoded(value))
    temp.replace(path)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def command(args, cwd=None):
    # Never inherit a caller's alternate Git directory, index or command configuration.
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["GIT_TERMINAL_PROMPT"] = "0"
    result = subprocess.run(
        args,
        cwd=str(cwd) if cwd else None,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode:
        raise RuntimeError(args[0] + " command failed; check repository access and authentication")
    return result.stdout.strip()


def git(target, *args):
    return command(
        [
            "git",
            "-c",
            "core.hooksPath=/dev/null",
            "-c",
            "commit.gpgsign=false",
            "-c",
            "user.name=Stemma",
            "-c",
            "user.email=stemma@localhost",
            *args,
        ],
        target,
    )


class Releases:
    """Freeze, artifact and attempt bookkeeping shared by every delivery path.

    Delivery is not implemented here. A subclass verifies the destination, produces
    the reviewed commit, checks it against the frozen artifact and installs its transport.
    """

    # Whether this delivery has a build between pushing and going live. A folder is live
    # the moment its bytes are verified, so a caller must not assume every service builds.
    builds = False

    def __init__(self, root):
        self.studio = Studio(root)
        self.root = Path(root).resolve()
        self.transport = None

    def state(self):
        return self.studio.load(auto_sync=False)

    def status(self):
        state = self.state()
        blog = state["blog"]
        return {
            "token": fingerprint(state),
            "active_release": blog["active_release"],
            "releases": list(blog["releases"].values()),
            "attempts": blog["release_attempts"],
        }

    def freeze(self, token, destination, base="/blog/", planned_at=None, rollback=None):
        # The caller supplies a destination its own delivery has already verified.
        state = self.state()
        if token != fingerprint(state):
            raise Conflict(Message("error.deploy.stale"))
        require(
            not any(a["status"] == "running" for a in state["blog"]["release_attempts"]),
            Message("error.deploy.running"),
        )
        planned = planned_at or now()
        timestamp(planned)
        blog = state["blog"]
        active = blog["active_release"]
        if active:
            require(planned >= blog["releases"][active]["planned_published_at"], "Release time cannot move backwards")
        rid = "release-" + uuid.uuid4().hex
        overlay = Overlay(self.studio.repository, state)
        if rollback:
            old = blog["releases"][rollback]
            require(
                any(a["release"] == rollback and a["status"] == "succeeded" for a in blog["release_attempts"]),
                "Rollback requires a successful reviewed release",
            )
            public = json.loads(overlay.read_bytes(old["public_snapshot"]))
            selections = copy.deepcopy(old["selections"])
            assets = copy.deepcopy(old["assets"])
            structures = copy.deepcopy(old["structure_approvals"])
            series = copy.deepcopy(old["series_snapshot"])
            for doc in public["documents"]:
                did = next(d for d in selections if blog["identities"]["documents"][d]["id"] == doc["id"])
                pub = state["documents"][did]["publication"]
                doc["first_published_at"] = pub["first_published_at"] or planned
                doc["published_updated_at"] = planned
            from stemma_studio.core.public_assets import asset_url

            asset_bytes = {asset_url(a): overlay.read_bytes(a["path"]) for a in assets}
        else:
            bundle = prepare_input(self.studio, state, planned)
            public = bundle["public"]
            asset_bytes = bundle["assets"]
            selections = {
                did: d["publication"]["selected_pair"]
                for did, d in state["documents"].items()
                if d["publication"]["selected_pair"]
            }
            assets = {}
            for did, pid in selections.items():
                for a in state["documents"][did]["publication_pairs"][pid]["attachments"]:
                    require(a["id"] not in assets or assets[a["id"]] == a, "Conflicting release attachments")
                    assets[a["id"]] = a
            assets = list(assets.values())
            structures = [copy.deepcopy(blog["structure_approvals"][a]) for a in blog["selected_structure_approvals"]]
            series = [copy.deepcopy(blog["series"][s]) for s in blog["series_order"]]
        files = static_files(public, asset_bytes, base=base, preview=False, site=load_site(self.root))
        files[".nojekyll"] = b""
        for name in files:
            output_path(name)
        dates = {
            did: {
                k: next(d for d in public["documents"] if d["id"] == blog["identities"]["documents"][did]["id"])[k]
                for k in ("first_published_at", "published_updated_at")
            }
            for did in selections
        }
        prefix = "data/blog/releases/" + rid + "/"
        raw = encoded(public)
        release = {
            "id": rid,
            "decided_at": now(),
            "planned_published_at": planned,
            "input_fingerprint": fingerprint(state),
            "selections": selections,
            "structure_approvals": structures,
            "series_snapshot": series,
            "public_snapshot": prefix + "public.json",
            "public_sha256": sha(raw),
            "assets": assets,
            "base": base,
            "destination": destination,
            "parent_release": active,
            "files": {p: sha(b) for p, b in files.items()},
            "dates": dates,
            "rollback_of": rollback,
        }
        overlay.write_bytes_new(prefix + "public.json", raw)
        for p, b in files.items():
            overlay.write_bytes_new(prefix + "site/" + p, b)
        state["blog"]["releases"][rid] = release
        overlay.save(state)
        overlay.commit()
        return release

    def artifact(self, release):
        prefix = "data/blog/releases/" + release["id"] + "/site/"
        files = {p: self.studio.repository.read_bytes(prefix + p) for p in release["files"]}
        require(all(sha(b) == release["files"][p] for p, b in files.items()), "Frozen artifact changed")
        return files

    def configuration(self):
        raise NotImplementedError("A delivery subclass must say where it is configured to send")

    def commit(self, release):
        raise NotImplementedError("A delivery subclass must produce a reviewed commit")

    def verify_commit(self, release, commit):
        raise NotImplementedError("A delivery subclass must verify its own commit")

    def start(self, rid):
        state = self.state()
        blog = state["blog"]
        release = blog["releases"][rid]
        if blog["active_release"] == rid:
            return self.status()
        require(release["parent_release"] == blog["active_release"], "This release is stale; review a new release")
        # A release carries the destination it was frozen for, and delivery sends it there
        # whatever a screen now says. Choosing a different destination therefore ends a
        # frozen release: sending it anyway would write to the old one under the new one's
        # name. A release belonging to another kind of delivery is left to that delivery
        # to refuse, which it does in the words of the mode it actually names.
        configured = self.configuration() or {}
        require(
            release["destination"] == configured or release["destination"].get("mode") != configured.get("mode"),
            "This release was frozen for a different destination; review a new release",
        )
        require(not any(a["status"] == "running" for a in blog["release_attempts"]), "A deployment is already running")
        attempt = {
            "release": rid,
            "started_at": now(),
            "finished_at": None,
            "status": "running",
            "error": None,
            "commit": None,
        }
        blog["release_attempts"].append(attempt)
        self.studio.save(state)
        try:
            commit = self.commit(release)
            state = self.state()
            state["blog"]["release_attempts"][-1]["commit"] = commit
            self.studio.save(state)
            self.transport.push(release, Path(release["destination"]["path"]), commit)
        except Exception:
            self.finish("failed", "error.deploy.push")
            raise
        return self.check()

    def check(self):
        state = self.state()
        attempts = state["blog"]["release_attempts"]
        if not attempts or attempts[-1]["status"] != "running":
            return self.status()
        attempt = attempts[-1]
        release = state["blog"]["releases"][attempt["release"]]
        if not attempt["commit"]:
            return self.status()
        self.verify_commit(release, attempt["commit"])
        result = self.transport.status(release, attempt["commit"])
        if result == "succeeded":
            self.finish("succeeded")
        elif result == "failed":
            self.finish("failed", "error.deploy.pages")
        return self.status()

    def finish(self, status, error=None):
        # A failure is recorded as a message key, so each screen can explain it in its own
        # language; the key is what the data root keeps.
        state = self.state()
        blog = state["blog"]
        attempt = blog["release_attempts"][-1]
        require(attempt["status"] == "running", "No running deployment")
        attempt.update(status=status, finished_at=now(), error=error)
        if status == "succeeded":
            release = blog["releases"][attempt["release"]]
            blog["active_release"] = release["id"]
            for did, dates in release["dates"].items():
                state["documents"][did]["publication"].update(dates)
        self.studio.save(state)

    def interrupt(self):
        # Unknown remote outcomes are checked before retrying the same frozen release.
        self.finish("failed", "error.deploy.interrupted")
        return self.status()
