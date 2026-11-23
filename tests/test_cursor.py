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
