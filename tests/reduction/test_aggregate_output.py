import json

import pytest

from czjLLM.reduction import (
    AggregateOutput, CollectionManifest, CollectionManifestStore, LogicalWorkUnit,
    CollectionManifestValidationError, derive_aggregate_output_id,
    extract_aggregate_lineage, same_aggregate_lineage,
)


def manifest(payload="one"):
    return CollectionManifest("daily", [LogicalWorkUnit("1", {"text": payload})])


def test_aggregate_identity_invariants():
    first = manifest()
    assert AggregateOutput(first, "summary", {}).aggregate_output_id == AggregateOutput(first, "summary", {}).aggregate_output_id
    assert AggregateOutput(first, "summary", {}).aggregate_output_id != AggregateOutput(first, "topics", {}).aggregate_output_id
    assert AggregateOutput(first, "summary", {}).aggregate_output_id != AggregateOutput(manifest("changed"), "summary", {}).aggregate_output_id


def test_manifest_store_round_trip_and_corruption(tmp_path):
    path = tmp_path / "manifest.json"
    original = manifest()
    CollectionManifestStore.save(path, original)
    assert CollectionManifestStore.load(path).to_mapping() == original.to_mapping()
    value = json.loads(path.read_text())
    value["units"][0]["payload"]["text"] = "corrupt"
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="fingerprint"):
        CollectionManifestStore.load(path)


def test_generic_reduction_does_not_import_source_adapters():
    from pathlib import Path
    source = "\n".join(path.read_text() for path in Path("czjLLM/reduction").glob("*.py"))
    for forbidden in ("SQLiteAdapter", "MSSQLAdapter", "ElasticsearchAdapter", "ESSink", "SqlSink", "row_merger"):
        assert forbidden not in source


def test_lineage_projection_uses_only_canonical_aggregate_fields():
    original = AggregateOutput(
        manifest(), "summary", {"private_data": ["not for lineage"]},
        {"source_alias": "safe-fixture"},
    )
    canonical = original.to_mapping()
    expected_keys = {
        "aggregate_output_contract_version", "aggregate_output_id",
        "collection_id", "manifest_fingerprint", "output_key",
    }
    projected = original.lineage_mapping()
    assert set(projected) == expected_keys
    assert projected == {key: canonical[key] for key in expected_keys}
    assert extract_aggregate_lineage(original) == projected
    assert extract_aggregate_lineage(canonical) == projected
    assert extract_aggregate_lineage(original.as_logical_work_unit_payload()) == projected
    assert "private_data" not in json.dumps(projected)
    assert "source_alias" not in json.dumps(projected)
    assert original.aggregate_output_id == derive_aggregate_output_id(manifest(), "summary")
    projected["output_key"] = "changed"
    assert original.lineage_mapping()["output_key"] == "summary"


def test_lineage_comparison_distinguishes_identity_not_payload_or_provenance():
    reference = AggregateOutput(manifest(), "summary", {"value": 1})
    alternative = AggregateOutput(manifest(), "summary", {"value": 999},
                                  {"source_alias": "different"})
    assert same_aggregate_lineage(reference, alternative.to_mapping())
    assert same_aggregate_lineage(reference.as_logical_work_unit_payload(), alternative)
    assert not same_aggregate_lineage(reference, AggregateOutput(manifest(), "topics", {}))
    assert not same_aggregate_lineage(reference, AggregateOutput(manifest("changed"), "summary", {}))
    assert not same_aggregate_lineage(
        reference,
        AggregateOutput(CollectionManifest("other", [LogicalWorkUnit("1", {"text": "one"})]),
                        "summary", {}),
    )


@pytest.mark.parametrize("field,invalid", [
    ("aggregate_output_contract_version", "2"),
    ("collection_id", "other"),
    ("collection_id", "Bearer credential"),
    ("output_key", "renamed"),
    ("aggregate_output_id", "aggregate-v1-invalid"),
    ("manifest_fingerprint", "ABC"),
    ("manifest_fingerprint", "f" * 64),
])
def test_tampered_or_incompatible_lineage_fails_closed(field, invalid):
    mapping = AggregateOutput(manifest(), "summary", {}).to_mapping()
    mapping[field] = invalid
    with pytest.raises(CollectionManifestValidationError):
        extract_aggregate_lineage(mapping)


def test_lineage_missing_or_invalid_record_fails_closed():
    record = AggregateOutput(manifest(), "summary", {}).to_mapping()
    for field in (
        "aggregate_output_contract_version", "aggregate_output_id",
        "collection_id", "manifest_fingerprint", "output_key",
    ):
        invalid = dict(record)
        del invalid[field]
        with pytest.raises(CollectionManifestValidationError, match="missing required"):
            extract_aggregate_lineage(invalid)
    with pytest.raises(CollectionManifestValidationError, match="mapping"):
        extract_aggregate_lineage(None)
    with pytest.raises(CollectionManifestValidationError):
        same_aggregate_lineage(record, {"aggregate_output_id": record["aggregate_output_id"]})


def test_lineage_helpers_accept_detached_json_roundtrip_and_keep_v1_wire_contract():
    original = AggregateOutput(manifest(), "summary", {"nested": {"entries": [1, 2]}})
    encoded = json.loads(json.dumps(original.to_mapping()))
    assert extract_aggregate_lineage(encoded) == original.lineage_mapping()
    assert same_aggregate_lineage(encoded, original)
    assert set(encoded) == {
        "aggregate_output_contract_version", "aggregate_output_id",
        "collection_id", "manifest_fingerprint", "output_key", "payload", "provenance",
    }
