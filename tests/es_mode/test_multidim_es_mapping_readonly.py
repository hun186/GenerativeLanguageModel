"""Offline and payload-free verification of live ES Mapping compatibility probe."""
from copy import deepcopy
import base64
import json
from pathlib import Path
import ssl

import pytest
import yaml

from czjLLM.common.multidim_mapping_contract_audit import inspect_mapping_response
from scripts.audit_multidim_es_mapping_readonly import _endpoint, _request_mapping

ROOT = Path(__file__).resolve().parents[2]
MAPPING = ROOT / "czjLLM/config_es/schemas/InfoExtraction-MultiDim-mapping.yaml"


def _fixture():
    source = yaml.safe_load(MAPPING.read_text(encoding="utf-8"))
    return {"news_test": {"mappings": {"properties": source["properties"]}}}


def test_current_glm_mapping_template_matches_pinned_contract():
    report = inspect_mapping_response(_fixture())
    assert report["status"] == "OBSERVED_MAPPING_COMPATIBLE", report["issues"]
    assert report["checked_nested_paths"] >= 7
    assert report["checked_leaf_types"] >= 30
    assert report["document_content_read"] is False
    assert report["source_date_fidelity"] == "NOT_VERIFIED"


@pytest.mark.parametrize("mutation,path,reason", [
    (lambda p: p["multidim_event_json"].update(type="object"),
     "multidim_event_json", "NESTED_TYPE_MISMATCH"),
    (lambda p: p["multidim_event_json"]["properties"]["Event"].update(type="object"),
     "multidim_event_json.Event", "NESTED_TYPE_MISMATCH"),
    (lambda p: p["multidim_event_json"]["properties"]["Event"]["properties"]["subject"].update(type="text"),
     "multidim_event_json.Event.subject", "FIELD_TYPE_MISMATCH"),
    (lambda p: p["multidim_event_json"]["properties"]["Event"]["properties"].pop("time_iso"),
     "multidim_event_json.Event.time_iso", "MISSING_FIELD"),
    (lambda p: p["multidim_event_json"]["properties"]["Event_Timeline"]["properties"]["time_iso"].update(format="epoch_millis"),
     "multidim_event_json.Event_Timeline.time_iso", "DATE_FORMAT_DIFFERENCE_REVIEW"),
])
def test_detects_mapping_drift_without_printing_actual_mapping(mutation, path, reason):
    mapping = _fixture()
    before = deepcopy(mapping)
    mutation(mapping["news_test"]["mappings"]["properties"])
    assert mapping != before
    report = inspect_mapping_response(mapping)
    assert report["status"] == "REVIEW_REQUIRED"
    assert {"field": path, "reason": reason} in report["issues"]
    raw = json.dumps(report)
    assert "epoch_millis" not in raw
    assert "SENSITIVE" not in raw


@pytest.mark.parametrize("mapping", [
    {}, {"alias": {"mappings": {"properties": {}}}},
    {"news_test": {"mappings": {"properties": {}}}, "extra": {}},
    {"news_test": {"mappings": {}}}, {"news_test": []},
])
def test_rejects_aliases_wrong_indices_or_invalid_response(mapping):
    report = inspect_mapping_response(mapping)
    assert report["status"] == "UNAVAILABLE" or report["status"] == "REVIEW_REQUIRED"
    assert report.get("status") != "OBSERVED_MAPPING_COMPATIBLE"


@pytest.mark.parametrize("url", [
    "http://es.example.invalid:9001",
    "https://name.invalid:9200/_cat/indices",
    "https://name.invalid:9200/?x=1",
    "https://user:pass@name.invalid:9200",
    "https://name.invalid:9200#fragment",
    "name.invalid:9200", "",
])
def test_url_rejects_non_https_credentials_and_arbitrary_paths(url):
    with pytest.raises(ValueError, match="HTTPS_ENDPOINT_REQUIRED"):
        _endpoint(url)


def test_https_origin_only_accepts_fixed_mapping_path():
    assert _endpoint("https://es.example.invalid:9001/") == "https://es.example.invalid:9001"


def test_no_cert_means_no_network(tmp_path):
    with pytest.raises(ValueError, match="CA_CERT_FILE_NOT_FOUND"):
        _request_mapping("https://example.invalid:9200", str(tmp_path / "missing.crt"),
                         "user", "secret")


def test_tls_exception_preserves_ca_verification_and_get_only(monkeypatch, tmp_path):
    # Synthetic network and certificate fixture; no actual outbound request.
    cert = tmp_path / "ca.crt"
    cert.write_text("synthetic", encoding="utf-8")
    class Context:
        verify_mode = ssl.CERT_REQUIRED
        check_hostname = True
    context = Context()
    monkeypatch.setattr(ssl, "create_default_context", lambda cafile: context)
    captured = {}
    class FakeResponse:
        def __enter__(self): return self
        def __exit__(self, *_): return None
        def getcode(self): return 200
        def read(self, n):
            return json.dumps(_fixture()).encode("utf-8")
    class FakeOpener:
        def open(self, req, timeout):
            captured["url"] = req.full_url
            captured["method"] = req.get_method()
            captured["timeout"] = timeout
            captured["authorization"] = req.get_header("Authorization")
            return FakeResponse()
    monkeypatch.setattr(
        "scripts.audit_multidim_es_mapping_readonly.build_opener",
        lambda *args: FakeOpener())
    result = _request_mapping("https://es.example.invalid:9001", str(cert),
                              "user", "secret", skip_hostname=True)
    assert result == _fixture()
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is False
    assert captured["method"] == "GET"
    assert captured["url"] == "https://es.example.invalid:9001/news_test/_mapping"
    assert captured["timeout"] <= 12
    assert captured["authorization"] == "Basic " + base64.b64encode(b"user:secret").decode()
