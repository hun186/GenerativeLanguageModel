from pathlib import Path
from types import SimpleNamespace

import pytest

from czjLLM.es_mode.adapters.elasticsearch_adapter import ElasticsearchAdapter
from czjLLM.handlers import handle_data_mode as data_handler
from czjLLM.job_manager.job_config import LLMJobConfig
from czjLLM.prompt_pipeline.dispatch_parallelism import attach_execution_budget
from .fake_es import InMemoryES, bulk, scan


pytestmark = pytest.mark.e2e


class RecordingElasticsearchAdapter(ElasticsearchAdapter):
    def __init__(self, cfg, store):
        super().__init__(cfg)
        self.es = InMemoryES(store)
        self.selected = []

    def select_pending_rows(self, **kwargs):
        for row in super().select_pending_rows(**kwargs):
            self.selected.append(str(row[0]))
            yield row

    def connect(self):
        return self


def test_handle_data_mode_es_backend_runs_production_scheduler(
    fake_openai, monkeypatch, tmp_path
):
    import czjLLM.es_mode.adapters.elasticsearch_adapter as adapter_module
    import czjLLM.es_mode.runtime.sinks.es_sink as sink_module

    store = {
        "czjllm-e2e-records": {
            "es-e2e-001": {"rawInfo": {"content": "ROW_ID=es-e2e-001"}},
            "es-e2e-002": {"rawInfo": {"content": "ROW_ID=es-e2e-002"}},
        }
    }
    monkeypatch.setattr(
        adapter_module, "helpers", SimpleNamespace(scan=lambda **kw: scan(store, **kw))
    )
    monkeypatch.setattr(
        sink_module,
        "helpers",
        SimpleNamespace(bulk=lambda _client, actions, **_kw: bulk(store, actions)),
    )
    cfg = {
        "src_index": "czjllm-e2e-records", "tgt_index": "czjllm-e2e-records",
        "id_col": "_id", "input_col": "rawInfo.content", "output_col": "analysis",
        "reset_output": False, "es_prefetch_buffer": 0, "rerun": {},
    }
    adapter = RecordingElasticsearchAdapter(cfg, store)
    monkeypatch.setattr(
        data_handler, "resolve_es_connection", lambda ctx, get_param, args: (adapter, cfg)
    )

    ctx = LLMJobConfig()
    ctx.mode = "es"
    ctx.task = "ROW_ID echo"
    ctx.model_spec = fake_openai.model_spec
    ctx.model_spec_name = "e2e-model"
    ctx.max_tokens = 64
    ctx.PGMSubDir = str(tmp_path)
    ctx.prompt_dir = str(tmp_path / "prompts")
    ctx.llm_source_dir = str(tmp_path / "work")
    ctx.llm_source_finished_dir = str(tmp_path / "finished")
    ctx.log_dir = str(tmp_path / "logs")
    ctx.n_process = 2
    ctx.slice_parallelism = 2
    ctx.schedule_todo_wait_seconds = 5
    ctx.pending_running_all_deferred_wait_seconds = 0
    ctx.output_profile = "none"
    ctx.es_flush_every = 1
    ctx.reduction = {"enabled": False, "profile": "concat_text"}
    for directory in (ctx.prompt_dir, ctx.llm_source_dir, ctx.llm_source_finished_dir, ctx.log_dir):
        Path(directory).mkdir(parents=True, exist_ok=True)
    attach_execution_budget(ctx)

    params = {
        "id_col": "_id", "input_col": "rawInfo.content", "output_col": "analysis",
        "record_update_time": False, "output_profile": "none",
    }
    get_param = lambda name, default=None: params.get(name, default)
    args = SimpleNamespace(
        config="offline-e2e", id_col=None, input_col=None, output_col=None,
        output_profile=None, flatten_json=False, reset_output=False,
    )
    data_handler.handle_data_mode(ctx, get_param, args)

    expected = {"es-e2e-001", "es-e2e-002"}
    requested = {
        marker
        for request in fake_openai.requests
        for marker in expected
        if f"ROW_ID={marker}" in str(request["body"])
    }
    written = {key for key in expected if store["czjllm-e2e-records"][key].get("analysis")}
    assert set(adapter.selected) == requested == written == expected
    assert all(
        store["czjllm-e2e-records"][key]["analysis"] == f"RESULT::{key}"
        for key in expected
    )
    assert ctx._execution_budget.snapshot().in_use == 0
