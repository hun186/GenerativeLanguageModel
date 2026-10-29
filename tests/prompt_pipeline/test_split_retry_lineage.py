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


def test_recreated_root_with_same_child_does_not_reuse_stale_nested_family(tmp_path):
    """A stale child's own journal may not override a fresh direct parent."""
    root, original = _running_parent(tmp_path, text="root version A")
    child_text = "the same child prompt"
    install_split_prompts(str(root), original,
                          [("root-0.txt", child_text), ("root-1.txt", "sibling A")])
    family_a = verified_split_family_id(str(root), original)
    child = root.parent.parent / "TODO" / "root-0.txt"
    nested = [("root-0-0.txt", "left"), ("root-0-1.txt", "right")]
    install_split_prompts(str(child), child_text, nested)
    assert verified_split_family_id(str(child), child_text) == family_a

    # An independent new source run reuses the child prompt text and
    # filename, but has a different parent intent and hence a new family.
    root.write_text("root version B", encoding="utf-8")
    family_b = record_split_identity(
        str(root), "root version B",
        [("root-0.txt", child_text), ("root-1.txt", "sibling B")],
    )
    assert family_b != family_a
    assert verified_split_family_id(str(root), "root version B") == family_b
    assert verified_split_family_id(str(child), child_text) == ""  # conflict
    # Explicitly committing a new nested intent may adopt only family B,
    # never the stale family's persisted UUID.
    assert record_split_identity(str(child), child_text, nested) == family_b
    assert verified_split_family_id(str(child), child_text) == family_b
    descendant = root.parent.parent / "TODO" / nested[0][0]
    assert verified_split_family_id(str(descendant), nested[0][1]) == family_b


def test_symlinked_identity_directories_cannot_read_or_redirect_other_item(tmp_path):
    source, text = _running_parent(tmp_path / "source")
    install_split_prompts(str(source), text,
                          [("root-0.txt", "left"), ("root-1.txt", "right")])
    family = verified_split_family_id(str(source), text)
    assert family

    for alias_level in ("identity", "splits"):
        victim, victim_text = _running_parent(tmp_path / alias_level)
        victim_root = victim.parent.parent
        real_root = source.parent.parent
        identity = victim_root / "_extract_slice_identity"
        try:
            if alias_level == "identity":
                identity.symlink_to(real_root / "_extract_slice_identity",
                                    target_is_directory=True)
            else:
                identity.mkdir()
                (identity / "splits").symlink_to(
                    real_root / "_extract_slice_identity" / "splits",
                    target_is_directory=True,
                )
        except (OSError, NotImplementedError):
            pytest.skip("directory symlinks unavailable")
        assert verified_split_family_id(str(victim), text) == ""
        with pytest.raises(ValueError, match="split journal namespace is a symlink"):
            record_split_identity(
                str(victim), victim_text,
                [("root-0.txt", "victim left"), ("root-1.txt", "victim right")],
            )
        assert verified_split_family_id(str(source), text) == family


def test_shallow_file_size_with_excessive_json_nesting_is_unknown(tmp_path):
    parent, original = _running_parent(tmp_path)
    journal = _intent_path(parent)
    journal.parent.mkdir(parents=True, exist_ok=True)
    journal.write_text("[" * 1100 + "0" + "]" * 1100, encoding="utf-8")
    assert journal.stat().st_size < 16384
    assert verified_split_family_id(str(parent), original) == ""
    # Malformed old evidence does not crash or prevent explicit new intent.
    family = record_split_identity(
        str(parent), original,
        [("root-0.txt", "left"), ("root-1.txt", "right")],
    )
    assert re.fullmatch(r"[0-9a-f]{32}", family)
    assert verified_split_family_id(str(parent), original) == family


def test_split_family_rejects_nil_non_version4_and_wrong_variant(tmp_path):
    parent, original = _running_parent(tmp_path)
    record_split_identity(str(parent), original,
                          [("root-0.txt", "left"), ("root-1.txt", "right")])
    journal = _intent_path(parent)
    original_data = json.loads(journal.read_text(encoding="utf-8"))
    child = parent.parent.parent / "TODO" / "root-0.txt"
    for invalid in (
        "0" * 32,                    # NIL
        "1" * 32,                    # Wrong UUID version
        "123456781234412341234567890abcde",  # v4 nibble, wrong variant
        "A" * 32,                    # Noncanonical uppercase
    ):
        modified = dict(original_data, split_family_id=invalid)
        journal.write_text(json.dumps(modified), encoding="utf-8")
        assert verified_split_family_id(str(parent), original) == ""
        assert verified_split_family_id(str(child), "left") == ""
    journal.write_text(json.dumps(original_data), encoding="utf-8")
    assert verified_split_family_id(str(parent), original) == original_data["split_family_id"]


@pytest.mark.parametrize("names", [
    ("root-0.txt", "root-0.txt"),
    ("root-0.txt", "root-2.txt"),
    ("root-1.txt", "root-other.txt"),
])
def test_split_writer_rejects_noncanonical_or_duplicate_children_without_writes(tmp_path, names):
    parent, original = _running_parent(tmp_path)
    journal = _intent_path(parent)
    with pytest.raises(ValueError, match="canonical, distinct"):
        install_split_prompts(str(parent), original, [(name, "child") for name in names])
    assert parent.read_text(encoding="utf-8") == original
    assert not journal.exists()
    assert not (parent.parent.parent / "TODO").exists()


def test_split_family_rejects_malformed_parent_or_sibling_hash_even_if_length_64(tmp_path):
    parent, original = _running_parent(tmp_path)
    install_split_prompts(str(parent), original,
                          [("root-0.txt", "left"), ("root-1.txt", "right")])
    journal = _intent_path(parent)
    valid = json.loads(journal.read_text(encoding="utf-8"))
    child = parent.parent.parent / "TODO" / "root-0.txt"
    assert verified_split_family_id(str(parent), original)
    for location in ("parent_prompt_sha256", "sibling"):
        altered = json.loads(json.dumps(valid))
        if location == "parent_prompt_sha256":
            altered[location] = "g" * 64
        else:
            altered["children"][1]["prompt_sha256"] = "G" * 64
        journal.write_text(json.dumps(altered), encoding="utf-8")
        assert verified_split_family_id(str(parent), original) == ""
        assert verified_split_family_id(str(child), "left") == ""
    journal.write_text(json.dumps(valid), encoding="utf-8")
    assert verified_split_family_id(str(child), "left") == valid["split_family_id"]
