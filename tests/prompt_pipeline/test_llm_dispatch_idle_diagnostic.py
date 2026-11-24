"""Read-only LLM dispatch snapshot: synthetic data and secret sentinels only."""
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import time

import pytest

from scripts.diagnose_llm_dispatch_idle import snapshot, main


def fixture(logs, now, *, pending=8, running=1):
    logs.mkdir()
    (logs / "loadmeter_20261109_1.json").write_text(json.dumps({
        "queue": {"pending": pending, "running": running, "completed": 3},
        "workers": {"n_process": 8},
        "consumer": {"last_round_ts": now - 500},
        "session_run_id": "PRIVATE_RUN_MARKER", "rows": {"PRIVATE_PK": {}},
    }), encoding="utf-8")
    (logs / "base_url_load.json").write_text(json.dumps({
        "http://PRIVATE_ENDPOINT_A:11434/v1": {
            "leases": [now + 400, now - 15], "last_update": now - 8,
        },
        "http://PRIVATE_ENDPOINT_B:11434/v1": {
            "leases": [], "last_update": now - 50,
        },
    }), encoding="utf-8")
    audit = logs / "llm_call_audit"
    audit.mkdir()
    with (audit / "llm_call_audit_20261109.csv").open("w", newline="", encoding="utf-8") as fp:
        w = csv.DictWriter(fp, fieldnames=[
            "timestamp", "base_url", "ok", "call_llm_api_returned", "error", "prompt_file",
        ])
        w.writeheader()
        w.writerow({
            "timestamp": datetime.fromtimestamp(now - 42, timezone.utc).isoformat(),
            "base_url": "http://PRIVATE_ENDPOINT_A:11434/v1", "ok": "NO",
            "call_llm_api_returned": "NO", "error": "PRIVATE_ERROR_MARKER",
            "prompt_file": "PRIVATE_PROMPT_MARKER",
        })
    return logs


def test_synthetic_straggler_lease_privacy(tmp_path):
    now = 1800000000.0
    report = snapshot(fixture(tmp_path / "logs", now), now=now)
    assert report["diagnosis_status"] == "OBSERVED_NOT_PROVEN"
    assert report["gpu_utilization_status"] == "NOT_OBSERVED"
    assert report["root_cause_status"] == "NOT_DETERMINED"
    assert "POSSIBLE_BATCH_TAIL_OR_DISPATCH_GAP" in report["signals"]
    assert "EXPIRED_LEASE_RECORDS_UNCLEANED" in report["signals"]
    assert report["sources"]["audit"]["recent_failed_rows"] == 1
    assert report["sources"]["audit"]["by_endpoint"]["endpoint_01"]["audit_rows"] == 1
    for secret in ("PRIVATE_ENDPOINT", "PRIVATE_RUN", "PRIVATE_PK", "PRIVATE_PROMPT", "PRIVATE_ERROR"):
        assert secret not in json.dumps(report)


def test_pending_no_running_is_not_proof(tmp_path):
    now = 1800000000.0
    report = snapshot(fixture(tmp_path / "logs", now, pending=15, running=0), now=now)
    assert "PENDING_WITHOUT_RUNNING" in report["signals"]
    assert report["root_cause_status"] == "NOT_DETERMINED"


def test_missing_input_is_unknown_not_zero(tmp_path):
    logs = tmp_path / "logs"
    logs.mkdir()
    result = snapshot(logs, now=1800000000)
    assert result["diagnosis_status"] == "UNVERIFIED"
    assert all(result["sources"][k]["status"] == "MISSING" for k in ("meter", "load", "audit"))


def test_symlink_rejected(tmp_path):
    now = 1800000000.0
    logs = fixture(tmp_path / "logs", now)
    (logs / "base_url_load.json").unlink()
    (logs / "private").write_text("PRIVATE_SECRET", encoding="utf-8")
    try:
        (logs / "base_url_load.json").symlink_to(logs / "private")
    except (OSError, NotImplementedError):
        return
    report = snapshot(logs, now=now)
    assert report["sources"]["load"]["status"] == "UNSAFE_PATH"
    assert "PRIVATE_SECRET" not in json.dumps(report)


def test_audit_too_large_fails_closed(tmp_path):
    now = 1800000000.0
    logs = fixture(tmp_path / "logs", now)
    file = logs / "llm_call_audit" / "llm_call_audit_20261109.csv"
    with file.open("ab") as fp:
        fp.truncate(16 * 1024 * 1024 + 1)
    doc = snapshot(logs, now=now)
    assert doc["diagnosis_status"] == "UNVERIFIED"
    assert doc["sources"]["audit"]["status"] == "SIZE_LIMIT"


def test_naive_timestamp_is_not_assumed_utc(tmp_path):
    now = 1800000000.0
    logs = fixture(tmp_path / "logs", now)
    file = logs / "llm_call_audit" / "llm_call_audit_20261109.csv"
    file.write_text(file.read_text(encoding="utf-8").replace("+00:00", ""), encoding="utf-8")
    report = snapshot(logs, now=now)
    assert report["sources"]["audit"]["status"] == "INCOMPLETE"
    assert report["sources"]["audit"]["invalid_timestamp_rows"] == 1



@pytest.mark.parametrize("bad_timestamp", ["not-a-timestamp", "2030-11-18T10:01:02"])
def test_invalid_audit_timestamp_withholds_all_partial_counts(
    tmp_path, bad_timestamp,
):
    """One unplaceable row means even previously valid window counts are partial."""
    now = 1800000000.0
    logs = fixture(tmp_path / "logs", now)
    file = logs / "llm_call_audit" / "llm_call_audit_20261109.csv"
    with file.open("a", encoding="utf-8", newline="") as handle:
        handle.write(
            f"{bad_timestamp},http://PRIVATE_ENDPOINT_A:11434/v1,YES,YES,"
            "PRIVATE_ERROR,PRIVATE_PROMPT\n"
        )
    report = snapshot(logs, now=now)
    audit = report["sources"]["audit"]
    assert audit["status"] == "INCOMPLETE"
    assert audit["invalid_timestamp_rows"] == 1
    assert audit["warning"] == "PARTIAL_AUDIT_COUNTS_WITHHELD"
    for key in (
        "recent_completed_audit_rows", "recent_ok_rows", "recent_failed_rows",
        "recent_wrapper_returned_rows", "unknown_endpoint_rows",
        "last_audit_completion_age_seconds", "by_endpoint",
    ):
        assert key not in audit
    assert report["diagnosis_status"] == "UNVERIFIED"
    assert report["root_cause_status"] == "NOT_DETERMINED"
    assert report["sources"]["meter"]["status"] == "OBSERVED"
    assert report["sources"]["load"]["status"] == "OBSERVED"
    assert "PENDING_WITH_NO_RECENT_COMPLETION_AUDIT" not in report["signals"]
    from scripts.diagnose_llm_dispatch_idle import format_human_report
    assert "【最近完成 Audit】" not in format_human_report(report)
    for marker in ("PRIVATE_ENDPOINT", "PRIVATE_PROMPT", str(logs)):
        assert marker not in json.dumps(report)


@pytest.mark.parametrize("column,bad_value", [
    ("ok", "MAYBE"),
    ("call_llm_api_returned", "MAYBE"),
])
def test_invalid_audit_call_status_fails_closed(tmp_path, column, bad_value):
    now = 1800000000.0
    logs = fixture(tmp_path / "logs", now)
    path = logs / "llm_call_audit" / "llm_call_audit_20261109.csv"
    with path.open(newline="", encoding="utf-8") as source:
        rows = list(csv.DictReader(source))
    rows[0][column] = bad_value
    with path.open("w", newline="", encoding="utf-8") as target:
        writer = csv.DictWriter(target, fieldnames=[
            "timestamp", "base_url", "ok", "call_llm_api_returned",
            "error", "prompt_file",
        ])
        writer.writeheader()
        writer.writerows(rows)
    report = snapshot(logs, now=now)
    assert report["sources"]["audit"] == {"status": "SCHEMA_MISMATCH"}
    assert report["diagnosis_status"] == "UNVERIFIED"
    assert report["sources"]["meter"]["status"] == "OBSERVED"
    assert report["sources"]["load"]["status"] == "OBSERVED"
    assert "PRIVATE_" not in json.dumps(report)


def test_duplicate_audit_csv_header_fails_closed(tmp_path):
    now = 1800000000.0
    logs = fixture(tmp_path / "logs", now)
    path = logs / "llm_call_audit" / "llm_call_audit_20261109.csv"
    lines = path.read_text(encoding="utf-8").splitlines()
    lines[0] += ",ok"
    lines[1] += ",YES"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    report = snapshot(logs, now=now)
    assert report["sources"]["audit"] == {"status": "SCHEMA_MISMATCH"}
    assert report["sources"]["meter"]["status"] == "OBSERVED"
    assert report["sources"]["load"]["status"] == "OBSERVED"
    assert report["root_cause_status"] == "NOT_DETERMINED"


def test_legacy_blank_worker_return_observation_remains_accepted(tmp_path):
    now = 1800000000.0
    logs = fixture(tmp_path / "logs", now)
    path = logs / "llm_call_audit" / "llm_call_audit_20261109.csv"
    with path.open(newline="", encoding="utf-8") as source:
        rows = list(csv.DictReader(source))
    rows[0]["call_llm_api_returned"] = ""
    with path.open("w", newline="", encoding="utf-8") as target:
        writer = csv.DictWriter(target, fieldnames=[
            "timestamp", "base_url", "ok", "call_llm_api_returned",
            "error", "prompt_file",
        ])
        writer.writeheader()
        writer.writerows(rows)
    report = snapshot(logs, now=now)
    assert report["sources"]["audit"]["status"] == "OBSERVED"
    assert report["sources"]["audit"]["recent_failed_rows"] == 1
    assert report["sources"]["audit"]["recent_wrapper_returned_rows"] == 0
    assert report["diagnosis_status"] == "OBSERVED_NOT_PROVEN"


def test_foreground_repeated_samples_redacted(tmp_path, capsys):
    logs = fixture(tmp_path / "logs", time.time())
    assert main(["--logs-dir", str(logs), "--samples", "2", "--interval-seconds", "0"]) == 0
    lines = capsys.readouterr().out.strip().splitlines()
    assert [json.loads(x)["sample_number"] for x in lines] == [1, 2]
    assert "PRIVATE_ENDPOINT" not in "\n".join(lines)
    assert "PRIVATE_PK" not in "\n".join(lines)


@pytest.mark.parametrize("case", ["truncated", "missing_columns", "unterminated_quote"])
def test_csv_interrupted_append_fails_closed_instead_of_counting_completion(tmp_path, case):
    now = 1800000000.0
    logs = fixture(tmp_path / "logs", now)
    file = logs / "llm_call_audit" / "llm_call_audit_20261109.csv"
    timestamp = datetime.fromtimestamp(now - 2, timezone.utc).isoformat()
    with file.open("a", encoding="utf-8") as output:
        if case == "truncated":
            output.write(f"{timestamp},http://PRIVATE_ENDPOINT_A:11434/v1,YES,YES")
        elif case == "missing_columns":
            output.write(f"{timestamp},http://PRIVATE_ENDPOINT_A:11434/v1,YES\n")
        else:
            output.write(f'{timestamp},http://PRIVATE_ENDPOINT_A:11434/v1,YES,YES,"torn\n')
    report = snapshot(logs, now=now)
    assert report["diagnosis_status"] == "UNVERIFIED"
    assert report["sources"]["audit"]["status"] == "INCOMPLETE"
    assert "recent_completed_audit_rows" not in report["sources"]["audit"]
    assert "PRIVATE_ENDPOINT_A" not in json.dumps(report)



def test_human_no_args_style_summary_is_chinese_and_redacted(tmp_path, capsys):
    logs = fixture(tmp_path / "logs", time.time())
    assert main(["--logs-dir", str(logs), "--human"]) == 0
    text = capsys.readouterr().out
    assert "【Queue 工作狀態】" in text
    assert "【資料讀取】" in text
    assert "【端點負載估計】" in text
    assert "仍有待處理項目" not in text
    assert "GPU 正常／異常" in text
    for marker in ("PRIVATE_ENDPOINT", "PRIVATE_PK", "PRIVATE_RUN", "PRIVATE_PROMPT",
                   "PRIVATE_ERROR", str(logs)):
        assert marker not in text


def test_human_missing_logs_does_not_claim_success(tmp_path, capsys):
    missing = tmp_path / "no_such_logs"
    assert main(["--logs-dir", str(missing), "--human"]) == 2
    output = capsys.readouterr().out
    assert "找不到資料" in output
    assert "資料不足或不完整" in output
    assert str(missing) not in output


def test_python_help_exposes_human_and_window_flags(capsys):
    with pytest.raises(SystemExit) as stopped:
        main(["--help"])
    assert stopped.value.code == 0
    output = capsys.readouterr().out
    assert "--human" in output
    assert "--samples" in output
    assert "--logs-dir" in output


def test_windows_bat_no_argument_entry_stays_open_and_help_forwards():
    # Portable structural check; Hosted Windows runs the actual --help path.
    launcher = (Path(__file__).resolve().parents[2] / "run_llm_dispatch_diagnostic.bat")
    content = launcher.read_text(encoding="utf-8")
    assert 'if not "%~1"=="" goto :ARGS' in content
    assert '"scripts\\diagnose_llm_dispatch_idle.py" --human' in content
    assert "pause >nul" in content
    assert '"scripts\\diagnose_llm_dispatch_idle.py" %*' in content


def _split_source_roots(tmp_path, now):
    """Move disposable logs to the three real-world separate source roots."""
    shared = fixture(tmp_path / "original", now)
    meter = tmp_path / "PRIVATE_meter_dir"
    load = tmp_path / "PRIVATE_load_dir"
    audit = tmp_path / "PRIVATE_audit_parent"
    for folder in (meter, load, audit):
        folder.mkdir()
    (shared / "loadmeter_20261109_1.json").rename(meter / "loadmeter_20261109_1.json")
    (shared / "base_url_load.json").rename(load / "base_url_load.json")
    (shared / "llm_call_audit").rename(audit / "llm_call_audit")
    return meter, load, audit


def test_separate_source_roots_recover_missing_evidence_without_claiming_same_run(tmp_path):
    now = 1800000000.0
    meter, load, audit = _split_source_roots(tmp_path, now)
    default = snapshot(tmp_path / "MISSING_SHARED", now=now)
    assert all(default["sources"][k]["status"] == "MISSING"
               for k in ("meter", "load", "audit"))
    report = snapshot(tmp_path / "MISSING_SHARED", now=now,
                      meter_logs=meter, load_logs=load, audit_logs=audit)
    assert report["diagnosis_status"] == "OBSERVED_NOT_PROVEN"
    assert all(report["sources"][k]["status"] == "OBSERVED"
               for k in ("meter", "load", "audit"))
    assert report["sources"]["meter"]["pending"] == 8
    assert report["sources"]["load"]["active_leases_total"] == 1
    assert report["sources"]["audit"]["recent_failed_rows"] == 1
    assert report["cross_source_run_identity"] == "NOT_VERIFIED"
    assert report["source_directory_selection"] == {
        "meter": "EXPLICIT", "load": "EXPLICIT", "audit": "EXPLICIT",
    }
    output = json.dumps(report)
    for hidden in ("PRIVATE_", "PRIVATE_ENDPOINT", "PRIVATE_PK",
                   str(meter), str(load), str(audit), "11434"):
        assert hidden not in output


def test_one_invalid_override_does_not_mask_other_valid_sources(tmp_path):
    now = 1800000000.0
    shared = fixture(tmp_path / "logs", now)
    result = snapshot(shared, now=now, meter_logs=tmp_path / "NONEXISTENT_METER")
    assert result["diagnosis_status"] == "UNVERIFIED"
    assert result["sources"]["meter"]["status"] == "MISSING"
    assert result["sources"]["load"]["status"] == "OBSERVED"
    assert result["sources"]["audit"]["status"] == "OBSERVED"
    assert result["sources"]["audit"]["recent_failed_rows"] == 1
    assert result["cross_source_run_identity"] == "NOT_VERIFIED"
    assert result["root_cause_status"] == "NOT_DETERMINED"


def test_symlinked_overridden_root_fails_closed_without_blocking_others(tmp_path):
    now = 1800000000.0
    meter, load, audit = _split_source_roots(tmp_path, now)
    alias = tmp_path / "PRIVATE_symlink_alias"
    try:
        alias.symlink_to(meter, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlink not available")
    result = snapshot(tmp_path / "missing", now=now,
                      meter_logs=alias, load_logs=load, audit_logs=audit)
    assert result["sources"]["meter"]["status"] == "UNSAFE_PATH"
    assert result["sources"]["load"]["status"] == "OBSERVED"
    assert result["sources"]["audit"]["status"] == "OBSERVED"
    assert result["diagnosis_status"] == "UNVERIFIED"
    assert "PRIVATE_" not in json.dumps(result)


def test_cli_split_roots_and_human_status_are_private(tmp_path, capsys):
    now = time.time()
    meter, load, audit = _split_source_roots(tmp_path, now)
    args = [
        "--logs-dir", str(tmp_path / "missing"),
        "--meter-logs-dir", str(meter),
        "--load-logs-dir", str(load),
        "--audit-logs-dir", str(audit),
    ]
    assert main(args) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["source_directory_selection"]["meter"] == "EXPLICIT"
    assert report["cross_source_run_identity"] == "NOT_VERIFIED"
    assert main(args + ["--human"]) == 0
    friendly = capsys.readouterr().out
    assert "跨來源 Run 身分：未驗證" in friendly
    assert "獨立指定" in friendly
    assert "Queue 工作狀態" in friendly
    assert "LLM 完成稽核" in friendly
    for private in ("PRIVATE_", str(meter), str(load), str(audit), "11434"):
        assert private not in friendly


def test_default_shared_mode_remains_backward_compatible(tmp_path):
    now = 1800000000.0
    logs = fixture(tmp_path / "logs", now)
    doc = snapshot(logs, now=now)
    assert doc["source_directory_selection"] == {
        "meter": "SHARED", "load": "SHARED", "audit": "SHARED",
    }
    assert doc["sources"]["meter"]["status"] == "OBSERVED"
    assert doc["sources"]["load"]["status"] == "OBSERVED"
    assert doc["sources"]["audit"]["status"] == "OBSERVED"
    assert doc["cross_source_run_identity"] == "NOT_VERIFIED"


def _quality_file(logs, now, *, events=None):
    """Synthetic current Audit generation; never source actual run content."""
    file = logs / "llm_call_audit" / "processing_quality_events_20261109.jsonl"
    if events is None:
        events = [
            ("consumer_orchestration_failure", "CONSUMER_ROUND_TIMEOUT", now - 30),
            ("consumer_orchestration_failure", "CONSUMER_ROUND_EXCEPTION", now - 31),
            ("row_merger_retryable_failure", "ROW_MERGER_WRITEBACK_RETRY", now - 32),
            ("consumer_orchestration_failure", "CONSUMER_TERMINATED", now - 1000),
        ]
    records = []
    for i, (event, code, ts) in enumerate(events):
        records.append({
            "schema_version": 1,
            "event_id": "PRIVATE_EVENT_ID_" + str(i),
            "ts": datetime.fromtimestamp(ts, timezone.utc).isoformat(),
            "run_id": "PRIVATE_RUN_ID",
            "event": event, "scope": "run", "code": code,
            "outcome": "failure", "document_id": "", "slice_id": "",
            "private_added_future_field": "PRIVATE_RAW_UNTRUSTED",
        })
    # Quality event stream also contains slice and document records, which
    # must NOT be counted as run-level GPU dispatch incidents.
    records.append({
        "schema_version": 1,
        "event_id": "PRIVATE_SLICE_ID",
        "ts": datetime.fromtimestamp(now - 25, timezone.utc).isoformat(),
        "run_id": "PRIVATE_RUN_ID",
        "event": "slice_json_repair", "scope": "slice",
        "code": "JSON_REPAIR_SUCCEEDED", "document_id": "PRIVATE_PK",
    })
    file.write_text("".join(json.dumps(row) + "\n" for row in records),
                    encoding="utf-8")
    return file


def test_run_quality_active_generation_fixed_incident_counts_and_privacy(tmp_path):
    now = 1800000000.0
    logs = fixture(tmp_path / "logs", now)
    _quality_file(logs, now)
    report = snapshot(logs, now=now, window=900)
    quality = report["sources"]["quality"]
    assert quality["status"] == "OBSERVED"
    assert quality["recent_run_incident_events"] == 3
    assert quality["by_category"]["consumer_orchestration_failure"] == 2
    assert quality["by_category"]["row_merger_retryable_failure"] == 1
    assert quality["by_code"]["CONSUMER_ROUND_TIMEOUT"] == 1
    assert quality["by_code"]["CONSUMER_TERMINATED"] == 0
    assert quality["archive_coverage"] == "ACTIVE_GENERATION_ONLY"
    assert quality["run_identity"] == "NOT_VERIFIED"
    assert report["root_cause_status"] == "NOT_DETERMINED"
    assert report["diagnosis_status"] == "OBSERVED_NOT_PROVEN"
    for marker in ("PRIVATE_EVENT_ID", "PRIVATE_RUN_ID", "PRIVATE_RAW",
                   "PRIVATE_PK", "PRIVATE_SLICE_ID"):
        assert marker not in json.dumps(report)


def test_missing_quality_does_not_invalidate_existing_three_source_observation(tmp_path):
    now = 1800000000.0
    logs = fixture(tmp_path / "logs", now)
    result = snapshot(logs, now=now)
    assert result["sources"]["quality"]["status"] == "MISSING"
    assert result["diagnosis_status"] == "OBSERVED_NOT_PROVEN"
    assert all(result["sources"][key]["status"] == "OBSERVED"
               for key in ("meter", "load", "audit"))


@pytest.mark.parametrize("mutation,code", [
    (lambda rows: rows[:-1], "INCOMPLETE"),
    (lambda rows: rows.replace(b"CONSUMER_ROUND_TIMEOUT",
                               b"UNTRUSTED_INVALID_CODE"), "SCHEMA_MISMATCH"),
    (lambda rows: rows.replace(b'"scope": "run"', b'"scope": "slice"', 1),
     "SCHEMA_MISMATCH"),
    (lambda rows: rows.replace(b'"event": "consumer_orchestration_failure"',
                               b'"event": ["PRIVATE_LIST"]', 1), "SCHEMA_MISMATCH"),
    (lambda rows: rows.replace(b"+00:00", b"", 1), "INCOMPLETE"),
])
def test_quality_incomplete_or_untrusted_incident_refuses_partial_counts(
    tmp_path, mutation, code
):
    now = 1800000000.0
    logs = fixture(tmp_path / "logs", now)
    path = _quality_file(logs, now)
    path.write_bytes(mutation(path.read_bytes()))
    report = snapshot(logs, now=now)
    assert report["sources"]["quality"]["status"] == code
    assert "recent_run_incident_events" not in report["sources"]["quality"]
    assert report["diagnosis_status"] == "OBSERVED_NOT_PROVEN"
    assert "PRIVATE_" not in json.dumps(report)


def test_quality_symlink_does_not_follow_private_target(tmp_path):
    now = 1800000000.0
    logs = fixture(tmp_path / "logs", now)
    file = _quality_file(logs, now)
    target = tmp_path / "PRIVATE_ORIGINAL"
    file.rename(target)
    try:
        file.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("symlink unsupported")
    report = snapshot(logs, now=now)
    assert report["sources"]["quality"]["status"] == "UNSAFE_PATH"
    assert report["diagnosis_status"] == "OBSERVED_NOT_PROVEN"
    assert "PRIVATE_" not in json.dumps(report)


def test_quality_human_summary_and_separate_audit_root(tmp_path, capsys):
    now = time.time()
    meter, load, audit = _split_source_roots(tmp_path, now)
    _quality_file(audit, now)
    args = ["--logs-dir", str(tmp_path / "missing"),
            "--meter-logs-dir", str(meter),
            "--load-logs-dir", str(load),
            "--audit-logs-dir", str(audit), "--human"]
    assert main(args) == 0
    output = capsys.readouterr().out
    assert "Quality Run 異常" in output
    assert "Consumer 異常：2" in output
    assert "Row Merger 重試異常：1" in output
    assert "跨來源 Run 身分：未驗證" in output
    for marker in ("PRIVATE_", str(meter), str(load), str(audit)):
        assert marker not in output


def test_quality_run_failures_exactly_match_current_writer_allowlist():
    # The standalone CLI uses stdlib only; this regression fails whenever
    # production code adds/renames an incident type, instead of silently
    # dropping an important future quality event.
    from czjLLM.utilities.processing_quality import RUN_INCIDENT_CODES
    from scripts.diagnose_llm_dispatch_idle import _RUN_FAILURE_CODES

    expected = {key: set(value) for key, value in RUN_INCIDENT_CODES.items()
                if key not in ("queue_recovery",)}
    assert {key: set(value) for key, value in _RUN_FAILURE_CODES.items()} == expected


def test_duplicate_quality_event_id_is_not_double_counted(tmp_path):
    now = 1800000000.0
    logs = fixture(tmp_path / "logs", now)
    file = _quality_file(logs, now)
    first = file.read_text(encoding="utf-8").splitlines()[0]
    with file.open("a", encoding="utf-8") as output:
        output.write(first + "\n")
    result = snapshot(logs, now=now)
    assert result["sources"]["quality"]["status"] == "OBSERVED"
    assert result["sources"]["quality"]["recent_run_incident_events"] == 3
    assert result["sources"]["quality"]["by_code"]["CONSUMER_ROUND_TIMEOUT"] == 1


def test_conflicting_duplicate_quality_event_id_fails_closed(tmp_path):
    now = 1800000000.0
    logs = fixture(tmp_path / "logs", now)
    file = _quality_file(logs, now)
    first = json.loads(file.read_text(encoding="utf-8").splitlines()[0])
    first["code"] = "CONSUMER_TERMINATED"
    with file.open("a", encoding="utf-8") as output:
        output.write(json.dumps(first) + "\n")
    result = snapshot(logs, now=now)
    assert result["sources"]["quality"]["status"] == "SCHEMA_MISMATCH"
    assert "by_code" not in result["sources"]["quality"]
    assert result["diagnosis_status"] == "OBSERVED_NOT_PROVEN"


@pytest.mark.parametrize("change", [
    lambda row: row.update(event_id=[]),
    lambda row: row.pop("event_id"),
    lambda row: row.update(event="consumer_orchestration_typo"),
    lambda row: row.update(code="MALFORMED_UNKNOWN_CODE"),
    lambda row: row.update(scope="run"),
    lambda row: row.update(ts=0),
])
def test_invalid_nonincident_quality_event_fails_all_quality_counts(tmp_path, change):
    now = 1800000000.0
    logs = fixture(tmp_path / "logs", now)
    file = _quality_file(logs, now)
    rows = [json.loads(line) for line in file.read_text(encoding="utf-8").splitlines()]
    last = rows[-1]
    assert last["event"] == "slice_json_repair"
    change(last)
    file.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    result = snapshot(logs, now=now)
    assert result["sources"]["quality"]["status"] in ("SCHEMA_MISMATCH", "INCOMPLETE")
    assert "recent_run_incident_events" not in result["sources"]["quality"]
    assert result["sources"]["meter"]["status"] == "OBSERVED"
    assert result["root_cause_status"] == "NOT_DETERMINED"
