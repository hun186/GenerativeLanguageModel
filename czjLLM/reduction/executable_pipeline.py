"""Ordinary in-memory stage pipelines and bounded K2 pipeline references."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
import copy
from types import MappingProxyType
from typing import Any, Mapping

from czjLLM.reduction.execution import (
    ExecutableResult, ExecutionContext, ExecutionError, TaskExecutable, _stable_semantics,
)
from czjLLM.reduction.artifacts import normalized_fingerprint


class _PipelineContextView:
    def __init__(self, base: Any, stages: Any, task_setting: Mapping[str, Any] | None) -> None:
        self._base = base
        self.stages = stages
        if task_setting is not None:
            self.taskSetting = task_setting

    def __getattr__(self, name: str) -> Any:
        return getattr(self._base, name)


@dataclass(frozen=True)
class StagePipelineExecutable:
    stages: Any
    task_setting: Mapping[str, Any] | None = None
    max_rounds: int = 20
    executor_type: str = field(default="stage_pipeline", init=False)
    contract_version: str = field(default="reduction-stage-pipeline-v1", init=False)

    def __post_init__(self) -> None:
        if type(self.max_rounds) is not int or self.max_rounds <= 0:
            raise ValueError("max_rounds must be a positive integer")
        from czjLLM.prompt_pipeline.stage_runtime import normalize_stages
        normalized = tuple(normalize_stages(copy.deepcopy(self.stages)))
        object.__setattr__(self, "stages", normalized)
        if self.task_setting is not None:
            object.__setattr__(self, "task_setting",
                               MappingProxyType(copy.deepcopy(dict(self.task_setting))))

    def _effective_task_pool(self, context: ExecutionContext) -> Mapping[str, Any]:
        if self.task_setting is not None:
            return self.task_setting
        pool = getattr(context.runtime_ctx, "taskSetting", None)
        if isinstance(pool, Mapping):
            return pool
        runtime = context.task_runtime
        if runtime is not None and callable(getattr(runtime, "effective_task_pool", None)):
            pool = runtime.effective_task_pool()
            if isinstance(pool, Mapping):
                return pool
        return MappingProxyType({})

    def execute(self, item: Any, context: ExecutionContext) -> ExecutableResult:
        if not isinstance(item, str):
            raise ExecutionError("StagePipelineExecutable requires text input")
        if context.runtime_ctx is None:
            raise ExecutionError("StagePipelineExecutable requires runtime_ctx")
        from czjLLM.prompt_pipeline.stage_orchestrator import (
            init_chunk_stage_runtime, resolve_pipeline_stages, run_stage_pipeline,
        )
        # The production resolver accepts its public mapping schema (rather than
        # already-normalized StageDefinition objects), so adapt back without
        # changing or duplicating its state machine.
        effective_pool = self._effective_task_pool(context)
        ctx = _PipelineContextView(
            context.runtime_ctx, [copy.deepcopy(dict(stage.__dict__)) for stage in self.stages],
            effective_pool,
        )
        task_runtime = context.task_runtime
        if task_runtime is not None and callable(getattr(task_runtime, "for_context", None)):
            task_runtime = task_runtime.for_context(ctx)
        leaf_context = replace(context, runtime_ctx=ctx, task_runtime=task_runtime)
        chunk_id = "reduction-worker-item"
        runtime = init_chunk_stage_runtime(ctx, [chunk_id])
        def runner(job, _ctx, input_text):
            try:
                result = TaskExecutable(job.stage_task).execute(input_text, leaf_context)
                return {"ok": True, "output": result.output}
            except Exception as exc:
                return {"ok": False, "error": str(exc)}

        report = run_stage_pipeline(ctx, runtime, runner, max_rounds=self.max_rounds,
                                    original_inputs={chunk_id: item})
        stages = resolve_pipeline_stages(ctx)
        final = report["final"]
        states = runtime[chunk_id].stages
        if final["finished_chunks"] != 1 or any(state.state == "error" for state in states.values()):
            details = "; ".join(
                f"{name}={state.state}:{state.last_error}" for name, state in states.items()
            )
            raise ExecutionError(f"stage pipeline did not fully finish ({details})")
        if report["max_rounds_reached"] and final["finished_chunks"] != 1:
            raise ExecutionError("stage pipeline reached max orchestration rounds")
        output = report["stage_outputs"].get(chunk_id, {}).get(stages[-1].name)
        if not isinstance(output, str) or not output.strip():
            raise ExecutionError("stage pipeline final output is absent or blank")
        return ExecutableResult(output, self.executor_type, self.contract_version,
                                audit=MappingProxyType({"stage_count": len(stages)}),
                                metrics=MappingProxyType({"orchestration_round_count": len(report["rounds"]),
                                                          "output_character_count": len(output)}))

    def fingerprint_metadata(self, context: ExecutionContext) -> Mapping[str, Any]:
        stages = []
        for stage in self.stages:
            stages.append(_stable_semantics(stage.__dict__))
        runtime = context.task_runtime
        effective_pool = self._effective_task_pool(context)
        if runtime is not None and callable(getattr(runtime, "for_context", None)):
            runtime = runtime.for_context(_PipelineContextView(
                context.runtime_ctx, [copy.deepcopy(dict(stage.__dict__)) for stage in self.stages],
                effective_pool,
            ))
        return {"executor_type": self.executor_type, "contract_version": self.contract_version,
                "stages": stages, "task_setting": _stable_semantics(effective_pool),
                "max_rounds": self.max_rounds,
                "task_runtime": dict(runtime.fingerprint_metadata()) if runtime else {}}


@dataclass(frozen=True)
class PipelineRefExecutable:
    ref: str
    executor_type: str = field(default="pipeline_ref", init=False)
    contract_version: str = field(default="reduction-pipeline-ref-v1", init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.ref, str) or not self.ref.strip() or self.ref != self.ref.strip():
            raise ValueError("pipeline ref must be non-blank without surrounding whitespace")

    def _target(self, context: ExecutionContext):
        if context.executable_registry is None:
            raise ExecutionError("PipelineRefExecutable requires an executable registry")
        target = context.executable_registry.resolve(self.ref)
        from czjLLM.reduction.nested_execution import ReductionStageExecutable
        if not isinstance(target, (StagePipelineExecutable, PipelineRefExecutable,
                                   ReductionStageExecutable)):
            raise ExecutionError(
                "PipelineRef target must be StagePipelineExecutable, "
                "PipelineRefExecutable, or ReductionStageExecutable"
            )
        return target

    def execute(self, item: Any, context: ExecutionContext) -> ExecutableResult:
        derived_context = context.push_pipeline_ref(self.ref)
        target = self._target(derived_context)
        result = target.execute(item, derived_context)
        target_metadata = target.fingerprint_metadata(derived_context)
        fingerprint = normalized_fingerprint(target_metadata)
        return ExecutableResult(result.output, result.executor_type, result.contract_version,
                                audit=MappingProxyType({"pipeline_ref": self.ref,
                                                        "target_fingerprint": fingerprint,
                                                        "target": result.audit}),
                                provenance=result.provenance, metrics=result.metrics)

    def fingerprint_metadata(self, context: ExecutionContext) -> Mapping[str, Any]:
        derived_context = context.push_pipeline_ref(self.ref)
        target = self._target(derived_context)
        return {"executor_type": self.executor_type, "contract_version": self.contract_version,
                "ref": self.ref, "target": target.fingerprint_metadata(derived_context)}
