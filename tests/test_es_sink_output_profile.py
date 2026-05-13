import sys
import types
from types import SimpleNamespace

if "elasticsearch" not in sys.modules:
    elasticsearch_stub = types.ModuleType("elasticsearch")
    elasticsearch_stub.Elasticsearch = object
    elasticsearch_stub.helpers = types.SimpleNamespace(bulk=lambda *args, **kwargs: (0, []))
    sys.modules["elasticsearch"] = elasticsearch_stub
    sys.modules["elasticsearch.helpers"] = elasticsearch_stub.helpers

from czjLLM.es_mode.runtime.sinks.es_sink import ESSink


def _sink(output_col="generic_json", output_profile="none"):
    ctx = SimpleNamespace(output_profile=output_profile)
    return ESSink(ctx, es_client=None, index="test-index", output_col=output_col, flush_every=1000)


def test_generic_output_profile_does_not_mutate_payload():
    sink = _sink(output_col="analysis_json", output_profile="none")
    payload = [{"Event": {"time": "2025-01-02"}, "custom": {"keep": True}}]

    normalized = sink._normalize_payload_by_profile(payload)

    assert normalized == payload
    assert "time_iso" not in normalized[0]["Event"]


def test_legacy_multidim_output_col_infers_event_profile():
    sink = _sink(output_col="multidim_event_json", output_profile="auto")
    payload = [{"Event": {"time": "2025-01-02"}}]

    normalized = sink._normalize_payload_by_profile(payload)

    assert normalized[0]["Event"]["time_iso"] == "2025-01-02"
    assert normalized[0]["Event"]["time_precision"] == "day"


def test_explicit_multidim_event_profile_works_with_custom_output_col():
    sink = _sink(output_col="custom_events", output_profile="multidim_event")
    payload = [{"Event": {"time": "2025-01"}}]

    normalized = sink._normalize_payload_by_profile(payload)

    assert normalized[0]["Event"]["time_iso"] == "2025-01-01"
    assert normalized[0]["Event"]["time_precision"] == "month"


def test_write_output_false_skips_buffering():
    ctx = SimpleNamespace(output_profile="json", write_output=False, debug_es_sink=True)
    sink = ESSink(ctx, es_client=None, index="test-index", output_col="analysis_json", flush_every=1000)

    sink.write_main(pk="doc-1", result_text='{"x": 1}')

    assert sink._buffer == []
