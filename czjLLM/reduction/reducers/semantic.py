"""Source-independent semantic LLM reducer contract and input envelope."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Optional, Protocol

from czjLLM.reduction.contracts import ReducerResult
from czjLLM.reduction.reducers.deterministic import canonical_json


class SemanticReducerError(RuntimeError):
    """Semantic reduction could not safely produce a result."""


@dataclass(frozen=True)
class SemanticCallResult:
    output: str
    cost_twd: float = 0.0
    model_name: str = ""
    ok: bool = True


class SemanticRuntime(Protocol):
    def execute(self, *, task: str, content: str) -> SemanticCallResult: ...


def semantic_content_envelope(items: Iterable[Any]) -> tuple[list[Any], str]:
    """Materialize once and render stable, ordered, explicitly bounded items."""
    prepared = list(items)
    rendered = []
    for index, item in enumerate(prepared, 1):
        content = item if isinstance(item, str) else canonical_json(item)
        rendered.append(
            f"--- ITEM {index:06d} ---\n{content}\n--- END ITEM {index:06d} ---"
        )
    return prepared, "\n\n".join(rendered)


@dataclass(frozen=True)
class SemanticLLMReducer:
    task: str = ""
    profile: str = "semantic_llm"
    contract_version: str = "1"
    requires_stable_order: bool = True
    preserves_order: bool = False
    _allow_unconfigured: bool = field(default=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if not isinstance(self.task, str) or (not self._allow_unconfigured and not self.task.strip()):
            raise SemanticReducerError("semantic_llm task must be a non-blank string")

    @classmethod
    def _registry_prototype(cls) -> "SemanticLLMReducer":
        return cls(_allow_unconfigured=True)

    def reduce(self, items: Iterable[Any], context: Optional[Mapping[str, Any]] = None) -> ReducerResult:
        if not self.task.strip():
            raise SemanticReducerError("semantic_llm requires a configured non-blank task")
        prepared, content = semantic_content_envelope(items)
        if not prepared:
            raise SemanticReducerError("semantic_llm requires at least one input item")
        runtime = context.get("semantic_runtime") if isinstance(context, Mapping) else None
        if runtime is None or not callable(getattr(runtime, "execute", None)):
            raise SemanticReducerError("semantic_llm requires a semantic_runtime")
        try:
            result = runtime.execute(task=self.task, content=content)
        except SemanticReducerError:
            raise
        except Exception as exc:
            raise SemanticReducerError(f"semantic runtime failed: {exc}") from exc
        if not isinstance(result, SemanticCallResult):
            raise SemanticReducerError("semantic runtime returned an invalid result")
        if not result.ok:
            raise SemanticReducerError("semantic runtime reported failure")
        if not isinstance(result.output, str) or not result.output.strip():
            raise SemanticReducerError("semantic runtime returned empty output")
        output = result.output
        input_chars = sum(len(item if isinstance(item, str) else canonical_json(item)) for item in prepared)
        audit = {
            "task_sha256": hashlib.sha256(self.task.encode("utf-8")).hexdigest(),
            "model_name": result.model_name,
            "cost_twd": float(result.cost_twd),
        }
        changed = not (len(prepared) == 1 and isinstance(prepared[0], str) and output == prepared[0])
        return ReducerResult(
            output, self.profile, self.contract_version, changed,
            audit=audit,
            metrics={"input_count": len(prepared), "input_character_count": input_chars,
                     "output_character_count": len(output)},
        )
