import ast
import csv
import importlib.util
from pathlib import Path
from types import SimpleNamespace


_AUDIT_PATH = (
    Path(__file__).parents[2] / "czjLLM" / "utilities" / "llm_call_audit.py"
)
_SPEC = importlib.util.spec_from_file_location("llm_call_audit_under_test", _AUDIT_PATH)
assert _SPEC and _SPEC.loader
_AUDIT = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_AUDIT)
create_llm_call_audit_run = _AUDIT.create_llm_call_audit_run
log_llm_call = _AUDIT.log_llm_call
write_prompt_token_metadata = _AUDIT.write_prompt_token_metadata
read_prompt_token_metadata = _AUDIT.read_prompt_token_metadata


def test_every_prompt_worker_factory_receives_run_audit_metadata():
    controller_path = (
        Path(__file__).parents[2]
        / "czjLLM"
        / "prompt_pipeline"
        / "pipeline_controller.py"
    )
    tree = ast.parse(controller_path.read_text(encoding="utf-8"))
    context_factories = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name in {"llm_stream_consumer", "call_llm_api"}
    ]
    worker_calls = [
        node
        for factory in context_factories
        for node in ast.walk(factory)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "PromptAPIPipeline"
    ]

    assert len(worker_calls) == 2
    assert all(
        any(
            keyword.arg is None
            and isinstance(keyword.value, ast.Call)
            and isinstance(keyword.value.func, ast.Name)
            and keyword.value.func.id == "_llm_call_audit_kwargs"
            for keyword in call.keywords
        )
        for call in worker_calls
    )


def test_audit_run_appends_a_call_row(tmp_path):
    metadata = create_llm_call_audit_run(str(tmp_path))
    response = SimpleNamespace(
        usage=SimpleNamespace(prompt_tokens=12, completion_tokens=5, total_tokens=17),
        _czjllm_elapsed_seconds=1.25,
    )

    log_llm_call(
        audit_path=metadata["llm_call_audit_path"],
        run_id=metadata["llm_call_audit_run_id"],
        task="extract",
        prompt_file="prompt.txt",
        model_spec={"model_name": "test-model", "num_ctx": 1024},
        response=response,
        max_tokens=100,
        task_text_tokens=7,
        template_tokens=4,
        rendered_prompt_tokens=11,
        prompt_component_token_source="local_tokenizer_no_special_tokens",
    )

    with Path(metadata["llm_call_audit_path"]).open(encoding="utf-8", newline="") as fp:
        rows = list(csv.DictReader(fp))

    assert len(rows) == 1
    assert rows[0]["run_id"] == metadata["llm_call_audit_run_id"]
    assert rows[0]["total_tokens"] == "17"
    assert rows[0]["task_text_tokens"] == "7"
    assert rows[0]["template_tokens"] == "4"
    assert rows[0]["rendered_prompt_tokens"] == "11"
    assert rows[0]["prompt_component_token_source"] == "local_tokenizer_no_special_tokens"
    assert rows[0]["elapsed_seconds"] == "1.25"


def test_prompt_token_metadata_sidecar_contains_numbers_only(tmp_path):
    prompt = tmp_path / "TODO" / "0.txt"
    prompt.parent.mkdir(parents=True)
    prompt.write_text("secret source text", encoding="utf-8")

    write_prompt_token_metadata(
        str(prompt),
        task_text_tokens=123,
        template_tokens=45,
        rendered_prompt_tokens=168,
    )
    sidecar = prompt.parent.parent / ".llm_audit_tokens" / f"{prompt.name}.audit_tokens.json"
    raw = sidecar.read_text(encoding="utf-8")
    assert "secret source text" not in raw
    expected = {
        "task_text_tokens": 123,
        "template_tokens": 45,
        "rendered_prompt_tokens": 168,
        "prompt_component_token_source": "local_tokenizer_no_special_tokens",
    }
    assert read_prompt_token_metadata(str(prompt)) == expected
    # Queue claiming renames TODO/0.txt -> RUNNING/0.txt. The numeric sidecar
    # lives at the item root, so the worker still resolves the same metadata.
    running_prompt = prompt.parent.parent / "RUNNING" / prompt.name
    assert read_prompt_token_metadata(str(running_prompt)) == expected



def test_prompt_api_pipeline_emits_one_audit_row_per_request():
    controller_path = (
        Path(__file__).parents[2]
        / "czjLLM"
        / "prompt_pipeline"
        / "pipeline_controller.py"
    )
    tree = ast.parse(controller_path.read_text(encoding="utf-8"))
    pipeline_cls = next(
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "PromptAPIPipeline"
    )
    proc = next(
        node for node in pipeline_cls.body
        if isinstance(node, ast.FunctionDef) and node.name == "proc"
    )
    audit_calls = [
        node for node in ast.walk(proc)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "log_llm_call"
    ]
    request_calls = [
        node for node in ast.walk(proc)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "CallLLMAPI"
    ]

    assert len(request_calls) == 1
    assert len(audit_calls) == 1
    source = ast.get_source_segment(
        controller_path.read_text(encoding="utf-8"), proc
    )
    assert "llm_request_attempted = True" in source
    assert "if llm_request_attempted:" in source
    assert "response=response" in source
    assert "ok=ok" in source
    assert "error=err" in source


def test_provider_cached_usage_is_explicit_and_not_inferred(tmp_path):
    import csv
    from types import SimpleNamespace

    audit = tmp_path / "cache.csv"
    response = SimpleNamespace(
        usage=SimpleNamespace(
            prompt_tokens=120, completion_tokens=10, total_tokens=130,
            prompt_tokens_details=SimpleNamespace(cached_tokens=40),
        ), _czjllm_elapsed_seconds=2.5,
    )
    log_llm_call(audit_path=str(audit), run_id="run", prompt_file="p.txt",
                 model_spec={"model_name": "unit-model", "num_ctx": 1024},
                 response=response, stage_identity="stage-1")
    with audit.open(newline="", encoding="utf-8") as fp:
        rows = list(csv.DictReader(fp))
    assert rows[0]["cached_input_tokens"] == "40"
    assert rows[0]["cached_input_token_source"] == "provider_usage"
    assert rows[0]["stage_identity"] == "stage-1"

    no_cache_metadata = SimpleNamespace(
        usage=SimpleNamespace(prompt_tokens=120, completion_tokens=10, total_tokens=130),
        _czjllm_elapsed_seconds=1.0,
    )
    log_llm_call(audit_path=str(audit), run_id="run", prompt_file="p2.txt",
                 model_spec={"model_name": "unit-model", "num_ctx": 1024},
                 response=no_cache_metadata)
    with audit.open(newline="", encoding="utf-8") as fp:
        rows = list(csv.DictReader(fp))
    assert rows[1]["cached_input_tokens"] == ""
    assert rows[1]["cached_input_token_source"] == ""
    assert rows[1]["stage_identity"] == ""


def test_deepseek_cache_hit_and_provider_explicit_zero(tmp_path):
    import csv
    from types import SimpleNamespace

    audit = tmp_path / "cache.csv"
    for cached in (75, 0):
        response = SimpleNamespace(
            usage=SimpleNamespace(prompt_tokens=100, completion_tokens=20,
                                  total_tokens=120, prompt_cache_hit_tokens=cached),
            _czjllm_elapsed_seconds=2,
        )
        log_llm_call(audit_path=str(audit), run_id="run", prompt_file="p.txt",
                     model_spec={"model_name": "unit-model", "num_ctx": 1024},
                     response=response)
    with audit.open(newline="", encoding="utf-8") as fp:
        rows = list(csv.DictReader(fp))
    assert [row["cached_input_tokens"] for row in rows] == ["75", "0"]
    assert all(row["cached_input_token_source"] == "provider_usage" for row in rows)


def test_stage_identity_remains_metadata_not_prompt_payload(tmp_path):
    from pathlib import Path

    prompt = tmp_path / "TODO" / "a.txt"
    prompt.parent.mkdir(parents=True)
    prompt.write_text("secret task prompt", encoding="utf-8")
    write_prompt_token_metadata(
        str(prompt), task_text_tokens=20, template_tokens=10,
        rendered_prompt_tokens=30, stage_identity="classify",
    )
    sidecar = Path(str(prompt.parent.parent / ".llm_audit_tokens"
                       / "a.txt.audit_tokens.json"))
    raw = sidecar.read_text(encoding="utf-8")
    assert "secret task prompt" not in raw
    assert read_prompt_token_metadata(str(prompt))["stage_identity"] == "classify"
    running = prompt.parent.parent / "RUNNING" / "a.txt"
    assert read_prompt_token_metadata(str(running))["stage_identity"] == "classify"


def test_original_first_stage_relabel_preserves_token_counts_and_privacy(tmp_path):
    from pathlib import Path

    relabel = _AUDIT.relabel_prompt_token_stage
    prompt = tmp_path / "TODO" / "slice.txt"
    prompt.parent.mkdir(parents=True)
    prompt.write_text("private first-stage prompt", encoding="utf-8")
    write_prompt_token_metadata(
        str(prompt), task_text_tokens=72, template_tokens=30,
        rendered_prompt_tokens=102, stage_identity="single_stage",
    )
    assert relabel(str(prompt), "yaml_stage_alpha") is True
    expected = read_prompt_token_metadata(str(prompt))
    assert expected["stage_identity"] == "yaml_stage_alpha"
    assert expected["task_text_tokens"] == 72
    assert expected["template_tokens"] == 30
    assert expected["rendered_prompt_tokens"] == 102
    sidecar = Path(_AUDIT.prompt_token_metadata_path(str(prompt)))
    assert "private first-stage prompt" not in sidecar.read_text(encoding="utf-8")
    # Claiming TODO -> RUNNING keeps the same logical sidecar.
    running = prompt.parent.parent / "RUNNING" / "slice.txt"
    assert read_prompt_token_metadata(str(running))["stage_identity"] == "yaml_stage_alpha"

    missing = tmp_path / "TODO" / "missing.txt"
    missing.write_text("no component count", encoding="utf-8")
    assert relabel(str(missing), "yaml_stage_alpha") is False
    assert not _AUDIT.prompt_token_metadata_path(str(missing)).exists()


def test_multistage_original_prompt_retags_before_early_return():
    from pathlib import Path

    path = Path(__file__).parents[2] / "czjLLM" / "prompt_pipeline" / "pipeline_controller.py"
    source = path.read_text(encoding="utf-8")
    section = source.split('if (\n            stage_name == stage_defs[0].name', 1)[1]
    section = section.split('return  # 已有 TODO，不覆蓋', 1)[0]
    assert "shutil.copy2" in section
    assert "relabel_prompt_token_stage(str(fp), stage_name)" in section
    assert section.index("shutil.copy2") < section.index("relabel_prompt_token_stage")
