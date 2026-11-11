"""Disposable-only tests for opt-in sensitive JSON repair before/after snapshots."""
import json
import os
from pathlib import Path
import stat
from uuid import uuid4

import pytest

from czjLLM.utilities.json_repair_private_capture import (
    MAX_FILE_BYTES, capture_enabled, configured_private_root,
    write_private_repair, read_private_repair, clear_private_run,
)
from czjLLM.utilities.processing_quality import (
    emit_quality_event, quality_event_path,
)
from czjLLM.utilities.processing_quality_run_reader import QualityRunTailReader


def root(tmp_path):
    private = tmp_path / "secret-only"
    private.mkdir(mode=0o700)
    if os.name != "nt":
        private.chmod(0o700)
    return private


def test_disabled_by_default_and_explicit_configuration(monkeypatch, tmp_path):
    monkeypatch.delenv("CZJLLM_JSON_REPAIR_CAPTURE", raising=False)
    monkeypatch.delenv("CZJLLM_JSON_REPAIR_PRIVATE_DIR", raising=False)
    assert capture_enabled() is False
    assert configured_private_root() is None
    monkeypatch.setenv("CZJLLM_JSON_REPAIR_CAPTURE", "0")
    monkeypatch.setenv("CZJLLM_JSON_REPAIR_PRIVATE_DIR", str(tmp_path))
    assert capture_enabled() is False
    assert configured_private_root() == tmp_path


def test_exact_run_event_roundtrip_and_confirmed_manual_clear(tmp_path):
    folder = root(tmp_path)
    event_id = uuid4().hex
    original = '{"secret":"PRIVATE_REPORT" "value":1}'
    repaired = '{"secret":"PRIVATE_REPORT","value":1}'
    assert write_private_repair(folder, "run-a", event_id, original, repaired)
    assert read_private_repair(folder, "run-a", event_id) == {
        "original": original, "repaired": repaired,
    }
    with pytest.raises((ValueError, FileNotFoundError)):
        read_private_repair(folder, "run-b", event_id)
    with pytest.raises(ValueError, match="CONFIRMATION_REQUIRED"):
        clear_private_run(folder, "run-a", "NO")
    assert read_private_repair(folder, "run-a", event_id)["original"] == original
    assert clear_private_run(folder, "run-a", "DELETE_PRIVATE_JSON_REPAIRS") == 1
    with pytest.raises(FileNotFoundError):
        read_private_repair(folder, "run-a", event_id)
    assert "PRIVATE_REPORT" not in json.dumps(
        {"status": "deleted", "event_id": event_id},
    )


def test_exact_event_ids_disambiguate_same_slice_basename(tmp_path):
    folder = root(tmp_path)
    aid = uuid4().hex
    bid = uuid4().hex
    write_private_repair(folder, "run-same", aid, "A original", "A repaired")
    write_private_repair(folder, "run-same", bid, "B original", "B repaired")
    assert read_private_repair(folder, "run-same", aid)["original"] == "A original"
    assert read_private_repair(folder, "run-same", bid)["original"] == "B original"
    with pytest.raises(FileExistsError):
        write_private_repair(folder, "run-same", aid, "ATTACK", "ATTACK")
    assert read_private_repair(folder, "run-same", aid)["original"] == "A original"


@pytest.mark.parametrize("bad", [
    "", "some/path", "../../escape", "0123456789" * 3, "g" * 32,
])
def test_bad_event_ids_are_rejected(tmp_path, bad):
    with pytest.raises(ValueError):
        write_private_repair(root(tmp_path), "run-a", bad, "before", "after")


def test_symlink_reparse_and_private_permissions_fail_closed(tmp_path):
    private = root(tmp_path)
    alias = tmp_path / "private-link"
    try:
        alias.symlink_to(private, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable")
    with pytest.raises((ValueError, OSError)):
        write_private_repair(alias, "run-a", uuid4().hex, "x", "y")
    if os.name != "nt":
        private.chmod(0o755)
        with pytest.raises(ValueError, match="PRIVATE_DIR_PERMISSIONS"):
            write_private_repair(private, "run-a", uuid4().hex, "x", "y")


def test_tampered_snapshot_bad_json_and_links_are_rejected(tmp_path):
    private = root(tmp_path)
    event_id = uuid4().hex
    write_private_repair(private, "run-a", event_id, "confidential", "repaired")
    run_folder = next(x for x in private.iterdir() if x.is_dir())
    path = next(x for x in run_folder.iterdir() if x.name.endswith(".json"))
    path.write_text("corrupted", encoding="utf-8")
    with pytest.raises(ValueError):
        read_private_repair(private, "run-a", event_id)
    path.write_bytes(b"x" * (MAX_FILE_BYTES + 1))
    with pytest.raises(ValueError, match="PRIVATE_READ_BUDGET"):
        read_private_repair(private, "run-a", event_id)


def test_existing_hardlink_is_not_safe_to_read_or_clear(tmp_path):
    if not hasattr(os, "link"):
        pytest.skip("no hardlink support")
    private = root(tmp_path)
    event_id = uuid4().hex
    write_private_repair(private, "run-a", event_id, "1", "2")
    run_folder = next(x for x in private.iterdir() if x.is_dir())
    path = next(x for x in run_folder.iterdir() if x.name.endswith(".json"))
    alias = tmp_path / "same-inode-link.json"
    try:
        os.link(path, alias)
    except OSError:
        pytest.skip("hardlink unavailable")
    with pytest.raises(ValueError, match="UNSAFE_LINK_COUNT"):
        read_private_repair(private, "run-a", event_id)
    with pytest.raises(ValueError, match="UNSAFE_LINK_COUNT"):
        clear_private_run(private, "run-a", "DELETE_PRIVATE_JSON_REPAIRS")


def test_bounded_limits_without_allocating_large_real_data(monkeypatch, tmp_path):
    import czjLLM.utilities.json_repair_private_capture as cap
    private = root(tmp_path)
    monkeypatch.setattr(cap, "MAX_CASES_PER_RUN", 2)
    write_private_repair(private, "run-a", uuid4().hex, "v", "x")
    write_private_repair(private, "run-a", uuid4().hex, "v", "y")
    with pytest.raises(ValueError, match="PRIVATE_RUN_BUDGET"):
        write_private_repair(private, "run-a", uuid4().hex, "v", "z")
    with pytest.raises(ValueError, match="PRIVATE_TEXT_OVER_LIMIT"):
        write_private_repair(private, "run-b", uuid4().hex, "a" * 80001, "x")


def test_quality_event_exact_id_join_without_raw_payload(tmp_path):
    audit = tmp_path / "llm_call_audit_run.csv"
    event_id = uuid4().hex
    raw = "PRIVATE-ORIGINAL-SECRET"
    repaired = "PRIVATE-REPAIRED-SECRET"
    quality = emit_quality_event(
        str(audit), run_id="private-run",
        event="slice_json_repair", code="JSON_REPAIR_SUCCEEDED",
        scope="slice", outcome="recovered", slice_id="same.txt",
        event_id=event_id,
    )
    assert quality is not None
    stream = quality_event_path(str(audit))
    text = stream.read_text(encoding="utf-8")
    assert event_id in text
    assert raw not in text and repaired not in text
    reader = QualityRunTailReader(str(stream))
    _changed, stats = reader.poll()
    # Without a statistical comparison detail the quality event still counts
    # as a repair success, but not a categorized before/after observation.
    assert stats["repair_succeeded"] == 1
    assert stats["repair_analysis_count"] == 0


def test_worker_with_opt_in_captures_exact_pair_but_not_quality_jsonl(
    monkeypatch, tmp_path, capsys,
):
    import czjLLM.prompt_pipeline.pipeline_controller as pc

    private = root(tmp_path)
    monkeypatch.setenv("CZJLLM_JSON_REPAIR_CAPTURE", "1")
    monkeypatch.setenv("CZJLLM_JSON_REPAIR_PRIVATE_DIR", str(private))
    before = '{"secret":"PRIVATE_X" "v":2}'
    after = '{"secret":"PRIVATE_X","v":2}'
    monkeypatch.setattr(pc, "json_format_caller", lambda **_: after)
    prompt = tmp_path / "RUNNING" / "same.txt"
    prompt.parent.mkdir()
    prompt.write_text("synthetic-only", encoding="utf-8")
    audit = tmp_path / "llm_call_audit_run.csv"
    worker = pc.PromptAPIPipeline(
        task="to json", content="", promptFile=str(prompt),
        model_spec={"model_name": "dummy-model", "base_url": ["http://invalid.local"]},
        audit_run_id="private-test-run", audit_path=str(audit),
    )
    monkeypatch.setattr(worker, "extract_MainFileName_and_input_text",
                        lambda: ("", "", ""))
    retry, result = worker.handle_json_output(before)
    assert retry == [] and result == after
    output = capsys.readouterr().out
    assert "PRIVATE_X" not in output
    event_lines = quality_event_path(str(audit)).read_text(encoding="utf-8")
    assert "PRIVATE_X" not in event_lines
    events = [json.loads(x) for x in event_lines.splitlines()]
    repair = next(x for x in events if x["event"] == "slice_json_repair")
    pair = read_private_repair(private, "private-test-run", repair["event_id"])
    assert pair == {"original": before, "repaired": after}


def test_private_view_wiring_remains_explicit_and_does_not_embed_raw_in_quality():
    text = Path("czjLLM/job_manager/json_repair_review_gui.py").read_text(encoding="utf-8")
    assert "read_private_repair(" in text
    assert "messagebox.askyesno(" in text
    assert "DELETE_PRIVATE_JSON_REPAIRS" in text
    assert "show_private_json_diff(win" in text
    assert "case.get(\"event_id\"" in text


def test_windows_fixed_volume_classifier_fails_closed_for_remote_or_unknown():
    from czjLLM.utilities.json_repair_private_capture import _windows_local_fixed_drive
    assert _windows_local_fixed_drive("C:", drive_type=lambda _: 3)
    assert not _windows_local_fixed_drive("Z:", drive_type=lambda _: 4)
    assert not _windows_local_fixed_drive("X:", drive_type=lambda _: 0)
    assert not _windows_local_fixed_drive("X:", drive_type=lambda _: 2)
    assert not _windows_local_fixed_drive(r"\\server\share", drive_type=lambda _: 3)
    assert not _windows_local_fixed_drive("not-a-drive", drive_type=lambda _: 3)
    assert not _windows_local_fixed_drive("Q:", drive_type=lambda _: (_ for _ in ()).throw(OSError("bad")))


def test_lock_symlink_is_rejected_without_mutating_external_target(tmp_path, monkeypatch):
    import czjLLM.utilities.json_repair_private_capture as cap

    private = root(tmp_path)
    event_id = uuid4().hex
    run_id = "run-lock-symlink"
    digest = cap._validate_run_id(run_id)
    folder = cap._run_dir(cap._root(private), digest)
    target = tmp_path / "DO_NOT_WRITE_OUTSIDE.txt"
    # Empty external target forces the pre-fix implementation to write b"0",
    # so the regression detects actual unintended mutation, not only refusal.
    target.write_bytes(b"")
    lock = folder / ".capture.lock"
    try:
        lock.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("symlink not available")

    # Simulate Windows Python where O_NOFOLLOW is absent; pathname validation
    # must reject BEFORE the lockfile initialization writes b"0".
    monkeypatch.setattr(cap.os, "O_NOFOLLOW", 0, raising=False)
    with pytest.raises(ValueError, match="UNSAFE_FILE_TYPE"):
        cap.write_private_repair(private, run_id, event_id, "secret", "fixed")
    assert target.read_bytes() == b""
    assert not list(folder.glob("r-*.json"))


def test_fsync_failure_closes_file_before_removing_partial_snapshot(tmp_path, monkeypatch):
    import czjLLM.utilities.json_repair_private_capture as cap

    private = root(tmp_path)
    event_id = uuid4().hex
    original_fsync = cap.os.fsync

    def injected_fsync(fd):
        raise OSError("simulated disk error; PRIVATE_PAYLOAD")

    monkeypatch.setattr(cap.os, "fsync", injected_fsync)
    with pytest.raises(OSError):
        cap.write_private_repair(private, "run-partial", event_id,
                                 "PRIVATE_PAYLOAD", "PRIVATE_RESULT")
    monkeypatch.setattr(cap.os, "fsync", original_fsync)
    folder = next(p for p in private.iterdir() if p.is_dir())
    assert not list(folder.glob("r-*.json"))
    # Removing a file after its CRT descriptor is closed is especially
    # important on Windows, which forbids unlink of many open handles.


def test_raw_json_text_viewer_disables_clipboard_primary_auto_export():
    gui = Path("czjLLM/job_manager/json_repair_raw_diff_gui.py").read_text(encoding="utf-8")
    assert "exportselection=False" in gui
    assert 'tk.Text(frame, wrap="none"' in gui


def test_posix_mountinfo_detects_nested_remote_mounts_and_unverified_roots():
    import czjLLM.utilities.json_repair_private_capture as cap
    if os.name == "nt":
        pytest.skip("POSIX /proc mountinfo contract")
    mounts = (
        "19 0 8:1 / / rw,relatime - ext4 /dev/local rw\n"
        "20 19 0:99 / /vault rw,relatime - nfs4 remote:/vault rw\n"
        "21 19 8:2 / /work rw,relatime - xfs /dev/local2 rw\n"
    )
    assert cap._posix_local_filesystem(Path("/work/private"), mountinfo=mounts)
    assert not cap._posix_local_filesystem(Path("/vault/private"), mountinfo=mounts)
    assert not cap._posix_local_filesystem(Path("/vault/private"), mountinfo="")
    assert not cap._posix_local_filesystem(Path("/vault/private"), mountinfo="broken")
    assert not cap._posix_local_filesystem(Path("/work/private"), mountinfo=mounts.replace("xfs", "fuse.sshfs"))


def test_posix_mountinfo_parser_fails_closed_on_unknown_filesystem():
    import czjLLM.utilities.json_repair_private_capture as cap
    if os.name == "nt":
        pytest.skip("POSIX-only filesystem test")
    path = Path("/vault/private")
    for fstype in ("nfs", "nfs4", "cifs", "smb3", "fuse", "overlay", "9p", "unknown"):
        mounts = f"5 0 0:42 / / rw - {fstype} fake rw\n"
        assert not cap._posix_local_filesystem(path, mountinfo=mounts)


def test_stacked_mount_same_path_is_rejected_regardless_of_order():
    """A visible NFS mount can shadow local ext4 at the same mountpoint."""
    import czjLLM.utilities.json_repair_private_capture as cap
    if os.name == "nt":
        pytest.skip("Linux POSIX mountinfo contract")
    local = "20 19 8:1 / /vault rw,relatime - ext4 /dev/local rw\n"
    remote = "21 20 0:99 / /vault rw,relatime - nfs4 srv:/vault rw\n"
    for mounts in (local + remote, remote + local, local + local):
        assert not cap._posix_local_filesystem(Path("/vault/private"), mountinfo=mounts)
    # A more specific unambiguous mount supersedes a less-specific ancestor.
    mounts = "19 0 8:1 / / rw - ext4 /dev/local rw\n" + remote
    assert not cap._posix_local_filesystem(Path("/vault/private"), mountinfo=mounts)


@pytest.mark.skipif(os.name == "nt", reason="Linux mountinfo safety contract")
@pytest.mark.parametrize("preexisting", [True, False])
def test_nested_run_mount_rejected_before_any_private_artifact(
    monkeypatch, tmp_path, preexisting,
):
    """A local parent does not prove the child run directory is local."""
    import czjLLM.utilities.json_repair_private_capture as cap

    private = root(tmp_path)
    run_id = "nested-run-mount"
    event_id = uuid4().hex
    target = private / ("run-" + cap._validate_run_id(run_id)[:24])
    if preexisting:
        target.mkdir(mode=0o700)
    original_check = cap._posix_local_filesystem
    visited = []

    def verify_actual_destination(path, *, mountinfo=None):
        visited.append(Path(path))
        if Path(path) == target:
            return False  # Simulated NFS/CIFS mount directly on this run dir.
        return original_check(path, mountinfo=mountinfo)

    monkeypatch.setattr(cap, "_posix_local_filesystem", verify_actual_destination)
    with pytest.raises(ValueError, match="POSIX_LOCAL_FILESYSTEM_UNVERIFIED"):
        write_private_repair(private, run_id, event_id, "PRIVATE", "REPAIRED")
    assert target in visited
    assert target.is_dir()
    assert list(target.iterdir()) == []  # No lock file or plaintext snapshot.

    with pytest.raises(ValueError, match="POSIX_LOCAL_FILESYSTEM_UNVERIFIED"):
        read_private_repair(private, run_id, event_id)
    with pytest.raises(ValueError, match="POSIX_LOCAL_FILESYSTEM_UNVERIFIED"):
        clear_private_run(private, run_id, "DELETE_PRIVATE_JSON_REPAIRS")
    assert list(target.iterdir()) == []


@pytest.mark.skipif(os.name == "nt", reason="Linux mountinfo topology contract")
def test_hidden_local_child_beneath_remote_ancestor_is_not_accepted():
    """Remote ancestor overmount can hide an older, longer local child path."""
    import czjLLM.utilities.json_repair_private_capture as cap

    root = "19 0 8:1 / / rw,relatime - ext4 /dev/disk rw\\n"
    local_child = (
        "20 19 8:2 / /vault/private rw,relatime - ext4 /dev/child rw\\n"
    )
    remote_parent = (
        "21 19 0:99 / /vault rw,relatime - nfs4 srv:/vault rw\\n"
    )
    for mounts in (
        root + local_child + remote_parent,
        root + remote_parent + local_child,
        root + local_child + remote_parent.replace("nfs4", "cifs"),
    ):
        assert not cap._posix_local_filesystem(
            Path("/vault/private/run-abc"), mountinfo=mounts,
        )
        # A root outside the remote ancestor remains locally classifiable.
        assert cap._posix_local_filesystem(
            Path("/ordinary/local"), mountinfo=mounts,
        )
