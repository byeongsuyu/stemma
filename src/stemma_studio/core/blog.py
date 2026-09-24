"""Pure bilingual publication contracts; no files, UI, or graph mutation.

Variants, reviews and pairs are append-only records. Selecting a pair expresses a
local decision, not a successful deployment. Release execution belongs to the app.
"""

import copy
import hashlib
import json
import re
from datetime import datetime
from pathlib import PurePosixPath

from stemma_graph import GraphError


def require(condition, message):
    if not condition:
        raise GraphError(message)


def fingerprint(value):
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()


def fields(value, names):
    require(isinstance(value, dict) and set(value) == set(names.split()), "Invalid blog record fields")


def text(value):
    require(isinstance(value, str) and bool(value.strip()), "Text must not be blank")


def identifier(value, public=False):
    pattern = r"[0-9a-f]{32}" if public else r"[A-Za-z0-9_-]+"
    require(isinstance(value, str) and re.fullmatch(pattern, value) is not None, "Invalid blog ID")


def sha(value):
    require(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None, "Invalid SHA-256")


def timestamp(value):
    require(isinstance(value, str), "Invalid UTC timestamp")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        raise GraphError("Invalid UTC timestamp") from None
    require(parsed.strftime("%Y-%m-%dT%H:%M:%SZ") == value, "Invalid UTC timestamp")


def storage_path(value):
    text(value)
    require(
        "\\" not in value
        and not PurePosixPath(value).is_absolute()
        and all(p not in ("", ".", "..") for p in value.split("/")),
        "Invalid storage path",
    )


def empty_blog():
    return {
        "identities": {"documents": {}, "edges": {}, "questions": {}},
        "structure_approvals": {},
        "selected_structure_approvals": [],
        "question_labels": {},
        "edge_labels": {},
        "series": {},
        "series_order": [],
        "releases": {},
        "release_attempts": [],
        "active_release": None,
    }


def document_fields(legacy=None):
    return {
        "language_variants": {},
        "variant_reviews": {},
        "publication_pairs": {},
        "publication": {
            "selected_pair": None,
            "first_published_at": None,
            "published_updated_at": None,
            "legacy_v3": copy.deepcopy(legacy),
        },
    }


def pair_input(document, pair):
    require(
        isinstance(pair["variants"], dict) and set(pair["variants"]) == {"ko", "en"},
        "Publication requires both ko and en variants",
    )
    require(
        all(isinstance(vid, str) and vid in document["language_variants"] for vid in pair["variants"].values()),
        "Unknown variant",
    )
    return {
        "base_revision": pair["base_revision"],
        "variants": {lang: document["language_variants"][vid] for lang, vid in pair["variants"].items()},
        "attachments": pair["attachments"],
    }


def validate_assets(assets):
    require(isinstance(assets, list), "Invalid attachments")
    seen = set()
    for asset in assets:
        fields(asset, "id path sha256 media_type")
        identifier(asset["id"], public=True)
        require(asset["id"] not in seen, "Duplicate attachment")
        seen.add(asset["id"])
        storage_path(asset["path"])
        require(asset["path"].startswith("data/assets/"), "Attachment must be a preserved asset")
        sha(asset["sha256"])
        require(
            asset["media_type"]
            in ("image/png", "image/jpeg", "image/gif", "image/webp", "application/pdf", "text/plain"),
            "Unsupported attachment media type",
        )


def validate_pair(document, pair):
    fields(pair, "id base_revision variants attachments approved_at fingerprint")
    identifier(pair["id"])
    timestamp(pair["approved_at"])
    require(document["state"] == "confirmed", "Publishing requires confirmed document")
    payload = pair_input(document, pair)
    for lang, variant in payload["variants"].items():
        require(
            variant["language"] == lang and variant["base_revision"] == pair["base_revision"],
            "Publication variants must share the same base revision and correct languages",
        )
        review = document["variant_reviews"].get(variant["id"])
        require(
            review is not None and review["fingerprint"] == fingerprint(variant),
            "Publication requires reviewed variants",
        )
    summaries = [v["summary"] for v in payload["variants"].values()]
    require(
        all(s is None for s in summaries) or all(s is not None for s in summaries),
        "Publication summaries require both languages",
    )
    validate_assets(pair["attachments"])
    require(pair["fingerprint"] == fingerprint(payload), "Publication pair fingerprint changed")


def validate_document(docid, doc):
    revisions = {r["id"]: r for r in doc["revisions"]}
    for key in ("language_variants", "variant_reviews", "publication_pairs"):
        require(isinstance(doc.get(key), dict), "Missing blog document records")
    for vid, variant in doc["language_variants"].items():
        fields(variant, "id base_revision language title summary body created_at")
        identifier(vid)
        require(vid == variant["id"], "Variant ID mismatch")
        require(
            isinstance(variant["base_revision"], str) and variant["base_revision"] in revisions,
            "Unknown variant base revision",
        )
        require(variant["language"] in ("ko", "en"), "Unsupported variant language")
        text(variant["title"])
        if variant["summary"] is not None:
            text(variant["summary"])
        timestamp(variant["created_at"])
        body = variant["body"]
        fields(body, "kind path sha256")
        sha(body["sha256"])
        storage_path(body["path"])
        if body["kind"] == "base_revision":
            revision = revisions[variant["base_revision"]]
            require(
                body["path"] == revision["path"] and body["sha256"] == revision["sha256"],
                "Base-language body must match the exact revision",
            )
        else:
            require(body["kind"] == "translation", "Invalid variant body kind")
            require(body["path"] == f"data/translations/{docid}/{vid}.md", "Invalid translation storage path")
    for vid, review in doc["variant_reviews"].items():
        fields(review, "fingerprint reviewed_at")
        require(vid in doc["language_variants"], "Unknown reviewed variant")
        require(review["fingerprint"] == fingerprint(doc["language_variants"][vid]), "Stale variant review")
        timestamp(review["reviewed_at"])
    for pid, pair in doc["publication_pairs"].items():
        require(pid == pair["id"], "Pair ID mismatch")
        validate_pair(doc, pair)
    publication = doc["publication"]
    fields(publication, "selected_pair first_published_at published_updated_at legacy_v3")
    selected = publication["selected_pair"]
    require(
        selected is None or (isinstance(selected, str) and selected in doc["publication_pairs"]),
        "Publishing requires a reviewed bilingual pair ID, not a revision",
    )
    for key in ("first_published_at", "published_updated_at"):
        if publication[key] is not None:
            timestamp(publication[key])
    first, updated = publication["first_published_at"], publication["published_updated_at"]
    require(
        (first is None and updated is None) or (first is not None and updated is not None and first <= updated),
        "Invalid publication dates",
    )
    legacy = publication["legacy_v3"]
    if legacy is not None:
        fields(legacy, "published revision")
        require(type(legacy["published"]) is bool, "Invalid legacy publication")
        require(legacy["revision"] is None or legacy["revision"] in revisions, "Unknown legacy revision")
        require(
            not legacy["published"] or (doc["state"] == "confirmed" and legacy["revision"] in revisions),
            "Invalid legacy publication",
        )


def validate_series(series, documents):
    fields(series, "id slug public translations documents reviewed_fingerprint")
    identifier(series["id"], public=True)
    require(
        isinstance(series["slug"], str) and re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", series["slug"]) is not None,
        "Invalid series slug",
    )
    require(type(series["public"]) is bool, "Invalid series public flag")
    members = series["documents"]
    require(
        isinstance(members, list) and all(isinstance(d, str) and d in documents for d in members),
        "Unknown series document",
    )
    require(len(members) == len(set(members)), "Duplicate series document")
    translations = series["translations"]
    require(isinstance(translations, dict) and set(translations) <= {"ko", "en"}, "Invalid series languages")
    for label in translations.values():
        fields(label, "title summary")
        text(label["title"])
        if label["summary"] is not None:
            text(label["summary"])
    payload = {k: v for k, v in series.items() if k != "reviewed_fingerprint"}
    review = series["reviewed_fingerprint"]
    require(review is None or review == fingerprint(payload), "Stale series review")
    if series["public"]:
        require(set(translations) == {"ko", "en"}, "Public series requires ko and en")
        summaries = [v["summary"] for v in translations.values()]
        require(
            all(s is None for s in summaries) or all(s is not None for s in summaries),
            "Series summaries require both languages",
        )
        require(review == fingerprint(payload), "Public series requires review")


def validate(state):
    """Validate bilingual state, disclosure and deployment receipts."""
    blog = state.get("blog")
    fields(
        blog,
        "identities structure_approvals selected_structure_approvals question_labels "
        "edge_labels series series_order releases release_attempts active_release",
    )
    for docid, doc in state["documents"].items():
        validate_document(docid, doc)
    from .disclosure import validate_disclosure

    validate_disclosure(state)
    from .releases import validate as validate_releases

    validate_releases(state)
    require(isinstance(blog["series"], dict), "Invalid series records")
    slugs = set()
    for sid, series in blog["series"].items():
        validate_series(series, state["documents"])
        require(sid == series["id"], "Series ID mismatch")
        require(series["slug"] not in slugs, "Duplicate series slug")
        require(series["slug"] not in state["documents"], "Series slug must not copy a private document ID")
        slugs.add(series["slug"])
    order = blog["series_order"]
    require(
        isinstance(order, list)
        and all(isinstance(s, str) for s in order)
        and len(order) == len(set(order))
        and set(order) == set(blog["series"]),
        "Invalid series order",
    )


def preserve_records(previous, state):
    """Reject rewriting immutable metadata even when callers bypass use cases."""
    for did, old in previous["documents"].items():
        require(did in state["documents"], "Cannot remove a preserved document")
        new = state["documents"][did]
        for key in ("language_variants", "variant_reviews", "publication_pairs"):
            require(
                all(k in new[key] and new[key][k] == v for k, v in old[key].items()),
                "Immutable blog record changed: " + key,
            )
        require(
            new["publication"]["legacy_v3"] == old["publication"]["legacy_v3"], "Legacy publication record is immutable"
        )

    from .releases import preserve

    preserve(previous, state)
    for key in ("structure_approvals",):
        require(
            all(k in state["blog"][key] and state["blog"][key][k] == v for k, v in previous["blog"][key].items()),
            "Immutable structure approval changed",
        )
    for kind, mapping in previous["blog"]["identities"].items():
        require(
            all(
                k in state["blog"]["identities"][kind] and state["blog"]["identities"][kind][k] == v
                for k, v in mapping.items()
            ),
            "Immutable public identity changed",
        )
