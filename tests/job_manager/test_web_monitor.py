"""Actual loopback HTTP and process lifecycle, no GPU or external server."""
import http.client
import json
import socket
import time

import pytest

from czjLLM.job_manager.web_monitor import start_web_monitor, try_start_web_monitor


def _request(port, path, method="GET", headers=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
    try:
        conn.request(method, path, headers=headers or {})
        response = conn.getresponse()
        return response.status, response.read(), dict(response.getheaders())
    finally:
        conn.close()


def test_real_local_service_is_read_only_and_private_events_are_excluded():
    client = start_web_monitor(10, 0)
    assert client is not None
    try:
        client.inc_sched(4)
        client.inc_done(2)
        client.log("PRIVATE_LOG")
        client.set_audit_path("PRIVATE_PATH")
        client.inc_sched(-1)
        deadline = time.monotonic() + 5
        while True:
            status, raw, headers = _request(client.port, "/api/v1/status")
            data = json.loads(raw)
            if data["scheduled"] == 4 and data["completed"] == 2:
                break
            assert time.monotonic() < deadline
            time.sleep(.05)
        assert status == 200 and data["delivery_incomplete"]
        assert not data["sink_readback_verified"]
        assert b"PRIVATE" not in raw and headers["Cache-Control"] == "no-store"
        assert _request(client.port, "/")[0] == 200
        assert _request(client.port, "/app.js")[0] == 200
        assert _request(client.port, "/api/v1/status", "POST")[0] == 405
        assert _request(client.port, "/../../secret")[0] == 404
        assert _request(client.port, "/api/v1/status", headers={"Host": "other.example"})[0] == 403
        assert _request(client.port, "/api/v1/status", headers={"Origin": "https://other.example"})[0] == 403
        assert not client.cancellation_requested()
    finally:
        client.close()
    assert not client._process.is_alive()
    client.close()


def test_port_conflict_and_nonlocal_bind_fail_closed():
    with socket.socket() as occupied:
        occupied.bind(("127.0.0.1", 0))
        occupied.listen(1)
        assert start_web_monitor(0, occupied.getsockname()[1]) is None
    with pytest.warns(RuntimeWarning):
        assert try_start_web_monitor(1, {"GLM_WEB_HOST": "0.0.0.0"}) is None
    with pytest.warns(RuntimeWarning):
        assert try_start_web_monitor(1, {"GLM_WEB_PORT": "invalid"}) is None


def test_document_projection_real_meter_and_corruption(tmp_path):
    from czjLLM.job_manager.web_document_monitor import DocumentMonitor, project_public_documents
    meter = tmp_path / "PRIVATE_PATH.json"
    rows = {"PRIVATE_KEY": {"status": "in_progress", "total": 4, "done": 1,
                            "queue_running": 2, "temp_txt": "PRIVATE_FILENAME"}}
    meter.write_text(json.dumps({"rows": rows}), encoding="utf-8")
    now = [0.]
    monitor = DocumentMonitor(clock=lambda: now[0])
    monitor.set_path(str(meter))
    monitor.refresh_once()
    view = monitor.snapshot()
    assert view["status"] == "observed" and view["active"] == 1
    assert view["rows"][0]["running"] == 2
    assert "PRIVATE" not in json.dumps(view)
    assert view["sink_readback_verified"] is False
    alias = view["rows"][0]["alias"]
    monitor.refresh_once()
    assert monitor.snapshot()["rows"][0]["alias"] == alias
    now[0] = 9.
    assert monitor.snapshot() == {"status": "stale", "rows": []}
    meter.write_text("{", encoding="utf-8")
    monitor.refresh_once()
    assert monitor.snapshot() == {"status": "unavailable", "rows": []}
    monitor.set_path(str(tmp_path / "missing.json"))
    assert monitor.snapshot() == {"status": "waiting_for_meter", "rows": []}
    many = {"rows": {str(i): rows["PRIVATE_KEY"] for i in range(15)}}
    projected = project_public_documents(many, b"test")
    assert len(projected["rows"]) == 12 and projected["omitted"] == 3


def test_document_reader_rejects_result_from_previous_generation(monkeypatch):
    from czjLLM.job_manager import web_document_monitor as docs
    monitor = docs.DocumentMonitor()
    monitor.set_path("old")
    def read(_):
        monitor.set_path("new")
        return {"rows": {"old": {"status": "in_progress", "total": 1}}}
    monkeypatch.setattr(docs, "read_meter_strict", read)
    monitor.refresh_once()
    assert monitor.snapshot() == {"status": "waiting_for_meter", "rows": []}


def test_real_http_document_snapshot(tmp_path):
    meter = tmp_path / "PRIVATE_PATH.json"
    meter.write_text(json.dumps({"rows": {"PRIVATE_KEY": {
        "status": "in_progress", "total": 2, "done": 1, "queue_running": 1,
        "temp_txt": "PRIVATE_FILENAME"}}}), encoding="utf-8")
    client = start_web_monitor(1, 0)
    assert client is not None
    try:
        client.set_recovery_meter_path(meter)
        deadline = time.monotonic() + 12
        while True:
            status, raw, _ = _request(client.port, "/api/v1/status")
            doc = json.loads(raw)["documents"]
            if doc["status"] == "observed":
                break
            assert time.monotonic() < deadline
            time.sleep(.1)
        assert status == 200
        assert doc["rows"][0]["done"] == 1 and b"PRIVATE" not in raw
        assert _request(client.port, "/api/v1/status?path=/private")[0] == 404
    finally:
        client.close()


def test_worker_activity_real_files_and_redacted_http(tmp_path):
    from uuid import uuid4
    from czjLLM.job_manager.worker_dispatch_observation import write_worker_dispatch_observation

    item = tmp_path / "PRIVATE_ITEM"
    item.mkdir()
    audit = tmp_path / "llm_call_audit_20261102-1.csv"
    audit.write_text("prompt_file,model,base_url,ok,error\n", encoding="utf-8")
    meter = tmp_path / "meter.json"
    meter.write_text(json.dumps({"rows": {"PRIVATE_ROW": {
        "status": "in_progress", "total": 3, "done": 0, "queue_running": 2,
        "item_dir": str(item), "temp_txt": "PRIVATE_NAME"}}}), encoding="utf-8")
    a, b, c = uuid4().hex, uuid4().hex, uuid4().hex
    def emit(call, endpoint, status, detail=None):
        write_worker_dispatch_observation(
            audit_path=str(audit), item_dir=str(item), prompt_file=str(item / "chunk.txt"),
            worker_call_id=call, model_spec={"model_name": "PRIVATE_MODEL",
                "base_url": "http://" + endpoint, "api_key": "PRIVATE_SECRET"},
            status=status, stream_activity=detail)
    emit(a, "10.20.30.40:11434", "calling", {
        "event": "received", "elapsed_s": 5, "last_chunk_elapsed_s": 3,
        "chunks": 2, "thinking_seen": True, "content_seen": False})
    emit(b, "10.20.30.41:11434", "calling")
    emit(c, "10.20.30.42:11434", "returned")
    client = start_web_monitor(1, 0)
    assert client is not None
    try:
        client.set_recovery_meter_path(meter)
        client.set_audit_path(audit)
        def wait_count(expected):
            deadline = time.monotonic() + 15
            while True:
                _, raw, _ = _request(client.port, "/api/v1/status")
                docs = json.loads(raw)["documents"]
                workers = docs.get("workers", {})
                if workers.get("status") == "observed" and workers["count"] == expected:
                    return docs, workers, raw
                assert time.monotonic() < deadline
                time.sleep(.1)
        docs, workers, raw = wait_count(2)
        assert len(workers["calls"]) == 2
        assert len({v["endpoint_alias"] for v in workers["calls"]}) == 2
        assert {v["row_alias"] for v in workers["calls"]} == {docs["rows"][0]["alias"]}
        assert any(v["chunks"] == 2 and v["thinking_seen"] for v in workers["calls"])
        assert workers["gpu_utilization_known"] is False
        for private in (b"PRIVATE", b"10.20.30.", b"anchor_s", a.encode(), b.encode(), c.encode()):
            assert private not in raw
        emit(a, "10.20.30.40:11434", "returned")
        _, remaining, _ = wait_count(1)
        assert remaining["calls"][0]["chunks"] is None
    finally:
        client.close()


def test_shared_audit_numeric_projection_and_strict_limits(tmp_path, monkeypatch):
    from czjLLM.job_manager import audit_distribution as core
    from czjLLM.job_manager import win_gui
    assert win_gui.load_llm_audit_distribution is core.load_llm_audit_distribution
    audit = tmp_path / "audit.csv"
    audit.write_text("ok,prompt_file,token_usage_source,input_tokens,output_tokens,elapsed_seconds,cached_input_tokens,cached_input_token_source,model,base_url\n"
                     "YES,PRIVATE_FILE,llm_api_usage,100,20,2,0,provider_usage,PRIVATE_MODEL,PRIVATE_URL\n"
                     "YES,PRIVATE_FILE,llm_api_usage,200,40,4,100,provider_usage,PRIVATE_MODEL,PRIVATE_URL\n",
                     encoding="utf-8")
    view = core.load_public_audit(audit)
    assert view["status"] == "observed" and view["calls"] == 2
    assert view["metrics"]["elapsed_seconds"]["p50"] == 3
    assert view["metrics"]["elapsed_seconds"]["p95"] == 3.9
    assert view["metrics"]["template_tokens"]["p50"] is None
    assert view["provider_cache"]["observed_rows"] == 2
    assert view["provider_cache"]["hit_pct"] == pytest.approx(100/3)
    assert view["phase_metrics"] == {"ttft": None, "prefill": None, "decode": None}
    assert "PRIVATE" not in json.dumps(view)
    monkeypatch.setattr(core, "MAX_AUDIT_ROWS", 1)
    assert core.load_public_audit(audit)["status"] == "unavailable_or_over_budget"
    monkeypatch.setattr(core, "MAX_AUDIT_ROWS", 20000)
    audit.write_text("ok,prompt_file,token_usage_source\nYES,x,llm_api_usage", encoding="utf-8")
    assert core.load_public_audit(audit)["status"] == "unavailable_or_over_budget"
    monkeypatch.setattr(core, "MAX_AUDIT_BYTES", 5)
    assert core.load_public_audit(audit)["status"] == "unavailable_or_over_budget"


def test_audit_http_available_without_meter_and_no_private_metadata(tmp_path):
    audit = tmp_path / "llm_call_audit_20261102-1.csv"
    audit.write_text("ok,prompt_file,token_usage_source,input_tokens,output_tokens,elapsed_seconds\n"
                     "YES,PRIVATE_FILE,llm_api_usage,100,20,2\n", encoding="utf-8")
    client = start_web_monitor(1, 0)
    assert client is not None
    try:
        client.set_audit_path(audit)
        deadline = time.monotonic() + 12
        while True:
            _, raw, _ = _request(client.port, "/api/v1/status")
            data = json.loads(raw)
            if data["audit"]["status"] == "observed":
                break
            assert time.monotonic() < deadline
            time.sleep(.1)
        assert data["audit"]["calls"] == 1
        assert data["audit"]["metrics"]["elapsed_seconds"]["p50"] == 2
        assert b"PRIVATE" not in raw
        assert data["documents"]["status"] == "waiting_for_meter"
    finally:
        client.close()


@pytest.mark.parametrize("outcome", ["", "MAYBE", "yes", "UNKNOWN"])
def test_strict_audit_rejects_unknown_outcome_but_preserves_desktop_legacy(tmp_path, outcome):
    from czjLLM.job_manager import audit_distribution as core
    audit = tmp_path / "audit.csv"
    audit.write_text("ok,prompt_file,token_usage_source,input_tokens,output_tokens,elapsed_seconds\n"
                     + f"{outcome},x,llm_api_usage,100,20,2\n", encoding="utf-8")
    assert core.load_public_audit(audit) == {"status": "unavailable_or_over_budget"}
    assert core.load_llm_audit_distribution(audit)["calls"] == 1


def test_stream_distribution_valid_zero_missing_and_invalid_diagnostics(tmp_path):
    import csv
    from czjLLM.job_manager import audit_distribution as core, win_gui
    audit = tmp_path / "audit.csv"
    fields = ["ok", "prompt_file", "token_usage_source", "stream_timing_source",
              "stream_ttft_seconds", "stream_first_thinking_seconds",
              "stream_first_content_seconds", "stream_chunks"]
    source = "client_monotonic_completed_sse"
    rows = [
        ["YES", "PRIVATE", "llm_api_usage", source, "0", "", "0", "3"],
        ["NO", "PRIVATE", "llm_api_usage", source, "2", "2", "5", "7"],
        ["YES", "", "llm_api_usage", source, "", "", "", "2"],
        ["YES", "", "llm_api_usage", "", "", "", "", ""],
        ["YES", "", "llm_api_usage", source, "4", "2", "5", "7"],
        ["YES", "", "llm_api_usage", "native_guess", "1", "1", "", "2"],
        ["YES", "", "llm_api_usage", source, "nan", "", "nan", "2"],
        ["YES", "", "llm_api_usage", "", "1", "", "", ""],
    ]
    with audit.open("w", newline="", encoding="utf-8") as fp:
        writer = csv.writer(fp)
        writer.writerow(fields)
        writer.writerows(rows)
    view = core.load_public_audit(audit)
    timing = view["stream_timing"]
    assert view["status"] == "observed" and view["calls"] == 8 and view["failures"] == 1
    assert timing["observed_rows"] == 3 and timing["unreported_rows"] == 1
    assert timing["invalid_rows"] == 4 and timing["no_text_rows"] == 1
    assert timing["metrics"]["stream_ttft_seconds"]["count"] == 2
    assert timing["metrics"]["stream_ttft_seconds"]["p50"] == 1
    assert timing["metrics"]["stream_first_thinking_seconds"]["count"] == 1
    assert timing["metrics"]["stream_first_content_seconds"]["p50"] == 2.5
    assert timing["metrics"]["stream_chunks"]["count"] == 3
    assert view["phase_metrics"] == {"ttft": 1, "prefill": None, "decode": None}
    assert "PRIVATE" not in json.dumps(view)
    desktop = core.load_llm_audit_distribution(audit)
    assert desktop["stream_timing"]["metrics"]["stream_ttft_seconds"]["p50"] == 1
    summary = win_gui.format_llm_audit_summary(desktop)
    assert "TTFT P50/P95 1.0/1.9s (n=2)" in summary and "3/8" in summary


def test_stream_timing_http_coverage_and_no_inferred_native_phase(tmp_path):
    audit = tmp_path / "llm_call_audit_20261102-1.csv"
    audit.write_text("ok,prompt_file,token_usage_source,stream_timing_source,"
                     "stream_ttft_seconds,stream_first_thinking_seconds,"
                     "stream_first_content_seconds,stream_chunks\n"
                     "YES,PRIVATE,llm_api_usage,client_monotonic_completed_sse,0,,0,2\n",
                     encoding="utf-8")
    client = start_web_monitor(1, 0)
    assert client is not None
    try:
        client.set_audit_path(audit)
        deadline = time.monotonic() + 12
        while True:
            _, raw, _ = _request(client.port, "/api/v1/status")
            view = json.loads(raw)["audit"]
            if view["status"] == "observed":
                break
            assert time.monotonic() < deadline
            time.sleep(.1)
        assert view["stream_timing"]["observed_rows"] == 1
        assert view["stream_timing"]["metrics"]["stream_ttft_seconds"]["p50"] == 0
        assert view["phase_metrics"]["prefill"] is None and view["phase_metrics"]["decode"] is None
        assert b"PRIVATE" not in raw
    finally:
        client.close()


def test_incremental_audit_matches_full_snapshot_and_reuses_unchanged_result(tmp_path, monkeypatch):
    import csv
    from czjLLM.job_manager import audit_distribution as core
    from czjLLM.job_manager import audit_distribution_incremental as inc
    audit = tmp_path / "llm_call_audit_20261102-1.csv"
    fields = ["ok", "prompt_file", "token_usage_source", "input_tokens", "output_tokens",
              "elapsed_seconds", "error", "model", "base_url", "task", "stage_identity",
              "task_text_tokens", "template_tokens", "prompt_component_token_source"]
    rows = [["YES", "PRIVATE", "llm_api_usage", 100, 20, i+1, "quoted\nline", "m",
             "url", "task", "stage", 70, 30, "tokenizer"] for i in range(8)]
    with audit.open("w", newline="", encoding="utf-8") as fp:
        writer = csv.writer(fp)
        writer.writerow(fields)
        writer.writerows(rows)
    monkeypatch.setattr(inc, "MAX_SCAN_BYTES", 256)
    reader = inc.IncrementalAuditReader()
    seen = []
    for _ in range(20):
        result = reader.read(str(audit))
        if result["status"] == "observed":
            break
        assert result["status"] == "catching_up" and "calls" not in result
        seen.append(result["scanned_bytes"])
    assert seen and result["status"] == "observed"
    full = core.load_public_audit(audit)
    assert result["metrics"] == full["metrics"]
    assert result["stream_timing"] == full["stream_timing"]
    assert result["effective_heuristic_rows"] == full["effective_heuristic_rows"] == 6
    assert "PRIVATE" not in json.dumps(result)
    with monkeypatch.context() as ctx:
        def no_sort():
            raise AssertionError("unchanged file must reuse cached stats")
        ctx.setattr(reader.acc, "snapshot", no_sort)
        assert reader.read(str(audit)) == result
    with audit.open("a", newline="", encoding="utf-8") as fp:
        csv.writer(fp).writerow(rows[0])
    assert reader.read(str(audit))["calls"] == 9


def test_incremental_audit_incomplete_tail_replacement_and_budget(tmp_path, monkeypatch):
    from czjLLM.job_manager import audit_distribution_incremental as inc
    path = tmp_path / "llm_call_audit_20261102-1.csv"
    header = "ok,prompt_file,token_usage_source,elapsed_seconds\n"
    path.write_text(header + "YES,x,llm_api_usage,1\n", encoding="utf-8")
    reader = inc.IncrementalAuditReader()
    assert reader.read(str(path))["calls"] == 1
    with path.open("a", encoding="utf-8") as fp:
        fp.write("NO,x,llm_api_usage,2")
    pending = reader.read(str(path))
    assert pending["status"] == "catching_up" and "calls" not in pending
    with path.open("a", encoding="utf-8") as fp:
        fp.write("\n")
    assert reader.read(str(path))["failures"] == 1
    replacement = tmp_path / "replacement.csv"
    replacement.write_text(header + "YES,x,llm_api_usage,9\n", encoding="utf-8")
    replacement.replace(path)
    assert reader.read(str(path))["metrics"]["elapsed_seconds"]["p50"] == 9
    monkeypatch.setattr(inc, "MAX_ROWS", 1)
    other = tmp_path / "llm_call_audit_20261102-2.csv"
    other.write_text(header + "YES,x,llm_api_usage,1\nYES,x,llm_api_usage,2\n", encoding="utf-8")
    assert reader.read(str(other)) == {"status": "unavailable_or_over_budget"}


def test_audit_comparison_partitions_context_source_endpoint_and_cache(tmp_path):
    import csv
    from czjLLM.job_manager.audit_distribution_incremental import IncrementalAuditReader
    path = tmp_path / "llm_call_audit_20261102-1.csv"
    fields = ["ok", "prompt_file", "token_usage_source", "model", "base_url",
              "context_limit_tokens", "context_limit_source", "input_tokens", "output_tokens",
              "cached_input_tokens", "cached_input_token_source", "elapsed_seconds",
              "stream_timing_source", "stream_ttft_seconds", "stream_first_thinking_seconds",
              "stream_first_content_seconds", "stream_chunks"]
    def row(model, endpoint, ctx, source, ok, cache, elapsed):
        return [ok, "PRIVATE_PROMPT", "llm_api_usage", model, endpoint, ctx, source,
                100, 20, cache, "provider_usage", elapsed,
                "client_monotonic_completed_sse", "0", "", "0", "3"]
    rows = [
        row("PRIVATE_MODEL", "PRIVATE_ENDPOINT_A", 65536, "response", "YES", 0, 1),
        row("PRIVATE_MODEL", "PRIVATE_ENDPOINT_A", 65536, "response", "NO", 100, 3),
        row("PRIVATE_MODEL", "PRIVATE_ENDPOINT_A", 65536, "model_spec", "YES", 50, 4),
        row("PRIVATE_MODEL", "PRIVATE_ENDPOINT_B", 65536, "response", "YES", 50, 5),
        row("PRIVATE_MODEL", "PRIVATE_ENDPOINT_A", 131072, "response", "YES", 50, 6),
        row("PRIVATE_MODEL", "PRIVATE_ENDPOINT_A", 0, "unknown", "YES", 50, 7),
        row("", "PRIVATE_ENDPOINT_A", 65536, "response", "YES", 50, 8),
    ]
    with path.open("w", newline="", encoding="utf-8") as fp:
        writer = csv.writer(fp)
        writer.writerow(fields)
        writer.writerows(rows)
    reader = IncrementalAuditReader()
    view = reader.read(str(path))
    comp = view["comparison"]
    assert comp["grouped_rows"] == 6 and comp["unidentified_rows"] == 1
    assert len(comp["groups"]) == 5
    g = comp["groups"][0]
    assert g["calls"] == 2 and g["failure_pct"] == 50
    assert g["provider_cache"]["hit_pct"] == 50
    assert g["ttft"]["p50"] == 0 and g["ttft"]["count"] == 2
    assert g["slice_time"]["p50"] == 2
    assert len({x["model_alias"] for x in comp["groups"]}) == 1
    assert len({x["endpoint_alias"] for x in comp["groups"]}) == 2
    assert sum(x["context_limit_tokens"] is None for x in comp["groups"]) == 1
    assert "PRIVATE" not in json.dumps(view)
    assert reader.read(str(path)) == view


def test_group_budget_does_not_combine_distinct_or_unidentified_calls():
    from czjLLM.job_manager.audit_comparison import AuditComparison
    c = AuditComparison(max_rows=20, max_groups=1)
    base = {"ok": "YES", "model": "m", "base_url": "a",
            "prompt_file": "x", "token_usage_source": "llm_api_usage"}
    c.consume(base)
    c.consume({**base, "base_url": "b"})
    c.consume({**base, "model": ""})
    c.consume(base)
    result = c.snapshot()
    assert result["status"] == "limited"
    assert result["total_rows"] == 4 and result["grouped_rows"] == 2
    assert result["omitted_rows"] == result["unidentified_rows"] == 1
    assert len(result["groups"]) == 1


def test_quality_real_http_counts_recovery_and_no_private_identity(tmp_path):
    from czjLLM.utilities.processing_quality import emit_quality_event
    audit = str(tmp_path / "llm_call_audit_20261128-1.csv")
    def emit(event, code, scope, outcome, **extra):
        return emit_quality_event(audit, run_id="PRIVATE_RUN", event=event,
                                  code=code, scope=scope, outcome=outcome, **extra)
    path = emit("slice_json_validation", "JSON_SYNTAX_INVALID", "slice", "invalid",
                document_id="PRIVATE_DOC", slice_id="PRIVATE_SLICE")
    emit("slice_json_validation", "JSON_VALID", "slice", "valid",
         document_id="PRIVATE_DOC", slice_id="PRIVATE_OTHER")
    emit("slice_json_repair", "JSON_REPAIR_SUCCEEDED", "slice", "succeeded",
         document_id="PRIVATE_DOC", slice_id="PRIVATE_SLICE")
    emit("document_schema_rejected", "SCHEMA_OTHER", "document", "rejected",
         document_id="PRIVATE_DOC")
    emit("document_writeback_confirmed", "WRITEBACK_CONFIRMED", "document", "confirmed",
         document_id="PRIVATE_DOC")
    emit("worker_phase_failure", "WORKER_LLM_TIMEOUT_EXCEPTION", "run", "observed")
    client = start_web_monitor(1, 0)
    assert client is not None
    try:
        client.set_quality_event_path(path)
        deadline = time.monotonic() + 12
        while True:
            _, raw, _ = _request(client.port, "/api/v1/status")
            q = json.loads(raw)["quality"]
            if q["status"] == "observed":
                break
            assert time.monotonic() < deadline
            time.sleep(.1)
        assert q["events"] == 6
        assert q["slice_initial_invalid_pct"] == 50
        assert q["repair_success_pct"] == 100
        assert q["documents_schema_pending"] == 0
        assert q["documents_writeback_confirmed"] == 1
        assert q["document_schema_reject_pct"] == 0
        assert q["incident_codes"] == {"WORKER_LLM_TIMEOUT_EXCEPTION": 1}
        assert q["sink_readback_verified"] is False
        assert b"PRIVATE" not in raw and b"event_id" not in raw
        with path.open("ab") as fp:
            fp.write(b'{"incomplete":')
        deadline = time.monotonic() + 12
        while True:
            _, raw, _ = _request(client.port, "/api/v1/status")
            q = json.loads(raw)["quality"]
            if q["status"] == "incomplete_tail":
                break
            assert time.monotonic() < deadline
            time.sleep(.1)
        assert "events" not in q
    finally:
        client.close()


def test_quality_generation_staleness_capacity_and_missing_denominator(tmp_path, monkeypatch):
    from czjLLM.job_manager import web_quality_monitor as qm
    from czjLLM.utilities.processing_quality import QualityAccumulator
    stats = QualityAccumulator().snapshot()
    stats["quality_stream_status"] = "observed"
    view = qm.public_quality(stats)
    assert view["slice_initial_invalid_pct"] is None and view["repair_success_pct"] is None
    stats["error_codes"] = {"PRIVATE_RAW": 1}
    assert qm.public_quality(stats)["incident_codes"] == {}
    tick = [0]
    monitor = qm.WebQualityMonitor(clock=lambda: tick[0])
    path = tmp_path / "processing_quality_events_1.jsonl"
    path.write_bytes(b"{}\n")
    monitor.set_path(str(path))
    monkeypatch.setattr(qm, "MAX_SOURCE_BYTES", 1)
    monitor.refresh_once()
    assert monitor.snapshot() == {"status": "capacity_exceeded"}
    tick[0] = 9
    assert monitor.snapshot() == {"status": "stale"}
    monitor.set_path(str(tmp_path / "processing_quality_events_2.jsonl"))
    assert monitor.snapshot() == {"status": "waiting_for_quality"}


def test_web_repair_analysis_run_coverage_and_recent_sample_scope():
    from czjLLM.job_manager.web_repair_analysis import project_repair_analysis
    from czjLLM.utilities.processing_quality import QualityAccumulator
    from uuid import uuid4

    acc = QualityAccumulator()
    syntax = "JSON_REPAIR_SYNTAX_CANDIDATE"
    large = "JSON_REPAIR_LARGE_CHANGE"
    tail = "JSON_REPAIR_TAIL_CANDIDATE"
    unknown = "JSON_REPAIR_COMPARISON_UNAVAILABLE"
    def record(code=None, similarity=0):
        event = {"schema_version": 1, "event_id": uuid4().hex,
                 "event": "slice_json_repair", "code": "JSON_REPAIR_SUCCEEDED",
                 "scope": "slice", "outcome": "succeeded",
                 "document_id": "PRIVATE_DOCUMENT", "slice_id": "PRIVATE_SLICE",
                 "run_id": "PRIVATE_RUN"}
        if code:
            event["detail"] = {"repair_class": code, "error_kind": "EXPECTED_DELIMITER",
                "original_chars": 100, "repaired_chars": 90, "common_prefix_chars": 10,
                "common_suffix_chars": 10, "same_literal_pct": similarity,
                "before_key_patterns": 4, "after_key_patterns": 3, "error_pos_pct": 80}
        assert acc.add(event)
    record()
    for _ in range(51):
        record(syntax, 100)
    record(large, 0)
    record(tail)
    record(unknown)
    result = project_repair_analysis(acc.snapshot())
    assert result["successful_repairs"] == 55
    assert result["classified_rows"] == 54 and result["unreported_rows"] == 1
    assert result["comparable_rows"] == 53
    assert result["categories"][syntax] == 51
    assert result["recent"]["count"] == 50
    assert result["recent"]["categories"][syntax] == 47
    assert result["recent"]["metrics"]["same_literal_pct"]["count"] == 48
    assert result["recent"]["metrics"]["same_literal_pct"]["min"] == 0
    assert result["recent"]["metrics"]["length_delta_chars"]["count"] == 49
    assert result["recent"]["metrics"]["length_delta_chars"]["p50"] == -10
    assert result["recent"]["metrics"]["key_pattern_delta"]["p50"] == -1
    assert result["semantic_preservation_verified"] is False
    assert "PRIVATE" not in json.dumps(result)
    bad = acc.snapshot()
    bad["repair_analysis_categories"][syntax] = 999
    assert project_repair_analysis(bad) == {"status": "unverified"}


def test_web_repair_analysis_missing_comparison_and_real_http(tmp_path):
    from czjLLM.utilities.processing_quality import emit_quality_event
    from czjLLM.utilities.json_repair_analysis import analyze_json_repair
    from czjLLM.job_manager.web_repair_analysis import project_repair_analysis
    from czjLLM.utilities.processing_quality import QualityAccumulator
    stats = QualityAccumulator().snapshot()
    empty = project_repair_analysis(stats)
    assert empty["status"] == "no_comparison"
    assert empty["classification_coverage_pct"] is None
    original, repaired = '{"a":1 "b":2}', '{"a":1,"b":2}'
    try:
        json.loads(original)
    except json.JSONDecodeError as error:
        code, detail = analyze_json_repair(original, repaired, error)
    detail["repair_class"] = code
    path = emit_quality_event(str(tmp_path / "llm_call_audit_20261128-2.csv"),
        run_id="PRIVATE_RUN", event="slice_json_repair", scope="slice",
        code="JSON_REPAIR_SUCCEEDED", outcome="succeeded", detail=detail,
        document_id="PRIVATE_DOCUMENT", slice_id="PRIVATE_SLICE")
    client = start_web_monitor(1, 0)
    assert client is not None
    try:
        client.set_quality_event_path(path)
        deadline = time.monotonic() + 12
        while True:
            _, raw, _ = _request(client.port, "/api/v1/status")
            q = json.loads(raw)["quality"]
            if q["status"] == "observed":
                break
            assert time.monotonic() < deadline
            time.sleep(.1)
        a = q["repair_analysis"]
        assert a["classified_rows"] == 1 and a["classification_coverage_pct"] == 100
        assert a["categories"][code] == 1
        assert a["recent"]["metrics"]["same_literal_pct"]["p50"] == 100
        assert b"PRIVATE" not in raw and b"event_hint" not in raw
    finally:
        client.close()
