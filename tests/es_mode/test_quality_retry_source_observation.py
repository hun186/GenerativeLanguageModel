"""Read-only actual adapter method exercised with a synthetic ES client."""
from copy import deepcopy
from types import SimpleNamespace
import pytest

from czjLLM.es_mode.adapters.elasticsearch_adapter import ElasticsearchAdapter
from czjLLM.es_mode.quality_retry_source_observation import SourceObservationUnavailable


def fixture(pk="sha1", index="news", document_id="real-doc", cluster="cluster-a",
            uuid="index-a"):
    cfg = {"src_index": index, "tgt_index": index, "id_col": pk}
    adapter = ElasticsearchAdapter(cfg)
    seen = []
    hit = {"_id": document_id, "_index": index, "_source": {"sha1": "business-key"}}
    result = {"timed_out": False, "_shards": {"total": 1, "successful": 1, "failed": 0},
              "hits": {"total": {"value": 1, "relation": "eq"}, "hits": [hit]}}
    def info(**kwargs):
        seen.append(("info", kwargs))
        return {"cluster_uuid": cluster}
    def settings(**kwargs):
        seen.append(("settings", kwargs))
        return {index: {"settings": {"index": {"uuid": uuid}}}}
    def search(**kwargs):
        seen.append(("search", kwargs))
        return deepcopy(result)
    adapter.es = SimpleNamespace(info=info, indices=SimpleNamespace(get_settings=settings),
                                 search=search)
    return adapter, result, seen


def test_business_key_observation_uses_concrete_id_and_namespace():
    adapter, _, seen = fixture()
    obs = adapter.observe_quality_retry_source("business-key")
    assert obs.document_id == "real-doc"
    assert obs.concrete_index == "news"
    assert "real-doc" not in repr(obs)
    assert [name for name, _ in seen] == ["info", "settings", "search", "info", "settings"]
    request = seen[2][1]
    assert request["body"]["query"] == {"term": {"sha1.keyword": "business-key"}}
    assert request["body"]["_source"] == ["sha1"]
    assert request["body"]["track_total_hits"] is True


def test_same_id_distinct_namespace_has_distinct_scoped_identity():
    identities = set()
    for cluster, uuid, index in [("a", "x", "news"), ("b", "x", "news"),
                                  ("a", "y", "news"), ("a", "x", "other")]:
        adapter, _, _ = fixture(pk="_id", cluster=cluster, uuid=uuid, index=index)
        identities.add(adapter.observe_quality_retry_source("real-doc").scoped_document_id())
    assert len(identities) == 4


@pytest.mark.parametrize("kind", ["duplicate", "approximate", "missing", "timeout",
                                  "partial", "wrong_index", "wrong_key", "array_key",
                                  "missing_id", "bad_shards", "terminated"])
def test_uncertain_lookup_fails_closed_without_raw_key(kind):
    adapter, response, _ = fixture()
    hit = response["hits"]["hits"][0]
    if kind == "duplicate":
        response["hits"]["total"]["value"] = 2
        response["hits"]["hits"].append(dict(hit, _id="second"))
    elif kind == "approximate":
        response["hits"]["total"]["relation"] = "gte"
    elif kind == "missing":
        response["hits"] = {"total": {"value": 0, "relation": "eq"}, "hits": []}
    elif kind == "timeout":
        response["timed_out"] = True
    elif kind == "partial":
        response["_shards"].update(total=2, failed=1)
    elif kind == "wrong_index":
        hit["_index"] = "different"
    elif kind == "wrong_key":
        hit["_source"]["sha1"] = "different"
    elif kind == "array_key":
        hit["_source"]["sha1"] = ["business-key"]
    elif kind == "missing_id":
        hit.pop("_id")
    elif kind == "bad_shards":
        response["_shards"]["failed"] = False
    elif kind == "terminated":
        response["terminated_early"] = True
    with pytest.raises(SourceObservationUnavailable) as error:
        adapter.observe_quality_retry_source("business-key")
    assert "business-key" not in str(error.value)


def test_namespace_change_alias_dual_index_and_transport_failure():
    adapter, _, _ = fixture()
    uuids = iter(["old", "new"])
    adapter.es.indices.get_settings = lambda **_: {
        "news": {"settings": {"index": {"uuid": next(uuids)}}}}
    with pytest.raises(SourceObservationUnavailable):
        adapter.observe_quality_retry_source("business-key")
    adapter, _, _ = fixture()
    adapter.es.indices.get_settings = lambda **_: {
        "concrete-news": {"settings": {"index": {"uuid": "x"}}}}
    with pytest.raises(SourceObservationUnavailable):
        adapter.observe_quality_retry_source("business-key")
    adapter, _, seen = fixture()
    adapter.cfg["tgt_index"] = "another"
    with pytest.raises(SourceObservationUnavailable):
        adapter.observe_quality_retry_source("business-key")
    assert seen == []
    adapter, _, _ = fixture()
    def fail(**kwargs):
        raise RuntimeError("private endpoint and source key")
    adapter.es.search = fail
    with pytest.raises(SourceObservationUnavailable) as error:
        adapter.observe_quality_retry_source("business-key")
    assert str(error.value) == "source observation unavailable"


def test_exact_id_query_never_falls_back_to_business_key():
    adapter, result, seen = fixture(pk="_id")
    assert adapter.observe_quality_retry_source("real-doc").document_id == "real-doc"
    assert seen[2][1]["body"]["query"] == {"ids": {"values": ["real-doc"]}}
    assert seen[2][1]["body"]["_source"] is False
    result["hits"]["hits"][0]["_id"] = "other"
    with pytest.raises(SourceObservationUnavailable):
        adapter.observe_quality_retry_source("real-doc")


def _input_fixture():
    adapter, result, seen = fixture()
    adapter.cfg.update(input_col="body", output_col="result",
                       stage_source_input_cols=["title"])
    result["hits"]["hits"][0]["_source"].update(
        body="original source", title="original title", result="old output")
    return adapter, result, seen


def test_input_revision_ignores_output_writeback_but_changes_on_source_edit():
    adapter, result, seen = _input_fixture()
    def observe(body="original source", title="original title"):
        return adapter.observe_quality_retry_inputs(
            "business-key", expected_input=body, expected_stage_inputs={"title": title})
    first = observe()
    assert "original source" not in repr(first)
    assert "business-key" not in repr(first)
    assert set(seen[2][1]["body"]["_source"]) == {"sha1", "body", "title"}
    src = result["hits"]["hits"][0]["_source"]
    src.update(result="changed output", result_meta={"x": 1}, update_time_ai="new")
    assert observe() == first
    src["body"] = "changed source"
    with pytest.raises(SourceObservationUnavailable):
        observe()
    second = observe(body="changed source")
    assert first.source == second.source
    assert first.scoped_document_revision() != second.scoped_document_revision()
    src["title"] = "changed title"
    with pytest.raises(SourceObservationUnavailable):
        observe(body="changed source")
    assert observe(body="changed source", title="changed title") != second


@pytest.mark.parametrize("case", [
    "missing_stage", "extra_stage", "output_overlap", "meta_overlap",
    "time_overlap", "array_source", "absent_source", "multi_output",
    "overlapping_inputs", "empty_input", "bad_stage_config",
])
def test_input_revision_rejects_unsupported_or_unmatched_inputs(case):
    adapter, result, seen = _input_fixture()
    kwargs = {"expected_input": "original source",
              "expected_stage_inputs": {"title": "original title"}}
    src = result["hits"]["hits"][0]["_source"]
    if case == "missing_stage":
        kwargs["expected_stage_inputs"] = {}
    elif case == "extra_stage":
        kwargs["expected_stage_inputs"]["other"] = "extra"
    elif case == "output_overlap":
        adapter.cfg["output_col"] = "body"
    elif case == "meta_overlap":
        adapter.cfg["rerun"] = {"meta_field": "title"}
    elif case == "time_overlap":
        adapter.cfg["input_col"] = "update_time_ai"
    elif case == "array_source":
        src["body"] = ["original source"]
    elif case == "absent_source":
        src.pop("title")
    elif case == "multi_output":
        adapter.cfg["output_col"] = ["result", "other"]
    elif case == "overlapping_inputs":
        adapter.cfg["stage_source_input_cols"] = ["body.title"]
        kwargs["expected_stage_inputs"] = {"body.title": "original title"}
    elif case == "empty_input":
        kwargs["expected_input"] = " "
    elif case == "bad_stage_config":
        adapter.cfg["stage_source_input_cols"] = "title"
    with pytest.raises(SourceObservationUnavailable, match="^source observation unavailable$"):
        adapter.observe_quality_retry_inputs("business-key", **kwargs)


def test_input_revision_can_be_bound_to_existing_private_retry_identity():
    from czjLLM.es_mode.quality_retry_contract import RetryIdentity
    adapter, _, _ = _input_fixture()
    observed = adapter.observe_quality_retry_inputs(
        "business-key", expected_input="original source",
        expected_stage_inputs={"title": "original title"})
    identity = RetryIdentity(observed.scoped_document_revision(),
                             "result", "a" * 64, "quality-v1")
    assert "original source" not in repr(identity)
