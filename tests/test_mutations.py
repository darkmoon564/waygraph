from waygraph.mutations import run_matrix


def test_deterministic_mutation_matrix_has_no_false_valid_results():
    report = run_matrix()
    assert report['mode'] == 'deterministic_mutation_matrix_not_agent_benchmark'
    assert report['count'] == 8
    assert report['false_valid_count'] == 0
    assert report['false_stale_count'] == 0
    assert report['passed'] is True
