"""ES required-output debug log aggregation never changes pending decisions."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from czjLLM.es_mode.adapters import elasticsearch_adapter as adapter_module
from czjLLM.es_mode.adapters.elasticsearch_adapter import ElasticsearchAdapter
from czjLLM.es_mode.adapters.pending_policy_no_eventids import (
    ElasticsearchPendingPolicyMixin as WithoutEventIdsPolicy,
)
from czjLLM.es_mode.adapters.required_output_debug import (
    RequiredOutputFailureSummary,
    flush_required_output_failures,
)


def _config():
    return {
        "output_col": "multidim_event_json",
        "rerun": {
            "enable": True,
            "required_output_checks": [{
                "path": "Event_Timeline.time_iso",
                "validator": "date",
                "format": "iso8601",
                "min_valid_count": 1,
            }],
        },
    }


def _source(valid=False):
    return {
        "body": "document",
        "multidim_event_json": {
            "Event_Timeline": [
                {"time_iso": "2026-10-30T12:00:00Z" if valid else "not-a-date"},
            ],
        },
    }


def test_35000_identical_failures_yield_exact_count_with_few_console_lines(capsys):
    adapter = ElasticsearchAdapter(_config())
    for _ in range(35_000):
        decision = adapter.check_source_pending(_source(), ["multidim_event_json"])
        assert decision.pending and decision.reason == "required_output_invalid"
    flush_required_output_failures(adapter)
    messages = [
        line for line in capsys.readouterr().out.splitlines()
        if "required_output_check" in line
    ]
    assert 5 <= len(messages) <= 9
    assert "required_output_check failed:" in messages[0]
    assert "path=multidim_event_json.Event_Timeline.time_iso" in messages[0]
    assert "occurrences=10," in "\n".join(messages)
    assert "occurrences=1,000," in "\n".join(messages)
    assert "occurrences=30,000," in "\n".join(messages)
    assert "required_output_check summary: occurrences=35,000," in messages[-1]
    assert "not distinct documents" in messages[-1]
    # No re-emitted stale summary on the next batch's empty flush.
    flush_required_output_failures(adapter)
    assert capsys.readouterr().out == ""
    assert adapter.check_source_pending(_source(valid=True), ["multidim_event_json"]).pending is False


def test_rule_variants_are_independent_and_overflow_is_bounded(capsys):
    reporter = RequiredOutputFailureSummary()
    for i in range(40):
        reporter.record(
            path=f"output.path_{i}", validator="date", fmt="iso8601",
            found_valid=0, min_valid_count=1,
        )
    reporter.record(path="output.path_0", validator="date", fmt="iso8601",
                    found_valid=0, min_valid_count=1)
    reporter.flush()
    output = capsys.readouterr().out
    assert output.count("required_output_check failed:") == 32
    assert output.count("required_output_check summary: occurrences=") == 32
    assert "more than 32 distinct failure signatures" in output
    assert "additional_signatures_occurrences=8" in output
    assert "occurrences=2, path=output.path_0" in output


def test_newline_or_long_config_path_cannot_inject_multiline_debug(capsys):
    reporter = RequiredOutputFailureSummary()
    reporter.record(
        path="field\n[ERROR] fake-incident" + ("X" * 500),
        validator="date", fmt="iso8601", found_valid=0, min_valid_count=1,
    )
    reporter.flush()
    output = capsys.readouterr().out
    assert len(output.splitlines()) == 2
    assert "\n[ERROR]" not in output
    assert len(output) < 850


@pytest.mark.parametrize("policy_class", [
    ElasticsearchAdapter,
    WithoutEventIdsPolicy,
])
def test_log_aggregation_does_not_change_required_output_validity(
    policy_class, capsys,
):
    if policy_class is WithoutEventIdsPolicy:
        class P(WithoutEventIdsPolicy):
            def __init__(self):
                self.cfg = _config()
        policy = P()
    else:
        policy = policy_class(_config())
    invalid = policy.check_source_pending(_source(False), ["multidim_event_json"])
    valid = policy.check_source_pending(_source(True), ["multidim_event_json"])
    assert invalid.pending is True and invalid.reason == "required_output_invalid"
    assert valid.pending is False and valid.reason == "fresh_completed"
    flush_required_output_failures(policy)
    assert "occurrences=1," in capsys.readouterr().out


def test_real_single_index_stream_emits_final_summary_on_completion(
    monkeypatch, capsys,
):
    docs = [
        {"_id": f"key_{i}", "_source": _source(valid=i % 3 == 0)}
        for i in range(90)
    ]
    monkeypatch.setattr(
        adapter_module, "helpers",
        SimpleNamespace(scan=lambda **_kwargs: iter(docs)),
    )
    adapter = ElasticsearchAdapter(_config())
    adapter.es = SimpleNamespace(search=lambda **_kwargs: {"hits": {"hits": []}})
    actual = list(adapter.select_pending_rows(
        src_table="single", tgt_table="single",
        pk="_id", input_col="body", output_cols=["multidim_event_json"],
    ))
    assert len(actual) == 60
    logs = capsys.readouterr().out
    assert "required_output_check summary: occurrences=60," in logs
    assert logs.count("required_output_check failed:") == 1
    assert logs.count("required_output_check repeated:") == 1
    assert logs.count("required_output_check summary:") == 1


def test_early_scan_close_reports_only_observed_events(monkeypatch, capsys):
    docs = [
        {"_id": f"key_{i}", "_source": _source(False)}
        for i in range(200)
    ]
    monkeypatch.setattr(
        adapter_module, "helpers",
        SimpleNamespace(scan=lambda **_kwargs: iter(docs)),
    )
    adapter = ElasticsearchAdapter(_config())
    adapter.es = SimpleNamespace(search=lambda **_kwargs: {"hits": {"hits": []}})
    stream = adapter.select_pending_rows(
        src_table="single", tgt_table="single", pk="_id", input_col="body",
        output_cols=["multidim_event_json"],
    )
    assert next(stream)[0] == "key_0"
    assert next(stream)[0] == "key_1"
    stream.close()
    output = capsys.readouterr().out
    assert "required_output_check summary: occurrences=2," in output
    assert "occurrences=200," not in output


def test_multiple_threads_have_exact_summary_count(capsys):
    reporter = RequiredOutputFailureSummary()

    def worker(_):
        for __ in range(100):
            reporter.record(
                path="output.date", validator="date", fmt="iso8601",
                found_valid=0, min_valid_count=1,
            )

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(worker, range(8)))
    reporter.flush()
    output = capsys.readouterr().out
    assert "required_output_check summary: occurrences=800," in output
    assert output.count("required_output_check failed:") == 1
