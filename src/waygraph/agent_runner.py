"""Anthropic tool-use benchmark runner for isolated graph conditions."""
from __future__ import annotations

import hashlib
import json
import os
import statistics
import re
import time
import platform
import sys
from importlib.metadata import version, PackageNotFoundError
from pathlib import Path
from typing import Any
from uuid import uuid4
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from types import SimpleNamespace

from .cursor import Cursor
from .graph import Graph, GraphError
from .questions import load_question_set

_READ_QUERY = re.compile(r"^\s*(MATCH|OPTIONAL\s+MATCH|WITH|UNWIND|RETURN)\b", re.I)
_WRITE_CLAUSE = re.compile(r"\b(CREATE|MERGE|DELETE|DETACH|SET|REMOVE|DROP|LOAD\s+CSV|CALL)\b", re.I)


class _OpenRouterClient:
    """Small OpenAI-compatible OpenRouter client using only the stdlib."""

    def __init__(self, api_key: str, *, timeout: float = 120.0):
        self.api_key = api_key
        self.timeout = timeout
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **payload: Any) -> Any:
        request = Request(
            "https://openrouter.ai/api/v1/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            try:
                body = json.loads(exc.read().decode("utf-8", errors="replace"))
                detail = body.get("error", {}).get("message", "request rejected")
            except (ValueError, AttributeError):
                detail = "request rejected"
            raise RuntimeError(f"OpenRouter HTTP {exc.code}: {str(detail)[:400]}") from exc
        except URLError as exc:
            raise RuntimeError(f"OpenRouter connection failed: {exc.reason}") from exc
        choices = []
        for choice in data.get("choices", []):
            message = choice.get("message", {})
            tool_calls = [
                SimpleNamespace(id=call.get("id", ""), function=SimpleNamespace(
                    name=call.get("function", {}).get("name", ""),
                    arguments=call.get("function", {}).get("arguments", "{}"),
                ))
                for call in (message.get("tool_calls") or [])
            ]
            message_obj = SimpleNamespace(content=message.get("content"), tool_calls=tool_calls or None)
            message_obj.model_dump = lambda exclude_none=True, m=message: {k: v for k, v in m.items() if v is not None}
            choices.append(SimpleNamespace(message=message_obj, finish_reason=choice.get("finish_reason")))
        usage = data.get("usage", {})
        return SimpleNamespace(
            choices=choices,
            usage=SimpleNamespace(prompt_tokens=usage.get("prompt_tokens", 0), completion_tokens=usage.get("completion_tokens", 0)),
            model=data.get("model", payload.get("model")),
        )


def _validate_read_query(query: str) -> None:
    if not isinstance(query, str) or len(query) > 4000 or ";" in query or not _READ_QUERY.match(query) or _WRITE_CLAUSE.search(query):
        raise ValueError("Only one read-only Cypher query over the inspected graph schema is allowed")
    limit = re.search(r"\bLIMIT\s+(\d+)\b", query, re.I)
    if limit and int(limit.group(1)) > 100:
        raise ValueError("Query LIMIT cannot exceed 100")


def _is_auth_error(message: str) -> bool:
    lowered = message.lower()
    return any(marker in lowered for marker in ("http 401", "http 403", "user not found", "api key not valid", "invalid api key"))


def _is_fatal_provider_error(message: str) -> bool:
    return _is_auth_error(message) or bool(re.search(r"\bhttp (?:429|5\d\d)\b", message, re.I))


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


def _anthropic_tools(condition: str) -> list[dict[str, Any]]:
    if condition == "cursor":
        specs = [
            ("start_walk", "Start a cursor using the exact origin node ID shown in parentheses in the question, not its display title.", {"origin": {"type": "string"}}),
            ("inspect_walk", "Inspect the current node and the currently offered outgoing edges.", {}),
            ("follow_edge", "Follow an edge ID from the latest inspection.", {"edge_id": {"type": "string"}}),
            ("get_walk", "Get the ordered nodes and edges traversed in this walk.", {}),
        ]
    else:
        specs = [
            ("inspect_schema", "Return the read-only graph schema and traversal model.", {}),
            ("query_graph", "Run a bounded read-only Cypher query. Use only MATCH/RETURN and parameters.", {"query": {"type": "string"}, "params": {"type": "object"}}),
        ]
    return [{"name": name, "description": description, "input_schema": {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}} for name, description, props in specs]


def _call_tool(condition: str, name: str, args: dict[str, Any], graph: Graph, cursor: Cursor | None, session: str) -> tuple[dict[str, Any], Cursor | None, int]:
    if condition == "cursor":
        if name == "start_walk":
            cursor = Cursor(graph, args["origin"])
            return cursor.inspect(), cursor, 1
        if cursor is None:
            raise GraphError("Start the requested walk before using cursor tools", "CURSOR_NOT_STARTED")
        if name == "inspect_walk":
            return cursor.inspect(), cursor, 1
        if name == "follow_edge":
            return cursor.follow(args["edge_id"]), cursor, 1
        if name == "get_walk":
            return cursor.get_walk(), cursor, 1
        raise ValueError(f"Unknown cursor tool: {name}")
    if name == "inspect_schema":
        return {"model": "DPEdge nodes represent source relationships; DP_FROM links source entity to edge; DP_TO links edge to target entity.", "labels": ["DPEntity", "DPEdge"], "relationship_types": ["DP_FROM", "DP_TO"], "limits": {"rows": 100}}, cursor, 1
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


def _run_one(client: Any, model: str, max_tokens: int, max_tool_calls: int, condition: str, question: dict[str, Any], graph: Graph) -> dict[str, Any]:
    session = "eval-" + uuid4().hex
    cursor = None
    system = (
        "Answer the graph traversal task using only the available tools. "
        "Return only the exact final graph node ID, with no explanation. "
        "The requested route is specified in the task. Do not guess an ID."
    )
    messages: list[dict[str, Any]] = [{"role": "user", "content": question["question"]}]
    tool_calls = 0
    input_tokens = output_tokens = 0
    tool_trace: list[dict[str, Any]] = []
    started = time.perf_counter_ns()
    answer = ""
    error = None
    for _ in range(max_tool_calls + 1):
        response = client.messages.create(model=model, max_tokens=max_tokens, temperature=0.0, system=system, messages=messages, tools=_anthropic_tools(condition))
        input_tokens += getattr(response.usage, "input_tokens", 0)
        output_tokens += getattr(response.usage, "output_tokens", 0)
        blocks = [_content_payload(block) for block in response.content]
        messages.append({"role": "assistant", "content": blocks})
        tool_uses = [block for block in response.content if getattr(block, "type", None) == "tool_use"]
        if not tool_uses:
            answer = "\n".join(getattr(block, "text", "") for block in response.content if getattr(block, "type", None) == "text").strip()
            break
        results = []
        for block in tool_uses:
            if tool_calls >= max_tool_calls:
                error = "TOOL_CALL_LIMIT"
                break
            tool_calls += 1
            tool_started = time.perf_counter_ns()
            try:
                tool_args = dict(block.input)
                if condition == "cursor":
                    tool_args["session"] = session
                result, cursor, rows = _call_tool(condition, block.name, tool_args, graph, cursor, session)
                tool_error = None
            except Exception as exc:
                result, rows, tool_error = {"error": str(exc)[:500]}, 0, type(exc).__name__
            elapsed_ms = (time.perf_counter_ns() - tool_started) / 1e6
            tool_trace.append({"name": block.name, "input": block.input, "result": result, "error_type": tool_error, "latency_ms": elapsed_ms, "rows": rows})
            results.append({"type": "tool_result", "tool_use_id": block.id, "content": json.dumps(result, ensure_ascii=False), **({"is_error": True} if tool_error else {})})
        if error:
            break
        messages.append({"role": "user", "content": results})
    else:
        error = "TURN_LIMIT"
    elapsed_ms = (time.perf_counter_ns() - started) / 1e6
    if cursor is not None:
        walk = cursor.get_walk()
    else:
        walk = None
    normalized = answer.strip().strip("`\"' ")
    return {
        "question_id": question["question_id"], "question": question["question"], "condition": condition,
        "graph_snapshot_id": question["graph_snapshot_id"], "model_id": model,
        "answer": answer, "gold_answer": question["answer"],
        "is_correct": normalized == question["answer"], "input_tokens": input_tokens,
        "output_tokens": output_tokens, "tool_calls": tool_calls, "temperature": 0.0, "max_tokens": max_tokens,
        "traversal_hops": len(walk["edges"]) if walk else None,
        "latency_ms": elapsed_ms, "error": error, "walk": walk,
        "tool_trace": tool_trace,
    }


def _run_one_gemini(client: Any, genai_types: Any, model: str, max_tokens: int, max_tool_calls: int, condition: str, question: dict[str, Any], graph: Graph) -> dict[str, Any]:
    session = "eval-" + uuid4().hex
    cursor = None
    system = "Answer the graph traversal task using only the available functions. Return only the exact final graph node ID, with no explanation. Do not guess an ID."
    contents: list[Any] = [genai_types.Content(role="user", parts=[genai_types.Part.from_text(text=question["question"])])]
    declarations = []
    for spec in _anthropic_tools(condition):
        declarations.append(genai_types.FunctionDeclaration(name=spec["name"], description=spec["description"], parameters=spec["input_schema"]))
    tool = genai_types.Tool(function_declarations=declarations)
    config = genai_types.GenerateContentConfig(system_instruction=system, tools=[tool], temperature=0.0, max_output_tokens=max_tokens)
    tool_calls = input_tokens = output_tokens = 0
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
        # Preserve the provider's complete model turn when returning function results.
        contents.append(model_content)
        function_responses = []
        for function_call in function_calls:
            if tool_calls >= max_tool_calls:
                error = "TOOL_CALL_LIMIT"
                break
            tool_calls += 1
            args = dict(getattr(function_call, "args", {}) or {})
            if condition == "cursor":
                args["session"] = session
            tool_started = time.perf_counter_ns()
            try:
                result, cursor, rows = _call_tool(condition, function_call.name, args, graph, cursor, session)
                tool_error = None
            except Exception as exc:
                result, rows, tool_error = {"error": str(exc)[:500]}, 0, type(exc).__name__
            elapsed_ms = (time.perf_counter_ns() - tool_started) / 1e6
            tool_trace.append({"name": function_call.name, "input": args, "result": result, "error_type": tool_error, "latency_ms": elapsed_ms, "rows": rows})
            function_responses.append(genai_types.Part.from_function_response(name=function_call.name, response=result))
        if error:
            break
        contents.append(genai_types.Content(role="user", parts=function_responses))
    else:
        error = "TURN_LIMIT"
    elapsed_ms = (time.perf_counter_ns() - started) / 1e6
    walk = cursor.get_walk() if cursor is not None else None
    normalized = answer.strip().strip("`\"' ")
    return {
        "question_id": question["question_id"], "question": question["question"], "condition": condition,
        "graph_snapshot_id": question["graph_snapshot_id"], "model_id": model,
        "answer": answer, "gold_answer": question["answer"], "is_correct": normalized == question["answer"],
        "input_tokens": input_tokens, "output_tokens": output_tokens, "tool_calls": tool_calls,
        "temperature": 0.0, "max_tokens": max_tokens,
        "traversal_hops": len(walk["edges"]) if walk else None, "latency_ms": elapsed_ms,
        "error": error, "walk": walk, "tool_trace": tool_trace,
    }


def _run_one_openrouter(client: Any, model: str, max_tokens: int, max_tool_calls: int, condition: str, question: dict[str, Any], graph: Graph) -> dict[str, Any]:
    session = "eval-" + uuid4().hex
    cursor = None
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": "Answer the graph traversal task using only the available functions. Return only the exact final graph node ID, with no explanation. Do not guess an ID."},
        {"role": "user", "content": question["question"]},
    ]
    tools = [{"type": "function", "function": {"name": spec["name"], "description": spec["description"], "parameters": spec["input_schema"]}} for spec in _anthropic_tools(condition)]
    tool_calls = input_tokens = output_tokens = 0
    tool_trace: list[dict[str, Any]] = []
    started = time.perf_counter_ns()
    answer = ""
    error = None
    models_served: list[str] = []
    model_turns: list[dict[str, Any]] = []
    for _ in range(max_tool_calls + 1):
        response = client.chat.completions.create(
            model=model, messages=messages, tools=tools, temperature=0.0,
            max_tokens=max_tokens, parallel_tool_calls=False, session_id=session,
        )
        response_model = getattr(response, "model", None) or model
        models_served.append(response_model)
        usage = getattr(response, "usage", None)
        turn_input_tokens = getattr(usage, "prompt_tokens", 0) if usage else 0
        turn_output_tokens = getattr(usage, "completion_tokens", 0) if usage else 0
        input_tokens += turn_input_tokens
        output_tokens += turn_output_tokens
        choice = response.choices[0]
        model_turns.append({"model_served": response_model, "finish_reason": getattr(choice, "finish_reason", None), "input_tokens": turn_input_tokens, "output_tokens": turn_output_tokens})
        message = choice.message
        calls = list(getattr(message, "tool_calls", None) or [])
        if not calls:
            answer = (getattr(message, "content", None) or "").strip()
            break
        assistant_message = message.model_dump(exclude_none=True) if hasattr(message, "model_dump") else {
            "role": "assistant", "content": getattr(message, "content", None),
            "tool_calls": [call.model_dump(exclude_none=True) if hasattr(call, "model_dump") else call for call in calls],
        }
        messages.append(assistant_message)
        for call in calls:
            if tool_calls >= max_tool_calls:
                error = "TOOL_CALL_LIMIT"
                break
            tool_calls += 1
            tool_started = time.perf_counter_ns()
            try:
                args = json.loads(call.function.arguments or "{}")
                if not isinstance(args, dict):
                    raise ValueError("Tool arguments must be a JSON object")
            except (json.JSONDecodeError, ValueError) as exc:
                args = {}
                result, rows, tool_error = {"error": str(exc)}, 0, type(exc).__name__
            else:
                if condition == "cursor":
                    args["session"] = session
                try:
                    result, cursor, rows = _call_tool(condition, call.function.name, args, graph, cursor, session)
                    tool_error = None
                except Exception as exc:
                    result, rows, tool_error = {"error": str(exc)[:500]}, 0, type(exc).__name__
            elapsed_ms = (time.perf_counter_ns() - tool_started) / 1e6
            tool_trace.append({"name": call.function.name, "input": args, "result": result, "error_type": tool_error, "latency_ms": elapsed_ms, "rows": rows, "model_served": response_model})
            messages.append({"role": "tool", "tool_call_id": call.id, "content": json.dumps(result, ensure_ascii=False)})
        if error:
            break
    else:
        error = "TURN_LIMIT"
    elapsed_ms = (time.perf_counter_ns() - started) / 1e6
    walk = cursor.get_walk() if cursor is not None else None
    normalized = answer.strip().strip("`\"' ")
    return {
        "question_id": question["question_id"], "question": question["question"], "condition": condition,
        "graph_snapshot_id": question["graph_snapshot_id"], "model_id": model, "models_served": models_served,
        "model_turns": model_turns,
        "answer": answer, "gold_answer": question["answer"], "is_correct": normalized == question["answer"],
        "input_tokens": input_tokens, "output_tokens": output_tokens, "tool_calls": tool_calls,
        "temperature": 0.0, "max_tokens": max_tokens,
        "traversal_hops": len(walk["edges"]) if walk else None, "latency_ms": elapsed_ms,
        "error": error, "walk": walk, "tool_trace": tool_trace,
    }


def run_agent_evaluation(*, source_file: Path, question_file: Path, output: Path, condition: str, model: str, provider: str = "openrouter", repetitions: int = 1, split: str = "pilot", max_tool_calls: int = 20, max_tokens: int = 2048) -> dict[str, Any]:
    """Run isolated model trials with Gemini, Anthropic, or OpenRouter."""
    if condition not in {"cursor", "native-cypher"}:
        raise ValueError("condition must be cursor or native-cypher")
    if provider not in {"gemini", "anthropic", "openrouter"}:
        raise ValueError("provider must be gemini, anthropic, or openrouter")
    if provider == "openrouter" and not model.strip():
        model = "nvidia/nemotron-3-ultra-550b-a55b:free"
    if not model or not model.strip() or not 1 <= repetitions <= 20 or not 1 <= max_tool_calls <= 100:
        raise ValueError("model is required; repetitions must be 1..20 and max_tool_calls 1..100")
    key_name = {"gemini": "GEMINI_API_KEY", "anthropic": "ANTHROPIC_API_KEY", "openrouter": "OPENROUTER_API_KEY"}[provider]
    if not os.environ.get(key_name):
        raise RuntimeError(f"{key_name} is required for {provider} agent evaluation")
    try:
        if provider == "gemini":
            from google import genai
            from google.genai import types as genai_types
        elif provider == "anthropic":
            import anthropic
    except ImportError as exc:
        package = {"gemini": "google-genai", "anthropic": "anthropic", "openrouter": "Python standard library"}[provider]
        raise RuntimeError(f"Install {package} before {provider} agent evaluation") from exc
    source_bytes = source_file.read_bytes()
    document = json.loads(source_bytes)
    output.mkdir(parents=True, exist_ok=True)
    reports = []
    question_sha256 = hashlib.sha256(question_file.read_bytes()).hexdigest()
    for repetition in range(1, repetitions + 1):
        store = output / "stores" / f"{condition}-{repetition:03d}"
        if store.exists():
            raise ValueError(f"Evaluation store already exists; choose an empty output directory: {store}")
        store.parent.mkdir(parents=True, exist_ok=True)
        with Graph(str(store)) as graph:
            imported = graph.import_source_graph(document, hashlib.sha256(source_bytes).hexdigest())
            snapshot_id = graph.snapshot_id()
            questions = load_question_set(question_file, expected_snapshot_id=graph.snapshot_id(), split=split)
            if provider == "gemini":
                client = genai.Client(api_key=os.environ[key_name])
            elif provider == "anthropic":
                client = anthropic.Anthropic(api_key=os.environ[key_name], timeout=120.0, max_retries=0)
            else:
                client = _OpenRouterClient(api_key=os.environ[key_name], timeout=120.0)
            run_id = uuid4().hex
            results = []
            fatal_error = None
            fatal_status = None
            trace_path = output / f"{condition}-{repetition:03d}.jsonl"
            with trace_path.open("w", encoding="utf-8") as trace_file:
                for question in questions:
                    try:
                        if provider == "gemini":
                            result = _run_one_gemini(client, genai_types, model, max_tokens, max_tool_calls, condition, question, graph)
                        elif provider == "anthropic":
                            result = _run_one(client, model, max_tokens, max_tool_calls, condition, question, graph)
                        else:
                            result = _run_one_openrouter(client, model, max_tokens, max_tool_calls, condition, question, graph)
                    except Exception as exc:
                        result = {"question_id": question["question_id"], "condition": condition, "graph_snapshot_id": question["graph_snapshot_id"], "model_id": model, "answer": "", "gold_answer": question["answer"], "is_correct": False, "input_tokens": 0, "output_tokens": 0, "tool_calls": 0, "traversal_hops": None, "latency_ms": None, "error": f"{type(exc).__name__}: {str(exc)[:500]}", "walk": None, "tool_trace": []}
                        error_text = result["error"]
                        if _is_fatal_provider_error(error_text):
                            fatal_error = error_text
                            fatal_status = "failed_authentication" if _is_auth_error(error_text) else "failed_provider"
                    result.update({"run_id": run_id, "repetition": repetition, "prompt_version": "route-following-v1", "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
                    result["prompt_sha256"] = hashlib.sha256(("route-following-v1\n" + question["question"]).encode("utf-8")).hexdigest()
                    trace_file.write(json.dumps(result, ensure_ascii=False) + "\n")
                    results.append(result)
                    if fatal_error:
                        break
        reports.append({"run_id": run_id, "repetition": repetition, "store": str(store), "graph_snapshot_id": snapshot_id, "import": imported, "trace_path": str(trace_path), "question_set_count": len(questions), "not_attempted_questions": len(questions) - len(results), "count": len(results), "status": fatal_status or "complete", "fatal_error": fatal_error, **_agent_result_metrics(results), "results": results})
    sdk_distribution = {"gemini": "google-genai", "anthropic": "anthropic", "openrouter": None}[provider]
    try:
        sdk_version = version(sdk_distribution) if sdk_distribution else "stdlib-urllib"
    except PackageNotFoundError:
        sdk_version = None
    all_results = [row for trial in reports for row in trial["results"]]
    latencies = [row["latency_ms"] for row in all_results if row["latency_ms"] is not None]
    report = {
        "mode": f"{provider}_tool_agent", "provider": provider, "condition": condition, "model_id": model,
        "sdk_version": sdk_version, "python_version": sys.version,
        "platform": platform.platform(), "source_sha256": hashlib.sha256(source_bytes).hexdigest(),
        "question_sha256": question_sha256, "split": split, "repetitions": repetitions,
        "temperature": 0.0, "max_tokens": max_tokens, "max_tool_calls": max_tool_calls,
        "aggregate": {
            "total_runs": len(all_results),
            **_agent_result_metrics(all_results),
            "question_set_total": sum(trial["question_set_count"] for trial in reports),
            "not_attempted_questions": sum(trial["not_attempted_questions"] for trial in reports),
            "mean_latency_ms": sum(latencies) / len(latencies) if latencies else None,
            "latency_population_stddev_ms": statistics.pstdev(latencies) if latencies else None,
        },
        "reports": reports,
    }
    (output / f"{condition}-summary.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report
