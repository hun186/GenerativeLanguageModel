"""Production Stage orchestration boundaries: observed run events, not document failure."""
import json
from types import SimpleNamespace

import pytest

from czjLLM.prompt_pipeline import stage_orchestrator as so
from czjLLM.reduction.execution import ExecutionCancelled
from czjLLM.utilities.processing_quality import QualityTailReader, quality_event_path


def _ctx(tmp_path):
    return SimpleNamespace(
        stages=[{"name": "extract", "task": "extract private text"}],
        llm_call_audit_path=str(tmp_path / "llm_call_audit_stage.csv"),
        llm_call_audit_run_id="stage-incidents",
    )


def _runtime(ctx):
    return so.init_chunk_stage_runtime(ctx, ["private-chunk-path"])


def _recorded(ctx):
    path = quality_event_path(ctx.llm_call_audit_path)
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_stage_runner_exception_emits_one_run_event_then_propagates(tmp_path):
    ctx = _ctx(tmp_path)

    def failing_runner(*_args):
        raise OSError("sensitive stage execution path and prompt")

    with pytest.raises(OSError, match="sensitive stage"):
        so.execute_stage_round(
            ctx, _runtime(ctx), failing_runner,
            original_inputs={"private-chunk-path": "private document content"},
        )

    rows = _recorded(ctx)
    assert len(rows) == 1
    assert rows[0]["event"] == "stage_orchestration_failure"
    assert rows[0]["code"] == "STAGE_RUNNER_EXCEPTION"
    assert rows[0]["scope"] == "run"
    assert rows[0]["document_id"] == rows[0]["slice_id"] == ""
    raw = quality_event_path(ctx.llm_call_audit_path).read_text(encoding="utf-8")
    for secret in ("private-chunk-path", "private document content", "sensitive stage", "extract private text"):
        assert secret not in raw
    stats = QualityTailReader(str(quality_event_path(ctx.llm_call_audit_path))).poll()[1]
    assert stats["stage_orchestration_failure_events"] == 1
    assert stats["documents_decided"] == 0
    assert stats["slice_validation_attempts"] == 0


def test_stage_input_preparation_exception_emits_only_prepare_code(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path)
    calls = []

    def broken_input(**_kwargs):
        raise ValueError("private source path")

    monkeypatch.setattr(so, "resolve_stage_input", broken_input)
    with pytest.raises(ValueError, match="private source"):
        so.execute_stage_round(ctx, _runtime(ctx), lambda *_args: calls.append(True))
    assert calls == []
    assert [record["code"] for record in _recorded(ctx)] == ["STAGE_PREPARE_EXCEPTION"]


def test_stage_task_resolution_exception_emits_prepare_code(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path)
    def cannot_prepare(*_args, **_kwargs):
        raise RuntimeError("private task content")
    monkeypatch.setattr(so, "resolve_stage_task", cannot_prepare)
    with pytest.raises(RuntimeError, match="private task"):
        so.execute_stage_round(ctx, _runtime(ctx), lambda *_args: True)
    assert [record["code"] for record in _recorded(ctx)] == ["STAGE_PREPARE_EXCEPTION"]


def test_stage_runner_cancel_is_not_a_failure(tmp_path):
    ctx = _ctx(tmp_path)

    def cancel(*_args):
        raise ExecutionCancelled("cooperative cancellation")

    with pytest.raises(ExecutionCancelled):
        so.execute_stage_round(ctx, _runtime(ctx), cancel)
    assert not quality_event_path(ctx.llm_call_audit_path).exists()


def test_stage_two_argument_runner_compatibility_does_not_record_failure(tmp_path):
    ctx = _ctx(tmp_path)
    attempts = []

    def legacy_runner(job, _ctx):
        attempts.append(job.stage_name)
        return {"ok": True, "output": "finished"}

    outcome = so.execute_stage_round(ctx, _runtime(ctx), legacy_runner)
    assert outcome.finished_chunks == 1
    assert attempts == ["extract"]
    assert not quality_event_path(ctx.llm_call_audit_path).exists()


def test_stage_returned_failure_is_not_an_exception_incident(tmp_path):
    ctx = _ctx(tmp_path)
    outcome = so.execute_stage_round(
        ctx, _runtime(ctx),
        lambda *_args: {"ok": False, "error": "private provider failure"},
    )
    assert outcome.dispatched_jobs == 1
    assert not quality_event_path(ctx.llm_call_audit_path).exists()


def test_stage_legacy_fallback_exception_is_recorded_once(tmp_path):
    ctx = _ctx(tmp_path)
    invocations = []

    def legacy_broken(job, _ctx):
        invocations.append(job.stage_name)
        raise RuntimeError("private exception after compatibility fallback")

    with pytest.raises(RuntimeError, match="private exception"):
        so.execute_stage_round(ctx, _runtime(ctx), legacy_broken)
    assert invocations == ["extract"]
    assert [row["code"] for row in _recorded(ctx)] == ["STAGE_RUNNER_EXCEPTION"]


def test_stage_audit_failure_does_not_override_runner_error(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path)
    monkeypatch.setattr(
        so, "emit_quality_event",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("quality file broken")),
    )
    def runner(*_args):
        raise ValueError("authoritative runner exception")
    with pytest.raises(ValueError, match="authoritative runner exception"):
        so.execute_stage_round(ctx, _runtime(ctx), runner)
    assert not quality_event_path(ctx.llm_call_audit_path).exists()


def test_stage_audit_failure_does_not_override_cancellation(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path)
    monkeypatch.setattr(
        so, "emit_quality_event",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("quality file broken")),
    )
    def cancel(*_args):
        raise ExecutionCancelled("stop")
    with pytest.raises(ExecutionCancelled):
        so.execute_stage_round(ctx, _runtime(ctx), cancel)
    assert not quality_event_path(ctx.llm_call_audit_path).exists()
