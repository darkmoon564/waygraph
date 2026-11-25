"""Single-owner Relate graph adapter. Verified API: relate-db 1.2.0."""
from __future__ import annotations

from collections import defaultdict
from contextlib import contextmanager
from typing import Any, Iterator
import hashlib
import json
import re

import relate

from .source_graph import normalize_source_graph

_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_FTS_TOKEN = re.compile(r"[A-Za-z0-9_]+")


def _safe_ident(name: str, kind: str = "identifier") -> str:
    if not isinstance(name, str) or not _SAFE_IDENTIFIER.match(name):
        raise ValueError(f"Unsafe Cypher {kind}: {name!r}")
    return name


class GraphError(RuntimeError):
    def __init__(self, message: str, code: str = "INVALID_ARGUMENT"):
        super().__init__(message)
        self.code = code


class Graph:
    def __init__(self, path: str, *, read_only: bool = False):
        self.path = path
        self.read_only = read_only
        self.conn = relate.connect(database=path, read_only=read_only)

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "Graph":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def query(self, cypher: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        return [dict(row) for row in self.conn.execute(cypher, params or {}).fetchall()]

    def snapshot_id(self) -> str:
        """Hash source entities and facts, excluding learned shortcuts."""
        entities = self.query(
            "MATCH (n:DPEntity) RETURN n.id AS id, n.title AS title, "
            "n.source_labels AS labels, n.source_properties_json AS properties "
            "ORDER BY id"
        )
        edges = self.query(
            "MATCH (a:DPEntity)-[:DP_FROM]->(e:DPEdge)-[:DP_TO]->(b:DPEntity) "
            "RETURN e.id AS id, a.id AS source, b.id AS target, e.kind AS kind, "
            "e.active AS active, e.source_properties_json AS properties ORDER BY id"
        )
        payload = json.dumps(
            {"entities": entities, "edges": edges},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @contextmanager
    def transaction(self) -> Iterator[None]:
        if self.read_only:
            raise GraphError("Cannot write using a read-only connection", "INVALID_ARGUMENT")
        self.conn.autocommit = False
        try:
            yield
            self.conn.commit()
        except BaseException:
            self.conn.rollback()
            raise
        finally:
            self.conn.autocommit = True

    def initialize(self) -> None:
        self.query("CREATE CONSTRAINT dp_entity_id IF NOT EXISTS FOR (n:DPEntity) REQUIRE n.id IS UNIQUE")
        self.query("CREATE CONSTRAINT dp_edge_id IF NOT EXISTS FOR (n:DPEdge) REQUIRE n.id IS UNIQUE")
        self.query("CREATE CONSTRAINT dp_shortcut_id IF NOT EXISTS FOR (n:DPShortcut) REQUIRE n.id IS UNIQUE")
        self.query(
            "CREATE FULLTEXT INDEX dp_entity_ft IF NOT EXISTS "
            "FOR (n:DPEntity) ON EACH [n.title, n.id, n.search_text]"
        )

    def seed(self) -> None:
        self.initialize()
        nodes = [
            ("python", "Python", ["Surface"]),
            ("sdk", "Relate SDK", ["Capability"]),
            ("engine", "Relate Engine", ["Page"]),
            ("transactions", "Transactions", ["Capability"]),
            ("cypher", "Cypher", ["Surface"]),
            ("mcp", "MCP", ["Surface"]),
        ]
        edges = [
            ("e1", "python", "sdk", "USES"),
            ("e2", "sdk", "engine", "CONNECTS_TO"),
            ("e3", "engine", "transactions", "SUPPORTS"),
            ("e4", "engine", "cypher", "SUPPORTS"),
            ("e5", "sdk", "mcp", "EXPOSES"),
        ]
        with self.transaction():
            for nid, title, labels in nodes:
                label_suffix = "".join(f":{_safe_ident(lbl, 'label')}" for lbl in labels)
                self.query(
                    f"MERGE (n:DPEntity {label_suffix[1:] if False else ''}{{id:$id}}) "
                    f"SET n{label_suffix}, n.title=$title, n.source_labels=$labels, "
                    "n.search_text=$search_text",
                    {"id": nid, "title": title, "labels": labels, "search_text": f"{nid} {title} {' '.join(labels)}"},
                )
            for eid, src, dst, kind in edges:
                rel_type = _safe_ident(kind, "relationship type")
                self.query(
                    "MATCH (a:DPEntity {id:$src}), (b:DPEntity {id:$dst}) "
                    "MERGE (e:DPEdge {id:$id}) SET e.kind=$kind, e.active=true "
                    "MERGE (a)-[:DP_FROM]->(e) MERGE (e)-[:DP_TO]->(b) "
                    f"MERGE (a)-[r:{rel_type} {{dp_edge_id:$id}}]->(b) SET r.active=true",
                    {"id": eid, "src": src, "dst": dst, "kind": kind},
                )

    def import_source_graph(self, document: Any, source_sha256: str) -> dict[str, Any]:
        metadata, entities, edges = normalize_source_graph(document, source_sha256)
        self.initialize()
        entities_by_labels: defaultdict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
        for entity in entities:
            clean_labels = tuple(_safe_ident(lbl, "label") for lbl in entity["labels"])
            entities_by_labels[clean_labels].append(entity)

        edges_by_kind: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
        for edge in edges:
            clean_kind = _safe_ident(edge["kind"], "relationship type")
            edges_by_kind[clean_kind].append(edge)

        with self.transaction():
            for label_tuple, group in entities_by_labels.items():
                label_clause = "".join(f":{lbl}" for lbl in label_tuple)
                for batch in _batches(group, 250):
                    rows = [
                        {
                            "id": entity["id"],
                            "source_id": entity["source_id"],
                            "title": entity["title"],
                            "labels": entity["labels"],
                            "properties_json": entity["properties_json"],
                            "search_text": _build_search_text(entity["id"], entity["title"], entity["labels"], entity["properties"]),
                            "source_values": _property_values(entity["properties"]),
                        }
                        for entity in batch
                    ]
                    self.query(
                        "UNWIND $rows AS row MERGE (n:DPEntity {id:row.id}) "
                        f"SET n{label_clause}, "
                        "n.source_id=row.source_id, n.title=row.title, n.source_labels=row.labels, "
                        "n.source_properties_json=row.properties_json, n.search_text=row.search_text, "
                        "n.dataset_id=$dataset_id, n.dataset_sha256=$source_sha256, "
                        "n.dataset_source_url=$source_url, n.dataset_version=$source_verified "
                        "SET n += row.source_values",
                        {"rows": rows, **metadata},
                    )
            for rel_type, group in edges_by_kind.items():
                for batch in _batches(group, 250):
                    rows = [
                        {
                            "id": edge["id"],
                            "source": edge["source"],
                            "target": edge["target"],
                            "kind": edge["kind"],
                            "properties_json": edge["properties_json"],
                            "source_values": _property_values(edge["properties"]),
                        }
                        for edge in batch
                    ]
                    self.query(
                        "UNWIND $rows AS row MATCH (a:DPEntity {id:row.source}), (b:DPEntity {id:row.target}) "
                        "MERGE (e:DPEdge {id:row.id}) SET e.kind=row.kind, e.active=true, "
                        "e.source_id=row.id, e.source_properties_json=row.properties_json, "
                        "e.dataset_id=$dataset_id, e.dataset_sha256=$source_sha256, "
                        "e.dataset_source_url=$source_url, e.dataset_version=$source_verified "
                        "SET e += row.source_values MERGE (a)-[:DP_FROM]->(e) MERGE (e)-[:DP_TO]->(b) "
                        f"MERGE (a)-[r:{rel_type} {{dp_edge_id:row.id}}]->(b) "
                        "SET r.active=true, r += row.source_values",
                        {"rows": rows, **metadata},
                    )
        return {**metadata, "entities": len(entities), "relationships": len(edges)}

    def search_nodes(self, query_text: str, *, label: str | None = None, limit: int = 10) -> list[dict[str, Any]]:
        """Hybrid lexical + native Relate full-text search over entities."""
        if not isinstance(query_text, str) or not query_text.strip():
            raise GraphError("query must be a non-empty string", "INVALID_ARGUMENT")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 50:
            raise GraphError("limit must be an integer from 1 to 50", "INVALID_ARGUMENT")
        label_filter = label.strip() if isinstance(label, str) and label.strip() else None
        if label_filter is not None:
            _safe_ident(label_filter, "label")

        needle = query_text.strip()
        needle_lower = needle.lower()
        scored: dict[str, dict[str, Any]] = {}

        # 1. Exact / substring lexical priority on id and title (handles ':', '--flags', exact IDs).
        exact_rows = self.query(
            "MATCH (n:DPEntity) "
            "WHERE toLower(n.id) CONTAINS $needle OR toLower(coalesce(n.title, '')) CONTAINS $needle "
            "RETURN n.id AS id, n.title AS title, n.source_labels AS labels, "
            "n.source_properties_json AS properties_json ORDER BY n.id LIMIT 50",
            {"needle": needle_lower},
        )
        for row in exact_rows:
            labels = row.get("labels") or []
            if label_filter and label_filter not in labels:
                continue
            rid = row["id"]
            title = row.get("title") or ""
            bonus = 10.0 if rid.lower() == needle_lower or title.lower() == needle_lower else 4.0
            scored[rid] = {
                "id": rid,
                "title": title,
                "labels": labels,
                "properties": _property_preview(row.get("properties_json"), max_text=240),
                "score": bonus,
            }

        # 2. Native Relate 1.2.0 full-text index ranking over title, id, and search_text.
        tokens = _FTS_TOKEN.findall(needle)
        if tokens:
            fts_query = " OR ".join(tokens[:12])
            try:
                fts_rows = self.query(
                    "CALL db.index.fulltext.queryNodes('dp_entity_ft', $q) "
                    "YIELD node, score "
                    "RETURN node.id AS id, node.title AS title, node.source_labels AS labels, "
                    "node.source_properties_json AS properties_json, score AS score "
                    "ORDER BY score DESC LIMIT 50",
                    {"q": fts_query},
                )
            except relate.Error:
                fts_rows = []
            for row in fts_rows:
                labels = row.get("labels") or []
                if label_filter and label_filter not in labels:
                    continue
                rid = row["id"]
                fts_score = float(row.get("score") or 0.0)
                if rid in scored:
                    scored[rid]["score"] = round(scored[rid]["score"] + fts_score, 4)
                else:
                    scored[rid] = {
                        "id": rid,
                        "title": row.get("title") or "",
                        "labels": labels,
                        "properties": _property_preview(row.get("properties_json"), max_text=240),
                        "score": round(fts_score, 4),
                    }

        ranked = sorted(scored.values(), key=lambda item: (-item["score"], item["id"]))
        return ranked[:limit]

    def node(self, node_id: str) -> dict[str, Any] | None:
        rows = self.query(
            "MATCH (n:DPEntity {id:$id}) RETURN n.id AS id, n.title AS title, "
            "n.source_labels AS labels, n.source_properties_json AS properties_json LIMIT 1",
            {"id": node_id},
        )
        if rows:
            rows[0]["labels"] = rows[0].get("labels") or []
            rows[0]["properties"] = _property_preview(rows[0].pop("properties_json", None))
        return rows[0] if rows else None

    def neighbors(self, node_id: str, *, limit: int = 100) -> list[dict[str, Any]]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100_000:
            raise ValueError("neighbor limit must be an integer from 1 to 100000")
        rows = self.query(
            "MATCH (a:DPEntity {id:$id})-[:DP_FROM]->(e:DPEdge)-[:DP_TO]->(b:DPEntity) "
            "WHERE e.active = true RETURN e.id AS edge_id, e.kind AS kind, "
            "e.source_properties_json AS properties_json, b.id AS node_id, b.title AS title, "
            f"b.source_labels AS labels ORDER BY edge_id LIMIT {limit}",
            {"id": node_id},
        )
        for row in rows:
            row["labels"] = row.get("labels") or []
            row["properties"] = _property_preview(row.pop("properties_json", None), max_text=160)
        return rows

    def edge(self, edge_id: str) -> dict[str, Any] | None:
        rows = self.query(
            "MATCH (a:DPEntity)-[:DP_FROM]->(e:DPEdge {id:$id})-[:DP_TO]->(b:DPEntity) "
            "RETURN e.id AS id, e.kind AS kind, e.active AS active, "
            "e.source_properties_json AS properties_json, a.id AS source, b.id AS target LIMIT 1",
            {"id": edge_id},
        )
        if rows:
            rows[0]["source_properties"] = _decode_properties(rows[0].pop("properties_json", None))
        return rows[0] if rows else None

    def disable_edge(self, edge_id: str) -> None:
        with self.transaction():
            rows = self.query("MATCH (e:DPEdge {id:$id}) SET e.active=false RETURN e.id AS id", {"id": edge_id})
            if not rows:
                raise GraphError(f"Unknown edge: {edge_id}", "RELATIONSHIP_NOT_AVAILABLE")
            self.query("MATCH (:DPEntity)-[r {dp_edge_id:$id}]->(:DPEntity) SET r.active=false", {"id": edge_id})

    def delete_edge(self, edge_id: str) -> None:
        with self.transaction():
            rows = self.query("MATCH (e:DPEdge {id:$id}) DETACH DELETE e RETURN $id AS id", {"id": edge_id})
            if not rows:
                raise GraphError(f"Unknown edge: {edge_id}", "RELATIONSHIP_NOT_AVAILABLE")
            self.query("MATCH (:DPEntity)-[r {dp_edge_id:$id}]->(:DPEntity) DELETE r", {"id": edge_id})

    def set_edge_kind(self, edge_id: str, kind: str) -> None:
        if not isinstance(kind, str) or not kind.strip():
            raise GraphError("kind must be a non-empty string", "INVALID_ARGUMENT")
        clean_kind = _safe_ident(kind.strip(), "relationship type")
        edge = self.edge(edge_id)
        if edge is None:
            raise GraphError(f"Unknown edge: {edge_id}", "RELATIONSHIP_NOT_AVAILABLE")
        with self.transaction():
            self.query("MATCH (e:DPEdge {id:$id}) SET e.kind=$kind", {"id": edge_id, "kind": clean_kind})
            self.query("MATCH (:DPEntity)-[r {dp_edge_id:$id}]->(:DPEntity) DELETE r", {"id": edge_id})
            self.query(
                "MATCH (a:DPEntity {id:$src}), (b:DPEntity {id:$dst}) "
                f"MERGE (a)-[r:{clean_kind} {{dp_edge_id:$id}}]->(b) "
                "SET r.active=$active, r += $props",
                {
                    "id": edge_id,
                    "src": edge["source"],
                    "dst": edge["target"],
                    "active": bool(edge["active"]),
                    "props": _property_values(edge["source_properties"]),
                },
            )

    def retarget_edge(self, edge_id: str, *, source: str | None = None, target: str | None = None) -> None:
        edge = self.edge(edge_id)
        if edge is None:
            raise GraphError(f"Unknown edge: {edge_id}", "RELATIONSHIP_NOT_AVAILABLE")
        new_source = source if source is not None else edge["source"]
        new_target = target if target is not None else edge["target"]
        if self.node(new_source) is None or self.node(new_target) is None:
            raise GraphError("New edge endpoints must be existing entities", "NODE_NOT_FOUND")
        rel_type = _safe_ident(edge["kind"], "relationship type")
        with self.transaction():
            if source is not None:
                self.query("MATCH ()-[r:DP_FROM]->(e:DPEdge {id:$id}) DELETE r", {"id": edge_id})
                self.query(
                    "MATCH (a:DPEntity {id:$source}), (e:DPEdge {id:$id}) MERGE (a)-[:DP_FROM]->(e)",
                    {"id": edge_id, "source": new_source},
                )
            if target is not None:
                self.query("MATCH (e:DPEdge {id:$id})-[r:DP_TO]->() DELETE r", {"id": edge_id})
                self.query(
                    "MATCH (e:DPEdge {id:$id}), (b:DPEntity {id:$target}) MERGE (e)-[:DP_TO]->(b)",
                    {"id": edge_id, "target": new_target},
                )
            self.query("MATCH (:DPEntity)-[r {dp_edge_id:$id}]->(:DPEntity) DELETE r", {"id": edge_id})
            self.query(
                "MATCH (a:DPEntity {id:$src}), (b:DPEntity {id:$dst}) "
                f"MERGE (a)-[r:{rel_type} {{dp_edge_id:$id}}]->(b) "
                "SET r.active=$active, r += $props",
                {
                    "id": edge_id,
                    "src": new_source,
                    "dst": new_target,
                    "active": bool(edge["active"]),
                    "props": _property_values(edge["source_properties"]),
                },
            )

    def update_edge_property(self, edge_id: str, key: str, value: Any) -> None:
        if not isinstance(key, str) or not key.strip() or key.startswith("source__"):
            raise GraphError("property key must be a non-empty source key", "INVALID_ARGUMENT")
        if not isinstance(value, (str, int, float, bool, list)):
            raise GraphError("property value must be a JSON scalar or list", "INVALID_ARGUMENT")
        edge = self.edge(edge_id)
        if edge is None:
            raise GraphError(f"Unknown edge: {edge_id}", "RELATIONSHIP_NOT_AVAILABLE")
        properties = dict(edge["source_properties"])
        properties[key] = value
        serialized = json.dumps(properties, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        source_prop = {f"source__{key}": value}
        with self.transaction():
            self.query(
                "MATCH (e:DPEdge {id:$id}) SET e.source_properties_json=$properties_json "
                "SET e += $source_value",
                {"id": edge_id, "properties_json": serialized, "source_value": source_prop},
            )
            self.query(
                "MATCH (:DPEntity)-[r {dp_edge_id:$id}]->(:DPEntity) SET r += $source_value",
                {"id": edge_id, "source_value": source_prop},
            )

    def delete_node(self, node_id: str) -> None:
        with self.transaction():
            rows = self.query("MATCH (n:DPEntity {id:$id}) DETACH DELETE n RETURN $id AS id", {"id": node_id})
            if not rows:
                raise GraphError(f"Unknown node: {node_id}", "NODE_NOT_FOUND")


def _batches(items: list[dict[str, Any]], size: int) -> Iterator[list[dict[str, Any]]]:
    for start in range(0, len(items), size):
        yield items[start:start + size]


def _property_values(properties: dict[str, Any]) -> dict[str, Any]:
    return {f"source__{key}": value for key, value in properties.items() if not isinstance(value, dict)}


def _build_search_text(node_id: str, title: str, labels: list[str], properties: dict[str, Any]) -> str:
    parts = [node_id, title, " ".join(labels)]
    for key in ("heading", "term", "word", "command", "flag", "capability", "problem", "short", "summary", "description", "section", "page", "first_line"):
        val = properties.get(key)
        if isinstance(val, str) and val.strip():
            parts.append(val.strip()[:300])
    return " ".join(parts)


def _decode_properties(serialized: str | None) -> dict[str, Any]:
    if not serialized:
        return {}
    return json.loads(serialized)


def _property_preview(serialized: str | None, *, max_text: int = 800) -> dict[str, Any]:
    properties = _decode_properties(serialized)
    preview: dict[str, Any] = {}
    for key in ("title", "heading", "term", "word", "command", "flag", "capability", "problem", "short", "summary", "description", "text", "url", "md_url", "section", "type", "status"):
        value = properties.get(key)
        if isinstance(value, str):
            preview[key] = value if len(value) <= max_text else value[:max_text] + "…"
        elif isinstance(value, (int, float, bool)):
            preview[key] = value
    return preview
