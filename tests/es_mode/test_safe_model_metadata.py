from __future__ import annotations

from czjLLM.es_mode.model_metadata import (
    safe_model_metadata,
    safe_model_tag,
    strip_sensitive_metadata,
)


def test_model_spec_is_allowlisted_without_endpoint_or_api_key():
    spec = {
        "model_name": "qwen3.8:latest-128k",
        "base_url": ["http://private-host:11435/v1"],
        "base_url_alias": "ollama-analysis-pool",
        "api_key": "secret-token",
        "num_ctx": 131072,
        "temperature": 0.2,
        "version": "2026-08",
        "nProcess": 4,
    }

    assert safe_model_metadata(spec) == {
        "model_name": "qwen3.8:latest-128k",
        "base_url_alias": "ollama-analysis-pool",
        "num_ctx": 131072,
        "temperature": 0.2,
        "model_version": "2026-08",
    }
    assert safe_model_tag(spec) == "qwen3.8:latest-128k"


def test_stringified_model_spec_cannot_leak_credentials_into_model_tag():
    unsafe = str({
        "model_name": "qwen3.8:latest-128k",
        "base_url": "http://private-host/v1",
        "api_key": "secret-token",
        "num_ctx": 131072,
    })

    assert safe_model_tag(unsafe) == "qwen3.8:latest-128k"
    assert safe_model_tag("api_key=secret-token") is None
    assert safe_model_tag("secretariat-analysis-v2") == "secretariat-analysis-v2"


def test_nested_sensitive_metadata_is_removed_defensively():
    sanitized = strip_sensitive_metadata({
        "model_name": "safe-model",
        "api_key": "secret-token",
        "base_url": "http://private-host/v1",
        "model_spec": {"model_name": "must-not-be-embedded"},
        "plugin": {"access_token": "secret", "version": "v2"},
        "note": "Bearer secret-token",
    })

    assert sanitized == {
        "model_name": "safe-model",
        "plugin": {"version": "v2"},
        "note": "[REDACTED]",
    }
