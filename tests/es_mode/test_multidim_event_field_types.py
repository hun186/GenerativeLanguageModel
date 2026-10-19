from __future__ import annotations

import pytest

from czjLLM.es_mode.output_profiles.multidim_event import normalize_multidim_event_payload


def _payload(consequence):
    return [{
        "article_date_iso": None,
        "article_date_precision": "unknown",
        "Event": [{
            "event_id": "E1",
            "time_raw": None,
            "time_iso": None,
            "time_precision": "unknown",
            "consequence": consequence,
        }],
    }]


@pytest.mark.parametrize("value", ["部署進程持續受阻", None])
def test_event_consequence_accepts_text_or_null(value):
    result = normalize_multidim_event_payload(_payload(value))

    assert result[0]["Event"][0]["consequence"] is value


def test_event_consequence_rejects_impact_like_object_before_es_writeback():
    with pytest.raises(
        TypeError,
        match=r"Event\[0\]\.consequence must be a string or null; got dict",
    ):
        normalize_multidim_event_payload(_payload({
            "impact_description": "部署進程持續受阻",
            "event_ids": ["E1"],
        }))


def test_flat_importance_scores_relocated_into_documented_nested_object():
    from copy import deepcopy

    scores = {
        "coverage": 85, "novelty": 25, "impact": 70,
        "credibility": 90, "importance_score": 71,
    }
    payload = _payload(None)
    payload[0].update(scores)
    original = deepcopy(payload)
    result = normalize_multidim_event_payload(payload)
    assert result[0]["importance"] == scores
    assert all(key not in result[0] for key in scores)
    assert payload == original


def test_partial_flat_importance_safely_combines_disjoint_nested_scores():
    payload = _payload(None)
    payload[0].update({
        "importance": {"coverage": 85, "novelty": 25},
        "impact": 70, "credibility": None, "importance_score": 71,
    })
    result = normalize_multidim_event_payload(payload)
    assert result[0]["importance"] == {
        "coverage": 85, "novelty": 25, "impact": 70,
        "credibility": None, "importance_score": 71,
    }


def test_identical_flat_and_nested_importance_is_idempotent():
    payload = _payload(None)
    payload[0].update({"coverage": 85, "importance": {"coverage": 85}})
    normalized = normalize_multidim_event_payload(payload)
    assert normalized[0]["importance"] == {"coverage": 85}
    assert normalize_multidim_event_payload(normalized) == normalized


def test_conflicting_flat_and_nested_importance_rejected_not_overwritten():
    payload = _payload(None)
    payload[0].update({"coverage": 80, "importance": {"coverage": 85}})
    with pytest.raises(ValueError, match="importance.coverage conflicts"):
        normalize_multidim_event_payload(payload)


@pytest.mark.parametrize("invalid", [False, "85", 85.5, [], {}])
def test_invalid_flat_score_types_still_fail_closed(invalid):
    payload = _payload(None)
    payload[0]["coverage"] = invalid
    with pytest.raises(TypeError, match="importance.coverage must be integer or null"):
        normalize_multidim_event_payload(payload)


@pytest.mark.parametrize(
    "nested,flat", [(True, 1), (85.0, 85), (False, 0), ("85", 85), (85, True)],
)
def test_equal_looking_invalid_nested_and_flat_scores_do_not_escape_type_validation(
    nested, flat,
):
    payload = _payload(None)
    payload[0].update({
        "importance": {"coverage": nested},
        "coverage": flat,
    })
    with pytest.raises(TypeError, match="importance.coverage must be integer or null"):
        normalize_multidim_event_payload(payload)


def test_unknown_extra_field_still_rejected_when_flat_scores_present():
    payload = _payload(None)
    payload[0].update({"coverage": 85, "unsupported_score": 23})
    with pytest.raises(ValueError, match="unsupported_score"):
        normalize_multidim_event_payload(payload)
