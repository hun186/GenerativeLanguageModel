"""Real-file offline audit correlation evidence, without network/model/sinks."""
from __future__ import annotations

import csv
import json
from pathlib import Path
from uuid import uuid4

import pytest

from czjLLM.cli_tools.llm_lineage_report import main
from czjLLM.utilities.llm_lineage_evidence import summarize_llm_lineage_evidence


def _audit(root: Path, fields: tuple[str, ...], rows: list[dict]) -> Path:
    path = root / "llm_call_audit_20261102-001.csv"
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    return path


def test_complete_observed_ids_are_not_http_request_denominators(tmp_path, capsys):
    a, b, claim = (uuid4().hex for _ in range(3))
    headers = ("ok", "error", "audit_record_id", "worker_call_id",
               "queue_claim_event_id", "call_llm_api_returned",
               "prompt_file", "base_url")
    rows = [
        dict(ok="YES", error="", audit_record_id=a, worker_call_id=b,
             queue_claim_event_id=claim, call_llm_api_returned="YES",
             prompt_file="PRIVATE_PATH", base_url="http://PRIVATE_KEY"),
    ]
    path = _audit(tmp_path, headers, rows)
    before = path.read_bytes()
    report = summarize_llm_lineage_evidence(path)
    assert report["state"] == "observed"
    assert report["observed_csv_rows"] == 1
    assert report["audit_id_columns"]["audit_record_id"]["valid_rows"] == 1
    assert report["audit_id_columns"]["worker_call_id"]["valid_rows"] == 1
    assert report["audit_id_columns"]["queue_claim_event_id"]["valid_rows"] == 1
    assert report["claim_id_without_worker_call_id_rows"] == 0
    assert "not provider HTTP attempt" in report["denominator_contract"]
    assert main(["--audit-path", str(path)]) == 0
    output = capsys.readouterr().out
    for secret in ("PRIVATE_PATH", "PRIVATE_KEY", a, b, claim, str(path)):
        assert secret not in output
    assert json.loads(output)["state"] == "observed"
    assert before == path.read_bytes()


def test_pre_uuid_legacy_audit_has_unknown_not_false_zero(tmp_path):
    path = _audit(tmp_path, ("ok", "error", "prompt_file"), [
        dict(ok="YES", error="", prompt_file="private"),
        dict(ok="NO", error="raw private traceback", prompt_file="private"),
    ])
    result = summarize_llm_lineage_evidence(path)
    assert result["state"] == "partial_evidence"
    assert result["observed_csv_rows"] == 2
    assert result["observed_yes_rows"] == 1
    assert result["observed_no_rows"] == 1
    assert result["audit_id_columns"]["worker_call_id"]["valid_rows"] is None
    assert result["call_llm_api_returned"]["yes_rows"] is None
    assert result["claim_id_without_worker_call_id_rows"] is None
    assert "private" not in json.dumps(result)


def test_duplicate_invalid_and_unpaired_ids_are_degraded_without_values(tmp_path):
    worker = uuid4().hex
    claim = uuid4().hex
    audit_id = uuid4().hex
    fields = ("ok", "error", "audit_record_id", "worker_call_id",
              "queue_claim_event_id", "call_llm_api_returned")
    path = _audit(tmp_path, fields, [
        dict(ok="NO", error="secret", audit_record_id=audit_id,
             worker_call_id=worker, queue_claim_event_id=claim,
             call_llm_api_returned="NO"),
        dict(ok="YES", error="", audit_record_id=audit_id,
             worker_call_id=worker, queue_claim_event_id=claim,
             call_llm_api_returned="YES"),
        dict(ok="YES", error="", audit_record_id="not-a-uuid-secret",
             worker_call_id="", queue_claim_event_id=uuid4().hex,
             call_llm_api_returned=""),
    ])
    report = summarize_llm_lineage_evidence(path)
    assert report["state"] == "degraded"
    assert report["audit_id_columns"]["audit_record_id"]["duplicate_rows"] == 1
    assert report["audit_id_columns"]["audit_record_id"]["invalid_rows"] == 1
    assert report["audit_id_columns"]["worker_call_id"]["duplicate_rows"] == 1
    assert report["claim_id_without_worker_call_id_rows"] == 1
    assert report["observed_csv_rows"] == 3
    for private in (worker, claim, audit_id, "not-a-uuid-secret", "secret"):
        assert private not in json.dumps(report)


def test_malformed_width_and_invalid_outcome_do_not_inflate_verified_counts(tmp_path):
    path = _audit(tmp_path, ("ok", "error", "audit_record_id"), [
        dict(ok="YES", error="", audit_record_id=uuid4().hex),
        dict(ok="MAYBE", error="private-error", audit_record_id=""),
    ])
    with path.open("a", encoding="utf-8", newline="") as fp:
        fp.write("NO,secret,extra,cell\r\n")
    result = summarize_llm_lineage_evidence(path)
    assert result["state"] == "degraded"
    assert result["malformed_width_rows"] == 1
    assert result["unknown_outcome_rows"] == 1
    assert result["observed_yes_rows"] == 1
    assert result["observed_no_rows"] == 0
    assert result["observed_csv_rows"] == 3


def test_bad_header_reparse_and_incomplete_snapshot_fail_closed(tmp_path, capsys):
    bad = _audit(tmp_path, ("ok", "ok", "error"), [
        {"ok": "YES", "error": ""},
    ])
    with pytest.raises(ValueError, match="header"):
        summarize_llm_lineage_evidence(bad)
    good = _audit(tmp_path, ("ok", "error"), [{"ok": "YES", "error": ""}])
    with good.open("ab") as fp:
        fp.write(b"partial")
    with pytest.raises(ValueError, match="incomplete"):
        summarize_llm_lineage_evidence(good)
    with pytest.raises(SystemExit):
        main(["--audit-path", str(good)])
    printed = capsys.readouterr().err
    assert "invalid, unstable or oversized" in printed
    assert "partial" not in printed


def test_reused_claim_is_shared_reference_not_duplicate_provider_request(tmp_path):
    claim = uuid4().hex
    path = _audit(tmp_path, (
        "ok", "error", "audit_record_id", "worker_call_id",
        "queue_claim_event_id", "call_llm_api_returned",
    ), [
        {"ok": "YES", "error": "", "audit_record_id": uuid4().hex,
         "worker_call_id": uuid4().hex, "queue_claim_event_id": claim,
         "call_llm_api_returned": "YES"},
        {"ok": "NO", "error": "hidden", "audit_record_id": uuid4().hex,
         "worker_call_id": uuid4().hex, "queue_claim_event_id": claim,
         "call_llm_api_returned": "NO"},
    ])
    report = summarize_llm_lineage_evidence(path)
    assert report["state"] == "observed"
    assert report["audit_id_columns"]["queue_claim_event_id"]["duplicate_rows"] == 1
    assert report["audit_id_columns"]["audit_record_id"]["duplicate_rows"] == 0
    assert "shared references" in report["duplicate_id_semantics"]
    assert claim not in json.dumps(report)


def test_blank_worker_return_is_unknown_not_failure_or_provider_error(tmp_path):
    path = _audit(tmp_path, (
        "ok", "error", "audit_record_id", "worker_call_id",
        "queue_claim_event_id", "call_llm_api_returned",
    ), [
        {"ok": "YES", "error": "", "audit_record_id": uuid4().hex,
         "worker_call_id": uuid4().hex, "queue_claim_event_id": "",
         "call_llm_api_returned": ""},
    ])
    report = summarize_llm_lineage_evidence(path)
    assert report["state"] == "partial_evidence"
    assert report["call_llm_api_returned"]["unknown_rows"] == 1
    assert report["call_llm_api_returned"]["invalid_rows"] == 0
    assert report["observed_no_rows"] == 0


def test_noncanonical_uuid4_and_invalid_return_marker_fail_degraded(tmp_path):
    path = _audit(tmp_path, (
        "ok", "error", "audit_record_id", "worker_call_id",
        "queue_claim_event_id", "call_llm_api_returned",
    ), [
        {"ok": "YES", "error": "", "audit_record_id": str(uuid4()),
         "worker_call_id": uuid4().hex.upper(),
         "queue_claim_event_id": "", "call_llm_api_returned": "MAYBE"},
    ])
    report = summarize_llm_lineage_evidence(path)
    assert report["state"] == "degraded"
    assert report["audit_id_columns"]["audit_record_id"]["invalid_rows"] == 1
    assert report["audit_id_columns"]["worker_call_id"]["invalid_rows"] == 1
    assert report["call_llm_api_returned"]["invalid_rows"] == 1
