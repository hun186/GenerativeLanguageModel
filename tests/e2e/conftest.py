from __future__ import annotations

from types import SimpleNamespace

import pytest

from .fake_openai_server import FakeOpenAIServer


@pytest.fixture
def fake_openai(tmp_path):
    server = FakeOpenAIServer().start()
    server.model_spec = {
        "base_url": server.base_url,
        "model_name": "e2e-model",
        "api_key": "e2e-dummy-key",
    }
    server.work_dir = tmp_path
    try:
        yield server
    finally:
        server.close()


@pytest.fixture
def sink_ctx(tmp_path):
    return SimpleNamespace(
        output_col="analysis",
        input_col="body",
        primary_key="id",
        record_update_time=False,
        flatten_json_output=False,
        output_profile="none",
        output_profiles=None,
        output_profile_plugins=None,
        es_flush_every=100,
        es_flush_bytes=1_000_000,
        es_flush_secs=60,
        es_refresh_after_flush=False,
        write_output=True,
        debug_es_sink=False,
        PGMSubDir=str(tmp_path),
    )
