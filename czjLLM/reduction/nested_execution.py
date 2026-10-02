"""Bounded K2 nested ReductionStage execution and initial input preparation."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Iterable, Mapping, Protocol

from czjLLM.reduction.execution import (
    ExecutableResult, ExecutionContext, ExecutionError, TaskExecutable,
)
from czjLLM.reduction.stage import ReductionStage, effective_input_cut_len


class InputPreparer(Protocol):
    def prepare(self, item: Any, context: ExecutionContext) -> Iterable[Any]: ...
    def fingerprint_metadata(self, context: ExecutionContext) -> Mapping[str, Any]: ...


@dataclass(frozen=True)
class IdentityInputPreparer:
    contract_version: str = field(default="reduction-identity-input-preparer-v1", init=False)

    def prepare(self, item: Any, context: ExecutionContext) -> Iterable[Any]:
        return (item,)

    def fingerprint_metadata(self, context: ExecutionContext) -> Mapping[str, Any]:
        return {"type": "identity", "contract_version": self.contract_version}


@dataclass(frozen=True)
class TokenizerInputPreparer:
    task: str
    tokenizer_factory: Any = field(default=None, repr=False, compare=False)
    contract_version: str = field(default="reduction-tokenizer-input-preparer-v1", init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.task, str) or not self.task.strip() or self.task != self.task.strip():
            raise ValueError("input preparer task must be non-blank without surrounding whitespace")

    def prepare(self, item: Any, context: ExecutionContext) -> Iterable[str]:
        if not isinstance(item, str):
            raise ExecutionError("tokenizer input preparer requires text input")
        if not item.strip():
            raise ExecutionError("tokenizer input preparer requires nonblank text input")
        ctx = context.runtime_ctx
        if ctx is None:
            raise ExecutionError("tokenizer input preparer requires runtime_ctx")
        factory = self.tokenizer_factory
        if factory is None:
            from czjLLM.tokenizer_utils import TokenizerWrapper
            factory = TokenizerWrapper
        tokenizer = factory(model_name=ctx.model_spec_name, task=self.task,
                            max_tokens=ctx.max_tokens)
        tokenizer.max_input_tokens = effective_input_cut_len(
            self.task, context, use_global_task_pool=self.tokenizer_factory is None
        )
        chunks = tokenizer.tokenize(text=item, adjust=True, max_tokens=ctx.max_tokens,
                                    quiet=True)["ctxCut"]
        if not isinstance(chunks, (list, tuple)) or not chunks or any(
                not isinstance(chunk, str) or not chunk.strip() for chunk in chunks):
            raise ExecutionError("input tokenizer returned empty or invalid chunks")
        return tuple(chunks)

    def fingerprint_metadata(self, context: ExecutionContext) -> Mapping[str, Any]:
        ctx = context.runtime_ctx
        return {
            "type": "tokenizer",
            "contract_version": self.contract_version,
            "tokenizer_contract_version": "tokenizer-wrapper-v1",
            "task": self.task,
            "model_spec_name": getattr(ctx, "model_spec_name", None),
            "max_tokens": getattr(ctx, "max_tokens", None),
            "input_cut_len": effective_input_cut_len(
                self.task, context, use_global_task_pool=self.tokenizer_factory is None
            ),
        }


@dataclass(frozen=True)
class ReductionStageExecutable:
    stage: ReductionStage
    input_preparer: InputPreparer
    executor_type: str = field(default="reduction_stage", init=False)
    contract_version: str = field(default="reduction-stage-executable-v1", init=False)

    def __post_init__(self) -> None:
        from czjLLM.reduction.executable_pipeline import PipelineRefExecutable
        if not isinstance(self.stage, ReductionStage):
            raise TypeError("ReductionStageExecutable.stage must be a ReductionStage")
        if not isinstance(self.stage.worker, (TaskExecutable, PipelineRefExecutable)):
            raise ValueError(
                "nested ReductionStage worker must be TaskExecutable or PipelineRefExecutable"
            )
        if self.stage.reduction.requires_semantic_runtime():
            raise ValueError("nested ReductionStageExecutable does not support semantic reducers in K2 v1")
        if not callable(getattr(self.input_preparer, "prepare", None)) or not callable(
                getattr(self.input_preparer, "fingerprint_metadata", None)):
            raise TypeError("ReductionStageExecutable.input_preparer must implement InputPreparer")

    def execute(self, item: Any, context: ExecutionContext) -> ExecutableResult:
        nested_context = context.enter_nested_reduction()
        prepared = list(self.input_preparer.prepare(item, nested_context))
        if not prepared:
            raise ExecutionError("nested ReductionStage input preparer returned no items")
        result = self.stage.execute(prepared, nested_context)
        audit = {
            "nested_reduction_depth": nested_context.nesting.nested_reduction_depth,
            "stop_reason": result.stop_reason,
            "rounds_completed": result.rounds_completed,
            "stage": dict(result.audit),
        }
        metrics = {
            "prepared_input_count": len(prepared),
            "child_worker_execution_count": result.worker_execution_count,
            "stage": dict(result.metrics),
        }
        return ExecutableResult(
            result.payload, self.executor_type, self.contract_version,
            audit=MappingProxyType(audit),
            provenance=MappingProxyType({"stage": dict(result.provenance)}),
            metrics=MappingProxyType(metrics),
        )

    def fingerprint_metadata(self, context: ExecutionContext) -> Mapping[str, Any]:
        nested_context = context.enter_nested_reduction()
        return {
            "executor_type": self.executor_type,
            "contract_version": self.contract_version,
            "input_preparer": self.input_preparer.fingerprint_metadata(nested_context),
            "stage": self.stage.fingerprint_metadata(nested_context),
        }
