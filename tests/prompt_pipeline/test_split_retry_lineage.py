"""Source-verified JSON split family lineage; not general request retry accounting."""

import json
import re

import pytest

from czjLLM.prompt_pipeline.slice_identity import (
    install_split_prompts, record_split_identity, verified_split_family_id,
)


def _running_parent(tmp_path, name="root.txt", text="original parent prompt"):
    item = tmp_path / "item"
    running = item / "RUNNING"
    running.mkdir(parents=True, exist_ok=True)
    parent = running / name
    parent.write_text(text, encoding="utf-8")
    return parent, text


def _intent_path(parent):
    return parent.parent.parent / "_extract_slice_identity" / "splits" / (parent.name + ".json")


def test_verified_split_parent_and_children_share_one_persisted_random_family(tmp_path):
    parent, original = _running_parent(tmp_path)
    children = [("root-0.txt", "first exact split"),
                ("root-1.txt", "second exact split")]
    install_split_prompts(str(parent), original, children)
    journal = _intent_path(parent)
    record = json.loads(journal.read_text(encoding="utf-8"))
    family = record["split_family_id"]
    assert re.fullmatch(r"[0-9a-f]{32}", family)
    assert "original parent prompt" not in journal.read_text(encoding="utf-8")
    assert verified_split_family_id(str(parent), original) == family
    for name, text in children:
        child_path = parent.parent.parent / "TODO" / name
        assert child_path.read_text(encoding="utf-8") == text
        assert verified_split_family_id(str(child_path), text) == family
    # A child's identity remains source-verified after the split parent is
    # removed by the existing queue processor.
    parent.unlink()
    child = parent.parent.parent / "TODO" / children[0][0]
    assert verified_split_family_id(str(child), children[0][1]) == family
    assert verified_split_family_id(str(child), "different prompt") == ""


def test_nested_split_inherits_lineage_only_from_verified_direct_parent(tmp_path):
    parent, original = _running_parent(tmp_path)
    install_split_prompts(str(parent), original,
                          [("root-0.txt", "child text"),
                           ("root-1.txt", "sibling")])
    family = verified_split_family_id(str(parent), original)
    child = parent.parent.parent / "TODO" / "root-0.txt"
    grandchildren = [("root-0-0.txt", "grandchild left"),
                     ("root-0-1.txt", "grandchild right")]
    install_split_prompts(str(child), "child text", grandchildren)
    nested_journal = child.parent.parent / "_extract_slice_identity" / "splits" / "root-0.txt.json"
    assert json.loads(nested_journal.read_text())["split_family_id"] == family
    for name, text in grandchildren:
        path = child.parent / name
        assert verified_split_family_id(str(path), text) == family

    # Replacing a verified parent with the same prompt preserves family.
    assert record_split_identity(str(parent), original,
                                 [("root-0.txt", "child text"),
                                  ("root-1.txt", "sibling")]) == family


def test_missing_legacy_or_stale_records_cannot_invent_lineage(tmp_path):
    parent, original = _running_parent(tmp_path)
    assert verified_split_family_id(str(parent), original) == ""
    journal = _intent_path(parent)
    journal.parent.mkdir(parents=True, exist_ok=True)
    # Before this feature, a valid version-1 journal carries no family UUID.
    record_split_identity(str(parent), original,
                          [("root-0.txt", "text-a"), ("root-1.txt", "text-b")])
    original_json = json.loads(journal.read_text())
    original_json.pop("split_family_id")
    journal.write_text(json.dumps(original_json), encoding="utf-8")
    assert verified_split_family_id(str(parent), original) == ""
    child = parent.parent.parent / "TODO" / "root-0.txt"
    assert verified_split_family_id(str(child), "text-a") == ""
    # A subsequent explicit split of the verified source can create a fresh
    # family, but must not retroactively claim it for the old journal.
    new_family = record_split_identity(str(parent), original,
                                       [("root-0.txt", "text-a"),
                                        ("root-1.txt", "text-b")])
    assert re.fullmatch(r"[0-9a-f]{32}", new_family)
    assert verified_split_family_id(str(child), "text-a") == new_family
    assert verified_split_family_id(str(child), "not the original child") == ""


def test_journal_malformed_unknown_and_symlink_are_not_family_evidence(tmp_path):
    parent, original = _running_parent(tmp_path)
    journal = _intent_path(parent)
    journal.parent.mkdir(parents=True, exist_ok=True)
    journal.write_text('{"version":1,"children":[{"name":[],"prompt_sha256":"abc"}]}')
    assert verified_split_family_id(str(parent), original) == ""
    record_split_identity(str(parent), original,
                          [("root-0.txt", "left"), ("root-1.txt", "right")])
    content = json.loads(journal.read_text())
    assert verified_split_family_id(str(parent), original) == content["split_family_id"]
    journal.write_text("x" * 16385, encoding="utf-8")
    assert verified_split_family_id(str(parent), original) == ""
    journal.write_text(json.dumps(content), encoding="utf-8")
    content["children"][0]["name"] = []
    journal.write_text(json.dumps(content))
    assert verified_split_family_id(str(parent), original) == ""
    content["children"][0]["name"] = "root-0.txt"
    content["split_family_id"] = "malformed-identifier"
    journal.write_text(json.dumps(content))
    assert verified_split_family_id(str(parent), original) == ""
    # Symlink journals are not allowed as evidence; don't delete the target.
    journal.unlink()
    target = tmp_path / "other.json"
    target.write_text(json.dumps(content))
    try:
        journal.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable on this host")
    assert verified_split_family_id(str(parent), original) == ""
    assert target.exists()


def test_unrelated_requeues_or_filename_prefixes_are_not_split_families(tmp_path):
    parent, original = _running_parent(tmp_path)
    install_split_prompts(str(parent), original,
                          [("root-0.txt", "left"), ("root-1.txt", "right")])
    root = parent.parent.parent
    unlinked = root / "RUNNING" / "root-0-0.txt"
    unlinked.write_text("left", encoding="utf-8")
    assert verified_split_family_id(str(unlinked), "left") == ""
    unrelated = root / "RUNNING" / "root-other.txt"
    unrelated.write_text("left", encoding="utf-8")
    assert verified_split_family_id(str(unrelated), "left") == ""
    assert verified_split_family_id(str(root / "Success" / "root-0.txt"), "left") == ""
    assert verified_split_family_id(str(root / "TODO" / "root-0.txt"), "right") == ""
