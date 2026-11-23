from types import SimpleNamespace

import pytest

from waygraph.agent_runner import _agent_result_metrics, _call_tool, _is_auth_error, _run_one, _run_one_gemini, _run_one_openrouter, _validate_read_query, run_agent_evaluation
from waygraph.graph import Graph


def test_native_query_is_read_only_and_bounded():
    _validate_read_query("MATCH (n:DPEntity) RETURN n.id LIMIT 50")
    with pytest.raises(ValueError):
        _validate_read_query("MATCH (n) DELETE n")
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


def test_native_query_tool_enforces_result_limit():
    with Graph(":memory:") as graph:
        graph.seed()
        result, cursor, rows = _call_tool("native-cypher", "query_graph", {"query": "MATCH (n:DPEntity) RETURN n.id"}, graph, None, "s")
    assert cursor is None
    assert rows == 1
    assert result["count"] == 6


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

