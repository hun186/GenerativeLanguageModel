"""Windows native directory enumeration and gated CLI — synthetic + NTFS tests."""
import json
import os
from pathlib import Path
import struct
import subprocess
import sys

import pytest

from scripts import inspect_queue_recovery_state as inspect
from scripts import queue_win32_native_enumeration as native
from scripts import queue_win32_handle_identity as win


def _record(name="slice.txt", *, attributes=0):
    encoded = name.encode("utf-16-le")
    buf = bytearray(64 + len(encoded))
    struct.pack_into("<II", buf, 56, attributes, len(encoded))
    buf[64:] = encoded
    return bytes(buf)


def test_decode_one_native_record_without_content_or_path_logging():
    record = native._decode_directory_record(_record("繁體中文.txt"))
    assert record.name == "繁體中文.txt"
    assert record.attributes == 0


@pytest.mark.parametrize("mutate", [
    lambda b: b[:63],
    lambda b: struct.pack_into("<I", b, 0, 72) or b,
    lambda b: struct.pack_into("<I", b, 60, 0) or b,
    lambda b: struct.pack_into("<I", b, 60, 3) or b,
    lambda b: struct.pack_into("<I", b, 60, 5000) or b,
])
def test_malformed_native_record_refuses_fixed_code(mutate):
    b = bytearray(_record("secret.txt"))
    with pytest.raises(win.UnsafeWindowsIdentity, match="WINDOWS_DIRECTORY_RECORD_INVALID"):
        native._decode_directory_record(bytes(mutate(b)))


def test_native_record_with_lone_surrogate_fails_closed():
    b = bytearray(64)
    struct.pack_into("<II", b, 56, 0, 2)
    b.extend(b"\x00\xd8")  # U+D800, not valid scalar value
    with pytest.raises(win.UnsafeWindowsIdentity, match="WINDOWS_DIRECTORY_NAME_UNSAFE"):
        native._decode_directory_record(bytes(b))


class FakeNative:
    """Only synthetic API; no actual filesystem calls or source content."""
    def __init__(self, nodes):
        self.nodes = nodes
        self.opened = []
        self.closed = []

    def open_drive_root(self, drive):
        assert drive == "C:"
        root = ()
        self.opened.append(root)
        return root

    def open_child(self, parent, name, *, directory):
        item = parent + (name,)
        if item not in self.nodes:
            raise win.UnsafeWindowsIdentity("WINDOWS_CHILD_OPEN_FAILED")
        if self.nodes[item]["directory"] != directory:
            raise win.UnsafeWindowsIdentity("WINDOWS_ENTRY_TYPE_MISMATCH")
        self.opened.append(item)
        return item

    def identity(self, token):
        node = self.nodes[token]
        return win.HandleIdentity(42, node["file_id"], node["links"],
                                  node["directory"])

    def entries(self, token):
        for name in self.nodes[token].get("entries", []):
            child = token + (name,)
            node = self.nodes[child]
            yield native._Entry(
                name, (win.FILE_ATTRIBUTE_DIRECTORY if node["directory"] else 0)
                | (win.FILE_ATTRIBUTE_REPARSE_POINT if node.get("reparse") else 0)
            )

    def close(self, token):
        self.closed.append(token)


def _nodes():
    return {
        (): {"directory": True, "file_id": bytes([1] * 16), "links": 1},
        ("item",): {"directory": True, "file_id": bytes([2] * 16),
                    "links": 1, "entries": ["TODO", "RUNNING", "Success",
                                            ".success-publish-staging"]},
        ("item", "TODO"): {"directory": True, "file_id": bytes([3] * 16),
                           "links": 1, "entries": ["Root.txt"]},
        ("item", "TODO", "Root.txt"): {
            "directory": False, "file_id": bytes([7] * 16), "links": 2
        },
        ("item", "RUNNING"): {"directory": True, "file_id": bytes([4] * 16),
                              "links": 1, "entries": ["root.txt"]},
        ("item", "RUNNING", "root.txt"): {
            "directory": False, "file_id": bytes([7] * 16), "links": 2
        },
        ("item", "Success"): {"directory": True, "file_id": bytes([5] * 16),
                              "links": 1, "entries": []},
        ("item", ".success-publish-staging"): {
            "directory": True, "file_id": bytes([6] * 16), "links": 1,
            "entries": [".success-deadbeef.tmp"]
        },
        ("item", ".success-publish-staging", ".success-deadbeef.tmp"): {
            "directory": False, "file_id": bytes([9] * 16), "links": 1
        },
    }


def test_synthetic_native_scan_reuses_inode_identity_without_leaking_names():
    fake = FakeNative(_nodes())
    roles, unsafe, unknown = native._scan_roles_with_api(fake, r"C:\item", 100)
    assert unsafe == unknown == 0
    assert len(roles["TODO"]) == len(roles["RUNNING"]) == 1
    assert roles["TODO"][0][1] == roles["RUNNING"][0][1]
    assert roles["TODO"][0][2] == 2
    assert len(roles[".success-publish-staging"]) == 1
    assert set(fake.opened) == set(fake.closed)
    assert fake.closed[-1] == ()


def test_synthetic_native_directory_budget_stops_before_opening_files():
    nodes = _nodes()
    fake = FakeNative(nodes)
    with pytest.raises(win.UnsafeWindowsIdentity, match="WINDOWS_SCAN_LIMIT"):
        native._scan_roles_with_api(fake, r"C:\item", 2)
    assert set(fake.opened) == set(fake.closed)


def test_synthetic_native_scan_refuses_reparse_children_without_opening_them():
    nodes = _nodes()
    nodes[("item", "TODO")]["entries"] = ["junction"]
    nodes[("item", "TODO", "junction")] = {
        "directory": True, "file_id": bytes([8] * 16),
        "links": 1, "reparse": True
    }
    fake = FakeNative(nodes)
    roles, unsafe, unknown = native._scan_roles_with_api(fake, r"C:\item", 100)
    assert unsafe == 1 and unknown == 0
    assert ("item", "TODO", "junction") not in fake.opened
    assert not roles["TODO"]
    assert set(fake.opened) == set(fake.closed)


def test_synthetic_native_scan_refuses_root_role_junction():
    nodes = _nodes()
    nodes[("item", "TODO")]["reparse"] = True
    fake = FakeNative(nodes)
    with pytest.raises(win.UnsafeWindowsIdentity, match="WINDOWS_ROLE_UNSAFE"):
        native._scan_roles_with_api(fake, r"C:\item", 100)
    assert set(fake.opened) == set(fake.closed)


def test_synthetic_native_scan_refuses_deep_nesting_without_handle_leaks():
    nodes = _nodes()
    nodes[("item", "TODO")]["entries"] = ["a"]
    p = ("item", "TODO")
    for i in range(native.MAX_NATIVE_DEPTH + 2):
        child = p + ("a",)
        nodes[child] = {
            "directory": True, "file_id": bytes([i % 250 + 1] * 16),
            "links": 1, "entries": ["a"]
        }
        p = child
    nodes[p]["entries"] = []
    fake = FakeNative(nodes)
    with pytest.raises(win.UnsafeWindowsIdentity, match="WINDOWS_SCAN_DEPTH_LIMIT"):
        native._scan_roles_with_api(fake, r"C:\item", 1000)
    assert set(fake.opened) == set(fake.closed)


def test_cli_windows_default_remains_unsupported(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(inspect, "_is_windows", lambda: True)
    def forbidden(*args, **kwargs):
        raise AssertionError("experimental scan invoked without explicit opt-in")
    monkeypatch.setattr(inspect, "_native_windows_snapshot", forbidden)
    monkeypatch.setattr(sys, "argv", [
        "inspect-queue", "--item-dir", str(tmp_path / "private"),
    ])
    assert inspect.main() == 2
    report = json.loads(capsys.readouterr().out)
    assert report["items"][0]["codes"] == ["UNSUPPORTED_SAFE_SCAN_PLATFORM"]


def test_cli_opt_in_windows_forces_review_even_with_no_findings(
    monkeypatch, tmp_path, capsys
):
    monkeypatch.setattr(inspect, "_is_windows", lambda: True)
    monkeypatch.setattr(inspect, "_native_windows_snapshot",
                        lambda item, limit: ({r: [] for r in inspect.ROLES}, 0, 0))
    monkeypatch.setattr(sys, "argv", [
        "inspect-queue", "--item-dir", str(tmp_path / "PRIVATE_PATH"),
        "--experimental-windows",
    ])
    assert inspect.main() == 2
    stdout = capsys.readouterr().out
    report = json.loads(stdout)
    assert report["items"][0]["scan_complete"]
    assert report["items"][0]["status"] == "review_required"
    assert report["items"][0]["codes"] == ["WINDOWS_EXPERIMENTAL_UNVERIFIED"]
    assert "PRIVATE_PATH" not in stdout


def test_cli_windows_case_insensitive_names_and_shared_file_ids(
    monkeypatch, tmp_path
):
    fake = FakeNative(_nodes())
    monkeypatch.setattr(inspect, "_is_windows", lambda: True)
    monkeypatch.setattr(inspect, "_native_windows_snapshot",
                        lambda item, limit: native._scan_roles_with_api(
                            fake, r"C:\item", limit))
    result = inspect.inspect_item(tmp_path / "private", experimental_windows=True)
    assert result["counts"]["todo_running_basename_overlaps"] == 1
    assert result["counts"]["todo_running_shared_inode_groups"] == 1
    assert result["counts"]["multiply_linked_queue_entries"] == 2
    assert result["counts"]["staging_temp_files"] == 1
    assert "WINDOWS_EXPERIMENTAL_UNVERIFIED" in result["codes"]


def test_native_windows_error_never_leaks_private_path(monkeypatch, tmp_path):
    monkeypatch.setattr(inspect, "_is_windows", lambda: True)
    def unsafe(*args, **kwargs):
        raise win.UnsafeWindowsIdentity("SECRET_USER_AND_PATH")
    monkeypatch.setattr(inspect, "_native_windows_snapshot", unsafe)
    result = inspect.inspect_item(tmp_path / "PRIVATE", experimental_windows=True)
    assert not result["scan_complete"]
    assert result["codes"] == ["INCOMPLETE_OR_UNSAFE_SCAN"]
    assert "SECRET_USER_AND_PATH" not in json.dumps(result)


@pytest.mark.skipif(os.name != "nt", reason="requires actual Windows handle enumeration")
def test_ntfs_native_todo_running_real_hardlink_detection(tmp_path):
    item = tmp_path / "item"
    todo = item / "TODO"
    running = item / "RUNNING"
    todo.mkdir(parents=True)
    running.mkdir()
    source = todo / "piece.txt"
    source.write_bytes(b"PRIVATE_BYTES_NEVER_READ")
    try:
        os.link(source, running / "piece.txt")
    except OSError:
        pytest.skip("hardlinks unavailable on operator filesystem")
    result = inspect.inspect_item(item, experimental_windows=True)
    assert result["scan_complete"]
    assert result["counts"]["todo_running_shared_inode_groups"] == 1
    assert "POSSIBLE_INTERRUPTED_LINK_MOVE" in result["codes"]
    assert result["status"] == "review_required"
    assert source.read_bytes() == b"PRIVATE_BYTES_NEVER_READ"


@pytest.mark.skipif(os.name != "nt", reason="requires actual Windows handle enumeration")
def test_ntfs_native_reparse_child_not_traversed(tmp_path):
    item = tmp_path / "item"
    todo = item / "TODO"
    todo.mkdir(parents=True)
    external = tmp_path / "external"
    external.mkdir()
    (external / "secret.txt").write_text("PRIVATE_SOURCE")
    try:
        (todo / "junction").symlink_to(external, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("native symlink creation not authorized")
    result = inspect.inspect_item(item, experimental_windows=True)
    assert result["scan_complete"]
    assert result["counts"]["unsafe_entries"] == 1
    assert result["counts"]["todo_files"] == 0
    assert result["status"] == "review_required"


def test_direct_cli_entrypoint_without_pythonpath_can_run_outside_repo(tmp_path):
    """AGENTS.md: import path compatibility is centralized in CLI startup."""
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    entrypoint = Path(inspect.__file__).resolve()
    command = [sys.executable, str(entrypoint),
               "--item-dir", str(tmp_path / "missing")]
    result = subprocess.run(
        command, cwd=tmp_path, env=env, capture_output=True, text=True,
        timeout=15,
    )
    assert result.returncode == 2
    payload = json.loads(result.stdout)
    assert payload["items"][0]["codes"] == ["INCOMPLETE_OR_UNSAFE_SCAN"]
    assert "Traceback" not in result.stderr


@pytest.mark.skipif(os.name != "nt", reason="requires real Windows native import")
def test_windows_direct_script_experimental_import_from_foreign_cwd(tmp_path):
    """Exercise ordinary 'from scripts...' imports after entrypoint path setup."""
    item = tmp_path / "item"
    (item / "TODO").mkdir(parents=True)
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    entrypoint = Path(inspect.__file__).resolve()
    result = subprocess.run(
        [sys.executable, str(entrypoint),
         "--item-dir", str(item), "--experimental-windows"],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 2
    assert "Traceback" not in result.stderr
    payload = json.loads(result.stdout)
    assert payload["items"][0]["scan_complete"]
    assert "WINDOWS_EXPERIMENTAL_UNVERIFIED" in payload["items"][0]["codes"]
