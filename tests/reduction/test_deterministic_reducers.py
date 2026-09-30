import math
from pathlib import Path

import pytest

from czjLLM.reduction import (
    CompositeReducer, DedupReducer, DeterministicReducerError, EntityUnionReducer,
    GroupReducer, RankReducer, TopKReducer, parse_reduction_config, reduce_single_pass,
)


def test_dedup_whole_value_is_exact_first_wins_and_ordered():
    first = {"id": 1, "title": "A"}
    result = DedupReducer().reduce([first, {"title": "A", "id": 1}, {"id": 1, "title": "B"}])
    assert result.payload == [first, {"id": 1, "title": "B"}]
    assert result.payload[0] is first
    assert result.changed and result.metrics == {"input_count": 3, "output_count": 2, "duplicate_count": 1}


def test_dedup_composite_nested_key_and_missing_path():
    items = [{"meta": {"id": [1, {"x": True}]}, "v": "first"},
             {"meta": {"id": [1, {"x": True}]}, "v": "second"}]
    assert DedupReducer(("meta.id",)).reduce(items).payload == items[:1]
    with pytest.raises(DeterministicReducerError, match="Missing required path"):
        DedupReducer(("missing",)).reduce(items)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), object(), {1: "bad"}])
def test_dedup_rejects_non_json_values(value):
    with pytest.raises(DeterministicReducerError):
        DedupReducer().reduce([value])


def test_group_exact_shape_first_seen_and_member_order():
    items = [
        {"day": "d2", "category": {"x": 1}, "created_at": 2, "host": "a", "timestamp": 4},
        {"day": "d1", "category": {"x": 2}},
        {"day": "d2", "category": {"x": 1}, "created_at": 3},
    ]
    result = GroupReducer(("day", "category")).reduce(items)
    assert result.payload[0] == {"key": [{"path": "day", "value": "d2"}, {"path": "category", "value": {"x": 1}}], "items": [items[0], items[2]]}
    assert result.payload[1]["items"] == [items[1]]
    assert result.metrics == {"input_count": 3, "group_count": 2}
    assert GroupReducer(("day", "category")).reduce(items).payload == result.payload


def test_group_source_style_names_and_missing_path():
    item = {"created_at": "x", "host": "h", "timestamp": 1}
    assert GroupReducer(("created_at", "host", "timestamp")).reduce([item]).payload[0]["items"] == [item]
    with pytest.raises(DeterministicReducerError, match="Missing required path"):
        GroupReducer(("missing",)).reduce([item])


def test_entity_union_flattens_one_level_and_never_merges_conflicts():
    first = {"id": 1, "name": "A"}; conflict = {"id": 1, "name": "B"}
    result = EntityUnionReducer(("id",)).reduce([[first], conflict, {"id": 2}])
    assert result.payload == [first, {"id": 2}]
    assert result.metrics == {"input_count": 3, "entity_input_count": 3, "output_count": 2, "duplicate_count": 1}
    assert EntityUnionReducer().reduce([[first, {"name": "A", "id": 1}]]).payload == [first]
    with pytest.raises(DeterministicReducerError, match="must be a mapping"):
        EntityUnionReducer().reduce([[first, 3]])


def test_rank_numeric_direction_and_stable_ties():
    items = [{"id": "two", "score": 2}, {"id": "ten-a", "score": 10.0}, {"id": "ten-b", "score": 10}]
    assert [x["id"] for x in RankReducer("score").reduce(items).payload] == ["ten-a", "ten-b", "two"]
    assert [x["id"] for x in RankReducer("score", False).reduce(items).payload] == ["two", "ten-a", "ten-b"]


@pytest.mark.parametrize("score", [True, "10", float("nan"), float("inf")])
def test_rank_rejects_invalid_scores(score):
    with pytest.raises(DeterministicReducerError, match="finite|NaN/Infinity"):
        RankReducer("score").reduce([{"score": score}])


def test_rank_rejects_missing_path_and_non_mapping():
    with pytest.raises(DeterministicReducerError): RankReducer("score").reduce([{}])
    with pytest.raises(DeterministicReducerError): RankReducer("score").reduce([1])


@pytest.mark.parametrize(("k", "expected"), [(1, [1]), (2, [1, 2]), (3, [1, 2, 3]), (9, [1, 2, 3])])
def test_top_k(k, expected):
    assert TopKReducer(k).reduce([1, 2, 3]).payload == expected


@pytest.mark.parametrize("k", [0, -1, True])
def test_top_k_invalid(k):
    with pytest.raises(DeterministicReducerError): TopKReducer(k).reduce([1])


def _config(k=2):
    return parse_reduction_config({"enabled": True, "profile": "composite", "options": {"steps": [
        {"profile": "dedup", "options": {"key_paths": ["id"]}},
        {"profile": "rank", "options": {"score_path": "score"}},
        {"profile": "top_k", "options": {"k": k}},
    ]}})


def test_composite_production_chain_is_repeatable_and_bounded():
    items = [{"id": "a", "score": 2}, {"id": "a", "score": 99}, {"id": "b", "score": 10}, {"id": "c", "score": 10}]
    one = reduce_single_pass(items, _config()); two = reduce_single_pass(items, _config())
    assert one.payload == two.payload == [items[2], items[3]]
    assert one.profile == "composite" and one.contract_version == "1"
    assert one.metrics == {"step_count": 3, "input_count": 4, "output_count": 2}
    assert len(one.audit["steps"]) == 3 and all("payload" not in step for step in one.audit["steps"])


def test_composite_concat_json_then_union_and_order_metadata():
    config = parse_reduction_config({"enabled": True, "profile": "composite", "options": {"steps": [
        {"profile": "concat_json_list"}, {"profile": "entity_union", "options": {"key_paths": ["id"]}}
    ]}})
    result = reduce_single_pass([[{"id": 1}], {"id": 1}, {"id": 2}], config)
    assert result.payload == [{"id": 1}, {"id": 2}]
    reducer = CompositeReducer((DedupReducer(), RankReducer("score")))
    assert reducer.requires_stable_order is True and reducer.preserves_order is False


def test_composite_handoff_wraps_strings_and_mappings():
    class Capture:
        profile = "capture"; contract_version = "1"; requires_stable_order = False; preserves_order = True
        def __init__(self): self.seen = None
        def reduce(self, items, context=None):
            from czjLLM.reduction import ReducerResult
            self.seen = list(items); return ReducerResult(self.seen, self.profile, "1", False)
    for payload in ("abc", {"a": 1}):
        class Produce(Capture):
            def reduce(self, items, context=None):
                from czjLLM.reduction import ReducerResult
                return ReducerResult(payload, "produce", "1", False)
        capture = Capture(); CompositeReducer((Produce(), capture)).reduce([0])
        assert capture.seen == [payload]


def test_deterministic_module_is_source_and_model_independent():
    text = Path("czjLLM/reduction/reducers/deterministic.py").read_text(encoding="utf-8").lower()
    for forbidden in ("sql_mode", "es_mode", "sqliteadapter", "mssqladapter", "elasticsearchadapter", "sqlsink", "essink", "row_merger", "openai", "ollama", "callllmapi", "promptgenerator", "tokenizerwrapper"):
        assert forbidden not in text
