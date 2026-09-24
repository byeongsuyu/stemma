"""Reusable genealogy core. This package alone is sufficient; Python standard library only."""

from .contracts import GraphError, GraphView, Node, RevisionRef, Succession
from .genealogy import Genealogy

__all__ = ["GraphError", "RevisionRef", "Node", "Succession", "GraphView", "Genealogy"]
