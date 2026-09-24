"""Explicit, loss-preserving conversion of Studio metadata to schema version 4."""

import copy

from stemma_graph import GraphError

from .blog import document_fields, empty_blog, require


def upgrade(state):
    """Group legacy question edges by document pair; refuse incompatible approvals.

    Revision references, approval and publication must agree before edges can merge.
    Different notes are retained with their original scopes, not silently discarded.
    Existing approvals never imply an archived document. The repository preserves
    the complete source JSON before the first save in the new schema.
    """
    result = copy.deepcopy(state)
    if result.get("schema_version") == 4:
        return result
    if result.get("schema_version") == 3:
        require("blog" not in result, "Legacy state already contains blog metadata")
        for doc in result["documents"].values():
            require(
                not any(k in doc for k in ("language_variants", "variant_reviews", "publication_pairs")),
                "Legacy document already contains blog metadata",
            )
            legacy = doc["publication"]
            require(set(legacy) == {"published", "revision"}, "Invalid legacy publication")
            doc.update(document_fields(legacy))
        result["blog"] = empty_blog()
        result["schema_version"] = 4
        return result
    if result.get("schema_version") == 2:
        for doc in result["documents"].values():
            doc["archived"] = False
        result["schema_version"] = 3
        return upgrade(result)
    if result.get("schema_version") != 1:
        raise GraphError("Unsupported Studio schema version")
    groups = {}
    for edge in result["edges"]:
        groups.setdefault((edge["parent"], edge["child"]), []).append(edge)
    edges = []
    for group in groups.values():
        first = copy.deepcopy(group[0])
        for field in ("parent_revision", "child_revision", "state", "public"):
            if any(e[field] != first[field] for e in group):
                raise GraphError("Legacy parallel edges require review: " + first["id"])
        first["questions"] = sorted({e["question"] for e in group})
        if len({e["change_note"] for e in group}) > 1:
            first["change_note"] = "\n\n".join("[" + e["question"] + "] " + e["change_note"] for e in group)
        if len(group) > 1:
            first["legacy_edge_ids"] = [e["id"] for e in group]
        del first["question"]
        edges.append(first)
    result["edges"] = edges
    result["schema_version"] = 2
    return upgrade(result)
