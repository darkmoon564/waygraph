from waygraph.graph import Graph
from waygraph.questions import freeze_question_set, generate, load_question_set, oracle_path
import pytest

def test_questions_have_real_gold_edges():
    with Graph(':memory:') as graph:
        graph.seed()
        questions=generate(graph,30)
        assert questions
        assert all(len(q['gold_edges'])>=2 for q in questions)

def test_question_ids_are_snapshot_stable_and_gold_is_graph_derived():
    with Graph(':memory:') as graph:
        graph.seed()
        first=generate(graph,limit=5)
        second=generate(graph,limit=5)
        assert [q['question_id'] for q in first]==[q['question_id'] for q in second]
        assert all(q['graph_snapshot_id']==graph.snapshot_id() for q in first)
        assert all(oracle_path(graph,q['origin'],q['gold_edges'])==q['gold_nodes'] for q in first)
        for q in first:
            current=q['origin']
            for step,target in zip(q['route'],q['gold_nodes'][1:]):
                target_node=graph.node(target)
                matches={edge['node_id'] for edge in graph.neighbors(current,limit=100_000) if edge['kind']==step['relationship_type'] and edge['title']==step['destination_title'] and edge['labels']==target_node['labels']}
                assert matches=={target}
                current=target

def test_question_sampling_rotates_across_origins():
    with Graph(':memory:') as graph:
        graph.seed()
        questions=generate(graph,limit=5)
        assert len(questions)>=2
        assert questions[0]['origin'] != questions[1]['origin']

def test_frozen_question_set_splits_and_checksums(tmp_path):
    with Graph(':memory:') as graph:
        graph.seed()
        output=tmp_path/'questions.jsonl'
        manifest=freeze_question_set(graph,output,limit=5,pilot_count=1)
        pilot=load_question_set(output,expected_snapshot_id=manifest['graph_snapshot_id'],split='pilot')
        all_questions=load_question_set(output,expected_snapshot_id=manifest['graph_snapshot_id'])
        held_out=[q for q in all_questions if q['split']=='held_out']
        assert manifest['status']=='draft_for_semantic_review'
        assert len(pilot)==1
        assert len(held_out)==manifest['question_count']-1
        assert not ({q['question_id'] for q in pilot} & {q['question_id'] for q in held_out})
        with pytest.raises(ValueError,match='semantic review'):
            load_question_set(output,expected_snapshot_id=manifest['graph_snapshot_id'],split='held_out')

        output.write_text(output.read_text(encoding='utf-8')+' ',encoding='utf-8')
        with pytest.raises(ValueError,match='checksum'):
            load_question_set(output,expected_snapshot_id=manifest['graph_snapshot_id'])
