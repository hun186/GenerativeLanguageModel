"""Read-only LLM dispatch snapshot: synthetic data and secret sentinels only."""
import csv
from datetime import datetime, timezone
import json
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
