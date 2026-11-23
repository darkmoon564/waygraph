"""Deterministic oracle evaluation; no fabricated LLM scores."""
from __future__ import annotations
import json
import time
import hashlib
import statistics
from pathlib import Path
from .cursor import Cursor
from .graph import Graph
from .questions import generate, load_question_set, oracle_path
from .shortcuts import learn, reuse


def run_repeats(graph: Graph, output: Path, repetitions: int, *, questions_file: Path, split: str) -> dict:
    """Replay a frozen split repeatedly, resetting learned shortcut state each time."""
    if isinstance(repetitions, bool) or not isinstance(repetitions, int) or not 1 <= repetitions <= 100:
        raise ValueError("repetitions must be an integer from 1 to 100")
    questions = load_question_set(questions_file, expected_snapshot_id=graph.snapshot_id(), split=split)
    output.mkdir(parents=True, exist_ok=True)
    reports = []
    for repetition in range(1, repetitions + 1):
        db_path = output / "stores" / f"repeat-{repetition:03d}"
        if db_path.exists():
            raise ValueError(f"Repeat store already exists; choose an empty output directory: {db_path}")
        db_path.parent.mkdir(parents=True, exist_ok=True)
        with Graph(str(db_path)) as isolated:
            source_path = Path("data/source/relate-docs-graph.json")
            source_bytes = source_path.read_bytes()
            imported = isolated.import_source_graph(json.loads(source_bytes), hashlib.sha256(source_bytes).hexdigest())
            if imported["entities"] != len(graph.query("MATCH (n:DPEntity) RETURN n.id AS id")) or imported["relationships"] != len(graph.query("MATCH (e:DPEdge) RETURN e.id AS id")):
                raise RuntimeError("Repeat store import counts do not match the source graph")
            report = run(isolated, output / f"repeat-{repetition:03d}", len(questions), questions_file=questions_file, split=split)
        report["repetition"] = repetition
        report["isolated_store"] = str(db_path)
        reports.append(report)
    flat = [result for report in reports for result in report["results"]]
    latencies = [result["walk_ms"] for result in flat]
    summary = {
        "mode": "deterministic_oracle_replay_not_agent_benchmark",
        "graph_snapshot_id": graph.snapshot_id(),
        "split": split,
        "repetitions": repetitions,
        "questions_per_repetition": len(questions),
        "total_runs": len(flat),
        "accuracy": sum(result["is_correct"] for result in flat) / len(flat),
        "walk_latency_ms": {
            "mean": statistics.mean(latencies),
            "median": statistics.median(latencies),
            "population_stddev": statistics.pstdev(latencies),
            "min": min(latencies),
            "max": max(latencies),
        },
        "metrics_unavailable": ["tokens", "model_calls", "agent_latency"],
        "reports": reports,
    }
    (output / "repeats.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary

def run(graph: Graph, output: Path, limit: int = 30, *, questions_file: Path | None = None, split: str | None = None) -> dict:
    snapshot_id=graph.snapshot_id()
    if questions_file is not None:
        questions=load_question_set(questions_file,expected_snapshot_id=snapshot_id,split=split)
    else:
        if split is not None:
            raise ValueError("split requires a frozen questions_file")
        questions=generate(graph,limit=limit)
    if not questions:
        raise ValueError("Graph has no qualifying multi-hop paths")
    if any(q["graph_snapshot_id"] != snapshot_id for q in questions):
        raise RuntimeError("Graph changed while generating the question set")
    output.mkdir(parents=True,exist_ok=True)
    with (output/'questions.jsonl').open('w',encoding='utf-8') as f:
        for q in questions:
            f.write(json.dumps(q)+'\n')
    results=[]
    for q in questions:
        gold_nodes=oracle_path(graph,q['origin'],q['gold_edges'])
        if gold_nodes != q['gold_nodes'] or gold_nodes[-1] != q['answer']:
            raise RuntimeError(f"Independent gold path no longer matches question {q['question_id']}")
        started=time.perf_counter_ns()
        cursor=Cursor(graph,q['origin'])
        cursor.inspect()
        for edge_id in q['gold_edges']:
            cursor.follow(edge_id)
        walk_ms=(time.perf_counter_ns()-started)/1e6
        shortcut=learn(graph,q['origin'],q['answer'],q['gold_edges'])
        reuse_ms=None
        shortcut_valid=False
        if shortcut['promoted']:
            started=time.perf_counter_ns()
            hit=reuse(graph,shortcut['id'])
            reuse_ms=(time.perf_counter_ns()-started)/1e6
            shortcut_valid=hit['valid']
        correct=cursor.current==gold_nodes[-1]
        results.append({'question_id':q['question_id'],'graph_snapshot_id':snapshot_id,'gold_answer':gold_nodes[-1],'answer':cursor.current,'is_correct':correct,'correct':correct,'hops':len(cursor.edges),'walk_ms':walk_ms,'reuse_ms':reuse_ms,'shortcut_status':shortcut['status'],'shortcut_promoted':shortcut['promoted'],'shortcut_valid':shortcut_valid})
    if graph.snapshot_id()!=snapshot_id:
        raise RuntimeError("Graph changed during oracle evaluation")
    reuse_times=[r['reuse_ms'] for r in results if r['reuse_ms'] is not None]
    report={'mode':'oracle_replay_not_agent_benchmark','graph_snapshot_id':snapshot_id,'question_split':split,'count':len(results),'accuracy':sum(r['is_correct'] for r in results)/len(results),'mean_walk_ms':sum(r['walk_ms'] for r in results)/len(results),'reuse_count':len(reuse_times),'mean_reuse_ms':sum(reuse_times)/len(reuse_times) if reuse_times else None,'results':results}
    (output/'oracle_results.json').write_text(json.dumps(report,indent=2))
    return report
