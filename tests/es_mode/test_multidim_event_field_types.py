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
