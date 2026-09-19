import pytest

from czjLLM.reduction.reducers import (
    ConcatJsonListReducer,
    ConcatTextReducer,
    LegacyJsonDeepMergeReducer,
)
from czjLLM.utilities.slice_merge import merge_dict_slices_audited


def test_concat_text_joins_prepared_items_in_stable_order_and_keeps_empty_items():
    result = ConcatTextReducer().reduce(["first\n", "", "second\n"])

    assert result.payload == "first\nsecond\n"
    assert result.metrics == {"input_count": 3}
    assert result.changed is True


def test_concat_text_empty_input_and_single_item_contract():
    reducer = ConcatTextReducer()

    assert reducer.reduce([]).payload == ""
    single = reducer.reduce(["already prepared\n"])
    assert single.payload == "already prepared\n"
    assert single.changed is False


def test_concat_text_rejects_non_text_without_filesystem_coercion():
    with pytest.raises(TypeError, match="already-prepared string"):
        ConcatTextReducer().reduce(["text", 3])


@pytest.mark.parametrize(
    ("items", "expected"),
    [
        ([{"id": 1}], [{"id": 1}]),
        ([[{"id": 1}, {"id": 2}]], [{"id": 1}, {"id": 2}]),
        ([{"id": 1}, [{"id": 2}, {"id": 3}]], [{"id": 1}, {"id": 2}, {"id": 3}]),
        ([[[{"nested": 0}], {"id": 1}, 9]], [{"id": 1}]),
        ([], []),
    ],
)
def test_concat_json_list_preserves_legacy_one_level_dict_contract(items, expected):
    assert ConcatJsonListReducer().reduce(items).payload == expected


def test_concat_json_list_preserves_order_and_reports_discarded_members():
    result = ConcatJsonListReducer().reduce(
        [[{"id": 1}, 9], {"id": 2}, [[{"nested": 0}], {"id": 3}]]
    )

    assert result.payload == [{"id": 1}, {"id": 2}, {"id": 3}]
    assert result.metrics == {"input_count": 3, "output_count": 3, "discarded_count": 2}


def test_deep_merge_recurses_concats_lists_and_defaults_to_no_dedup():
    items = [
        {"nested": {"left": 1}, "values": [1], "title": "left"},
        {"nested": {"right": 2}, "values": [1, 2], "title": "right"},
    ]

    result = LegacyJsonDeepMergeReducer().reduce(items)

    assert result.payload == {
        "nested": {"left": 1, "right": 2},
        "values": [1, 1, 2],
        "title": "left",
    }
    assert result.audit["counts"]["list_concat"] == 1
    assert result.audit["counts"]["list_dedup_removed"] == 0
    assert result.audit["counts"]["scalar_conflict"] == 1


def test_deep_merge_exposes_dedup_and_prefer_right_options():
    result = LegacyJsonDeepMergeReducer(
        conflict_policy="prefer_right",
        dedup_lists=True,
    ).reduce([{"values": [{"id": 1}], "title": "left"}, {"values": [{"id": 1}], "title": "right"}])

    assert result.payload == {"values": [{"id": 1}], "title": "right"}
    assert result.audit["counts"]["list_dedup_removed"] == 1
    assert {(sample["action"], sample["chosen"]) for sample in result.audit["samples"]} == {
        ("list_dedup", "other"),
        ("scalar_conflict", "right"),
    }


def test_deep_merge_preserves_empty_none_and_type_mismatch_legacy_behavior():
    result = LegacyJsonDeepMergeReducer().reduce(
        [
            {"empty": "", "null": None, "shape": {"left": 1}},
            {"empty": "value", "null": "value", "shape": ["right"]},
        ]
    )

    assert result.payload == {
        "empty": "value",
        "null": "value",
        "shape": {"left": 1},
    }
    assert result.audit["counts"]["scalar_conflict"] == 1
    assert result.audit["counts"]["type_mismatch"] == 1
    assert any(
        sample["action"] == "type_mismatch" and sample["path"] == "shape"
        for sample in result.audit["samples"]
    )


def test_deep_merge_adapter_matches_authoritative_legacy_utility_report():
    items = [
        {"nested": {"left": 1}, "values": [1], "title": "A"},
        {"nested": {"right": 2}, "values": [1, 2], "title": "B"},
    ]
    expected_payload, expected_audit = merge_dict_slices_audited(
        items,
        conflict_policy="prefer_left",
        dedup_lists=True,
        logger=None,
        max_log=10,
    )

    result = LegacyJsonDeepMergeReducer(dedup_lists=True).reduce(items)

    assert result.payload == expected_payload
    assert result.audit == expected_audit
    assert result.changed is expected_audit["changed"]
