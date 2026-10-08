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
