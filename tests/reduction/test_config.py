from types import MappingProxyType

import pytest

from czjLLM.reduction.config import (
    ReductionConfigError,
    parse_reduction_config,
)


def test_absent_and_explicit_false_are_inactive():
    absent = parse_reduction_config(None)
    disabled = parse_reduction_config(
        {"enabled": False, "profile": "text-concat", "controller": "single_pass"}
    )

    assert absent.enabled is False
    assert absent.profile is None
    assert disabled.enabled is False
    assert disabled.profile == "concat_text"
    assert isinstance(disabled.options, MappingProxyType)


def test_mapping_without_enabled_is_valid_but_inactive():
    config = parse_reduction_config({"profile": "concat_text"})

    assert config.enabled is False
    assert config.profile == "concat_text"


@pytest.mark.parametrize(
    ("value", "canonical"),
    [
        ("concat_text", "concat_text"),
        ("json-list-concat", "concat_json_list"),
        ("legacy deep merge", "legacy_json_deep_merge"),
    ],
)
def test_enabled_profiles_and_aliases_are_canonicalized(value, canonical):
    config = parse_reduction_config(
        {"enabled": True, "profile": value, "controller": "single_pass"}
    )

    assert config.enabled is True
    assert config.profile == canonical


@pytest.mark.parametrize("raw", [True, "concat_text", []])
def test_reduction_must_be_a_mapping(raw):
    with pytest.raises(ReductionConfigError, match="must be a mapping"):
        parse_reduction_config(raw)


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ({"enabled": True}, "profile is required"),
        ({"enabled": True, "profile": "unknown"}, "Unknown reduction profile"),
        (
            {"enabled": True, "profile": "concat_text", "controller": "mystery"},
            "must be one of",
        ),
        ({"enabled": True, "profile": "concat_text", "rounds": []}, "Unsupported reduction key"),
        (
            {"enabled": True, "profile": "concat_text", "options": {"dedup_lists": True}},
            "Unsupported reduction option",
        ),
        (
            {"enabled": True, "profile": "legacy_json_deep_merge", "options": {"dedup_lists": 1}},
            "dedup_lists must be a boolean",
        ),
        (
            {"enabled": True, "profile": "legacy_json_deep_merge", "options": {"max_audit_samples": True}},
            "non-negative integer",
        ),
        (
            {"enabled": True, "profile": "legacy_json_deep_merge", "options": {"conflict_policy": "last"}},
            "conflict_policy must be one of",
        ),
    ],
)
def test_invalid_pr_c_configuration_is_rejected(raw, message):
    with pytest.raises(ReductionConfigError, match=message):
        parse_reduction_config(raw)


def test_explicit_reduction_conflicts_with_legacy_merge_slices():
    with pytest.raises(ReductionConfigError, match="mutually exclusive"):
        parse_reduction_config(
            {"enabled": True, "profile": "legacy_json_deep_merge"},
            merge_slices=True,
        )


def test_disabled_reduction_does_not_conflict_with_legacy_merge_slices():
    assert parse_reduction_config(
        {"enabled": False, "profile": "concat_text"},
        merge_slices=True,
    ).enabled is False


def test_fixed_and_adaptive_hierarchical_configs_build_d1_controllers():
    fixed = parse_reduction_config({
        "enabled": True,
        "profile": "concat_text",
        "controller": "fixed_rounds",
        "controller_options": {"rounds": 2},
        "runtime": {"round_task": "SUMMARY"},
    })
    adaptive = parse_reduction_config({
        "enabled": True,
        "profile": "concat_text",
        "controller": "adaptive_hierarchical",
        "controller_options": {
            "target_max_chars": 12000,
            "max_rounds": 4,
            "min_reduction_ratio": 0.1,
        },
        "runtime": {"round_task": "raw summary instruction"},
    })

    assert fixed.build_controller().rounds == 2
    assert adaptive.build_controller().target_max_chars == 12000
    assert fixed.runtime["round_task"] == "SUMMARY"


@pytest.mark.parametrize("rounds", [0, -1, True, 1.5, "2"])
def test_fixed_rounds_strictly_requires_positive_integer(rounds):
    with pytest.raises(ReductionConfigError, match="fixed rounds"):
        parse_reduction_config({
            "enabled": True, "profile": "concat_text", "controller": "fixed_rounds",
            "controller_options": {"rounds": rounds},
            "runtime": {"round_task": "SUMMARY"},
        })


@pytest.mark.parametrize(
    "options",
    [
        {"target_max_chars": -1, "max_rounds": 2, "min_reduction_ratio": 0.1},
        {"target_max_chars": True, "max_rounds": 2, "min_reduction_ratio": 0.1},
        {"target_max_chars": 1, "max_rounds": 0, "min_reduction_ratio": 0.1},
        {"target_max_chars": 1, "max_rounds": True, "min_reduction_ratio": 0.1},
        {"target_max_chars": 1, "max_rounds": 2, "min_reduction_ratio": -0.1},
        {"target_max_chars": 1, "max_rounds": 2, "min_reduction_ratio": float("inf")},
    ],
)
def test_adaptive_options_reuse_strict_d1_validation(options):
    with pytest.raises(ReductionConfigError, match="Invalid reduction.controller_options"):
        parse_reduction_config({
            "enabled": True, "profile": "concat_text",
            "controller": "adaptive_hierarchical", "controller_options": options,
            "runtime": {"round_task": "SUMMARY"},
        })


@pytest.mark.parametrize(
    ("extra", "message"),
    [
        ({"controller_options": {"rounds": 2, "extra": 1}}, "Unsupported reduction controller option"),
        ({"controller_options": {"rounds": 2}, "runtime": {"round_task": "SUMMARY", "extra": 1}}, "Unsupported reduction runtime"),
        ({"controller_options": {"rounds": 2}}, "round_task is required"),
    ],
)
def test_hierarchical_schema_rejects_missing_or_unknown_fields(extra, message):
    raw = {"enabled": True, "profile": "concat_text", "controller": "fixed_rounds"}
    raw.update(extra)
    with pytest.raises(ReductionConfigError, match=message):
        parse_reduction_config(raw)


def test_hierarchical_rejects_json_profile_and_single_pass_rejects_runtime_settings():
    with pytest.raises(ReductionConfigError, match="concat_text only"):
        parse_reduction_config({
            "enabled": True, "profile": "concat_json_list", "controller": "fixed_rounds",
            "controller_options": {"rounds": 1}, "runtime": {"round_task": "SUMMARY"},
        })
    with pytest.raises(ReductionConfigError, match="absent or empty for single_pass"):
        parse_reduction_config({
            "enabled": True, "profile": "concat_text", "controller": "single_pass",
            "runtime": {"round_task": "SUMMARY"},
        })
