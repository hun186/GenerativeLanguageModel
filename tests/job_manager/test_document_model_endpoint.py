"""Observed per-row LLM model/IP is audit evidence, not configured endpoint guess."""
from __future__ import annotations

import csv
import inspect
from pathlib import Path

from czjLLM.job_manager import document_progress, win_gui
from czjLLM.job_manager.document_model_endpoint import (
    _endpoint_ip, observed_model_endpoint_pairs, summarize_model_endpoint_pairs,
)


def _audit(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(
            stream, fieldnames=("prompt_file", "model", "base_url", "ok", "error"),
        )
        writer.writeheader()
        writer.writerows(rows)


def test_multiple_rows_only_join_real_descendant_prompt_paths(tmp_path):
    root = tmp_path / "item"
    sibling = tmp_path / "item_extra"
    inside = root / "RUNNING" / "a.txt"
    audit = tmp_path / "llm_call_audit_test.csv"
    _audit(audit, [
        dict(prompt_file=str(inside), model="qwen3.6:128k",
             base_url="http://192.168.1.20:11434/v1", ok="YES", error=""),
        dict(prompt_file=str(root / "RUNNING" / "b.txt"),
             model="qwen3.6:128k", base_url="http://192.168.1.21:11434/v1",
             ok="NO", error="secret failure"),
        dict(prompt_file=str(sibling / "RUNNING" / "c.txt"),
             model="other-model", base_url="http://10.0.0.3:5000",
             ok="YES", error=""),
    ])
    seen = observed_model_endpoint_pairs(audit, {
        "one": str(root), "other": str(sibling), "missing": str(tmp_path / "missing"),
    })
    assert seen["one"]["pairs"] == [
        "qwen3.6:128k · 192.168.1.20:11434",
        "qwen3.6:128k · 192.168.1.21:11434",
    ]
    assert seen["one"]["latest"] == "qwen3.6:128k · 192.168.1.21:11434"
    assert seen["other"]["latest"] == "other-model · 10.0.0.3:5000"
    assert seen["missing"]["latest"] == ""
    assert "2 組" not in summarize_model_endpoint_pairs(seen["one"])
    assert "(+1 組)" in summarize_model_endpoint_pairs(seen["one"])


def test_only_literal_ip_is_displayed_never_full_url_or_secrets(tmp_path):
    assert _endpoint_ip("http://10.1.2.3:11434/api?token=SECRET") == "10.1.2.3:11434"
    assert _endpoint_ip("https://[2001:db8::1]:8443/v1") == "[2001:db8::1]:8443"
    assert _endpoint_ip("http://user:password@10.1.2.3:11434/") == ""
    assert _endpoint_ip("https://service.example.internal:443") == ""
    assert _endpoint_ip("http://localhost:11434") == ""
    assert _endpoint_ip("invalid://10.1.2.3") == ""
    assert _endpoint_ip("http://10.1.2.3:bad") == ""
    audit = tmp_path / "llm_call_audit_protected.csv"
    item = tmp_path / "item"
    _audit(audit, [
        dict(prompt_file=str(item / "RUNNING" / "input.txt"),
             model="qwen3.6:latest-128k",
             base_url="http://user:password@192.168.1.2:11434/?token=SECRET",
             ok="NO", error="PRIVATE_ERR"),
    ])
    projected = observed_model_endpoint_pairs(audit, {"one": str(item)})
    assert projected["one"]["latest"] == "qwen3.6:latest-128k · IP 未記錄"
    assert "password" not in str(projected)
    assert "SECRET" not in str(projected)
    assert "input.txt" not in str(projected)


def test_strict_audit_failure_preserves_meter_rows_and_unknown_marker(tmp_path, monkeypatch):
    meter = tmp_path / "loadmeter_test.json"
    item = tmp_path / "item"
    meter.write_text(__import__("json").dumps({
        "rows": {"r1": {
            "item_dir": str(item), "total": 2, "done": 1,
            "queue_running": 1, "status": "in_progress",
        }},
    }), encoding="utf-8")
    missing_audit = tmp_path / "llm_call_audit_no_csv.csv"
    view = document_progress.read_document_progress(
        meter, audit_path=str(missing_audit),
    )
    assert len(view["shown"]) == 1
    assert view["shown"][0]["model_endpoint"] == "—"
    assert "Audit 暫無法核對" in view["notice"]

    audit = tmp_path / "llm_call_audit_yes.csv"
    _audit(audit, [dict(prompt_file=str(item / "RUNNING" / "p.txt"),
                        model="mock-model", base_url="http://127.0.0.1:11434",
                        ok="YES", error="")])
    view = document_progress.read_document_progress(meter, audit_path=str(audit))
    assert view["shown"][0]["model_endpoint"] == "mock-model · 127.0.0.1:11434"
    assert "127.0.0.1" not in meter.read_text(encoding="utf-8")
    with audit.open("ab") as output:
        output.write(b"truncated")
    bad = document_progress.read_document_progress(meter, audit_path=str(audit))
    assert bad["shown"][0]["model_endpoint"] == "—"
    assert bad["shown"][0]["stage"] == view["shown"][0]["stage"]
    assert "Audit 暫無法核對" in bad["notice"]


def test_guarantees_no_model_from_unobserved_config_or_unrelated_item(tmp_path):
    row = document_progress.classify_row("row", {
        "total": 1, "done": 0, "status": "in_progress",
        "model_spec": {"model_name": "UNVERIFIED-config", "base_url": "http://10.0.0.1"},
    })
    assert row["model_endpoint"] == "—"
    audit = tmp_path / "llm_call_audit_status.csv"
    _audit(audit, [dict(prompt_file="/unrelated/RUNNING/a.txt",
                        model="qwen3.6", base_url="http://192.168.1.8",
                        ok="YES", error="")])
    found = observed_model_endpoint_pairs(audit, {"x": str(tmp_path / "row")})
    assert found["x"]["latest"] == ""


def test_gui_inserts_one_actual_observed_model_ip_column_without_changing_cancel():
    src = inspect.getsource(win_gui._gui_proc_main)
    assert '("model_endpoint", "模型／端點 IP（已記錄）", 250)' in src
    assert 'item["model_endpoint"], item["pending_text"]' in src
    assert "page=args[3], audit_path=args[4]" in src
    assert 'orient="horizontal", command=document_grid.xview' in src
    assert "cancel_event.set()" in src
    assert "Cancelled / safely drained" in src


def test_switch_back_to_prior_endpoint_is_still_the_actual_latest(tmp_path):
    root = tmp_path / "item"
    audit = tmp_path / "llm_call_audit_switch.csv"
    _audit(audit, [
        dict(prompt_file=str(root / "RUNNING" / f"{i}.txt"),
             model="qwen3.6",
             base_url=f"http://192.168.20.{host}:11434",
             ok="YES", error="")
        for i, host in enumerate((11, 22, 11))
    ])
    evidence = observed_model_endpoint_pairs(audit, {"row": str(root)})["row"]
    assert evidence["pairs"] == [
        "qwen3.6 · 192.168.20.11:11434",
        "qwen3.6 · 192.168.20.22:11434",
    ]
    assert evidence["latest"] == "qwen3.6 · 192.168.20.11:11434"
    assert summarize_model_endpoint_pairs(evidence).startswith(
        "qwen3.6 · 192.168.20.11:11434"
    )


def test_more_than_six_distinct_endpoints_still_displays_last_actual_observation(tmp_path):
    root = tmp_path / "item"
    audit = tmp_path / "llm_call_audit_seven.csv"
    _audit(audit, [
        dict(prompt_file=str(root / "RUNNING" / f"{i}.txt"),
             model="qwen3.6", base_url=f"http://192.168.30.{i}:11434",
             ok="YES", error="")
        for i in range(1, 9)
    ])
    evidence = observed_model_endpoint_pairs(audit, {"row": str(root)})["row"]
    assert len(evidence["pairs"]) == 6
    assert evidence["more_pairs"] is True
    assert evidence["latest"] == "qwen3.6 · 192.168.30.8:11434"
    text = summarize_model_endpoint_pairs(evidence)
    assert text.startswith("qwen3.6 · 192.168.30.8:11434")
    assert "(+6+ 組)" in text
    assert "192.168.30.6" not in text


def test_legacy_non_dict_meter_row_does_not_break_model_projection(tmp_path):
    meter = tmp_path / "loadmeter_legacy.json"
    item = tmp_path / "item"
    meter.write_text(__import__("json").dumps({
        "rows": {"broken": None, "wellformed": {"item_dir": str(item), "total": 1}},
    }), encoding="utf-8")
    audit = tmp_path / "llm_call_audit_legacy.csv"
    _audit(audit, [dict(prompt_file=str(item / "RUNNING" / "a.txt"),
                        model="qwen3.6", base_url="http://10.0.0.8:11434",
                        ok="YES", error="")])
    result = document_progress.read_document_progress(
        meter, mode="全部", audit_path=str(audit),
    )
    by_key = {row["key"]: row["model_endpoint"] for row in result["shown"]}
    assert by_key["broken"] == "—"
    assert by_key["wellformed"] == "qwen3.6 · 10.0.0.8:11434"
