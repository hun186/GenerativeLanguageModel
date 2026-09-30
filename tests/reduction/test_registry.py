from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Optional

from czjLLM.reduction import ReducerRegistry, ReducerResult, get_default_registry


@dataclass(frozen=True)
class ExampleReducer:
    profile: str = "example"
    contract_version: str = "test"
    requires_stable_order: bool = False
    preserves_order: bool = True

    def reduce(
        self,
        items: Iterable[Any],
        context: Optional[Mapping[str, Any]] = None,
    ) -> ReducerResult:
        return ReducerResult(list(items), self.profile, self.contract_version, False)


def test_default_registry_contains_all_pr_b_builtins():
    registry = get_default_registry()

    assert registry.has("concat_text")
    assert registry.has("concat_json_list")
    assert registry.has("legacy_json_deep_merge")
    for profile in ("dedup", "group", "entity_union", "rank", "top_k", "composite"):
        assert registry.has(profile)


def test_profile_names_are_canonicalized_and_aliases_resolve():
    registry = get_default_registry()

    assert registry.normalize_name(" LEGACY-json   deep-merge ") == "legacy_json_deep_merge"
    assert registry.get("legacy json deep merge") is registry.get("legacy_json_deep_merge")
    assert registry.get("text-concat") is registry.get("concat_text")
    for alias, canonical in (("deduplicate", "dedup"), ("exact-dedup", "dedup"),
                             ("group-by", "group"), ("union", "entity_union"),
                             ("exact-union", "entity_union"), ("topk", "top_k"), ("top-k", "top_k")):
        assert registry.get(alias) is registry.get(canonical)


def test_unknown_profile_is_observable_without_unrelated_fallback():
    registry = get_default_registry()

    assert registry.has("not_a_reducer") is False
    assert registry.get("not_a_reducer") is None


def test_registry_instances_do_not_contaminate_each_other_or_default_registry():
    first = ReducerRegistry()
    second = ReducerRegistry()
    first.register("example", ExampleReducer(), aliases=("sample",))

    assert first.has("sample")
    assert second.has("example") is False
    assert get_default_registry().has("example") is False


def test_builtin_reducer_metadata_is_explicit():
    registry = get_default_registry()

    for profile in ("concat_text", "concat_json_list", "legacy_json_deep_merge"):
        reducer = registry.get(profile)
        assert reducer is not None
        assert reducer.profile == profile
        assert reducer.contract_version == "1"
        assert reducer.requires_stable_order is True
        assert reducer.preserves_order is True
    for profile in ("dedup", "group", "entity_union", "rank", "top_k"):
        reducer = registry.get(profile)
        assert reducer.contract_version == "1"
        assert reducer.requires_stable_order is True
    assert registry.get("rank").preserves_order is False


def test_empty_registry_names_and_aliases_are_rejected():
    registry = ReducerRegistry()

    import pytest

    with pytest.raises(ValueError, match="must not be empty"):
        registry.register(" ", ExampleReducer())
    with pytest.raises(ValueError, match="must not be empty"):
        registry.register("example", ExampleReducer(), aliases=(" ",))
