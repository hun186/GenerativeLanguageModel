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
        usage=SimpleNamespace(prompt_tokens=12, completion_tokens=5, total_tokens=17)
    )

    log_llm_call(
        audit_path=metadata["llm_call_audit_path"],
        run_id=metadata["llm_call_audit_run_id"],
        task="extract",
        prompt_file="prompt.txt",
        model_spec={"model_name": "test-model", "num_ctx": 1024},
        response=response,
        max_tokens=100,
    )

    with Path(metadata["llm_call_audit_path"]).open(encoding="utf-8", newline="") as fp:
        rows = list(csv.DictReader(fp))

    assert len(rows) == 1
    assert rows[0]["run_id"] == metadata["llm_call_audit_run_id"]
    assert rows[0]["total_tokens"] == "17"
