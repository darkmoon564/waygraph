from waygraph.cursor import Cursor
from waygraph.graph import Graph, GraphError
import pytest

def test_walk_and_reject_invalid_edge():
    with Graph(':memory:') as graph:
        graph.seed()
        cursor=Cursor(graph,'python')
        cursor.inspect()
        assert cursor.follow('e1')['current']['id']=='sdk'
        with pytest.raises(GraphError):
            cursor.follow('e3')
        assert cursor.backtrack()['current']['id']=='python'

def test_follow_requires_latest_offer_and_rejects_stale_offer():
    with Graph(':memory:') as graph:
        graph.seed()
        cursor=Cursor(graph,'python')
        with pytest.raises(GraphError) as unoffered:
            cursor.follow('e1')
        assert unoffered.value.code=='RELATIONSHIP_NOT_AVAILABLE'
        cursor.inspect()
        graph.disable_edge('e1')
        with pytest.raises(GraphError) as stale:
            cursor.follow('e1')
        assert stale.value.code=='RELATIONSHIP_NOT_AVAILABLE'

def test_hop_limit_stops_walk_and_hides_neighbors():
    with Graph(':memory:') as graph:
        graph.seed()
        cursor=Cursor(graph,'python',max_hops=1)
        cursor.inspect()
        state=cursor.follow('e1')
        assert state['hops']==1
        assert state['remaining_hops']==0
        assert state['neighbors']==[]
        with pytest.raises(GraphError) as limit:
            cursor.follow('e2')
        assert limit.value.code=='HOP_LIMIT_REACHED'

def test_missing_origin_and_disconnected_edge_have_stable_codes():
    with Graph(':memory:') as graph:
        graph.seed()
        with pytest.raises(GraphError) as missing:
            Cursor(graph,'missing')
        assert missing.value.code=='NODE_NOT_FOUND'
        cursor=Cursor(graph,'python')
        cursor.inspect()
        with pytest.raises(GraphError) as disconnected:
            cursor.follow('e3')
        assert disconnected.value.code=='RELATIONSHIP_NOT_AVAILABLE'

def test_take_shortcut_compresses_hops_backtracks_and_fails_closed_on_mutation():
    from waygraph.shortcuts import learn
    with Graph(':memory:') as graph:
        graph.seed()
        learn(graph, 'python', 'transactions', ['e1', 'e2', 'e3'])
        promoted = learn(graph, 'python', 'transactions', ['e1', 'e2', 'e3'])
        assert promoted['status'] == 'VALID'

        cursor = Cursor(graph, 'python')
        state = cursor.inspect()
        assert [s['shortcut_id'] for s in state['shortcuts']] == [promoted['id']]

        jumped = cursor.take_shortcut(promoted['id'])
        assert jumped['current']['id'] == 'transactions'
        assert jumped['hops'] == 3
        assert jumped['cursor_steps'] == 1
        assert len(jumped['shortcuts_used']) == 1

        rewound = cursor.backtrack()
        assert rewound['current']['id'] == 'python'
        assert rewound['hops'] == 0
        assert rewound['cursor_steps'] == 0
        assert rewound['shortcuts_used'] == []

        # Mutate underlying edge after inspect: take_shortcut must fail closed!
        graph.disable_edge('e2')
        with pytest.raises(GraphError) as stale:
            cursor.take_shortcut(promoted['id'])
        assert stale.value.code == 'SHORTCUT_STALE'
        assert cursor.current == 'python'

def test_search_nodes_and_native_domain_relationships_sync():
    with Graph(':memory:') as graph:
        graph.seed()
        hits = graph.search_nodes('Relate Engine', label='Page')
        assert hits and hits[0]['id'] == 'engine'
        native_rows = graph.query("MATCH (a:Surface {id:'python'})-[r:USES]->(b:Capability {id:'sdk'}) RETURN r.active AS active")
        assert native_rows == [{'active': True}]
        graph.disable_edge('e1')
        native_after = graph.query("MATCH (a:Surface {id:'python'})-[r:USES]->(b:Capability {id:'sdk'}) RETURN r.active AS active")
        assert native_after == [{'active': False}]
