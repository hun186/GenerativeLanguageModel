"""Source-independent executable contracts for ReductionStage workers."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping, Protocol


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
class ExecutionContext:
    runtime_ctx: Any = None
    task_runtime: TaskRuntime | None = None
    executable_registry: "ExecutableRegistry | None" = None
    reducer_context: Mapping[str, Any] = field(default_factory=_empty_mapping)

    def __post_init__(self) -> None:
        if not isinstance(self.reducer_context, Mapping):
            raise TypeError("ExecutionContext.reducer_context must be a mapping")
        object.__setattr__(self, "reducer_context", MappingProxyType(dict(self.reducer_context)))


class Executable(Protocol):
    executor_type: str
    contract_version: str
    def execute(self, item: Any, context: ExecutionContext) -> ExecutableResult: ...
    def fingerprint_metadata(self, context: ExecutionContext) -> Mapping[str, Any]: ...


class ExecutableRegistry:
    """Explicit, instance-local registry. K1 accepts ordinary pipelines only."""

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
        return {"executor_type": self.executor_type, "contract_version": self.contract_version,
                "task": _stable_semantics(self.task), "runtime": dict(metadata)}


def _stable_semantics(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(k): _stable_semantics(v) for k, v in sorted(value.items(), key=lambda x: str(x[0]))}
    if isinstance(value, (list, tuple)):
        return [_stable_semantics(v) for v in value]
    if callable(value):
        return {"callable_module": getattr(value, "__module__", ""),
                "callable_qualname": getattr(value, "__qualname__", getattr(value, "__name__", ""))}
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"unsupported fingerprint semantic value: {type(value).__name__}")
