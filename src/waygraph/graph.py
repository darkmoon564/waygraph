"""Single-owner Relate graph adapter. Verified API: relate-db 1.0.1."""
from __future__ import annotations
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator
import hashlib
import json
import relate
from .source_graph import normalize_source_graph

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

    def seed(self) -> None:
        self.initialize()
        nodes = [("python", "Python"), ("sdk", "Relate SDK"), ("engine", "Relate Engine"), ("transactions", "Transactions"), ("cypher", "Cypher"), ("mcp", "MCP")]
        edges = [("e1", "python", "sdk", "USES"), ("e2", "sdk", "engine", "CONNECTS_TO"), ("e3", "engine", "transactions", "SUPPORTS"), ("e4", "engine", "cypher", "SUPPORTS"), ("e5", "sdk", "mcp", "EXPOSES")]
        with self.transaction():
            for nid, title in nodes:
                self.query("MERGE (n:DPEntity {id:$id}) SET n.title=$title", {"id":nid,"title":title})
            for eid, src, dst, kind in edges:
                self.query("MATCH (a:DPEntity {id:$src}), (b:DPEntity {id:$dst}) MERGE (e:DPEdge {id:$id}) SET e.kind=$kind, e.active=true MERGE (a)-[:DP_FROM]->(e) MERGE (e)-[:DP_TO]->(b)", {"id":eid,"src":src,"dst":dst,"kind":kind})

    def import_source_graph(self, document: Any, source_sha256: str) -> dict[str, Any]:
        metadata, entities, edges = normalize_source_graph(document, source_sha256)
        self.initialize()
        with self.transaction():
            for batch in _batches(entities, 250):
                rows = []
                for entity in batch:
                    rows.append({
                        "id": entity["id"], "source_id": entity["source_id"],
                        "title": entity["title"], "labels": entity["labels"],
                        "properties_json": entity["properties_json"],
                        "source_values": _property_values(entity["properties"]),
                    })
                self.query(
                    "UNWIND $rows AS row MERGE (n:DPEntity {id:row.id}) "
                    "SET n.source_id=row.source_id, n.title=row.title, n.source_labels=row.labels, "
                    "n.source_properties_json=row.properties_json, n.dataset_id=$dataset_id, "
                    "n.dataset_sha256=$source_sha256, n.dataset_source_url=$source_url, "
                    "n.dataset_version=$source_verified SET n += row.source_values",
                    {"rows": rows, **metadata},
                )
            for batch in _batches(edges, 250):
                rows = []
                for edge in batch:
                    rows.append({
                        "id": edge["id"], "source": edge["source"], "target": edge["target"],
                        "kind": edge["kind"], "properties_json": edge["properties_json"],
                        "source_values": _property_values(edge["properties"]),
                    })
                self.query(
                    "UNWIND $rows AS row MATCH (a:DPEntity {id:row.source}), (b:DPEntity {id:row.target}) "
                    "MERGE (e:DPEdge {id:row.id}) SET e.kind=row.kind, e.active=true, "
                    "e.source_id=row.id, e.source_properties_json=row.properties_json, "
                    "e.dataset_id=$dataset_id, e.dataset_sha256=$source_sha256, "
                    "e.dataset_source_url=$source_url, e.dataset_version=$source_verified "
                    "SET e += row.source_values MERGE (a)-[:DP_FROM]->(e) MERGE (e)-[:DP_TO]->(b)",
                    {"rows": rows, **metadata},
                )
        return {**metadata, "entities": len(entities), "relationships": len(edges)}

    def node(self, node_id: str) -> dict[str, Any] | None:
        rows = self.query("MATCH (n:DPEntity {id:$id}) RETURN n.id AS id, n.title AS title, n.source_labels AS labels, n.source_properties_json AS properties_json LIMIT 1", {"id":node_id})
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
            {"id":node_id},
        )
        for row in rows:
            row["labels"] = row.get("labels") or []
            row["properties"] = _property_preview(row.pop("properties_json", None), max_text=160)
        return rows

    def edge(self, edge_id: str) -> dict[str, Any] | None:
        rows=self.query("MATCH (a:DPEntity)-[:DP_FROM]->(e:DPEdge {id:$id})-[:DP_TO]->(b:DPEntity) RETURN e.id AS id, e.kind AS kind, e.active AS active, e.source_properties_json AS properties_json, a.id AS source, b.id AS target LIMIT 1", {"id":edge_id})
        if rows:
            rows[0]["source_properties"] = _decode_properties(rows[0].pop("properties_json", None))
        return rows[0] if rows else None

    def disable_edge(self, edge_id: str) -> None:
        rows=self.query("MATCH (e:DPEdge {id:$id}) SET e.active=false RETURN e.id AS id", {"id":edge_id})
        if not rows:
            raise GraphError(f"Unknown edge: {edge_id}", "RELATIONSHIP_NOT_AVAILABLE")

    def delete_edge(self, edge_id: str) -> None:
        with self.transaction():
            rows = self.query("MATCH (e:DPEdge {id:$id}) DETACH DELETE e RETURN $id AS id", {"id": edge_id})
            if not rows:
                raise GraphError(f"Unknown edge: {edge_id}", "RELATIONSHIP_NOT_AVAILABLE")

    def set_edge_kind(self, edge_id: str, kind: str) -> None:
        if not isinstance(kind, str) or not kind.strip():
            raise GraphError("kind must be a non-empty string", "INVALID_ARGUMENT")
        if self.edge(edge_id) is None:
            raise GraphError(f"Unknown edge: {edge_id}", "RELATIONSHIP_NOT_AVAILABLE")
        self.query("MATCH (e:DPEdge {id:$id}) SET e.kind=$kind", {"id": edge_id, "kind": kind.strip()})

    def retarget_edge(self, edge_id: str, *, source: str | None = None, target: str | None = None) -> None:
        edge = self.edge(edge_id)
        if edge is None:
            raise GraphError(f"Unknown edge: {edge_id}", "RELATIONSHIP_NOT_AVAILABLE")
        new_source = source if source is not None else edge["source"]
        new_target = target if target is not None else edge["target"]
        if self.node(new_source) is None or self.node(new_target) is None:
            raise GraphError("New edge endpoints must be existing entities", "NODE_NOT_FOUND")
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
        with self.transaction():
            self.query(
                "MATCH (e:DPEdge {id:$id}) SET e.source_properties_json=$properties_json "
                "SET e += $source_value",
                {
                    "id": edge_id,
                    "properties_json": serialized,
                    "source_value": {f"source__{key}": value},
                },
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
    # Keep source fields queryable without colliding with the app's ID/title fields.
    return {f"source__{key}": value for key, value in properties.items() if not isinstance(value, dict)}


def _decode_properties(serialized: str | None) -> dict[str, Any]:
    if not serialized:
        return {}
    import json
    return json.loads(serialized)


def _property_preview(serialized: str | None, *, max_text: int = 800) -> dict[str, Any]:
    properties = _decode_properties(serialized)
    preview: dict[str, Any] = {}
    for key in ("title", "heading", "term", "word", "command", "capability", "problem", "short", "summary", "description", "text", "url", "md_url", "section", "type", "status"):
        value = properties.get(key)
        if isinstance(value, str):
            preview[key] = value if len(value) <= max_text else value[:max_text] + "…"
        elif isinstance(value, (int, float, bool)):
            preview[key] = value
    return preview
