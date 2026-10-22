"""Failure taxonomy consumes audit CSV only: no live model, network or database."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from czjLLM.cli_tools.llm_failure_report import main
from czjLLM.utilities.llm_failure_summary import (
    classify_failed_call, llm_failure_history, summarize_llm_failure_audit,
)


HEADERS = ("timestamp", "run_id", "ok", "error", "prompt_file", "base_url")


def _audit(path: Path, rows: list[tuple[str, str]]):
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=HEADERS)
        writer.writeheader()
        for state, error in rows:
            writer.writerow(dict(ok=state, error=error,
                                 prompt_file="/secret/prompt.txt",
                                 base_url="http://username:password@internal.invalid"))


def test_failure_categories_and_request_denominator_are_separate(tmp_path: Path):
    path = tmp_path / "llm_call_audit_20261022-1.csv"
    payload = "Bearer sk-SECRET-NEVER-EMIT " + "/a/b/private-document"
    _audit(path, [
        ("YES", ""), ("NO", "ReadTimeout " + payload),
        ("NO", "HTTPError 429 " + payload),
        ("NO", "connection refused " + payload),
        ("NO", "jsondecodeerror " + payload),
        ("NO", "opaque local exception " + payload),
        ("???", payload),
    ])
    before = path.read_bytes()
    report = summarize_llm_failure_audit(path)
    assert path.read_bytes() == before
    assert report["total_rows"] == 7
    assert report["observed_call_attempts"] == 6
    assert report["successful_call_attempts"] == 1
    assert report["failed_call_attempts"] == 5
    assert report["failed_call_pct"] == 83.33
    assert report["unclassified_or_invalid_status_rows"] == 1
    assert report["state"] == "degraded_invalid_rows"
    for name in ("rate_limit", "timeout", "transport", "json_postprocessing", "unclassified"):
        assert report["failure_categories"][name] == 1
    printed = json.dumps(report)
    assert payload not in printed
    assert "password" not in printed and "private-document" not in printed
    assert "prompt.txt" not in printed
    assert classify_failed_call("context length exceeded") == "context_budget"
    assert classify_failed_call("unrelated unknown") == "unclassified"


def test_empty_denominator_unknown_and_header_requirements(tmp_path: Path):
    path = tmp_path / "llm_call_audit_empty.csv"
    _audit(path, [])
    out = summarize_llm_failure_audit(path)
    assert out["failed_call_pct"] is None
    assert out["state"] == "no_observed_calls"
    path.write_text("ok\nNO\n", encoding="utf-8")
    with pytest.raises(ValueError, match="headers"):
        summarize_llm_failure_audit(path)


def test_truncation_utf8_and_bounded_input_refuse_incomplete_counts(tmp_path: Path):
    path = tmp_path / "llm_call_audit_broken.csv"
    _audit(path, [("YES", "")])
    path.write_bytes(path.read_bytes()[:-1])
    with pytest.raises(ValueError, match="trailing"):
        summarize_llm_failure_audit(path)
    path.write_bytes(b"ok,error\nNO,\xff\n")
    with pytest.raises(ValueError, match="UTF-8"):
        summarize_llm_failure_audit(path)
    _audit(path, [("YES", "")])
    with pytest.raises(ValueError, match="bound"):
        summarize_llm_failure_audit(path, max_bytes=16)
    with pytest.raises(ValueError, match="bound"):
        summarize_llm_failure_audit(path, max_bytes=True)


def test_history_run_isolation_and_symlink_protection(tmp_path: Path):
    a = tmp_path / "llm_call_audit_20261021-1.csv"
    b = tmp_path / "llm_call_audit_20261022-1.csv"
    _audit(a, [("NO", "ReadTimeout")])
    _audit(b, [("YES", "")])
    report = llm_failure_history(tmp_path, limit=2)
    assert report["available_run_files"] == 2
    assert "log_file" not in report["runs"][0]
    assert report["runs"][0]["failed_call_attempts"] == 0
    assert report["runs"][1]["failed_call_attempts"] == 1
    with pytest.raises(ValueError, match="limit"):
        llm_failure_history(tmp_path, limit=True)
    with pytest.raises(ValueError, match="limit"):
        llm_failure_history(tmp_path, limit=101)
    link = tmp_path / "llm_call_audit_link.csv"
    link.symlink_to(a)
    assert llm_failure_history(tmp_path)["available_run_files"] == 2
    with pytest.raises(ValueError, match="symlink"):
        summarize_llm_failure_audit(link)



def test_blank_record_degrades_without_reclassifying_quoted_newlines(tmp_path: Path):
    path = tmp_path / "llm_call_audit_20261022-blank.csv"
    _audit(path, [("YES", ""), ("NO", "timeout\n\nwithout separator")])
    raw = path.read_text(encoding="utf-8")
    # Place a genuinely blank physical CSV record between the two rows.
    with path.open("w", encoding="utf-8", newline="") as fp:
        fp.write(raw.replace("YES,", "YES,", 1))  # preserve valid quoted multiline
        fp.write("\n")
    report = summarize_llm_failure_audit(path)
    assert report["failed_call_attempts"] == 1
    assert report["successful_call_attempts"] == 1
    assert report["unclassified_or_invalid_status_rows"] == 1
    assert report["state"] == "degraded_invalid_rows"


def test_untrusted_filename_is_not_released_in_report(tmp_path: Path, capsys):
    source = tmp_path / "llm_call_audit_patient-123.csv"
    _audit(source, [("NO", "timeout with private token")])
    result = summarize_llm_failure_audit(source)
    assert "patient-123" not in json.dumps(result)
    assert "log_file" not in result
    assert main(["--audit-path", str(source)]) == 0
    assert "patient-123" not in capsys.readouterr().out


def test_history_enforces_actual_snapshots_not_stale_preflight_sizes(tmp_path: Path, monkeypatch):
    import czjLLM.utilities.llm_failure_summary as mod
    files = [tmp_path / f"llm_call_audit_20261022-{i}.csv" for i in range(3)]
    for item in files:
        _audit(item, [("YES", "")])
    real = mod._summarize_snapshot
    calls = []

    def forced(path, *, max_bytes):
        calls.append(max_bytes)
        summary, size = real(path, max_bytes=max_bytes)
        return summary, 25

    monkeypatch.setattr(mod, "_summarize_snapshot", forced)
    monkeypatch.setattr(mod, "MAX_HISTORY_BYTES", 60)
    with pytest.raises(ValueError, match="budget"):
        llm_failure_history(tmp_path, limit=3)
    assert len(calls) <= 3
    assert calls[-1] < calls[0]


def test_replacement_symlink_cannot_redirect_open(tmp_path: Path, monkeypatch):
    import czjLLM.utilities.llm_failure_summary as mod
    source = tmp_path / "llm_call_audit_20261022-safe.csv"
    target = tmp_path / "llm_call_audit_20261022-secret.csv"
    _audit(source, [("YES", "")])
    _audit(target, [("NO", "timeout")])
    original_open = mod.os.open

    def replaced(path, flags, *args, **kwargs):
        # Simulate local replacement after the initial lstat precheck.
        if Path(path) == source:
            source.unlink()
            source.symlink_to(target)
        return original_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(mod.os, "open", replaced)
    with pytest.raises((ValueError, OSError)):
        summarize_llm_failure_audit(source)


def test_cli_atomic_output_preserves_raw_csv_and_refuses_audit_names(tmp_path: Path, capsys):
    path = tmp_path / "llm_call_audit_20261022-77.csv"
    _audit(path, [("NO", "429"), ("YES", "")])
    raw = path.read_bytes()
    out = tmp_path / "safe_report.json"
    assert main(["--audit-path", str(path), "--output", str(out)]) == 0
    result = json.loads(out.read_text(encoding="utf-8"))
    assert result["run"]["failed_call_attempts"] == 1
    assert path.read_bytes() == raw
    assert json.loads(capsys.readouterr().out)["mode"] == "single_run"
    with pytest.raises(SystemExit) as exc:
        main(["--audit-path", str(path),
              "--output", str(tmp_path / "llm_call_audit_evil.json")])
    assert exc.value.code == 2
    assert path.read_bytes() == raw
