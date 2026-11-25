"""Bounded cursor that follows only recently offered graph edges or verified shortcuts."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from .graph import Graph, GraphError
from .shortcuts import list_shortcuts, reuse


MAX_HOPS = 32


@dataclass
class Cursor:
    graph: Graph
    current: str
    max_hops: int = 8
    nodes: list[str] = field(default_factory=list)
    edges: list[str] = field(default_factory=list)
    _offered_edges: dict[str, str] = field(default_factory=dict, init=False, repr=False)
    _offered_shortcuts: dict[str, dict[str, Any]] = field(default_factory=dict, init=False, repr=False)
    _step_sizes: list[int] = field(default_factory=list, init=False, repr=False)
    shortcut_jumps: list[dict[str, Any]] = field(default_factory=list, init=False)
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
        if self.edges and not self._step_sizes:
            self._step_sizes = [1] * len(self.edges)

    def inspect(self) -> dict[str, Any]:
        current = self.graph.node(self.current)
        if current is None:
            self._offered_edges.clear()
            self._offered_shortcuts.clear()
            raise GraphError(f"Current node no longer exists: {self.current}", "NODE_NOT_FOUND")
        remaining = self.max_hops - len(self.edges)
        if remaining <= 0:
            neighbors = []
            shortcuts = []
            self._offered_edges.clear()
            self._offered_shortcuts.clear()
        else:
            neighbors = self.graph.neighbors(self.current)
            self._offered_edges = {edge["edge_id"]: edge["node_id"] for edge in neighbors}
            raw_shortcuts = list_shortcuts(self.graph, origin=self.current, include_non_valid=False, validate=False)
            shortcuts = [
                {
                    "shortcut_id": item["shortcut_id"],
                    "target": item["target"],
                    "target_title": item["target_title"],
                    "target_labels": item["target_labels"],
                    "hop_count": item["hop_count"],
                    "edge_kinds": item["edge_kinds"],
                    "walk_count": item["walk_count"],
                    "reuse_count": item["reuse_count"],
                    "fingerprint": item["fingerprint"],
                }
                for item in raw_shortcuts
                if 1 <= item["hop_count"] <= remaining
            ]
            self._offered_shortcuts = {item["shortcut_id"]: item for item in shortcuts}
        return {
            "current": current,
            "neighbors": neighbors,
            "shortcuts": shortcuts,
            "walk": list(self.nodes),
            "edges": list(self.edges),
            "hops": len(self.edges),
            "cursor_steps": len(self._step_sizes),
            "shortcuts_used": list(self.shortcut_jumps),
            "max_hops": self.max_hops,
            "walk_id": self.walk_id,
            "remaining_hops": remaining,
        }

    def get_walk(self) -> dict[str, Any]:
        return {
            "origin": self.nodes[0],
            "current": self.current,
            "nodes": list(self.nodes),
            "edges": list(self.edges),
            "hops": len(self.edges),
            "cursor_steps": len(self._step_sizes),
            "shortcuts_used": list(self.shortcut_jumps),
            "max_hops": self.max_hops,
            "walk_id": self.walk_id,
        }

    def follow(self, edge_id: str) -> dict[str, Any]:
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
            self._offered_shortcuts.clear()
            raise GraphError(f"Edge {edge_id!r} is no longer available from {self.current!r}", "RELATIONSHIP_NOT_AVAILABLE")

        self.current = edge["node_id"]
        self.edges.append(edge_id)
        self.nodes.append(self.current)
        self._step_sizes.append(1)
        self._offered_edges.clear()
        self._offered_shortcuts.clear()
        return self.inspect()

    def take_shortcut(self, shortcut_id: str) -> dict[str, Any]:
        """Validate a promoted shortcut fail-closed and advance the cursor in one step."""
        if len(self.edges) >= self.max_hops:
            raise GraphError("Walk reached its hop limit", "HOP_LIMIT_REACHED")
        offered = self._offered_shortcuts.get(shortcut_id)
        if offered is None:
            raise GraphError(
                f"Shortcut {shortcut_id!r} was not offered by the latest inspection of {self.current!r}",
                "SHORTCUT_NOT_FOUND",
            )
        checked = reuse(self.graph, shortcut_id, record_use=True)
        if not checked["valid"]:
            self._offered_shortcuts.pop(shortcut_id, None)
            reason = checked["reason"] or "SHORTCUT_STALE"
            raise GraphError(
                f"Shortcut {shortcut_id!r} failed live dependency verification ({reason}); inspect and follow live edges instead",
                "SHORTCUT_STALE",
            )
        evidence_edges = list(checked["evidence"])
        path_nodes = list(checked["nodes"])
        if not evidence_edges or len(path_nodes) != len(evidence_edges) + 1 or path_nodes[0] != self.current:
            self._offered_shortcuts.pop(shortcut_id, None)
            raise GraphError(f"Shortcut {shortcut_id!r} origin does not match cursor node {self.current!r}", "PATH_DISCONTINUITY")
        if len(self.edges) + len(evidence_edges) > self.max_hops:
            raise GraphError("Shortcut traversal would exceed max_hops", "HOP_LIMIT_REACHED")

        step_index = len(self._step_sizes)
        self.edges.extend(evidence_edges)
        self.nodes.extend(path_nodes[1:])
        self.current = path_nodes[-1]
        self._step_sizes.append(len(evidence_edges))
        self.shortcut_jumps.append({
            "step_index": step_index,
            "shortcut_id": shortcut_id,
            "origin": path_nodes[0],
            "target": self.current,
            "edges": evidence_edges,
            "hops_compressed": len(evidence_edges),
            "fingerprint": checked["fingerprint"],
        })
        self._offered_edges.clear()
        self._offered_shortcuts.clear()
        return self.inspect()

    def backtrack(self) -> dict[str, Any]:
        if not self.edges:
            raise GraphError("Already at walk origin", "PATH_DISCONTINUITY")
        step_size = self._step_sizes.pop() if self._step_sizes else 1
        undone_step_index = len(self._step_sizes)
        for _ in range(step_size):
            self.edges.pop()
            self.nodes.pop()
        if self.shortcut_jumps and self.shortcut_jumps[-1].get("step_index") == undone_step_index:
            self.shortcut_jumps.pop()
        self.current = self.nodes[-1]
        if not self.edges:
            self.walk_id = uuid4().hex
        self._offered_edges.clear()
        self._offered_shortcuts.clear()
        return self.inspect()
