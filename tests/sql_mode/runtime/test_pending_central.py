import json
from types import SimpleNamespace

from czjLLM.prompt_pipeline import pending_central


def test_order_rows_avoids_running_until_after_cold_rows(tmp_path):
    ctx = SimpleNamespace(
        PGMSubDir=str(tmp_path),
        _pending_tgt_table="target",
        pending_running_console_enabled=True,
    )

    pending_central.mark_running(ctx, "pk-1")

    rows = [("pk-1", "hot"), ("pk-2", "cold"), ("pk-3", "cold")]

    assert pending_central.order_rows_avoiding_running(ctx, rows) == [
        ("pk-2", "cold"),
        ("pk-3", "cold"),
        ("pk-1", "hot"),
    ]


def test_mark_not_running_removes_running_state(tmp_path):
    ctx = SimpleNamespace(
        PGMSubDir=str(tmp_path),
        _pending_tgt_table="target",
        pending_running_console_enabled=True,
    )

    pending_central.mark_running(ctx, "pk-1")
    assert pending_central.is_running(ctx, "pk-1") is True

    pending_central.mark_not_running(ctx, "pk-1")

    assert pending_central.is_running(ctx, "pk-1") is False


def test_order_rows_records_adjustment_log(tmp_path):
    ctx = SimpleNamespace(
        PGMSubDir=str(tmp_path),
        _pending_tgt_table="target",
        pending_running_console_enabled=True,
    )

    pending_central.mark_running(ctx, "pk-1")
    pending_central.order_rows_avoiding_running(ctx, [("pk-1", "hot"), ("pk-2", "cold")])

    log_path = tmp_path / "logs" / "pending_running_console_adjustments.log"
    assert log_path.exists()
    assert '"event": "initial_reorder"' in log_path.read_text(encoding="utf-8")


def test_adjustment_log_uses_local_iso_timestamp(tmp_path):
    ctx = SimpleNamespace(
        PGMSubDir=str(tmp_path),
        _pending_tgt_table="target",
        pending_running_console_enabled=True,
    )

    pending_central.record_adjustment(ctx, "unit_test_event", pk="pk-1")

    log_path = tmp_path / "logs" / "pending_running_console_adjustments.log"
    rows = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    assert rows[0]["event"] == "unit_test_event"
    assert isinstance(rows[0]["ts"], str)
    assert "T" in rows[0]["ts"]
    assert "timezone" in rows[0]


def test_running_console_prunes_dead_pid(tmp_path, monkeypatch):
    ctx = SimpleNamespace(
        PGMSubDir=str(tmp_path),
        _pending_tgt_table="target",
        pending_running_console_enabled=True,
    )
    console_path = tmp_path / "logs" / "pending_running_console.json"
    console_path.parent.mkdir(parents=True, exist_ok=True)
    console_path.write_text(json.dumps({
        "version": 1,
        "running": {
            "target|pk-dead": {
                "state": "running",
                "pk": "pk-dead",
                "target": "target",
                "pid": 999999,
                "started_ts": 9999999999,
                "updated_ts": 9999999999,
            }
        },
    }), encoding="utf-8")

    def _fake_kill(pid, sig):
        raise ProcessLookupError()

    monkeypatch.setattr(pending_central.os, "kill", _fake_kill)

    assert pending_central.is_running(ctx, "pk-dead") is False
    data = json.loads(console_path.read_text(encoding="utf-8"))
    assert data["running"] == {}


def test_pid_liveness_uses_windows_api_without_os_kill(tmp_path, monkeypatch):
    calls = {"kill": 0, "open": 0}

    class _Kernel32:
        def OpenProcess(self, _access, _inherit, pid):
            calls["open"] += 1
            assert pid == 12345
            return 100

        def GetLastError(self):
            return 0

        def GetExitCodeProcess(self, _handle, exit_code_ptr):
            exit_code_ptr._obj.value = 259
            return 1

        def CloseHandle(self, _handle):
            return 1

    class _Windll:
        kernel32 = _Kernel32()

    def _unexpected_kill(_pid, _sig):
        calls["kill"] += 1
        raise SystemError("os.kill should not be used on Windows")

    monkeypatch.setattr(pending_central.os, "name", "nt")
    monkeypatch.setattr(pending_central.os, "kill", _unexpected_kill)
    monkeypatch.setattr(pending_central.ctypes, "windll", _Windll(), raising=False)

    assert pending_central._pid_is_alive(12345) is True
    assert calls == {"kill": 0, "open": 1}


def test_pid_liveness_windows_invalid_parameter_means_dead(monkeypatch):
    class _Kernel32:
        def OpenProcess(self, _access, _inherit, _pid):
            return 0

        def GetLastError(self):
            return 87

    class _Windll:
        kernel32 = _Kernel32()

    monkeypatch.setattr(pending_central.os, "name", "nt")
    monkeypatch.setattr(pending_central.ctypes, "windll", _Windll(), raising=False)

    assert pending_central._pid_is_alive(12345) is False


def test_mark_not_running_retains_recent_finished_for_one_hour_by_default(tmp_path):
    ctx = SimpleNamespace(
        PGMSubDir=str(tmp_path),
        _pending_tgt_table="target",
        pending_running_console_enabled=True,
    )

    pending_central.mark_running(ctx, "pk-1")
    pending_central.mark_not_running(ctx, "pk-1", state="completed")

    console_path = tmp_path / "logs" / "pending_running_console.json"
    data = json.loads(console_path.read_text(encoding="utf-8"))
    assert "target|pk-1" in data["last_finished"]
    assert data["last_finished"]["target|pk-1"]["state"] == "completed"


def test_last_finished_prunes_older_than_retention(tmp_path):
    ctx = SimpleNamespace(
        PGMSubDir=str(tmp_path),
        _pending_tgt_table="target",
        pending_running_console_enabled=True,
        pending_running_console_finished_retention_seconds=3600,
    )
    console_path = tmp_path / "logs" / "pending_running_console.json"
    console_path.parent.mkdir(parents=True, exist_ok=True)
    console_path.write_text(json.dumps({
        "version": 1,
        "running": {},
        "last_finished": {
            "target|old": {"state": "completed", "pk": "old", "updated_ts": 1},
            "target|recent": {
                "state": "completed",
                "pk": "recent",
                "updated_ts": pending_central.time.time(),
            },
        },
    }), encoding="utf-8")

    pending_central.mark_running(ctx, "pk-new")

    data = json.loads(console_path.read_text(encoding="utf-8"))
    assert "target|old" not in data["last_finished"]
    assert "target|recent" in data["last_finished"]


def test_corrupt_console_file_is_rebuilt(tmp_path):
    ctx = SimpleNamespace(
        PGMSubDir=str(tmp_path),
        _pending_tgt_table="target",
        pending_running_console_enabled=True,
    )
    console_path = tmp_path / "logs" / "pending_running_console.json"
    console_path.parent.mkdir(parents=True, exist_ok=True)
    console_path.write_text("{not-valid-json", encoding="utf-8")

    pending_central.mark_running(ctx, "pk-1")

    data = json.loads(console_path.read_text(encoding="utf-8"))
    assert data["running"]["target|pk-1"]["state"] == "running"
