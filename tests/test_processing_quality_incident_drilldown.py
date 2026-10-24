"""Read-only incident family drilldown over actual quality JSONL, without PII or live dependencies."""
from __future__ import annotations

import json

import pytest

from czjLLM.cli_tools.processing_quality_report import (
    main, report_for_audit, report_history, run_incident_diagnostics,
)
from czjLLM.utilities.processing_quality import emit_quality_event, quality_event_path


def _write(audit, *, event, code, scope="run", document_id=""):
    emit_quality_event(
        str(audit), run_id="safe-run", event=event, code=code, scope=scope,
        outcome="observed", document_id=document_id,
    )


def test_integration_real_jsonl_incidents_are_grouped_without_document_denominator(tmp_path):
    audit = tmp_path / "llm_call_audit_incidents.csv"
    private = "private-source-SHOULD-NOT-APPEAR"
    _write(audit, event="worker_phase_failure", code="WORKER_LLM_TIMEOUT_EXCEPTION")
    _write(audit, event="worker_phase_failure", code="WORKER_LLM_HTTP_SERVER_EXCEPTION")
    _write(audit, event="worker_phase_failure", code="WORKER_LLM_TIMEOUT_EXCEPTION")
    _write(audit, event="stage_orchestration_failure", code="STAGE_RUNNER_EXCEPTION")
    _write(audit, event="producer_operational_failure", code="PRODUCER_FUTURE_EXCEPTION")
    _write(audit, event="slice_json_validation", code="JSON_SYNTAX_INVALID", scope="slice")
    _write(audit, event="document_schema_rejected", code="SCHEMA_OTHER",
           scope="document", document_id=private)
    path = quality_event_path(str(audit))
    before = path.read_bytes()

    result = report_for_audit(audit)["run"]
    diagnostic = result["incident_diagnostics"]
    assert result["state"] == "observed"
    assert diagnostic["observed_run_incident_events"] == 5
    assert diagnostic["families"]["worker_phase_failure"] == {
        "observed_events": 3,
        "codes": {
            "WORKER_LLM_HTTP_SERVER_EXCEPTION": 1,
            "WORKER_LLM_TIMEOUT_EXCEPTION": 2,
        },
        "share_of_observed_incidents_pct": 60.0,
    }
    assert diagnostic["families"]["stage_orchestration_failure"]["share_of_observed_incidents_pct"] == 20.0
    assert diagnostic["families"]["producer_operational_failure"]["observed_events"] == 1
    assert diagnostic["families"]["row_merger_retryable_failure"]["observed_events"] == 0
    assert diagnostic["sample_advisory"].startswith("small observed incident")
    assert result["metrics"]["events"] == 7
    assert result["metrics"]["slice_validation_attempts"] == 1
    assert result["metrics"]["documents_schema_pending"] == 1
    assert "JSON_SYNTAX_INVALID" not in json.dumps(diagnostic)
    assert "SCHEMA_OTHER" not in json.dumps(diagnostic)
    assert private not in json.dumps(diagnostic)
    assert path.read_bytes() == before


def test_focus_is_allowlisted_projection_not_a_mutation_of_metrics(tmp_path):
    audit = tmp_path / "llm_call_audit_focus.csv"
    _write(audit, event="worker_phase_failure", code="WORKER_LLM_RATE_LIMIT_EXCEPTION")
    _write(audit, event="stage_orchestration_failure", code="STAGE_PREPARE_EXCEPTION")
    complete = report_for_audit(audit)
    focus = report_for_audit(audit, incident_family="worker_phase_failure")
    a = complete["run"]["incident_diagnostics"]
    b = focus["run"]["incident_diagnostics"]
    assert b["focus_family"] == "worker_phase_failure"
    assert list(b["families"]) == ["worker_phase_failure"]
    assert b["observed_run_incident_events"] == 2  # Includes unselected Stage events.
    assert b["families"]["worker_phase_failure"]["share_of_observed_incidents_pct"] == 50.0
    assert focus["run"]["metrics"] == complete["run"]["metrics"]
    assert a["families"]["stage_orchestration_failure"]["observed_events"] == 1


def test_zero_incidents_are_unknown_share_even_if_there_are_document_events(tmp_path):
    audit = tmp_path / "llm_call_audit_only_document.csv"
    _write(audit, event="document_writeback_confirmed", code="WRITEBACK_CONFIRMED",
           scope="document", document_id="sensitive")
    diagnostic = report_for_audit(audit)["run"]["incident_diagnostics"]
    assert diagnostic["observed_run_incident_events"] == 0
    assert all(item["share_of_observed_incidents_pct"] is None
               for item in diagnostic["families"].values())
    assert "unknown" in diagnostic["sample_advisory"]


def test_corrupt_and_identity_spoofing_do_not_inflate_incident_denominator(tmp_path):
    audit = tmp_path / "llm_call_audit_corrupt_incident.csv"
    _write(audit, event="worker_phase_failure", code="WORKER_LLM_CONNECTION_EXCEPTION")
    stream = quality_event_path(str(audit))
    with stream.open("ab") as writer:
        writer.write(b'{"schema_version":1,"event_id":"bad","event":"worker_phase_failure","scope":"run","code":"WORKER_LLM_TIMEOUT_EXCEPTION","document_id":"sensitive"}\n')
        writer.write(b'not-json\n')
        writer.write(b'{"schema_version":1,"event_id":"incomplete"')
    result = report_for_audit(audit)["run"]
    assert result["state"] == "degraded_corrupt_lines"
    assert result["skipped_corrupt_complete_lines"] == 2
    assert result["incomplete_or_concurrent_append"] is True
    assert result["incident_diagnostics"]["observed_run_incident_events"] == 1
    assert result["incident_diagnostics"]["families"]["worker_phase_failure"]["observed_events"] == 1


def test_history_filter_is_per_run_no_cross_run_rates(tmp_path):
    first = tmp_path / "llm_call_audit_20261024-01.csv"
    last = tmp_path / "llm_call_audit_20261024-02.csv"
    _write(first, event="worker_phase_failure", code="WORKER_LLM_CONNECTION_EXCEPTION")
    _write(last, event="stage_orchestration_failure", code="STAGE_RUNNER_EXCEPTION")
    report = report_history(tmp_path, limit=2, incident_family="worker_phase_failure")
    assert report["selected_run_files"] == 2
    assert [r["incident_diagnostics"]["observed_run_incident_events"] for r in report["runs"]] == [1, 1]
    assert [r["incident_diagnostics"]["families"]["worker_phase_failure"]["observed_events"]
            for r in report["runs"]] == [0, 1]
    assert report["runs"][0]["incident_diagnostics"]["families"]["worker_phase_failure"]["share_of_observed_incidents_pct"] == 0.0


def test_cli_focus_json_output_is_atomic_and_unknown_family_is_rejected(tmp_path, capsys):
    audit = tmp_path / "llm_call_audit_cli.csv"
    _write(audit, event="worker_phase_failure", code="WORKER_LLM_TIMEOUT_EXCEPTION")
    stream = quality_event_path(str(audit))
    before = stream.read_bytes()
    output = tmp_path / "focus.json"
    assert main(["--audit-path", str(audit), "--incident-family",
                 "worker_phase_failure", "--output", str(output)]) == 0
    saved = json.loads(output.read_text(encoding="utf-8"))
    assert json.loads(capsys.readouterr().out) == saved
    assert saved["run"]["incident_diagnostics"]["families"]["worker_phase_failure"]["observed_events"] == 1
    assert stream.read_bytes() == before
    with pytest.raises(SystemExit) as exc:
        main(["--audit-path", str(audit), "--incident-family",
              "document_schema_rejected"])
    assert exc.value.code == 2
    with pytest.raises(ValueError, match="unknown run-scoped"):
        run_incident_diagnostics({"error_codes": {}}, family="arbitrary")
    with pytest.raises(ValueError, match="unknown run-scoped"):
        report_history(tmp_path, incident_family="document_schema_rejected")
