import pytest

from waygraph import mcp_server
from waygraph.cursor import MAX_HOPS
from waygraph.graph import Graph


@pytest.fixture
def server_graph(monkeypatch):
    graph = Graph(':memory:')
    graph.seed()
    monkeypatch.setattr(mcp_server, '_graph', graph)
    monkeypatch.setattr(mcp_server, '_cursors', {})
    yield graph
    graph.close()


def test_mcp_envelopes_and_hop_limit(server_graph):
    started = mcp_server.start_walk('session-1', 'python', max_hops=1)
    assert started['ok'] is True
    assert started['error'] is None
    assert started['trace_id']
    assert [edge['edge_id'] for edge in started['data']['neighbors']] == ['e1']

    bad_edge = mcp_server.follow_edge('session-1', 'e3')
    assert bad_edge['ok'] is False
    assert bad_edge['error']['code'] == 'RELATIONSHIP_NOT_AVAILABLE'

    followed = mcp_server.follow_edge('session-1', 'e1')
    assert followed['ok'] is True
    assert followed['data']['current']['id'] == 'sdk'
    assert followed['data']['neighbors'] == []

    over_limit = mcp_server.follow_edge('session-1', 'e2')
    assert over_limit['ok'] is False
    assert over_limit['error']['code'] == 'HOP_LIMIT_REACHED'

    missing = mcp_server.inspect_walk('unknown')
    assert missing['ok'] is False
    assert missing['error']['code'] == 'CURSOR_NOT_STARTED'


def test_mcp_rejects_invalid_hop_limit(server_graph):
    result = mcp_server.start_walk('session-2', 'python', max_hops=MAX_HOPS + 1)
    assert result['ok'] is False
    assert result['error']['code'] == 'INVALID_ARGUMENT'


def test_repeated_save_in_one_walk_does_not_promote(server_graph):
    for session in ('walk-1', 'walk-2'):
        mcp_server.start_walk(session, 'python', max_hops=3)
        for edge_id in ('e1', 'e2', 'e3'):
            result=mcp_server.follow_edge(session, edge_id)
            assert result['ok'] is True
        saved=mcp_server.save_shortcut(session)
        assert saved['ok'] is True
        if session == 'walk-1':
            assert saved['data']['status']=='CANDIDATE'
            duplicate=mcp_server.save_shortcut(session)
            assert duplicate['data']['status']=='CANDIDATE'
            assert duplicate['data']['walk_count']==1
        else:
            assert saved['data']['status']=='VALID'
            assert saved['data']['walk_count']==2
