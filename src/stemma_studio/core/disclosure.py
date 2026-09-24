"""Validated structure snapshots, public identities and date precision rules."""

import re
from datetime import UTC, date, datetime

from .blog import fields, fingerprint, identifier, require, text, timestamp

EDGE_FIELDS = ("id", "parent", "parent_revision", "child", "child_revision", "questions")


def document_date(document):
    """Use recorded source time first; never infer time from revision order."""
    source = (document.get("source") or {}).get("date")
    value = source if source else document.get("created_at")
    kind = "source" if source else "created"
    unknown = {"kind": "unknown", "value": None, "precision": "unknown"}
    if not isinstance(value, str):
        return unknown
    try:
        if re.fullmatch(r"\d{4}-\d{2}", value):
            date.fromisoformat(value + "-01")
            return {"kind": kind, "value": value, "precision": "month"}
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            date.fromisoformat(value)
        else:
            if not re.match(r"^\d{4}-\d{2}-\d{2}T", value):
                return unknown
            datetime.fromisoformat(value)
        return {"kind": kind, "value": value[:10], "precision": "day"}
    except ValueError:
        return unknown


def chronology_key(document):
    """Sort using recorded precision; normalize timezone-aware instants to UTC.

    Unknown dates stay last. Date-only values retain their recorded precision;
    this key is private and does not add timestamps to public placeholders.
    """
    value = (document.get("source") or {}).get("date") or document.get("created_at")
    if document_date(document)["value"] is None:
        return ""
    if "T" in value:
        instant = datetime.fromisoformat(value)
        if instant.tzinfo is not None:
            instant = instant.astimezone(UTC).replace(tzinfo=None)
        return instant.isoformat(timespec="microseconds")
    return value


def month_date(document):
    value = document_date(document)
    return {"kind": value["kind"], "value": value["value"][:7] if value["value"] else None}


def validate_snapshot(state, approval, live=False):
    """Stored snapshots are immutable; live compatibility is checked at approval/export."""
    fields(approval, "id anchor nodes edges approved_at fingerprint")
    identifier(approval["id"])
    timestamp(approval["approved_at"])
    documents = state["documents"]
    require(isinstance(approval["anchor"], str) and approval["anchor"] in documents, "Unknown structure anchor")
    require(isinstance(approval["nodes"], list) and isinstance(approval["edges"], list), "Invalid structure lists")
    nodes = set()
    for node in approval["nodes"]:
        fields(node, "document date")
        did = node["document"]
        require(isinstance(did, str) and did in documents and did not in nodes, "Unknown or duplicate structure node")
        nodes.add(did)
        value = node["date"]
        fields(value, "kind value")
        require(value["kind"] in ("source", "created", "unknown"), "Invalid structure date kind")
        if value["kind"] == "unknown":
            require(value["value"] is None, "Unknown date must be null")
        else:
            require(
                isinstance(value["value"], str) and re.fullmatch(r"\d{4}-\d{2}", value["value"]) is not None,
                "Structure date must contain only a month",
            )
            try:
                date.fromisoformat(value["value"] + "-01")
            except ValueError:
                require(False, "Invalid structure month")
        if live:
            require(documents[did]["state"] == "confirmed", "Structure requires confirmed documents")
            require(value == month_date(documents[did]), "Structure date changed; review again")
    require(approval["anchor"] in nodes, "Structure must contain its anchor")
    live_edges = {e["id"]: e for e in state["edges"]}
    seen = set()
    for edge in approval["edges"]:
        fields(edge, " ".join(EDGE_FIELDS))
        identifier(edge["id"])
        require(edge["id"] not in seen, "Duplicate structure edge")
        seen.add(edge["id"])
        for end in ("parent", "child"):
            require(isinstance(edge[end], str) and edge[end] in nodes, "Structure edge needs both approved nodes")
            require(
                edge[end + "_revision"] in [r["id"] for r in documents[edge[end]]["revisions"]],
                "Unknown structure revision",
            )
        scopes = edge["questions"]
        require(
            isinstance(scopes, list)
            and scopes
            and all(isinstance(q, str) and q in state["questions"] for q in scopes)
            and len(scopes) == len(set(scopes)),
            "Invalid structure questions",
        )
        if live:
            original = live_edges.get(edge["id"])
            require(
                original is not None
                and original["state"] == "confirmed"
                and all(edge[k] == original[k] for k in EDGE_FIELDS),
                "Structure edge changed; review again",
            )
    require(
        approval["fingerprint"] == fingerprint({k: approval[k] for k in ("anchor", "nodes", "edges")}),
        "Structure fingerprint changed",
    )
    if live:
        from .adapters import to_genealogy

        component = to_genealogy(state).connected_components([approval["anchor"]])[0]
        require(nodes <= set(component["nodes"]), "Structure includes an unrelated component")


def validate_disclosure(state):
    blog = state["blog"]
    mappings = blog["identities"]
    fields(mappings, "documents edges questions")
    keys = {
        "documents": set(state["documents"]),
        "edges": {e["id"] for e in state["edges"]},
        "questions": set(state["questions"]),
    }
    private = set.union(*keys.values())
    used, slugs = set(), set()
    for kind, mapping in mappings.items():
        require(isinstance(mapping, dict), "Invalid identity mapping")
        for internal, value in mapping.items():
            require(internal in keys[kind], "Unknown mapped identity")
            if kind == "documents":
                fields(value, "id slug")
                slug = value["slug"]
                require(
                    isinstance(slug, str) and re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug) is not None,
                    "Invalid public slug",
                )
                require(slug not in private and slug not in slugs, "Duplicate or private public slug")
                slugs.add(slug)
                value = value["id"]
            identifier(value, public=True)
            require(value not in used and value not in private, "Duplicate or private public identity")
            used.add(value)
    require(isinstance(blog["structure_approvals"], dict), "Invalid structure approvals")
    for aid, approval in blog["structure_approvals"].items():
        validate_snapshot(state, approval)
        require(aid == approval["id"], "Structure approval ID mismatch")
    chosen = blog["selected_structure_approvals"]
    require(
        isinstance(chosen, list)
        and all(isinstance(a, str) and a in blog["structure_approvals"] for a in chosen)
        and len(chosen) == len(set(chosen)),
        "Invalid selected structure approvals",
    )
    for kind, source in (("question_labels", keys["questions"]), ("edge_labels", keys["edges"])):
        require(isinstance(blog[kind], dict), "Invalid public labels")
        for internal, label in blog[kind].items():
            require(internal in source, "Unknown public label target")
            fields(label, "public translations")
            require(type(label["public"]) is bool, "Invalid label public flag")
            require(
                isinstance(label["translations"], dict) and set(label["translations"]) <= {"ko", "en"},
                "Invalid label languages",
            )
            for value in label["translations"].values():
                text(value)
    for sid in blog["series"]:
        require(sid not in used and sid not in private, "Series ID conflicts with another identity")
        used.add(sid)
    assets = {}
    for doc in state["documents"].values():
        for pair in doc["publication_pairs"].values():
            for asset in pair["attachments"]:
                require(
                    asset["id"] not in used and asset["id"] not in private, "Asset ID conflicts with another identity"
                )
                require(asset["id"] not in assets or assets[asset["id"]] == asset, "Conflicting public attachment ID")
                assets[asset["id"]] = asset
