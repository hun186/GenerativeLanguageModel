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
