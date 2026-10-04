"""Source-independent K1 ReductionStage orchestration."""

from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from functools import wraps
import math
import re
from types import MappingProxyType
from pathlib import Path
from typing import Any, Iterable, Mapping, Protocol, Tuple

from czjLLM.reduction.artifacts import normalized_fingerprint
from czjLLM.reduction.collection import CollectionManifestValidationError, _validate_identity
from czjLLM.reduction.config import ReductionConfig
from czjLLM.reduction.engine import reduce_single_pass
from czjLLM.reduction.execution import (
    Executable, ExecutionCancelled, ExecutionContext, ExecutionError, _stable_semantics,
)
from czjLLM.reduction.factory import build_configured_reducer
from czjLLM.reduction.hierarchical import RoundMetrics, reduce_hierarchical_text
from czjLLM.reduction.registry import get_default_registry
from czjLLM.reduction.runtime_task import CONTENT_PREPARATION_CONTRACT_VERSION


class RoundPreparer(Protocol):
    def prepare(self, payload: str, round_index: int, context: ExecutionContext) -> Iterable[str]: ...
    def fingerprint_metadata(self, context: ExecutionContext) -> Mapping[str, Any]: ...


MAX_MEMBER_FAILURE_DETAILS = 100


@dataclass(frozen=True)
class PartialSuccessPolicy:
    mode: str = "require_all"
    min_success_count: int = 1
    min_success_ratio: float = 0.0

    def __post_init__(self) -> None:
        if self.mode not in {"require_all", "allow_partial"}:
            raise ValueError("failure policy mode must be require_all or allow_partial")
        if type(self.min_success_count) is not int or self.min_success_count < 1:
            raise ValueError("min_success_count must be an integer >= 1")
        if type(self.min_success_ratio) not in {int, float}:
            raise ValueError("min_success_ratio must be a finite number between 0 and 1")
        ratio = float(self.min_success_ratio)
        if not math.isfinite(ratio) or not 0.0 <= ratio <= 1.0:
            raise ValueError("min_success_ratio must be a finite number between 0 and 1")
        object.__setattr__(self, "min_success_ratio", ratio)

    def to_mapping(self) -> dict[str, Any]:
        return {"mode": self.mode, "min_success_count": self.min_success_count,
                "min_success_ratio": self.min_success_ratio}


@dataclass(frozen=True)
class MemberFailureRecord:
    round_index: int
    input_index: int
    logical_id: str | None
    error_type: str
    reason: str = "execution_error"

    def __post_init__(self) -> None:
        if type(self.round_index) is not int or self.round_index < 1:
            raise ValueError("round_index must be an integer >= 1")
        if type(self.input_index) is not int or self.input_index < 0:
            raise ValueError("input_index must be a non-negative integer")
        if self.logical_id is not None and not isinstance(self.logical_id, str):
            raise TypeError("logical_id must be a string or None")
        if not isinstance(self.error_type, str) or not re.fullmatch(
            r"[A-Za-z_][A-Za-z0-9_]*", self.error_type
        ):
            raise ValueError("error_type must be a safe class name")
        if self.reason != "execution_error":
            raise ValueError("member failure reason must be execution_error")

    def to_mapping(self) -> dict[str, Any]:
        return {"round_index": self.round_index, "input_index": self.input_index,
                "logical_id": self.logical_id, "error_type": self.error_type,
                "reason": self.reason}


class PartialSuccessRejectedError(ExecutionError):
    reason = "partial_success_threshold_not_met"

    def __init__(self, *, attempted: int, succeeded: int, failed: int) -> None:
        self.attempted = attempted
        self.succeeded = succeeded
        self.failed = failed
        self.success_ratio = succeeded / attempted if attempted else 0.0
        super().__init__(
            "partial success threshold not met "
            f"(attempted={attempted}, succeeded={succeeded}, failed={failed})"
        )


def _observe_stage_execution(fn):
    @wraps(fn)
    def observed(self, items, context):
        context.emit("reduction_stage_started", profile=self.reduction.profile,
                     controller=self.reduction.controller)
        try:
            result = fn(self, items, context)
        except ExecutionCancelled:
            context.emit("reduction_stage_cancelled", profile=self.reduction.profile,
                         controller=self.reduction.controller, stop_reason="cancelled")
            raise
        except PartialSuccessRejectedError as exc:
            context.emit("reduction_partial_rejected", profile=self.reduction.profile,
                         controller=self.reduction.controller, attempted=exc.attempted,
                         succeeded=exc.succeeded, failed=exc.failed,
                         success_ratio=exc.success_ratio, reason=exc.reason)
            context.emit("reduction_stage_failed", profile=self.reduction.profile,
                         controller=self.reduction.controller,
                         error_type=type(exc).__name__, reason=exc.reason)
            raise
        except BaseException as exc:
            context.emit("reduction_stage_failed", profile=self.reduction.profile,
                         controller=self.reduction.controller,
                         error_type=type(exc).__name__, reason="execution_error")
            raise
        context.emit("reduction_stage_completed", profile=result.profile,
                     controller=result.controller, attempted=result.worker_attempt_count,
                     succeeded=result.worker_success_count, failed=result.worker_failure_count,
                     success_ratio=(result.worker_success_count / result.worker_attempt_count
                                    if result.worker_attempt_count else 0.0),
                     partial_result=result.partial_result, stop_reason=result.stop_reason)
        if result.partial_result:
            context.emit("reduction_partial_accepted", profile=result.profile,
                         controller=result.controller, attempted=result.worker_attempt_count,
                         succeeded=result.worker_success_count, failed=result.worker_failure_count,
                         partial_result=True)
        return result
    return observed


def effective_input_cut_len(
    task: Any, context: ExecutionContext, *, use_global_task_pool: bool = True
) -> int:
    """Resolve the tokenizer boundary shared by initial and round preparation."""
    runtime = context.task_runtime
    if runtime is not None and callable(getattr(runtime, "effective_input_cut_len", None)):
        value = runtime.effective_input_cut_len(task)
        if type(value) is int:
            return value
    pool = getattr(context.runtime_ctx, "taskSetting", None)
    if not isinstance(pool, Mapping):
        if not use_global_task_pool:
            return 3000
        from czjLLM.taskConfig import taskSetting
        pool = taskSetting
    current: Any = task
    seen: set[str] = set()
    while True:
        if isinstance(current, str):
            key = current.strip()
            if not key or key not in pool or key in seen:
                break
            seen.add(key)
            current = pool[key]
        if not isinstance(current, Mapping):
            break
        value = current.get("InputCutLen")
        if type(value) is int:
            return value
        mapped = current.get("task", current.get("prompt", ""))
        key = str(mapped or "").strip()
        if not key or key not in pool or key in seen or pool[key] is current:
            break
        seen.add(key)
        current = pool[key]
    return 3000


@dataclass(frozen=True)
class TokenizerRoundPreparer:
    task: str
    tokenizer_factory: Any = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if not isinstance(self.task, str) or not self.task.strip() or self.task != self.task.strip():
            raise ValueError("round preparer task must be non-blank without surrounding whitespace")

    def prepare(self, payload: str, round_index: int, context: ExecutionContext) -> Iterable[str]:
        if not isinstance(payload, str) or not payload.strip():
            raise ExecutionError("round preparer requires nonblank aggregate text")
        if type(round_index) is not int or round_index < 2:
            raise ExecutionError("round preparer round_index must be >= 2")
        ctx = context.runtime_ctx
        if ctx is None:
            raise ExecutionError("tokenizer round preparer requires runtime_ctx")
        runtime = context.task_runtime
        if runtime is not None and callable(getattr(runtime, "prepare_content_chunks", None)):
            try:
                chunks = runtime.prepare_content_chunks(task=self.task, content=payload)
            except Exception as exc:
                raise ExecutionError(f"round prompt-aware preparation failed: {exc}") from exc
            if not chunks or any(not isinstance(chunk, str) or not chunk.strip() for chunk in chunks):
                raise ExecutionError("round prompt-aware preparation returned invalid chunks")
            return tuple(chunks)
        factory = self.tokenizer_factory
        if factory is None:
            from czjLLM.tokenizer_utils import TokenizerWrapper
            factory = TokenizerWrapper
        tokenizer = factory(model_name=ctx.model_spec_name, task=self.task,
                            max_tokens=ctx.max_tokens)
        tokenizer.max_input_tokens = effective_input_cut_len(
            self.task, context, use_global_task_pool=self.tokenizer_factory is None
        )
        chunks = tokenizer.tokenize(
                             text=payload, adjust=True, max_tokens=ctx.max_tokens, quiet=True)["ctxCut"]
        if not isinstance(chunks, (list, tuple)) or not chunks or any(
                not isinstance(chunk, str) or not chunk.strip() for chunk in chunks):
            raise ExecutionError("round tokenizer returned empty or invalid chunks")
        return tuple(chunks)

    def fingerprint_metadata(self, context: ExecutionContext) -> Mapping[str, Any]:
        ctx = context.runtime_ctx
        return {"type": "tokenizer", "contract_version": "reduction-tokenizer-round-preparer-v3",
                "tokenizer_contract_version": "tokenizer-wrapper-v1",
                "content_preparation_contract": CONTENT_PREPARATION_CONTRACT_VERSION,
                "task": self.task, "model_name": getattr(ctx, "model_spec_name", None),
                "max_tokens": getattr(ctx, "max_tokens", None),
                "input_cut_len": effective_input_cut_len(
                    self.task, context, use_global_task_pool=self.tokenizer_factory is None
                )}


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
    worker_attempt_count: int = 0
    worker_success_count: int = 0
    worker_failure_count: int = 0
    partial_result: bool = False

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
    failure_policy: PartialSuccessPolicy = field(default_factory=PartialSuccessPolicy)
    contract_version: str = field(default="reduction-stage-v3", init=False)

    def __post_init__(self) -> None:
        if type(self.worker_parallelism) is not int or self.worker_parallelism <= 0:
            raise ValueError("worker_parallelism must be a positive integer")
        if not isinstance(self.reduction, ReductionConfig) or not self.reduction.enabled:
            raise ValueError("ReductionStage requires an enabled ReductionConfig")
        if not isinstance(self.failure_policy, PartialSuccessPolicy):
            raise TypeError("failure_policy must be PartialSuccessPolicy")
        hierarchical = self.reduction.controller != "single_pass"
        if hierarchical != (self.round_preparer is not None):
            raise ValueError("round_preparer is required only for hierarchical ReductionStage")

    def execution_fingerprint(self, context: ExecutionContext) -> str:
        return normalized_fingerprint(_stable_semantics(self.fingerprint_metadata(context)))

    def fingerprint_metadata(self, context: ExecutionContext) -> Mapping[str, Any]:
        reducer = build_configured_reducer(
            self.reduction.profile or "", self.reduction.options, get_default_registry()
        )
        return {
            "contract_version": self.contract_version,
            "reduction": {
                "profile": self.reduction.profile,
                "reducer_contract_version": reducer.contract_version,
                "options": _stable_semantics(self.reduction.options),
                "controller": self.reduction.controller,
                "controller_options": _stable_semantics(self.reduction.controller_options),
                "failure_policy": self.failure_policy.to_mapping(),
            },
            "worker": self.worker.fingerprint_metadata(context),
            "round_preparer": (
                self.round_preparer.fingerprint_metadata(context) if self.round_preparer else None
            ),
        }

    @_observe_stage_execution
    def execute(self, items: Iterable[Any], context: ExecutionContext) -> ReductionStageResult:
        context.raise_if_cancelled()
        prepared = list(items)
        if not prepared:
            raise ExecutionError("ReductionStage requires at least one prepared item")
        attempts = successes = failures = 0
        failure_details: list[MemberFailureRecord] = []

        def record_failure(round_index: int, input_index: int, value: Any,
                           exc: ExecutionError) -> None:
            nonlocal failures
            failures += 1
            logical_id = getattr(value, "logical_id", None)
            try:
                logical_id = _validate_identity(logical_id, "logical_id")
            except CollectionManifestValidationError:
                logical_id = None
            if len(failure_details) < MAX_MEMBER_FAILURE_DETAILS:
                failure_details.append(MemberFailureRecord(
                    round_index, input_index, logical_id, type(exc).__name__
                ))
            context.emit("reduction_member_failed", round_index=round_index,
                         input_index=input_index, logical_id=logical_id,
                         error_type=type(exc).__name__, reason="execution_error")

        def work(values: Iterable[Any], round_index: int) -> list[Any]:
            nonlocal attempts, successes
            values = list(values)
            if not values:
                raise ExecutionError("ReductionStage worker batch must not be empty")
            context.raise_if_cancelled()
            from czjLLM.prompt_pipeline.dispatch_parallelism import cap_orchestration_workers
            width = min(len(values), cap_orchestration_workers(
                context.runtime_ctx, self.worker_parallelism
            ))
            ordered: dict[int, Any] = {}
            if width == 1:
                for index, value in enumerate(values):
                    context.raise_if_cancelled()
                    attempts += 1
                    try:
                        result = self.worker.execute(value, context)
                    except ExecutionCancelled:
                        raise
                    except ExecutionError as exc:
                        if self.failure_policy.mode == "require_all":
                            logical_id = getattr(value, "logical_id", None)
                            try:
                                logical_id = _validate_identity(logical_id, "logical_id")
                            except CollectionManifestValidationError:
                                logical_id = None
                            context.emit("reduction_member_failed", round_index=round_index,
                                         input_index=index, logical_id=logical_id,
                                         error_type=type(exc).__name__, reason="execution_error")
                            raise
                        record_failure(round_index, index, value, exc)
                    else:
                        context.raise_if_cancelled()
                        successes += 1
                        ordered[index] = result.output
            else:
                pool = ThreadPoolExecutor(max_workers=width)
                active: dict[Future[Any], int] = {}
                next_index = 0
                try:
                    while next_index < width:
                        context.raise_if_cancelled()
                        future = pool.submit(self.worker.execute, values[next_index], context)
                        active[future] = next_index
                        attempts += 1
                        next_index += 1
                    while active:
                        done, _ = wait(active, return_when=FIRST_COMPLETED)
                        context.raise_if_cancelled()
                        for future in done:
                            index = active.pop(future)
                            try:
                                result = future.result()
                            except ExecutionCancelled:
                                raise
                            except ExecutionError as exc:
                                if self.failure_policy.mode == "require_all":
                                    logical_id = getattr(values[index], "logical_id", None)
                                    try:
                                        logical_id = _validate_identity(logical_id, "logical_id")
                                    except CollectionManifestValidationError:
                                        logical_id = None
                                    context.emit("reduction_member_failed", round_index=round_index,
                                                 input_index=index, logical_id=logical_id,
                                                 error_type=type(exc).__name__, reason="execution_error")
                                    raise
                                record_failure(round_index, index, values[index], exc)
                            else:
                                context.raise_if_cancelled()
                                successes += 1
                                ordered[index] = result.output
                            if next_index < len(values):
                                context.raise_if_cancelled()
                                replacement = pool.submit(
                                    self.worker.execute, values[next_index], context
                                )
                                active[replacement] = next_index
                                attempts += 1
                                next_index += 1
                except Exception:
                    for future in active:
                        future.cancel()
                    raise
                finally:
                    pool.shutdown(wait=True, cancel_futures=True)
            context.raise_if_cancelled()
            batch_succeeded = len(ordered)
            batch_attempted = len(values)
            batch_failed = batch_attempted - batch_succeeded
            ratio = batch_succeeded / batch_attempted
            if self.failure_policy.mode == "allow_partial" and (
                batch_succeeded == 0
                or batch_succeeded < self.failure_policy.min_success_count
                or ratio < self.failure_policy.min_success_ratio
            ):
                raise PartialSuccessRejectedError(
                    attempted=batch_attempted, succeeded=batch_succeeded, failed=batch_failed
                )
            return [ordered[index] for index in sorted(ordered)]

        initial_outputs = work(prepared, 1)
        if self.reduction.controller == "single_pass":
            context.raise_if_cancelled()
            result = reduce_single_pass(initial_outputs, self.reduction,
                                        context=context.reducer_context)
            context.raise_if_cancelled()
            final = self._result(result.payload, 1, "single_pass_complete", attempts,
                                successes, failures, failure_details, (),
                                tuple(result.warnings), len(prepared),
                                reducer_audit=result.audit,
                                reducer_provenance=result.provenance,
                                reducer_metrics=result.metrics)
            context.raise_if_cancelled()
            return final

        assert self.round_preparer is not None
        def next_round(payload: str, round_index: int) -> Iterable[str]:
            context.raise_if_cancelled()
            values = self.round_preparer.prepare(payload, round_index, context)
            return work(values, round_index)
        hierarchical = reduce_hierarchical_text(
            initial_outputs, profile=self.reduction.profile or "",
            controller=self.reduction.build_controller(), next_round_items=next_round,
            context=context.reducer_context, checkpoint_root=self.checkpoint_root,
            execution_fingerprint=self.execution_fingerprint(context),
            cancellation_check=context.raise_if_cancelled,
        )
        context.raise_if_cancelled()
        final = self._result(hierarchical.payload, hierarchical.rounds_completed,
                             hierarchical.stop_reason, attempts, successes, failures,
                             failure_details, hierarchical.round_metrics,
                             hierarchical.warnings, len(prepared))
        context.raise_if_cancelled()
        return final

    def _result(self, payload: Any, rounds: int, stop: str, attempts: int,
                successes: int, failures: int,
                failure_details: list[MemberFailureRecord],
                round_metrics: Tuple[RoundMetrics, ...], warnings: Tuple[str, ...], inputs: int,
                *, reducer_audit: Mapping[str, Any] | None = None,
                reducer_provenance: Mapping[str, Any] | None = None,
                reducer_metrics: Mapping[str, Any] | None = None) -> ReductionStageResult:
        partial = failures > 0
        ratio = successes / attempts if attempts else 0.0
        metrics = {"input_item_count": inputs, "worker_execution_count": attempts,
                   "worker_attempt_count": attempts, "worker_success_count": successes,
                   "worker_failure_count": failures, "worker_success_ratio": ratio,
                   "round_count": rounds, "partial_result": partial}
        if isinstance(payload, str):
            metrics["output_character_count"] = len(payload)
        if reducer_metrics is not None:
            metrics["reducer"] = dict(reducer_metrics)
        omitted = failures - len(failure_details)
        audit = {"execution_fingerprint_contract": self.contract_version,
                 "failure_policy": self.failure_policy.to_mapping(),
                 "partial_result": partial, "failed_member_count": failures,
                 "failure_details_recorded": len(failure_details),
                 "failure_details_omitted": omitted}
        if reducer_audit is not None:
            audit["reducer"] = dict(reducer_audit)
        provenance = {}
        if reducer_provenance is not None:
            provenance["reducer"] = dict(reducer_provenance)
        if partial:
            provenance["partial_success"] = {
                "incomplete": True, "attempted": attempts, "succeeded": successes,
                "failed": failures, "success_ratio": ratio,
                "failures": [item.to_mapping() for item in failure_details],
                "failure_details_omitted": omitted,
            }
            warnings = tuple(warnings) + (
                f"partial_success_accepted: succeeded={successes} "
                f"attempted={attempts} failed={failures}",
            )
        return ReductionStageResult(payload, self.reduction.profile or "",
                                    self.reduction.controller, rounds, stop, attempts,
                                    tuple(round_metrics), tuple(warnings),
                                    audit=MappingProxyType(audit),
                                    provenance=MappingProxyType(provenance),
                                    metrics=MappingProxyType(metrics),
                                    worker_attempt_count=attempts,
                                    worker_success_count=successes,
                                    worker_failure_count=failures,
                                    partial_result=partial)
