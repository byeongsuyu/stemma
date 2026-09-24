"""Translate Studio records into the smaller contracts understood by graph consumers.

This is the dependency boundary: the core never needs to understand Studio JSON."""

from stemma_graph import Genealogy, Node, RevisionRef, Succession


def to_genealogy(state):
    """Discard storage, title, and publication fields and build a validated core graph."""
    return Genealogy(
        tuple(
            Node(
                docid,
                tuple(r["id"] for r in doc["revisions"]),
                tuple(doc["questions"]),
                doc["state"] == "confirmed",
                doc["archived"],
            )
            for docid, doc in state["documents"].items()
        ),
        tuple(state["questions"]),
        tuple(
            Succession(
                e["id"],
                RevisionRef(e["parent"], e["parent_revision"]),
                RevisionRef(e["child"], e["child_revision"]),
                tuple(e["questions"]),
                e["change_note"],
                e["state"] == "confirmed",
            )
            for e in state["edges"]
        ),
    )
