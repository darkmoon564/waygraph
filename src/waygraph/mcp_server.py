"""Typed MCP cursor tools; one process owns the Relate writer."""
from __future__ import annotations

import os
from typing import Any, Callable
from uuid import uuid4

import relate
from mcp.server.fastmcp import FastMCP

from .cursor import Cursor
from .graph import Graph, GraphError
from .shortcuts import learn, reuse

mcp = FastMCP("Waygraph")
_graph: Graph | None = None
_cursors: dict[str, Cursor] = {}


def graph() -> Graph:
    global _graph
    if _graph is None:
        _graph = Graph(os.environ.get("WAYGRAPH_DB", "data/relate/pilot"))
    return _graph


def _cursor(session: str) -> Cursor:
    if not isinstance(session, str) or not session or len(session) > 128:
        raise GraphError("session must contain 1-128 characters", "INVALID_ARGUMENT")
    cursor = _cursors.get(session)
    if cursor is None:
        raise GraphError(f"No active walk for session {session!r}", "CURSOR_NOT_STARTED")
    return cursor


def _invoke(operation: Callable[[], Any]) -> dict[str, Any]:
    trace_id = uuid4().hex
    try:
        data = operation()
        return {"ok": True, "data": data, "error": None, "trace_id": trace_id}
    except GraphError as exc:
        return {"ok": False, "data": None, "error": {"code": exc.code, "message": str(exc)}, "trace_id": trace_id}
    except ValueError as exc:
        return {"ok": False, "data": None, "error": {"code": "INVALID_ARGUMENT", "message": str(exc)}, "trace_id": trace_id}
    except relate.Error as exc:
        return {"ok": False, "data": None, "error": {"code": "DATABASE_UNAVAILABLE", "message": str(exc)[:500]}, "trace_id": trace_id}


@mcp.tool()
def start_walk(session: str, origin: str, max_hops: int = 8) -> dict:
    """Start a walk; result includes only the current node's offered outgoing edges."""
    def operation() -> dict:
        if not session or len(session) > 128:
            raise GraphError("session must contain 1-128 characters", "INVALID_ARGUMENT")
        cursor = Cursor(graph(), origin, max_hops=max_hops)
        _cursors[session] = cursor
        return cursor.inspect()
    return _invoke(operation)


@mcp.tool()
def inspect_walk(session: str) -> dict:
    """Refresh the bounded list of edges that may be followed from this cursor."""
    return _invoke(lambda: _cursor(session).inspect())


@mcp.tool()
def follow_edge(session: str, edge_id: str) -> dict:
    """Follow an edge offered by the latest inspection, then inspect the destination."""
    return _invoke(lambda: _cursor(session).follow(edge_id))


@mcp.tool()
def backtrack(session: str) -> dict:
    """Undo one traversal step and refresh the available edges."""
    return _invoke(lambda: _cursor(session).backtrack())


@mcp.tool()
def get_walk(session: str) -> dict:
    """Return the ordered node and edge IDs visited so far."""
    return _invoke(lambda: _cursor(session).get_walk())


@mcp.tool()
def save_shortcut(session: str) -> dict:
    """Learn an evidence-bearing shortcut from the current walk."""
    def operation() -> dict:
        cursor = _cursor(session)
        return learn(graph(), cursor.nodes[0], cursor.current, cursor.edges, observation_id=cursor.walk_id)
    return _invoke(operation)


@mcp.tool()
def check_shortcut(shortcut_id: str) -> dict:
    """Validate shortcut evidence against current facts before reuse."""
    return _invoke(lambda: reuse(graph(), shortcut_id))


def main() -> None:
    try:
        mcp.run(transport="stdio")
    finally:
        if _graph is not None:
            _graph.close()


if __name__ == "__main__":
    main()
