"""Pure Studio-specific document and workflow rules.

Functions return new state dictionaries and perform no file operations. Studio
adds titles, representative choices, revision descriptors, and publication state
around the minimal graph contract. Graph invariants are delegated to the core."""

import copy
import hashlib
import re

from stemma_graph import GraphError as ModelError

from ..locale import Message
from . import blog
from .adapters import to_genealogy


def digest(text):
    """Fingerprint UTF-8 text so an immutable snapshot can be checked on retrieval."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def empty_state():
    """Create a fresh Studio metadata container, without touching persistence."""
    return {"schema_version": 4, "questions": {}, "documents": {}, "edges": [], "blog": blog.empty_blog()}


def _require(condition, message):
    if not condition:
        raise ModelError(message)


def validate(state):
    """Check Studio metadata, then delegate lineage consistency to the graph constructor.

    This checks hash descriptors, not file contents. The repository checks actual
    bytes through verify_contents when loading or saving."""
    _require(state.get("schema_version") == 4, "Unsupported schema version")
    documents, questions = state["documents"], state["questions"]
    for qid, question in questions.items():
        _require(bool(qid) and bool(question["text"].strip()), "Question needs ID and text")
        _require(isinstance(question["public"], bool), "Question needs explicit public flag")
        _require(len(question["representatives"]) == len(set(question["representatives"])), "Duplicate representative")
        for docid in question["representatives"]:
            _require(docid in documents, "Unknown representative")
            _require(qid in documents[docid]["questions"], "Representative must participate")
            _require(documents[docid]["state"] == "confirmed", "Draft cannot represent a position")
    for docid, doc in documents.items():
        _require(re.fullmatch(r"[A-Za-z0-9_-]+", docid) is not None, "Invalid document ID")
        _require(doc["state"] in ("draft", "confirmed"), "Invalid document state")
        _require(type(doc.get("archived")) is bool, "Document needs explicit archived flag")
        _require(doc["kind"] in ("imported", "original"), "Invalid document kind")
        _require(bool(doc["title"].strip()), "Document needs a display title")
        _require(len(doc["questions"]) == len(set(doc["questions"])), "Duplicate question")
        _require(set(doc["questions"]) <= set(questions), "Unknown question")
        revisions = doc["revisions"]
        _require(bool(revisions), "Document needs a revision")
        ids = [rev["id"] for rev in revisions]
        _require(len(ids) == len(set(ids)), "Duplicate revision")
        _require(doc["current_revision"] in ids, "Unknown current revision")
        for rev in revisions:
            _require(len(rev["sha256"]) == 64, "Invalid revision hash")
            _require(bool(rev["path"]), "Revision needs path")
    for edge in state["edges"]:
        _require(edge["state"] in ("proposed", "confirmed"), "Invalid edge state")
        _require(type(edge["public"]) is bool, "Invalid public edge flag")
    # Construction delegates the graph invariants to their single source of truth.
    to_genealogy(state)
    blog.validate(state)


def active_edges(state, question=None):
    """Select confirmed Studio edge records, optionally within one question."""
    return [e for e in state["edges"] if e["state"] == "confirmed" and (question is None or question in e["questions"])]


def genealogy(state, question):
    """Adapt a core graph view and attach Studio representative metadata.

    Representative choices are not required by the reusable graph engine."""
    view = to_genealogy(state).view(question)
    representatives = state["questions"][question]["representatives"]
    return {
        "question": question,
        "nodes": list(view.nodes),
        "edges": copy.deepcopy(active_edges(state, question)),
        "roots": list(view.roots),
        "terminals": list(view.terminals),
        "representatives": list(representatives),
        "archived": [d for d in view.nodes if state["documents"][d]["archived"]],
        "representatives_needing_review": [d for d in representatives if d not in view.terminals],
    }


def confirm(state, docid, archive_parents=()):
    """Return state with this document and its incoming succession proposals confirmed.

    The core handles revision pinning. This adapter copies those results back while
    preserving Studio-only fields such as public flags and change descriptions."""
    _require(docid in state["documents"], "Unknown document")
    revision = state["documents"][docid]["current_revision"]
    graph = to_genealogy(state).confirm_document(docid, revision, archive_parents)
    result = copy.deepcopy(state)
    result["documents"][docid]["state"] = "confirmed"
    for node in graph.nodes:
        result["documents"][node.id]["archived"] = node.archived
    by_id = {e.id: e for e in graph.edges}
    for edge in result["edges"]:
        updated = by_id[edge["id"]]
        edge["state"] = "confirmed" if updated.confirmed else "proposed"
        edge["child_revision"] = updated.child.revision
    validate(result)
    return result


def set_archived(state, docid, archived=True):
    """Change future-use eligibility without unpublishing or altering succession facts."""
    graph = to_genealogy(state).set_archived(docid, archived)
    result = copy.deepcopy(state)
    for node in graph.nodes:
        result["documents"][node.id]["archived"] = node.archived
    validate(result)
    return result


def set_representatives(state, question, docids):
    """Replace the author-selected representatives for one question, without publishing."""
    _require(question in state["questions"], "Unknown question")
    result = copy.deepcopy(state)
    result["questions"][question]["representatives"] = list(docids)
    validate(result)
    return result


def set_publication(state, docid, pair_id=None):
    """Select a reviewed bilingual pair locally, or clear the selection.

    Revision IDs no longer grant publication. Actual deployment remains separate.

    Retirement is enforced here rather than in an interface, because the editor and
    the command line both arrive at this decision and the rule must not depend on
    which one the author used. A retired document is never published anew: its
    argument was carried forward, so the successor is what gets published. One that
    is already selected or still live may be re-approved, and clearing is always
    allowed, which is what keeps a takedown possible after retirement.
    """
    _require(docid in state["documents"], "Unknown document")
    doc = state["documents"][docid]
    if pair_id is not None and doc["archived"]:
        active = state["blog"]["releases"].get(state["blog"]["active_release"])
        live = active["selections"] if active else {}
        _require(
            bool(doc["publication"]["selected_pair"]) or docid in live,
            Message("error.publish_archived"),
        )
    result = copy.deepcopy(state)
    result["documents"][docid]["publication"]["selected_pair"] = pair_id
    validate(result)
    return result


def create_draft(state, docid, title, questions, revision, parents):
    """Build a draft and its proposed incoming relationships without writing text.

    The application supplies a revision descriptor. Each parent entry supplies a
    document ID and question list; an optional change_note overrides the revision note.
    Parent revisions are captured now rather than silently following later edits."""
    _require(docid not in state["documents"], "Document already exists")
    note = revision["note"]
    result = copy.deepcopy(state)
    # Draft creation and public/representative selection are independent decisions.
    result["documents"][docid] = {
        "title": title,
        "kind": "original",
        "state": "draft",
        "archived": False,
        "questions": list(questions),
        "current_revision": revision["id"],
        "source": None,
        **blog.document_fields(),
        "revisions": [copy.deepcopy(revision)],
    }
    for parent in parents:
        _require(parent["parent"] in result["documents"], "Unknown parent")
        pid = parent["parent"]
        _require(not result["documents"][pid]["archived"], "Archived document cannot be a new parent")
        # Accept the original single-question call syntax, but persist only a scope list.
        scopes = parent.get("questions", [parent["question"]] if "question" in parent else [])
        _require(not isinstance(scopes, str), "Questions must be a sequence, not a string")
        result["edges"].append(
            {
                "id": "edge-" + digest(pid + "|" + docid)[:16],
                "parent": pid,
                "parent_revision": result["documents"][pid]["current_revision"],
                "child": docid,
                "child_revision": revision["id"],
                "questions": list(scopes),
                "change_note": parent.get("change_note", note),
                "state": "proposed",
                "public": False,
            }
        )
    validate(result)
    return result


def add_revision(state, docid, revision):
    """Append an expression-only revision while preserving document and edge identity.

    A changed position belongs in a new document. Existing public revision selection
    and historical edge references remain unchanged."""
    _require(docid in state["documents"], "Unknown document")
    result = copy.deepcopy(state)
    doc = result["documents"][docid]
    _require(doc["kind"] == "original", "Imported snapshots are immutable; create a new document")
    _require(revision["sha256"] not in [r["sha256"] for r in doc["revisions"]], "Unchanged revision")
    doc["revisions"].append(copy.deepcopy(revision))
    # Do not move the public revision or historical edge references during a text edit.
    doc["current_revision"] = revision["id"]
    validate(result)
    return result
