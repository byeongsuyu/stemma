"""Publish reviewed blog artifacts through a PR without changing the author's checkout."""

import json
import re
import tempfile
from pathlib import Path

from stemma_studio.core.blog import require
from stemma_studio.core.releases import output_path
from stemma_studio.locale import Message

from .deploy import Releases, command, git, private_locations, sha, write_marker


def inspect(path, root, branch="master"):
    original = Path(path).expanduser()
    require(original.is_absolute() and not original.is_symlink(), "An absolute homepage checkout is required")
    target = original.resolve()
    for private in private_locations(root):
        require(
            target != private and private not in target.parents and target not in private.parents,
            "Homepage overlaps private workspace",
        )
    require((target / ".git").is_dir() and not (target / ".git").is_symlink(), "Use the main homepage checkout")
    require(git(target, "rev-parse", "--show-toplevel") == str(target), "Not a repository root")
    require(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", branch), "Invalid base branch")
    remote = git(target, "remote", "get-url", "origin")
    match = re.fullmatch(r"(?:https://github.com/|git@github.com:)([A-Za-z0-9-]+/[A-Za-z0-9_.-]+?)(?:\.git)?", remote)
    require(match is not None, "Origin must be a GitHub repository")
    repo = match.group(1)
    git(target, "rev-parse", "--verify", "refs/heads/" + branch)
    return {"mode": "homepage-pr", "path": str(target), "repository": repo, "branch": branch}


class Homepage(Releases):
    """Release receipts stay in Studio; checkout-local records make PR retries idempotent."""

    builds = True

    def __init__(self, root, remote=None):
        super().__init__(root)
        self.remote = remote or GitHub()
        self.settings = self.root / "data/blog/homepage.json"

    def configuration(self):
        return json.loads(self.settings.read_text()) if self.settings.exists() else None

    def configure(self, path, branch="master"):
        require(not any(a["status"] == "running" for a in self.status()["attempts"]), "Finish the pending PR first")
        config = inspect(path, self.root, branch)
        self.settings.parent.mkdir(parents=True, exist_ok=True)
        write_marker(self.settings, config)
        return config

    def freeze_configured(self, token, rollback=None):
        config = self.configuration()
        require(config is not None, "Configure the homepage folder first")
        require(inspect(config["path"], self.root, config["branch"]) == config, "Homepage configuration changed")
        return self.freeze(token, config, rollback=rollback)

    def target(self, r):
        require(
            r["destination"].get("mode") == "homepage-pr",
            Message("error.deploy.dedicated"),
        )
        config = inspect(r["destination"]["path"], self.root, r["destination"]["branch"])
        require(config == r["destination"], "Homepage origin or configuration changed")
        return Path(config["path"])

    def record_path(self, r):
        target = self.target(r)
        folder = target / ".git" / "stemma-pr"
        require(not folder.is_symlink(), "Symlink PR records rejected")
        path = folder / (r["id"] + ".json")
        require(not path.is_symlink(), "Symlink PR record rejected")
        return path

    def record(self, r):
        path = self.record_path(r)
        return json.loads(path.read_text()) if path.exists() else None

    def manifest(self, target, commit, prefix="blog/"):
        result = {}
        for entry in git(target, "ls-tree", "-r", commit, "--", prefix).splitlines():
            meta, name = entry.split("\t", 1)
            mode, kind, oid = meta.split()
            require(mode == "100644" and kind == "blob" and name.startswith(prefix), "Nonregular blog content")
            rel = name[len(prefix) :]
            output_path(rel)
            # Git's text helper strips bytes, so hash blobs through a binary subprocess.
            import os
            import subprocess

            data = subprocess.run(
                ["git", "cat-file", "blob", oid],
                cwd=str(target),
                check=True,
                stdout=subprocess.PIPE,
                env={k: v for k, v in os.environ.items() if not k.startswith("GIT_")},
            ).stdout
            result[rel] = sha(data)
        return result

    def build(self, rid, base_commit=None):
        r = self.state()["blog"]["releases"][rid]
        target = self.target(r)
        record = self.record(r)
        if record and record["commit"]:
            self.verify_commit(r, record["commit"])
            return record
        base = (
            record["base"]
            if record
            else base_commit or git(target, "rev-parse", "refs/heads/" + r["destination"]["branch"])
        )
        require(
            git(target, "ls-tree", base, "--", ".nojekyll").startswith("100644 blob "),
            "Homepage must have a regular .nojekyll file",
        )
        current = self.manifest(target, base)
        blog_entry = git(target, "ls-tree", base, "--", "blog")
        require(not blog_entry or blog_entry.startswith("040000 tree "), "Blog root must be a directory")
        old = self.state()["blog"]["releases"].get(r["parent_release"])
        require(current == (old["files"] if old else {}), "Existing blog files differ from the last successful release")
        files = self.artifact(r)
        # A worktree isolates the generated branch from dirty files and the author's index.
        branch = "codex/blog-" + rid
        folder = target / ".git" / "stemma-worktrees"
        require(not folder.is_symlink(), "Symlink worktree root rejected")
        folder.mkdir(exist_ok=True)
        work = folder / rid
        if not record:
            require(not work.exists() and not git(target, "branch", "--list", branch), "Unexpected release worktree")
            record = {"commit": None, "base": base, "branch": branch, "worktree": str(work), "url": None}
            self.record_path(r).parent.mkdir(exist_ok=True)
            write_marker(self.record_path(r), record)
        require(
            record["worktree"] == str(work) and record["branch"] == branch and not work.is_symlink(),
            "Invalid worktree receipt",
        )
        if not work.exists():
            require(not git(target, "branch", "--list", branch), "Interrupted worktree creation requires inspection")
            git(target, "worktree", "add", "-b", branch, str(work), base)
        require(git(work, "symbolic-ref", "--short", "HEAD") == branch, "Unexpected worktree branch")
        head = git(work, "rev-parse", "HEAD")
        if head != base:
            candidate = dict(record, commit=head)
            write_marker(self.record_path(r), candidate)
            self.verify_commit(r, head)
            return candidate
        # Resume an interrupted file replacement only within the owned artifact set.
        require(not (work / "blog").is_symlink(), "Symlink blog root rejected")
        for path in (work / "blog").rglob("*"):
            require(not path.is_symlink(), "Symlink in generated worktree")
            if path.is_file():
                require(
                    path.relative_to(work / "blog").as_posix() in set(current) | set(files), "Unmanaged worktree file"
                )
        for name in current:
            path = work / "blog" / name
            if path.exists():
                path.unlink()
        for name, data in files.items():
            path = work / "blog" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        git(work, "add", "--", "blog")
        git(work, "commit", "--allow-empty", "-m", "Publish reviewed blog site")
        commit = git(work, "rev-parse", "HEAD")
        record = {"commit": commit, "base": base, "branch": branch, "worktree": str(work), "url": None}
        self.record_path(r).parent.mkdir(exist_ok=True)
        write_marker(self.record_path(r), record)
        self.verify_commit(r, commit)
        return record

    def verify_commit(self, r, commit):
        target = self.target(r)
        record = self.record(r)
        require(record is not None and record["commit"] == commit, "Missing release commit receipt")
        require(
            git(target, "rev-list", "--parents", "-n", "1", commit).split() == [commit, record["base"]],
            "Unexpected release ancestry",
        )
        changes = git(target, "diff", "--name-only", record["base"], commit).splitlines()
        require(all(p.startswith("blog/") for p in changes), "Changes outside blog subtree")
        require(self.manifest(target, commit) == r["files"], "PR differs from frozen release")

    def commit(self, r):
        target = self.target(r)
        self.remote.config(r)
        self.remote.fetch(target, r)
        remote_base = git(target, "rev-parse", "refs/remotes/origin/" + r["destination"]["branch"])
        old = self.state()["blog"]["releases"].get(r["parent_release"])
        require(
            self.manifest(target, remote_base) == (old["files"] if old else {}),
            "Remote blog changed; review before publishing",
        )
        record = self.record(r)
        if record:
            require(
                git(target, "merge-base", remote_base, record["base"]) == record["base"], "Remote base history changed"
            )
        if not record or not record["commit"]:
            record = self.build(r["id"], remote_base)
        self.verify_commit(r, record["commit"])
        return record["commit"]

    def start(self, rid):
        service = self

        class Transport:
            def push(self, r, target, commit):
                record = service.record(r)
                url = service.remote.pr(r, record)
                write_marker(service.record_path(r), dict(record, url=url))

            def status(self, r, commit):
                return service.remote.status(r, service.record(r), service)

        self.transport = Transport()
        return super().start(rid)

    def check(self):
        service = self

        class Transport:
            def status(self, r, commit):
                return service.remote.status(r, service.record(r), service)

        self.transport = Transport()
        return super().check()


class GitHub:
    def api(self, path):
        return json.loads(command(["gh", "api", path]))

    def config(self, r):
        try:
            data = self.api("repos/" + r["destination"]["repository"] + "/pages")
        except FileNotFoundError:
            raise ValueError("GitHub CLI (gh) is required. Install it and run gh auth login.") from None
        require(
            data.get("build_type") == "legacy"
            and data.get("source") == {"branch": r["destination"]["branch"], "path": "/"},
            "Pages must deploy from the configured branch / (root)",
        )

    def fetch(self, target, r):
        branch = r["destination"]["branch"]
        git(target, "fetch", "origin", "refs/heads/" + branch + ":refs/remotes/origin/" + branch)

    def pr(self, r, record):
        self.config(r)
        repo = r["destination"]["repository"]
        target = Path(r["destination"]["path"])
        # Push only the reviewed commit to its dedicated branch, never master or --all.
        git(target, "push", "origin", record["commit"] + ":refs/heads/" + record["branch"])
        existing = json.loads(
            command(
                [
                    "gh",
                    "pr",
                    "list",
                    "--repo",
                    repo,
                    "--head",
                    record["branch"],
                    "--base",
                    r["destination"]["branch"],
                    "--state",
                    "all",
                    "--json",
                    "url,state",
                ]
            )
        )
        if existing:
            require(
                len(existing) == 1 and existing[0]["state"] != "CLOSED",
                "The release PR was closed; prepare a new release",
            )
            return existing[0]["url"]
        with tempfile.TemporaryDirectory() as tmp:
            body = Path(tmp) / "body.md"
            body.write_text(
                "Update only blog/ with the reviewed bilingual static site.\n\nMerge this PR to publish through GitHub Pages.\n",
                encoding="utf-8",
            )
            return command(
                [
                    "gh",
                    "pr",
                    "create",
                    "--repo",
                    repo,
                    "--base",
                    r["destination"]["branch"],
                    "--head",
                    record["branch"],
                    "--title",
                    "Publish reviewed blog site",
                    "--body-file",
                    str(body),
                ]
            )

    def status(self, r, record, service):
        self.config(r)
        repo = r["destination"]["repository"]
        rows = json.loads(
            command(
                [
                    "gh",
                    "pr",
                    "list",
                    "--repo",
                    repo,
                    "--head",
                    record["branch"],
                    "--base",
                    r["destination"]["branch"],
                    "--state",
                    "all",
                    "--json",
                    "number",
                ]
            )
        )
        if not rows:
            return "running"
        require(len(rows) == 1, "Ambiguous PR receipt")
        pr = self.api("repos/" + repo + "/pulls/" + str(rows[0]["number"]))
        if not pr.get("merged"):
            return "failed" if pr.get("state") == "closed" else "running"
        require(pr["head"]["sha"] == record["commit"], "Merged PR head changed")
        merge = pr["merge_commit_sha"]
        target = service.target(r)
        self.fetch(target, r)
        require(service.manifest(target, merge) == r["files"], "Merged blog differs from reviewed release")
        receipt = self.api("repos/" + repo + "/pages/builds/latest")
        if receipt.get("commit") != merge:
            return "running"
        return {"built": "succeeded", "errored": "failed"}.get(receipt.get("status"), "running")
