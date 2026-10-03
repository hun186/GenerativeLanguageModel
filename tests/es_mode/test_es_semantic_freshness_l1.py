from czjLLM.es_mode.adapters.pending_policy import ElasticsearchPendingPolicyMixin
from czjLLM.es_mode.adapters.pending_policy_no_eventids import (
    ElasticsearchPendingPolicyMixin as NoEventIdsPendingPolicyMixin,
)
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from czjLLM.es_mode.adapters import elasticsearch_adapter as adapter_module
from czjLLM.es_mode.adapters.elasticsearch_adapter import ElasticsearchAdapter


class Policy(ElasticsearchPendingPolicyMixin):
    def __init__(self, rerun): self.cfg = {"output_col": "summary", "rerun": rerun}


class NoEventIdsPolicy(NoEventIdsPendingPolicyMixin):
    def __init__(self, rerun): self.cfg = {"output_col": "summary", "rerun": rerun}


def test_es_execution_fingerprint_is_cumulative():
    strict = Policy({"enable": True, "execution_fingerprint": "new"})
    assert strict.check_source_pending({"summary": "ok", "summary_meta": {"execution_fingerprint": "new"}}, ["summary"]).pending is False
    assert strict.check_source_pending({"summary": "ok", "summary_meta": {}}, ["summary"]).reason == "missing_processing_identity"
    assert strict.check_source_pending({"summary": "ok", "summary_meta": {"execution_fingerprint": "old"}}, ["summary"]).reason == "execution_fingerprint_mismatch"
    legacy = Policy({"enable": False})
    assert legacy.check_source_pending({"summary": "ok"}, ["summary"]).pending is False


def test_es_semantic_metadata_missing_and_mismatch_reasons_match_query_policy():
    cases = [
        ({"model_tag": "m"}, {}, "missing_meta"),
        ({"model_tag": "m"}, {"model_tag": "old"}, "model_tag_mismatch"),
        ({"pipeline_hash": "p"}, {}, "missing_meta"),
        ({"pipeline_hash": "p"}, {"pipeline_hash": "old"}, "pipeline_hash_mismatch"),
    ]
    for configured, meta, reason in cases:
        policy = Policy({"enable": True, **configured})
        assert policy._needs_rerun_clause("idx", "summary") is not None
        assert policy.check_source_pending({"summary": "ok", "summary_meta": meta}, ["summary"]).reason == reason
        matching = dict(configured)
        assert policy.check_source_pending(
            {"summary": "ok", "summary_meta": matching}, ["summary"]
        ).reason == "fresh_completed"


def test_es_required_output_and_time_policy_specific_reasons():
    required = Policy({"enable": True, "required_output_checks": [{"path": "needed"}]})
    assert required.check_source_pending({"summary": {"other": "x"}}, ["summary"]).reason == "required_output_invalid"
    old = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
    stale = Policy({"enable": True, "stale_after_days": 2})
    assert stale.check_source_pending(
        {"summary": "ok", "summary_meta": {"processed_at": old}}, ["summary"]
    ).reason == "stale_after_days"
    forced = Policy({"enable": True, "force_since": datetime.now(timezone.utc).isoformat()})
    assert forced.check_source_pending(
        {"summary": "ok", "summary_meta": {"processed_at": old}}, ["summary"]
    ).reason == "force_since"


def _required_cfg():
    return {"output_col": "summary", "rerun": {
        "enable": True,
        "required_output_checks": [{
            "path": "events.date", "validator": "date", "format": "yyyy-MM-dd",
            "min_valid_count": 2,
        }],
    }}


def test_single_index_required_checks_broaden_then_python_postfilter(monkeypatch):
    docs = [
        {"_id": "A", "_source": {"body": "a", "summary": {"events": [
            {"date": "2026-01-01"}, {"date": "2026-01-02"}]}}},
        {"_id": "B", "_source": {"body": "b", "summary": {"events": [
            {"date": "not-a-date"}, {"date": "2026-01-02"}]}}},
        {"_id": "C", "_source": {"body": "c"}},
    ]
    captured = {}
    def scan(**kwargs):
        captured["query"] = kwargs["query"]
        return iter(docs)
    monkeypatch.setattr(adapter_module, "helpers", SimpleNamespace(scan=scan))
    adapter = ElasticsearchAdapter(_required_cfg())
    adapter.es = SimpleNamespace(search=lambda **_kwargs: {"hits": {"hits": []}})
    selected = list(adapter._scan_single_index_pending(
        "idx", "_id", "body", ["summary"], 100))
    assert [row[0] for row in selected] == ["B", "C"]
    query_bool = captured["query"]["query"]["bool"]
    assert "should" not in query_bool and "minimum_should_match" not in query_bool
    assert adapter.check_source_pending(docs[0]["_source"], ["summary"]).reason == "fresh_completed"
    assert adapter.check_source_pending(docs[1]["_source"], ["summary"]).reason == "required_output_invalid"
    assert adapter.check_source_pending(docs[2]["_source"], ["summary"]).reason == "missing_output"


def test_ordinary_single_index_keeps_optimized_query(monkeypatch):
    captured = {}
    monkeypatch.setattr(adapter_module, "helpers", SimpleNamespace(
        scan=lambda **kwargs: captured.setdefault("query", kwargs["query"]) and iter([])))
    adapter = ElasticsearchAdapter({"output_col": "summary", "rerun": {
        "enable": True, "execution_fingerprint": "current"}})
    adapter.es = SimpleNamespace(search=lambda **_kwargs: {"hits": {"hits": []}})
    assert list(adapter._scan_single_index_pending("idx", "_id", "body", ["summary"], 100)) == []
    query_bool = captured["query"]["query"]["bool"]
    assert query_bool["minimum_should_match"] == 1 and query_bool["should"]


def test_dual_index_bulk_check_keeps_invalid_target_pending(monkeypatch):
    source = [{"_id": "A", "_source": {"body": "a"}},
              {"_id": "B", "_source": {"body": "b"}}]
    targets = {
        "A": {"summary": {"events": [{"date": "2026-01-01"}, {"date": "2026-01-02"}]}},
        "B": {"summary": {"events": [{"date": "bad"}]}},
    }
    monkeypatch.setattr(adapter_module, "helpers", SimpleNamespace(
        scan=lambda **_kwargs: iter(source)))
    class ES:
        def mget(self, *, body, **_kwargs):
            return {"docs": [{"_id": key, "found": True, "_source": targets[key]}
                             for key in body["ids"]]}
    adapter = ElasticsearchAdapter(_required_cfg()); adapter.es = ES()
    selected = list(adapter._scan_dual_index_pending(
        "src", "tgt", "_id", "body", ["summary"], 100))
    assert [row[0] for row in selected] == ["B"]


def test_no_eventids_required_output_postfilter_policy_parity():
    rerun = _required_cfg()["rerun"]
    source = {"summary": {"events": [{"date": "bad"}]}}
    regular = Policy(rerun)
    no_eventids = NoEventIdsPolicy(rerun)
    assert regular._requires_python_freshness_scan(["summary"]) is True
    assert no_eventids._requires_python_freshness_scan(["summary"]) is True
    assert regular.check_source_pending(source, ["summary"]) == \
        no_eventids.check_source_pending(source, ["summary"])
