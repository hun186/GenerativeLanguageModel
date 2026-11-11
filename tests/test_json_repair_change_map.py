"""Headless verification of the popup's non-payload length change map."""
from czjLLM.utilities.json_repair_change_map import change_map_segments


def test_prefix_middle_suffix_bar_preserves_original_and_repaired_lengths():
    case = {"detail": {
        "original_chars": 4846, "repaired_chars": 5140,
        "common_prefix_chars": 1000, "common_suffix_chars": 3000,
    }}
    before, after = change_map_segments(case)
    assert before == (1000, 846, 3000)
    assert after == (1000, 1140, 3000)
    assert sum(before) == 4846 and sum(after) == 5140


def test_no_negative_middle_when_prefix_suffix_are_inconsistent():
    case = {"detail": {
        "original_chars": 3, "repaired_chars": 5,
        "common_prefix_chars": 10, "common_suffix_chars": 10,
    }}
    before, after = change_map_segments(case)
    assert before == (3, 0, 0)
    assert after == (3, 2, 0)


def test_unavailable_metrics_are_not_converted_to_trusted_evidence():
    assert change_map_segments({"detail": {}}) == ((0, 0, 0), (0, 0, 0))


def test_summary_is_not_a_semantic_or_token_level_diff():
    case = {"detail": {
        "original_chars": 11, "repaired_chars": 12,
        "common_prefix_chars": 4, "common_suffix_chars": 3,
        "same_literal_pct": 95,
    }}
    assert change_map_segments(case) == ((4, 4, 3), (4, 5, 3))
