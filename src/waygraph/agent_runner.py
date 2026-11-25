"""Tool-use benchmark runner for isolated graph conditions (cursor, waygraph, native-cypher)."""
from __future__ import annotations

import asyncio
from concurrent.futures import Future
import hashlib
import json
import os
import platform
import re
import statistics
import sys
import threading
import time
from collections.abc import Callable
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4

from .cursor import Cursor
from .graph import Graph, GraphError
from .questions import load_question_set
from .shortcuts import learn, list_shortcuts

_READ_QUERY = re.compile(
    r"^\s*(MATCH|OPTIONAL\s+MATCH|WITH|UNWIND|RETURN|CALL\s+db\.index\.fulltext\.queryNodes)\b",
    re.I,
)
_WRITE_CLAUSE = re.compile(r"\b(CREATE|MERGE|DELETE|DETACH|SET|REMOVE|DROP|LOAD\s+CSV|FOREACH)\b", re.I)
_DISALLOWED_CALL = re.compile(r"\bCALL\b(?!\s+db\.index\.fulltext\.queryNodes\b)", re.I)

_CONDITIONS = frozenset({"cursor", "waygraph", "native-cypher"})
_TRANSPORTS = frozenset({"in-process", "mcp-stdio"})
_OPENAI_COMPAT_URLS: dict[str, str] = {
    "openrouter": "https://openrouter.ai/api/v1/chat/completions",
    "groq": "https://api.groq.com/openai/v1/chat/completions",
    "cerebras": "https://api.cerebras.ai/v1/chat/completions",
    "ollama": "http://127.0.0.1:11434/v1/chat/completions",
}
_PROVIDER_DISPLAY: dict[str, str] = {
    "openrouter": "OpenRouter",
    "groq": "Groq",
    "cerebras": "Cerebras",
    "ollama": "Ollama",
    "gemini": "Gemini",
    "anthropic": "Anthropic",
}
_PROVIDER_KEY_ENV: dict[str, str | None] = {
    "openrouter": "OPENROUTER_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "groq": "GROQ_API_KEY",
    "cerebras": "CEREBRAS_API_KEY",
    "ollama": None,
    "anthropic": "ANTHROPIC_API_KEY",
}
_DEFAULT_MODELS: dict[str, str] = {
    "openrouter": "nvidia/nemotron-3-ultra-550b-a55b:free",
    "groq": "llama-3.3-70b-versatile",
    "cerebras": "llama3.1-8b",
    "gemini": "gemini-2.5-flash",
    "ollama": "qwen2.5:7b",
}
_SYSTEM_RESERVED_REL_TYPES = frozenset({"DP_FROM", "DP_TO", "DP_SHORTCUT_FROM", "DP_SHORTCUT_TO"})


def _is_auth_error(message: str) -> bool:
    lowered = message.lower()
    return any(
        marker in lowered
        for marker in ("http 401", "http 403", "user not found", "api key not valid", "invalid api key")
    )


def _is_daily_quota_error(message: str) -> bool:
    lowered = message.lower()
    if any(
        marker in lowered
        for marker in (
            "per-day",
            "free-models-per-day",
            "daily limit",
            "daily quota",
            "requests per day",
            "tokens per day",
            "limit_rpd",
        )
    ):
        return True
    return bool(re.search(r"\b(?:per\s+day|rpd|tpd)\b", lowered))


def _is_fatal_provider_error(message: str) -> bool:
    return _is_auth_error(message) or _is_daily_quota_error(message) or bool(re.search(r"\bhttp (?:429|5\d\d)\b", message, re.I))


class _OpenRouterClient:
    """Small OpenAI-compatible chat completions client using only the stdlib."""

    def __init__(
        self,
        api_key: str = "",
        *,
        timeout: float = 120.0,
        base_url: str = _OPENAI_COMPAT_URLS["openrouter"],
        provider_name: str = "OpenRouter",
        max_retries: int = 3,
        retry_base_delay: float = 1.0,
    ):
        self.api_key = api_key
        self.timeout = timeout
        self.base_url = base_url
        self.provider_name = provider_name
        self.max_retries = max_retries
        self.retry_base_delay = retry_base_delay
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _prepare_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        body = dict(payload)
        provider_lower = self.provider_name.lower()
        if provider_lower != "openrouter":
            body.pop("session_id", None)
        if provider_lower in {"ollama", "cerebras"}:
            body.pop("parallel_tool_calls", None)
        return body

    def _extract_http_error_detail(self, exc: HTTPError) -> str:
        raw_body = ""
        try:
            raw_body = exc.read().decode("utf-8", errors="replace")
            parsed = json.loads(raw_body)
            if isinstance(parsed, dict):
                err_obj = parsed.get("error")
                if isinstance(err_obj, dict) and err_obj.get("message"):
                    return str(err_obj["message"])
                if isinstance(err_obj, str) and err_obj.strip():
                    return err_obj.strip()
                if parsed.get("message"):
                    return str(parsed["message"])
        except (ValueError, AttributeError, OSError):
            pass
        cleaned = raw_body.strip()
        return cleaned[:400] if cleaned else "request rejected"

    def _retry_delay(self, exc: HTTPError, attempt: int) -> float:
        headers = getattr(exc, "headers", None)
        if headers is not None:
            retry_after = headers.get("Retry-After")
            if retry_after is not None:
                try:
                    return max(0.0, min(float(retry_after), 30.0))
                except ValueError:
                    pass
        return self.retry_base_delay * (2**attempt)

    def _create(self, **payload: Any) -> Any:
        wire_payload = self._prepare_payload(payload)
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "waygraph/0.1",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        data: dict[str, Any] = {}
        for attempt in range(self.max_retries + 1):
            request = Request(
                self.base_url,
                data=json.dumps(wire_payload).encode("utf-8"),
                headers=headers,
                method="POST",
            )
            try:
                with urlopen(request, timeout=self.timeout) as response:
                    data = json.loads(response.read().decode("utf-8"))
                break
            except HTTPError as exc:
                detail = self._extract_http_error_detail(exc)
                error_msg = f"{self.provider_name} HTTP {exc.code}: {str(detail)[:400]}"
                if exc.code == 429 and _is_daily_quota_error(error_msg):
                    raise RuntimeError(error_msg) from exc
                if exc.code in {429, 502, 503} and attempt < self.max_retries:
                    time.sleep(self._retry_delay(exc, attempt))
                    continue
                raise RuntimeError(error_msg) from exc
            except URLError as exc:
                raise RuntimeError(f"{self.provider_name} connection failed: {exc.reason}") from exc

        choices = []
        for choice in data.get("choices", []):
            message = dict(choice.get("message") or {})
            raw_calls = message.get("tool_calls") or []
            tool_calls = []
            normalized_raw_calls = []
            for idx, call in enumerate(raw_calls):
                fn = call.get("function") or {}
                raw_arguments = fn.get("arguments", "{}")
                if isinstance(raw_arguments, dict):
                    arguments_str = json.dumps(raw_arguments, ensure_ascii=False)
                else:
                    arguments_str = str(raw_arguments or "{}")
                call_id = call.get("id") or f"call_{idx}"
                fn_name = fn.get("name", "")
                tool_calls.append(
                    SimpleNamespace(
                        id=call_id,
                        type="function",
                        function=SimpleNamespace(name=fn_name, arguments=arguments_str),
                    )
                )
                normalized_raw_calls.append(
                    {
                        "id": call_id,
                        "type": "function",
                        "function": {"name": fn_name, "arguments": arguments_str},
                    }
                )
            dumped_message = {
                "role": message.get("role", "assistant"),
                **{k: v for k, v in message.items() if v is not None and k != "tool_calls"},
            }
            if normalized_raw_calls:
                dumped_message["tool_calls"] = normalized_raw_calls
            message_obj = SimpleNamespace(content=message.get("content"), tool_calls=tool_calls or None)
            message_obj.model_dump = lambda exclude_none=True, m=dumped_message: (
                {k: v for k, v in m.items() if v is not None} if exclude_none else dict(m)
            )
            choices.append(SimpleNamespace(message=message_obj, finish_reason=choice.get("finish_reason")))
        usage = data.get("usage") or {}
        return SimpleNamespace(
            choices=choices,
            usage=SimpleNamespace(
                prompt_tokens=usage.get("prompt_tokens", 0) or 0,
                completion_tokens=usage.get("completion_tokens", 0) or 0,
            ),
            model=data.get("model", payload.get("model")),
        )


class _McpStdioBridge:
    """Synchronous bridge to a `waygraph.mcp_server` subprocess over MCP stdio."""

    def __init__(self, store_path: Path, *, timeout: float = 60.0):
        self.store_path = Path(store_path)
        self.timeout = timeout
        self._ready = threading.Event()
        self._startup_error: BaseException | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._queue: asyncio.Queue[tuple[str, dict[str, Any], Future[Any]] | None] | None = None
        self._thread: threading.Thread | None = None

    def open(self) -> "_McpStdioBridge":
        self._thread = threading.Thread(target=self._run_thread, name="waygraph-mcp-stdio", daemon=True)
        self._thread.start()
        if not self._ready.wait(timeout=self.timeout):
            raise RuntimeError("Timed out starting waygraph.mcp_server over stdio")
        if self._startup_error is not None:
            raise RuntimeError(f"Failed to start waygraph.mcp_server: {self._startup_error}") from self._startup_error
        return self

    def _run_thread(self) -> None:
        asyncio.run(self._worker())

    async def _worker(self) -> None:
        from mcp import ClientSession
        from mcp.client.stdio import StdioServerParameters, stdio_client

        self._loop = asyncio.get_running_loop()
        self._queue = asyncio.Queue()
        env = dict(os.environ)
        env["WAYGRAPH_DB"] = str(self.store_path)
        src_root = str(Path(__file__).resolve().parents[1])
        existing_py = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = f"{src_root}{os.pathsep}{existing_py}" if existing_py else src_root
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "waygraph.mcp_server"],
            env=env,
        )
        try:
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    self._ready.set()
                    while True:
                        item = await self._queue.get()
                        if item is None:
                            break
                        name, arguments, fut = item
                        try:
                            res = await session.call_tool(name, arguments)
                            fut.set_result(res)
                        except BaseException as exc:
                            fut.set_exception(exc)
        except BaseException as exc:
            if not self._ready.is_set():
                self._startup_error = exc
                self._ready.set()

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if self._loop is None or self._queue is None:
            raise RuntimeError("MCP stdio session is not open")
        fut: Future[Any] = Future()
        self._loop.call_soon_threadsafe(self._queue.put_nowait, (name, arguments, fut))
        res = fut.result(timeout=self.timeout)
        envelope: dict[str, Any] | None = None
        structured = getattr(res, "structuredContent", None)
        if isinstance(structured, dict) and "ok" in structured:
            envelope = structured
        else:
            blocks = getattr(res, "content", None) or []
            if blocks and hasattr(blocks[0], "text"):
                envelope = json.loads(blocks[0].text)
        if not isinstance(envelope, dict):
            if getattr(res, "isError", False):
                raise RuntimeError(f"MCP tool {name!r} returned an unparsed error")
            raise RuntimeError(f"Unexpected MCP response payload from {name!r}")
        if not envelope.get("ok", False):
            err = envelope.get("error") or {}
            code = err.get("code") or "INVALID_ARGUMENT"
            msg = err.get("message") or f"MCP tool {name!r} failed"
            raise GraphError(msg, code)
        data = envelope.get("data")
        return data if isinstance(data, dict) else {"value": data}

    def close(self) -> None:
        if self._loop is not None and self._queue is not None:
            try:
                self._loop.call_soon_threadsafe(self._queue.put_nowait, None)
            except RuntimeError:
                pass
        if self._thread is not None:
            self._thread.join(timeout=15.0)
            self._thread = None
        self._loop = None
        self._queue = None

    def __enter__(self) -> "_McpStdioBridge":
        return self.open()

    def __exit__(self, *_: object) -> None:
        self.close()


def _validate_read_query(query: str) -> None:
    if (
        not isinstance(query, str)
        or len(query) > 4000
        or ";" in query
        or not _READ_QUERY.match(query)
        or _WRITE_CLAUSE.search(query)
        or _DISALLOWED_CALL.search(query)
    ):
        raise ValueError("Only one read-only Cypher query over the inspected graph schema is allowed")
    limit = re.search(r"\bLIMIT\s+(\d+)\b", query, re.I)
    if limit and int(limit.group(1)) > 100:
        raise ValueError("Query LIMIT cannot exceed 100")


def _agent_result_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    answered = [row for row in rows if row.get("error") is None]
    return {
        "attempted_questions": len(rows),
        "answered_questions": len(answered),
        "provider_failures": sum(row.get("error") is not None for row in rows),
        "accuracy": sum(bool(row.get("is_correct")) for row in rows) / len(rows) if rows else None,
        "answer_accuracy": sum(bool(row.get("is_correct")) for row in answered) / len(answered) if answered else None,
        "mean_input_tokens": sum(row.get("input_tokens", 0) for row in answered) / len(answered) if answered else None,
        "mean_output_tokens": sum(row.get("output_tokens", 0) for row in answered) / len(answered) if answered else None,
        "mean_tool_calls": sum(row.get("tool_calls", 0) for row in answered) / len(answered) if answered else None,
    }


def _agent_shortcut_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    answered = [row for row in rows if row.get("error") is None]
    cursor_steps = [row["cursor_steps"] for row in answered if row.get("cursor_steps") is not None]
    traversal_hops = [row["traversal_hops"] for row in answered if row.get("traversal_hops") is not None]
    return {
        "shortcut_hits": sum(int(row.get("shortcut_hits", 0) or 0) for row in rows),
        "stale_shortcut_rejections": sum(int(row.get("stale_shortcut_rejections", 0) or 0) for row in rows),
        "shortcuts_promoted": sum(int(row.get("shortcuts_promoted", 0) or 0) for row in rows),
        "mean_cursor_steps": sum(cursor_steps) / len(cursor_steps) if cursor_steps else None,
        "mean_traversal_hops": sum(traversal_hops) / len(traversal_hops) if traversal_hops else None,
    }


def _anthropic_tools(condition: str) -> list[dict[str, Any]]:
    if condition == "cursor":
        specs: list[tuple[str, str, dict[str, Any], list[str]]] = [
            (
                "search_nodes",
                "Search graph entities using hybrid lexical + full-text search to locate starting node IDs.",
                {"query": {"type": "string"}, "label": {"type": "string"}, "limit": {"type": "integer"}},
                ["query"],
            ),
            (
                "start_walk",
                "Start a cursor using the exact origin node ID shown in parentheses in the question, not its display title.",
                {"origin": {"type": "string"}, "max_hops": {"type": "integer"}},
                ["origin"],
            ),
            (
                "inspect_walk",
                "Inspect the current node and the currently offered outgoing edges.",
                {},
                [],
            ),
            (
                "follow_edge",
                "Follow an edge ID from the latest inspection.",
                {"edge_id": {"type": "string"}},
                ["edge_id"],
            ),
            (
                "backtrack",
                "Undo one cursor step and refresh the available outgoing edges.",
                {},
                [],
            ),
            (
                "get_walk",
                "Get the ordered nodes and edges traversed in this walk.",
                {},
                [],
            ),
        ]
    elif condition == "waygraph":
        specs = [
            (
                "search_nodes",
                "Search graph entities using hybrid lexical + full-text search to locate starting node IDs.",
                {"query": {"type": "string"}, "label": {"type": "string"}, "limit": {"type": "integer"}},
                ["query"],
            ),
            (
                "start_walk",
                "Start a cursor at the exact origin node ID; returns offered outgoing edges and promoted shortcuts.",
                {"origin": {"type": "string"}, "max_hops": {"type": "integer"}},
                ["origin"],
            ),
            (
                "inspect_walk",
                "Inspect the current node, offered outgoing edges, and promoted shortcuts.",
                {},
                [],
            ),
            (
                "take_shortcut",
                "Validate a promoted shortcut_id from the latest inspection fail-closed and jump across its verified path in one step.",
                {"shortcut_id": {"type": "string"}},
                ["shortcut_id"],
            ),
            (
                "follow_edge",
                "Follow an edge ID from the latest inspection.",
                {"edge_id": {"type": "string"}},
                ["edge_id"],
            ),
            (
                "backtrack",
                "Undo one cursor step (single edge or shortcut jump) and refresh available offers.",
                {},
                [],
            ),
            (
                "get_walk",
                "Get the ordered nodes, edges, and shortcuts traversed in this walk.",
                {},
                [],
            ),
            (
                "save_shortcut",
                "Explicitly record an evidence-bearing shortcut from the current walk.",
                {},
                [],
            ),
        ]
    elif condition == "native-cypher":
        specs = [
            (
                "inspect_schema",
                "Return the read-only graph schema, native domain labels, relationship types, and fulltext index.",
                {},
                [],
            ),
            (
                "query_graph",
                "Run a bounded read-only Cypher query (MATCH, OPTIONAL MATCH, WITH, UNWIND, RETURN, or CALL db.index.fulltext.queryNodes).",
                {"query": {"type": "string"}, "params": {"type": "object"}},
                ["query"],
            ),
        ]
    else:
        raise ValueError(f"Unsupported condition: {condition}")
    return [
        {
            "name": name,
            "description": description,
            "input_schema": {
                "type": "object",
                "properties": props,
                "required": required,
                "additionalProperties": False,
            },
        }
        for name, description, props, required in specs
    ]


def _strip_shortcuts(inspection: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in inspection.items() if k != "shortcuts"}


def _inspect_native_schema(graph: Graph) -> dict[str, Any]:
    label_rows = graph.query("MATCH (n:DPEntity) RETURN DISTINCT n.source_labels AS labels")
    domain_labels_set: set[str] = set()
    for row in label_rows:
        for lbl in row.get("labels") or []:
            if isinstance(lbl, str) and lbl:
                domain_labels_set.add(lbl)
    domain_labels = sorted(domain_labels_set)

    rel_rows = graph.query("MATCH (:DPEntity)-[r]->(:DPEntity) WHERE r.active = true RETURN DISTINCT type(r) AS rel_type ORDER BY rel_type")
    domain_rel_types = [
        row["rel_type"]
        for row in rel_rows
        if isinstance(row.get("rel_type"), str) and row["rel_type"] not in _SYSTEM_RESERVED_REL_TYPES
    ]
    if not domain_rel_types:
        edge_rows = graph.query("MATCH (e:DPEdge) WHERE e.active = true RETURN DISTINCT e.kind AS kind ORDER BY kind")
        domain_rel_types = [row["kind"] for row in edge_rows if isinstance(row.get("kind"), str)]

    all_labels = ["DPEntity", "DPEdge"] + [lbl for lbl in domain_labels if lbl not in {"DPEntity", "DPEdge"}]
    all_rel_types = domain_rel_types + ["DP_FROM", "DP_TO"]
    return {
        "model": (
            "Entities carry :DPEntity plus native domain labels (properties: id, title, source_labels, search_text, source__*). "
            "Active domain relationships exist both as direct typed edges (a:DPEntity)-[r:<REL_TYPE> {active: true, dp_edge_id}]->(b:DPEntity) "
            "and as reified edge nodes (a:DPEntity)-[:DP_FROM]->(e:DPEdge {active: true, kind})-[:DP_TO]->(b:DPEntity). "
            "Full-text search is available via CALL db.index.fulltext.queryNodes('dp_entity_ft', $q) YIELD node, score."
        ),
        "domain_labels": domain_labels,
        "labels": all_labels,
        "domain_relationship_types": domain_rel_types,
        "relationship_types": all_rel_types,
        "fulltext_index": {
            "name": "dp_entity_ft",
            "label": "DPEntity",
            "properties": ["title", "id", "search_text"],
            "call": "CALL db.index.fulltext.queryNodes('dp_entity_ft', $q) YIELD node, score",
        },
        "limits": {"rows": 100},
    }


def _call_tool(
    condition: str,
    name: str,
    args: dict[str, Any],
    graph: Graph | None,
    cursor: Cursor | None,
    session: str,
    *,
    mcp_bridge: _McpStdioBridge | None = None,
) -> tuple[dict[str, Any], Cursor | None, int]:
    if condition in {"cursor", "waygraph"}:
        allowed = (
            {"search_nodes", "start_walk", "inspect_walk", "follow_edge", "backtrack", "get_walk"}
            if condition == "cursor"
            else {"search_nodes", "start_walk", "inspect_walk", "take_shortcut", "follow_edge", "backtrack", "get_walk", "save_shortcut"}
        )
        if name not in allowed:
            raise ValueError(f"Unknown {condition} tool: {name}")

        if mcp_bridge is not None:
            if name == "search_nodes":
                data = mcp_bridge.call_tool(
                    "search_nodes",
                    {
                        "query": args["query"],
                        "label": args.get("label") or "",
                        "limit": int(args.get("limit", 10)),
                    },
                )
                return data, cursor, 1
            if name == "start_walk":
                data = mcp_bridge.call_tool(
                    "start_walk",
                    {
                        "session": session,
                        "origin": args["origin"],
                        "max_hops": int(args.get("max_hops", 8)),
                    },
                )
                return (_strip_shortcuts(data) if condition == "cursor" else data), cursor, 1
            if name in {"inspect_walk", "backtrack", "get_walk", "save_shortcut"}:
                data = mcp_bridge.call_tool(name, {"session": session})
                if condition == "cursor" and name in {"inspect_walk", "backtrack"}:
                    data = _strip_shortcuts(data)
                return data, cursor, 1
            if name == "follow_edge":
                data = mcp_bridge.call_tool("follow_edge", {"session": session, "edge_id": args["edge_id"]})
                return (_strip_shortcuts(data) if condition == "cursor" else data), cursor, 1
            if name == "take_shortcut":
                data = mcp_bridge.call_tool("take_shortcut", {"session": session, "shortcut_id": args["shortcut_id"]})
                return data, cursor, 1

        if graph is None:
            raise RuntimeError("Graph instance is required for in-process tool execution")
        if name == "search_nodes":
            nodes = graph.search_nodes(
                args["query"],
                label=args.get("label") or None,
                limit=int(args.get("limit", 10)),
            )
            return {"nodes": nodes}, cursor, 1
        if name == "start_walk":
            cursor = Cursor(graph, args["origin"], max_hops=int(args.get("max_hops", 8)))
            data = cursor.inspect()
            if condition == "cursor":
                cursor._offered_shortcuts.clear()
                data = _strip_shortcuts(data)
            return data, cursor, 1
        if cursor is None:
            raise GraphError("Start the requested walk before using cursor tools", "CURSOR_NOT_STARTED")
        if name == "inspect_walk":
            data = cursor.inspect()
            if condition == "cursor":
                cursor._offered_shortcuts.clear()
                data = _strip_shortcuts(data)
            return data, cursor, 1
        if name == "follow_edge":
            data = cursor.follow(args["edge_id"])
            if condition == "cursor":
                cursor._offered_shortcuts.clear()
                data = _strip_shortcuts(data)
            return data, cursor, 1
        if name == "take_shortcut":
            return cursor.take_shortcut(args["shortcut_id"]), cursor, 1
        if name == "backtrack":
            data = cursor.backtrack()
            if condition == "cursor":
                cursor._offered_shortcuts.clear()
                data = _strip_shortcuts(data)
            return data, cursor, 1
        if name == "get_walk":
            return cursor.get_walk(), cursor, 1
        if name == "save_shortcut":
            learned = learn(graph, cursor.nodes[0], cursor.current, cursor.edges, observation_id=cursor.walk_id)
            return learned, cursor, 1
        raise ValueError(f"Unknown {condition} tool: {name}")

    if condition != "native-cypher":
        raise ValueError(f"Unsupported condition: {condition}")
    if graph is None:
        raise RuntimeError("native-cypher requires an in-process Graph instance")
    if name == "inspect_schema":
        return _inspect_native_schema(graph), cursor, 1
    if name == "query_graph":
        query = args.get("query")
        _validate_read_query(query)
        if not re.search(r"\bLIMIT\s+\d+\b", query, re.I):
            query = query.rstrip() + " LIMIT 100"
        rows = graph.query(query, args.get("params") or {})
        if len(rows) > 100:
            rows = rows[:100]
        return {"rows": rows, "count": len(rows)}, cursor, 1
    raise ValueError(f"Unknown native query tool: {name}")


def _apply_single_mutation(graph: Graph, spec: dict[str, Any]) -> dict[str, Any]:
    op = spec.get("op") or spec.get("action") or spec.get("type") or spec.get("kind") or spec.get("method")
    params = spec
    if not op:
        for candidate in ("disable_edge", "retarget_edge", "update_edge_property"):
            if candidate in spec:
                op = candidate
                raw = spec[candidate]
                params = {"edge_id": raw} if isinstance(raw, str) else dict(raw)
                break
    if op == "disable_edge":
        edge_id = params["edge_id"]
        graph.disable_edge(edge_id)
        return {"op": "disable_edge", "edge_id": edge_id}
    if op == "retarget_edge":
        edge_id = params["edge_id"]
        source = params.get("source")
        target = params.get("target")
        graph.retarget_edge(edge_id, source=source, target=target)
        return {"op": "retarget_edge", "edge_id": edge_id, "source": source, "target": target}
    if op == "update_edge_property":
        edge_id = params["edge_id"]
        key = params["key"]
        value = params["value"]
        graph.update_edge_property(edge_id, key, value)
        return {"op": "update_edge_property", "edge_id": edge_id, "key": key, "value": value}
    raise ValueError(f"Unsupported before_mutation operation: {op!r}")


def _apply_before_mutation(graph: Graph, before_mutation: dict[str, Any] | list[dict[str, Any]]) -> list[dict[str, Any]]:
    specs = before_mutation if isinstance(before_mutation, list) else [before_mutation]
    return [_apply_single_mutation(graph, item) for item in specs]


def _system_prompt(condition: str, *, style: str = "tools") -> str:
    noun = "functions" if style == "functions" else "tools"
    if condition == "waygraph":
        return (
            f"Answer the graph traversal task using only the available {noun}. "
            "Prefer take_shortcut when an offered shortcut advances along the requested route; "
            "if take_shortcut fails validation (SHORTCUT_STALE), fall back to follow_edge on live offered neighbors. "
            "Return only the exact final graph node ID, with no explanation. Do not guess an ID."
        )
    if condition == "native-cypher":
        return (
            f"Answer the graph traversal task using only the available {noun}. "
            "Inspect the graph schema if needed and run bounded read-only Cypher queries. "
            "Return only the exact final graph node ID, with no explanation. Do not guess an ID."
        )
    return (
        f"Answer the graph traversal task using only the available {noun}. "
        "Return only the exact final graph node ID, with no explanation. "
        "The requested route is specified in the task. Do not guess an ID."
    )


def _valid_shortcut_fingerprints(
    graph: Graph | None,
    mcp_bridge: _McpStdioBridge | None,
    origin: str | None = None,
    target: str | None = None,
) -> dict[str, str]:
    if mcp_bridge is not None:
        resp = mcp_bridge.call_tool(
            "find_shortcuts",
            {
                "origin": origin or "",
                "target": target or "",
                "include_non_valid": False,
                "validate": False,
                "limit": 100,
            },
        )
        items = resp.get("shortcuts") or []
    elif graph is not None:
        items = list_shortcuts(graph, origin=origin, target=target, include_non_valid=False, limit=100)
    else:
        items = []
    return {item["shortcut_id"]: item["fingerprint"] for item in items if "shortcut_id" in item and "fingerprint" in item}


def _execute_tool_step(
    condition: str,
    name: str,
    args: dict[str, Any],
    graph: Graph | None,
    cursor: Cursor | None,
    session: str,
    mcp_bridge: _McpStdioBridge | None,
) -> tuple[dict[str, Any], Cursor | None, int, str | None, int, int]:
    """Execute one tool call, returning (result, cursor, rows, error_type, stale_rejections, newly_promoted)."""
    stale_rejections = 0
    newly_promoted = 0
    before_valid: dict[str, str] = {}
    if condition == "waygraph" and name == "save_shortcut":
        try:
            before_valid = _valid_shortcut_fingerprints(graph, mcp_bridge)
        except Exception:
            before_valid = {}
    try:
        result, cursor, rows = _call_tool(condition, name, args, graph, cursor, session, mcp_bridge=mcp_bridge)
        if condition == "waygraph" and name == "save_shortcut" and isinstance(result, dict):
            sid = result.get("id")
            fp = result.get("fingerprint")
            if result.get("promoted") and sid and before_valid.get(sid) != fp:
                newly_promoted = 1
        return result, cursor, rows, None, 0, newly_promoted
    except GraphError as exc:
        if exc.code == "SHORTCUT_STALE":
            stale_rejections = 1
        return {"error": str(exc)[:500], "code": exc.code}, cursor, 0, type(exc).__name__, stale_rejections, 0
    except Exception as exc:
        return {"error": str(exc)[:500]}, cursor, 0, type(exc).__name__, 0, 0


def _resolve_walk_and_autolearn(
    *,
    condition: str,
    error: str | None,
    normalized_answer: str,
    graph: Graph | None,
    cursor: Cursor | None,
    session: str,
    mcp_bridge: _McpStdioBridge | None,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]], int]:
    walk: dict[str, Any] | None = None
    if cursor is not None:
        walk = cursor.get_walk()
    elif mcp_bridge is not None and condition in {"cursor", "waygraph"}:
        try:
            walk = mcp_bridge.call_tool("get_walk", {"session": session})
        except GraphError:
            walk = None

    auto_learned: list[dict[str, Any]] = []
    newly_promoted = 0
    if (
        condition != "waygraph"
        or error is not None
        or walk is None
        or (walk.get("shortcuts_used") or [])
    ):
        return walk, auto_learned, newly_promoted

    edges = list(walk.get("edges") or [])
    nodes = list(walk.get("nodes") or [])
    current_node = str(walk.get("current") or "")
    walk_id = str(walk.get("walk_id") or uuid4().hex)
    if (
        len(edges) < 2
        or len(nodes) != len(edges) + 1
        or len(set(nodes)) != len(nodes)
        or not normalized_answer
        or (normalized_answer != current_node and current_node not in normalized_answer)
    ):
        return walk, auto_learned, newly_promoted

    if mcp_bridge is not None:
        try:
            before_full = _valid_shortcut_fingerprints(None, mcp_bridge, origin=nodes[0], target=nodes[-1])
            learned_full = mcp_bridge.call_tool("save_shortcut", {"session": session})
            auto_learned.append(learned_full)
            if learned_full.get("promoted") and before_full.get(learned_full.get("id", "")) != learned_full.get("fingerprint"):
                newly_promoted += 1
            if len(edges) >= 3:
                for _ in range(len(edges) - 2):
                    mcp_bridge.call_tool("backtrack", {"session": session})
                before_prefix = _valid_shortcut_fingerprints(None, mcp_bridge, origin=nodes[0], target=nodes[2])
                learned_prefix = mcp_bridge.call_tool("save_shortcut", {"session": session})
                auto_learned.append(learned_prefix)
                if learned_prefix.get("promoted") and before_prefix.get(learned_prefix.get("id", "")) != learned_prefix.get("fingerprint"):
                    newly_promoted += 1
        except GraphError:
            pass
        return walk, auto_learned, newly_promoted

    if graph is not None and not graph.read_only:
        corridors: list[tuple[str, str, list[str], str]] = [
            (nodes[0], nodes[-1], edges, walk_id),
        ]
        if len(edges) >= 3:
            corridors.append((nodes[0], nodes[2], edges[:2], f"{walk_id}:prefix2"))
        for origin, target, sub_edges, obs_id in corridors:
            try:
                before = _valid_shortcut_fingerprints(graph, None, origin=origin, target=target)
                learned = learn(graph, origin, target, sub_edges, observation_id=obs_id)
                auto_learned.append(learned)
                if learned.get("promoted") and before.get(learned["id"]) != learned.get("fingerprint"):
                    newly_promoted += 1
            except GraphError:
                pass
    return walk, auto_learned, newly_promoted


def _maybe_apply_question_mutation(question: dict[str, Any], graph: Graph | None) -> list[dict[str, Any]] | None:
    mutation = question.get("before_mutation")
    if not mutation or question.get("_mutation_applied"):
        return question.get("_applied_mutations")
    if graph is None:
        raise RuntimeError("before_mutation requires a writable Graph instance")
    return _apply_before_mutation(graph, mutation)


def _content_payload(block: Any) -> dict[str, Any]:
    if hasattr(block, "model_dump"):
        return block.model_dump(mode="json")
    if isinstance(block, dict):
        return block
    result = {"type": getattr(block, "type", "unknown")}
    for field in ("id", "name", "input", "text"):
        if hasattr(block, field):
            result[field] = getattr(block, field)
    return result


def _build_question_result(
    *,
    question: dict[str, Any],
    condition: str,
    model: str,
    answer: str,
    normalized: str,
    input_tokens: int,
    output_tokens: int,
    tool_calls: int,
    max_tokens: int,
    elapsed_ms: float,
    error: str | None,
    walk: dict[str, Any] | None,
    tool_trace: list[dict[str, Any]],
    stale_shortcut_rejections: int,
    shortcuts_promoted: int,
    auto_learned: list[dict[str, Any]],
    applied_mutations: list[dict[str, Any]] | None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    shortcut_hits = len(walk.get("shortcuts_used") or []) if walk else 0
    cursor_steps = walk.get("cursor_steps") if walk and "cursor_steps" in walk else None
    payload: dict[str, Any] = {
        "question_id": question["question_id"],
        "question": question["question"],
        "condition": condition,
        "graph_snapshot_id": question["graph_snapshot_id"],
        "model_id": model,
        **(extra or {}),
        "answer": answer,
        "gold_answer": question["answer"],
        "is_correct": normalized == question["answer"],
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "tool_calls": tool_calls,
        "temperature": 0.0,
        "max_tokens": max_tokens,
        "traversal_hops": len(walk["edges"]) if walk else None,
        "cursor_steps": cursor_steps,
        "shortcut_hits": shortcut_hits,
        "stale_shortcut_rejections": stale_shortcut_rejections,
        "shortcuts_promoted": shortcuts_promoted,
        "latency_ms": elapsed_ms,
        "error": error,
        "walk": walk,
        "tool_trace": tool_trace,
    }
    if auto_learned:
        payload["auto_learned_shortcuts"] = auto_learned
    if applied_mutations:
        payload["applied_mutations"] = applied_mutations
    return payload


def _run_one(
    client: Any,
    model: str,
    max_tokens: int,
    max_tool_calls: int,
    condition: str,
    question: dict[str, Any],
    graph: Graph | None,
    *,
    mcp_bridge: _McpStdioBridge | None = None,
) -> dict[str, Any]:
    applied_mutations = _maybe_apply_question_mutation(question, graph)
    session = "eval-" + uuid4().hex
    cursor = None
    system = _system_prompt(condition, style="tools")
    messages: list[dict[str, Any]] = [{"role": "user", "content": question["question"]}]
    tool_calls = 0
    input_tokens = output_tokens = 0
    stale_rejections = 0
    shortcuts_promoted = 0
    tool_trace: list[dict[str, Any]] = []
    started = time.perf_counter_ns()
    answer = ""
    error = None
    tools_spec = _anthropic_tools(condition)
    for _ in range(max_tool_calls + 1):
        response = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            temperature=0.0,
            system=system,
            messages=messages,
            tools=tools_spec,
        )
        input_tokens += getattr(response.usage, "input_tokens", 0)
        output_tokens += getattr(response.usage, "output_tokens", 0)
        blocks = [_content_payload(block) for block in response.content]
        messages.append({"role": "assistant", "content": blocks})
        tool_uses = [block for block in response.content if getattr(block, "type", None) == "tool_use"]
        if not tool_uses:
            answer = "\n".join(
                getattr(block, "text", "") for block in response.content if getattr(block, "type", None) == "text"
            ).strip()
            break
        results = []
        for block in tool_uses:
            if tool_calls >= max_tool_calls:
                error = "TOOL_CALL_LIMIT"
                break
            tool_calls += 1
            tool_started = time.perf_counter_ns()
            tool_args = dict(block.input)
            if condition in {"cursor", "waygraph"}:
                tool_args["session"] = session
            result, cursor, rows, tool_error, step_stale, step_promoted = _execute_tool_step(
                condition, block.name, tool_args, graph, cursor, session, mcp_bridge
            )
            stale_rejections += step_stale
            shortcuts_promoted += step_promoted
            elapsed_ms = (time.perf_counter_ns() - tool_started) / 1e6
            tool_trace.append(
                {
                    "name": block.name,
                    "input": block.input,
                    "result": result,
                    "error_type": tool_error,
                    "latency_ms": elapsed_ms,
                    "rows": rows,
                }
            )
            results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": json.dumps(result, ensure_ascii=False),
                    **({"is_error": True} if tool_error else {}),
                }
            )
        if error:
            break
        messages.append({"role": "user", "content": results})
    else:
        error = "TURN_LIMIT"
    elapsed_ms = (time.perf_counter_ns() - started) / 1e6
    normalized = answer.strip().strip("`\"' ")
    walk, auto_learned, auto_promoted = _resolve_walk_and_autolearn(
        condition=condition,
        error=error,
        normalized_answer=normalized,
        graph=graph,
        cursor=cursor,
        session=session,
        mcp_bridge=mcp_bridge,
    )
    shortcuts_promoted += auto_promoted
    return _build_question_result(
        question=question,
        condition=condition,
        model=model,
        answer=answer,
        normalized=normalized,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        tool_calls=tool_calls,
        max_tokens=max_tokens,
        elapsed_ms=elapsed_ms,
        error=error,
        walk=walk,
        tool_trace=tool_trace,
        stale_shortcut_rejections=stale_rejections,
        shortcuts_promoted=shortcuts_promoted,
        auto_learned=auto_learned,
        applied_mutations=applied_mutations,
    )


def _run_one_gemini(
    client: Any,
    genai_types: Any,
    model: str,
    max_tokens: int,
    max_tool_calls: int,
    condition: str,
    question: dict[str, Any],
    graph: Graph | None,
    *,
    mcp_bridge: _McpStdioBridge | None = None,
) -> dict[str, Any]:
    applied_mutations = _maybe_apply_question_mutation(question, graph)
    session = "eval-" + uuid4().hex
    cursor = None
    system = _system_prompt(condition, style="functions")
    contents: list[Any] = [genai_types.Content(role="user", parts=[genai_types.Part.from_text(text=question["question"])])]
    declarations = [
        genai_types.FunctionDeclaration(name=spec["name"], description=spec["description"], parameters=spec["input_schema"])
        for spec in _anthropic_tools(condition)
    ]
    tool = genai_types.Tool(function_declarations=declarations)
    config = genai_types.GenerateContentConfig(
        system_instruction=system,
        tools=[tool],
        temperature=0.0,
        max_output_tokens=max_tokens,
    )
    tool_calls = input_tokens = output_tokens = 0
    stale_rejections = 0
    shortcuts_promoted = 0
    tool_trace: list[dict[str, Any]] = []
    started = time.perf_counter_ns()
    answer = ""
    error = None
    for _ in range(max_tool_calls + 1):
        response = client.models.generate_content(model=model, contents=contents, config=config)
        usage = getattr(response, "usage_metadata", None)
        input_tokens += getattr(usage, "prompt_token_count", 0) if usage else 0
        output_tokens += getattr(usage, "candidates_token_count", 0) if usage else 0
        candidate = response.candidates[0] if getattr(response, "candidates", None) else None
        model_content = getattr(candidate, "content", None) if candidate else None
        parts = list(getattr(model_content, "parts", []) or [])
        function_calls = [part.function_call for part in parts if getattr(part, "function_call", None) is not None]
        if not function_calls:
            answer = "".join(getattr(part, "text", "") or "" for part in parts).strip()
            break
        contents.append(model_content)
        function_responses = []
        for function_call in function_calls:
            if tool_calls >= max_tool_calls:
                error = "TOOL_CALL_LIMIT"
                break
            tool_calls += 1
            args = dict(getattr(function_call, "args", {}) or {})
            if condition in {"cursor", "waygraph"}:
                args["session"] = session
            tool_started = time.perf_counter_ns()
            result, cursor, rows, tool_error, step_stale, step_promoted = _execute_tool_step(
                condition, function_call.name, args, graph, cursor, session, mcp_bridge
            )
            stale_rejections += step_stale
            shortcuts_promoted += step_promoted
            elapsed_ms = (time.perf_counter_ns() - tool_started) / 1e6
            tool_trace.append(
                {
                    "name": function_call.name,
                    "input": args,
                    "result": result,
                    "error_type": tool_error,
                    "latency_ms": elapsed_ms,
                    "rows": rows,
                }
            )
            function_responses.append(genai_types.Part.from_function_response(name=function_call.name, response=result))
        if error:
            break
        contents.append(genai_types.Content(role="user", parts=function_responses))
    else:
        error = "TURN_LIMIT"
    elapsed_ms = (time.perf_counter_ns() - started) / 1e6
    normalized = answer.strip().strip("`\"' ")
    walk, auto_learned, auto_promoted = _resolve_walk_and_autolearn(
        condition=condition,
        error=error,
        normalized_answer=normalized,
        graph=graph,
        cursor=cursor,
        session=session,
        mcp_bridge=mcp_bridge,
    )
    shortcuts_promoted += auto_promoted
    return _build_question_result(
        question=question,
        condition=condition,
        model=model,
        answer=answer,
        normalized=normalized,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        tool_calls=tool_calls,
        max_tokens=max_tokens,
        elapsed_ms=elapsed_ms,
        error=error,
        walk=walk,
        tool_trace=tool_trace,
        stale_shortcut_rejections=stale_rejections,
        shortcuts_promoted=shortcuts_promoted,
        auto_learned=auto_learned,
        applied_mutations=applied_mutations,
    )


def _run_one_openrouter(
    client: Any,
    model: str,
    max_tokens: int,
    max_tool_calls: int,
    condition: str,
    question: dict[str, Any],
    graph: Graph | None,
    *,
    mcp_bridge: _McpStdioBridge | None = None,
) -> dict[str, Any]:
    applied_mutations = _maybe_apply_question_mutation(question, graph)
    session = "eval-" + uuid4().hex
    cursor = None
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": _system_prompt(condition, style="functions")},
        {"role": "user", "content": question["question"]},
    ]
    tools = [
        {"type": "function", "function": {"name": spec["name"], "description": spec["description"], "parameters": spec["input_schema"]}}
        for spec in _anthropic_tools(condition)
    ]
    tool_calls = input_tokens = output_tokens = 0
    stale_rejections = 0
    shortcuts_promoted = 0
    tool_trace: list[dict[str, Any]] = []
    started = time.perf_counter_ns()
    answer = ""
    error = None
    models_served: list[str] = []
    model_turns: list[dict[str, Any]] = []
    for _ in range(max_tool_calls + 1):
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            tools=tools,
            temperature=0.0,
            max_tokens=max_tokens,
            parallel_tool_calls=False,
            session_id=session,
        )
        response_model = getattr(response, "model", None) or model
        models_served.append(response_model)
        usage = getattr(response, "usage", None)
        turn_input_tokens = getattr(usage, "prompt_tokens", 0) if usage else 0
        turn_output_tokens = getattr(usage, "completion_tokens", 0) if usage else 0
        input_tokens += turn_input_tokens
        output_tokens += turn_output_tokens
        choice = response.choices[0]
        model_turns.append(
            {
                "model_served": response_model,
                "finish_reason": getattr(choice, "finish_reason", None),
                "input_tokens": turn_input_tokens,
                "output_tokens": turn_output_tokens,
            }
        )
        message = choice.message
        calls = list(getattr(message, "tool_calls", None) or [])
        if not calls:
            answer = (getattr(message, "content", None) or "").strip()
            break
        assistant_message = (
            message.model_dump(exclude_none=True)
            if hasattr(message, "model_dump")
            else {
                "role": "assistant",
                "content": getattr(message, "content", None),
                "tool_calls": [call.model_dump(exclude_none=True) if hasattr(call, "model_dump") else call for call in calls],
            }
        )
        messages.append(assistant_message)
        for call in calls:
            if tool_calls >= max_tool_calls:
                error = "TOOL_CALL_LIMIT"
                break
            tool_calls += 1
            tool_started = time.perf_counter_ns()
            try:
                raw_arguments = call.function.arguments
                args = raw_arguments if isinstance(raw_arguments, dict) else json.loads(raw_arguments or "{}")
                if not isinstance(args, dict):
                    raise ValueError("Tool arguments must be a JSON object")
            except (json.JSONDecodeError, ValueError) as exc:
                args = {}
                result, rows, tool_error = {"error": str(exc)}, 0, type(exc).__name__
            else:
                if condition in {"cursor", "waygraph"}:
                    args["session"] = session
                result, cursor, rows, tool_error, step_stale, step_promoted = _execute_tool_step(
                    condition, call.function.name, args, graph, cursor, session, mcp_bridge
                )
                stale_rejections += step_stale
                shortcuts_promoted += step_promoted
            elapsed_ms = (time.perf_counter_ns() - tool_started) / 1e6
            tool_trace.append(
                {
                    "name": call.function.name,
                    "input": args,
                    "result": result,
                    "error_type": tool_error,
                    "latency_ms": elapsed_ms,
                    "rows": rows,
                    "model_served": response_model,
                }
            )
            messages.append({"role": "tool", "tool_call_id": call.id, "content": json.dumps(result, ensure_ascii=False)})
        if error:
            break
    else:
        error = "TURN_LIMIT"
    elapsed_ms = (time.perf_counter_ns() - started) / 1e6
    normalized = answer.strip().strip("`\"' ")
    walk, auto_learned, auto_promoted = _resolve_walk_and_autolearn(
        condition=condition,
        error=error,
        normalized_answer=normalized,
        graph=graph,
        cursor=cursor,
        session=session,
        mcp_bridge=mcp_bridge,
    )
    shortcuts_promoted += auto_promoted
    return _build_question_result(
        question=question,
        condition=condition,
        model=model,
        answer=answer,
        normalized=normalized,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        tool_calls=tool_calls,
        max_tokens=max_tokens,
        elapsed_ms=elapsed_ms,
        error=error,
        walk=walk,
        tool_trace=tool_trace,
        stale_shortcut_rejections=stale_rejections,
        shortcuts_promoted=shortcuts_promoted,
        auto_learned=auto_learned,
        applied_mutations=applied_mutations,
        extra={"models_served": models_served, "model_turns": model_turns},
    )


def _load_resumed_answers(trace_path: Path) -> tuple[dict[str, dict[str, Any]], str | None]:
    if not trace_path.exists():
        return {}, None
    answered_by_qid: dict[str, dict[str, Any]] = {}
    existing_run_id: str | None = None
    for line in trace_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if existing_run_id is None and isinstance(row.get("run_id"), str):
            existing_run_id = row["run_id"]
        qid = row.get("question_id")
        if isinstance(qid, str) and row.get("error") is None:
            answered_by_qid[qid] = row
    return answered_by_qid, existing_run_id


def _load_questions_for_store(
    *,
    question_file: Path,
    graph: Graph,
    document: Any,
    source_sha256: str,
    split: str | None,
    allow_mutated_store: bool,
) -> tuple[str, list[dict[str, Any]]]:
    current_snapshot_id = graph.snapshot_id()
    try:
        questions = load_question_set(question_file, expected_snapshot_id=current_snapshot_id, split=split)
        return current_snapshot_id, questions
    except ValueError:
        if not allow_mutated_store:
            raise
        with Graph(":memory:") as clean_graph:
            clean_graph.import_source_graph(document, source_sha256)
            clean_snapshot_id = clean_graph.snapshot_id()
        questions = load_question_set(question_file, expected_snapshot_id=clean_snapshot_id, split=split)
        return clean_snapshot_id, questions


def _build_provider_client(provider: str, key_name: str | None, genai_mod: Any = None, anthropic_mod: Any = None) -> Any:
    if provider == "gemini":
        return genai_mod.Client(api_key=os.environ[key_name])  # type: ignore[index]
    if provider == "anthropic":
        return anthropic_mod.Anthropic(api_key=os.environ[key_name], timeout=120.0, max_retries=0)  # type: ignore[index]
    if provider == "ollama":
        base_url = os.environ.get("OLLAMA_CHAT_URL", "").strip() or _OPENAI_COMPAT_URLS["ollama"]
        api_key = os.environ.get("OLLAMA_API_KEY", "").strip()
        return _OpenRouterClient(api_key=api_key, timeout=120.0, base_url=base_url, provider_name="Ollama")
    assert key_name is not None
    return _OpenRouterClient(
        api_key=os.environ[key_name],
        timeout=120.0,
        base_url=_OPENAI_COMPAT_URLS[provider],
        provider_name=_PROVIDER_DISPLAY[provider],
    )


def run_agent_evaluation(
    *,
    source_file: Path,
    question_file: Path,
    output: Path,
    condition: str,
    model: str,
    provider: str = "openrouter",
    repetitions: int = 1,
    split: str | None = "pilot",
    max_tool_calls: int = 20,
    max_tokens: int = 2048,
    transport: str = "in-process",
    resume: bool = False,
    client: Any | None = None,
) -> dict[str, Any]:
    """Run isolated or resumable model trials across cursor, waygraph, and native-cypher."""
    if condition not in _CONDITIONS:
        raise ValueError("condition must be cursor, waygraph, or native-cypher")
    if provider not in _PROVIDER_KEY_ENV:
        raise ValueError("provider must be openrouter, gemini, groq, cerebras, ollama, or anthropic")
    if transport not in _TRANSPORTS:
        raise ValueError("transport must be in-process or mcp-stdio")
    if transport == "mcp-stdio" and condition == "native-cypher":
        raise ValueError("mcp-stdio transport supports cursor and waygraph conditions")
    if not model or not model.strip():
        model = _DEFAULT_MODELS.get(provider, "")
    if not model or not model.strip() or not 1 <= repetitions <= 20 or not 1 <= max_tool_calls <= 100:
        raise ValueError("model is required; repetitions must be 1..20 and max_tool_calls 1..100")

    key_name = _PROVIDER_KEY_ENV[provider]
    if client is None and key_name is not None and not os.environ.get(key_name):
        raise RuntimeError(f"{key_name} is required for {provider} agent evaluation")

    genai_mod = None
    genai_types = None
    anthropic_mod = None
    if client is None:
        try:
            if provider == "gemini":
                from google import genai as genai_mod
                from google.genai import types as genai_types
            elif provider == "anthropic":
                import anthropic as anthropic_mod
        except ImportError as exc:
            package = {"gemini": "google-genai", "anthropic": "anthropic"}.get(provider, "Python standard library")
            raise RuntimeError(f"Install {package} before {provider} agent evaluation") from exc

    effective_split = None if split in (None, "all") else split
    source_bytes = source_file.read_bytes()
    source_sha256 = hashlib.sha256(source_bytes).hexdigest()
    document = json.loads(source_bytes)
    output.mkdir(parents=True, exist_ok=True)
    reports = []
    question_sha256 = hashlib.sha256(question_file.read_bytes()).hexdigest()

    for repetition in range(1, repetitions + 1):
        store = output / "stores" / f"{condition}-{repetition:03d}"
        trace_path = output / f"{condition}-{repetition:03d}.jsonl"
        store_existed = store.exists()
        if store_existed and not resume:
            raise ValueError(f"Evaluation store already exists; choose an empty output directory: {store}")
        store.parent.mkdir(parents=True, exist_ok=True)

        answered_by_qid, previous_run_id = _load_resumed_answers(trace_path) if (resume and store_existed) else ({}, None)
        run_id = previous_run_id or uuid4().hex
        active_client = client if client is not None else _build_provider_client(provider, key_name, genai_mod, anthropic_mod)

        results: list[dict[str, Any]] = []
        fatal_error: str | None = None
        fatal_status: str | None = None

        if transport == "in-process":
            with Graph(str(store)) as graph:
                if store_existed and resume:
                    imported = {
                        "resumed": True,
                        "source_sha256": source_sha256,
                        "entities": graph.query("MATCH (n:DPEntity) RETURN count(n) AS c")[0]["c"],
                        "relationships": graph.query("MATCH (e:DPEdge) RETURN count(e) AS c")[0]["c"],
                    }
                else:
                    imported = graph.import_source_graph(document, source_sha256)
                snapshot_id, questions = _load_questions_for_store(
                    question_file=question_file,
                    graph=graph,
                    document=document,
                    source_sha256=source_sha256,
                    split=effective_split,
                    allow_mutated_store=bool(store_existed and resume),
                )
                with trace_path.open("w", encoding="utf-8") as trace_file:
                    for idx, question in enumerate(questions):
                        qid = question["question_id"]
                        if qid in answered_by_qid:
                            prior = answered_by_qid[qid]
                            trace_file.write(json.dumps(prior, ensure_ascii=False) + "\n")
                            trace_file.flush()
                            results.append(prior)
                            continue
                        result, fatal_error, fatal_status = _execute_trial_question(
                            provider=provider,
                            client=active_client,
                            genai_types=genai_types,
                            model=model,
                            max_tokens=max_tokens,
                            max_tool_calls=max_tool_calls,
                            condition=condition,
                            question=question,
                            graph=graph,
                            mcp_bridge=None,
                            run_id=run_id,
                            repetition=repetition,
                        )
                        trace_file.write(json.dumps(result, ensure_ascii=False) + "\n")
                        trace_file.flush()
                        results.append(result)
                        if fatal_error:
                            for rem_q in questions[idx + 1 :]:
                                rem_id = rem_q["question_id"]
                                if rem_id in answered_by_qid:
                                    saved = answered_by_qid[rem_id]
                                    trace_file.write(json.dumps(saved, ensure_ascii=False) + "\n")
                                    results.append(saved)
                            trace_file.flush()
                            break
        else:
            with Graph(str(store)) as setup_graph:
                if store_existed and resume:
                    imported = {
                        "resumed": True,
                        "source_sha256": source_sha256,
                        "entities": setup_graph.query("MATCH (n:DPEntity) RETURN count(n) AS c")[0]["c"],
                        "relationships": setup_graph.query("MATCH (e:DPEdge) RETURN count(e) AS c")[0]["c"],
                    }
                else:
                    imported = setup_graph.import_source_graph(document, source_sha256)
                snapshot_id, questions = _load_questions_for_store(
                    question_file=question_file,
                    graph=setup_graph,
                    document=document,
                    source_sha256=source_sha256,
                    split=effective_split,
                    allow_mutated_store=bool(store_existed and resume),
                )
            mcp_bridge: _McpStdioBridge | None = None
            try:
                with trace_path.open("w", encoding="utf-8") as trace_file:
                    for idx, question in enumerate(questions):
                        qid = question["question_id"]
                        if qid in answered_by_qid:
                            prior = answered_by_qid[qid]
                            trace_file.write(json.dumps(prior, ensure_ascii=False) + "\n")
                            trace_file.flush()
                            results.append(prior)
                            continue
                        run_question = question
                        if question.get("before_mutation"):
                            if mcp_bridge is not None:
                                mcp_bridge.close()
                                mcp_bridge = None
                            with Graph(str(store)) as mut_graph:
                                applied = _apply_before_mutation(mut_graph, question["before_mutation"])
                            run_question = {**question, "_mutation_applied": True, "_applied_mutations": applied}
                        if mcp_bridge is None:
                            mcp_bridge = _McpStdioBridge(store).open()
                        result, fatal_error, fatal_status = _execute_trial_question(
                            provider=provider,
                            client=active_client,
                            genai_types=genai_types,
                            model=model,
                            max_tokens=max_tokens,
                            max_tool_calls=max_tool_calls,
                            condition=condition,
                            question=run_question,
                            graph=None,
                            mcp_bridge=mcp_bridge,
                            run_id=run_id,
                            repetition=repetition,
                        )
                        trace_file.write(json.dumps(result, ensure_ascii=False) + "\n")
                        trace_file.flush()
                        results.append(result)
                        if fatal_error:
                            for rem_q in questions[idx + 1 :]:
                                rem_id = rem_q["question_id"]
                                if rem_id in answered_by_qid:
                                    saved = answered_by_qid[rem_id]
                                    trace_file.write(json.dumps(saved, ensure_ascii=False) + "\n")
                                    results.append(saved)
                            trace_file.flush()
                            break
            finally:
                if mcp_bridge is not None:
                    mcp_bridge.close()

        reports.append(
            {
                "run_id": run_id,
                "repetition": repetition,
                "store": str(store),
                "transport": transport,
                "resumed": bool(store_existed and resume),
                "graph_snapshot_id": snapshot_id,
                "import": imported,
                "trace_path": str(trace_path),
                "question_set_count": len(questions),
                "not_attempted_questions": len(questions) - len(results),
                "count": len(results),
                "status": fatal_status or "complete",
                "fatal_error": fatal_error,
                **_agent_result_metrics(results),
                **_agent_shortcut_metrics(results),
                "results": results,
            }
        )

    sdk_distribution = {"gemini": "google-genai", "anthropic": "anthropic"}.get(provider)
    try:
        sdk_version = version(sdk_distribution) if sdk_distribution else "stdlib-urllib"
    except PackageNotFoundError:
        sdk_version = None
    all_results = [row for trial in reports for row in trial["results"]]
    latencies = [row["latency_ms"] for row in all_results if row["latency_ms"] is not None]
    report = {
        "mode": f"{provider}_tool_agent",
        "provider": provider,
        "condition": condition,
        "transport": transport,
        "resumed": resume,
        "model_id": model,
        "sdk_version": sdk_version,
        "python_version": sys.version,
        "platform": platform.platform(),
        "source_sha256": source_sha256,
        "question_sha256": question_sha256,
        "split": split if split is not None else "all",
        "repetitions": repetitions,
        "temperature": 0.0,
        "max_tokens": max_tokens,
        "max_tool_calls": max_tool_calls,
        "aggregate": {
            "total_runs": len(all_results),
            **_agent_result_metrics(all_results),
            **_agent_shortcut_metrics(all_results),
            "question_set_total": sum(trial["question_set_count"] for trial in reports),
            "not_attempted_questions": sum(trial["not_attempted_questions"] for trial in reports),
            "mean_latency_ms": sum(latencies) / len(latencies) if latencies else None,
            "latency_population_stddev_ms": statistics.pstdev(latencies) if latencies else None,
        },
        "reports": reports,
    }
    (output / f"{condition}-summary.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def _execute_trial_question(
    *,
    provider: str,
    client: Any,
    genai_types: Any,
    model: str,
    max_tokens: int,
    max_tool_calls: int,
    condition: str,
    question: dict[str, Any],
    graph: Graph | None,
    mcp_bridge: _McpStdioBridge | None,
    run_id: str,
    repetition: int,
) -> tuple[dict[str, Any], str | None, str | None]:
    fatal_error: str | None = None
    fatal_status: str | None = None
    try:
        if provider == "gemini":
            result = _run_one_gemini(
                client, genai_types, model, max_tokens, max_tool_calls, condition, question, graph, mcp_bridge=mcp_bridge
            )
        elif provider == "anthropic":
            result = _run_one(
                client, model, max_tokens, max_tool_calls, condition, question, graph, mcp_bridge=mcp_bridge
            )
        else:
            result = _run_one_openrouter(
                client, model, max_tokens, max_tool_calls, condition, question, graph, mcp_bridge=mcp_bridge
            )
    except Exception as exc:
        result = {
            "question_id": question["question_id"],
            "question": question.get("question", ""),
            "condition": condition,
            "graph_snapshot_id": question["graph_snapshot_id"],
            "model_id": model,
            "answer": "",
            "gold_answer": question["answer"],
            "is_correct": False,
            "input_tokens": 0,
            "output_tokens": 0,
            "tool_calls": 0,
            "traversal_hops": None,
            "cursor_steps": None,
            "shortcut_hits": 0,
            "stale_shortcut_rejections": 0,
            "shortcuts_promoted": 0,
            "latency_ms": None,
            "error": f"{type(exc).__name__}: {str(exc)[:500]}",
            "walk": None,
            "tool_trace": [],
        }
        error_text = result["error"]
        if _is_fatal_provider_error(error_text):
            fatal_error = error_text
            if _is_auth_error(error_text):
                fatal_status = "failed_authentication"
            elif _is_daily_quota_error(error_text):
                fatal_status = "paused_daily_quota_resumable"
            else:
                fatal_status = "failed_provider"
    result.update(
        {
            "run_id": run_id,
            "repetition": repetition,
            "transport": "mcp-stdio" if mcp_bridge is not None else "in-process",
            "prompt_version": "route-following-v1",
            "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
    )
    result["prompt_sha256"] = hashlib.sha256(("route-following-v1\n" + question["question"]).encode("utf-8")).hexdigest()
    return result, fatal_error, fatal_status
