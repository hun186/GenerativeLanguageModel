"""Failure taxonomy consumes audit CSV only: no live model, network or database."""

from __future__ import annotations

import csv
import json
import os
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


def test_json_repair_failure_marker_is_counted_without_raw_payload(tmp_path: Path):
    path = tmp_path / "llm_call_audit_20261022-repair.csv"
    _audit(path, [("YES", ""), ("NO", "JSON_POSTPROCESSING_FAILED"),
                  ("NO", "")])
    report = summarize_llm_failure_audit(path)
    assert report["failed_call_attempts"] == 2
    assert report["failure_categories"]["json_postprocessing"] == 1
    assert report["failure_categories"]["unclassified"] == 1
    assert "JSON_POSTPROCESSING_FAILED" not in json.dumps(report)


@pytest.mark.skipif(not hasattr(os, "mkfifo") or not hasattr(os, "O_NONBLOCK"),
                    reason="requires POSIX nonblocking FIFO support")
def test_replaced_audit_fifo_open_cannot_block(tmp_path: Path, monkeypatch):
    import czjLLM.utilities.llm_failure_summary as mod
    source = tmp_path / "llm_call_audit_20261022-fifo.csv"
    _audit(source, [("YES", "")])
    orig = mod.os.open
    replaced = False

    def swap_to_fifo(path, flags, *args, **kwargs):
        nonlocal replaced
        if not replaced and Path(path) == source:
            replaced = True
            source.unlink()
            os.mkfifo(source)
            assert flags & os.O_NONBLOCK
        return orig(path, flags, *args, **kwargs)

    monkeypatch.setattr(mod.os, "open", swap_to_fifo)
    with pytest.raises(ValueError, match="changed or was redirected"):
        summarize_llm_failure_audit(source)
    assert replaced


def test_large_valid_csv_error_field_within_file_budget(tmp_path: Path):
    path = tmp_path / "llm_call_audit_20261022-large.csv"
    long_error = "ReadTimeout " + "confidential-data-" * 9000
    _audit(path, [("NO", long_error), ("YES", "")])
    original_limit = csv.field_size_limit()
    original_bytes = path.read_bytes()
    report = summarize_llm_failure_audit(path)
    assert report["failed_call_attempts"] == 1
    assert report["failure_categories"]["timeout"] == 1
    assert report["successful_call_attempts"] == 1
    assert report["state"] == "observed"
    assert long_error[:100] not in json.dumps(report)
    assert path.read_bytes() == original_bytes
    assert csv.field_size_limit() == original_limit


def test_large_csv_does_not_mutate_process_wide_parser_setting(tmp_path: Path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from czjLLM.utilities import llm_failure_summary as mod

    path = tmp_path / "llm_call_audit_20261022-concurrent.csv"
    _audit(path, [("NO", "ReadTimeout " + "private!" * 21000)])
    before = csv.field_size_limit()
    # Even if another unrelated CSV reader is using the global default,
    # our parser must not call the setter/getter at all.
    def forbidden_global_change(*args, **kwargs):
        raise AssertionError("csv.field_size_limit should never be used")

    monkeypatch.setattr(csv, "field_size_limit", forbidden_global_change)
    with ThreadPoolExecutor(max_workers=4) as pool:
        reports = list(pool.map(lambda _: mod.summarize_llm_failure_audit(path), range(8)))
    assert all(r["failure_categories"]["timeout"] == 1 for r in reports)
    monkeypatch.undo()
    assert csv.field_size_limit() == before


def test_csv_writer_escaping_multiline_and_bad_postquote(tmp_path: Path):
    path = tmp_path / "llm_call_audit_20261022-quotes.csv"
    _audit(path, [("NO", 'ReadTimeout: "header, quoted"\nsecond line'),
                  ("YES", "")])
    result = summarize_llm_failure_audit(path)
    assert result["failed_call_attempts"] == 1
    assert result["successful_call_attempts"] == 1
    path.write_bytes(b'ok,error\nNO,"closed"unexpected\n')
    with pytest.raises(ValueError, match="malformed"):
        summarize_llm_failure_audit(path)


def test_long_csv_error_field_does_not_amplify_per_character_memory(tmp_path: Path):
    import tracemalloc
    path = tmp_path / "llm_call_audit_20261022-near-limit.csv"
    # Quoted commas and CR/LF exercise the optimized StringIO span writer,
    # not merely the zero-copy unquoted branch.
    large_error = 'ReadTimeout ' + ('private,data\n' * 250000)
    _audit(path, [("NO", large_error)])
    size = path.stat().st_size
    assert 2 * 1024 * 1024 < size < 16 * 1024 * 1024
    tracemalloc.start()
    try:
        report = summarize_llm_failure_audit(path)
        _, peak_bytes = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert report["failure_categories"]["timeout"] == 1
    # Old one-list-reference-per-character implementation can exceed 10x;
    # allow generous headroom for CPython 3.10/3.11 differences.
    assert peak_bytes < size * 6


def test_csv_excess_fields_fail_before_multi_megabyte_buffering(tmp_path: Path):
    import tracemalloc
    path = tmp_path / "llm_call_audit_20261022-comma-flood.csv"
    # The approved header has two columns. A malformed row with millions of
    # empty fields must be rejected immediately at the third column, without
    # retaining the entire row as a Python object list.
    path.write_bytes(b"ok,error\nNO," + b"," * (4 * 1024 * 1024) + b"\n")
    original = path.read_bytes()
    tracemalloc.start()
    try:
        with pytest.raises(ValueError, match="too many fields"):
            summarize_llm_failure_audit(path)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert peak < len(original) * 5
    assert path.read_bytes() == original


def test_csv_header_field_bound_and_valid_width(tmp_path: Path):
    path = tmp_path / "llm_call_audit_20261022-width.csv"
    _audit(path, [("NO", 'ReadTimeout, "sample"'), ("YES", "")])
    assert summarize_llm_failure_audit(path)["failed_call_attempts"] == 1
    path.write_bytes(b"ok,error\nNO,timeout,unexpected\n")
    with pytest.raises(ValueError, match="too many fields"):
        summarize_llm_failure_audit(path)


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
    fixture_size = max(path.stat().st_size for path in files)
    # Each of the first two snapshots remains physically readable; only the
    # accumulated verified-byte accounting exhausts the third snapshot.
    budget = fixture_size * 2 + 5

    def forced(path, *, max_bytes):
        calls.append(max_bytes)
        summary, size = real(path, max_bytes=max_bytes)
        return summary, fixture_size + 3

    monkeypatch.setattr(mod, "_summarize_snapshot", forced)
    monkeypatch.setattr(mod, "MAX_HISTORY_BYTES", budget)
    with pytest.raises(ValueError, match="budget"):
        llm_failure_history(tmp_path, limit=3)
    assert len(calls) == 2
    assert calls[1] < calls[0]


def test_directory_swapped_to_same_file_via_symlink_is_detected(tmp_path: Path, monkeypatch):
    import czjLLM.utilities.llm_failure_summary as mod
    folder = tmp_path / "real-parent"
    folder.mkdir()
    source = folder / "llm_call_audit_20261022-1.csv"
    _audit(source, [("YES", "")])
    relocated = tmp_path / "moved-parent"
    original_open = mod.os.open
    did_swap = False

    def swap_before_open(path, flags, *args, **kwargs):
        nonlocal did_swap
        if Path(path) == source and not did_swap:
            did_swap = True
            folder.rename(relocated)
            folder.symlink_to(relocated, target_is_directory=True)
        # This is the SAME regular-file inode as before, so descriptor-vs-leaf
        # checks alone pass; checking all parent identities must reject it.
        return original_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(mod.os, "open", swap_before_open)
    with pytest.raises(ValueError, match="identity changed"):
        summarize_llm_failure_audit(source)
    assert did_swap


def test_history_rejects_plain_directory_swap_before_scandir(tmp_path: Path, monkeypatch):
    import czjLLM.utilities.llm_failure_summary as mod
    root = tmp_path / "audit"
    replacement = tmp_path / "replacement"
    root.mkdir()
    replacement.mkdir()
    _audit(root / "llm_call_audit_20261022-good.csv", [("YES", "")])
    _audit(replacement / "llm_call_audit_20261022-other.csv",
           [("NO", "ReadTimeout")])
    moved = tmp_path / "original-moved"
    real_scandir = mod.os.scandir
    did_swap = False

    def swap_scandir(path):
        nonlocal did_swap
        if Path(path) == root and not did_swap:
            did_swap = True
            root.rename(moved)
            replacement.rename(root)
        return real_scandir(path)

    monkeypatch.setattr(mod.os, "scandir", swap_scandir)
    with pytest.raises(ValueError, match="identity changed"):
        llm_failure_history(root)
    assert did_swap


def test_history_revalidates_root_after_selected_snapshot(tmp_path: Path, monkeypatch):
    import czjLLM.utilities.llm_failure_summary as mod
    root = tmp_path / "audit"
    replacement = tmp_path / "replacement"
    root.mkdir()
    replacement.mkdir()
    _audit(root / "llm_call_audit_20261022-good.csv", [("YES", "")])
    moved = tmp_path / "original-moved"
    original = mod._summarize_snapshot
    did_swap = False

    def swap_after_summary(path, *, max_bytes):
        nonlocal did_swap
        report = original(path, max_bytes=max_bytes)
        if not did_swap:
            did_swap = True
            root.rename(moved)
            replacement.rename(root)
        return report

    monkeypatch.setattr(mod, "_summarize_snapshot", swap_after_summary)
    with pytest.raises(ValueError, match="identity changed"):
        llm_failure_history(root)
    assert did_swap


def test_history_rejects_simulated_windows_junction_scope(tmp_path: Path, monkeypatch):
    import czjLLM.utilities.llm_failure_summary as mod
    _audit(tmp_path / "llm_call_audit_20261022-1.csv", [("YES", "")])
    original = mod._is_reparse_or_link

    def simulated(metadata):
        return (metadata.st_ino == tmp_path.lstat().st_ino and
                metadata.st_dev == tmp_path.lstat().st_dev) or original(metadata)

    monkeypatch.setattr(mod, "_is_reparse_or_link", simulated)
    # The earlier no-follow ancestor snapshot rejects this junction before
    # the later directory-type check; that early refusal is intentional.
    with pytest.raises(ValueError, match="symlink or reparse audit path components"):
        llm_failure_history(tmp_path)


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
