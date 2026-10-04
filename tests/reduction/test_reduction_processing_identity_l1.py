from types import SimpleNamespace

from czjLLM.reduction import (
    ExecutionContext, ProcessingIdentity, StagePipelineExecutable,
    bind_persisted_execution_fingerprint, executable_semantic_fingerprint,
    parse_reduction_stage_executable_config,
)


class Executable:
    def fingerprint_metadata(self, context):
        return {"task": context.reducer_context.get("task"), "reducer": {"top_k": 5}}


def test_processing_identity_uses_executable_metadata():
    first = executable_semantic_fingerprint(Executable(), ExecutionContext(reducer_context={"task": "a"}))
    again = executable_semantic_fingerprint(Executable(), ExecutionContext(reducer_context={"task": "a"}))
    changed = executable_semantic_fingerprint(Executable(), ExecutionContext(reducer_context={"task": "b"}))
    assert first == again and first != changed
    assert ProcessingIdentity(first).execution_fingerprint == first


def _root(**changes):
    values = dict(
        mode="sql", task="summary", taskSetting={"summary": {"task": "PROMPT-A", "InputCutLen": 100}},
        model_spec_name="model-profile", model_spec={"model_name": "m", "temperature": 0.1,
                                                     "api_key": "secret", "base_url": "https://private"},
        max_tokens=1000, think_mode=True, reduction={"enabled": False},
        worker_parallelism=2, checkpoint_path="/tmp/a", PGMSubDir="/tmp/run",
        _execution_budget=SimpleNamespace(capacity=2),
    )
    values.update(changes)
    return SimpleNamespace(**values)


class Adapter:
    def __init__(self):
        self.cfg = {"semantic_freshness": {"execution_fingerprint": "auto"}}


def test_auto_fingerprint_tracks_semantics_and_excludes_operations():
    first = bind_persisted_execution_fingerprint(_root(), Adapter())
    same = bind_persisted_execution_fingerprint(_root(
        model_spec={"model_name": "m", "temperature": 0.1, "api_key": "different", "base_url": "http://other"},
        worker_parallelism=99, checkpoint_path="/elsewhere", PGMSubDir="/other",
        _execution_budget=SimpleNamespace(capacity=99)), Adapter())
    assert first == same
    assert first != bind_persisted_execution_fingerprint(_root(
        taskSetting={"summary": {"task": "PROMPT-B", "InputCutLen": 100}}), Adapter())
    assert first != bind_persisted_execution_fingerprint(_root(
        model_spec={"model_name": "m", "temperature": 0.9}), Adapter())


def test_auto_fingerprint_tracks_stage_pipeline_and_explicit_k2_executable():
    stage_a = StagePipelineExecutable([{"name": "one", "task": "summary"}])
    stage_b = StagePipelineExecutable([{"name": "one", "task": "other"}])
    assert bind_persisted_execution_fingerprint(
        _root(semantic_freshness_executable=stage_a), Adapter()
    ) != bind_persisted_execution_fingerprint(
        _root(semantic_freshness_executable=stage_b), Adapter()
    )


def test_literal_fingerprint_remains_an_explicit_override():
    adapter = Adapter()
    adapter.cfg["semantic_freshness"]["execution_fingerprint"] = "external-v7"
    root = _root()
    assert bind_persisted_execution_fingerprint(root, adapter) == "external-v7"
    assert root.expected_execution_fingerprint == "external-v7"


def test_auto_fingerprint_tracks_nested_reduction_stage_semantics():
    def nested(task):
        return parse_reduction_stage_executable_config({
            "type": "reduction_stage", "input_preparer": {"type": "identity"},
            "stage": {
                "worker": {"type": "task", "task": task},
                "reduction": {"enabled": True, "profile": "concat_text"},
            },
        })

    first = bind_persisted_execution_fingerprint(
        _root(semantic_freshness_executable=nested("summary")), Adapter())
    changed = bind_persisted_execution_fingerprint(
        _root(semantic_freshness_executable=nested("other")), Adapter())
    assert first != changed
