"""Schema-aware normalization for the published Relate documentation graph."""
from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from typing import Any

SOURCE_URL = "https://relatedb.ai/docs/graph.json"
DATASET_ID = "relate-docs"


def normalize_source_graph(document: Any, source_sha256: str) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    """Validate the observed Relate docs graph schema and prepare stable records."""
    if not isinstance(document, dict):
        raise ValueError("Source graph must be a JSON object")
    if document.get("format") != 1 or document.get("kind") != "documentation":
        raise ValueError("Expected Relate documentation graph format 1")
    verified = _text(document.get("verified"), "verified")
    source_sha256 = _text(source_sha256, "source SHA-256")
    if len(source_sha256) != 64 or any(c not in "0123456789abcdef" for c in source_sha256.lower()):
        raise ValueError("source SHA-256 must contain 64 hexadecimal characters")
    raw_nodes = document.get("nodes")
    raw_relationships = document.get("relationships")
    if not isinstance(raw_nodes, list) or not isinstance(raw_relationships, list):
        raise ValueError("Source graph must contain nodes and relationships arrays")

    nodes: list[dict[str, Any]] = []
    node_ids: set[str] = set()
    for index, raw in enumerate(raw_nodes):
        where = f"nodes[{index}]"
        if not isinstance(raw, dict):
            raise ValueError(f"{where} must be an object")
        node_id = _text(raw.get("id"), f"{where}.id")
        labels = raw.get("labels")
        properties = raw.get("properties")
        if not isinstance(labels, list) or not labels or any(not isinstance(label, str) or not label for label in labels):
            raise ValueError(f"{where}.labels must be a non-empty array of strings")
        if not isinstance(properties, dict):
            raise ValueError(f"{where}.properties must be an object")
        _validate_properties(properties, f"{where}.properties")
        if node_id in node_ids:
            raise ValueError(f"Duplicate source node id: {node_id}")
        if not node_id.startswith(f"{labels[0]}:"):
            raise ValueError(f"{where}.id must use the documented Label:id form")
        node_ids.add(node_id)
        nodes.append({
            "id": node_id,
            "source_id": node_id.split(":", 1)[1],
            "labels": labels,
            "title": _caption(properties, labels, node_id),
            "properties": properties,
            "properties_json": _canonical_json(properties),
        })

    relationships: list[dict[str, Any]] = []
    duplicates: defaultdict[str, int] = defaultdict(int)
    for index, raw in enumerate(raw_relationships):
        where = f"relationships[{index}]"
        if not isinstance(raw, dict):
            raise ValueError(f"{where} must be an object")
        kind = _text(raw.get("type"), f"{where}.type")
        source = _text(raw.get("start"), f"{where}.start")
        target = _text(raw.get("end"), f"{where}.end")
        properties = raw.get("properties", {})
        if not isinstance(properties, dict):
            raise ValueError(f"{where}.properties must be an object")
        _validate_properties(properties, f"{where}.properties")
        if source not in node_ids or target not in node_ids:
            raise ValueError(f"{where} references a node absent from the source graph")
        canonical = _canonical_json({"type": kind, "start": source, "end": target, "properties": properties})
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        occurrence = duplicates[digest]
        duplicates[digest] += 1
        relationships.append({
            "id": f"relate-docs:{digest}:{occurrence}",
            "source": source,
            "target": target,
            "kind": kind,
            "properties": properties,
            "properties_json": _canonical_json(properties),
        })

    metadata = {
        "dataset_id": DATASET_ID,
        "source_url": SOURCE_URL,
        "source_sha256": source_sha256.lower(),
        "source_verified": verified,
    }
    return metadata, nodes, relationships


def _caption(properties: dict[str, Any], labels: list[str], fallback: str) -> str:
    for key in ("title", "heading", "term", "capability", "problem", "recipe", "command", "flag", "word", "short", "summary"):
        value = properties.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    if "Example" in labels:
        page = properties.get("page")
        section = properties.get("section")
        lang = properties.get("lang")
        position = properties.get("position")
        if page and section and isinstance(position, int):
            return f"Example {position} from {page} / {section}" + (f" ({lang})" if lang else "")
        first_line = properties.get("first_line")
        if isinstance(first_line, str) and first_line.strip():
            line = first_line.strip().replace("\n", " ")
            if len(line) > 100:
                line = line[:100] + "…"
            return f"Example: {line}"
        if page:
            location = f"{page} / {section}" if section else str(page)
            return f"Example from {location}" + (f" ({lang})" if lang else "")
    if "Flag" in labels and isinstance(properties.get("flag"), str):
        return properties["flag"]
    source_id = properties.get("id")
    if isinstance(source_id, str) and source_id.strip():
        return source_id.strip()
    return fallback


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value.strip()


def _validate_properties(value: Any, location: str) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError(f"{location} keys must be strings")
            _validate_properties(item, f"{location}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _validate_properties(item, f"{location}[{index}]")
    elif value is None or isinstance(value, (str, int, float, bool)):
        return
    else:
        raise ValueError(f"{location} contains unsupported JSON value {type(value).__name__}")


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
