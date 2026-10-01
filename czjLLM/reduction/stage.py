"""Source-independent K1 ReductionStage orchestration."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from types import MappingProxyType
from pathlib import Path
from typing import Any, Iterable, Mapping, Protocol, Tuple

from czjLLM.reduction.artifacts import normalized_fingerprint
from czjLLM.reduction.config import ReductionConfig
from czjLLM.reduction.engine import reduce_single_pass
from czjLLM.reduction.execution import Executable, ExecutionContext, ExecutionError, _stable_semantics
from czjLLM.reduction.hierarchical import RoundMetrics, reduce_hierarchical_text


class RoundPreparer(Protocol):
    def prepare(self, payload: str, round_index: int, context: ExecutionContext) -> Iterable[str]: ...
    def fingerprint_metadata(self, context: ExecutionContext) -> Mapping[str, Any]: ...


@dataclass(frozen=True)
class TokenizerRoundPreparer:
    task: str
    tokenizer_factory: Any = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if not isinstance(self.task, str) or not self.task.strip() or self.task != self.task.strip():
            raise ValueError("round preparer task must be non-blank without surrounding whitespace")

    def _effective_input_cut_len(self, context: ExecutionContext) -> int:
        ctx = context.runtime_ctx
        pool = getattr(ctx, "taskSetting", None)
        spec = pool.get(self.task) if isinstance(pool, Mapping) else None
        if isinstance(spec, Mapping) and type(spec.get("InputCutLen")) is int:
            return spec["InputCutLen"]
        if isinstance(pool, Mapping):
            return 3000
        if self.tokenizer_factory is None:
            from czjLLM.taskConfig import taskSetting
            global_spec = taskSetting.get(self.task)
            if isinstance(global_spec, Mapping) and type(global_spec.get("InputCutLen")) is int:
                return global_spec["InputCutLen"]
        return 3000

    def prepare(self, payload: str, round_index: int, context: ExecutionContext) -> Iterable[str]:
        if not isinstance(payload, str) or not payload.strip():
            raise ExecutionError("round preparer requires nonblank aggregate text")
        if type(round_index) is not int or round_index < 2:
            raise ExecutionError("round preparer round_index must be >= 2")
        ctx = context.runtime_ctx
        if ctx is None:
            raise ExecutionError("tokenizer round preparer requires runtime_ctx")
        factory = self.tokenizer_factory
        if factory is None:
            from czjLLM.tokenizer_utils import TokenizerWrapper
            factory = TokenizerWrapper
        tokenizer = factory(model_name=ctx.model_spec_name, task=self.task,
                            max_tokens=ctx.max_tokens)
        tokenizer.max_input_tokens = self._effective_input_cut_len(context)
        chunks = tokenizer.tokenize(
                             text=payload, adjust=True, max_tokens=ctx.max_tokens, quiet=True)["ctxCut"]
        if not isinstance(chunks, (list, tuple)) or not chunks or any(
                not isinstance(chunk, str) or not chunk.strip() for chunk in chunks):
            raise ExecutionError("round tokenizer returned empty or invalid chunks")
        return tuple(chunks)

    def fingerprint_metadata(self, context: ExecutionContext) -> Mapping[str, Any]:
        ctx = context.runtime_ctx
        return {"type": "tokenizer", "contract_version": "reduction-tokenizer-round-preparer-v1",
                "tokenizer_contract_version": "tokenizer-wrapper-v1",
                "task": self.task, "model_name": getattr(ctx, "model_spec_name", None),
                "max_tokens": getattr(ctx, "max_tokens", None),
                "input_cut_len": self._effective_input_cut_len(context)}


@dataclass(frozen=True)
class ReductionStageResult:
    payload: Any
    profile: str
    controller: str
    rounds_completed: int
    stop_reason: str
    worker_execution_count: int
    round_metrics: Tuple[RoundMetrics, ...] = ()
    warnings: Tuple[str, ...] = ()
    audit: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))
    provenance: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))
    metrics: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))

    def __post_init__(self) -> None:
        for name in ("audit", "provenance", "metrics"):
            value = getattr(self, name)
            if not isinstance(value, Mapping):
                raise TypeError(f"ReductionStageResult.{name} must be a mapping")
            object.__setattr__(self, name, MappingProxyType(dict(value)))


@dataclass(frozen=True)
class ReductionStage:
    worker: Executable
    reduction: ReductionConfig
    worker_parallelism: int = 1
    round_preparer: RoundPreparer | None = None
    checkpoint_root: str | Path | None = None
    contract_version: str = field(default="reduction-stage-v1", init=False)

    def __post_init__(self) -> None:
        if type(self.worker_parallelism) is not int or self.worker_parallelism <= 0:
            raise ValueError("worker_parallelism must be a positive integer")
        if not isinstance(self.reduction, ReductionConfig) or not self.reduction.enabled:
            raise ValueError("ReductionStage requires an enabled ReductionConfig")
        hierarchical = self.reduction.controller != "single_pass"
        if hierarchical != (self.round_preparer is not None):
            raise ValueError("round_preparer is required only for hierarchical ReductionStage")

    def execution_fingerprint(self, context: ExecutionContext) -> str:
        data = {"contract_version": self.contract_version,
                "worker": self.worker.fingerprint_metadata(context),
                "round_preparer": self.round_preparer.fingerprint_metadata(context) if self.round_preparer else None}
        return normalized_fingerprint(_stable_semantics(data))

    def execute(self, items: Iterable[Any], context: ExecutionContext) -> ReductionStageResult:
        prepared = list(items)
        if not prepared:
            raise ExecutionError("ReductionStage requires at least one prepared item")
        count = 0

        def work(values: Iterable[Any]) -> list[Any]:
            nonlocal count
            values = list(values)
            from czjLLM.prompt_pipeline.dispatch_parallelism import cap_orchestration_workers
            width = cap_orchestration_workers(context.runtime_ctx, self.worker_parallelism)
            if width == 1:
                results = [self.worker.execute(value, context) for value in values]
            else:
                with ThreadPoolExecutor(max_workers=width) as pool:
                    results = list(pool.map(lambda value: self.worker.execute(value, context), values))
            count += len(results)
            return [result.output for result in results]

        initial_outputs = work(prepared)
        if self.reduction.controller == "single_pass":
            result = reduce_single_pass(initial_outputs, self.reduction,
                                        context=context.reducer_context)
            return self._result(result.payload, 1, "single_pass_complete", count, (),
                                tuple(result.warnings), len(prepared),
                                reducer_audit=result.audit,
                                reducer_provenance=result.provenance,
                                reducer_metrics=result.metrics)

        assert self.round_preparer is not None
        def next_round(payload: str, round_index: int) -> Iterable[str]:
            return work(self.round_preparer.prepare(payload, round_index, context))
        hierarchical = reduce_hierarchical_text(
            initial_outputs, profile=self.reduction.profile or "",
            controller=self.reduction.build_controller(), next_round_items=next_round,
            context=context.reducer_context, checkpoint_root=self.checkpoint_root,
            execution_fingerprint=self.execution_fingerprint(context),
        )
        return self._result(hierarchical.payload, hierarchical.rounds_completed,
                            hierarchical.stop_reason, count, hierarchical.round_metrics,
                            hierarchical.warnings, len(prepared))

    def _result(self, payload: Any, rounds: int, stop: str, count: int,
                round_metrics: Tuple[RoundMetrics, ...], warnings: Tuple[str, ...], inputs: int,
                *, reducer_audit: Mapping[str, Any] | None = None,
                reducer_provenance: Mapping[str, Any] | None = None,
                reducer_metrics: Mapping[str, Any] | None = None) -> ReductionStageResult:
        metrics = {"input_item_count": inputs, "worker_execution_count": count,
                   "round_count": rounds}
        if isinstance(payload, str):
            metrics["output_character_count"] = len(payload)
        if reducer_metrics is not None:
            metrics["reducer"] = dict(reducer_metrics)
        audit = {"execution_fingerprint_contract": self.contract_version}
        if reducer_audit is not None:
            audit["reducer"] = dict(reducer_audit)
        provenance = {}
        if reducer_provenance is not None:
            provenance["reducer"] = dict(reducer_provenance)
        return ReductionStageResult(payload, self.reduction.profile or "",
                                    self.reduction.controller, rounds, stop, count,
                                    tuple(round_metrics), tuple(warnings),
                                    audit=MappingProxyType(audit),
                                    provenance=MappingProxyType(provenance),
                                    metrics=MappingProxyType(metrics))
