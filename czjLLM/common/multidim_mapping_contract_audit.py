"""Privacy-safe ES Mapping drift evaluator for GLM MultiDim task contract v1.

The input is an Elasticsearch /news_test/_mapping response, never _source.
Read-only pure function; public contract paths/reason codes only.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
CONTRACT = ROOT / "czjLLM/es_mode/contracts/multidim_search_v1.json"
INDEX = "news_test"
MAX_MISMATCHES = 30


def _node(props: dict, path: str) -> dict | None:
    node: Any = {"properties": props}
    for name in path.split("."):
        if not isinstance(node, dict):
            return None
        children = node.get("properties")
        fields = node.get("fields")
        if isinstance(children, dict) and isinstance(children.get(name), dict):
            node = children[name]
        elif isinstance(fields, dict) and isinstance(fields.get(name), dict):
            node = fields[name]
        else:
            return None
    return node if isinstance(node, dict) else None


def inspect_mapping_response(response: Any, *, contract: dict | None = None) -> dict:
    """Return a redacted, field-path-only compatibility report.

    A matching Mapping is only type/path compatibility; no analyzer quality,
    source date fidelity, indexed document shape or actual search is proven.
    """
    spec = contract if contract is not None else json.loads(CONTRACT.read_text(encoding="utf-8"))
    base = {
        "schema_version": 1,
        "contract_id": "glm.multidim_event.search_consumer",
        "index": INDEX,
        "read_only": True,
        "no_writeback_or_replay": True,
        "document_content_read": False,
        "live_search_validated": False,
        "source_date_fidelity": "NOT_VERIFIED",
        "analyzer_quality": "NOT_VERIFIED",
    }
    if (not isinstance(response, dict) or set(response) != {INDEX}
            or not isinstance(response.get(INDEX), dict)):
        return {**base, "status": "UNAVAILABLE", "reason_code": "INDEX_MAPPING_RESPONSE_UNVERIFIED"}
    doc = response[INDEX]
    mapping = doc.get("mappings")
    props = mapping.get("properties") if isinstance(mapping, dict) else None
    if not isinstance(props, dict):
        return {**base, "status": "UNAVAILABLE", "reason_code": "MAPPING_PROPERTIES_UNVERIFIED"}

    issues: list[dict[str, str]] = []

    def record(path: str, reason: str) -> None:
        if len(issues) < MAX_MISMATCHES:
            issues.append({"field": path, "reason": reason})

    root = _node(props, "multidim_event_json")
    if root is None:
        record("multidim_event_json", "MISSING_FIELD")
    elif root.get("type") != "nested":
        record("multidim_event_json", "NESTED_TYPE_MISMATCH")
    elif root.get("dynamic") != "strict":
        record("multidim_event_json", "DYNAMIC_POLICY_DIFFERENCE")

    for path in spec["nested_paths"]:
        if path == "multidim_event_json":
            continue
        node = _node(props, path)
        if node is None:
            record(path, "MISSING_NESTED_PATH")
        elif node.get("type") != "nested":
            record(path, "NESTED_TYPE_MISMATCH")

    for path, expected in spec["field_types"].items():
        public_path = "multidim_event_json." + path
        node = _node(props, public_path)
        if node is None:
            record(public_path, "MISSING_FIELD")
        elif node.get("type") != expected:
            record(public_path, "FIELD_TYPE_MISMATCH")

    for path, expected in spec["date_formats"].items():
        public_path = "multidim_event_json." + path
        node = _node(props, public_path)
        if node is not None and node.get("type") == "date" and node.get("format") != expected:
            record(public_path, "DATE_FORMAT_DIFFERENCE_REVIEW")

    return {
        **base,
        "status": "OBSERVED_MAPPING_COMPATIBLE" if not issues else "REVIEW_REQUIRED",
        "checked_nested_paths": len(spec["nested_paths"]),
        "checked_leaf_types": len(spec["field_types"]),
        "checked_date_formats": len(spec["date_formats"]),
        "issues_truncated": len(issues) >= MAX_MISMATCHES,
        "issues": issues,
    }
