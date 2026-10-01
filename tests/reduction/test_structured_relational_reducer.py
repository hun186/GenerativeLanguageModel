from copy import deepcopy
from types import MappingProxyType

import pytest

from czjLLM.es_mode.output_profiles import get_default_registry as output_profiles
from czjLLM.reduction import (
    ReductionConfigError, StructuredRelationalError, StructuredRelationalReducer,
    get_default_registry, parse_reduction_config, reduce_single_pass,
)


ENTITIES = [{"name": "events", "collection_path": "Event", "id_field": "event_id", "canonical_prefix": "E"}]
REFERENCES = [
    {"collection_path": name, "field": "event_ids", "target": "events"}
    for name in ("Person", "Involved_Parties", "Impact", "Event_Timeline", "evidence_snippets")
]


def reducer():
    return StructuredRelationalReducer(ENTITIES, REFERENCES)


def record(action="same", ids=("E1",)):
    refs = list(ids)
    return {
        "article_date_iso": None, "article_date_precision": "unknown",
        "Event": [{"event_id": value, "action": action, "time_raw": None,
                   "time_iso": None, "time_precision": "unknown", "consequence": None}
                  for value in ids],
        "Person": [{"name": "Alice", "event_ids": refs}],
        "Involved_Parties": [{"label": "x", "event_ids": refs}],
        "Impact": [{"description": "x", "event_ids": refs}],
        "Event_Timeline": [{"description": "x", "time_raw": None, "time_iso": None,
                            "time_precision": "unknown", "event_ids": refs}],
        "evidence_snippets": [{"text": "E1 remains text", "event_ids": refs}],
        "unrelated": "E1",
    }


def test_constructor_registry_metadata_and_config_are_fail_closed_and_immutable():
    with pytest.raises(StructuredRelationalError):
        StructuredRelationalReducer()
    prototype = StructuredRelationalReducer._registry_prototype()
    with pytest.raises(StructuredRelationalError):
        prototype.reduce([])
    registry = get_default_registry()
    assert registry.normalize_name("relational") == "structured_relational"
    assert isinstance(registry.get("structured_relational"), StructuredRelationalReducer)
    configured = parse_reduction_config({"enabled": True, "profile": "relational",
                                         "options": {"entity_sets": ENTITIES, "references": REFERENCES}})
    assert configured.profile == "structured_relational"
    assert isinstance(configured.options, MappingProxyType)
    assert isinstance(configured.options["entity_sets"], tuple)
    assert isinstance(configured.options["entity_sets"][0], MappingProxyType)
    assert reducer().requires_stable_order and reducer().preserves_order


@pytest.mark.parametrize("options", [
    {}, {"entity_sets": [], "references": []},
    {"entity_sets": ENTITIES, "references": [], "extra": 1},
    {"entity_sets": [ENTITIES[0], ENTITIES[0]], "references": []},
    {"entity_sets": [ENTITIES[0], {"name": "people", "collection_path": "Person", "id_field": "id", "canonical_prefix": "E"}], "references": []},
    {"entity_sets": ENTITIES, "references": [{"collection_path": "Person", "field": "event_ids", "target": "missing"}]},
])
def test_invalid_configuration_fails_during_parsing(options):
    with pytest.raises(Exception):
        parse_reduction_config({"enabled": True, "profile": "structured_relational", "options": options})


def _entity(name, path, field, prefix):
    return {"name": name, "collection_path": path, "id_field": field,
            "canonical_prefix": prefix}


@pytest.mark.parametrize("left,right", [("E", "E1"), ("E", "E12"),
                                          ("E1", "E11"), ("REL", "REL9")])
def test_overlapping_prefix_namespaces_fail_at_constructor_and_config(left, right):
    entities = [_entity("left", "Left", "id", left),
                _entity("right", "Right", "id", right)]
    with pytest.raises(StructuredRelationalError, match="overlapping canonical prefix"):
        StructuredRelationalReducer(entities, [])
    with pytest.raises(ReductionConfigError, match="overlapping canonical prefix"):
        parse_reduction_config({"enabled": True, "profile": "structured_relational",
                                "options": {"entity_sets": entities, "references": []}})


@pytest.mark.parametrize("left,right", [("E", "P"), ("E", "EVENT"),
                                          ("E", "E0"), ("A_", "A1")])
def test_disjoint_prefix_namespaces_remain_valid(left, right):
    entities = [_entity("left", "Left", "id", left),
                _entity("right", "Right", "id", right)]
    direct = StructuredRelationalReducer(entities, [])
    parsed = parse_reduction_config({"enabled": True, "profile": "structured_relational",
                                     "options": {"entity_sets": entities, "references": []}})
    assert len(direct.entity_sets) == len(parsed.options["entity_sets"]) == 2


def test_duplicate_entity_endpoint_fails_at_constructor_and_config():
    entities = [_entity("events_a", "Event", "event_id", "E"),
                _entity("events_b", "Event", "event_id", "X")]
    with pytest.raises(StructuredRelationalError, match="duplicate entity endpoint"):
        StructuredRelationalReducer(entities, [])
    with pytest.raises(ReductionConfigError, match="duplicate entity endpoint"):
        parse_reduction_config({"enabled": True, "profile": "structured_relational",
                                "options": {"entity_sets": entities, "references": []}})


@pytest.mark.parametrize("targets", [("events", "events"), ("events", "incidents")])
def test_duplicate_reference_endpoint_fails_for_same_or_different_targets(targets):
    entities = [_entity("events", "Event", "event_id", "E"),
                _entity("incidents", "Incident", "incident_id", "I")]
    references = [{"collection_path": "Person", "field": "event_ids", "target": target}
                  for target in targets]
    with pytest.raises(StructuredRelationalError, match="duplicate reference endpoint"):
        StructuredRelationalReducer(entities, references)
    with pytest.raises(ReductionConfigError, match="duplicate reference endpoint"):
        parse_reduction_config({"enabled": True, "profile": "structured_relational",
                                "options": {"entity_sets": entities, "references": references}})


def test_entity_reference_endpoint_conflict_fails_at_constructor_and_config():
    entities = [_entity("events", "Event", "event_id", "E"),
                _entity("people", "Person", "event_ids", "P")]
    references = [{"collection_path": "Person", "field": "event_ids", "target": "events"}]
    with pytest.raises(StructuredRelationalError, match="entity/reference endpoint conflict"):
        StructuredRelationalReducer(entities, references)
    with pytest.raises(ReductionConfigError, match="entity/reference endpoint conflict"):
        parse_reduction_config({"enabled": True, "profile": "structured_relational",
                                "options": {"entity_sets": entities, "references": references}})


def test_shared_collection_with_distinct_entity_and_reference_fields_is_valid():
    entities = [_entity("events", "Event", "event_id", "E"),
                _entity("people", "Person", "person_id", "P")]
    references = [{"collection_path": "Person", "field": "event_ids", "target": "events"}]
    direct = StructuredRelationalReducer(entities, references)
    parsed = parse_reduction_config({"enabled": True, "profile": "structured_relational",
                                     "options": {"entity_sets": entities,
                                                 "references": references}})
    assert direct.references[0].field == parsed.options["references"][0]["field"] == "event_ids"


def test_composite_and_hierarchical_use_are_rejected():
    with pytest.raises(Exception, match="inside composite"):
        parse_reduction_config({"enabled": True, "profile": "composite", "options": {"steps": [
            {"profile": "structured_relational", "options": {"entity_sets": ENTITIES, "references": []}}
        ]}})
    with pytest.raises(Exception, match="concat_text only"):
        parse_reduction_config({"enabled": True, "controller": "fixed_rounds",
                                "profile": "structured_relational",
                                "options": {"entity_sets": ENTITIES, "references": []},
                                "controller_options": {"rounds": 2}, "runtime": {"round_task": "x"}})


def test_two_pass_assignment_rewrites_all_references_preserves_order_and_does_not_merge():
    original = [record("same", ("E1", "E2")), record("same", ("E1",))]
    snapshot = deepcopy(original)
    result = reducer().reduce(original)
    assert [[item["event_id"] for item in row["Event"]] for row in result.payload] == [["E1", "E2"], ["E3"]]
    for collection in ("Person", "Involved_Parties", "Impact", "Event_Timeline", "evidence_snippets"):
        assert result.payload[0][collection][0]["event_ids"] == ["E1", "E2"]
        assert result.payload[1][collection][0]["event_ids"] == ["E3"]
    assert len(result.payload) == 2 and result.payload[1]["Event"][0]["action"] == "same"
    assert result.payload[1]["unrelated"] == "E1"
    assert result.payload[1]["evidence_snippets"][0]["text"] == "E1 remains text"
    assert original == snapshot
    assert result.changed
    assert result.metrics == {"input_record_count": 2, "output_record_count": 2,
                              "entity_count": 3, "reference_count": 15,
                              "remapped_id_count": 1, "remapped_reference_count": 5}
    assert set(result.audit) == {"remap_count", "remap_fingerprint", "entity_set_count", "reference_spec_count"}
    assert len(result.audit["remap_fingerprint"]) == 64 and "payload" not in result.audit
    assert [dict(item) for item in result.provenance["id_remap"]] == [
        {"record_index": 0, "entity_set": "events", "local_id": "E1", "canonical_id": "E1"},
        {"record_index": 0, "entity_set": "events", "local_id": "E2", "canonical_id": "E2"},
        {"record_index": 1, "entity_set": "events", "local_id": "E1", "canonical_id": "E3"},
    ]


def test_one_level_flatten_and_immutable_payload_work_without_mutation():
    frozen = MappingProxyType({key: tuple(MappingProxyType(member) for member in value)
                               if isinstance(value, list) else value
                               for key, value in record().items()})
    result = reducer().reduce(((frozen,),))
    assert result.payload[0]["Event"][0]["event_id"] == "E1"
    assert isinstance(result.payload, list) and isinstance(result.payload[0], dict)
    assert not result.changed


def test_empty_valid_input_and_empty_references_are_safe():
    empty = StructuredRelationalReducer(ENTITIES, []).reduce([])
    assert empty.payload == [] and not empty.changed
    value = record(); value["Person"][0]["event_ids"] = []
    assert reducer().reduce([value]).payload[0]["Person"][0]["event_ids"] == []


@pytest.mark.parametrize("mutate, message", [
    (lambda rows: rows[0]["Event"].append(dict(rows[0]["Event"][0])), "duplicate local ID"),
    (lambda rows: rows[0]["Person"][0].__setitem__("event_ids", ["E1", "E1"]), "duplicate reference"),
    (lambda rows: rows[0]["Person"][0].__setitem__("event_ids", ["E9"]), "unknown local reference"),
    (lambda rows: rows[0].pop("Event"), "missing entity collection"),
    (lambda rows: rows[0].__setitem__("Event", {}), "must be a list or tuple"),
    (lambda rows: rows[0].__setitem__("Event", [1]), "entity member"),
    (lambda rows: rows[0]["Event"][0].pop("event_id"), "missing ID field"),
    (lambda rows: rows[0]["Event"][0].__setitem__("event_id", " E1"), "local ID"),
    (lambda rows: rows[0]["Person"][0].pop("event_ids"), "missing reference field"),
    (lambda rows: rows[0]["Person"].__setitem__(0, 1), "reference member"),
])
def test_malformed_relational_data_fails_explicitly(mutate, message):
    rows = [record()]; mutate(rows)
    with pytest.raises(StructuredRelationalError, match=message):
        reducer().reduce(rows)


@pytest.mark.parametrize("items", [["bad"], [1], [[[record()]]], [[record(), "bad"]]])
def test_invalid_or_deeper_input_shapes_fail(items):
    with pytest.raises(StructuredRelationalError, match="must be a mapping"):
        reducer().reduce(items)


def test_multiple_entity_sets_have_independent_counters_and_unique_prefixes():
    configured = StructuredRelationalReducer(
        ENTITIES + [{"name": "people", "collection_path": "Actors", "id_field": "person_id", "canonical_prefix": "P"}], [])
    result = configured.reduce([{"Event": [{"event_id": "x"}], "Actors": [{"person_id": "x"}, {"person_id": "y"}]}])
    assert result.payload == [{"Event": [{"event_id": "E1"}], "Actors": [{"person_id": "P1"}, {"person_id": "P2"}]}]


def test_multidim_output_profile_compatibility_and_global_uniqueness():
    values = [record("A"), record("B")]
    for value in values:
        value.pop("unrelated")
        value["Involved_Parties"] = []
        value["Impact"] = []
        value["evidence_snippets"] = []
    result = reducer().reduce(values)
    ids = [row["Event"][0]["event_id"] for row in result.payload]
    assert ids == ["E1", "E2"] and len(ids) == len(set(ids))
    normalized = output_profiles().normalize_payload("multidim_event", result.payload)
    assert normalized[1]["Person"][0]["event_ids"] == ["E2"]
