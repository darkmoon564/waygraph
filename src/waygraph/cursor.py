"""Bounded cursor that follows only recently offered graph edges."""
from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4

from .graph import Graph, GraphError


MAX_HOPS = 32


@dataclass
class Cursor:
    graph: Graph
    current: str
    max_hops: int = 8
    nodes: list[str] = field(default_factory=list)
    edges: list[str] = field(default_factory=list)
    _offered_edges: dict[str, str] = field(default_factory=dict, init=False, repr=False)
    walk_id: str = field(default_factory=lambda: uuid4().hex, init=False)

    def __post_init__(self) -> None:
        if isinstance(self.max_hops, bool) or not isinstance(self.max_hops, int) or not 1 <= self.max_hops <= MAX_HOPS:
            raise GraphError(f"max_hops must be an integer from 1 to {MAX_HOPS}", "INVALID_ARGUMENT")
        if self.graph.node(self.current) is None:
            raise GraphError(f"Unknown start node: {self.current}", "NODE_NOT_FOUND")
        if not self.nodes:
            self.nodes.append(self.current)
        elif self.nodes[-1] != self.current or len(self.nodes) != len(self.edges) + 1:
            raise GraphError("Cursor walk history is inconsistent", "PATH_DISCONTINUITY")
        if len(self.edges) > self.max_hops:
            raise GraphError("Cursor walk already exceeds max_hops", "HOP_LIMIT_REACHED")

    def inspect(self) -> dict:
        current = self.graph.node(self.current)
        if current is None:
            self._offered_edges.clear()
            raise GraphError(f"Current node no longer exists: {self.current}", "NODE_NOT_FOUND")
        if len(self.edges) >= self.max_hops:
            neighbors = []
            self._offered_edges.clear()
        else:
            neighbors = self.graph.neighbors(self.current)
            self._offered_edges = {edge["edge_id"]: edge["node_id"] for edge in neighbors}
        return {
            "current": current,
            "neighbors": neighbors,
            "walk": list(self.nodes),
            "edges": list(self.edges),
            "hops": len(self.edges),
            "max_hops": self.max_hops,
            "walk_id": self.walk_id,
            "remaining_hops": self.max_hops - len(self.edges),
        }

    def get_walk(self) -> dict:
        return {
            "origin": self.nodes[0],
            "current": self.current,
            "nodes": list(self.nodes),
            "edges": list(self.edges),
            "hops": len(self.edges),
            "max_hops": self.max_hops,
            "walk_id": self.walk_id,
        }

    def follow(self, edge_id: str) -> dict:
        if len(self.edges) >= self.max_hops:
            raise GraphError("Walk reached its hop limit", "HOP_LIMIT_REACHED")
        offered_target = self._offered_edges.get(edge_id)
        if offered_target is None:
            raise GraphError(
                f"Edge {edge_id!r} was not offered by the latest inspection of {self.current!r}",
                "RELATIONSHIP_NOT_AVAILABLE",
            )

        # Recheck the source fact so a mutation after inspect cannot use a stale offer.
        current_edges = {edge["edge_id"]: edge for edge in self.graph.neighbors(self.current)}
        edge = current_edges.get(edge_id)
        if edge is None or edge["node_id"] != offered_target:
            self._offered_edges.clear()
            raise GraphError(f"Edge {edge_id!r} is no longer available from {self.current!r}", "RELATIONSHIP_NOT_AVAILABLE")

        self.current = edge["node_id"]
        self.edges.append(edge_id)
        self.nodes.append(self.current)
        self._offered_edges.clear()
        return self.inspect()

    def backtrack(self) -> dict:
        if not self.edges:
            raise GraphError("Already at walk origin", "PATH_DISCONTINUITY")
        self.edges.pop()
        self.nodes.pop()
        self.current = self.nodes[-1]
        if not self.edges:
            self.walk_id = uuid4().hex
        self._offered_edges.clear()
        return self.inspect()
