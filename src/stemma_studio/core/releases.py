"""Immutable release contracts and append-only deployment receipts, without I/O."""

import re

from .blog import fields, identifier, require, sha, storage_path, timestamp, validate_assets


def output_path(path):
    storage_path(path)
    require(
        path == ".nojekyll" or not any(p.startswith(".") for p in path.split("/")),
        "Hidden deployment files are forbidden",
    )
    require(
        path in ("fonts/MaruBuri-Regular.woff2", "fonts/MaruBuri-Bold.woff2", "fonts/OFL.txt")
        or path in ("index.html", "404.html", "site.css", "theme.css", "site.js", ".nojekyll")
        or re.fullmatch(
            r"(ko|en)/(index.html|series/index.html|series/[a-z0-9-]+/index.html|posts/[a-z0-9-]+/(index.html|genealogy/index.html))",
            path,
        )
        or re.fullmatch(r"assets/[0-9a-f]{32}\.(png|jpg|jpeg|gif|webp|pdf|txt)", path),
        "File is outside the public output allowlist",
    )


def validate(state):
    blog = state["blog"]
    records = blog["releases"]
    attempts = blog["release_attempts"]
    require(isinstance(records, dict) and isinstance(attempts, list), "Invalid release history")
    for rid, r in records.items():
        fields(
            r,
            "id decided_at planned_published_at input_fingerprint selections structure_approvals "
            "series_snapshot public_snapshot public_sha256 assets base destination parent_release files dates rollback_of",
        )
        identifier(rid)
        require(rid == r["id"], "Release ID mismatch")
        timestamp(r["decided_at"])
        timestamp(r["planned_published_at"])
        sha(r["input_fingerprint"])
        sha(r["public_sha256"])
        require(r["public_snapshot"] == "data/blog/releases/" + rid + "/public.json", "Invalid release snapshot path")
        require(
            isinstance(r["base"], str) and re.fullmatch(r"/(?:[a-zA-Z0-9_-]+/)*", r["base"]), "Invalid deployment base"
        )
        # Deliveries differ in what a destination needs; the folder needs no service at all.
        mode = r["destination"].get("mode")
        home = mode == "homepage-pr"
        if home:
            fields(r["destination"], "path repository mode branch")
            require(
                r["base"] == "/blog/"
                and isinstance(r["destination"]["branch"], str)
                and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", r["destination"]["branch"]),
                "Invalid homepage target",
            )
        elif mode == "local-folder":
            fields(r["destination"], "path mode base")
            require(r["destination"]["base"] == r["base"], "Folder base must match the release base")
        else:
            # Preserved records from the removed dedicated-repository mode stay readable.
            fields(r["destination"], "path repository")
        require(
            isinstance(r["destination"]["path"], str) and r["destination"]["path"].startswith("/"),
            "Explicit destination required",
        )
        repo = r["destination"].get("repository")
        require(
            repo is None
            or isinstance(repo, str)
            and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9][A-Za-z0-9_.-]*", repo),
            "Invalid GitHub repository",
        )
        require(
            (home and repo is not None)
            or repo is None
            or repo.split("/")[1].lower() != repo.split("/")[0].lower() + ".github.io",
            "Use homepage PR mode for a personal homepage",
        )
        for key in ("parent_release", "rollback_of"):
            require(r[key] is None or r[key] in records and r[key] != rid, "Unknown release reference")
        require(
            isinstance(r["selections"], dict)
            and isinstance(r["dates"], dict)
            and set(r["dates"]) == set(r["selections"]),
            "Invalid release selections",
        )
        for did, pair in r["selections"].items():
            require(
                did in state["documents"] and pair in state["documents"][did]["publication_pairs"],
                "Unknown release pair",
            )
            fields(r["dates"][did], "first_published_at published_updated_at")
            for date in r["dates"][did].values():
                timestamp(date)
            require(
                r["dates"][did]["first_published_at"] <= r["dates"][did]["published_updated_at"],
                "Invalid release dates",
            )
        require(
            isinstance(r["structure_approvals"], list) and isinstance(r["series_snapshot"], list),
            "Invalid release snapshots",
        )
        for a in r["structure_approvals"]:
            require(a == blog["structure_approvals"].get(a.get("id")), "Unknown preserved approval")
        from .blog import validate_series

        for series in r["series_snapshot"]:
            validate_series(series, state["documents"])
        validate_assets(r["assets"])
        require(
            isinstance(r["files"], dict)
            and {"index.html", "404.html", "site.css", "site.js", ".nojekyll"} <= set(r["files"]),
            "Incomplete artifact",
        )
        for path, value in r["files"].items():
            output_path(path)
            sha(value)
    active = None
    dates = {}
    running = False
    for a in attempts:
        fields(a, "release started_at finished_at status error commit")
        require(a["release"] in records, "Unknown attempt release")
        timestamp(a["started_at"])
        require(a["status"] in ("running", "failed", "succeeded"), "Invalid deployment status")
        require(
            a["commit"] is None or isinstance(a["commit"], str) and re.fullmatch("[0-9a-f]{40,64}", a["commit"]),
            "Invalid deployed commit",
        )
        if a["status"] == "running":
            require(not running and a["finished_at"] is None and a["error"] is None, "Invalid running attempt")
            running = True
        else:
            require(not running, "An unfinished attempt must be last")
            timestamp(a["finished_at"])
            require(a["finished_at"] >= a["started_at"], "Invalid attempt timestamps")
            if a["status"] == "succeeded":
                require(a["error"] is None and a["commit"] is not None, "Success requires a commit receipt")
                r = records[a["release"]]
                require(r["parent_release"] == active or a["release"] == active, "Release history diverged")
                active = a["release"]
                dates.update(r["dates"])
            else:
                require(isinstance(a["error"], str) and bool(a["error"]), "Failure requires an explanation")
    require(blog["active_release"] == active, "Active release requires a success receipt")
    for did, doc in state["documents"].items():
        expected = dates.get(did, {"first_published_at": None, "published_updated_at": None})
        require(
            all(doc["publication"][key] == value for key, value in expected.items()),
            "Publication dates require successful release history",
        )


def preserve(previous, state):
    old = previous["blog"]
    new = state["blog"]
    require(all(new["releases"].get(k) == v for k, v in old["releases"].items()), "Immutable release changed")
    before = old["release_attempts"]
    after = new["release_attempts"]
    require(len(after) >= len(before), "Cannot remove deployment history")
    for a, b in zip(before, after):
        if a["status"] != "running":
            require(a == b, "Completed deployment attempt changed")
        else:
            require(all(a[k] == b[k] for k in ("release", "started_at")), "Running attempt identity changed")
            require(a["commit"] is None or a["commit"] == b["commit"], "Deployment commit changed")
