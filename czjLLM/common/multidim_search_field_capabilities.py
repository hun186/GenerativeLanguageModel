"""Offline comparison of indexed MultiDim fields used by SRAF-style search.

This is a TEMPLATE audit; it does not check a live Mapping, installed ES
analyzers, tokenization quality, reindex coverage or SRAF runtime query plan.
"""
from __future__ import annotations
import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "czjLLM/es_mode/contracts/multidim_search_v1.json"
FIELDS = (
    "Event.subject", "Event.object", "Event.action", "Event.location",
    "Event.consequence", "Event.relation", "Event_Summary",
    "Person.name", "Involved_Parties.party_name",
    "Impact.impact_description", "evidence_snippets.text",
    "article_title", "core_entities", "locations",
)


def _lookup(properties: dict, path: str) -> dict | None:
    node = {"properties": properties}
    for part in path.split("."):
        children = node.get("properties", {})
        if not isinstance(children, dict) or not isinstance(children.get(part), dict):
            return None
        node = children[part]
    return node


def inspect_template_search_fields(contract: dict, mapping: dict) -> dict:
    field_types = contract.get("field_types", {})
    properties = mapping.get("properties", {})
    root = _lookup(properties, "multidim_event_json")
    if (not isinstance(root, dict) or root.get("type") != "nested"
            or not isinstance(root.get("properties"), dict)):
        return {"status": "UNAVAILABLE", "reason_code": "MAPPING_ROOT_NOT_VERIFIED"}
    counts = {"KEYWORD_ONLY": 0, "TEXT_INDEXED": 0, "KEYWORD_PLUS_TEXT": 0}
    results = []
    for field in FIELDS:
        expect = field_types.get(field)
        node = _lookup(root["properties"], field)
        if not isinstance(node, dict) or node.get("type") != expect:
            return {"status": "UNAVAILABLE", "reason_code": "CONTRACT_FIELD_DRIFT"}
        actual = node.get("type")
        primary = node.get("index", True)
        if type(primary) is not bool:
            return {"status": "UNAVAILABLE", "reason_code": "INDEX_FLAG_UNVERIFIED"}
        if primary is False:
            # An explicit index:false must not be reported as having a
            # normal inverted search index. Doc values may differ.
            return {"status": "UNAVAILABLE", "reason_code": "PRIMARY_INDEX_DISABLED",
                    "field": field}
        if actual == "text":
            capability = "TEXT_INDEXED"
        elif actual == "keyword":
            multi = node.get("fields", {})
            if multi is None:
                multi = {}
            if not isinstance(multi, dict):
                return {"status": "UNAVAILABLE", "reason_code": "FIELDS_UNVERIFIED"}
            text_fields = []
            for name, desc in multi.items():
                if not isinstance(desc, dict) or desc.get("type") != "text":
                    continue
                indexed = desc.get("index", True)
                if type(indexed) is not bool:
                    return {"status": "UNAVAILABLE", "reason_code": "INDEX_FLAG_UNVERIFIED"}
                if indexed:
                    text_fields.append(name)
            capability = "KEYWORD_PLUS_TEXT" if text_fields else "KEYWORD_ONLY"
        else:
            return {"status": "UNAVAILABLE", "reason_code": "UNSUPPORTED_SEARCH_FIELD_TYPE"}
        counts[capability] += 1
        # Only known public paths and fixed capability codes, not analyzer
        # definitions, private examples, user content, or mapping payloads.
        results.append({"field": field, "capability": capability})
    return {
        "status": "OBSERVED_TEMPLATE_NOT_LIVE",
        "schema_version": 1,
        "contract_id": "glm.multidim_event.search_consumer",
        "fields": results,
        "counts": counts,
        "cjk_analyzer_installed": "NOT_VERIFIED",
        "chinese_tokenization_quality": "NOT_VERIFIED",
        "historical_documents_reindexed": "NOT_VERIFIED",
        "sraf_runtime_query_alignment": "NOT_VERIFIED",
        "live_index_mapping": "NOT_CHECKED",
        "read_only": True, "es_requests": 0,
    }


def inspect_checked_in_template() -> dict:
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    path = ROOT / contract["mapping_source"]
    mapping = yaml.safe_load(path.read_text(encoding="utf-8"))
    return inspect_template_search_fields(contract, mapping)
