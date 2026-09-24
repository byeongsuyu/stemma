"""Shared value objects used by the portable graph package.

Read this module first: RevisionRef identifies text, Node participates in questions,
and Succession records the author-approved direction between documents.
These objects carry no file locations, rendering instructions, or publication policy."""

from dataclasses import dataclass


class GraphError(ValueError):
    """A caller-supplied graph violates a semantic invariant."""

    pass


def require(condition, message):
    if not condition:
        raise GraphError(message)


def identifier(value):
    require(isinstance(value, str) and bool(value.strip()), "Expected nonempty string identifier")


@dataclass(frozen=True, order=True)
class RevisionRef:
    """Identify one immutable revision of a document.

    Document identity survives editing; revision identity identifies the exact text.
    Ordering is lexical and exists for deterministic output, not historical chronology."""

    document: str
    revision: str

    def __post_init__(self):
        identifier(self.document)
        identifier(self.revision)


@dataclass(frozen=True)
class Node:
    """Describe only the document information needed to validate a lineage.

    A document may participate in several questions and retain several revisions.
    A draft node can be stored, but does not enter a confirmed question view.
    Archived ends future use globally; it does not remove any historical graph fact."""

    id: str
    revisions: tuple
    questions: tuple = ()
    confirmed: bool = True
    archived: bool = False

    def __post_init__(self):
        """Copy sequence inputs and validate local fields before a graph checks references."""
        identifier(self.id)
        # frozen=True prevents later assignment; copying also isolates caller-owned lists.
        object.__setattr__(self, "revisions", tuple(self.revisions))
        object.__setattr__(self, "questions", tuple(self.questions))
        require(bool(self.revisions), "Node requires at least one revision")
        for value in self.revisions + self.questions:
            identifier(value)
        require(len(set(self.revisions)) == len(self.revisions), "Duplicate revision")
        require(len(set(self.questions)) == len(self.questions), "Duplicate participation")
        require(type(self.confirmed) is bool, "Expected boolean confirmed")
        require(type(self.archived) is bool, "Expected boolean archived")
        require(not self.archived or self.confirmed, "Only confirmed documents can end use")


@dataclass(frozen=True)
class Succession:
    """Record parent -> child across one or more questions, with both text revisions pinned.

    The note describes what changed. Succession does not imply agreement.
    A proposed edge is valid data but does not retire its parent as a terminal."""

    id: str
    parent: RevisionRef
    child: RevisionRef
    questions: tuple
    note: str
    confirmed: bool = True

    def __post_init__(self):
        require(not isinstance(self.questions, str), "Questions must be a sequence, not a string")
        object.__setattr__(self, "questions", tuple(self.questions))
        require(bool(self.questions), "Succession requires a question scope")
        require(len(set(self.questions)) == len(self.questions), "Duplicate question scope")
        for value in (self.id, self.note) + self.questions:
            identifier(value)
        require(
            isinstance(self.parent, RevisionRef) and isinstance(self.child, RevisionRef), "Expected revision references"
        )
        require(type(self.confirmed) is bool, "Expected boolean confirmed")


@dataclass(frozen=True)
class GraphView:
    """Return the confirmed graph for one question, including its global boundaries.

    Nodes, roots, and terminals contain document IDs; edges contain Succession values.
    A terminal is structural, not an automatic declaration of a representative position."""

    question: str
    nodes: tuple
    edges: tuple
    roots: tuple
    terminals: tuple
