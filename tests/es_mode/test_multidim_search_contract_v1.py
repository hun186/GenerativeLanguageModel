"""Pinned, offline GLM MultiDim search-consumer contract (v1).

Only GLM's MultiDim task/profile is covered. No SRAF import, ES requests,
operator data, pipeline execution, mapping writes or implicit migrations.
"""
from copy import deepcopy
import json
from pathlib import Path

import pytest
import yaml

from czjLLM.common.multidim_profile_audit import classify_stored_profile
from czjLLM.common.required_output_guard import evaluate_required_output_checks
from czjLLM.es_mode.output_profiles.multidim_event import (
    _EVENT_FIELDS, _LINKED_FIELDS, _TOP_LEVEL_FIELDS,
    normalize_multidim_event_payload,
)

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "czjLLM/es_mode/contracts/multidim_search_v1.json"
RULE = {
    "full_path": "multidim_event_json",
    "validator": "multidim_event_time",
    "min_valid_count": 1,
    "allow_empty_events": True,
}


def _contract():
    return json.loads(CONTRACT.read_text(encoding="utf-8"))


def _mapping():
    path = ROOT / _contract()["mapping_source"]
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _field(mapping, parts):
    node = mapping
    for part in parts:
        if part in node.get("properties", {}):
            node = node["properties"][part]
        elif part in node.get("fields", {}):
            node = node["fields"][part]
        else:
            raise AssertionError("contract_field_missing:" + ".".join(parts))
    return node


def _block(*, events=None, timeline=None, evidence=None):
    return {
        "article_date_iso": "2026-11-16",
        "article_date_precision": "day",
        "article_title": "Synthetic source only",
        "Event": ([{
            "event_id": "E1", "subject": "Taiwan", "object": "policy",
            "time_iso": "2026-11-15", "time_precision": "day",
            "time_raw": "2026-11-15",
        }] if events is None else events),
        "Event_Timeline": [] if timeline is None else timeline,
        "evidence_snippets": ([{"event_ids": ["E1"], "text": "synthetic evidence"}]
                              if evidence is None else evidence),
    }


def test_contract_version_is_task_scoped_not_framework_global():
    spec = _contract()
    assert spec["schema_version"] == 1
    assert spec["contract_id"] == "glm.multidim_event.search_consumer"
    assert spec["output_field"] == "multidim_event_json"
    assert spec["output_shape"] == "nonempty_array_of_article_blocks"
    assert spec["semantics"]["source_fidelity_verified_by_this_contract"] is False


def test_all_consumer_nested_paths_and_mapping_types_match_current_glm_yaml():
    spec = _contract()
    mapping = _mapping()
    root = _field(mapping, ["multidim_event_json"])
    assert root["type"] == "nested" and root["dynamic"] == "strict"
    for path in spec["nested_paths"]:
        assert _field(mapping, path.split("."))["type"] == "nested", path
    for path, expected in spec["field_types"].items():
        assert _field(root, path.split("."))["type"] == expected, path
    for path, expected in spec["date_formats"].items():
        assert _field(root, path.split("."))["format"] == expected, path


def test_consumer_fields_exist_in_output_profile_whitelist():
    spec = _contract()
    for field in spec["field_types"]:
        parts = field.split(".")
        head = parts[0]
        assert head in _TOP_LEVEL_FIELDS, head
        if head == "Event":
            assert parts[1] in _EVENT_FIELDS, field
        if head in _LINKED_FIELDS:
            assert parts[1] in _LINKED_FIELDS[head], field


@pytest.mark.parametrize("case, expected", [
    ("event_only", "PROFILE_ACCEPTED_EVENT_DATE_EMPTY_TIMELINE"),
    ("event_no_evidence", "PROFILE_ACCEPTED_EVENT_DATE_EMPTY_TIMELINE"),
    ("timeline", "PROFILE_ACCEPTED_EVENT_AND_TIMELINE_DATES"),
    ("unknown", "PROFILE_ACCEPTED_DATE_UNKNOWN"),
    ("empty_event", "PROFILE_ACCEPTED_NO_EVENTS"),
    ("invalid_event_link", "PROFILE_REJECTED"),
])
def test_profile_fixture_cases_remain_sraf_consumable_without_semantic_invention(case, expected):
    item = _block()
    if case == "event_no_evidence":
        item["evidence_snippets"] = []
    elif case == "timeline":
        item["Event_Timeline"] = [{
            "event_ids": ["E1"], "time_iso": "2026-11-16",
            "time_raw": "2026-11-16", "time_precision": "day",
            "description": "Milestone",
        }]
    elif case == "unknown":
        item["Event"][0].update(
            time_iso=None, time_raw=None, time_precision="unknown")
    elif case == "empty_event":
        item = _block(events=[], evidence=[])
    elif case == "invalid_event_link":
        item["evidence_snippets"][0]["event_ids"] = ["MISSING"]
    source = {"multidim_event_json": [item]}
    original = deepcopy(source)
    assert classify_stored_profile(source) == expected
    assert source == original
    if expected != "PROFILE_REJECTED":
        normalized = normalize_multidim_event_payload(source["multidim_event_json"])
        assert isinstance(normalized, list) and len(normalized) == 1


def test_empty_events_require_specific_task_optin_not_absent_output():
    empty = {"multidim_event_json": [_block(events=[], evidence=[])]}
    assert evaluate_required_output_checks(empty, [RULE]) == (True, None)
    assert evaluate_required_output_checks(
        empty, [{k: v for k, v in RULE.items() if k != "allow_empty_events"}]
    )[0] is False
    assert evaluate_required_output_checks(
        {"multidim_event_json": []}, [RULE])[0] is False
    assert evaluate_required_output_checks(
        {"multidim_event_json": [_block(events=[], evidence=[
            {"event_ids": [], "text": "orphan evidence"}
        ])]}, [RULE])[0] is False


def test_link_scope_and_source_date_are_explicit_not_inferred():
    semantics = _contract()["semantics"]
    assert semantics["event_id_scope"] == "per_multidim_event_json_article_block"
    assert semantics["link_field"] == "Event.event_id"
    assert semantics["linked_id_field"] == "event_ids"
    assert set(semantics["linked_arrays"]) == set(_LINKED_FIELDS)
    assert semantics["timeline_may_be_empty"] is True
    assert semantics["evidence_may_be_empty"] is True
    assert semantics["article_date_is_not_event_date"] is True
    assert semantics["evidence_text_requires_source_validation"] == "consumer_responsibility"
