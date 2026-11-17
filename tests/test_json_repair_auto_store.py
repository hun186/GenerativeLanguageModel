"""Disposable cross-platform lifecycle and private project-cache tests (no ES/LLM)."""
from __future__ import annotations

import os
from pathlib import Path
import time
from uuid import uuid4

import pytest

import czjLLM.utilities.json_repair_auto_store as auto
import czjLLM.utilities.json_repair_private_capture as cap


def _local_project(monkeypatch, tmp_path):
    monkeypatch.setattr(auto, "PROJECT_ROOT", tmp_path)
    if os.name != "nt":
        # GitHub Linux's disposable checkout may run on an overlay filesystem.
        # Inject the allowlisted local topology ONLY for private fixture tests.
        monkeypatch.setattr(cap, "_posix_local_filesystem", lambda *_a, **_kw: True)
    return tmp_path


def test_default_private_cache_follows_checkout_not_cwd(monkeypatch, tmp_path):
    project = _local_project(monkeypatch, tmp_path / "checkout")
    project.mkdir()
    elsewhere = tmp_path / "other"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    monkeypatch.delenv(cap.ROOT_ENV, raising=False)
    monkeypatch.delenv(cap.ENABLE_ENV, raising=False)
    assert cap.capture_enabled() is True
    directory = cap.configured_private_root()
    assert directory == project / ".runtime-private" / "json_repair"
    assert directory.is_dir() and directory.parent.is_dir()
    if os.name != "nt":
        assert directory.stat().st_mode & 0o077 == 0
        assert directory.parent.stat().st_mode & 0o077 == 0
    else:
        user_sid = auto._win_current_user_sid()
        assert auto._win_private_acl(directory, user_sid)
        assert auto._win_private_acl(directory.parent, user_sid)
    item = uuid4().hex
    assert cap.write_private_repair(directory, "test-win-linux", item, "PRE", "POST")
    assert cap.read_private_repair(directory, "test-win-linux", item) == {
        "original": "PRE", "repaired": "POST",
    }
    assert cap.clear_private_run(directory, "test-win-linux",
                                 "DELETE_PRIVATE_JSON_REPAIRS") == 1


def test_optout_never_enables_new_capture(monkeypatch):
    monkeypatch.setenv(cap.ENABLE_ENV, "0")
    assert cap.capture_enabled() is False
    monkeypatch.setenv(cap.ENABLE_ENV, "off")
    assert cap.capture_enabled() is False
    monkeypatch.delenv(cap.ENABLE_ENV, raising=False)
    assert cap.capture_enabled() is True


def test_unverified_volume_fails_closed_without_building_cache(monkeypatch, tmp_path):
    project = _local_project(monkeypatch, tmp_path / "checkout")
    project.mkdir()
    monkeypatch.delenv(cap.ROOT_ENV, raising=False)
    if os.name == "nt":
        monkeypatch.setattr(auto, "_win_volume_is_ntfs", lambda _p: False)
    else:
        monkeypatch.setattr(cap, "_posix_local_filesystem", lambda *_a, **_kw: False)
    with pytest.raises(ValueError):
        cap.configured_private_root()
    assert not (project / ".runtime-private").exists()


@pytest.mark.skipif(os.name == "nt", reason="portable POSIX chmod contract")
def test_existing_broad_directory_is_refused_without_chmod(monkeypatch, tmp_path):
    project = _local_project(monkeypatch, tmp_path / "checkout")
    private = project / ".runtime-private"
    private.mkdir(parents=True, mode=0o755)
    private.chmod(0o755)
    monkeypatch.delenv(cap.ROOT_ENV, raising=False)
    with pytest.raises(ValueError, match="PRIVATE_AUTO_DIRECTORY_PERMISSIONS"):
        cap.configured_private_root()
    assert private.stat().st_mode & 0o777 == 0o755
    assert not (private / "json_repair").exists()


def test_expiry_and_read_refusal_preserve_regular_quality_logs(monkeypatch, tmp_path):
    if os.name != "nt":
        monkeypatch.setattr(cap, "_posix_local_filesystem", lambda *_a, **_kw: True)
    root = tmp_path / "private"
    root.mkdir(mode=0o700)
    if os.name != "nt":
        root.chmod(0o700)
    event = uuid4().hex
    cap.write_private_repair(root, "run-expire", event, "PRIVATE BEFORE", "PRIVATE AFTER")
    run = next(x for x in root.iterdir() if x.is_dir())
    target = next(x for x in run.iterdir() if x.name.startswith("r-"))
    old = time.time() - cap.SNAPSHOT_TTL_SECONDS - 20
    os.utime(target, (old, old))
    with pytest.raises(ValueError, match="PRIVATE_SNAPSHOT_EXPIRED"):
        cap.read_private_repair(root, "run-expire", event)
    preserved = tmp_path / "processing_quality_events_run.jsonl"
    preserved.write_text("synthetic metrics only\n", encoding="utf-8")
    assert cap.prune_expired_private_captures(root) == 0
    assert not target.exists()
    assert not list(root.glob("run-*"))  # retire old empty Run metadata too
    assert preserved.read_text(encoding="utf-8") == "synthetic metrics only\n"


def test_global_budget_blocks_additional_run_without_plaintext(monkeypatch, tmp_path):
    if os.name != "nt":
        monkeypatch.setattr(cap, "_posix_local_filesystem", lambda *_a, **_kw: True)
    root = tmp_path / "private"
    root.mkdir(mode=0o700)
    if os.name != "nt":
        root.chmod(0o700)
    monkeypatch.setattr(cap, "MAX_TOTAL_BYTES", 400)
    cap.write_private_repair(root, "one", uuid4().hex, "X" * 80, "Y" * 80)
    with pytest.raises(ValueError, match="PRIVATE_TOTAL_BYTES_BUDGET"):
        cap.write_private_repair(root, "two", uuid4().hex, "A" * 80, "B" * 80)
    assert len(list(root.rglob("r-*.json"))) == 1


def test_unknown_file_prevents_prune_and_write(monkeypatch, tmp_path):
    if os.name != "nt":
        monkeypatch.setattr(cap, "_posix_local_filesystem", lambda *_a, **_kw: True)
    root = tmp_path / "private"
    root.mkdir(mode=0o700)
    if os.name != "nt":
        root.chmod(0o700)
    unknown = root / "DO_NOT_REMOVE.txt"
    unknown.write_text("untouched", encoding="utf-8")
    with pytest.raises(ValueError, match="UNKNOWN_PRIVATE_ARTIFACT"):
        cap.prune_expired_private_captures(root)
    with pytest.raises(ValueError, match="UNKNOWN_PRIVATE_ARTIFACT"):
        cap.write_private_repair(root, "x", uuid4().hex, "before", "after")
    assert unknown.read_text(encoding="utf-8") == "untouched"


def test_gui_has_explicit_auto_cache_status_and_expiry_message():
    gui = (Path(__file__).resolve().parents[1] /
           "czjLLM/job_manager/json_repair_review_gui.py").read_text(encoding="utf-8")
    assert "prune_expired_private_captures(cache_root)" in gui
    assert "72 小時" in gui
    assert "read_private_repair(" in gui
    assert "show_private_json_diff(win" in gui


def test_folder_budget_rejects_extra_run_then_recovers_after_expiry(monkeypatch, tmp_path):
    if os.name != "nt":
        monkeypatch.setattr(cap, "_posix_local_filesystem", lambda *_a, **_kw: True)
    root = tmp_path / "private"
    root.mkdir(mode=0o700)
    if os.name != "nt":
        root.chmod(0o700)
    monkeypatch.setattr(cap, "MAX_RUN_FOLDERS", 1)
    first = uuid4().hex
    cap.write_private_repair(root, "run-a", first, "before-a", "after-a")
    with pytest.raises(ValueError, match="PRIVATE_TOTAL_FOLDER_BUDGET"):
        cap.write_private_repair(root, "run-b", uuid4().hex, "before-b", "after-b")
    old_file = next(root.rglob("r-*.json"))
    before = time.time() - cap.SNAPSHOT_TTL_SECONDS - 15
    os.utime(old_file, (before, before))
    # Root-wide maintenance removes the old file AND empty run folder.
    assert cap.prune_expired_private_captures(root) == 0
    assert not list(root.glob("run-*"))
    second = uuid4().hex
    assert cap.write_private_repair(root, "run-b", second, "before-b", "after-b")
    assert cap.read_private_repair(root, "run-b", second)["repaired"] == "after-b"


def test_launch_housekeeping_honors_optout_and_fail_closed_volume(monkeypatch, tmp_path):
    project = _local_project(monkeypatch, tmp_path / "checkout")
    project.mkdir()
    monkeypatch.delenv(cap.ROOT_ENV, raising=False)
    monkeypatch.setenv(cap.ENABLE_ENV, "0")
    assert cap.startup_private_capture_maintenance() == "DISABLED"
    assert not (project / ".runtime-private").exists()
    monkeypatch.delenv(cap.ENABLE_ENV, raising=False)
    if os.name == "nt":
        monkeypatch.setattr(auto, "_win_volume_is_ntfs", lambda _p: False)
    else:
        monkeypatch.setattr(cap, "_posix_local_filesystem", lambda *_a, **_kw: False)
    assert cap.startup_private_capture_maintenance() == "UNAVAILABLE"
    assert not (project / ".runtime-private").exists()


def test_main_batch_entry_invokes_cache_maintenance_before_mode_dispatch():
    entry = (Path(__file__).resolve().parents[1] /
             "czjLLM/czjLLM_TextProcessing.py").read_text(encoding="utf-8")
    assert 'startup_private_capture_maintenance()' in entry
    assert entry.index('startup_private_capture_maintenance()') < entry.index(
        '    # 模式選擇')


def test_disabled_capture_still_expires_old_plaintext_on_headless_launch(
    monkeypatch, tmp_path,
):
    project = _local_project(monkeypatch, tmp_path / "checkout")
    project.mkdir()
    monkeypatch.delenv(cap.ROOT_ENV, raising=False)
    monkeypatch.delenv(cap.ENABLE_ENV, raising=False)
    root = cap.configured_private_root()
    event = uuid4().hex
    cap.write_private_repair(root, "run-before-optout", event, "SECRET", "REPAIRED")
    stale = next(root.rglob("r-*.json"))
    old = time.time() - cap.SNAPSHOT_TTL_SECONDS - 30
    os.utime(stale, (old, old))
    monkeypatch.setenv(cap.ENABLE_ENV, "0")
    assert cap.startup_private_capture_maintenance() == "DISABLED"
    assert not stale.exists()
    assert not list(root.glob("run-*"))
