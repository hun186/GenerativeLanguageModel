"""Shared required-output rule semantics and LLM provider finish reason."""
import csv
from pathlib import Path
from types import SimpleNamespace

import pytest

from czjLLM.common.required_output_guard import evaluate_required_output_checks
from czjLLM.es_mode.adapters.pending_policy import ElasticsearchPendingPolicyMixin
from czjLLM.es_mode.adapters.pending_policy_no_eventids import (
    ElasticsearchPendingPolicyMixin as NoEventIdsPolicy,
)
from czjLLM.utilities.llm_call_audit import (
    log_llm_call, normalized_finish_reason, create_llm_call_audit_run,
)


def _rule(path, *, minimum=1, validator="date"):
    return {"full_path": "multidim_event_json." + path,
            "validator": validator, "format": "iso8601",
            "min_valid_count": minimum}


@pytest.mark.parametrize("policy_type", [ElasticsearchPendingPolicyMixin, NoEventIdsPolicy])
def test_shared_evaluator_matches_rerun_policy_and_does_not_require_absent_event_timeline(
    policy_type, monkeypatch,
):
    source = {"multidim_event_json": {
        "Event": [{"time_iso": "2024-07-25"}],
        "Event_Timeline": [],
    }}
    rules = [_rule("Event.time_iso"), _rule("Event_Timeline.time_iso", minimum=0)]
    passed, fail = evaluate_required_output_checks(source, rules)
    assert passed and fail is None

    # The ES pending policy now shares the very same pure validator.
    policy = policy_type()
    policy.cfg = {
        "output_col": "multidim_event_json",
        "rerun": {"enable": True, "required_output_checks": [
            {"path": "Event.time_iso", "validator": "date",
             "format": "iso8601", "min_valid_count": 1},
            {"path": "Event_Timeline.time_iso", "validator": "date",
             "format": "iso8601", "min_valid_count": 0},
        ]},
    }
    assert policy._validate_required_output_checks(source, "multidim_event_json")
    policy.cfg["rerun"]["required_output_checks"][-1]["min_valid_count"] = 1
    assert not policy._validate_required_output_checks(source, "multidim_event_json")


@pytest.mark.parametrize("bad", ["2024-13-25", None, "", "bogus"])
def test_missing_or_bad_date_gives_sanitized_failure(bad):
    record = {"multidim_event_json": {"Event": [{"time_iso": bad}]}}
    ok, failure = evaluate_required_output_checks(
        record, [_rule("Event.time_iso")],
    )
    assert not ok
    assert failure["found_valid"] == 0
    assert set(failure) == {
        "path", "validator", "format", "found_valid", "min_valid_count",
    }
    assert bad not in tuple(failure.values()) or not isinstance(bad, str)


def test_event_date_and_timeline_date_are_separate_decisions():
    record = {"multidim_event_json": {
        "Event": [{"time_iso": "2024-07-25"}], "Event_Timeline": [],
    }}
    assert evaluate_required_output_checks(
        record, [_rule("Event.time_iso")],
    )[0] is True
    assert evaluate_required_output_checks(
        record, [_rule("Event_Timeline.time_iso")],
    )[0] is False


def _response(reason):
    return SimpleNamespace(
        choices=[SimpleNamespace(finish_reason=reason)],
        usage=SimpleNamespace(prompt_tokens=100, completion_tokens=96, total_tokens=196),
    )


@pytest.mark.parametrize(("value", "expected"), [
    ("stop", "stop"), ("length", "length"),
    ("content_filter", "content_filter"),
    (" unknown unexpected reason SECRET ", "other"),
    (None, ""), ("", "other"),
])
def test_finish_reason_is_fixed_allowlist(value, expected):
    assert normalized_finish_reason(_response(value)) == expected


def test_finish_reason_and_existing_max_tokens_preserved_in_new_audit(tmp_path):
    metadata = create_llm_call_audit_run(str(tmp_path))
    log_llm_call(
        audit_path=metadata["llm_call_audit_path"], run_id="r",
        task="to json", prompt_file="sensitive.txt",
        model_spec={"model_name": "test-model", "num_ctx": 4096},
        response=_response("length"), max_tokens=96,
    )
    with Path(metadata["llm_call_audit_path"]).open(
        newline="", encoding="utf-8",
    ) as handle:
        rows = list(csv.DictReader(handle))
    assert rows[0]["finish_reason"] == "length"
    assert rows[0]["max_output_tokens"] == "96"
    assert rows[0]["output_tokens"] == "96"
