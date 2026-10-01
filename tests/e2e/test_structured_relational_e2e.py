"""Offline PR J immutable-manifest through aggregate-sink acceptance."""

import sqlite3

import pytest

from czjLLM.es_mode.output_profiles import get_default_registry
from czjLLM.reduction import (
    AggregateOutput, CollectionManifest, LogicalWorkUnit,
    parse_reduction_config, reduce_single_pass,
)
from czjLLM.sql_mode.collection import SQLiteAggregateSink

pytestmark = pytest.mark.e2e

ENTITY_SETS = [{"name": "events", "collection_path": "Event", "id_field": "event_id", "canonical_prefix": "E"}]
REFERENCES = [{"collection_path": name, "field": "event_ids", "target": "events"}
              for name in ("Person", "Involved_Parties", "Impact", "Event_Timeline", "evidence_snippets")]


def _payload(label):
    return {"article_date_iso": None, "article_date_precision": "unknown", "Event_Summary": label,
            "Event": [{"event_id": "E1", "time_raw": None, "time_iso": None,
                       "time_precision": "unknown", "consequence": None}],
            "Person": [{"name": label, "event_ids": ["E1"]}],
            "Involved_Parties": [], "Impact": [], "evidence_snippets": [],
            "Event_Timeline": [{"description": label, "time_raw": None, "time_iso": None,
                                "time_precision": "unknown", "event_ids": ["E1"]}]}


def test_structured_relational_manifest_profile_and_idempotent_aggregate(tmp_path):
    manifest = CollectionManifest("relational-events", (
        LogicalWorkUnit("slice-a", _payload("A")),
        LogicalWorkUnit("slice-b", _payload("B")),
    ))
    assert [unit.payload["Event"][0]["event_id"] for unit in manifest.units] == ["E1", "E1"]
    config = parse_reduction_config({"enabled": True, "controller": "single_pass",
                                     "profile": "structured_relational",
                                     "options": {"entity_sets": ENTITY_SETS, "references": REFERENCES}})
    result = reduce_single_pass((unit.payload for unit in manifest.units), config)
    ids = [row["Event"][0]["event_id"] for row in result.payload]
    assert ids == ["E1", "E2"] and len(ids) == len(set(ids))
    assert result.payload[0]["Event_Summary"] == "A" and result.payload[1]["Event_Summary"] == "B"
    for row, event_id in zip(result.payload, ids):
        assert row["Person"][0]["event_ids"] == [event_id]
        assert row["Event_Timeline"][0]["event_ids"] == [event_id]
    assert len(result.provenance["id_remap"]) == 2
    validated = get_default_registry().normalize_payload("multidim_event", result.payload)

    connection = sqlite3.connect(tmp_path / "relational.sqlite")
    sink = SQLiteAggregateSink(connection); sink.ensure_schema()
    aggregate = AggregateOutput(manifest, "canonical-events", validated,
                                provenance={"remap_fingerprint": result.audit["remap_fingerprint"]})
    sink.upsert(aggregate); sink.upsert(aggregate)
    assert connection.execute("SELECT COUNT(*) FROM collection_aggregates").fetchone() == (1,)
    connection.close()
