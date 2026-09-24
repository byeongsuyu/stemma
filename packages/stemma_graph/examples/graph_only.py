"""Run a complete genealogy-only example: python3.12 -m examples.graph_only.

Only the portable package and the standard library are imported. The four
documents and two questions are synthetic and do not describe the real corpus."""

import json

from stemma_graph import Genealogy, Node, RevisionRef, Succession


def main():
    """Build a merge and a branch in different questions, then inspect each question view."""
    # Step 1: identify exact texts. No paths, titles, or publication flags are needed.
    a, b, c, d = (RevisionRef(doc, "r1") for doc in ("a", "b", "c", "d"))
    # Step 2: a document may take part in several questions; edges must stay within them.
    nodes = (
        Node("a", ("r1",), ("question", "other")),
        Node("b", ("r1",), ("question", "other")),
        Node("c", ("r1",), ("question",)),
        Node("d", ("r1",), ("other",)),
    )
    # Step 3: A and B merge into C for one question; A also branches to D for another.
    edges = (
        Succession("a-c", a, c, ("question",), "두 글을 이어 씀"),
        Succession("b-c", b, c, ("question",), "두 글을 이어 씀"),
        Succession("a-d", a, d, ("other",), "다른 질문으로 갈라짐"),
    )
    graph = Genealogy(nodes, ("question", "other"), edges)
    # Step 4: serialize and reconstruct without a Studio storage adapter; validation reruns.
    graph = Genealogy.from_dict(json.loads(json.dumps(graph.to_dict())))
    # Step 5: roots/terminals are computed per question. B is past in one and current in the other.
    views = {q: graph.view(q) for q in graph.questions}
    print(
        json.dumps(
            {
                "questions": {q: {"roots": v.roots, "terminals": v.terminals} for q, v in views.items()},
                "ancestors_of_c": graph.ancestors("c", "question"),
                "descendants_of_a_in_other": graph.descendants("a", "other"),
                "component_of_d": graph.connected_components(["d"])[0]["nodes"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
