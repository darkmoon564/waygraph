from waygraph.evaluation import run
from waygraph.graph import Graph
from waygraph.questions import freeze_question_set


def test_oracle_report_records_independent_answers_and_snapshot(tmp_path):
    with Graph(':memory:') as graph:
        graph.seed()
        report=run(graph,tmp_path,limit=2)
        assert report['mode']=='oracle_replay_not_agent_benchmark'
        assert report['count']==2
        assert report['accuracy']==1.0
        assert report['reuse_count']==0
        assert report['mean_reuse_ms'] is None
        assert all(row['is_correct'] for row in report['results'])
        assert all(row['graph_snapshot_id']==report['graph_snapshot_id'] for row in report['results'])


def test_evaluation_replays_frozen_pilot_split(tmp_path):
    with Graph(':memory:') as graph:
        graph.seed()
        questions=tmp_path/'questions.jsonl'
        freeze_question_set(graph,questions,limit=5,pilot_count=1)
        report=run(graph,tmp_path/'pilot-results',questions_file=questions,split='pilot')
        assert report['question_split']=='pilot'
        assert report['count']==1
