from types import SimpleNamespace

from czjLLM.utilities.slice_merge import (
    merge_dict_slices,
    merge_dict_slices_audited,
    should_merge_slices,
)


def test_slice_merge_activation_aliases_and_default_off():
    assert should_merge_slices(SimpleNamespace()) is False
    assert should_merge_slices(SimpleNamespace(merge_slices=True)) is True
    assert should_merge_slices(SimpleNamespace(enable_slice_merge=True)) is True
    assert should_merge_slices(SimpleNamespace(merge_strategy="dict_deep")) is True


def test_legacy_deep_merge_recurses_concats_lists_and_prefers_first_nonempty_scalar():
    merged = merge_dict_slices([
        {"nested": {"left": 1, "title": "A"}, "items": [1], "empty": "", "null": None},
        {"nested": {"right": 2, "title": "B"}, "items": [1, 2], "empty": "value", "null": "value"},
    ])

    assert merged == {
        "nested": {"left": 1, "right": 2, "title": "A"},
        "items": [1, 1, 2],
        "empty": "value",
        "null": "value",
    }


def test_audited_merge_freezes_semantic_report_for_all_conflict_classes():
    merged, report = merge_dict_slices_audited(
        [
            {"nested": {"left": 1}, "items": [{"id": 1}], "title": "A", "shape": {"x": 1}},
            {"nested": {"right": 2}, "items": [{"id": 1}, {"id": 2}], "title": "B", "shape": [1]},
        ],
        conflict_policy="prefer_left",
        dedup_lists=True,
        logger=None,
    )

    assert merged == {
        "nested": {"left": 1, "right": 2},
        "items": [{"id": 1}, {"id": 2}],
        "title": "A",
        "shape": {"x": 1},
    }
    assert report["changed"] is True
    assert report["counts"] == {
        "list_concat": 1,
        "list_dedup_removed": 1,
        "scalar_conflict": 1,
        "type_mismatch": 1,
    }
    assert {(sample["action"], sample["path"], sample["chosen"]) for sample in report["samples"]} == {
        ("list_dedup", "items", "other"),
        ("scalar_conflict", "title", "left"),
        ("type_mismatch", "shape", "left"),
    }


def test_audited_merge_empty_scalars_choose_right_without_recording_conflict():
    merged, report = merge_dict_slices_audited(
        [{"empty": "", "null": None}, {"empty": "value", "null": "value"}],
        logger=None,
    )

    assert merged == {"empty": "value", "null": "value"}
    assert report["changed"] is True
    assert report["counts"]["scalar_conflict"] == 1
    assert report["counts"]["type_mismatch"] == 0


def test_audited_merge_rejects_non_list_dict_shape_with_empty_report():
    assert merge_dict_slices_audited({"id": 1}, logger=None) == (
        {}, {"changed": False, "counts": {}, "samples": []}
    )
