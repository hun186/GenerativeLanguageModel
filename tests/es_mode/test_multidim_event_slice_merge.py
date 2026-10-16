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
    merged, _ = merge_dict_slices_audited(
        [left, right], multidim_event=True, logger=None,
    )
    assert [e["event_id"] for e in merged["Event"]] == ["E1", "E3"]
    with pytest.raises(ValueError, match="references missing Event.event_id 'E2'"):
        normalize_multidim_event_payload([merged])


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


def test_actual_row_merger_writes_two_e1_slices_via_es_profile(tmp_path):
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
            self.docs.append((pk, normalize_multidim_event_payload(json.loads(serialized))))

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
    row_merger_watchdog_generic(
        ctx, registry, lambda *_: None,
        SimpleNamespace(is_set=lambda: True),
        sink, scan_interval=0.01,
    )
    assert registry.removed
    assert len(sink.docs) == 1
    pk, docs = sink.docs[0]
    assert pk == "sample-id"
    assert [e["event_id"] for e in docs[0]["Event"]] == ["E1", "E2"]
    assert [r["event_ids"] for r in docs[0]["Impact"]] == [["E1"], ["E2"]]
