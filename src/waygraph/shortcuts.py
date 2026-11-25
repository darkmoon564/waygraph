"""Materialized shortcuts with evidence revalidation at read time."""
from __future__ import annotations

import hashlib
import json
from typing import Any
from uuid import uuid4

from .graph import Graph, GraphError

SEMANTIC_EDGE_PROPERTIES = frozenset({"anchor", "cell", "role"})
PROMOTION_THRESHOLD = 2


def fingerprint(edges: list[dict]) -> str:
    payload = {
        "version": 2,
        "edges": [
            {
                **{k: e[k] for k in ("id", "source", "target", "kind", "active")},
                "source_properties": {
                    key: e.get("source_properties", {})[key]
                    for key in sorted(SEMANTIC_EDGE_PROPERTIES)
                    if key in e.get("source_properties", {})
                },
            }
            for e in edges
        ],
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def verify_with_reason(graph: Graph, ids: list[str], origin: str, target: str) -> tuple[str | None, str | None]:
    proof, reason, _nodes = _verify_full(graph, ids, origin, target)
    return proof, reason


def _verify_full(graph: Graph, ids: list[str], origin: str, target: str) -> tuple[str | None, str | None, list[str]]:
    if not ids:
        return None, "EMPTY_PATH", []
    found = []
    nodes = [origin]
    current = origin
    for edge_id in ids:
        edge = graph.edge(edge_id)
        if not edge:
            return None, "DEPENDENCY_MISSING", []
        if edge["active"] is not True:
            return None, "DEPENDENCY_INACTIVE", []
        if edge["source"] != current:
            return None, "PATH_DISCONTINUITY", []
        found.append(edge)
        current = edge["target"]
        nodes.append(current)
    if current != target:
        return None, "ENDPOINT_MISMATCH", []
    return fingerprint(found), None, nodes


def verify(graph: Graph, ids: list[str], origin: str, target: str) -> str | None:
    proof, _reason = verify_with_reason(graph, ids, origin, target)
    return proof


def learn(graph: Graph, origin: str, target: str, edge_ids: list[str], *, observation_id: str | None = None) -> dict:
    observation_id = observation_id or uuid4().hex
    key = hashlib.sha256(json.dumps([origin, target, edge_ids]).encode()).hexdigest()[:24]
    with graph.transaction():
        proof, _reason, path_nodes = _verify_full(graph, edge_ids, origin, target)
        if proof is None:
            raise GraphError("Cannot learn shortcut: underlying walk is invalid", "PATH_DISCONTINUITY")
        edge_kinds = [graph.edge(eid)["kind"] for eid in edge_ids]  # type: ignore[index]
        rows = graph.query(
            "MATCH (s:DPShortcut {id:$id}) RETURN s.status AS status, "
            "coalesce(s.walk_count,s.uses,0) AS walk_count, coalesce(s.reuse_count,0) AS reuse_count, "
            "s.fingerprint AS fingerprint, s.observation_ids AS observation_ids",
            {"id": key},
        )
        existing = rows[0] if rows else None
        if existing and existing["status"] == "DISABLED":
            raise GraphError("Shortcut is disabled", "SHORTCUT_DISABLED")
        observations = list(existing.get("observation_ids") or []) if existing else []
        same_proof = existing is not None and existing.get("fingerprint") == proof
        duplicate = observation_id in observations
        reuse_count = int(existing.get("reuse_count") or 0) if existing and same_proof else 0
        if existing and existing["status"] == "STALE" and duplicate:
            raise GraphError("Start a new walk before relearning a stale shortcut", "PATH_DISCONTINUITY")
        if existing and existing["status"] == "VALID" and same_proof:
            walk_count = max(PROMOTION_THRESHOLD, existing["walk_count"])
            status = "VALID"
            observations = observations[:PROMOTION_THRESHOLD]
        elif existing and existing["status"] == "CANDIDATE" and same_proof and duplicate:
            walk_count = existing["walk_count"]
            status = "CANDIDATE"
        elif existing and existing["status"] == "CANDIDATE" and same_proof:
            walk_count = existing["walk_count"] + 1
            observations = (observations + [observation_id])[:PROMOTION_THRESHOLD]
            status = "VALID" if walk_count >= PROMOTION_THRESHOLD else "CANDIDATE"
        else:
            walk_count = 1
            observations = [observation_id]
            status = "CANDIDATE"
        graph.query(
            "MATCH (a:DPEntity {id:$src}), (b:DPEntity {id:$dst}) "
            "MERGE (s:DPShortcut {id:$id}) ON CREATE SET s.walk_count=0, s.reuse_count=0 "
            "SET s.origin=$src, s.target=$dst, s.evidence=$evidence, s.edge_kinds=$edge_kinds, "
            "s.path_nodes=$path_nodes, s.hop_count=$hop_count, s.fingerprint=$fingerprint, "
            "s.status=$status, s.validation_reason=null, s.walk_count=$walk_count, "
            "s.uses=$walk_count, s.reuse_count=$reuse_count, s.observation_ids=$observations "
            "MERGE (a)-[:DP_SHORTCUT_FROM]->(s) MERGE (s)-[:DP_SHORTCUT_TO]->(b)",
            {
                "src": origin,
                "dst": target,
                "id": key,
                "evidence": edge_ids,
                "edge_kinds": edge_kinds,
                "path_nodes": path_nodes,
                "hop_count": len(edge_ids),
                "fingerprint": proof,
                "status": status,
                "walk_count": walk_count,
                "reuse_count": reuse_count,
                "observations": observations,
            },
        )
    return {
        "id": key,
        "origin": origin,
        "target": target,
        "evidence": edge_ids,
        "edge_kinds": edge_kinds,
        "hop_count": len(edge_ids),
        "fingerprint": proof,
        "walk_count": walk_count,
        "reuse_count": reuse_count,
        "promotion_threshold": PROMOTION_THRESHOLD,
        "status": status,
        "promoted": status == "VALID",
    }


def reuse(graph: Graph, shortcut_id: str, *, record_use: bool = False) -> dict:
    rows = graph.query(
        "MATCH (s:DPShortcut {id:$id}) RETURN s.origin AS origin, s.target AS target, "
        "s.evidence AS evidence, s.fingerprint AS fingerprint, s.status AS status, "
        "s.validation_reason AS validation_reason, coalesce(s.reuse_count, 0) AS reuse_count",
        {"id": shortcut_id},
    )
    if not rows:
        raise GraphError(f"Unknown shortcut: {shortcut_id}", "SHORTCUT_NOT_FOUND")
    item = rows[0]
    evidence_ids = list(item["evidence"] or [])
    actual, reason, path_nodes = _verify_full(graph, evidence_ids, item["origin"], item["target"])
    if item["status"] == "DISABLED":
        reason = "SHORTCUT_DISABLED"
    elif item["status"] == "CANDIDATE" and actual is not None and actual == item["fingerprint"]:
        return {
            "id": shortcut_id,
            "valid": False,
            "origin": item["origin"],
            "target": item["target"],
            "evidence": [],
            "nodes": [],
            "fingerprint": item["fingerprint"],
            "status": "CANDIDATE",
            "reason": "PROMOTION_THRESHOLD_NOT_MET",
        }
    elif item["status"] == "STALE":
        reason = item.get("validation_reason") or reason or "SHORTCUT_STALE"
    elif actual is not None and actual != item["fingerprint"]:
        reason = "DEPENDENCY_CHANGED"
    valid = actual is not None and actual == item["fingerprint"] and item["status"] == "VALID"
    reuse_count = int(item.get("reuse_count") or 0)
    if not valid and item["status"] != "DISABLED" and not graph.read_only:
        graph.query(
            "MATCH (s:DPShortcut {id:$id}) SET s.status='STALE', s.validation_reason=$reason",
            {"id": shortcut_id, "reason": reason or "SHORTCUT_STALE"},
        )
    elif valid and record_use and not graph.read_only:
        reuse_count += 1
        graph.query(
            "MATCH (s:DPShortcut {id:$id}) SET s.reuse_count=$reuse_count",
            {"id": shortcut_id, "reuse_count": reuse_count},
        )
    status = "VALID" if valid else "DISABLED" if item["status"] == "DISABLED" else "STALE"
    return {
        "id": shortcut_id,
        "valid": valid,
        "origin": item["origin"],
        "target": item["target"],
        "evidence": evidence_ids if valid else [],
        "nodes": path_nodes if valid else [],
        "fingerprint": actual if valid else item["fingerprint"],
        "reuse_count": reuse_count,
        "status": status,
        "reason": None if valid else reason or "SHORTCUT_STALE",
    }


def list_shortcuts(
    graph: Graph,
    *,
    origin: str | None = None,
    target: str | None = None,
    include_non_valid: bool = False,
    validate: bool = False,
    limit: int = 25,
) -> list[dict[str, Any]]:
    """List learned shortcuts stored in Relate, optionally filtered by endpoints."""
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
        raise GraphError("limit must be an integer from 1 to 100", "INVALID_ARGUMENT")
    clauses = []
    params: dict[str, Any] = {}
    if origin:
        clauses.append("s.origin = $origin")
        params["origin"] = origin
    if target:
        clauses.append("s.target = $target")
        params["target"] = target
    if not include_non_valid:
        clauses.append("s.status = 'VALID'")
    where = ("WHERE " + " AND ".join(clauses) + " ") if clauses else ""
    rows = graph.query(
        f"MATCH (s:DPShortcut) {where}"
        "OPTIONAL MATCH (dst:DPEntity {id: s.target}) "
        "RETURN s.id AS shortcut_id, s.origin AS origin, s.target AS target, "
        "dst.title AS target_title, dst.source_labels AS target_labels, "
        "s.evidence AS evidence, s.edge_kinds AS edge_kinds, s.fingerprint AS fingerprint, "
        "s.status AS status, s.validation_reason AS validation_reason, "
        "coalesce(s.walk_count, s.uses, 0) AS walk_count, coalesce(s.reuse_count, 0) AS reuse_count "
        f"ORDER BY walk_count DESC, shortcut_id ASC LIMIT {limit}",
        params,
    )
    results = []
    for row in rows:
        evidence = list(row.get("evidence") or [])
        entry: dict[str, Any] = {
            "shortcut_id": row["shortcut_id"],
            "origin": row["origin"],
            "target": row["target"],
            "target_title": row.get("target_title") or row["target"],
            "target_labels": row.get("target_labels") or [],
            "hop_count": len(evidence),
            "edge_kinds": list(row.get("edge_kinds") or []),
            "evidence": evidence,
            "fingerprint": row["fingerprint"],
            "status": row["status"],
            "validation_reason": row.get("validation_reason"),
            "walk_count": int(row.get("walk_count") or 0),
            "reuse_count": int(row.get("reuse_count") or 0),
        }
        if validate:
            checked = reuse(graph, row["shortcut_id"], record_use=False)
            entry["status"] = checked["status"]
            entry["valid"] = checked["valid"]
            entry["validation_reason"] = checked["reason"]
        results.append(entry)
    return results
