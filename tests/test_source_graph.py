import pytest

from waygraph.source_graph import normalize_source_graph


def test_documentation_graph_normalizes_examples_and_duplicate_edges_stably():
    document = {
        "format": 1,
        "kind": "documentation",
        "verified": "1.0.1",
        "nodes": [
            {"id": "Page:docs/page", "labels": ["Page"], "properties": {"id": "docs/page", "title": "Docs page"}},
            {"id": "Example:docs/page#example-2", "labels": ["Example"], "properties": {"id": "docs/page#example-2", "page": "docs/page", "section": "codecs", "position": 2, "lang": "text", "first_line": "not used as the caption"}},
        ],
        "relationships": [
            {"type": "HAS_EXAMPLE", "start": "Page:docs/page", "end": "Example:docs/page#example-2", "properties": {"role": "body"}},
            {"type": "HAS_EXAMPLE", "start": "Page:docs/page", "end": "Example:docs/page#example-2", "properties": {"role": "body"}},
        ],
    }
    checksum = "a" * 64
    metadata, nodes, edges = normalize_source_graph(document, checksum)
    again = normalize_source_graph(document, checksum)
    assert metadata['source_sha256'] == checksum
    assert nodes[1]['title'] == 'Example 2 from docs/page / codecs (text)'
    assert [edge['id'] for edge in edges] == [edge['id'] for edge in again[2]]
    assert edges[0]['id'] != edges[1]['id']


def test_documentation_graph_rejects_dangling_relationship():
    document = {
        "format": 1,
        "kind": "documentation",
        "verified": "1.0.1",
        "nodes": [{"id": "Page:docs/page", "labels": ["Page"], "properties": {"id": "docs/page"}}],
        "relationships": [{"type": "LINKS_TO", "start": "Page:docs/page", "end": "Page:missing", "properties": {}}],
    }
    with pytest.raises(ValueError, match="absent"):
        normalize_source_graph(document, "a" * 64)
