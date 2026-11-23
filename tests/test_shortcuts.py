from waygraph.graph import Graph
from waygraph.shortcuts import learn,reuse

def promote(graph):
    first=learn(graph,'python','transactions',['e1','e2','e3'])
    assert first['status']=='CANDIDATE'
    second=learn(graph,'python','transactions',['e1','e2','e3'])
    assert second['status']=='VALID'
    return second

def test_shortcut_promotes_after_two_verified_walks():
    with Graph(':memory:') as graph:
        graph.seed()
        candidate=learn(graph,'python','transactions',['e1','e2','e3'])
        assert candidate['walk_count']==1
        assert candidate['promoted'] is False
        assert reuse(graph,candidate['id'])['status']=='CANDIDATE'
        promoted=learn(graph,'python','transactions',['e1','e2','e3'])
        assert promoted['walk_count']==2
        assert promoted['promoted'] is True
        assert reuse(graph,promoted['id'])['valid'] is True

def test_mutation_rejects_stale_shortcut():
    with Graph(':memory:') as graph:
        graph.seed()
        shortcut=promote(graph)
        assert reuse(graph,shortcut['id'])['valid'] is True
        graph.disable_edge('e2')
        result=reuse(graph,shortcut['id'])
        assert result['valid'] is False
        assert result['reason']=='DEPENDENCY_INACTIVE'

def test_type_and_relevant_property_changes_invalidate():
    with Graph(':memory:') as graph:
        graph.seed()
        typed=promote(graph)
        graph.set_edge_kind('e2','CONNECTS_DIFFERENTLY')
        assert reuse(graph,typed['id'])['reason']=='DEPENDENCY_CHANGED'

    with Graph(':memory:') as graph:
        graph.seed()
        shortcut=promote(graph)
        graph.update_edge_property('e2','role','reader')
        result=reuse(graph,shortcut['id'])
        assert not result['valid']
        assert result['reason']=='DEPENDENCY_CHANGED'

def test_irrelevant_property_change_keeps_shortcut_valid():
    with Graph(':memory:') as graph:
        graph.seed()
        shortcut=promote(graph)
        graph.update_edge_property('e2','debug_note','changed')
        assert reuse(graph,shortcut['id'])['valid'] is True

def test_endpoint_change_and_edge_delete_invalidate_with_reasons():
    with Graph(':memory:') as graph:
        graph.seed()
        shortcut=promote(graph)
        graph.retarget_edge('e3',target='cypher')
        assert reuse(graph,shortcut['id'])['reason']=='ENDPOINT_MISMATCH'

    with Graph(':memory:') as graph:
        graph.seed()
        shortcut=promote(graph)
        graph.delete_edge('e2')
        assert reuse(graph,shortcut['id'])['reason']=='DEPENDENCY_MISSING'

def test_retargeting_breaks_path_continuity():
    with Graph(':memory:') as graph:
        graph.seed()
        shortcut=promote(graph)
        graph.retarget_edge('e2',source='python')
        assert reuse(graph,shortcut['id'])['reason']=='PATH_DISCONTINUITY'

def test_deleting_path_node_keeps_shortcut_record_and_fails_closed():
    with Graph(':memory:') as graph:
        graph.seed()
        shortcut=learn(graph,'python','transactions',['e1','e2','e3'])
        graph.delete_node('sdk')
        result=reuse(graph,shortcut['id'])
        assert result['status']=='STALE'
        assert result['reason']=='DEPENDENCY_MISSING'
