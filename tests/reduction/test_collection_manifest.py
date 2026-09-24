"""PR F collection identity contract tests (dependency-light and in-memory)."""

import json
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from czjLLM.reduction import (
    COLLECTION_MANIFEST_CONTRACT_VERSION,
    CollectionManifest,
    CollectionManifestValidationError,
    LogicalWorkUnit,
    Reducer,
    ReducerResult,
)


def unit(identity="unit-1", payload=None, provenance=None):
    return LogicalWorkUnit(
        identity,
        {"text": "alpha"} if payload is None else payload,
        {"source_alias": "fixture"} if provenance is None else provenance,
    )


def manifest(units=None, collection_id="collection-1", provenance=None):
    return CollectionManifest(
        collection_id,
        [unit(), unit("unit-2", {"text": "beta"})] if units is None else units,
        {"adapter_kind": "in_memory"} if provenance is None else provenance,
    )


def test_valid_logical_work_unit_is_frozen_and_serializable():
    work = unit(payload={"text": "alpha", "labels": ["a", "b"]})

    assert work.logical_id == "unit-1"
    assert work.to_mapping() == {
        "logical_id": "unit-1",
        "payload": {"text": "alpha", "labels": ["a", "b"]},
        "provenance": {"source_alias": "fixture"},
    }
    json.dumps(work.to_mapping())
    with pytest.raises(FrozenInstanceError):
        work.logical_id = "replacement"


@pytest.mark.parametrize(
    "identity",
    [None, "", "   ", " leading", "trailing ", "bad\nline", "https://host/item", "/tmp/item"],
)
def test_invalid_logical_identity_is_rejected(identity):
    with pytest.raises(CollectionManifestValidationError, match="logical_id"):
        unit(identity)


@pytest.mark.parametrize(
    "identity",
    [
        "api_key=secret-token",
        "Bearer secret-token",
        "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.signatureABC",
    ],
)
def test_credential_or_jwt_logical_identity_is_rejected(identity):
    with pytest.raises(CollectionManifestValidationError, match="logical_id.*credential|JWT"):
        unit(identity)


@pytest.mark.parametrize(
    "identity",
    [
        "password=hunter2",
        "Bearer secret-token",
        "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.signatureABC",
    ],
)
def test_credential_or_jwt_collection_identity_is_rejected(identity):
    with pytest.raises(CollectionManifestValidationError, match="collection_id.*credential|JWT"):
        manifest(collection_id=identity)


def test_benign_secret_word_in_logical_identity_is_accepted():
    work = unit("secretariat-analysis-v2")

    assert work.logical_id == "secretariat-analysis-v2"


def test_manifest_preserves_explicit_caller_order():
    units = [unit("b"), unit("a")]
    value = manifest(units)

    assert value.contract_version == COLLECTION_MANIFEST_CONTRACT_VERSION == "1"
    assert [item.logical_id for item in value.units] == ["b", "a"]
    assert [item["logical_id"] for item in value.to_mapping()["units"]] == ["b", "a"]


def test_same_semantic_manifest_has_same_fingerprint():
    assert manifest().fingerprint == manifest().fingerprint


def test_payload_identity_order_and_collection_changes_affect_fingerprint():
    first = unit("one", {"value": 1})
    second = unit("two", {"value": 2})
    baseline = manifest([first, second])

    assert baseline.fingerprint != manifest([unit("one", {"value": 9}), second]).fingerprint
    assert baseline.fingerprint != manifest([unit("changed", {"value": 1}), second]).fingerprint
    assert baseline.fingerprint != manifest([second, first]).fingerprint
    assert baseline.fingerprint != manifest([first, second], collection_id="other").fingerprint


def test_caller_mutation_cannot_change_manifest_or_fingerprint():
    payload = {"nested": ["original"]}
    unit_provenance = {"selection": {"kind": "explicit"}}
    collection_provenance = {"query_alias": "daily", "parts": [1]}
    source_units = [unit("one", payload, unit_provenance)]
    value = manifest(source_units, provenance=collection_provenance)
    fingerprint = value.fingerprint

    payload["nested"].append("changed")
    unit_provenance["selection"]["kind"] = "changed"
    collection_provenance["parts"].append(2)
    source_units.append(unit("two"))

    assert value.to_mapping()["units"][0]["payload"] == {"nested": ["original"]}
    assert value.to_mapping()["units"][0]["provenance"] == {
        "selection": {"kind": "explicit"}
    }
    assert value.to_mapping()["provenance"] == {"query_alias": "daily", "parts": [1]}
    assert len(value.units) == 1
    assert value.fingerprint == fingerprint


def test_nested_contract_values_cannot_be_mutated_through_manifest_aliases():
    value = manifest([unit(payload={"nested": ["original"]})])

    with pytest.raises(TypeError):
        value.units[0].payload["nested"] = ("changed",)
    with pytest.raises(AttributeError):
        value.units[0].payload["nested"].append("changed")
    with pytest.raises(TypeError):
        value.provenance["new"] = "value"


def test_duplicate_logical_identity_is_rejected_with_identity():
    with pytest.raises(CollectionManifestValidationError, match="duplicate.*same"):
        manifest([unit("same"), unit("same", {"other": True})])


def test_canonical_serialization_round_trip_preserves_contract():
    original = manifest()
    serialized = original.to_mapping()
    reconstructed = CollectionManifest.from_mapping(json.loads(json.dumps(serialized)))

    assert reconstructed == original
    assert reconstructed.to_mapping() == serialized
    assert reconstructed.fingerprint == original.fingerprint


def test_corrupted_fingerprint_is_rejected_not_repaired():
    serialized = manifest().to_mapping()
    serialized["fingerprint"] = "0" * 64

    with pytest.raises(CollectionManifestValidationError, match="fingerprint"):
        CollectionManifest.from_mapping(serialized)


def test_incompatible_version_and_unknown_corruption_are_rejected():
    serialized = manifest().to_mapping()
    serialized["contract_version"] = "999"
    with pytest.raises(CollectionManifestValidationError, match="unsupported.*version"):
        CollectionManifest.from_mapping(serialized)

    serialized = manifest().to_mapping()
    serialized["unexpected"] = True
    with pytest.raises(CollectionManifestValidationError, match="unknown=.*unexpected"):
        CollectionManifest.from_mapping(serialized)


def test_serialization_has_only_semantic_fields_and_no_runtime_values():
    serialized = manifest().to_mapping()

    assert set(serialized) == {
        "contract_version", "collection_id", "units", "provenance", "fingerprint"
    }
    rendered = json.dumps(serialized, sort_keys=True)
    for excluded in ("created_at", "updated_at", "timestamp", "hostname", "pid", "thread"):
        assert excluded not in rendered.lower()


@pytest.mark.parametrize(
    "provenance",
    [{"created_at": "2026-01-01"}, {"nested": {"pid": 42}}, {"tmp_path": "/tmp/x"}],
)
def test_nondeterministic_provenance_fields_are_rejected(provenance):
    with pytest.raises(CollectionManifestValidationError, match="runtime state"):
        manifest(provenance=provenance)


@pytest.mark.parametrize(
    "provenance",
    [
        {"api_key": "value"},
        {"nested": {"password": "value"}},
        {"endpoint": "https://user:pass@example.invalid"},
        {"note": "Bearer credential"},
    ],
)
def test_secret_or_endpoint_bearing_provenance_is_rejected(provenance):
    with pytest.raises(CollectionManifestValidationError, match="provenance"):
        unit(provenance=provenance)


def test_contract_is_source_independent_and_keeps_existing_exports_compatible():
    import czjLLM.reduction.collection as collection_module

    source = Path(collection_module.__file__).read_text(encoding="utf-8").lower()
    forbidden_imports = (
        "sqliteadapter", "elasticsearchadapter", "row_merger", "call_llm_api",
        "sql_mode", "es_mode", "prompt_pipeline",
    )

    assert not any(name in source for name in forbidden_imports)
    assert Reducer is not None
    assert ReducerResult is not None
