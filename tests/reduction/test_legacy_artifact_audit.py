from __future__ import annotations

import json
from pathlib import Path

import pytest

from czjLLM.cli_tools.reduction_legacy_audit import main
from czjLLM.reduction.maintenance import inventory_legacy_reduction_artifacts
from czjLLM.reduction.retention import (
    item_retention_root,
    prompt_container_retention_root,
)


def _checkpoint(item: Path, name: str, *, manifest: str | None = "{}") -> Path:
    run = item / ".reduction" / "checkpoints" / name
    run.mkdir(parents=True)
    if manifest is not None:
        (run / "run.json").write_text(manifest, encoding="utf-8")
    return run


def _round(item: Path, name: str = "round-0002") -> Path:
    path = item / ".reduction" / "runtime" / name
    path.mkdir(parents=True)
    return path


def test_read_only_inventory_classifies_without_opening_payloads(tmp_path: Path):
    item = tmp_path / "item"
    legacy = _checkpoint(item, "a" * 64, manifest="{not actually valid")
    _checkpoint(item, "b" * 64, manifest=None)
    marked = _checkpoint(item, "c" * 64)
    (marked / ".retention.json").write_text("{broken", encoding="utf-8")
    bad_marker = _checkpoint(item, "d" * 64)
    (bad_marker / ".retention.json").mkdir()
    runtime = _round(item)
    unknown = _round(item, "custom-folder")
    unrelated = item / "_stage_outputs"
    unrelated.mkdir(parents=True)
    (unrelated / "do-not-touch").write_text("sensitive", encoding="utf-8")

    before = {p.relative_to(item).as_posix(): (p.stat().st_mtime_ns, p.read_bytes())
              for p in item.rglob("*") if p.is_file()}
    report = inventory_legacy_reduction_artifacts([item_retention_root(item)])
    after = {p.relative_to(item).as_posix(): (p.stat().st_mtime_ns, p.read_bytes())
             for p in item.rglob("*") if p.is_file()}

    assert before == after
    assert legacy.exists() and runtime.exists() and unknown.exists()
    assert report.read_only is True
    assert report.candidate_directories == 6
    assert report.unmarked_checkpoint_manifest_present_unverified == 1
    assert report.unmarked_checkpoint_manifest_missing == 1
    assert report.marker_files_present_unverified == 1
    assert report.marker_nonregular == 1
    assert report.unmarked_runtime_rounds == 1
    assert report.unrecognized_unmarked_directories == 1
    assert report.skipped_containment == 0
    assert report.scan_limit_reached is False
    assert "sensitive" not in json.dumps(report.__dict__)
    assert str(item) not in json.dumps(report.__dict__)


def test_prompt_root_scope_and_scan_bound_are_explicit(tmp_path: Path):
    prompt = tmp_path / "Prompt"
    one = _checkpoint(prompt / "item-a", "a" * 64)
    two = _checkpoint(prompt / "item-b", "b" * 64)
    nested = _checkpoint(prompt / "misc" / "nested" / "item", "c" * 64)
    outside = _checkpoint(tmp_path / "outside", "d" * 64)
    (prompt / "linked-item").symlink_to(outside.parent.parent, target_is_directory=True)

    result = inventory_legacy_reduction_artifacts(
        [prompt_container_retention_root(prompt)]
    )
    assert result.candidate_directories == 2
    assert result.unmarked_checkpoint_manifest_present_unverified == 2
    assert nested.exists() and outside.exists() and one.exists() and two.exists()

    bounded = inventory_legacy_reduction_artifacts(
        [prompt_container_retention_root(prompt)], max_scan_entries=1
    )
    assert bounded.scan_limit_reached is True
    assert bounded.scanned_entries == 1
    assert bounded.candidate_directories <= 1
    with pytest.raises(ValueError, match="positive integer"):
        inventory_legacy_reduction_artifacts([item_retention_root(prompt)], max_scan_entries=True)
    with pytest.raises(ValueError, match="positive integer"):
        inventory_legacy_reduction_artifacts([item_retention_root(prompt)], max_scan_entries=0)


def test_symlinks_never_classified_as_plain_legacy(tmp_path: Path):
    outside = _checkpoint(tmp_path / "outside", "f" * 64)
    item = tmp_path / "item"
    fake = _checkpoint(item, "a" * 64, manifest=None)
    (fake / "run.json").symlink_to(outside / "run.json")
    runtime_parent = item / ".reduction" / "runtime"
    runtime_parent.mkdir(parents=True)
    (runtime_parent / "round-0002").symlink_to(outside, target_is_directory=True)

    report = inventory_legacy_reduction_artifacts([item])
    assert report.candidate_directories == 1
    assert report.unmarked_checkpoint_manifest_nonregular == 1
    (item.parent / "item-link").symlink_to(item, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink or junction inventory roots"):
        inventory_legacy_reduction_artifacts([item_retention_root(item.parent / "item-link")])

    assert outside.exists()


def test_windows_reparse_junction_guard_in_prompt_and_explicit_root(tmp_path: Path, monkeypatch):
    # Simulate Windows FILE_ATTRIBUTE_REPARSE_POINT to cover 3.10/3.11,
    # even when the Linux test filesystem cannot create real junctions.
    from czjLLM.reduction import maintenance, retention

    prompt = tmp_path / "Prompt"
    blocked_item = prompt / "junction-like"
    run = _checkpoint(blocked_item, "a" * 64)
    safe = _checkpoint(prompt / "safe", "b" * 64)
    real = retention._is_reparse_path

    def junction_like(path: Path) -> bool:
        return Path(path) == blocked_item or real(path)

    monkeypatch.setattr(retention, "_is_reparse_path", junction_like)
    monkeypatch.setattr(maintenance, "_is_reparse_path", junction_like)
    report = inventory_legacy_reduction_artifacts([prompt_container_retention_root(prompt)])
    assert report.unmarked_checkpoint_manifest_present_unverified == 1
    assert report.candidate_directories == 1
    assert run.exists() and safe.exists()
    with pytest.raises(ValueError, match="symlink or junction"):
        inventory_legacy_reduction_artifacts([item_retention_root(blocked_item)])


def test_missing_roots_fail_and_overlapping_scopes_do_not_double_count(tmp_path: Path):
    item = tmp_path / "Prompt" / "one"
    _checkpoint(item, "a" * 64)
    prompt = item.parent
    with pytest.raises(ValueError, match="existing directory"):
        inventory_legacy_reduction_artifacts([tmp_path / "wrong"])
    with pytest.raises(ValueError, match="existing directory"):
        inventory_legacy_reduction_artifacts([tmp_path / "wrong" / "missing"])
    not_a_directory = tmp_path / "plain-file"
    not_a_directory.write_text("still here", encoding="utf-8")
    with pytest.raises(ValueError, match="existing directory"):
        inventory_legacy_reduction_artifacts([not_a_directory])
    report = inventory_legacy_reduction_artifacts([
        item_retention_root(item), prompt_container_retention_root(prompt),
        item_retention_root(item),
    ])
    assert report.candidate_directories == 1
    assert report.unmarked_checkpoint_manifest_present_unverified == 1
    # Prompt child + one checkpoint, not three overlapping walks.
    assert report.scanned_entries == 2


def test_python_api_rejects_empty_roots(tmp_path: Path):
    with pytest.raises(ValueError, match="at least one approved"):
        inventory_legacy_reduction_artifacts([])
    with pytest.raises(ValueError, match="at least one approved"):
        inventory_legacy_reduction_artifacts(path for path in [])


def test_item_root_and_dot_reduction_alias_share_one_scan_budget(tmp_path: Path):
    item = tmp_path / "item"
    checkpoint = _checkpoint(item, "a" * 64)
    report = inventory_legacy_reduction_artifacts(
        [item_retention_root(item), item_retention_root(item / ".reduction")],
        max_scan_entries=1,
    )
    assert report.scanned_entries == 1
    assert report.candidate_directories == 1
    assert report.unmarked_checkpoint_manifest_present_unverified == 1
    assert not report.scan_limit_reached
    assert checkpoint.exists()


def test_same_directory_as_item_and_prompt_root_is_not_double_scanned(tmp_path: Path):
    item = tmp_path / "both"
    artifact = _checkpoint(item, "a" * 64)
    report = inventory_legacy_reduction_artifacts(
        [item_retention_root(item), prompt_container_retention_root(item)],
        max_scan_entries=1,
    )
    assert report.scanned_entries == 1
    assert report.candidate_directories == 1
    assert report.unmarked_checkpoint_manifest_present_unverified == 1
    assert not report.scan_limit_reached
    assert artifact.exists()
    # A prompt-only scan must not treat the container's .reduction as
    # an item in its own right.
    prompt_only = inventory_legacy_reduction_artifacts(
        [prompt_container_retention_root(item)], max_scan_entries=1,
    )
    assert prompt_only.scanned_entries == 0
    assert prompt_only.candidate_directories == 0
    assert not prompt_only.scan_limit_reached


def test_cli_json_is_bounded_and_truncation_has_nonzero_exit(tmp_path: Path, capsys):
    prompt = tmp_path / "Prompt"
    _checkpoint(prompt / "one", "a" * 64)
    _checkpoint(prompt / "two", "b" * 64)
    assert main(["--prompt-root", str(prompt)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["report_version"] == 1
    assert report["unmarked_checkpoint_manifest_present_unverified"] == 2
    assert report["read_only"] is True
    assert "run_key" not in report

    assert main(["--prompt-root", str(prompt), "--max-scan-entries", "1"]) == 2
    truncated = json.loads(capsys.readouterr().out)
    assert truncated["scan_limit_reached"] is True
    assert main(["--prompt-root", str(prompt), "--max-scan-entries", "0"]) == 2
    assert "Inventory failed" in capsys.readouterr().err
