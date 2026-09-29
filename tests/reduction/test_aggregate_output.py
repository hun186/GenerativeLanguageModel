import json

import pytest

from czjLLM.reduction import (
    AggregateOutput, CollectionManifest, CollectionManifestStore, LogicalWorkUnit,
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
