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
