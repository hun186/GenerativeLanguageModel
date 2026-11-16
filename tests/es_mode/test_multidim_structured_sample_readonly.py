"""Synthetic, privacy-safe no-network tests of nested-only live ES sample."""
import base64
import json
import ssl
from copy import deepcopy

import pytest

from czjLLM.common.multidim_index_sample_audit import summarize_structured_sample
from scripts.audit_multidim_structured_sample_readonly import (
    _fetch_sample, _count, _get_search, main,
)


def _event_block():
    return {
        "article_date_iso": None, "article_date_precision": "unknown",
        "Event": [{
            "event_id": "SENSITIVE_EVENT_KEY",
            "time_iso": "2023-08-24", "time_raw": "private raw",
            "time_precision": "day",
        }],
        "Event_Timeline": [],
        "evidence_snippets": [],
    }


def _no_event_block():
    return {
        "article_date_iso": None, "article_date_precision": "unknown",
        "Event": [], "Event_Timeline": [], "evidence_snippets": [],
    }


def _hit(name, block):
    return {
        "_index": "news_test", "_id": name,
        "_source": {"multidim_event_json": [block]},
    }


def test_report_separates_profile_no_event_from_time_unverified_and_raw_documents():
    records = [
        _hit("PRIVATE_A", _event_block()),
        _hit("PRIVATE_B", _no_event_block()),
        _hit("PRIVATE_C", {"Event": [], "Event_Timeline": []}),
    ]
    before = deepcopy(records)
    report = summarize_structured_sample(44796, 23863, records)
    assert report["profile_counts"]["PROFILE_ACCEPTED_NO_EVENTS"] == 1
    assert report["profile_counts"]["PROFILE_ACCEPTED_EVENT_DATE_EMPTY_TIMELINE"] == 1
    assert report["profile_counts"]["PROFILE_REJECTED"] == 1
    assert report["profile_accepted_no_events_and_task_guard_eligible"] == 1
    assert report["sample_scope"] == "NESTED_MULTIDIM_PATH_MATCH_NOT_ALL_DOCUMENTS"
    assert report["full_index_document_count"] == 44796
    assert report["nested_candidate_document_count"] == 23863
    assert report["effective_runtime_rerun"] == "NOT_EVALUATED"
    assert report["raw_documents_exported"] is False
    assert records == before
    dumped = json.dumps(report)
    for secret in ("PRIVATE_A", "PRIVATE_B", "PRIVATE_C",
                   "SENSITIVE_EVENT_KEY", "private raw", "2023-08-24"):
        assert secret not in dumped


@pytest.mark.parametrize("bad", [
    [{"_index": "private_index", "_id": "one", "_source": {}}],
    [{"_index": "news_test", "_id": "one", "_source": None}],
    [{"_index": "news_test", "_id": "one", "_source": {}},
     {"_index": "news_test", "_id": "one", "_source": {}}],
])
def test_structured_sample_keeps_mixed_event_blocks_separate():
    sample = _hit("PRIVATE_MIXED", [_event_block(), _no_event_block()])
    # The sample aggregation intentionally classifies whole documents; the
    # _source field may contain multiple independently valid article blocks.
    sample["_source"]["multidim_event_json"] = [
        _event_block(), _no_event_block()]
    report = summarize_structured_sample(10, 1, [sample])
    assert report["profile_counts"]["PROFILE_ACCEPTED_MIXED_EVENT_PRESENCE"] == 1
    assert report["profile_counts"]["PROFILE_ACCEPTED_NO_EVENTS"] == 0
    assert report["profile_accepted_no_events_and_task_guard_eligible"] == 0


def test_reject_unverifiable_sample_without_partial_counters(bad):
    with pytest.raises(ValueError, match="UNVERIFIED_SAMPLE"):
        summarize_structured_sample(20, 10, bad)


def test_reject_invalid_denominators_and_success_biased_sizes():
    with pytest.raises(ValueError, match="UNVERIFIED_SAMPLE"):
        summarize_structured_sample(10, 20, [])
    with pytest.raises(ValueError, match="UNVERIFIED_SAMPLE"):
        summarize_structured_sample(10, 0, [_hit("one", _event_block())])
    with pytest.raises(ValueError, match="UNVERIFIED_SAMPLE"):
        summarize_structured_sample(True, 0, [])


@pytest.mark.parametrize("payload", [
    {}, {"hits": {"total": 1}}, {"hits": {"total": {"relation": "gte", "value": 10000}}},
    {"hits": {"total": {"relation": "eq", "value": -1}}},
])
def test_count_must_be_exact_not_lower_bound(payload):
    with pytest.raises(ValueError, match="COUNT_NOT_EXACT"):
        _count(payload)


def test_no_run_is_safe_default_and_never_prompts(capsys):
    assert main([]) == 2
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "NOT_TESTED"
    assert result["reason_code"] == "OPERATOR_NOT_OPTED_IN"


def test_sample_is_three_https_gets_only_and_ca_verified(monkeypatch, tmp_path):
    cert = tmp_path / "test-ca.crt"
    cert.write_text("fixture", encoding="utf-8")
    class Context:
        verify_mode = ssl.CERT_REQUIRED
        check_hostname = True
    context = Context()
    monkeypatch.setattr(
        "scripts.audit_multidim_structured_sample_readonly.ssl.create_default_context",
        lambda cafile: context,
    )
    calls = []
    sample_hits = [_hit("PRIVATE_A", _event_block()), _hit("PRIVATE_B", _no_event_block())]
    responses = [
        {"hits": {"total": {"relation": "eq", "value": 100}, "hits": []}},
        {"hits": {"total": {"relation": "eq", "value": 2}, "hits": []}},
        {"hits": {"total": {"relation": "eq", "value": 2}, "hits": sample_hits}},
    ]
    responses = [
        {**res, "timed_out": False,
         "_shards": {"total": 1, "successful": 1, "skipped": 0, "failed": 0}}
        for res in responses
    ]
    class Response:
        def __init__(self, value): self.value = value
        def __enter__(self): return self
        def __exit__(self, *_): return False
        def getcode(self): return 200
        def read(self, n): return json.dumps(self.value).encode("utf-8")
    class FakeOpener:
        def open(self, req, timeout):
            calls.append((req.full_url, req.get_method(), req.get_header("Authorization"), timeout))
            return Response(responses[len(calls) - 1])
    monkeypatch.setattr(
        "scripts.audit_multidim_structured_sample_readonly.build_opener",
        lambda *args: FakeOpener(),
    )
    result = _fetch_sample(
        "https://es.example.invalid:9200", str(cert), "operator",
        "SENSITIVE_PASSWORD", sample_size=2, skip_hostname=True,
    )
    assert result["profile_counts"]["PROFILE_ACCEPTED_NO_EVENTS"] == 1
    assert result["profile_accepted_no_events_and_task_guard_eligible"] == 1
    assert result["sampled_candidate_count"] == 2
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is False
    assert len(calls) == 3
    for url, method, authorization, timeout in calls:
        assert method == "GET"
        assert url.startswith("https://es.example.invalid:9200/news_test/_search?")
        assert timeout <= 20
        assert authorization == "Basic " + base64.b64encode(
            b"operator:SENSITIVE_PASSWORD").decode("ascii")
    assert "SENSITIVE_PASSWORD" not in json.dumps(result)
    assert "PRIVATE_A" not in json.dumps(result)


@pytest.mark.parametrize("bad_metadata", [
    {"timed_out": True},
    {"_shards": {"total": 2, "successful": 1, "skipped": 0, "failed": 1}},
    {"_shards": {"total": 2, "successful": 1, "skipped": 0, "failed": 0}},
    {"terminated_early": True},
])
def test_http_200_with_partial_shards_or_timeout_fails_closed(bad_metadata):
    response = {
        "timed_out": False,
        "_shards": {"total": 1, "successful": 1, "failed": 0},
        "hits": {"total": {"relation": "eq", "value": 20}, "hits": []},
    }
    response.update(bad_metadata)

    class FakeResponse:
        def __enter__(self): return self
        def __exit__(self, *_): return False
        def getcode(self): return 200
        def read(self, n): return json.dumps(response).encode("utf-8")

    class FakeOpener:
        def open(self, req, timeout): return FakeResponse()

    with pytest.raises(ValueError, match="SEARCH_PARTIAL_OR_UNVERIFIED"):
        _get_search("https://es.example.invalid:9200", FakeOpener(),
                    {"size": 0, "query": {"match_all": {}}})


def test_sample_size_does_not_allow_unbounded_es_load(capsys):
    assert main(["--run", "--sample-size", "301"]) == 2
    output = json.loads(capsys.readouterr().out)
    assert output["reason_code"] == "SAMPLE_SIZE_INVALID"


def test_sample_query_rejects_broad_url(monkeypatch):
    class Blocked:
        def open(self, req, timeout):
            raise AssertionError("unexpected network")
    with pytest.raises(ValueError, match="SEARCH_URI_TOO_LONG"):
        _get_search("https://es.example.invalid:9200", Blocked(),
                    {"query": {"terms": {"x": ["X" * 5000]}}})
