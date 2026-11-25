import importlib
import pytest
import sys
import types
from types import SimpleNamespace


def _load_es_sink_module(monkeypatch):
    try:
        has_elasticsearch = importlib.util.find_spec("elasticsearch") is not None
    except ValueError:
        has_elasticsearch = "elasticsearch" in sys.modules
    if not has_elasticsearch:
        fake_es = types.ModuleType("elasticsearch")
        fake_es.Elasticsearch = object
        fake_es.helpers = types.SimpleNamespace(bulk=lambda *args, **kwargs: (0, []))
        monkeypatch.setitem(sys.modules, "elasticsearch", fake_es)
    return importlib.import_module("czjLLM.es_mode.runtime.sinks.es_sink")


class DummyIndices:
    def exists(self, index):
        return True

    def refresh(self, index):
        return None


class DummyES:
    indices = DummyIndices()


def test_es_sink_multifield_writeback_uses_rule_indexes_and_meta(monkeypatch):
    mod = _load_es_sink_module(monkeypatch)
    ctx = SimpleNamespace(
        output_col="main_result",
        output_profile="json",
        record_update_time=True,
        es_refresh_after_flush=False,
        es_writeback_rules=[
            {"output_col": "route_result", "index": "audit-index", "write_meta": False},
            {"output_col": "main_result", "index": "main-index", "meta_field": "main_meta"},
        ],
        task="demo-task",
        channel="demo-channel",
        source="unit-test",
    )
    sink = mod.ESSink(ctx, DummyES(), index="default-index", output_col="main_result", flush_every=999)

    sink.write_main("doc-1", {"route_result": "zh", "main_result": '[{"x": 1}]'})

    assert len(sink._buffer) == 2
    by_index = {item["_index"]: item["doc"] for item in sink._buffer}
    assert by_index["audit-index"]["route_result"] == "zh"
    assert "route_result_meta" not in by_index["audit-index"]
    assert by_index["main-index"]["main_result"] == [{"x": 1}]
    assert by_index["main-index"]["main_meta"]["output_field"] == "main_result"
    sink._buffer.clear()


def test_es_sink_resolves_business_key_to_real_es_id_before_bulk(monkeypatch):
    captured = {}
    fake_es = types.ModuleType("elasticsearch")
    fake_es.Elasticsearch = object

    def fake_bulk(es, actions, **kwargs):
        captured["actions"] = list(actions)
        return len(captured["actions"]), []

    fake_es.helpers = types.SimpleNamespace(bulk=fake_bulk)
    monkeypatch.setitem(sys.modules, "elasticsearch", fake_es)
    sys.modules.pop("czjLLM.es_mode.runtime.sinks.es_sink", None)
    mod = importlib.import_module("czjLLM.es_mode.runtime.sinks.es_sink")

    class SearchES(DummyES):
        def search(self, index, body, request_timeout=None):
            captured["search"] = {"index": index, "body": body, "request_timeout": request_timeout}
            return {"hits": {"hits": [{"_id": "real-es-doc-id"}]}}

    adapter = SimpleNamespace(
        cfg={"id_col": "sha1", "pk_keyword_suffix": ".keyword"},
        get_field_mapping=lambda index, field: {"fields": {"keyword": {}}},
    )
    ctx = SimpleNamespace(
        output_col="main_result",
        output_profile="json",
        es_refresh_after_flush=False,
        es_request_timeout=12,
        _es_adapter=adapter,
    )
    sink = mod.ESSink(ctx, SearchES(), index="docs", output_col="main_result", flush_every=999)

    sink.write_main("business-key-1", {"ok": True})
    sink.flush_all()

    assert captured["search"]["body"]["query"] == {"term": {"sha1.keyword": "business-key-1"}}
    assert captured["actions"][0]["_id"] == "real-es-doc-id"
    assert captured["actions"][0]["doc"]["main_result"] == {"ok": True}
    assert captured["actions"][0]["doc"]["sha1"] == "business-key-1"


def test_es_sink_mapping_errors_are_terminal_and_removed_from_buffer(monkeypatch):
    fake_es = types.ModuleType("elasticsearch")
    fake_es.Elasticsearch = object

    def fake_bulk(es, actions, **kwargs):
        list(actions)
        return 0, [{"update": {
            "_index": "docs",
            "_id": "doc-1",
            "status": 400,
            "error": {"type": "document_parsing_exception", "reason": "Expected text but found START_OBJECT"},
        }}]

    fake_es.helpers = types.SimpleNamespace(bulk=fake_bulk)
    monkeypatch.setitem(sys.modules, "elasticsearch", fake_es)
    sys.modules.pop("czjLLM.es_mode.runtime.sinks.es_sink", None)
    mod = importlib.import_module("czjLLM.es_mode.runtime.sinks.es_sink")

    ctx = SimpleNamespace(output_col="main_result", output_profile="json", es_refresh_after_flush=False)
    sink = mod.ESSink(ctx, DummyES(), index="docs", output_col="main_result", flush_every=999)
    sink.write_main("doc-1", {"ok": True})

    try:
        sink.flush_all()
    except mod.OutputProfileValidationError as exc:
        assert "ES mapping rejected 1 update(s)" in str(exc)
        assert "Expected text but found START_OBJECT" in str(exc)
    else:
        raise AssertionError("Expected RuntimeError for ES bulk errors")

    assert sink._buffer == []

def test_es_sink_explicit_ack_flushes_buffered_update(monkeypatch):
    """write_main enqueues; explicit confirmation must send the ES bulk."""
    mod = _load_es_sink_module(monkeypatch)
    captured = []

    def bulk(_es, actions, **_kwargs):
        captured.extend(actions)
        return len(captured), []

    monkeypatch.setattr(mod.helpers, "bulk", bulk)
    ctx = SimpleNamespace(
        output_col="multidim_event_json", output_profile="json",
        es_refresh_after_flush=False, es_flush_secs=3600,
    )
    sink = mod.ESSink(
        ctx, DummyES(), index="docs",
        output_col="multidim_event_json", flush_every=1000,
    )
    sink.write_main("doc-1", '{"ok": true}')
    assert len(sink._buffer) == 1
    assert not captured, "ES has not yet acknowledged any bulk write"
    sink.confirm_writeback()
    assert len(captured) == 1
    assert captured[0]["_id"] == "doc-1"
    assert captured[0]["doc"]["multidim_event_json"] == {"ok": True}
    assert sink._buffer == []

@pytest.mark.parametrize("error_type", [
    "strict_dynamic_mapping_exception", "illegal_argument_exception",
    "unrecognized_bad_request",
])
def test_es_ack_treats_all_bulk_400_as_terminal(monkeypatch, error_type):
    mod = _load_es_sink_module(monkeypatch)

    def bulk(_es, actions, **_kwargs):
        action = list(actions)[0]
        return 0, [{"update": {
            "_index": action["_index"], "_id": action["_id"],
            "status": 400, "error": {"type": error_type, "reason": "bad mapping"},
        }}]

    monkeypatch.setattr(mod.helpers, "bulk", bulk)
    ctx = SimpleNamespace(
        output_col="multidim_event_json", output_profile="json",
        es_refresh_after_flush=False, es_flush_secs=3600,
    )
    sink = mod.ESSink(ctx, DummyES(), index="docs", flush_every=1000)
    sink.write_main("doc-400", '{"ok": true}')
    with pytest.raises(mod.ESBulkRequestRejected, match="ES mapping rejected") as error:
        sink.confirm_writeback()
    assert isinstance(error.value, mod.OutputProfileValidationError)
    assert sink._buffer == [], "terminal 400 actions must not be retained"


def test_local_profile_rejection_is_not_es_bulk_rejection(monkeypatch):
    mod = _load_es_sink_module(monkeypatch)
    calls = []
    def unexpected_bulk(*args, **kwargs):
        calls.append(True)
        raise AssertionError("invalid local payload must not reach ES")
    monkeypatch.setattr(mod.helpers, "bulk", unexpected_bulk)
    ctx = SimpleNamespace(output_profile="multidim_event", es_refresh_after_flush=False)
    sink = mod.ESSink(ctx, DummyES(), index="docs",
                      output_col="multidim_event_json", flush_every=1000)
    with pytest.raises(mod.OutputProfileValidationError) as error:
        sink.write_main("doc-local", '[{"Event": [{"event_id": "e1", "unexpected_field": "x"}]}]')
    assert not isinstance(error.value, mod.ESBulkRequestRejected)
    assert not calls and not sink._buffer


def test_es_ack_429_is_retryable_and_failed_batch_can_be_discarded(monkeypatch):
    mod = _load_es_sink_module(monkeypatch)

    def bulk(_es, actions, **_kwargs):
        action = list(actions)[0]
        return 0, [{"update": {
            "_index": action["_index"], "_id": action["_id"],
            "status": 429,
            "error": {"type": "es_rejected_execution_exception", "reason": "busy"},
        }}]

    monkeypatch.setattr(mod.helpers, "bulk", bulk)
    ctx = SimpleNamespace(
        output_col="multidim_event_json", output_profile="json",
        es_refresh_after_flush=False, es_flush_secs=3600,
    )
    sink = mod.ESSink(ctx, DummyES(), index="docs", flush_every=1000)
    sink.write_main("doc-429", '{"ok": true}')
    with pytest.raises(RuntimeError, match="bulk update failed") as error:
        sink.confirm_writeback()
    assert not isinstance(error.value, mod.OutputProfileValidationError)
    assert len(sink._buffer) == 1
    sink.discard_unacknowledged_writeback()
    assert sink._buffer == [] and sink._buffer_bytes == 0



def _quality_profile_fixture():
    return [{
        "article_date_iso": None,
        "article_date_precision": "unknown",
        "Event": [{
            "event_id": "E1",
            "time_raw": "2026-09-19",
            "time_iso": "2026-09-19",
            "time_precision": "day",
            "consequence": None,
        }],
        "Person": [{"event_ids": ["E1"], "name": "Example"}],
    }]


def test_quality_profile_observes_actual_builtin_without_writeback(monkeypatch):
    import json
    from copy import deepcopy
    from czjLLM.es_mode.quality_output_profile_observation import ProfileOutcome
    mod = _load_es_sink_module(monkeypatch)
    sink = mod.ESSink(SimpleNamespace(output_profile="auto"), DummyES(),
                      index="docs", output_col="multidim_event_json", flush_every=999)
    def fail_bulk(*args, **kwargs):
        pytest.fail("read-only profile observation must not call bulk")
    monkeypatch.setattr(mod.helpers, "bulk", fail_bulk)
    payload = {"multidim_event_json": json.dumps(_quality_profile_fixture())}
    before = deepcopy(payload)
    accepted = sink.observe_quality_output_profile(payload, "multidim_event_json")
    assert accepted.outcome is ProfileOutcome.STRUCTURALLY_ACCEPTED
    assert payload == before and sink._buffer == []
    invalid = _quality_profile_fixture()
    invalid[0]["Person"][0]["event_ids"] = ["PRIVATE_MISSING"]
    rejected = sink.observe_quality_output_profile(invalid, "multidim_event_json")
    assert rejected.outcome is ProfileOutcome.STRUCTURALLY_REJECTED
    assert accepted.profile_version == rejected.profile_version
    assert "PRIVATE_MISSING" not in repr(rejected) and sink._buffer == []
    assert invalid[0]["Person"][0]["event_ids"] == ["PRIVATE_MISSING"]
    with pytest.raises(mod.OutputProfileValidationError):
        sink.write_main("doc-1", invalid)
    assert sink._buffer == []


@pytest.mark.parametrize("unsupported", [
    "passthrough", "plugins", "routes", "flatten", "disabled", "other_column",
    "registry_override", "empty",
])
def test_quality_profile_observation_rejects_unsupported_boundary(monkeypatch, unsupported):
    from czjLLM.es_mode.quality_output_profile_observation import (
        OutputProfileObservationUnavailable,
    )
    mod = _load_es_sink_module(monkeypatch)
    ctx = SimpleNamespace(output_profile="multidim_event")
    sink = mod.ESSink(ctx, DummyES(), index="docs", output_col="multidim_event_json")
    col = sink.output_col
    payload = _quality_profile_fixture()
    if unsupported == "passthrough":
        sink.output_profile = "json"
    elif unsupported == "plugins":
        ctx.output_profile_plugins = ["untrusted-plugin"]
    elif unsupported == "routes":
        ctx.es_writeback_rules = [{"output_col": col, "index": "other"}]
    elif unsupported == "flatten":
        sink.flatten_json = True
    elif unsupported == "disabled":
        sink.write_output = False
    elif unsupported == "other_column":
        col = "other"
    elif unsupported == "registry_override":
        monkeypatch.setitem(mod.get_default_registry()._transformers,
                            "multidim_event", lambda data, **kwargs: data)
    elif unsupported == "empty":
        payload = []
    with pytest.raises(OutputProfileObservationUnavailable,
                       match="^output profile observation unavailable$"):
        sink.observe_quality_output_profile(payload, col)
    assert sink._buffer == []


def _combined_candidate_fixture(monkeypatch):
    from czjLLM.es_mode.adapters.elasticsearch_adapter import ElasticsearchAdapter
    mod = _load_es_sink_module(monkeypatch)
    col = "multidim_event_json"
    adapter = ElasticsearchAdapter({
        "src_index": "docs", "tgt_index": "docs", "output_col": col,
        "rerun": {"enable": True, "required_output_checks": [
            {"path": col, "validator": "multidim_event_time"}]},
    })
    adapter.es = DummyES()
    ctx = SimpleNamespace(output_profile="auto", _es_adapter=adapter)
    sink = mod.ESSink(ctx, adapter.es, index="docs", output_col=col, flush_every=999)
    monkeypatch.setattr(mod.helpers, "bulk", lambda *a, **k: pytest.fail("no bulk"))
    return sink, adapter, col


def test_combined_candidate_binds_both_rules_and_one_normalized_payload(monkeypatch):
    import json
    from copy import deepcopy
    from czjLLM.es_mode.quality_candidate_observation import CandidateOutcome
    from czjLLM.es_mode.quality_retry_contract import RetryIdentity
    sink, adapter, col = _combined_candidate_fixture(monkeypatch)
    payload = {col: json.dumps(_quality_profile_fixture())}
    original = deepcopy(payload)
    accepted = sink.observe_quality_candidate(adapter, payload, col)
    assert accepted.outcome is CandidateOutcome.STRUCTURALLY_ACCEPTED
    assert payload == original and sink._buffer == []
    invalid = _quality_profile_fixture()
    invalid[0]["Person"][0]["event_ids"] = ["PRIVATE_INVALID"]
    rejected = sink.observe_quality_candidate(adapter, invalid, col)
    assert rejected.outcome is CandidateOutcome.PROFILE_REJECTED
    assert rejected.quality_rule_version == accepted.quality_rule_version
    assert "PRIVATE_INVALID" not in repr(rejected)
    adapter.cfg["rerun"]["required_output_checks"][0]["min_valid_count"] = 2
    required = sink.observe_quality_candidate(adapter, payload, col)
    assert required.outcome is CandidateOutcome.REQUIRED_OUTPUT_REJECTED
    assert required.quality_rule_version != accepted.quality_rule_version
    rejected_new_rule = sink.observe_quality_candidate(adapter, invalid, col)
    assert rejected_new_rule.quality_rule_version == required.quality_rule_version
    assert rejected_new_rule.outcome is CandidateOutcome.PROFILE_REJECTED
    RetryIdentity("private", col, "a" * 64, required.quality_rule_version)
    assert sink._buffer == []


@pytest.mark.parametrize("case", ["other_adapter", "other_index", "other_client",
                                   "multi_output", "conflicting_output", "timestamp",
                                   "disabled_rules", "outside_path", "empty_payload"])
def test_combined_candidate_unsupported_scope_is_unavailable(monkeypatch, case):
    from czjLLM.es_mode.quality_candidate_observation import CandidateObservationUnavailable
    sink, adapter, col = _combined_candidate_fixture(monkeypatch)
    payload = _quality_profile_fixture()
    if case == "other_adapter":
        sink.ctx._es_adapter = None
    elif case == "other_index":
        adapter.cfg["tgt_index"] = "other"
    elif case == "other_client":
        adapter.es = DummyES()
    elif case == "multi_output":
        adapter.cfg["output_cols"] = [col, "secondary"]
    elif case == "conflicting_output":
        adapter.cfg["output_col"] = "other"
        adapter.cfg["output_cols"] = [col]
    elif case == "timestamp":
        sink.ctx.update_time_inside_output = True
    elif case == "disabled_rules":
        adapter.cfg["rerun"]["enable"] = False
    elif case == "outside_path":
        adapter.cfg["rerun"]["required_output_checks"] = [
            {"path": "outside", "relative_to_output": False}]
    elif case == "empty_payload":
        payload = []
    with pytest.raises(CandidateObservationUnavailable,
                       match="^quality candidate observation unavailable$"):
        sink.observe_quality_candidate(adapter, payload, col)
    assert sink._buffer == []
