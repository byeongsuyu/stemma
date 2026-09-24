"""Synthetic phase-one examples, not a migration or a production publisher.

Only an explicitly supplied empty temporary directory is written. The v4 example
is deliberately kept outside Studio.load/save until phase two implements it.
Public UUIDs below are fixed test constants, never derived from private IDs.
"""

import copy
import hashlib
import json
from pathlib import Path

from stemma_studio.blog import site_settings
from stemma_studio.blog.preview import SAMPLE
from stemma_studio.core.domain import digest
from stemma_studio.core.repository import FileRepository

SAMPLE_PAYLOAD = SAMPLE / "public-v3.json"


STAMP = "2026-01-10T09:00:00Z"
RELEASE_TIME = "2026-02-01T09:00:00Z"
IDS = {name: "PRIVATE-DOCUMENT-" + name for name in "ABCDEFGS"}
PUBLIC_IDS = dict(
    zip(
        "ABCDEFGS",
        (
            "b0323d9dad584cb6b663374d06f91adc",
            "342ac58f17b94182b0742ca61ac51358",
            "e8fa76bb14b643ff8b7b37dba9558602",
            "4cedf5c7ba314fda848ae352859968cf",
            "a45a346521de4dac8ed32ab46f2f8f48",
            "fdad81278bda43058c51c0962eb45ad2",
            "d53c22f90e6e44898f8955e30a0f17a3",
            "99092dde28574704b0ec34d18f16d70a",
        ),
    )
)
EDGE_IDS = dict(
    zip(
        ("ab", "ac", "bc", "cd", "ce", "ef", "dg"),
        (
            "a84c137f037c432fa2f4f1846084618a",
            "b8650e92991e410889ce4f41f50e380b",
            "c9e1050f55e4453d838caa36b4998478",
            "d8f1a3de8b8441f7b7a6428977b81912",
            "e6853a9b38014a73bcc705822a648844",
            "f135f6ff3d6545e7b75779b4b3ae8249",
            "62de407083ad4837ad3de2c4b438da71",
        ),
    )
)
SERIES_IDS = (
    "825a19d5f796441b883e48fd932ee586",
    "91cbd95b53f14b369a1a81a5e9af9b51",
    "2ebdd0525b2b4b9fb29e037449c5cc45",
    "bd96a6e52c954f469fb2c5aa4d64ac45",
)


def fingerprint(value):
    """Match the canonical review encoding specified by the phase-one contract."""
    return digest(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False))


def pair_input(document, pair):
    return {
        "base_revision": pair["base_revision"],
        "variants": {lang: document["language_variants"][vid] for lang, vid in pair["variants"].items()},
        "attachments": pair["attachments"],
    }


def make_fixture(root, unrelated=805):
    """Write a v3 corpus and return detached future-state and golden examples.

    Requiring an empty root prevents accidentally targeting the user's corpus.
    Future metadata and translation files exist only under this supplied root.
    """
    root = Path(root)
    if not root.is_dir() or any(root.iterdir()):
        raise ValueError("Fixture requires an existing empty temporary directory")
    repository = FileRepository(root)
    state = {"schema_version": 3, "questions": {}, "documents": {}, "edges": []}
    state["questions"] = {
        q: {"text": "PRIVATE-QUESTION-" + q, "representatives": [], "public": False} for q in ("q", "other")
    }
    state["questions"]["q"]["public"] = True
    names = list(IDS) + [f"isolated-{i}" for i in range(unrelated)]
    for name in names:
        docid = IDS.get(name, "PRIVATE-DOCUMENT-" + name)
        revisions = []
        for rid in ("r1", "r2") if name in ("C", "D") else ("r1",):
            path = f"data/revisions/{docid}/{rid}.md"
            body = f"가상 글 {name} {rid}.\n" if name in ("A", "C", "D", "S") else f"PRIVATE-BODY-{name}-{rid}\n"
            repository.write_new(path, body)
            revisions.append({"id": rid, "path": path, "sha256": digest(body), "note": "Fixture"})
        source = None
        if name == "A":
            path = f"data/imports/{docid}/source.md"
            repository.write_new(path, "PRIVATE-SOURCE-SNAPSHOT\n")
            source = {
                "snapshot": path,
                "sha256": digest("PRIVATE-SOURCE-SNAPSHOT\n"),
                "date": "2020-01-02",
                "assets": [],
                "missing_assets": [],
            }
        state["documents"][docid] = {
            "title": "PRIVATE-TITLE-" + name,
            "kind": "imported" if source else "original",
            "state": "confirmed",
            "archived": name == "B",
            "questions": ["q", "other"],
            "current_revision": revisions[-1]["id"],
            "source": source,
            "publication": {"published": name == "A", "revision": "r1" if name == "A" else None},
            "revisions": revisions,
        }
        if name not in ("B", "S"):
            state["documents"][docid]["created_at"] = "2022-08-19T23:45:06Z" if name == "E" else "2021-07-23T12:34:56Z"
    for name in EDGE_IDS:
        parent, child = name.upper()
        state["edges"].append(
            {
                "id": "PRIVATE-EDGE-" + name,
                "parent": IDS[parent],
                "child": IDS[child],
                "parent_revision": "r2" if name == "dg" else "r1",
                "child_revision": "r1",
                "questions": ["q", "other"] if name == "ac" else ["q"],
                "change_note": "PRIVATE-NOTE-" + name,
                "state": "confirmed",
                "public": False,
            }
        )
    state["questions"]["other"]["representatives"] = [IDS["B"]]
    repository.metadata.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    future = copy.deepcopy(state)
    future["schema_version"] = 4
    for doc in future["documents"].values():
        doc["language_variants"], doc["variant_reviews"], doc["publication_pairs"] = {}, {}, {}
        doc["publication"] = {
            "selected_pair": None,
            "first_published_at": None,
            "published_updated_at": None,
            "legacy_v3": doc["publication"],
        }

    def variant(name, rid, lang, reviewed=True, suffix=""):
        doc = future["documents"][IDS[name]]
        revision = next(r for r in doc["revisions"] if r["id"] == rid)
        vid = f"{lang}-{rid}{suffix}"
        if lang == "ko":
            body = {"kind": "base_revision", "path": revision["path"], "sha256": revision["sha256"]}
        else:
            path = f"data/translations/{IDS[name]}/{vid}.md"
            text = f"Synthetic post {name} {rid}{suffix}.\n"
            repository.write_new(path, text)
            body = {"kind": "translation", "path": path, "sha256": digest(text)}
        value = {
            "id": vid,
            "base_revision": rid,
            "language": lang,
            "title": ("가상 글 " if lang == "ko" else "Synthetic post ") + name,
            "summary": None,
            "body": body,
            "created_at": STAMP,
        }
        doc["language_variants"][vid] = value
        if reviewed:
            doc["variant_reviews"][vid] = {"fingerprint": fingerprint(value), "reviewed_at": STAMP}
        return vid

    for name, rid in (("A", "r1"), ("C", "r2"), ("D", "r1"), ("S", "r1")):
        doc = future["documents"][IDS[name]]
        pair = {
            "id": "pair-" + name,
            "base_revision": rid,
            "variants": {lang: variant(name, rid, lang) for lang in ("ko", "en")},
            "attachments": [],
            "approved_at": STAMP,
        }
        pair["fingerprint"] = fingerprint(pair_input(doc, pair))
        doc["publication_pairs"][pair["id"]] = pair
        doc["publication"]["selected_pair"] = pair["id"]
    variant("C", "r1", "en")
    variant("C", "r2", "en", reviewed=False, suffix="-draft")

    approval = {
        "id": "structure-one",
        "anchor": IDS["C"],
        "nodes": [
            {
                "document": IDS[n],
                "date": {
                    "kind": "unknown" if n == "B" else ("source" if n == "A" else "created"),
                    "value": (None if n == "B" else "2020-01" if n == "A" else "2022-08" if n == "E" else "2021-07"),
                },
            }
            for n in "ABCDEG"
        ],
        "edges": [
            {k: e[k] for k in ("id", "parent", "parent_revision", "child", "child_revision", "questions")}
            for e in state["edges"]
            if e["id"] != "PRIVATE-EDGE-ef"
        ],
        "approved_at": STAMP,
    }
    approval["fingerprint"] = fingerprint({k: approval[k] for k in ("anchor", "nodes", "edges")})
    series = {}
    for sid, slug, members, public in zip(
        SERIES_IDS, ("first", "second", "empty", "private"), ("CBA", "DC", "E", "A"), (True, True, True, False)
    ):
        item = {
            "id": sid,
            "slug": slug,
            "public": public,
            "translations": {
                lang: {"title": ("시리즈 " if lang == "ko" else "Series ") + slug, "summary": None}
                for lang in ("ko", "en")
            },
            "documents": [IDS[n] for n in members],
        }
        item["reviewed_fingerprint"] = fingerprint(item)
        series[sid] = item
    future["blog"] = {
        "identities": {
            "documents": {IDS[n]: {"id": pid, "slug": "post-" + n.lower()} for n, pid in PUBLIC_IDS.items()},
            "edges": {"PRIVATE-EDGE-" + n: eid for n, eid in EDGE_IDS.items()},
            "questions": {},
        },
        "structure_approvals": {approval["id"]: approval},
        "selected_structure_approvals": [approval["id"]],
        "question_labels": {},
        "edge_labels": {},
        "series": series,
        "series_order": list(SERIES_IDS),
        "releases": {},
        "release_attempts": [],
        "active_release": None,
    }
    expected_bytes = SAMPLE_PAYLOAD.read_bytes()
    expected = json.loads(expected_bytes)
    selections = {
        did: doc["publication"]["selected_pair"]
        for did, doc in future["documents"].items()
        if doc["publication"]["selected_pair"] is not None
    }
    review_input = {
        "selections": {
            did: {
                "pair": future["documents"][did]["publication_pairs"][pid],
                "variants": pair_input(future["documents"][did], future["documents"][did]["publication_pairs"][pid])[
                    "variants"
                ],
            }
            for did, pid in selections.items()
        },
        "structure_approvals": [copy.deepcopy(approval)],
        "series_snapshot": [copy.deepcopy(series[s]) for s in SERIES_IDS],
        "labels": {"questions": {}, "edges": {}},
        "identities": copy.deepcopy(future["blog"]["identities"]),
        "dates": {
            did: {
                "source_date": doc["source"]["date"] if doc["source"] else None,
                "created_at": doc.get("created_at"),
                "first_published_at": doc["publication"]["first_published_at"],
                "published_updated_at": doc["publication"]["published_updated_at"],
            }
            for did, doc in future["documents"].items()
            if did in selections
        },
        "assets": [],
        "planned_published_at": RELEASE_TIME,
    }
    release = {
        "id": "release-one",
        "decided_at": STAMP,
        "planned_published_at": RELEASE_TIME,
        "input_fingerprint": fingerprint(review_input),
        "selections": selections,
        "structure_approvals": review_input["structure_approvals"],
        "series_snapshot": review_input["series_snapshot"],
        "public_snapshot": "data/blog/releases/release-one/public.json",
        "public_sha256": hashlib.sha256(expected_bytes).hexdigest(),
        "assets": [],
    }
    repository.write_bytes_new(release["public_snapshot"], expected_bytes)
    future["blog"]["releases"][release["id"]] = release
    future["blog"]["release_attempts"] = [
        {
            "release": release["id"],
            "started_at": RELEASE_TIME,
            "finished_at": "2026-02-01T09:01:00Z",
            "status": "failed",
            "error": "Synthetic deployment failure",
        },
        {
            "release": release["id"],
            "started_at": "2026-02-01T09:02:00Z",
            "finished_at": None,
            "status": "running",
            "error": None,
        },
    ]
    sentinels = [
        "PRIVATE-",
        "2021-07-23T12:34:56Z",
        "2022-08-19",
        "data/",
        "sha256",
        "archived",
        "editor_sources",
        "editor_receipt",
        "variant_reviews",
    ]
    sentinels.extend(r["sha256"] for doc in state["documents"].values() for r in doc["revisions"])
    # The synthetic author writes in Korean and has said so, as a real author does before
    # publishing from a root that has never published anything.
    site_settings.save(root, {"language": "ko"})
    return {
        "legacy": state,
        "future": future,
        "expected": expected,
        "review_input": review_input,
        "sentinels": sentinels,
    }


def make_homepage(path):
    """Create a disposable personal-homepage checkout that the PR path accepts."""
    from stemma_studio.blog.deploy import git

    home = Path(path)
    home.mkdir(parents=True, exist_ok=True)
    git(home, "init")
    git(home, "symbolic-ref", "HEAD", "refs/heads/master")
    (home / "index.html").write_text("existing homepage")
    (home / ".nojekyll").write_text("")
    git(home, "add", ".")
    git(home, "commit", "-m", "Existing homepage")
    git(home, "remote", "add", "origin", "https://github.com/example/example.github.io.git")
    return home


def add_legacy_release(root, state, rid="release-" + "0" * 32, succeeded=True):
    """Record a preserved dedicated-repository release.

    That delivery mode is gone, but `studio.releases` still accepts its
    `{path, repository}` destination, so reading old history must keep working.
    """
    import copy

    from stemma_studio.blog.deploy import Releases, encoded, sha
    from stemma_studio.blog.input import prepare_input
    from stemma_studio.blog.preview import static_files
    from stemma_studio.core.blog import fingerprint

    service = Releases(root)
    bundle = prepare_input(service.studio, state, RELEASE_TIME)
    files = static_files(bundle["public"], bundle["assets"], base="/blog/", preview=False)
    files[".nojekyll"] = b""
    selections = {
        did: doc["publication"]["selected_pair"]
        for did, doc in state["documents"].items()
        if doc["publication"]["selected_pair"]
    }
    config = state["blog"]
    raw = encoded(bundle["public"])
    record = {
        "id": rid,
        "decided_at": RELEASE_TIME,
        "planned_published_at": RELEASE_TIME,
        "input_fingerprint": fingerprint(state),
        "selections": selections,
        "structure_approvals": [
            copy.deepcopy(config["structure_approvals"][a]) for a in config["selected_structure_approvals"]
        ],
        "series_snapshot": [copy.deepcopy(config["series"][s]) for s in config["series_order"]],
        "public_snapshot": "data/blog/releases/" + rid + "/public.json",
        "public_sha256": sha(raw),
        "assets": [],
        "base": "/blog/",
        "destination": {"path": "/absolute/legacy-blog-site", "repository": "owner/blog"},
        "parent_release": config["active_release"],
        "files": {p: sha(b) for p, b in files.items()},
        "dates": {
            did: {"first_published_at": RELEASE_TIME, "published_updated_at": RELEASE_TIME} for did in selections
        },
        "rollback_of": None,
    }
    repository = service.studio.repository
    repository.write_bytes_new(record["public_snapshot"], raw)
    for path, data in files.items():
        repository.write_bytes_new("data/blog/releases/" + rid + "/site/" + path, data)
    result = copy.deepcopy(state)
    result["blog"]["releases"][rid] = record
    result["blog"]["release_attempts"].append(
        {
            "release": rid,
            "started_at": RELEASE_TIME,
            "finished_at": "2026-02-01T09:05:00Z",
            "status": "succeeded" if succeeded else "failed",
            "error": None if succeeded else "Synthetic legacy deployment failure",
            "commit": "b" * 40 if succeeded else None,
        }
    )
    if succeeded:
        result["blog"]["active_release"] = rid
        for did in selections:
            result["documents"][did]["publication"].update(record["dates"][did])
    repository.save(result)
    return record
