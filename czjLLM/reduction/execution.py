"""Source-independent executable contracts for ReductionStage workers."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
import copy
import inspect
from types import MappingProxyType
from typing import Any, Mapping, Protocol

from czjLLM.reduction.artifacts import normalized_fingerprint


PROCESSING_IDENTITY_CONTRACT_VERSION = "reduction-processing-identity-v1"


@dataclass(frozen=True)
class ProcessingIdentity:
    """Safe identity persisted beside a derived destination result."""

    execution_fingerprint: str
    contract_version: str = PROCESSING_IDENTITY_CONTRACT_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.execution_fingerprint, str) or not self.execution_fingerprint.strip():
            raise ValueError("execution_fingerprint must be non-blank")


def executable_semantic_fingerprint(executable: "Executable", context: "ExecutionContext") -> str:
    """Hash the established Executable semantic metadata contract."""
    return normalized_fingerprint(_stable_semantics(executable.fingerprint_metadata(context)))


class ExecutionError(RuntimeError):
    """An executable failed closed."""


def _empty_mapping() -> Mapping[str, Any]:
    return MappingProxyType({})


@dataclass(frozen=True)
class ExecutableResult:
    output: Any
    executor_type: str
    contract_version: str
    audit: Mapping[str, Any] = field(default_factory=_empty_mapping)
    provenance: Mapping[str, Any] = field(default_factory=_empty_mapping)
    metrics: Mapping[str, Any] = field(default_factory=_empty_mapping)

    def __post_init__(self) -> None:
        for name in ("audit", "provenance", "metrics"):
            value = getattr(self, name)
            if not isinstance(value, Mapping):
                raise TypeError(f"ExecutableResult.{name} must be a mapping")
            object.__setattr__(self, name, MappingProxyType(dict(value)))


@dataclass(frozen=True)
class TaskCallResult:
    output: str
    ok: bool
    model_name: str = ""
    cost_twd: float = 0.0


class TaskRuntime(Protocol):
    def execute(self, *, task: Any, content: str) -> TaskCallResult: ...
    def fingerprint_metadata(self) -> Mapping[str, Any]: ...


@dataclass(frozen=True)
class ExecutionNestingState:
    """Immutable K2 traversal guards with deliberately small v1 limits."""

    nested_reduction_depth: int = 0
    max_nested_reduction_depth: int = 1
    pipeline_ref_stack: tuple[str, ...] = ()
    max_pipeline_ref_depth: int = 4

    def __post_init__(self) -> None:
        if type(self.nested_reduction_depth) is not int or self.nested_reduction_depth < 0:
            raise ValueError("nested_reduction_depth must be a non-negative integer")
        if type(self.max_nested_reduction_depth) is not int or not 0 <= self.max_nested_reduction_depth <= 1:
            raise ValueError("max_nested_reduction_depth must be 0 or 1")
        if self.nested_reduction_depth > self.max_nested_reduction_depth:
            raise ValueError("nested_reduction_depth exceeds configured maximum")
        if not isinstance(self.pipeline_ref_stack, tuple) or any(
                not isinstance(name, str) or not name.strip() or name != name.strip()
                for name in self.pipeline_ref_stack):
            raise ValueError("pipeline_ref_stack must contain non-blank ref names")
        if len(set(self.pipeline_ref_stack)) != len(self.pipeline_ref_stack):
            raise ValueError("pipeline_ref_stack must not contain a cycle")
        if type(self.max_pipeline_ref_depth) is not int or not 1 <= self.max_pipeline_ref_depth <= 4:
            raise ValueError("max_pipeline_ref_depth must be between 1 and 4")
        if len(self.pipeline_ref_stack) > self.max_pipeline_ref_depth:
            raise ValueError("pipeline_ref_stack exceeds configured maximum")

    def enter_nested_reduction(self) -> "ExecutionNestingState":
        next_depth = self.nested_reduction_depth + 1
        if next_depth > self.max_nested_reduction_depth:
            raise ExecutionError(
                "nested ReductionStage depth exceeds max_nested_reduction_depth "
                f"{self.max_nested_reduction_depth}"
            )
        return replace(self, nested_reduction_depth=next_depth)

    def push_pipeline_ref(self, ref_name: str) -> "ExecutionNestingState":
        if not isinstance(ref_name, str) or not ref_name.strip() or ref_name != ref_name.strip():
            raise ExecutionError("pipeline ref name must be non-blank without surrounding whitespace")
        path = self.pipeline_ref_stack + (ref_name,)
        if ref_name in self.pipeline_ref_stack:
            raise ExecutionError(f"pipeline ref cycle detected: {' -> '.join(path)}")
        if len(path) > self.max_pipeline_ref_depth:
            raise ExecutionError(
                "pipeline ref depth exceeds max_pipeline_ref_depth "
                f"{self.max_pipeline_ref_depth}: {' -> '.join(path)}"
            )
        return replace(self, pipeline_ref_stack=path)


@dataclass(frozen=True)
class ExecutionContext:
    runtime_ctx: Any = None
    task_runtime: TaskRuntime | None = None
    executable_registry: "ExecutableRegistry | None" = None
    reducer_context: Mapping[str, Any] = field(default_factory=_empty_mapping)
    nesting: ExecutionNestingState = field(default_factory=ExecutionNestingState)

    def __post_init__(self) -> None:
        if not isinstance(self.reducer_context, Mapping):
            raise TypeError("ExecutionContext.reducer_context must be a mapping")
        if not isinstance(self.nesting, ExecutionNestingState):
            raise TypeError("ExecutionContext.nesting must be ExecutionNestingState")
        object.__setattr__(self, "reducer_context", MappingProxyType(dict(self.reducer_context)))

    def enter_nested_reduction(self) -> "ExecutionContext":
        return replace(self, nesting=self.nesting.enter_nested_reduction())

    def push_pipeline_ref(self, ref_name: str) -> "ExecutionContext":
        return replace(self, nesting=self.nesting.push_pipeline_ref(ref_name))


class Executable(Protocol):
    executor_type: str
    contract_version: str
    def execute(self, item: Any, context: ExecutionContext) -> ExecutableResult: ...
    def fingerprint_metadata(self, context: ExecutionContext) -> Mapping[str, Any]: ...


class ExecutableRegistry:
    """Explicit, instance-local executable registry."""

    def __init__(self, entries: Mapping[str, Executable] | None = None) -> None:
        self._entries: dict[str, Executable] = {}
        for name, executable in (entries or {}).items():
            self.register(name, executable)

    def register(self, name: str, executable: Executable) -> None:
        if not isinstance(name, str) or not name.strip() or name != name.strip():
            raise ValueError("executable registry name must be non-blank without surrounding whitespace")
        if name in self._entries:
            raise ValueError(f"duplicate executable registry name: {name}")
        self._entries[name] = executable

    def resolve(self, name: str) -> Executable:
        try:
            return self._entries[name]
        except KeyError as exc:
            raise ExecutionError(f"unknown pipeline ref: {name}") from exc


@dataclass(frozen=True)
class TaskExecutable:
    task: Any
    executor_type: str = field(default="task", init=False)
    contract_version: str = field(default="reduction-task-executable-v1", init=False)

    def __post_init__(self) -> None:
        if isinstance(self.task, Mapping):
            object.__setattr__(self, "task", copy.deepcopy(dict(self.task)))

    def execute(self, item: Any, context: ExecutionContext) -> ExecutableResult:
        if not isinstance(item, str):
            raise ExecutionError("TaskExecutable requires text input")
        runtime = context.task_runtime
        if runtime is None or not callable(getattr(runtime, "execute", None)):
            raise ExecutionError("TaskExecutable requires a valid task runtime")
        try:
            result = runtime.execute(task=self.task, content=item)
        except Exception as exc:
            raise ExecutionError(f"task execution failed: {exc}") from exc
        if not isinstance(result, TaskCallResult) or not result.ok:
            raise ExecutionError("task runtime returned a failed or invalid result")
        if not isinstance(result.output, str) or not result.output.strip():
            raise ExecutionError("task runtime returned blank output")
        return ExecutableResult(
            output=result.output, executor_type=self.executor_type,
            contract_version=self.contract_version,
            audit=MappingProxyType({"model_name": result.model_name}),
            metrics=MappingProxyType({"cost_twd": result.cost_twd, "output_character_count": len(result.output)}),
        )

    def fingerprint_metadata(self, context: ExecutionContext) -> Mapping[str, Any]:
        runtime = context.task_runtime
        metadata = runtime.fingerprint_metadata() if runtime and callable(getattr(runtime, "fingerprint_metadata", None)) else {}
        task_semantics = (
            runtime.effective_task_semantics(self.task)
            if runtime and callable(getattr(runtime, "effective_task_semantics", None))
            else _stable_semantics(self.task)
        )
        return {"executor_type": self.executor_type, "contract_version": self.contract_version,
                "task": task_semantics, "runtime": dict(metadata)}


def _stable_semantics(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(k): _stable_semantics(v) for k, v in sorted(value.items(), key=lambda x: str(x[0]))}
    if isinstance(value, (list, tuple)):
        return [_stable_semantics(v) for v in value]
    if callable(value):
        semantic = {"callable_module": getattr(value, "__module__", ""),
                    "callable_qualname": getattr(value, "__qualname__", getattr(value, "__name__", ""))}
        try:
            semantic["callable_source"] = inspect.getsource(value)
        except (OSError, TypeError):
            pass
        return semantic
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"unsupported fingerprint semantic value: {type(value).__name__}")
