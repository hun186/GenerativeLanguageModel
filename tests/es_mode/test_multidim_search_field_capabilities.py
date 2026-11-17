"""Fixed, privacy-safe offline checks for GLM MultiDim search capabilities."""
from copy import deepcopy
import json

from czjLLM.common.multidim_search_field_capabilities import (
    FIELDS, inspect_checked_in_template, inspect_template_search_fields,
)
from scripts.audit_multidim_search_fields_offline import inspect_checked_in_template as cli_inspect


def test_current_template_has_keyword_only_and_text_field_categories():
    data = inspect_checked_in_template()
    assert data["status"] == "OBSERVED_TEMPLATE_NOT_LIVE"
    assert data["es_requests"] == 0
    assert data["cjk_analyzer_installed"] == "NOT_VERIFIED"
    assert data["historical_documents_reindexed"] == "NOT_VERIFIED"
    assert len(data["fields"]) == len(FIELDS)
    mapped = {x["field"]: x["capability"] for x in data["fields"]}
    assert mapped["Event.subject"] == "KEYWORD_ONLY"
    assert mapped["Event.object"] == "KEYWORD_ONLY"
    assert mapped["Impact.impact_description"] == "TEXT_INDEXED"
    assert mapped["evidence_snippets.text"] == "TEXT_INDEXED"
    assert mapped["article_title"] == "TEXT_INDEXED"
    assert sum(data["counts"].values()) == len(FIELDS)
    assert cli_inspect() == data


def test_text_multifield_properly_classifies_a_synthetic_mapping_copy():
    import yaml
    from czjLLM.common.multidim_search_field_capabilities import ROOT, CONTRACT
    spec = json.loads(CONTRACT.read_text(encoding="utf-8"))
    mapping = yaml.safe_load((ROOT / spec["mapping_source"]).read_text(encoding="utf-8"))
    before = deepcopy(mapping)
    field = mapping["properties"]["multidim_event_json"]["properties"][
        "Event"]["properties"]["subject"]
    field["fields"] = {"search": {"type": "text", "analyzer": "cjk"}}
    report = inspect_template_search_fields(spec, mapping)
    observed = {x["field"]: x["capability"] for x in report["fields"]}
    assert report["status"] == "OBSERVED_TEMPLATE_NOT_LIVE"
    assert observed["Event.subject"] == "KEYWORD_PLUS_TEXT"
    assert report["cjk_analyzer_installed"] == "NOT_VERIFIED"
    assert report["historical_documents_reindexed"] == "NOT_VERIFIED"
    # The fixed output key cjk_analyzer_installed is intentional; the
    # actual analyzer config from the synthetic input must not be copied.
    assert '"analyzer": "cjk"' not in json.dumps(report)
    assert "fields" not in before["properties"]["multidim_event_json"][
        "properties"]["Event"]["properties"]["subject"]



def test_contract_field_type_drift_fails_without_leaking_mapping_content():
    from pathlib import Path
    import yaml
    from czjLLM.common.multidim_search_field_capabilities import ROOT, CONTRACT
    spec = json.loads(CONTRACT.read_text(encoding="utf-8"))
    mapping = yaml.safe_load((ROOT / spec["mapping_source"]).read_text(encoding="utf-8"))
    mapping["properties"]["multidim_event_json"]["properties"]["Event"]["properties"][
        "subject"]["type"] = "text"
    mapping["secret_marker"] = "PRIVATE_MAPPING"
    report = inspect_template_search_fields(spec, mapping)
    assert report["status"] == "UNAVAILABLE"
    assert report["reason_code"] == "CONTRACT_FIELD_DRIFT"
    assert "PRIVATE_MAPPING" not in json.dumps(report)
