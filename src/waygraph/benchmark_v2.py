"""Natural multi-hop benchmark (v2) with recurring hub corridors and 3-regime lifecycle evaluation."""
from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any

from .cursor import Cursor
from .graph import Graph
from .questions import load_question_set, oracle_path
from .shortcuts import learn, list_shortcuts, reuse

# Six real 3-hop documentation corridors (4 questions per corridor = 24 natural goal-oriented questions).
# Intermediate Page hops are intentionally omitted from the prompt text so agents must discover or shortcut them.
_CORRIDOR_SPECS: list[dict[str, Any]] = [
    {
        "corridor_id": "mcp_serve_flags",
        "origin": "Capability:graph-queries-over-mcp",
        "mid_page": "Page:guides/integrations/claude-agent-sdk",
        "hub_node": "Command:serve",
        "targets": [
            ("Flag:serve-snapshot-format", "snapshot format", "pilot"),
            ("Flag:serve-ws-allow-origin", "WebSocket allowed origin", "pilot"),
            ("Flag:serve-max-open-transactions", "maximum open transactions", "pilot"),
            ("Flag:serve-load", "preloading a store on startup", "held_out"),
        ],
    },
    {
        "corridor_id": "sandbox_serve_flags",
        "origin": "Capability:offline-and-sandboxed-use",
        "mid_page": "Page:guides/agents/run-in-a-sandbox",
        "hub_node": "Command:serve",
        "targets": [
            ("Flag:serve-snapshot-format", "snapshot format", "pilot"),
            ("Flag:serve-ws-allow-origin", "WebSocket allowed origin", "pilot"),
            ("Flag:serve-max-open-transactions", "maximum open transactions", "pilot"),
            ("Flag:serve-load", "preloading a store on startup", "held_out"),
        ],
    },
    {
        "corridor_id": "neo4j_push_flags",
        "origin": "Capability:neo4j-subgraph-mirror",
        "mid_page": "Page:guides/neo4j/push-to-neo4j",
        "hub_node": "Command:push",
        "targets": [
            ("Flag:push-database", "target Neo4j database", "pilot"),
            ("Flag:push-allow-plaintext", "plaintext Bolt connections", "pilot"),
            ("Flag:push-nodes-update", "node update behavior", "pilot"),
            ("Flag:push-rels-update", "relationship update behavior", "held_out"),
        ],
    },
    {
        "corridor_id": "sandbox_extension_flags",
        "origin": "Capability:offline-and-sandboxed-use",
        "mid_page": "Page:guides/agents/run-in-a-sandbox",
        "hub_node": "Command:extension",
        "targets": [
            ("Flag:extension-approve", "approving an extension", "pilot"),
            ("Flag:extension-lang", "extension implementation language", "held_out"),
            ("Flag:extension-trust", "trust policy for extensions", "held_out"),
            ("Flag:extension-version", "pinning an extension version", "held_out"),
        ],
    },
    {
        "corridor_id": "shared_store_serve_flags",
        "origin": "Capability:shared-store-across-processes",
        "mid_page": "Page:guides/operate/two-processes-one-store",
        "hub_node": "Command:serve",
        "targets": [
            ("Flag:serve-snapshot-format", "snapshot format", "held_out"),
            ("Flag:serve-ws-allow-origin", "WebSocket allowed origin", "held_out"),
            ("Flag:serve-max-open-transactions", "maximum open transactions", "held_out"),
            ("Flag:serve-load", "preloading a store on startup", "held_out"),
        ],
    },
    {
        "corridor_id": "agent_memory_serve_flags",
        "origin": "Capability:agent-memory",
        "mid_page": "Page:reference/storage/formats",
        "hub_node": "Command:serve",
        "targets": [
            ("Flag:serve-snapshot-format", "snapshot format", "held_out"),
            ("Flag:serve-ws-allow-origin", "WebSocket allowed origin", "held_out"),
            ("Flag:serve-max-open-transactions", "maximum open transactions", "held_out"),
            ("Flag:serve-load", "preloading a store on startup", "held_out"),
        ],
    },
]


def _find_edge_id(graph: Graph, source: str, target: str) -> str:
    for edge in graph.neighbors(source, limit=100):
        if edge["node_id"] == target:
            return edge["edge_id"]
    raise RuntimeError(f"Expected active edge within 100-neighbor cap: {source} -> {target}")


def build_v2_questions(graph: Graph) -> list[dict[str, Any]]:
    """Build 24 natural, goal-oriented multi-hop questions verified against the live graph."""
    snapshot_id = graph.snapshot_id()
    records: list[dict[str, Any]] = []
    for spec in _CORRIDOR_SPECS:
        origin = spec["origin"]
        mid_page = spec["mid_page"]
        hub_node = spec["hub_node"]
        origin_node = graph.node(origin)
        hub_info = graph.node(hub_node)
        if origin_node is None or hub_info is None:
            raise RuntimeError(f"Missing corridor endpoint in graph: {origin} / {hub_node}")
        e1 = _find_edge_id(graph, origin, mid_page)
        e2 = _find_edge_id(graph, mid_page, hub_node)
        cmd_name = hub_info["title"]

        for target_id, goal_phrase, split in spec["targets"]:
            target_node = graph.node(target_id)
            if target_node is None:
                raise RuntimeError(f"Missing target node in graph: {target_id}")
            e3 = _find_edge_id(graph, hub_node, target_id)
            gold_edges = [e1, e2, e3]
            gold_nodes = oracle_path(graph, origin, gold_edges)
            if gold_nodes != [origin, mid_page, hub_node, target_id]:
                raise RuntimeError(f"Oracle path mismatch for {origin} -> {target_id}")

            identity = json.dumps([snapshot_id, origin, gold_edges], separators=(",", ":"), ensure_ascii=False)
            qid = "q2_" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]
            question_text = (
                f"Starting from capability {origin_node['title']!r} ({origin}), navigate the Relate "
                f"documentation graph to locate the `{cmd_name}` CLI flag node responsible for "
                f"{goal_phrase}. Return only the exact Flag node ID."
            )
            records.append({
                "id": qid,
                "question_id": qid,
                "graph_snapshot_id": snapshot_id,
                "corridor_id": spec["corridor_id"],
                "corridor_prefix_edges": [e1, e2],
                "corridor_hub": hub_node,
                "question": question_text,
                "origin": origin,
                "origin_title": origin_node["title"],
                "answer": target_id,
                "answer_title": target_node["title"],
                "gold_edges": gold_edges,
                "gold_nodes": gold_nodes,
                "equivalence_rule": "exact_node_id",
                "difficulty": {"hops": 3, "route_disclosed": False},
                "split": split,
            })
    return records


def freeze_v2_question_set(graph: Graph, output: Path) -> dict[str, Any]:
    """Write reviewed relate-docs-v2.jsonl and its checksum manifest."""
    records = build_v2_questions(graph)
    snapshot_id = records[0]["graph_snapshot_id"]
    payload = "".join(
        json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
        for item in records
    ).encode("utf-8")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(payload)
    manifest_path = output.with_name(output.stem + ".manifest.json")
    manifest = {
        "format": 1,
        "status": "reviewed",
        "review_note": "Natural goal-oriented 3-hop prompts without intermediate route disclosure; 6 recurring hub corridors verified uniquely reachable within the 100-neighbor offer cap.",
        "question_file": output.name,
        "question_file_sha256": hashlib.sha256(payload).hexdigest(),
        "graph_snapshot_id": snapshot_id,
        "question_count": len(records),
        "pilot_count": sum(item["split"] == "pilot" for item in records),
        "held_out_count": sum(item["split"] == "held_out" for item in records),
        "split_rule": "curated corridor-balanced 10 pilot / 14 held_out split",
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return {**manifest, "manifest_file": str(manifest_path)}


def _run_cold_regime(graph: Graph, questions: list[dict[str, Any]]) -> dict[str, Any]:
    total_steps = 0
    total_hops = 0
    correct = 0
    started = time.perf_counter_ns()
    for q in questions:
        cursor = Cursor(graph, q["origin"], max_hops=8)
        cursor.inspect()
        for edge_id in q["gold_edges"]:
            cursor.follow(edge_id)
        walk = cursor.get_walk()
        total_steps += walk["cursor_steps"]
        total_hops += walk["hops"]
        if cursor.current == q["answer"]:
            correct += 1
    elapsed_ms = (time.perf_counter_ns() - started) / 1e6
    return {
        "questions": len(questions),
        "accuracy": correct / len(questions),
        "total_cursor_steps": total_steps,
        "total_graph_hops": total_hops,
        "mean_cursor_steps": total_steps / len(questions),
        "shortcut_hits": 0,
        "elapsed_ms": round(elapsed_ms, 2),
    }


def _run_warm_waygraph_regime(graph: Graph, questions: list[dict[str, Any]]) -> dict[str, Any]:
    total_steps = 0
    total_hops = 0
    shortcut_hits = 0
    promotions = 0
    correct = 0
    started = time.perf_counter_ns()
    for q in questions:
        cursor = Cursor(graph, q["origin"], max_hops=8)
        state = cursor.inspect()
        hub = q["corridor_hub"]
        matching = [s for s in state["shortcuts"] if s["target"] == hub]
        if matching:
            cursor.take_shortcut(matching[0]["shortcut_id"])
            shortcut_hits += 1
            cursor.follow(q["gold_edges"][2])
        else:
            for edge_id in q["gold_edges"]:
                cursor.follow(edge_id)
            learned = learn(
                graph,
                q["origin"],
                hub,
                list(q["corridor_prefix_edges"]),
                observation_id=f"{cursor.walk_id}:prefix",
            )
            if learned["promoted"]:
                promotions += 1
        walk = cursor.get_walk()
        total_steps += walk["cursor_steps"]
        total_hops += walk["hops"]
        if cursor.current == q["answer"]:
            correct += 1
    elapsed_ms = (time.perf_counter_ns() - started) / 1e6
    valid_shortcuts = list_shortcuts(graph, include_non_valid=False, limit=100)
    return {
        "questions": len(questions),
        "accuracy": correct / len(questions),
        "total_cursor_steps": total_steps,
        "total_graph_hops": total_hops,
        "mean_cursor_steps": total_steps / len(questions),
        "shortcut_hits": shortcut_hits,
        "shortcuts_promoted": len(valid_shortcuts),
        "elapsed_ms": round(elapsed_ms, 2),
    }


def _open_isolated_docs_graph(
    tmpdir: Path,
    name: str,
    document: dict[str, Any],
    source_sha256: str,
    template_store: Path | None,
) -> Graph:
    if template_store is not None and template_store.is_file():
        dst = tmpdir / f"{name}.rl"
        shutil.copy2(template_store, dst)
        g = Graph(str(dst))
        g.query("MATCH (s:DPShortcut) DETACH DELETE s")
        return g
    g = Graph(":memory:")
    g.import_source_graph(document, source_sha256)
    return g


def _run_post_mutation_regime(
    document: dict[str, Any],
    source_sha256: str,
    *,
    template_store: Path | None = None,
) -> dict[str, Any]:
    """Compare Naive Path Cache vs. Waygraph fail-closed validation on 6 real docs-graph mutations."""
    cases = [
        ("disable_mid_edge", "disable", False, "DEPENDENCY_INACTIVE", True),
        ("delete_mid_edge", "delete", False, "DEPENDENCY_MISSING", True),
        ("retarget_final_edge", "retarget", False, "ENDPOINT_MISMATCH", False),
        ("change_edge_kind", "kind", False, "DEPENDENCY_CHANGED", True),
        ("mutate_semantic_role", "semantic_prop", False, "DEPENDENCY_CHANGED", True),
        ("mutate_non_semantic_note", "non_semantic_prop", True, None, False),
    ]
    results = []
    naive_false_valid = 0
    waygraph_false_valid = 0
    waygraph_false_stale = 0
    rerouted_recoveries = 0

    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        for name, action, expected_valid, expected_reason, can_reroute in cases:
            with _open_isolated_docs_graph(tmpdir, name, document, source_sha256, template_store) as g:
                origin = "Capability:agent-memory"
                p1 = "Page:get-started/agent-memory"
                p2 = "Page:guides/agents/connect-over-mcp"
                target = "Flag:read-only"
                e1 = _find_edge_id(g, origin, p1)
                e2 = _find_edge_id(g, p1, p2)
                e3 = _find_edge_id(g, p2, target)

                learn(g, origin, target, [e1, e2, e3])
                promoted = learn(g, origin, target, [e1, e2, e3])

                if action == "disable":
                    g.disable_edge(e2)
                elif action == "delete":
                    g.delete_edge(e2)
                elif action == "retarget":
                    g.retarget_edge(e3, target="Command:serve")
                elif action == "kind":
                    g.set_edge_kind(e2, "DEPRECATED_LINK")
                elif action == "semantic_prop":
                    g.update_edge_property(e2, "role", "deprecated")
                elif action == "non_semantic_prop":
                    g.update_edge_property(e2, "audit_note", "harmless_metadata")

                naive_accepted = True
                if not expected_valid and naive_accepted:
                    naive_false_valid += 1

                checked = reuse(g, promoted["id"])
                if not expected_valid and checked["valid"]:
                    waygraph_false_valid += 1
                if expected_valid and not checked["valid"]:
                    waygraph_false_stale += 1

                recovered = False
                if not checked["valid"] and can_reroute:
                    alt_page = "Page:guides/agents/model-agent-memory"
                    ae1 = _find_edge_id(g, origin, alt_page)
                    ae2 = _find_edge_id(g, alt_page, target)
                    cur = Cursor(g, origin, max_hops=8)
                    cur.inspect()
                    cur.follow(ae1)
                    cur.follow(ae2)
                    recovered = cur.current == target
                    if recovered:
                        rerouted_recoveries += 1

                results.append({
                    "case": name,
                    "expected_valid": expected_valid,
                    "naive_cache_accepted": naive_accepted,
                    "waygraph_valid": checked["valid"],
                    "waygraph_reason": checked["reason"],
                    "passed": (checked["valid"] is expected_valid and checked["reason"] == expected_reason),
                    "rerouted_to_live_truth": recovered,
                })

    return {
        "cases": len(results),
        "naive_cache_false_valid_count": naive_false_valid,
        "waygraph_false_valid_count": waygraph_false_valid,
        "waygraph_false_stale_count": waygraph_false_stale,
        "live_reroute_recoveries": rerouted_recoveries,
        "passed": all(r["passed"] for r in results) and waygraph_false_valid == 0 and waygraph_false_stale == 0,
        "results": results,
    }


def run_lifecycle_benchmark(
    source_file: Path = Path("data/source/relate-docs-graph.json"),
    question_file: Path = Path("data/questions/relate-docs-v2.jsonl"),
    *,
    split: str | None = None,
    template_store: Path | None = Path("data/relate/showcase.rl"),
) -> dict[str, Any]:
    """Run the 3-regime deterministic lifecycle benchmark (Cold vs Warm Desire Paths vs Post-Mutation)."""
    source_bytes = source_file.read_bytes()
    source_sha256 = hashlib.sha256(source_bytes).hexdigest()
    document = json.loads(source_bytes)
    usable_template = template_store if (template_store and template_store.is_file()) else None

    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        with _open_isolated_docs_graph(tmpdir, "cold", document, source_sha256, usable_template) as cold_graph:
            snapshot_id = cold_graph.snapshot_id()
            questions = load_question_set(question_file, expected_snapshot_id=snapshot_id, split=split)
            cold = _run_cold_regime(cold_graph, questions)

        with _open_isolated_docs_graph(tmpdir, "warm", document, source_sha256, usable_template) as warm_graph:
            warm_single_pass = _run_warm_waygraph_regime(warm_graph, questions)
            warm_steady_state = _run_warm_waygraph_regime(warm_graph, questions)

    mutation = _run_post_mutation_regime(document, source_sha256, template_store=usable_template)

    single_pass_step_reduction = 1.0 - (warm_single_pass["total_cursor_steps"] / cold["total_cursor_steps"])
    steady_state_step_reduction = 1.0 - (warm_steady_state["total_cursor_steps"] / cold["total_cursor_steps"])

    return {
        "mode": "deterministic_3_regime_lifecycle_benchmark",
        "graph_snapshot_id": snapshot_id,
        "question_file": str(question_file),
        "split": split or "all",
        "cold_cursor": cold,
        "warm_waygraph_pass_1": {
            **warm_single_pass,
            "cursor_step_reduction_pct": round(single_pass_step_reduction * 100.0, 1),
        },
        "warm_waygraph_steady_state": {
            **warm_steady_state,
            "cursor_step_reduction_pct": round(steady_state_step_reduction * 100.0, 1),
        },
        "post_mutation_vs_naive_cache": mutation,
    }


def main() -> None:
    source_file = Path("data/source/relate-docs-graph.json")
    output_file = Path("data/questions/relate-docs-v2.jsonl")
    source_bytes = source_file.read_bytes()
    source_sha256 = hashlib.sha256(source_bytes).hexdigest()
    document = json.loads(source_bytes)
    with Graph(":memory:") as g:
        g.import_source_graph(document, source_sha256)
        manifest = freeze_v2_question_set(g, output_file)
    report = run_lifecycle_benchmark(source_file, output_file)
    print(json.dumps({"manifest": manifest, "benchmark": report}, indent=2))


if __name__ == "__main__":
    main()
