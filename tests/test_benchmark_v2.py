from pathlib import Path

from waygraph.benchmark_v2 import run_lifecycle_benchmark
from waygraph.graph import Graph
from waygraph.questions import load_question_set, oracle_path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data" / "source" / "relate-docs-graph.json"
SHOWCASE = ROOT / "data" / "relate" / "showcase.rl"
V2_QUESTIONS = ROOT / "data" / "questions" / "relate-docs-v2.jsonl"


def test_v2_question_set_loads_pilot_and_held_out_and_matches_oracle():
    assert V2_QUESTIONS.exists(), "Run python -m waygraph.benchmark_v2 first"
    with Graph(str(SHOWCASE), read_only=True) as g:
        snap = g.snapshot_id()
        pilot = load_question_set(V2_QUESTIONS, expected_snapshot_id=snap, split="pilot")
        held_out = load_question_set(V2_QUESTIONS, expected_snapshot_id=snap, split="held_out")
        assert len(pilot) == 10
        assert len(held_out) == 14
        for q in pilot + held_out:
            assert q["difficulty"]["route_disclosed"] is False
            assert oracle_path(g, q["origin"], q["gold_edges"]) == q["gold_nodes"]
            assert q["gold_nodes"][-1] == q["answer"]


def test_3_regime_lifecycle_benchmark_compresses_steps_and_blocks_stale_mutations():
    report = run_lifecycle_benchmark(SOURCE, V2_QUESTIONS)
    assert report["cold_cursor"]["accuracy"] == 1.0
    assert report["warm_waygraph_pass_1"]["accuracy"] == 1.0
    assert report["warm_waygraph_pass_1"]["shortcut_hits"] >= 12
    assert report["warm_waygraph_pass_1"]["cursor_step_reduction_pct"] >= 15.0
    assert report["warm_waygraph_steady_state"]["cursor_step_reduction_pct"] >= 30.0
    mut = report["post_mutation_vs_naive_cache"]
    assert mut["passed"] is True
    assert mut["naive_cache_false_valid_count"] == 5
    assert mut["waygraph_false_valid_count"] == 0
    assert mut["waygraph_false_stale_count"] == 0
    assert mut["live_reroute_recoveries"] == 4
