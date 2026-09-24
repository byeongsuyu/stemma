"""Revision selection policy and the guarded public export boundary.

Publication is a Studio policy. The reusable graph core has no public flags."""

from .domain import validate


def project_public(state, planned_published_at=None, bodies=None):
    """Build an allowlisted prospective v3 payload without changing stored state.

    Bodies are verified by the application before injection. A caller must supply
    the planned release time explicitly; exporting never claims deployment success.
    """
    import copy

    from .blog import fields, require, text, timestamp
    from .disclosure import chronology_key, document_date, validate_snapshot
    from .domain import digest

    validate(state)
    config = state["blog"]
    documents = state["documents"]
    selected = {
        did: doc["publication_pairs"][doc["publication"]["selected_pair"]]
        for did, doc in documents.items()
        if doc["publication"]["selected_pair"] is not None
    }
    result = {"schema_version": 3, "documents": [], "genealogies": [], "series": []}
    if not selected:
        return result
    require(planned_published_at is not None, "Nonempty export requires an explicit planned publication time")
    timestamp(planned_published_at)
    require(bodies is not None and set(bodies) == set(selected), "Verified bilingual bodies required")
    identities = config["identities"]

    def public_id(kind, internal):
        require(internal in identities[kind], "Public identity missing; prepare identities locally first")
        value = identities[kind][internal]
        return value["id"] if kind == "documents" else value

    from .public_assets import asset_url, link_names

    for did, pair in selected.items():
        pid = public_id("documents", did)
        require(isinstance(bodies[did], dict) and set(bodies[did]) == {"ko", "en"}, "Both public bodies required")
        for lang, value in bodies[did].items():
            fields(value, "title summary body")
            variant = documents[did]["language_variants"][pair["variants"][lang]]
            text(value["body"])
            require(
                value["title"] == variant["title"]
                and value["summary"] == variant["summary"]
                and digest(value["body"]) == variant["body"]["sha256"],
                "Public body does not match approved pair",
            )
        publication = documents[did]["publication"]
        result["documents"].append(
            {
                "id": pid,
                "slug": identities["documents"][did]["slug"],
                "translations": copy.deepcopy(bodies[did]),
                "date": document_date(documents[did]),
                "first_published_at": publication["first_published_at"] or planned_published_at,
                "published_updated_at": (
                    publication["published_updated_at"]
                    if config["active_release"]
                    and config["releases"][config["active_release"]]["selections"].get(did)
                    == publication["selected_pair"]
                    else planned_published_at
                ),
                "assets": [
                    {
                        "id": a["id"],
                        "url": asset_url(a),
                        "media_type": a["media_type"],
                        # Only names the published text already contains. A name the
                        # body never mentions cannot be needed to resolve it, and
                        # private paths must not ride out in the payload.
                        "names": [
                            name
                            for name in link_names(documents[did], a["path"])
                            if any(name in value["body"] for value in bodies[did].values())
                        ],
                    }
                    for a in sorted(pair["attachments"], key=lambda a: a["id"])
                ],
            }
        )
    by_public_id = {identities["documents"][did]["id"]: documents[did] for did in selected}
    result["documents"].sort(key=lambda d: d["id"])
    result["documents"].sort(key=lambda d: chronology_key(by_public_id[d["id"]]), reverse=True)
    result["documents"].sort(key=lambda d: d["first_published_at"], reverse=True)

    months, approved_edges = {}, {}
    for aid in config["selected_structure_approvals"]:
        approval = config["structure_approvals"][aid]
        validate_snapshot(state, approval, live=True)
        for node in approval["nodes"]:
            did = node["document"]
            require(did not in months or months[did] == node["date"], "Conflicting structure dates")
            months[did] = node["date"]
        for edge in approval["edges"]:
            approved_edges[edge["id"]] = edge
    adjacency = {did: set() for did in set(months) | set(selected)}
    compatible = {}
    originals = {e["id"]: e for e in state["edges"]}
    for eid, edge in approved_edges.items():
        exact, allowed = True, True
        for end in ("parent", "child"):
            did = edge[end]
            if did not in selected:
                exact = False
                continue
            ordered = [r["id"] for r in documents[did]["revisions"]]
            current = ordered.index(selected[did]["base_revision"])
            historical = ordered.index(edge[end + "_revision"])
            allowed = allowed and current >= historical
            exact = exact and current == historical
        if not allowed:
            continue
        parent, child = edge["parent"], edge["child"]
        adjacency[parent].add(child)
        adjacency[child].add(parent)
        compatible[eid] = (edge, exact)

    for anchor in sorted(selected, key=lambda d: public_id("documents", d)):
        reached, frontier = {anchor}, [anchor]
        while frontier:
            current = frontier.pop()
            for neighbor in adjacency[current] - reached:
                reached.add(neighbor)
                frontier.append(neighbor)
        nodes = []
        for did in reached:
            node = {"id": public_id("documents", did), "kind": "public" if did in selected else "unpublished"}
            if did not in selected:
                node["month"] = months[did]["value"]
            nodes.append(node)
        edges = []
        for eid, (edge, exact) in compatible.items():
            if edge["parent"] not in reached:
                continue
            scopes = []
            for qid in edge["questions"]:
                label = config["question_labels"].get(qid)
                if state["questions"][qid]["public"] and label and label["public"] and label["translations"]:
                    scopes.append(
                        {"id": public_id("questions", qid), "translations": copy.deepcopy(label["translations"])}
                    )
            note = {}
            label = config["edge_labels"].get(eid)
            if (
                exact
                and originals[eid]["public"]
                and label
                and label["public"]
                and len(scopes) == len(edge["questions"])
            ):
                # Missing question wording in one language never reveals its common note there.
                note = {
                    lang: value
                    for lang, value in label["translations"].items()
                    if all(lang in q["translations"] for q in scopes)
                }
            edges.append(
                {
                    "id": public_id("edges", eid),
                    "parent": public_id("documents", edge["parent"]),
                    "child": public_id("documents", edge["child"]),
                    "questions": sorted(scopes, key=lambda q: q["id"]),
                    "change_note": note,
                }
            )
        result["genealogies"].append(
            {
                "document": public_id("documents", anchor),
                "scope_label": "approved_genealogy",
                "nodes": sorted(nodes, key=lambda n: n["id"]),
                "edges": sorted(edges, key=lambda e: e["id"]),
            }
        )
    for sid in config["series_order"]:
        series = config["series"][sid]
        members = [public_id("documents", did) for did in series["documents"] if did in selected]
        if series["public"] and members:
            result["series"].append(
                {
                    "id": sid,
                    "slug": series["slug"],
                    "translations": copy.deepcopy(series["translations"]),
                    "documents": members,
                }
            )
    return result
