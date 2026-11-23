"""Deterministic shortcut invalidation matrix on isolated synthetic graphs."""
from __future__ import annotations

from collections.abc import Callable

from .graph import Graph
from .shortcuts import learn, reuse


PATH = ["e1", "e2", "e3"]
ORIGIN = "python"
TARGET = "transactions"


def run_matrix() -> dict:
    cases: list[tuple[str, Callable[[Graph], None], bool, str | None]] = [
        ("disable_dependency", lambda graph: graph.disable_edge("e2"), False, "DEPENDENCY_INACTIVE"),
        ("delete_dependency", lambda graph: graph.delete_edge("e2"), False, "DEPENDENCY_MISSING"),
        ("change_endpoint", lambda graph: graph.retarget_edge("e3", target="cypher"), False, "ENDPOINT_MISMATCH"),
        ("change_type", lambda graph: graph.set_edge_kind("e2", "CONNECTS_DIFFERENTLY"), False, "DEPENDENCY_CHANGED"),
        ("change_relevant_property", lambda graph: graph.update_edge_property("e2", "role", "reader"), False, "DEPENDENCY_CHANGED"),
        ("change_irrelevant_property", lambda graph: graph.update_edge_property("e2", "debug_note", "changed"), True, None),
        ("delete_intermediate_node", lambda graph: graph.delete_node("sdk"), False, "DEPENDENCY_MISSING"),
        ("break_continuity", lambda graph: graph.retarget_edge("e2", source="python"), False, "PATH_DISCONTINUITY"),
    ]
    results = []
    for name, mutate, expected_valid, expected_reason in cases:
        with Graph(":memory:") as graph:
            graph.seed()
            learned = learn(graph, ORIGIN, TARGET, PATH)
            learned = learn(graph, ORIGIN, TARGET, PATH)
            mutate(graph)
            observed = reuse(graph, learned["id"])
            passed = observed["valid"] is expected_valid and observed["reason"] == expected_reason
            results.append({
                "case": name,
                "expected_valid": expected_valid,
                "valid": observed["valid"],
                "expected_reason": expected_reason,
                "reason": observed["reason"],
                "passed": passed,
            })
    false_valid = sum(not item["expected_valid"] and item["valid"] for item in results)
    false_stale = sum(item["expected_valid"] and not item["valid"] for item in results)
    return {
        "mode": "deterministic_mutation_matrix_not_agent_benchmark",
        "count": len(results),
        "false_valid_count": false_valid,
        "false_stale_count": false_stale,
        "passed": all(item["passed"] for item in results) and false_valid == 0,
        "results": results,
    }
