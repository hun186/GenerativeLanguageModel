from copy import deepcopy

import pytest

from czjLLM.es_mode.output_profiles import OutputProfileValidationError, get_default_registry


def _valid_payload():
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
        "Person": [{"event_ids": ["E1"], "name": "Alice"}],
        "Event_Timeline": [{
            "event_ids": ["E1"],
            "time_raw": "2026-09-19",
            "time_iso": "2026-09-19",
            "time_precision": "day",
            "description": "event",
        }],
    }]


def test_generic_profile_is_identity_passthrough():
    payload = {"custom": [1, {"keep": True}]}
    assert get_default_registry().normalize_payload("generic", payload) is payload


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda p: p[0].pop("Event"), r"Event is required"),
        (lambda p: p[0].__setitem__("facet", "not-a-list"), r"facet must be a JSON array"),
        (
            lambda p: p[0]["Event_Timeline"][0].update(
                {"time_iso": "2026-09-19", "time_precision": "month"}
            ),
            r"month precision requires normalized day 01",
        ),
        (lambda p: p[0]["Event"].append(deepcopy(p[0]["Event"][0])), r"duplicate event_id 'E1'"),
        (lambda p: p[0]["Person"][0].__setitem__("event_ids", ["MISSING"]), r"references missing Event.event_id"),
        (
            lambda p: p[0]["Event"][0].__setitem__("consequence", {"impact_description": "bad"}),
            r"consequence must be a string or null; got dict",
        ),
    ],
)
def test_multidim_profile_failures_are_typed_at_registry_boundary(mutate, message):
    payload = _valid_payload()
    mutate(payload)

    with pytest.raises(OutputProfileValidationError, match=message) as caught:
        get_default_registry().normalize_payload("multidim_event", payload)

    assert caught.value.profile == "multidim_event"


def test_multidim_profile_accepts_and_preserves_valid_contract_shape():
    payload = _valid_payload()
    normalized = get_default_registry().normalize_payload("multidim_event", payload)

    assert normalized[0]["Event"] == payload[0]["Event"]
    assert normalized[0]["Person"] == payload[0]["Person"]
    assert normalized[0]["Event_Timeline"] == payload[0]["Event_Timeline"]
    assert normalized[0]["Involved_Parties"] == []
    assert normalized[0]["Impact"] == []
    assert normalized[0]["evidence_snippets"] == []
