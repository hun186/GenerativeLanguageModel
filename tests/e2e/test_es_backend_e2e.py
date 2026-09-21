from copy import deepcopy
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
    bulk_actions = []

    def recording_bulk(_client, actions, **_kwargs):
        materialized = list(actions)
        bulk_actions.extend(deepcopy(materialized))
        return bulk(store, materialized)

    monkeypatch.setattr(
        sink_module,
        "helpers",
        SimpleNamespace(bulk=recording_bulk),
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

    expected_values = {
        "es-e2e-001": "RESULT::es-e2e-001",
        "es-e2e-002": "RESULT::es-e2e-002",
    }
    expected = set(expected_values)
    requested = {
        marker
        for request in fake_openai.requests
        for marker in expected
        if f"ROW_ID={marker}" in str(request["body"])
    }
    written = {key for key in expected if store["czjllm-e2e-records"][key].get("analysis")}
    assert set(adapter.selected) == requested == written == expected

    llm_responses = {
        marker: request.get("response_content")
        for request in fake_openai.requests
        for marker in expected
        if f"ROW_ID={marker}" in str(request["body"]) and request.get("status") == 200
    }
    assert llm_responses == expected_values, f"LLM boundary mismatch: {llm_responses!r}"

    combined_values = {}
    finished_root = Path(ctx.llm_source_finished_dir)
    for marker in expected:
        matches = [
            path
            for path in finished_root.rglob("*.txt")
            if marker in path.name and path.name.endswith("_ROW_ID_echo.txt")
        ]
        assert len(matches) == 1, (
            f"combined artifact lookup for {marker!r}: "
            f"{[str(path) for path in matches]!r}"
        )
        combined_values[marker] = matches[0].read_text(encoding="utf-8")
    assert combined_values == expected_values, (
        f"combine boundary mismatch: {combined_values!r}"
    )

    bulk_values = {
        str(action["_id"]): action["doc"].get("analysis")
        for action in bulk_actions
        if str(action.get("_id")) in expected
    }
    assert bulk_values == expected_values, f"ESSink bulk boundary mismatch: {bulk_values!r}"

    stored_values = {
        marker: store["czjllm-e2e-records"][marker].get("analysis")
        for marker in expected
    }
    assert stored_values == expected_values, f"final ES store mismatch: {stored_values!r}"
    assert ctx._execution_budget.snapshot().in_use == 0
