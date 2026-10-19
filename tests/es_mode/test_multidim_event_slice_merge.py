"""Regression for independent chunk-local Event IDs in ES multidim writeback."""
from __future__ import annotations

from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from czjLLM.es_mode.output_profiles.multidim_event import (
    normalize_multidim_event_payload,
)
from czjLLM.utilities.slice_merge import (
    is_multidim_event_slice_merge,
    merge_dict_slices_audited,
)


def _article(event_id, *, action, impact_nested=False):
    impact = {"event_ids": [event_id], "impact_description": "Consequences: " + action}
    return {
        "article_title": "UNODC marriage / trafficking issue paper",
        "article_date_iso": "2020-01-01",
        "article_date_precision": "year",
        "Event": [{
            "event_id": event_id,
            "subject": "UNODC",
            "action": action,
            "time_raw": "2020",
            "time_iso": "2020-01-01",
            "time_precision": "year",
        }],
        "Person": [{"event_ids": [event_id], "name": "Researcher " + action}],
        "Involved_Parties": [{"event_ids": [event_id], "party_name": "HEUNI"}],
        "Impact": [[impact]] if impact_nested else [impact],
        "Event_Timeline": [{
            "event_ids": [event_id],
            "time_raw": "2020",
            "time_iso": "2020-01-01",
            "time_precision": "year",
            "description": action,
        }],
        "evidence_snippets": [{"event_ids": [event_id], "text": action}],
    }


@pytest.mark.parametrize(
    "left_date,left_precision,right_date,right_precision,policy,expected",
    [
        (None, "unknown", "1982-12-10", "day", "prefer_left", (None, "unknown")),
        ("1982-12-10", "day", None, "unknown", "prefer_left", ("1982-12-10", "day")),
        (None, "unknown", "1982-12-10", "day", "prefer_right", ("1982-12-10", "day")),
        ("1982-12-10", "unknown", "1982-12-10", "day",
         "prefer_left", ("1982-12-10", "day")),
        ("1982-12-10", "day", "1982-12-10", "unknown",
         "prefer_left", ("1982-12-10", "day")),
        ("1982-12-10", "day", "1994-11-16", "day",
         "prefer_left", ("1982-12-10", "day")),
    ],
)
def test_article_date_and_precision_merge_as_source_pair(
    left_date, left_precision, right_date, right_precision, policy, expected,
):
    left = _article("E1", action="articles")
    right = _article("E1", action="annex")
    left.update(article_date_iso=left_date, article_date_precision=left_precision)
    right.update(article_date_iso=right_date, article_date_precision=right_precision)
    original = deepcopy([left, right])
    merged, report = merge_dict_slices_audited(
        [left, right], conflict_policy=policy, multidim_event=True,
        logger=None,
    )
    assert (merged["article_date_iso"], merged["article_date_precision"]) == expected
    assert normalize_multidim_event_payload([merged])[0]["article_date_precision"] == expected[1]
    assert [left, right] == original
    assert report["changed"]


def test_invalid_pairs_cannot_cross_assemble_a_valid_looking_article_date():
    left = _article("E1", action="one")
    right = _article("E1", action="two")
    left.update(article_date_iso=None, article_date_precision="day")
    right.update(article_date_iso="1982-12-10", article_date_precision="unknown")
    merged, _ = merge_dict_slices_audited(
        [left, right], multidim_event=True, logger=None,
    )
    assert (merged["article_date_iso"], merged["article_date_precision"]) == (None, "day")
    with pytest.raises(ValueError, match="null article_date_iso requires"):
        normalize_multidim_event_payload([merged])


def test_incomplete_source_date_pairs_cannot_cross_assemble_valid_metadata():
    left = _article("E1", action="one")
    right = _article("E1", action="two")
    del left["article_date_precision"]
    del right["article_date_iso"]
    left["article_date_iso"] = "1982-12-10"
    right["article_date_precision"] = "day"
    merged, _ = merge_dict_slices_audited(
        [left, right], multidim_event=True, logger=None,
    )
    assert "article_date_iso" not in merged
    assert "article_date_precision" not in merged
    with pytest.raises(ValueError, match="article_date_iso and article_date_precision"):
        normalize_multidim_event_payload([merged])


def test_incomplete_only_date_fields_are_audited_even_for_single_slice():
    row = _article("E1", action="only")
    del row["article_date_precision"]
    original = deepcopy(row)
    merged, report = merge_dict_slices_audited(
        [row], multidim_event=True, logger=None,
    )
    assert "article_date_iso" not in merged
    assert "article_date_precision" not in merged
    assert report["changed"] is True
    assert any(
        x["action"] == "article_date_pair_incomplete"
        and "article_date_iso" in x["left_short"]
        for x in report["samples"]
    )
    with pytest.raises(ValueError, match="article_date_iso and article_date_precision"):
        normalize_multidim_event_payload([merged])
    assert row == original


def test_article_date_trailing_whitespace_respects_same_es_normalization():
    left = _article("E1", action="one")
    right = _article("E1", action="two")
    left.update(article_date_iso=" 1982-12-10 ", article_date_precision="day")
    right.update(article_date_iso=None, article_date_precision="unknown")
    merged, _ = merge_dict_slices_audited(
        [left, right], multidim_event=True, logger=None,
    )
    assert merged["article_date_iso"] == "1982-12-10"
    assert merged["article_date_precision"] == "day"
    assert normalize_multidim_event_payload([merged])[0]["article_date_iso"] == "1982-12-10"
    assert left["article_date_iso"] == " 1982-12-10 "  # Do not mutate Success.


def test_invalid_article_date_pairs_are_not_silently_inferred():
    left = _article("E1", action="one")
    right = _article("E1", action="two")
    left.update(article_date_iso="1982-12-10", article_date_precision="unknown")
    right.update(article_date_iso="1994-11-16", article_date_precision="unknown")
    merged, _ = merge_dict_slices_audited(
        [left, right], multidim_event=True, logger=None,
    )
    with pytest.raises(ValueError, match="non-null article_date_iso"):
        normalize_multidim_event_payload([merged])


def test_generic_json_merge_does_not_apply_strict_article_date_pair_policy():
    left = _article("E1", action="one")
    right = _article("E1", action="two")
    left.update(article_date_iso=None, article_date_precision="unknown")
    right.update(article_date_iso="1982-12-10", article_date_precision="day")
    merged, _ = merge_dict_slices_audited([left, right], logger=None)
    assert merged["article_date_iso"] == "1982-12-10"
    assert merged["article_date_precision"] == "unknown"


@pytest.mark.parametrize(
    "form,invalid", [
        ("flat", True), ("flat", 85.0), ("flat", "85"),
        ("nested", True), ("nested", 85.0),
    ],
)
def test_invalid_importance_scores_in_later_slice_are_rejected_before_merge(
    form, invalid,
):
    from czjLLM.utilities.slice_merge import MultidimEventSchemaError

    left = _article("E1", action="first")
    right = _article("E1", action="second")
    if form == "flat":
        left["coverage"] = 85
        right["coverage"] = invalid
    else:
        left["importance"] = {"coverage": 85}
        right["importance"] = {"coverage": invalid}
    originals = deepcopy([left, right])
    with pytest.raises(
        MultidimEventSchemaError,
        match=r"multidim slice 1 (?:article|importance).coverage must be integer or null",
    ):
        merge_dict_slices_audited(
            [left, right], multidim_event=True, logger=None,
        )
    assert [left, right] == originals


def test_same_slice_flat_and_nested_score_conflict_cannot_disappear_on_merge():
    from czjLLM.utilities.slice_merge import MultidimEventSchemaError

    first = _article("E1", action="first")
    second = _article("E1", action="second")
    first["importance"] = {"coverage": 85}
    second["importance"] = {"coverage": 80}
    second["coverage"] = 85
    # Naive deep merge (prefer_left) would produce importance.coverage=85,
    # coverage=85 and incorrectly make slice 2's conflicting values disappear.
    with pytest.raises(
        MultidimEventSchemaError, match="slice 1 importance.coverage conflicts",
    ):
        merge_dict_slices_audited(
            [first, second], multidim_event=True, logger=None,
        )


def test_importance_object_type_mismatch_not_hidden_by_later_slice():
    from czjLLM.utilities.slice_merge import MultidimEventSchemaError

    first = _article("E1", action="first")
    second = _article("E1", action="second")
    first["importance"] = None
    second["importance"] = {"coverage": 85}
    with pytest.raises(MultidimEventSchemaError, match="slice 0 importance must be object"):
        merge_dict_slices_audited([first, second], multidim_event=True, logger=None)


def test_original_generic_slice_merge_does_not_get_strict_importance_validation():
    first = _article("E1", action="first")
    second = _article("E1", action="second")
    first["coverage"] = 85
    second["coverage"] = True
    merged, _ = merge_dict_slices_audited([first, second], logger=None)
    assert merged["coverage"] == 85


def test_two_independent_e1_events_relabel_linked_references_and_normalize_impact():
    left = _article("E1", action="publish report", impact_nested=True)
    right = _article("E1", action="interview experts", impact_nested=True)
    original = deepcopy([left, right])

    merged, report = merge_dict_slices_audited(
        [left, right], multidim_event=True, dedup_lists=True, logger=None,
    )

    assert [e["event_id"] for e in merged["Event"]] == ["E1", "E2"]
    for field in ("Person", "Involved_Parties", "Event_Timeline", "evidence_snippets"):
        assert [row["event_ids"] for row in merged[field]] == [["E1"], ["E2"]]
    # Impact arrives as nested arrays in actual repaired LLM output.
    assert [[r["event_ids"] for r in group] for group in merged["Impact"]] == [
        [["E1"]], [["E2"]],
    ]
    normalized = normalize_multidim_event_payload([merged])
    assert [row["event_ids"] for row in normalized[0]["Impact"]] == [["E1"], ["E2"]]
    assert len(normalized[0]["Event"]) == 2
    assert report["counts"]["list_concat"] >= 1
    assert [left, right] == original  # Never mutate cached Success slice JSON.


def test_collision_allocates_unused_global_id_without_stealing_later_original_id():
    first = _article("E1", action="one")
    second = _article("E1", action="two")
    third = _article("E2", action="three")
    merged, _ = merge_dict_slices_audited(
        [first, second, third], multidim_event=True, logger=None,
    )
    assert [r["event_id"] for r in merged["Event"]] == ["E1", "E3", "E2"]
    assert [r["event_ids"] for r in merged["Person"]] == [["E1"], ["E3"], ["E2"]]
    normalize_multidim_event_payload([merged])


def test_repeated_id_within_one_slice_remains_schema_error():
    row = _article("E1", action="one")
    row["Event"].append(dict(row["Event"][0]))
    with pytest.raises(ValueError, match="inside slice 0"):
        merge_dict_slices_audited([row], multidim_event=True, logger=None)


def test_dangling_reference_is_never_made_valid_by_generated_event_id():
    left = _article("E1", action="first")
    right = _article("E1", action="second")
    # The second slice's E2 is not declared by its Event; the writeback
    # must keep rejecting this dangling foreign key even after renumbering.
    right["Person"][0]["event_ids"] = ["E2"]
    with pytest.raises(ValueError, match="slice 1 Person references missing local Event.event_id 'E2'"):
        merge_dict_slices_audited(
            [left, right], multidim_event=True, logger=None,
        )


def test_dangling_reference_cannot_be_rescued_by_event_in_another_slice():
    left = _article("E1", action="first")
    left["Person"][0]["event_ids"] = ["E2"]  # Missing locally.
    right = _article("E1", action="second")
    right["Event"].append({
        "event_id": "E2", "subject": "UNODC", "action": "third",
        "time_raw": "2020", "time_iso": "2020-01-01", "time_precision": "year",
    })
    with pytest.raises(ValueError, match="slice 0 Person references missing local Event.event_id 'E2'"):
        merge_dict_slices_audited(
            [left, right], multidim_event=True, logger=None,
        )


def test_single_writeback_rule_selects_profile_over_generic_default():
    ctx = SimpleNamespace(
        output_col="raw",
        output_profile="none",
        es_writeback_rules=[{
            "output_col": "multidim_event_json",
            "output_profile": "multidim_event",
        }],
    )
    assert is_multidim_event_slice_merge(ctx)
    # Explicit output selection is still authoritative in the per-field writer.
    assert is_multidim_event_slice_merge(ctx, output_col="multidim_event_json")
    assert not is_multidim_event_slice_merge(ctx, output_col="raw")


def test_each_shared_source_field_gets_independent_profile_merge():
    from czjLLM.sql_mode.runtime.row_merger_generic import (
        _apply_slice_merge_to_write_map,
        _slice_merge_writeback_value,
    )
    left = _article("E1", action="first")
    right = _article("E1", action="second")
    slices = [left, right]
    raw = json.dumps(slices, ensure_ascii=False)
    ctx = SimpleNamespace(
        output_col="generic_json",
        output_profile="none",
        sql_writeback_rules=[
            {"output_col": "generic_json", "output_profile": "none"},
            {"output_col": "multidim_event_json", "output_profile": "multidim_event"},
        ],
        merge_dedup_lists=True,
    )
    for primary_multidim in (False, True):
        primary, _ = merge_dict_slices_audited(
            slices, multidim_event=primary_multidim, logger=None,
        )
        # Both output columns consume the exact same source JSON.
        mapped = {"generic_json": raw, "multidim_event_json": raw}
        updated = _apply_slice_merge_to_write_map(
            ctx, mapped, raw, primary, source_slices=slices,
            primary_multidim=primary_multidim,
        )
        assert updated == ["generic_json", "multidim_event_json"]
        generic = json.loads(mapped["generic_json"])
        strict = json.loads(mapped["multidim_event_json"])
        assert isinstance(generic, dict)
        assert [row["event_id"] for row in generic["Event"]] == ["E1", "E1"]
        assert [row["event_id"] for row in strict[0]["Event"]] == ["E1", "E2"]
        normalize_multidim_event_payload(strict)
        assert _slice_merge_writeback_value(ctx, "multidim_event_json", strict[0]) == mapped["multidim_event_json"]


def test_whitespace_reference_follows_its_own_remapped_slice_event():
    left = _article("E1", action="first")
    right = _article(" E1 ", action="second")
    right["Person"][0]["event_ids"] = [" E1 "]
    merged, _ = merge_dict_slices_audited(
        [left, right], multidim_event=True, logger=None,
    )
    assert [e["event_id"] for e in merged["Event"]] == ["E1", "E2"]
    assert [row["event_ids"] for row in merged["Person"]] == [["E1"], ["E2"]]
    normalize_multidim_event_payload([merged])


def test_stage_source_preserves_multidim_array_envelope():
    from czjLLM.prompt_pipeline.pipeline_controller import (
        _merge_single_extract_stage_json_parts,
    )
    source = [
        json.dumps([_article("E1", action="first")], ensure_ascii=False),
        json.dumps([_article("E1", action="second")], ensure_ascii=False),
    ]
    ctx = SimpleNamespace(
        output_col="multidim_event_json",
        output_profile="multidim_event",
        merge_log_changes=False,
    )
    result = json.loads(_merge_single_extract_stage_json_parts(source, ctx))
    assert isinstance(result, list) and len(result) == 1
    validated = normalize_multidim_event_payload(result)
    assert [row["event_id"] for row in validated[0]["Event"]] == ["E1", "E2"]


def test_multi_rule_profile_uses_actual_selected_flatten_column():
    from czjLLM.sql_mode.runtime.row_merger_generic import (
        _selected_slice_merge_output_col,
    )
    raw = ' [{"Event": [{"event_id": "E1"}]}] '
    ctx = SimpleNamespace(
        output_col="generic_json",
        output_profile="none",
        sql_writeback_rules=[
            {"output_col": "generic_json", "output_profile": "none"},
            {"output_col": "multidim_event_json", "output_profile": "multidim_event"},
        ],
        sql_flatten_writeback_rule=0,
    )
    write_map = {"generic_json": raw, "multidim_event_json": raw}
    selected = _selected_slice_merge_output_col(ctx, write_map, raw)
    assert selected == "generic_json"
    assert not is_multidim_event_slice_merge(ctx, output_col=selected)
    ctx.sql_flatten_writeback_rule = 1
    selected = _selected_slice_merge_output_col(ctx, write_map, raw)
    assert selected == "multidim_event_json"
    assert is_multidim_event_slice_merge(ctx, output_col=selected)


def test_mixed_profile_stage_defers_merge_until_per_field_writeback():
    from czjLLM.prompt_pipeline.pipeline_controller import (
        _merge_single_extract_stage_json_parts,
    )
    from czjLLM.utilities.slice_merge import needs_per_output_slice_merge

    ctx = SimpleNamespace(
        output_col="generic_json",
        output_profile="none",
        merge_log_changes=False,
        es_writeback_rules=[
            {"output_col": "generic_json", "source": "stage", "stage": "extract",
             "output_profile": "none"},
            {"output_col": "multidim_event_json", "source": "stage", "stage": "extract",
             "output_profile": "multidim_event"},
        ],
    )
    assert needs_per_output_slice_merge(ctx, source="stage")
    rows = [
        json.dumps([_article("E1", action="first")], ensure_ascii=False),
        json.dumps([_article("E1", action="second")], ensure_ascii=False),
    ]
    pending = json.loads(_merge_single_extract_stage_json_parts(rows, ctx))
    assert isinstance(pending, list) and len(pending) == 2
    assert [r["Event"][0]["event_id"] for r in pending] == ["E1", "E1"]
    # The Row Merger uses the raw list to make distinct profile-bound outputs.


@pytest.mark.parametrize("source", ["combined", "stage"])
def test_omitted_secondary_es_profile_infers_multidim_without_primary_leak(source):
    from czjLLM.utilities.slice_merge import needs_per_output_slice_merge
    from czjLLM.prompt_pipeline.pipeline_controller import (
        _merge_single_extract_stage_json_parts,
    )
    ctx = SimpleNamespace(
        output_col="generic_json",
        output_profile="none",
        merge_log_changes=False,
        es_writeback_rules=[
            {"output_col": "generic_json", "source": source, "output_profile": "none"},
            {"output_col": "multidim_event_json", "source": source},
        ],
    )
    assert not is_multidim_event_slice_merge(ctx, output_col="generic_json")
    assert is_multidim_event_slice_merge(ctx, output_col="multidim_event_json")
    assert needs_per_output_slice_merge(ctx, source=source)
    if source == "stage":
        parts = [
            json.dumps([_article("E1", action="first")]),
            json.dumps([_article("E1", action="second")]),
        ]
        result = json.loads(_merge_single_extract_stage_json_parts(parts, ctx))
        assert len(result) == 2
        assert [row["Event"][0]["event_id"] for row in result] == ["E1", "E1"]
    # An explicit non-multidim override must defeat the auto inference.
    ctx.es_writeback_rules[-1]["output_profile"] = "none"
    assert not is_multidim_event_slice_merge(ctx, output_col="multidim_event_json")
    assert not needs_per_output_slice_merge(ctx, source=source)


@pytest.mark.parametrize("implicit_profile", [True, False])
def test_source_consumer_not_primary_field_controls_strict_premerge(implicit_profile):
    from czjLLM.utilities.slice_merge import (
        is_multidim_event_source_merge,
        needs_per_output_slice_merge,
    )
    from czjLLM.prompt_pipeline.pipeline_controller import (
        _merge_single_extract_stage_json_parts,
    )

    strict_rule = {"output_col": "multidim_event_json", "source": "combined"}
    if not implicit_profile:
        strict_rule["output_profile"] = "multidim_event"

    ctx = SimpleNamespace(
        output_col="generic_json",
        output_profile="none",
        merge_log_changes=False,
        es_writeback_rules=[
            {"output_col": "generic_json", "source": "stage",
             "stage": "extract", "output_profile": "none"},
            strict_rule,
        ],
    )
    assert not needs_per_output_slice_merge(ctx, source="combined")
    assert not needs_per_output_slice_merge(ctx, source="stage")
    assert is_multidim_event_source_merge(ctx, source="combined")
    assert not is_multidim_event_source_merge(ctx, source="stage")
    assert not is_multidim_event_slice_merge(ctx)

    first = _article("E1", action="first")
    second = _article("E1", action="second")
    parts = [json.dumps([first]), json.dumps([second])]

    # Stage output consumes generic profile; its duplicate IDs are unchanged.
    stage = json.loads(_merge_single_extract_stage_json_parts(parts, ctx))
    assert isinstance(stage, dict)
    assert [event["event_id"] for event in stage["Event"]] == ["E1", "E1"]

    # Combined uses the strict consumer's actual profile, not ctx.output_col.
    merged, _ = merge_dict_slices_audited(
        [first, second],
        multidim_event=is_multidim_event_source_merge(ctx, source="combined"),
        logger=None,
    )
    validated = normalize_multidim_event_payload([merged])
    assert [event["event_id"] for event in validated[0]["Event"]] == ["E1", "E2"]
    assert [row["event_ids"] for row in validated[0]["Person"]] == [["E1"], ["E2"]]


def test_single_implicit_es_rule_can_override_unrelated_primary_field():
    ctx = SimpleNamespace(
        output_col="raw", output_profile="none",
        es_writeback_rules=[{"output_col": "multidim_event_json"}],
    )
    assert is_multidim_event_slice_merge(ctx)
    assert is_multidim_event_slice_merge(ctx, output_col="multidim_event_json")
    assert not is_multidim_event_slice_merge(ctx, output_col="raw")


def test_original_generic_contract_never_renumbers_events():
    x = _article("E1", action="one")
    y = _article("E1", action="two")
    plain, _ = merge_dict_slices_audited([x, y], logger=None)
    assert [e["event_id"] for e in plain["Event"]] == ["E1", "E1"]
    assert not is_multidim_event_slice_merge(
        SimpleNamespace(output_col="multidim_event_json",
                        output_profile="multidim_event_no_eventids"))
    assert not is_multidim_event_slice_merge(
        SimpleNamespace(output_col="generic_json", output_profile="auto"))
    assert is_multidim_event_slice_merge(
        SimpleNamespace(output_col="multidim_event_json", output_profile="auto"))
    assert is_multidim_event_slice_merge(
        SimpleNamespace(
            output_col="raw",
            output_profile="none",
            es_writeback_rules=[{
                "output_col": "multidim_event_json",
                "output_profile": "multidim_event",
            }],
        )
    )


def test_multidim_single_chunk_nested_impact_normalizes_without_remapping():
    item = _article("E1", action="single", impact_nested=True)
    assert normalize_multidim_event_payload([item])[0]["Impact"][0]["event_ids"] == ["E1"]


@pytest.mark.parametrize("flatten_rule", [0, 1, 2])
def test_row_merger_merges_unselected_deferred_stage_per_destination(
    tmp_path, monkeypatch, flatten_rule,
):
    """A different flatten source cannot skip a deferred stage's E1 repair."""
    from czjLLM.sql_mode.runtime import row_merger_generic as merger
    from czjLLM.sql_mode.runtime.multistage_writeback import WritebackPayload
    from czjLLM.utilities.slice_merge import needs_per_output_slice_merge

    stage_slices = [_article("E1", action="A"), _article("E1", action="B")]
    stage_text = json.dumps(stage_slices, ensure_ascii=False)
    combined_dict = {"status": "combined aggregate"}
    combined_text = json.dumps(combined_dict, ensure_ascii=False)

    class Registry:
        removed = False

        def list_items(self):
            return {} if self.removed else {str(item): meta}

        def remove(self, path):
            assert path == str(item)
            self.removed = True

    class ValidatingSink:
        def __init__(self):
            self.docs = []

        def open(self):
            pass

        def close(self):
            pass

        def write_main(self, pk, write_map, update_time=None):
            assert pk == "id-two-sources"
            assert json.loads(write_map["combined_json"]) == combined_dict
            generic = json.loads(write_map["stage_generic_json"])
            strict = normalize_multidim_event_payload(
                json.loads(write_map["multidim_event_json"])
            )
            assert isinstance(generic, dict)
            assert [x["event_id"] for x in generic["Event"]] == ["E1", "E1"]
            assert [x["event_id"] for x in strict[0]["Event"]] == ["E1", "E2"]
            assert [x["event_ids"] for x in strict[0]["Person"]] == [["E1"], ["E2"]]
            self.docs.append((generic, strict))

    item = tmp_path / "item"
    success = item / "Success"
    success.mkdir(parents=True)
    (success / "0.txt").write_text("done", encoding="utf-8")
    (success / "1.txt").write_text("done", encoding="utf-8")
    root = tmp_path / "source"
    root.mkdir()
    src = root / "input.txt"
    src.write_text("source", encoding="utf-8")
    result_file = tmp_path / "finished" / "combined.txt"
    result_file.parent.mkdir()
    result_file.write_text(combined_text, encoding="utf-8")

    meta = {"pk": "id-two-sources", "temp_txt": str(src),
            "CombBackFN": str(result_file)}
    ctx = SimpleNamespace(
        task="InfoExtraction-MultiDim-SQLFriendly-to_json_format",
        output_col="combined_json", output_profile="none",
        merge_slices=True, merge_dedup_lists=True, merge_log_changes=False,
        record_update_time=False, flatten_json_output=False,
        cleanup_prompt_item_after_writeback=False,
        llm_source_dir=str(root),
        llm_source_backup_dir=str(tmp_path / "backup"),
        sql_flatten_writeback_rule=flatten_rule,
        sql_writeback_rules=[
            {"output_col": "combined_json", "source": "combined",
             "output_profile": "none"},
            {"output_col": "stage_generic_json", "source": "stage",
             "stage": "extract", "output_profile": "none"},
            {"output_col": "multidim_event_json", "source": "stage",
             "stage": "extract", "output_profile": "multidim_event"},
        ],
    )
    assert needs_per_output_slice_merge(ctx, source="stage")

    def fake_resolve(rule_ctx, path, text):
        if rule_ctx.sql_writeback_source == "stage":
            return WritebackPayload(
                main_payload=stage_slices, main_text=stage_text,
                flatten_text=stage_text, source="stage:extract",
            )
        return WritebackPayload(
            main_payload=combined_dict, main_text=combined_text,
            flatten_text=combined_text, source="combined",
        )

    monkeypatch.setattr(merger, "resolve_writeback_payload", fake_resolve)
    sink = ValidatingSink()
    reg = Registry()
    merger.row_merger_watchdog_generic(
        ctx, reg, lambda *_: None,
        SimpleNamespace(is_set=lambda: True), sink,
        scan_interval=0.01,
    )
    assert reg.removed
    assert len(sink.docs) == 1


def test_deferred_invalid_stage_reference_blocks_fallback_reclaim(tmp_path, monkeypatch):
    """Mixed stage references can fail outside direct legacy merge guards."""
    import queue
    from czjLLM.sql_mode.runtime import row_merger_generic as merger
    from czjLLM.sql_mode.runtime.multistage_writeback import WritebackPayload
    from czjLLM.reduction.production_control import (
        finish_legacy_merge_item, try_begin_legacy_merge_item,
    )

    stage_parts = [_article("E1", action="first"), _article("E1", action="second")]
    stage_parts[1]["Person"][0]["event_ids"] = ["E3"]
    stage_text = json.dumps(stage_parts)
    combined_text = json.dumps({"status": "previously combined"})
    item = tmp_path / "item"
    success = item / "Success"
    success.mkdir(parents=True)
    (success / "0.txt").write_text("preserved answer", encoding="utf-8")
    source = tmp_path / "input.txt"
    source.write_text("preserved input", encoding="utf-8")
    output = tmp_path / "combined.json"
    output.write_text(combined_text, encoding="utf-8")
    claims_at_removal, writes, releases, audits = [], [], [], []

    class Registry:
        removed = False
        def list_items(self):
            return {} if self.removed else {str(item): meta}
        def remove(self, path):
            assert path == str(item)
            claims_at_removal.append(try_begin_legacy_merge_item(ctx, path))
            self.removed = True

    meta = {"pk": "bad-stage-fk", "temp_txt": str(source),
            "CombBackFN": str(output)}
    ctx = SimpleNamespace(
        output_col="combined_json", output_profile="none",
        merge_slices=True, merge_log_changes=False,
        record_update_time=False, flatten_json_output=False,
        llm_source_dir=str(tmp_path), llm_source_backup_dir=str(tmp_path / "backup"),
        sql_flatten_writeback_rule=0,
        sql_writeback_rules=[
            {"output_col": "combined_json", "source": "combined", "output_profile": "none"},
            {"output_col": "stage_generic_json", "source": "stage",
             "stage": "extract", "output_profile": "none"},
            {"output_col": "multidim_event_json", "source": "stage",
             "stage": "extract", "output_profile": "multidim_event"},
        ],
    )

    def resolve(rule_ctx, path, text):
        if rule_ctx.sql_writeback_source == "stage":
            return WritebackPayload(
                main_payload=stage_parts, main_text=stage_text,
                flatten_text=stage_text, source="stage:extract",
            )
        return WritebackPayload(
            main_payload={"status": "previously combined"},
            main_text=combined_text, flatten_text=combined_text,
            source="combined",
        )

    class Sink:
        def open(self): pass
        def close(self): pass
        def write_main(self, *_args, **_kwargs): writes.append(True)

    monkeypatch.setattr(merger, "resolve_writeback_payload", resolve)
    monkeypatch.setattr(merger, "mark_not_running",
                        lambda _ctx, pk, state: releases.append((pk, state)))
    monkeypatch.setattr(merger, "record_adjustment",
                        lambda _ctx, event, pk=None, **kw:
                            audits.append((event, pk, kw)) or None)
    done_q = queue.Queue()
    registry = Registry()
    merger.row_merger_watchdog_generic(
        ctx, registry, lambda *_: None,
        SimpleNamespace(is_set=lambda: True), Sink(),
        scan_interval=0.001, done_q=done_q,
    )

    assert registry.removed and not writes
    assert claims_at_removal == [False]
    assert releases == [("bad-stage-fk", "writeback_failed_schema")]
    assert len(audits) == 1
    assert "E3" in audits[0][2]["error"]
    assert done_q.get_nowait() == 1 and done_q.empty()
    finish_legacy_merge_item(ctx, str(item), success=False)
    finish_legacy_merge_item(ctx, str(item), success=True)
    assert not try_begin_legacy_merge_item(ctx, str(item))
    assert try_begin_legacy_merge_item(SimpleNamespace(), str(item))
    assert source.read_text(encoding="utf-8") == "preserved input"
    assert (success / "0.txt").exists() and output.exists()


@pytest.mark.parametrize("flatten_idx", [None, 0, 1], ids=["single", "generic", "strict"])
def test_actual_row_merger_writes_two_e1_slices_via_es_profile(tmp_path, flatten_idx):
    """Exercise production watchdog and production ES profile without a live ES server."""
    from czjLLM.sql_mode.runtime.row_merger_generic import row_merger_watchdog_generic

    class Registry:
        def __init__(self, root, meta):
            self.root, self.meta, self.removed = root, meta, False

        def list_items(self):
            return {} if self.removed else {self.root: self.meta}

        def remove(self, _):
            self.removed = True

    class Sink:
        def __init__(self):
            self.docs = []

        def open(self):
            pass

        def close(self):
            pass

        def write_main(self, pk, value, update_time=None):
            serialized = value["multidim_event_json"]
            self.docs.append((
                pk,
                normalize_multidim_event_payload(json.loads(serialized)),
                json.loads(value["generic_json"]) if "generic_json" in value else None,
            ))

    item = tmp_path / "item"
    (item / "Success").mkdir(parents=True)
    (item / "Success" / "0.txt").write_text("success", encoding="utf-8")
    (item / "Success" / "1.txt").write_text("success", encoding="utf-8")
    source = tmp_path / "src" / "cache" / "input.txt"
    source.parent.mkdir(parents=True)
    source.write_text("raw input", encoding="utf-8")
    combined = tmp_path / "finished" / "cache" / "merged.txt"
    combined.parent.mkdir(parents=True)
    combined.write_text(
        json.dumps([
            _article("E1", action="first", impact_nested=True),
            _article("E1", action="second", impact_nested=True),
        ], ensure_ascii=False),
        encoding="utf-8",
    )
    registry = Registry(str(item), {
        "pk": "sample-id", "temp_txt": str(source), "CombBackFN": str(combined),
    })
    sink = Sink()
    ctx = SimpleNamespace(
        task="InfoExtraction-MultiDim-SQLFriendly-to_json_format",
        output_col="multidim_event_json",
        output_profile="multidim_event",
        merge_slices=True,
        merge_dedup_lists=True,
        merge_log_changes=False,
        record_update_time=False,
        flatten_json_output=False,
        cleanup_prompt_item_after_writeback=False,
        llm_source_dir=str(tmp_path / "src"),
        llm_source_backup_dir=str(tmp_path / "backup"),
    )
    if flatten_idx is not None:
        ctx.output_col = "generic_json"
        ctx.output_profile = "none"
        ctx.sql_flatten_writeback_rule = flatten_idx
        ctx.sql_writeback_rules = [
            {"output_col": "generic_json", "source": "combined",
             "output_profile": "none"},
            {"output_col": "multidim_event_json", "source": "combined",
             "output_profile": "multidim_event"},
        ]
    row_merger_watchdog_generic(
        ctx, registry, lambda *_: None,
        SimpleNamespace(is_set=lambda: True),
        sink, scan_interval=0.01,
    )
    assert registry.removed
    assert len(sink.docs) == 1
    pk, docs, generic = sink.docs[0]
    assert pk == "sample-id"
    assert [e["event_id"] for e in docs[0]["Event"]] == ["E1", "E2"]
    if flatten_idx is not None:
        assert isinstance(generic, dict)
        assert [e["event_id"] for e in generic["Event"]] == ["E1", "E1"]
    assert [r["event_ids"] for r in docs[0]["Impact"]] == [["E1"], ["E2"]]
