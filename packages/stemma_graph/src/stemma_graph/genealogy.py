"""Validate and query immutable, question-scoped document lineage.

Construction enforces invariants once for each new value. Read queries filter to
confirmed relationships; add/confirm operations build a new validated value.
There is no database, file access, publication policy, or UI dependency here."""

from dataclasses import asdict, dataclass, replace

from .contracts import GraphView, Node, RevisionRef, Succession, identifier, require


@dataclass(frozen=True)
class Genealogy:
    """Hold all document nodes and question-labeled succession edges.

    Each document pair has at most one edge, carrying a set of question scopes.
    The union of all scopes must be acyclic, including proposed edges."""

    nodes: tuple
    questions: tuple
    edges: tuple = ()

    def __post_init__(self):
        """Validate local membership, edge references, uniqueness, and the global DAG."""
        for field in ("nodes", "questions", "edges"):
            object.__setattr__(self, field, tuple(getattr(self, field)))
        for q in self.questions:
            identifier(q)
        require(len(set(self.questions)) == len(self.questions), "Duplicate question")
        require(all(isinstance(n, Node) for n in self.nodes), "Expected nodes")
        nodes = {n.id: n for n in self.nodes}
        require(len(nodes) == len(self.nodes), "Duplicate node")
        for n in self.nodes:
            require(set(n.questions) <= set(self.questions), "Unknown question")
        # A relationship is unique by document pair, regardless of its question scopes.
        ids, pairs = set(), set()
        adjacency = {n: set() for n in nodes}
        for e in self.edges:
            require(isinstance(e, Succession), "Expected succession")
            require(e.id not in ids, "Duplicate edge ID")
            ids.add(e.id)
            require(e.parent.document != e.child.document, "Self succession is not allowed")
            require(set(e.questions) <= set(self.questions), "Unknown question")
            for ref in (e.parent, e.child):
                require(ref.document in nodes, "Unknown edge endpoint")
                n = nodes[ref.document]
                require(ref.revision in n.revisions, "Unknown edge revision")
                require(set(e.questions) <= set(n.questions), "Endpoint must participate in every scope")
                require(not e.confirmed or n.confirmed, "Confirmed edge needs confirmed endpoints")
            pair = (e.parent.document, e.child.document)
            require(pair not in pairs, "Only one succession per document pair is allowed")
            pairs.add(pair)
            # Question overlap never creates another edge between this document pair.
            adjacency[e.parent.document].add(e.child.document)
        # Kahn traversal avoids recursion limits on long corpora. Proposals also must be acyclic.
        degree = {n: 0 for n in nodes}
        for children in adjacency.values():
            for child in children:
                degree[child] += 1
        # Repeatedly remove nodes with no remaining predecessors. A cycle leaves
        # nodes that can never become ready, so the visited count will be too small.
        ready = [n for n, d in degree.items() if d == 0]
        count = 0
        while ready:
            n = ready.pop()
            count += 1
            for child in adjacency[n]:
                degree[child] -= 1
                if degree[child] == 0:
                    ready.append(child)
        require(count == len(nodes), "Genealogy must be acyclic")

    def view(self, question):
        """Derive roots and terminals from confirmed edges for exactly one question.

        Sorting makes output deterministic; it does not rank importance or recency."""
        require(question in self.questions, "Unknown question")
        nodes = tuple(sorted(n.id for n in self.nodes if n.confirmed and question in n.questions))
        edges = tuple(sorted((e for e in self.edges if e.confirmed and question in e.questions), key=lambda e: e.id))
        # Compute boundaries after filtering by question and confirmation state.
        # The same document can therefore be historical in one question and current in another.
        incoming = {e.child.document for e in edges}
        outgoing = {e.parent.document for e in edges}
        return GraphView(
            question,
            nodes,
            edges,
            tuple(n for n in nodes if n not in incoming),
            tuple(n for n in nodes if n not in outgoing),
        )

    def _walk(self, document, question, direction, depth=None):
        """Traverse the confirmed question graph breadth-first.

        The starting document is excluded from the result. A finite depth counts hops;
        None means all reachable nodes. The visited set prevents duplicate work at merges."""
        view = self.view(question)
        require(document in view.nodes, "Document not in confirmed question graph")
        require(depth is None or (type(depth) is int and depth >= 0), "Invalid depth")
        adjacency = {n: set() for n in view.nodes}
        for e in view.edges:
            p, c = e.parent.document, e.child.document
            if direction in ("forward", "both"):
                adjacency[p].add(c)
            if direction in ("backward", "both"):
                adjacency[c].add(p)
        # frontier is one hop layer; subtracting seen handles converging branches.
        seen, frontier, level = {document}, {document}, 0
        while frontier and (depth is None or level < depth):
            frontier = set().union(*(adjacency[n] for n in frontier)) - seen
            seen.update(frontier)
            level += 1
        return tuple(sorted(seen - {document}))

    def ancestors(self, document, question):
        """Return every confirmed predecessor reachable within the question."""
        return self._walk(document, question, "backward")

    def descendants(self, document, question):
        """Return every confirmed successor reachable within the question."""
        return self._walk(document, question, "forward")

    def neighborhood(self, document, question, radius=1):
        """Return nearby nodes and the edges between them, walking in both directions.

        This is an induced local slice. Its boundary nodes are not necessarily the roots
        or terminals of the full question graph."""
        nodes = tuple(sorted((document,) + self._walk(document, question, "both", radius)))
        edges = tuple(e for e in self.view(question).edges if e.parent.document in nodes and e.child.document in nodes)
        # This is a local slice, not a claim that its boundary nodes are global roots/terminals.
        return {"question": question, "nodes": nodes, "edges": edges}

    def connected_components(self, documents, include_proposed=False):
        """Return complete weak components touched by the selected document IDs.

        Direction is ignored for reachability only; original edges retain direction.
        All questions participate. Archived nodes remain; unconfirmed edges are
        excluded by default, so a selected draft may be an isolated component.
        """
        require(not isinstance(documents, str), "Document IDs must be a sequence")
        selected = set(documents)
        adjacency = {node.id: set() for node in self.nodes}
        require(selected <= set(adjacency), "Unknown document")
        edges = tuple(e for e in self.edges if include_proposed or e.confirmed)
        for edge in edges:
            parent, child = edge.parent.document, edge.child.document
            adjacency[parent].add(child)
            adjacency[child].add(parent)
        visited, result = set(), []
        for start in sorted(selected):
            if start in visited:
                continue
            component, frontier = {start}, [start]
            while frontier:
                current = frontier.pop()
                for neighbor in adjacency[current] - component:
                    component.add(neighbor)
                    frontier.append(neighbor)
            visited.update(component)
            result.append(
                {"nodes": tuple(sorted(component)), "edges": tuple(e for e in edges if e.parent.document in component)}
            )
        return tuple(result)

    def add_node(self, node):
        """Return a new graph with this node; validation runs again during replacement."""
        return replace(self, nodes=self.nodes + (node,))

    def add_edge(self, edge):
        """Return a new graph with this relationship, rejecting invalid references or cycles."""
        parent = next((n for n in self.nodes if n.id == edge.parent.document), None)
        require(parent is not None and not parent.archived, "Archived document cannot be a new parent")
        return replace(self, edges=self.edges + (edge,))

    def set_archived(self, document, archived=True):
        """Explicitly end or restore future use without changing historical lineage."""
        require(any(n.id == document for n in self.nodes), "Unknown document")
        require(type(archived) is bool, "Expected boolean archived")
        return replace(self, nodes=tuple(replace(n, archived=archived) if n.id == document else n for n in self.nodes))

    def available_documents(self):
        """Return document IDs eligible for new use, independently of question terminals."""
        return tuple(sorted(n.id for n in self.nodes if not n.archived))

    def confirm_document(self, document, revision, archive_parents=()):
        """Confirm a document and its incoming proposals at the selected revision.

        Newly confirmed edges pin the chosen child revision. Already confirmed edges keep
        the historical revision they originally referenced. The input graph is unchanged."""
        node = next((n for n in self.nodes if n.id == document), None)
        require(node is not None and revision in node.revisions, "Unknown document/revision")
        require(not node.archived, "Restore an archived document before confirming new use")
        require(not isinstance(archive_parents, str), "Parent IDs must be a sequence")
        archive_parents = tuple(archive_parents)
        require(len(set(archive_parents)) == len(archive_parents), "Duplicate archive parent")
        incoming = tuple(e for e in self.edges if e.child.document == document)
        require(
            set(archive_parents) <= {e.parent.document for e in incoming}, "Can only archive direct succession parents"
        )
        archived = {n.id for n in self.nodes if n.archived}
        require(
            not any(not e.confirmed and e.parent.document in archived for e in incoming),
            "Archived document cannot be used by a pending succession; restore it first",
        )
        # dataclasses.replace constructs a new instance and re-runs __post_init__,
        # so confirmation cannot bypass reference or cycle validation.
        return replace(
            self,
            nodes=tuple(
                replace(n, confirmed=True)
                if n.id == document
                else replace(n, archived=True)
                if n.id in archive_parents
                else n
                for n in self.nodes
            ),
            edges=tuple(
                replace(e, confirmed=True, child=RevisionRef(document, revision) if not e.confirmed else e.child)
                if e.child.document == document
                else e
                for e in self.edges
            ),
        )

    def to_dict(self):
        """Produce detached, JSON-serializable values with an explicit schema version."""
        return {"schema_version": 3, **asdict(self)}

    @classmethod
    def from_dict(cls, data):
        """Rebuild value objects from decoded JSON and run constructor validation."""
        require(data.get("schema_version") in (2, 3), "Unsupported genealogy schema")
        if data["schema_version"] == 3:
            require(all("archived" in n for n in data["nodes"]), "Missing document use state")
        return cls(
            tuple(Node(**n) for n in data["nodes"]),
            tuple(data["questions"]),
            tuple(
                Succession(**{**e, "parent": RevisionRef(**e["parent"]), "child": RevisionRef(**e["child"])})
                for e in data["edges"]
            ),
        )
