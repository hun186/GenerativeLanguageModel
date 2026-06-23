from czjLLM.es_mode.adapters.elasticsearch_adapter import ElasticsearchAdapter


def _adapter(output_cols=None):
    return ElasticsearchAdapter({"output_cols": output_cols or ["route", "result", "audit"]})


def test_es_resolves_output_cols_from_cfg_and_cleans_empty_values():
    adapter = ElasticsearchAdapter({"output_cols": ["route", "", " result ", None]})

    assert adapter._resolve_output_cols() == ["route", "result"]


def test_es_requires_all_outputs_to_be_fresh_for_completed_row():
    adapter = _adapter()

    assert adapter._is_fresh_outputs_all({"route": "zh", "result": [{"x": 1}], "audit": [{"x": 1}]}, ["route", "result", "audit"])
    assert not adapter._is_fresh_outputs_all({"route": "zh", "result": [{"x": 1}]}, ["route", "result", "audit"])
