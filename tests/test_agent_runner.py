import hashlib
import io
import json
from types import SimpleNamespace
from urllib.error import HTTPError

import pytest

from waygraph.agent_runner import (
    _OpenRouterClient,
    _agent_result_metrics,
    _agent_shortcut_metrics,
    _call_tool,
    _is_auth_error,
    _run_one,
    _run_one_gemini,
    _run_one_openrouter,
    _validate_read_query,
    run_agent_evaluation,
)
from waygraph.graph import Graph
from waygraph.shortcuts import list_shortcuts


def _write_synthetic_fixture(tmp_path, questions_fn):
    document = {
        "format": 1,
        "kind": "documentation",
        "verified": "2026-01-01",
        "nodes": [
            {"id": "Surface:python", "labels": ["Surface"], "properties": {"title": "Python"}},
            {"id": "Capability:sdk", "labels": ["Capability"], "properties": {"title": "Relate SDK"}},
            {"id": "Capability:alt_sdk", "labels": ["Capability"], "properties": {"title": "Fallback SDK"}},
            {"id": "Page:engine", "labels": ["Page"], "properties": {"title": "Relate Engine"}},
            {"id": "Capability:tx", "labels": ["Capability"], "properties": {"title": "Transactions"}},
        ],
        "relationships": [
            {"type": "USES", "start": "Surface:python", "end": "Capability:sdk", "properties": {}},
            {"type": "CONNECTS_TO", "start": "Capability:sdk", "end": "Page:engine", "properties": {}},
            {"type": "USES_BACKUP", "start": "Surface:python", "end": "Capability:alt_sdk", "properties": {}},
            {"type": "CONNECTS_TO", "start": "Capability:alt_sdk", "end": "Page:engine", "properties": {}},
            {"type": "SUPPORTS", "start": "Page:engine", "end": "Capability:tx", "properties": {}},
        ],
    }
    source_file = tmp_path / "source.json"
    source_bytes = json.dumps(document).encode("utf-8")
    source_file.write_bytes(source_bytes)
    with Graph(":memory:") as g:
        g.import_source_graph(document, hashlib.sha256(source_bytes).hexdigest())
        snapshot_id = g.snapshot_id()
        edges = {
            (row["src"], row["dst"], row["kind"]): row["id"]
            for row in g.query(
                "MATCH (a:DPEntity)-[:DP_FROM]->(e:DPEdge)-[:DP_TO]->(b:DPEntity) "
                "RETURN e.id AS id, a.id AS src, b.id AS dst, e.kind AS kind"
            )
        }
    records = questions_fn(snapshot_id, edges)
    q_file = tmp_path / "questions.jsonl"
    payload = "".join(json.dumps(item, sort_keys=True, separators=(",", ":")) + "\n" for item in records).encode("utf-8")
    q_file.write_bytes(payload)
    manifest = {
        "format": 1,
        "status": "reviewed",
        "question_file": q_file.name,
        "question_file_sha256": hashlib.sha256(payload).hexdigest(),
        "graph_snapshot_id": snapshot_id,
        "question_count": len(records),
        "pilot_count": sum(item.get("split") == "pilot" for item in records),
        "held_out_count": sum(item.get("split") == "held_out" for item in records),
    }
    (tmp_path / "questions.manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return source_file, q_file, snapshot_id, edges


def test_native_query_is_read_only_and_bounded():
    _validate_read_query("MATCH (n:DPEntity) RETURN n.id LIMIT 50")
    _validate_read_query(
        "CALL db.index.fulltext.queryNodes('dp_entity_ft', $q) YIELD node, score RETURN node.id, score LIMIT 10"
    )
    with pytest.raises(ValueError):
        _validate_read_query("MATCH (n) DELETE n")
    with pytest.raises(ValueError):
        _validate_read_query("CALL dbms.procedures() YIELD name RETURN name")
    with pytest.raises(ValueError):
        _validate_read_query("MATCH (n) RETURN n LIMIT 101")
    with pytest.raises(ValueError):
        _validate_read_query("MATCH (n) RETURN n; MATCH (m) RETURN m")


def test_cursor_agent_tool_loop_respects_offered_edges():
    class FakeMessages:
        def __init__(self):
            self.calls = 0

        def create(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                block = SimpleNamespace(type="tool_use", name="start_walk", id="t1", input={"origin": "python"})
                content = [block]
            elif self.calls == 2:
                block = SimpleNamespace(type="tool_use", name="follow_edge", id="t2", input={"edge_id": "e1"})
                content = [block]
            elif self.calls == 3:
                block = SimpleNamespace(type="tool_use", name="follow_edge", id="t3", input={"edge_id": "e2"})
                content = [block]
            else:
                content = [SimpleNamespace(type="text", text="engine")]
            return SimpleNamespace(content=content, usage=SimpleNamespace(input_tokens=10, output_tokens=5))

    class FakeClient:
        def __init__(self):
            self.messages = FakeMessages()

    question = {"question_id": "q1", "graph_snapshot_id": "snapshot", "question": "Follow two edges", "answer": "engine"}
    with Graph(":memory:") as graph:
        graph.seed()
        result = _run_one(FakeClient(), "fake-model", 100, 8, "cursor", question, graph)
    assert result["is_correct"]
    assert result["traversal_hops"] == 2
    assert result["tool_calls"] == 3
    assert result["input_tokens"] == 40
    assert result["output_tokens"] == 20
    assert "shortcuts" not in result["tool_trace"][0]["result"]


def test_native_query_tool_enforces_result_limit():
    with Graph(":memory:") as graph:
        graph.seed()
        schema, _, _ = _call_tool("native-cypher", "inspect_schema", {}, graph, None, "s")
        result, cursor, rows = _call_tool("native-cypher", "query_graph", {"query": "MATCH (n:DPEntity) RETURN n.id"}, graph, None, "s")
    assert cursor is None
    assert rows == 1
    assert result["count"] == 6
    assert set(schema["domain_labels"]) == {"Capability", "Page", "Surface"}
    assert "USES" in schema["domain_relationship_types"]
    assert schema["fulltext_index"]["name"] == "dp_entity_ft"


def test_gemini_function_call_loop_uses_cursor_tools():
    class Types:
        class Content:
            def __init__(self, **kwargs): self.__dict__.update(kwargs)
        class Part:
            @staticmethod
            def from_text(*, text): return SimpleNamespace(text=text)
            @staticmethod
            def from_function_response(*, name, response): return SimpleNamespace(name=name, response=response)
        class FunctionDeclaration:
            def __init__(self, **kwargs): self.__dict__.update(kwargs)
        class Tool:
            def __init__(self, **kwargs): self.__dict__.update(kwargs)
        class GenerateContentConfig:
            def __init__(self, **kwargs): self.__dict__.update(kwargs)

    class Models:
        def __init__(self): self.turn = 0
        def generate_content(self, **kwargs):
            self.turn += 1
            if self.turn <= 3:
                calls = [
                    ("start_walk", {"origin": "python"}),
                    ("follow_edge", {"edge_id": "e1"}),
                    ("follow_edge", {"edge_id": "e2"}),
                ]
                name, args = calls[self.turn - 1]
                parts = [SimpleNamespace(function_call=SimpleNamespace(name=name, args=args), text=None)]
            else:
                parts = [SimpleNamespace(function_call=None, text="engine")]
            candidate = SimpleNamespace(content=SimpleNamespace(parts=parts))
            usage = SimpleNamespace(prompt_token_count=7, candidates_token_count=3)
            return SimpleNamespace(candidates=[candidate], usage_metadata=usage)

    question = {"question_id": "q1", "graph_snapshot_id": "snapshot", "question": "Follow two edges", "answer": "engine"}
    client = SimpleNamespace(models=Models())
    with Graph(":memory:") as graph:
        graph.seed()
        result = _run_one_gemini(client, Types, "gemini-test", 100, 8, "cursor", question, graph)
    assert result["is_correct"]
    assert result["traversal_hops"] == 2
    assert result["tool_calls"] == 3
    assert result["input_tokens"] == 28
    assert result["output_tokens"] == 12


def test_gemini_runner_requires_key(monkeypatch, tmp_path):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        run_agent_evaluation(source_file=tmp_path / "absent.json", question_file=tmp_path / "q.jsonl", output=tmp_path / "out", condition="cursor", model="test", provider="gemini")


def test_openrouter_tool_call_loop_uses_cursor_tools():
    class Completions:
        def __init__(self): self.turn = 0; self.sessions = []
        def create(self, **kwargs):
            self.turn += 1
            self.sessions.append(kwargs.get("session_id"))
            if self.turn <= 3:
                name, args = [
                    ("start_walk", {"origin": "python"}),
                    ("follow_edge", {"edge_id": "e1"}),
                    ("follow_edge", {"edge_id": "e2"}),
                ][self.turn - 1]
                call = SimpleNamespace(id=f"call-{self.turn}", function=SimpleNamespace(name=name, arguments=__import__("json").dumps(args)))
                message = SimpleNamespace(content=None, tool_calls=[call], model_dump=lambda **_: {"role": "assistant", "content": None, "tool_calls": []})
            else:
                message = SimpleNamespace(content="engine", tool_calls=None)
            usage = SimpleNamespace(prompt_tokens=8, completion_tokens=4)
            return SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=usage)

    client = SimpleNamespace(chat=SimpleNamespace(completions=Completions()))
    question = {"question_id": "q1", "graph_snapshot_id": "snapshot", "question": "Follow two edges", "answer": "engine"}
    with Graph(":memory:") as graph:
        graph.seed()
        result = _run_one_openrouter(client, "provider/model:free", 100, 8, "cursor", question, graph)
    assert result["is_correct"]
    assert result["traversal_hops"] == 2
    assert result["tool_calls"] == 3
    assert result["input_tokens"] == 32
    assert result["output_tokens"] == 16
    assert len(set(client.chat.completions.sessions)) == 1


def test_openrouter_runner_requires_key(monkeypatch, tmp_path):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="OPENROUTER_API_KEY"):
        run_agent_evaluation(source_file=tmp_path / "absent.json", question_file=tmp_path / "q.jsonl", output=tmp_path / "out", condition="cursor", model="test/model:free", provider="openrouter")


def test_auth_failure_detection_stops_retries():
    assert _is_auth_error("OpenRouter HTTP 401: User not found")
    assert _is_auth_error("HTTP 403: API key not valid")
    assert not _is_auth_error("HTTP 429: rate limit exceeded")


def test_agent_result_metrics_separate_answer_accuracy_from_provider_failures():
    metrics = _agent_result_metrics([
        {"error": None, "is_correct": True, "input_tokens": 12, "output_tokens": 5, "tool_calls": 3},
        {"error": "HTTP 429", "is_correct": False, "input_tokens": 0, "output_tokens": 0, "tool_calls": 0},
    ])
    assert metrics == {
        "attempted_questions": 2,
        "answered_questions": 1,
        "provider_failures": 1,
        "accuracy": 0.5,
        "answer_accuracy": 1.0,
        "mean_input_tokens": 12,
        "mean_output_tokens": 5,
        "mean_tool_calls": 3,
    }


def test_waygraph_promotes_shortcut_across_two_questions_and_reuses_on_third():
    """Waygraph auto-learns >=2-hop walks across Q1 & Q2, promotes to VALID, and jumps in 1 step on Q3."""

    class AdaptiveCompletions:
        def create(self, **kwargs):
            messages = kwargs["messages"]
            tool_msgs = [m for m in messages if m.get("role") == "tool"]
            if not tool_msgs:
                call = SimpleNamespace(id="c1", function=SimpleNamespace(name="start_walk", arguments=json.dumps({"origin": "python"})))
                return SimpleNamespace(
                    choices=[SimpleNamespace(message=SimpleNamespace(content=None, tool_calls=[call]))],
                    usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5),
                )
            latest = json.loads(tool_msgs[-1]["content"])
            cur_id = latest["current"]["id"]
            if cur_id == "engine":
                return SimpleNamespace(
                    choices=[SimpleNamespace(message=SimpleNamespace(content="engine", tool_calls=None))],
                    usage=SimpleNamespace(prompt_tokens=10, completion_tokens=3),
                )
            shortcuts = [s for s in latest.get("shortcuts", []) if s["target"] == "engine"]
            if shortcuts:
                call = SimpleNamespace(
                    id="c_sc",
                    function=SimpleNamespace(name="take_shortcut", arguments=json.dumps({"shortcut_id": shortcuts[0]["shortcut_id"]})),
                )
            else:
                next_edge = "e1" if cur_id == "python" else "e2"
                call = SimpleNamespace(id=f"c_{next_edge}", function=SimpleNamespace(name="follow_edge", arguments=json.dumps({"edge_id": next_edge})))
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=None, tool_calls=[call]))],
                usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5),
            )

    client = SimpleNamespace(chat=SimpleNamespace(completions=AdaptiveCompletions()))
    questions = [
        {"question_id": f"q{i}", "graph_snapshot_id": "snap", "question": "Reach engine from python", "answer": "engine"}
        for i in (1, 2, 3)
    ]
    with Graph(":memory:") as graph:
        graph.seed()
        results = [_run_one_openrouter(client, "test-model", 128, 10, "waygraph", q, graph) for q in questions]
        valid = list_shortcuts(graph, origin="python", target="engine")

    assert [r["is_correct"] for r in results] == [True, True, True]
    assert results[0]["cursor_steps"] == 2
    assert results[0]["shortcuts_promoted"] == 0
    assert results[1]["cursor_steps"] == 2
    assert results[1]["shortcuts_promoted"] == 1
    assert results[2]["cursor_steps"] == 1
    assert results[2]["traversal_hops"] == 2
    assert results[2]["shortcut_hits"] == 1
    assert results[2]["tool_calls"] == 2  # start_walk + take_shortcut
    assert len(valid) == 1 and valid[0]["reuse_count"] == 1

    agg = _agent_shortcut_metrics(results)
    assert agg["shortcut_hits"] == 1
    assert agg["shortcuts_promoted"] == 1
    assert agg["stale_shortcut_rejections"] == 0
    assert agg["mean_traversal_hops"] == 2.0
    assert agg["mean_cursor_steps"] == pytest.approx(5 / 3)


def test_waygraph_handles_shortcut_stale_on_before_mutation_and_falls_back(tmp_path):
    """When before_mutation disables an underlying edge, take_shortcut fails closed with SHORTCUT_STALE and falls back."""

    def make_questions(snapshot_id, edges):
        e_py_sdk = edges[("Surface:python", "Capability:sdk", "USES")]
        return [
            {
                "question_id": "q1",
                "graph_snapshot_id": snapshot_id,
                "question": "Reach Page:engine from Surface:python",
                "answer": "Page:engine",
                "split": "pilot",
            },
            {
                "question_id": "q2",
                "graph_snapshot_id": snapshot_id,
                "question": "Reach Page:engine from Surface:python again",
                "answer": "Page:engine",
                "split": "pilot",
            },
            {
                "question_id": "q3",
                "graph_snapshot_id": snapshot_id,
                "question": "Reach Page:engine from Surface:python after mutation",
                "answer": "Page:engine",
                "split": "pilot",
                "before_mutation": {"op": "disable_edge", "edge_id": e_py_sdk},
            },
        ]

    source_file, q_file, _, edges = _write_synthetic_fixture(tmp_path, make_questions)
    e_py_sdk = edges[("Surface:python", "Capability:sdk", "USES")]
    e_sdk_eng = edges[("Capability:sdk", "Page:engine", "CONNECTS_TO")]
    e_py_alt = edges[("Surface:python", "Capability:alt_sdk", "USES_BACKUP")]
    e_alt_eng = edges[("Capability:alt_sdk", "Page:engine", "CONNECTS_TO")]

    class FallbackCompletions:
        def create(self, **kwargs):
            tool_msgs = [m for m in kwargs["messages"] if m.get("role") == "tool"]
            if not tool_msgs:
                call = SimpleNamespace(id="t1", function=SimpleNamespace(name="start_walk", arguments=json.dumps({"origin": "Surface:python"})))
                return SimpleNamespace(
                    choices=[SimpleNamespace(message=SimpleNamespace(content=None, tool_calls=[call]))],
                    usage=SimpleNamespace(prompt_tokens=8, completion_tokens=4),
                )
            latest = json.loads(tool_msgs[-1]["content"])
            if latest.get("code") == "SHORTCUT_STALE":
                call = SimpleNamespace(id="t_re", function=SimpleNamespace(name="inspect_walk", arguments="{}"))
                return SimpleNamespace(
                    choices=[SimpleNamespace(message=SimpleNamespace(content=None, tool_calls=[call]))],
                    usage=SimpleNamespace(prompt_tokens=8, completion_tokens=4),
                )
            cur = latest["current"]["id"]
            if cur == "Page:engine":
                return SimpleNamespace(
                    choices=[SimpleNamespace(message=SimpleNamespace(content="Page:engine", tool_calls=None))],
                    usage=SimpleNamespace(prompt_tokens=8, completion_tokens=2),
                )
            shortcuts = [s for s in latest.get("shortcuts", []) if s["target"] == "Page:engine"]
            if shortcuts:
                call = SimpleNamespace(
                    id="t_sc",
                    function=SimpleNamespace(name="take_shortcut", arguments=json.dumps({"shortcut_id": shortcuts[0]["shortcut_id"]})),
                )
            else:
                offered_ids = {n["edge_id"] for n in latest.get("neighbors", [])}
                for candidate in (e_py_sdk, e_sdk_eng, e_py_alt, e_alt_eng):
                    if candidate in offered_ids:
                        chosen = candidate
                        break
                call = SimpleNamespace(id="t_fe", function=SimpleNamespace(name="follow_edge", arguments=json.dumps({"edge_id": chosen})))
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=None, tool_calls=[call]))],
                usage=SimpleNamespace(prompt_tokens=8, completion_tokens=4),
            )

    client = SimpleNamespace(chat=SimpleNamespace(completions=FallbackCompletions()))
    report = run_agent_evaluation(
        source_file=source_file,
        question_file=q_file,
        output=tmp_path / "out",
        condition="waygraph",
        model="mock-free",
        provider="ollama",
        split="pilot",
        client=client,
    )
    rows = report["reports"][0]["results"]
    assert [r["is_correct"] for r in rows] == [True, True, True]
    assert rows[2]["stale_shortcut_rejections"] == 1
    assert rows[2]["shortcut_hits"] == 0
    assert rows[2]["walk"]["edges"] == [e_py_alt, e_alt_eng]
    assert report["aggregate"]["stale_shortcut_rejections"] == 1
    assert report["aggregate"]["shortcuts_promoted"] == 1


def test_resume_skips_answered_questions_and_preserves_promoted_shortcuts(tmp_path):
    """resume=True keeps the Relate store (with promoted shortcuts) and skips already-answered questions."""

    def make_questions(snapshot_id, _edges):
        return [
            {
                "question_id": f"q{idx}",
                "graph_snapshot_id": snapshot_id,
                "question": f"Reach Page:engine from Surface:python ({idx})",
                "answer": "Page:engine",
                "split": "pilot" if idx <= 2 else "held_out",
            }
            for idx in (1, 2, 3)
        ]

    source_file, q_file, _, edges = _write_synthetic_fixture(tmp_path, make_questions)
    e_py_sdk = edges[("Surface:python", "Capability:sdk", "USES")]
    e_sdk_eng = edges[("Capability:sdk", "Page:engine", "CONNECTS_TO")]

    seen_prompts: list[str] = []
    fail_on_q3 = {"active": True}

    class ResumableCompletions:
        def create(self, **kwargs):
            user_prompt = kwargs["messages"][1]["content"]
            tool_msgs = [m for m in kwargs["messages"] if m.get("role") == "tool"]
            if not tool_msgs:
                seen_prompts.append(user_prompt)
                if fail_on_q3["active"] and "(3)" in user_prompt:
                    raise RuntimeError("OpenRouter HTTP 429: Rate limit exceeded: free-models-per-day.")
                call = SimpleNamespace(id="t1", function=SimpleNamespace(name="start_walk", arguments=json.dumps({"origin": "Surface:python"})))
                return SimpleNamespace(
                    choices=[SimpleNamespace(message=SimpleNamespace(content=None, tool_calls=[call]))],
                    usage=SimpleNamespace(prompt_tokens=6, completion_tokens=3),
                )
            latest = json.loads(tool_msgs[-1]["content"])
            cur = latest["current"]["id"]
            if cur == "Page:engine":
                return SimpleNamespace(
                    choices=[SimpleNamespace(message=SimpleNamespace(content="Page:engine", tool_calls=None))],
                    usage=SimpleNamespace(prompt_tokens=6, completion_tokens=2),
                )
            shortcuts = [s for s in latest.get("shortcuts", []) if s["target"] == "Page:engine"]
            if shortcuts:
                call = SimpleNamespace(
                    id="t_sc",
                    function=SimpleNamespace(name="take_shortcut", arguments=json.dumps({"shortcut_id": shortcuts[0]["shortcut_id"]})),
                )
            else:
                nxt = e_py_sdk if cur == "Surface:python" else e_sdk_eng
                call = SimpleNamespace(id="t_fe", function=SimpleNamespace(name="follow_edge", arguments=json.dumps({"edge_id": nxt})))
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=None, tool_calls=[call]))],
                usage=SimpleNamespace(prompt_tokens=6, completion_tokens=3),
            )

    client = SimpleNamespace(chat=SimpleNamespace(completions=ResumableCompletions()))
    out_dir = tmp_path / "resume_out"

    first = run_agent_evaluation(
        source_file=source_file,
        question_file=q_file,
        output=out_dir,
        condition="waygraph",
        model="mock-free",
        provider="openrouter",
        split="all",
        client=client,
    )
    assert first["reports"][0]["status"] == "paused_daily_quota_resumable"
    assert first["aggregate"]["answered_questions"] == 2
    assert first["aggregate"]["provider_failures"] == 1
    assert len(seen_prompts) == 3

    # Second run with resume=True: Q1 and Q2 must be skipped, and Q3 must reuse the promoted shortcut from run 1!
    seen_prompts.clear()
    fail_on_q3["active"] = False
    resumed = run_agent_evaluation(
        source_file=source_file,
        question_file=q_file,
        output=out_dir,
        condition="waygraph",
        model="mock-free",
        provider="openrouter",
        split="all",
        resume=True,
        client=client,
    )
    assert len(seen_prompts) == 1 and "(3)" in seen_prompts[0]
    assert resumed["reports"][0]["status"] == "complete"
    assert resumed["reports"][0]["resumed"] is True
    assert resumed["aggregate"]["answered_questions"] == 3
    assert resumed["aggregate"]["provider_failures"] == 0
    assert resumed["aggregate"]["shortcut_hits"] == 1
    assert resumed["reports"][0]["results"][2]["cursor_steps"] == 1


def test_openrouter_client_retries_transient_429_but_stops_immediately_on_daily_quota(monkeypatch):
    sleeps: list[float] = []
    monkeypatch.setattr("waygraph.agent_runner.time.sleep", lambda delay: sleeps.append(delay))

    attempts = {"count": 0}

    def fake_urlopen_transient(req, timeout=120.0):
        attempts["count"] += 1
        if attempts["count"] < 3:
            body = json.dumps({"error": {"message": "Rate limit exceeded: 20 requests per minute"}}).encode("utf-8")
            raise HTTPError(req.full_url, 429, "Too Many Requests", {}, io.BytesIO(body))

        class Resp:
            def __enter__(self): return self
            def __exit__(self, *a): pass
            def read(self):
                return json.dumps({
                    "choices": [{"message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 5, "completion_tokens": 1},
                }).encode("utf-8")

        return Resp()

    monkeypatch.setattr("waygraph.agent_runner.urlopen", fake_urlopen_transient)
    client = _OpenRouterClient(api_key="test-key", retry_base_delay=0.25)
    resp = client.chat.completions.create(model="m", messages=[{"role": "user", "content": "hi"}])
    assert resp.choices[0].message.content == "ok"
    assert len(sleeps) == 2

    # Daily quota exhaustion must NOT sleep or retry
    sleeps.clear()
    daily_calls = {"count": 0}

    def fake_urlopen_daily(req, timeout=120.0):
        daily_calls["count"] += 1
        body = json.dumps({"error": {"message": "Rate limit exceeded: free-models-per-day"}}).encode("utf-8")
        raise HTTPError(req.full_url, 429, "Too Many Requests", {}, io.BytesIO(body))

    monkeypatch.setattr("waygraph.agent_runner.urlopen", fake_urlopen_daily)
    with pytest.raises(RuntimeError, match="free-models-per-day"):
        client.chat.completions.create(model="m", messages=[{"role": "user", "content": "hi"}])
    assert daily_calls["count"] == 1
    assert sleeps == []


def test_mcp_stdio_transport_end_to_end_smoke(tmp_path):
    """End-to-end smoke test spawning real `waygraph.mcp_server` over stdio."""

    def make_questions(snapshot_id, _edges):
        return [
            {
                "question_id": f"q_mcp_{idx}",
                "graph_snapshot_id": snapshot_id,
                "question": f"Walk from Surface:python to Page:engine via SDK ({idx})",
                "answer": "Page:engine",
                "split": "pilot",
            }
            for idx in (1, 2, 3)
        ]

    source_file, q_file, _, edges = _write_synthetic_fixture(tmp_path, make_questions)
    e_py_sdk = edges[("Surface:python", "Capability:sdk", "USES")]
    e_sdk_eng = edges[("Capability:sdk", "Page:engine", "CONNECTS_TO")]

    class McpSmokeCompletions:
        def create(self, **kwargs):
            tool_msgs = [m for m in kwargs["messages"] if m.get("role") == "tool"]
            if not tool_msgs:
                call = SimpleNamespace(id="m1", function=SimpleNamespace(name="start_walk", arguments=json.dumps({"origin": "Surface:python"})))
                return SimpleNamespace(
                    choices=[SimpleNamespace(message=SimpleNamespace(content=None, tool_calls=[call]))],
                    usage=SimpleNamespace(prompt_tokens=9, completion_tokens=4),
                )
            latest = json.loads(tool_msgs[-1]["content"])
            cur = latest["current"]["id"]
            if cur == "Page:engine":
                return SimpleNamespace(
                    choices=[SimpleNamespace(message=SimpleNamespace(content="Page:engine", tool_calls=None))],
                    usage=SimpleNamespace(prompt_tokens=9, completion_tokens=2),
                )
            shortcuts = [s for s in latest.get("shortcuts", []) if s["target"] == "Page:engine"]
            if shortcuts:
                call = SimpleNamespace(
                    id="m_sc",
                    function=SimpleNamespace(name="take_shortcut", arguments=json.dumps({"shortcut_id": shortcuts[0]["shortcut_id"]})),
                )
            else:
                nxt = e_py_sdk if cur == "Surface:python" else e_sdk_eng
                call = SimpleNamespace(id="m_fe", function=SimpleNamespace(name="follow_edge", arguments=json.dumps({"edge_id": nxt})))
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=None, tool_calls=[call]))],
                usage=SimpleNamespace(prompt_tokens=9, completion_tokens=4),
            )

    client = SimpleNamespace(chat=SimpleNamespace(completions=McpSmokeCompletions()))
    report = run_agent_evaluation(
        source_file=source_file,
        question_file=q_file,
        output=tmp_path / "mcp_out",
        condition="waygraph",
        model="mock-mcp-model",
        provider="ollama",
        transport="mcp-stdio",
        split="pilot",
        client=client,
    )
    assert report["transport"] == "mcp-stdio"
    assert report["aggregate"]["answered_questions"] == 3
    assert report["aggregate"]["accuracy"] == 1.0
    assert report["aggregate"]["shortcuts_promoted"] == 1
    assert report["aggregate"]["shortcut_hits"] == 1
    q3 = report["reports"][0]["results"][2]
    assert q3["transport"] == "mcp-stdio"
    assert q3["cursor_steps"] == 1
    assert q3["traversal_hops"] == 2


def test_waygraph_autolearns_two_hop_prefix_corridor_on_three_hop_walks():
    """Two distinct 3-hop walks sharing a 2-hop hub prefix promote the 2-hop corridor automatically."""

    class ThreeHopCompletions:
        def create(self, **kwargs):
            prompt = kwargs["messages"][1]["content"]
            final_edge = "e3" if "transactions" in prompt else "e4"
            final_node = "transactions" if "transactions" in prompt else "cypher"
            tool_msgs = [m for m in kwargs["messages"] if m.get("role") == "tool"]
            if not tool_msgs:
                call = SimpleNamespace(id="p1", function=SimpleNamespace(name="start_walk", arguments=json.dumps({"origin": "python"})))
                return SimpleNamespace(
                    choices=[SimpleNamespace(message=SimpleNamespace(content=None, tool_calls=[call]))],
                    usage=SimpleNamespace(prompt_tokens=6, completion_tokens=3),
                )
            latest = json.loads(tool_msgs[-1]["content"])
            cur = latest["current"]["id"]
            if cur == final_node:
                return SimpleNamespace(
                    choices=[SimpleNamespace(message=SimpleNamespace(content=final_node, tool_calls=None))],
                    usage=SimpleNamespace(prompt_tokens=6, completion_tokens=2),
                )
            shortcuts = [s for s in latest.get("shortcuts", []) if s["target"] == "engine"]
            if cur == "python" and shortcuts:
                call = SimpleNamespace(
                    id="p_sc",
                    function=SimpleNamespace(name="take_shortcut", arguments=json.dumps({"shortcut_id": shortcuts[0]["shortcut_id"]})),
                )
            else:
                nxt = "e1" if cur == "python" else ("e2" if cur == "sdk" else final_edge)
                call = SimpleNamespace(id=f"p_{nxt}", function=SimpleNamespace(name="follow_edge", arguments=json.dumps({"edge_id": nxt})))
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=None, tool_calls=[call]))],
                usage=SimpleNamespace(prompt_tokens=6, completion_tokens=3),
            )

    client = SimpleNamespace(chat=SimpleNamespace(completions=ThreeHopCompletions()))
    q1 = {"question_id": "q1", "graph_snapshot_id": "s", "question": "Go to transactions", "answer": "transactions"}
    q2 = {"question_id": "q2", "graph_snapshot_id": "s", "question": "Go to cypher", "answer": "cypher"}
    q3 = {"question_id": "q3", "graph_snapshot_id": "s", "question": "Go to transactions again", "answer": "transactions"}
    with Graph(":memory:") as graph:
        graph.seed()
        r1 = _run_one_openrouter(client, "m", 100, 10, "waygraph", q1, graph)
        r2 = _run_one_openrouter(client, "m", 100, 10, "waygraph", q2, graph)
        r3 = _run_one_openrouter(client, "m", 100, 10, "waygraph", q3, graph)

    assert r1["is_correct"] and r2["is_correct"] and r3["is_correct"]
    assert r2["shortcuts_promoted"] == 1  # 2-hop prefix python -> engine promoted!
    assert r3["shortcut_hits"] == 1
    assert r3["cursor_steps"] == 2  # 1 shortcut jump (python->engine) + 1 follow_edge (e3)
    assert r3["traversal_hops"] == 3


def test_cli_agent_eval_forwards_new_flags(monkeypatch, tmp_path):
    from waygraph import cli

    captured: dict = {}

    def fake_run(**kwargs):
        captured.update(kwargs)
        return {"ok": True}

    monkeypatch.setattr(cli, "run_agent_evaluation", fake_run)
    monkeypatch.setattr(
        "sys.argv",
        [
            "waygraph",
            "agent-eval",
            "--condition",
            "waygraph",
            "--provider",
            "groq",
            "--transport",
            "mcp-stdio",
            "--resume",
            "--split",
            "all",
            "--questions-file",
            str(tmp_path / "q.jsonl"),
            "--output",
            str(tmp_path / "out"),
        ],
    )
    cli.main()
    assert captured["condition"] == "waygraph"
    assert captured["provider"] == "groq"
    assert captured["transport"] == "mcp-stdio"
    assert captured["resume"] is True
    assert captured["split"] is None

