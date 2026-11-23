"""Stable question and gold-path generation from source graph facts."""
from __future__ import annotations

import hashlib
import json
from collections import deque
from pathlib import Path

from .graph import Graph, GraphError


def generate(graph: Graph, limit: int = 30, max_hops: int = 4) -> list[dict]:
    if limit < 1 or not 1 <= max_hops <= 8:
        raise ValueError("limit must be positive and max_hops must be between 1 and 8")
    snapshot_id = graph.snapshot_id()
    origins = graph.query("MATCH (n:DPEntity) RETURN n.id AS id ORDER BY id LIMIT 1000")
    by_origin: dict[str, list[dict]] = {}
    for origin in origins:
        start = origin["id"]
        start_node = graph.node(start)
        start_title = start_node["title"] if start_node else start
        queue = deque([(start, [], [start], [])])
        visited = {start}
        candidates = []
        seen_routes: set[tuple[tuple[str, str, str], ...]] = set()
        while queue:
            current, edges, nodes, kinds = queue.popleft()
            if len(edges) >= max_hops:
                continue
            for neighbor in graph.neighbors(current, limit=100_000):
                nxt = neighbor["node_id"]
                if nxt in visited:
                    continue
                visited.add(nxt)
                new_edges = edges + [neighbor["edge_id"]]
                new_nodes = nodes + [nxt]
                new_kinds = kinds + [neighbor["kind"]]
                if len(new_edges) >= 2:
                    route = _unique_route(graph, start, new_kinds, new_nodes[1:])
                    if route is not None:
                        route_signature = tuple((step["relationship_type"], step["destination_label"], step["destination_title"]) for step in route)
                    else:
                        route_signature = ()
                    if route is not None and route_signature not in seen_routes:
                        seen_routes.add(route_signature)
                        answer_node = graph.node(nxt)
                        answer_title = answer_node["title"] if answer_node else nxt
                        route_text = ", then ".join(
                            f"{step['relationship_type']} to {step['destination_label']} {step['destination_title']!r}"
                            for step in route
                        )
                        identity = json.dumps(
                            [snapshot_id, start, new_edges], separators=(",", ":"), ensure_ascii=False
                        )
                        question_id = "q_" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]
                        candidates.append({
                            "id": question_id,
                            "question_id": question_id,
                            "graph_snapshot_id": snapshot_id,
                            "question": (
                                f"Starting at {start_title!r} ({start}), follow {route_text}. "
                                "What is the exact graph node ID at the end of that route?"
                            ),
                            "origin": start,
                            "origin_title": start_title,
                            "answer": nxt,
                            "answer_title": answer_title,
                            "route": route,
                            "gold_edges": new_edges,
                            "gold_nodes": new_nodes,
                            "equivalence_rule": "exact_node_id",
                            "difficulty": {"hops": len(new_edges)},
                        })
                queue.append((nxt, new_edges, new_nodes, new_kinds))
                if len(candidates) >= 2:
                    break
            if len(candidates) >= 2:
                break
        if candidates:
            by_origin[start] = candidates
        if len(by_origin) >= limit:
            break

    questions = []
    for candidate_index in range(2):
        for start in by_origin:
            candidates = by_origin[start]
            if candidate_index < len(candidates):
                questions.append(candidates[candidate_index])
                if len(questions) >= limit:
                    return questions
    return questions


def _unique_route(graph: Graph, origin: str, kinds: list[str], targets: list[str]) -> list[dict[str, str]] | None:
    """Describe every hop so its type plus destination caption selects one node."""
    current = origin
    route = []
    for kind, target in zip(kinds, targets):
        node = graph.node(target)
        if node is None:
            return None
        labels = node["labels"]
        label = labels[0] if labels else "Entity"
        title = node["title"] or target
        matching_targets = {
            edge["node_id"]
            for edge in graph.neighbors(current, limit=100_000)
            if edge["kind"] == kind and edge["title"] == title and (not labels or edge["labels"] == labels)
        }
        if matching_targets != {target}:
            return None
        route.append({"relationship_type": kind, "destination_label": label, "destination_title": title})
        current = target
    return route


def oracle_path(graph: Graph, origin: str, edge_ids: list[str]) -> list[str]:
    """Resolve an ordered path from graph facts without using Cursor state."""
    if not edge_ids:
        raise GraphError("Gold path must contain at least one relationship", "PATH_DISCONTINUITY")
    nodes = [origin]
    current = origin
    for edge_id in edge_ids:
        edge = graph.edge(edge_id)
        if edge is None or edge["active"] is not True or edge["source"] != current:
            raise GraphError(f"Gold path is invalid at relationship {edge_id!r}", "PATH_DISCONTINUITY")
        current = edge["target"]
        nodes.append(current)
    return nodes


def freeze_question_set(graph: Graph, output: Path, *, limit: int = 30, pilot_count: int = 10) -> dict:
    """Write a deterministic pilot/held-out JSONL set and checksum manifest."""
    questions = generate(graph, limit=limit)
    if len(questions) < 2 or not 1 <= pilot_count < len(questions):
        raise ValueError("question set must contain at least two questions and a smaller positive pilot_count")
    snapshot_id = questions[0]["graph_snapshot_id"]
    if any(item["graph_snapshot_id"] != snapshot_id for item in questions):
        raise RuntimeError("Generated questions span multiple graph snapshots")

    pilot_ids = {
        item["question_id"]
        for item in sorted(
            questions,
            key=lambda item: hashlib.sha256(
                f"{snapshot_id}:{item['question_id']}".encode("utf-8")
            ).hexdigest(),
        )[:pilot_count]
    }
    records = [
        {**item, "split": "pilot" if item["question_id"] in pilot_ids else "held_out"}
        for item in questions
    ]
    payload = "".join(
        json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
        for item in records
    ).encode("utf-8")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(payload)
    manifest_path = output.with_name(output.stem + ".manifest.json")
    manifest = {
        "format": 1,
        "status": "draft_for_semantic_review",
        "question_file": output.name,
        "question_file_sha256": hashlib.sha256(payload).hexdigest(),
        "graph_snapshot_id": snapshot_id,
        "question_count": len(records),
        "pilot_count": sum(item["split"] == "pilot" for item in records),
        "held_out_count": sum(item["split"] == "held_out" for item in records),
        "split_rule": "ascending SHA-256 of graph_snapshot_id + ':' + question_id",
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return {**manifest, "manifest_file": str(manifest_path)}


def load_question_set(path: Path, *, expected_snapshot_id: str, split: str | None = None) -> list[dict]:
    """Load a frozen JSONL set only when its checksum and snapshot match."""
    manifest_path = path.with_name(path.stem + ".manifest.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload = path.read_bytes()
    if hashlib.sha256(payload).hexdigest() != manifest.get("question_file_sha256"):
        raise ValueError("Frozen question file checksum does not match its manifest")
    if manifest.get("graph_snapshot_id") != expected_snapshot_id:
        raise ValueError("Frozen question set targets a different graph snapshot")
    questions = [json.loads(line) for line in payload.decode("utf-8").splitlines() if line.strip()]
    if len(questions) != manifest.get("question_count"):
        raise ValueError("Frozen question count does not match its manifest")
    ids = [item.get("question_id") for item in questions]
    if any(not item_id for item_id in ids) or len(set(ids)) != len(ids):
        raise ValueError("Frozen question IDs must be present and unique")
    if any(item.get("graph_snapshot_id") != expected_snapshot_id for item in questions):
        raise ValueError("Question record targets a different graph snapshot")
    if sum(item.get("split") == "pilot" for item in questions) != manifest.get("pilot_count"):
        raise ValueError("Frozen pilot split count does not match its manifest")
    if sum(item.get("split") == "held_out" for item in questions) != manifest.get("held_out_count"):
        raise ValueError("Frozen held-out split count does not match its manifest")
    if split is not None and split not in {"pilot", "held_out"}:
        raise ValueError("split must be 'pilot' or 'held_out'")
    if split == "held_out" and manifest.get("status") != "reviewed":
        raise ValueError("Held-out questions are unavailable until semantic review is marked 'reviewed'")
    if split is not None:
        questions = [item for item in questions if item.get("split") == split]
    return questions
