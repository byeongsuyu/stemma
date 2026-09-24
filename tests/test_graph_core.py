"""Contract and independence tests for the reusable genealogy core.

The isolated-package test copies only stemma_graph and the example into a new
folder. The dependency test guards against accidentally importing Studio or I/O."""

import ast
import dataclasses
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from stemma_graph import Genealogy, GraphError, Node, RevisionRef, Succession

from stemma_studio.core.application import Studio
from stemma_studio.core.domain import confirm, empty_state
from stemma_studio.core.publication import project_public
from stemma_studio.core.repository import MemoryRepository


class CoreTests(unittest.TestCase):
    """Use synthetic graphs to verify semantics independently of the writing archive."""

    def setUp(self):
        self.a, self.b, self.c = (RevisionRef(d, "1") for d in ("a", "b", "c"))
        self.nodes = tuple(Node(d, ("1",), ("q", "other")) for d in ("a", "b", "c"))
        self.graph = Genealogy(
            self.nodes,
            ("q", "other"),
            (Succession("a-c", self.a, self.c, ("q",), "정리"), Succession("b-c", self.b, self.c, ("q",), "정리")),
        )

    def test_weak_component_crosses_directions_and_preserves_original_edges(self):
        graph = self.graph.add_node(Node("isolated", ("1",), ("q",)))
        before = graph.to_dict()
        groups = graph.connected_components(["a", "c", "isolated"])
        self.assertEqual([g["nodes"] for g in groups], [("a", "b", "c"), ("isolated",)])
        self.assertEqual(groups[0]["edges"], graph.edges)
        self.assertEqual(graph.to_dict(), before)
        self.assertEqual(graph.connected_components([]), ())
        with self.assertRaises(GraphError):
            graph.connected_components(["missing"])

    def test_core_does_not_need_paths_titles_or_publication(self):
        self.assertEqual(self.graph.view("q").terminals, ("c",))
        self.assertEqual(self.graph.view("other").terminals, ("a", "b", "c"))

    def test_reference_and_node_validation(self):
        for build in (
            lambda: RevisionRef("", "1"),
            lambda: Node("a", ()),
            lambda: Node("a", ("1", "1")),
            lambda: Node("a", ("1",), ("q", "q")),
            lambda: Genealogy(self.nodes + (self.nodes[0],), ("q", "other")),
            lambda: Genealogy(self.nodes, ("q",)),
        ):
            with self.assertRaises(GraphError):
                build()

    def test_unknown_revision_and_self_edge(self):
        for edge in (
            Succession("bad", self.a, RevisionRef("c", "2"), ("q",), "note"),
            Succession("bad", self.a, self.a, ("q",), "note"),
        ):
            with self.assertRaises(GraphError):
                self.graph.add_edge(edge)

    def test_proposals_not_active_and_confirm_immutable(self):
        node = Node("d", ("1", "2"), ("q",), False)
        graph = self.graph.add_node(node).add_edge(
            Succession("c-d", self.c, RevisionRef("d", "1"), ("q",), "note", False)
        )
        updated = graph.confirm_document("d", "2")
        self.assertEqual(graph.view("q").terminals, ("c",))
        self.assertEqual(updated.view("q").terminals, ("d",))
        self.assertEqual(updated.edges[-1].child.revision, "2")
        with self.assertRaises(dataclasses.FrozenInstanceError):
            updated.nodes = ()

    def test_cross_question_cycle_rejected(self):
        with self.assertRaises(GraphError):
            self.graph.add_edge(Succession("reverse", self.c, self.a, ("other",), "note", False))

    def test_traversal_and_local_slice(self):
        self.assertEqual(self.graph.ancestors("c", "q"), ("a", "b"))
        self.assertEqual(self.graph.descendants("a", "q"), ("c",))
        self.assertEqual(self.graph.neighborhood("a", "q", 1)["nodes"], ("a", "c"))
        self.assertEqual(self.graph.neighborhood("a", "q", 2)["nodes"], ("a", "b", "c"))
        with self.assertRaises(GraphError):
            self.graph.neighborhood("a", "q", -1)

    def test_long_chain_no_recursion_limit(self):
        nodes = tuple(Node(str(i), ("1",), ("q",)) for i in range(1200))
        edges = tuple(
            Succession(str(i), RevisionRef(str(i), "1"), RevisionRef(str(i + 1), "1"), ("q",), "n") for i in range(1199)
        )
        graph = Genealogy(nodes, ("q",), edges)
        self.assertEqual(graph.view("q").terminals, ("1199",))
        self.assertEqual(len(graph.ancestors("1199", "q")), 1199)

    def test_json_round_trip(self):
        self.assertEqual(Genealogy.from_dict(json.loads(json.dumps(self.graph.to_dict()))), self.graph)
        with self.assertRaises(GraphError):
            Genealogy.from_dict({"schema_version": 99})

    def test_input_containers_cannot_mutate_graph(self):
        nodes = list(self.nodes)
        graph = Genealogy(nodes, ["q", "other"])
        nodes.clear()
        self.assertEqual(len(graph.nodes), 3)

    def test_memory_repository_runs_complete_workflow(self):
        """Prove that workflow behavior does not require the file repository."""
        app = Studio(repository=MemoryRepository())
        state = empty_state()
        state["questions"]["q"] = {"text": "question?", "public": False, "representatives": []}
        state = app.create_draft(state, "a", "a", ["q"], "first", [], "note")
        state = confirm(state, "a")
        state = app.create_draft(state, "b", "b", ["q"], "second", [{"parent": "a", "question": "q"}], "note")
        state = confirm(state, "b")
        app.save(state)
        state = app.add_revision(state, "b", "edited", "note")
        self.assertEqual(app.load(), state)
        self.assertEqual(project_public(state), {"schema_version": 3, "documents": [], "genealogies": [], "series": []})

    def test_core_dependency_boundary(self):
        root = Path(__file__).resolve().parents[1] / "packages" / "stemma_graph" / "src" / "stemma_graph"
        allowed = {"dataclasses"}
        for path in root.glob("*.py"):
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    self.assertTrue(all(alias.name.split(".")[0] in allowed for alias in node.names), path.name)
                if isinstance(node, ast.ImportFrom) and not node.level:
                    self.assertIn(node.module.split(".")[0], allowed, path.name)
        # The core is lineage only; scoring or combined navigation layers belong elsewhere.
        self.assertEqual({p.name for p in root.glob("*.py")}, {"__init__.py", "contracts.py", "genealogy.py"})

    def test_package_alone_works_outside_project(self):
        """Prove that the graph package can run without any Studio code or data."""
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as folder:
            shutil.copytree(root / "packages/stemma_graph/src/stemma_graph", Path(folder) / "stemma_graph")
            shutil.copyfile(root / "packages/stemma_graph/examples/graph_only.py", Path(folder) / "demo.py")
            result = subprocess.run(
                [sys.executable, "-B", "demo.py"], cwd=folder, capture_output=True, text=True, check=True
            )
            output = json.loads(result.stdout)
            self.assertEqual(output["questions"]["question"]["terminals"], ["c"])
            self.assertEqual(output["questions"]["other"]["terminals"], ["b", "d"])
            self.assertEqual(output["component_of_d"], ["a", "b", "c", "d"])


if __name__ == "__main__":
    unittest.main()
