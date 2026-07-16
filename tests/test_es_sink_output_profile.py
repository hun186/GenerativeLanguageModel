import sys
import json
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


def test_generic_llm_result_json_auto_does_not_infer_event_profile():
    sink = _sink(output_col="llm_result_json", output_profile="auto")
    payload = [{"Event": {"time": "2025-01-02"}}]

    normalized = sink._normalize_payload_by_profile(payload)

    assert normalized == payload
    assert "time_iso" not in normalized[0]["Event"]


def test_explicit_multidim_event_profile_works_with_custom_output_col():
    sink = _sink(output_col="custom_events", output_profile="multidim_event")
    payload = [{"Event": {"time": "2025-01"}}]

    normalized = sink._normalize_payload_by_profile(payload)

    assert normalized[0]["Event"]["time_iso"] == "2025-01-01"
    assert normalized[0]["Event"]["time_precision"] == "month"


def test_external_output_profile_plugin_can_transform_payload():
    module = types.ModuleType("tests.fake_es_profile_plugin")

    def register_output_profiles(registry):
        registry.register("unit_upper", lambda payload, **kwargs: {"value": payload["value"].upper()})

    module.register_output_profiles = register_output_profiles
    sys.modules[module.__name__] = module
    ctx = SimpleNamespace(output_profile="unit_upper", output_profile_plugins=[module.__name__])
    sink = ESSink(ctx, es_client=None, index="test-index", output_col="plugin_json", flush_every=1000)

    normalized = sink._normalize_payload_by_profile({"value": "ok"})

    assert normalized == {"value": "OK"}


def test_write_output_false_skips_buffering():
    ctx = SimpleNamespace(output_profile="json", write_output=False, debug_es_sink=True)
    sink = ESSink(ctx, es_client=None, index="test-index", output_col="analysis_json", flush_every=1000)

    sink.write_main(pk="doc-1", result_text='{"x": 1}')

    assert sink._buffer == []


def test_multidim_event_profile_drops_invalid_nested_placeholders():
    sink = _sink(output_col="multidim_event_json", output_profile="multidim_event")
    payload = [{
        "Event": None,
        "Involved_Parties": [None, "", {"party_name": "WIPO", "party_role": "org"}],
        "Impact": "",
        "Event_Timeline": [{"date": "2025-01"}, None],
        "evidence_snippets": None,
    }]

    normalized = sink._normalize_payload_by_profile(payload)

    assert normalized[0]["Event"] == {}
    assert normalized[0]["Involved_Parties"] == [{"party_name": "WIPO", "party_role": "org"}]
    assert normalized[0]["Impact"] == []
    assert normalized[0]["Event_Timeline"] == [
        {
            "date": "2025-01",
            "date_raw": "2025-01",
            "date_iso": "2025-01-01",
            "date_precision": "month",
        }
    ]
    assert normalized[0]["evidence_snippets"] == []


def test_single_stage_self_envelope_is_unwrapped_before_es_writeback():
    sink = _sink(output_col="multidim_event_json", output_profile="multidim_event")
    inner = {"Event": {"time": "2026-06-08"}, "Event_Timeline": [{"date": "2026-06-08"}]}
    envelope = {"multidim_event_json": [json.dumps(inner, ensure_ascii=False)]}

    sink.write_main("doc-1", {"multidim_event_json": json.dumps(envelope, ensure_ascii=False)})

    doc = sink._buffer[0]["doc"]
    assert set(doc["multidim_event_json"][0].keys()) != {"multidim_event_json"}
    assert doc["multidim_event_json"][0]["Event"]["time_iso"] == "2026-06-08"
    assert doc["multidim_event_json"][0]["Event_Timeline"][0]["date_iso"] == "2026-06-08"
