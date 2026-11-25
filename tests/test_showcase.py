import json
import re
from pathlib import Path

import pytest

from waygraph.graph import Graph
from waygraph.shortcuts import list_shortcuts

ROOT = Path(__file__).resolve().parents[1]
STORE = ROOT / "data" / "relate" / "showcase.rl"
VIEWER = ROOT / "viewer"
CANONICAL_SNAPSHOT = "d691ad319bfeb28b18d07ec5a2bc59eaeea2cf88f76ae6671294ac12beba78ae"

pytestmark = pytest.mark.skipif(not STORE.exists(), reason="showcase store not built")


@pytest.fixture(scope="module")
def graph():
    with Graph(str(STORE), read_only=True) as g:
        yield g


def test_showcase_store_has_full_docs_graph_and_canonical_snapshot(graph):
    assert graph.query("MATCH (n:DPEntity) RETURN count(n) AS c")[0]["c"] == 4133
    assert graph.query("MATCH (e:DPEdge) RETURN count(e) AS c")[0]["c"] == 9148
    assert graph.snapshot_id() == CANONICAL_SNAPSHOT


def test_showcase_store_contains_all_shortcut_lifecycle_states(graph):
    rows = graph.query(
        "MATCH (s:DPShortcut) RETURN s.status AS status, s.walk_count AS w, "
        "s.reuse_count AS r, s.evidence AS ev, s.fingerprint AS fp"
    )
    by_status = {}
    for row in rows:
        by_status.setdefault(row["status"], []).append(row)
    assert len(by_status["VALID"]) >= 3
    assert len(by_status["CANDIDATE"]) >= 2
    assert len(by_status["STALE"]) >= 1
    for row in by_status["VALID"]:
        assert row["w"] >= 2 and row["r"] >= 1
        assert len(row["ev"]) >= 2 and re.fullmatch(r"[0-9a-f]{64}", row["fp"])
    assert all(row["w"] == 1 for row in by_status["CANDIDATE"])


def test_showcase_valid_shortcuts_revalidate_against_live_graph():
    with Graph(str(STORE), read_only=True) as g:
        valid = list_shortcuts(g, validate=True, limit=50)
        assert valid and all(item["valid"] for item in valid)
        stale = [s for s in list_shortcuts(g, include_non_valid=True, limit=50) if s["status"] == "STALE"]
        assert stale and stale[0]["validation_reason"]


def test_showcase_native_relationships_and_fulltext_search(graph):
    native = graph.query("MATCH (a:Capability)-[r:CITES]->(b:Page) RETURN count(r) AS c")[0]["c"]
    assert native == 133
    hits = graph.search_nodes("read-only", label="Flag")
    assert any(hit["id"] == "Flag:read-only" for hit in hits)


def test_viewer_files_exist_and_embed_valid_data():
    html = (VIEWER / "index.html").read_text(encoding="utf-8")
    data = json.loads((VIEWER / "showcase-data.json").read_text(encoding="utf-8"))
    embedded = re.search(r'<script id="showcase-data" type="application/json">(.*?)</script>', html, re.S)
    assert embedded, "inline data missing; run python viewer/build_viewer.py"
    assert json.loads(embedded.group(1).replace("<\\/", "</")) == data
    assert "__SHOWCASE_DATA__" not in html
    assert data["store"]["entities"] == 4133 and data["store"]["relationships"] == 9148
    assert len(data["scenarios"]) == 4 and len(data["shortcuts"]) == 6
    assert 30 <= data["subgraph"]["node_count"] <= 60


def test_viewer_scenarios_reference_known_nodes_and_edges():
    data = json.loads((VIEWER / "showcase-data.json").read_text(encoding="utf-8"))
    nodes = {n["id"] for n in data["subgraph"]["nodes"]}
    edges = {e["id"] for e in data["subgraph"]["edges"]}
    for shortcut in data["shortcuts"]:
        assert set(shortcut["path_nodes"]) <= nodes
        assert set(shortcut["evidence"]) <= edges
    for scenario in data["scenarios"]:
        for step in scenario["steps"]:
            assert set(step["visited_nodes"]) <= nodes
            assert set(step["walked_edges"]) <= edges


def test_viewer_template_never_injects_unescaped_html():
    html = (VIEWER / "studio.template.html").read_text(encoding="utf-8")
    assert "innerHTML" in html and "function esc(" in html
    assert "document.write" not in html and "eval(" not in html
