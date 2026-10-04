"""Production adapter for one post-initial hierarchical text map round."""

from __future__ import annotations

import hashlib
import inspect
import json
from pathlib import Path
from typing import Any, Callable, Mapping, Optional

from czjLLM.utilities.fs_safe import safe_atomic_write_text, safe_read_text, safe_rmtree
from czjLLM.reduction.execution import ExecutionCancelled
from czjLLM.reduction.production_control import raise_if_execution_cancelled
from czjLLM.reduction.retention import (
    ArtifactLease,
    ReductionArtifactKind,
    write_artifact_marker,
)


TEXT_ROUND_RUNTIME_CONTRACT_VERSION = "reduction-text-round-v2"


class TextRoundRuntimeError(RuntimeError):
    """A post-initial reduction map round did not complete."""


class _RuntimeContextView:
    """Non-mutating attribute overlay for one reduction map round."""

    def __init__(self, base: Any, **overrides: Any) -> None:
        self._base = base
        self.__dict__.update(overrides)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._base, name)


_MODEL_SEMANTIC_KEYS = frozenset(
    {
        "model_name", "model", "model_version", "version", "temperature",
        "top_p", "top_k", "seed", "repeat_penalty", "frequency_penalty",
        "presence_penalty", "num_ctx", "context_window", "stop",
    }
)


def _stable_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return {
            str(k): _stable_value(v)
            for k, v in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_stable_value(v) for v in value]
    return str(value)


class TextRoundRuntimeAdapter:
    """Re-slice, render, dispatch, and collect exactly one reduction map round."""

    def __init__(
        self,
        *,
        ctx: Any,
        item_workspace: str | Path,
        round_task: str,
        tokenizer_factory: Optional[Callable[..., Any]] = None,
        prompt_generator_factory: Optional[Callable[[Any], Any]] = None,
        llm_dispatch: Optional[Callable[..., Any]] = None,
    ) -> None:
        self.ctx = ctx
        self.item_workspace = Path(item_workspace)
        self.round_task = str(round_task).strip()
        if not self.round_task:
            raise ValueError("round_task must be non-empty")
        self._tokenizer_factory = tokenizer_factory
        self._prompt_generator_factory = prompt_generator_factory
        self._llm_dispatch = llm_dispatch

    def _derived_context(self) -> Any:
        return _RuntimeContextView(self.ctx, task=self.round_task)

    def fingerprint_metadata(self) -> Mapping[str, Any]:
        """Return allowlisted, deterministic semantics; credentials/URLs are excluded."""
        settings = getattr(self.ctx, "taskSetting", {})
        task_spec = (
            settings.get(self.round_task)
            if isinstance(settings, Mapping)
            else None
        )
        if isinstance(task_spec, Mapping) and callable(task_spec.get("template")):
            try:
                template = inspect.getsource(task_spec["template"])
            except (OSError, TypeError):
                template = getattr(
                    task_spec["template"], "__qualname__", "registered-template"
                )
            task_context = {
                key: _stable_value(getattr(self.ctx, key, None))
                for key in (
                    "main_file_name",
                    "keyConsiderations",
                    "textClass",
                    "exclusiveTextClass",
                )
            }
        else:
            template = " ".join(self.round_task.split())
            task_context = {}
        model_spec = getattr(self.ctx, "model_spec", {})
        safe_model_spec = (
            {
                key: _stable_value(model_spec[key])
                for key in sorted(model_spec)
                if key in _MODEL_SEMANTIC_KEYS
            }
            if isinstance(model_spec, Mapping)
            else {}
        )
        input_cut = (
            task_spec.get("InputCutLen", 3000)
            if isinstance(task_spec, Mapping)
            else 3000
        )
        return {
            "contract_version": TEXT_ROUND_RUNTIME_CONTRACT_VERSION,
            "round_task": self.round_task,
            "template": template,
            "task_context": task_context,
            "tokenizer": {
                "wrapper": "TokenizerWrapper",
                "model_name": str(getattr(self.ctx, "model_spec_name", "") or ""),
                "input_cut_len": input_cut,
                "max_tokens": getattr(self.ctx, "max_tokens", None),
                "adjust": True,
            },
            "model": {
                "identity": str(getattr(self.ctx, "model_spec_name", "") or ""),
                "settings": safe_model_spec,
                "max_tokens": getattr(self.ctx, "max_tokens", None),
                "think_mode": bool(getattr(self.ctx, "think_mode", True)),
                "mock_llm_mode": bool(getattr(self.ctx, "mock_llm_mode", False)),
            },
        }

    def execution_fingerprint(self) -> str:
        encoded = json.dumps(
            self.fingerprint_metadata(), ensure_ascii=False, sort_keys=True,
            separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def next_round_items(self, previous_payload: str, next_round_index: int) -> list[str]:
        raise_if_execution_cancelled(self.ctx)
        if not isinstance(previous_payload, str) or not previous_payload.strip():
            raise TextRoundRuntimeError("previous aggregate must be non-empty text")
        if type(next_round_index) is not int or next_round_index < 2:
            raise TextRoundRuntimeError("runtime map rounds must have an index of at least 2")

        derived = self._derived_context()
        raise_if_execution_cancelled(self.ctx)
        tokenizer_factory = self._tokenizer_factory
        if tokenizer_factory is None:
            from czjLLM.tokenizer_utils import TokenizerWrapper

            tokenizer_factory = TokenizerWrapper
        try:
            tokenizer = tokenizer_factory(
                model_name=derived.model_spec_name,
                task=self.round_task,
                max_tokens=derived.max_tokens,
            )
            chunks = tokenizer.tokenize(
                text=previous_payload,
                adjust=True,
                max_tokens=derived.max_tokens,
                quiet=True,
            )["ctxCut"]
        except Exception as exc:
            raise TextRoundRuntimeError(
                f"tokenization failed for reduction round {next_round_index}: {exc}"
            ) from exc
        if not chunks or not all(isinstance(chunk, str) and chunk.strip() for chunk in chunks):
            raise TextRoundRuntimeError("tokenization produced no usable reduction chunks")
        raise_if_execution_cancelled(self.ctx)

        round_dir = (
            self.item_workspace
            / ".reduction"
            / "runtime"
            / f"round-{next_round_index:04d}"
        )
        if round_dir.exists():
            safe_rmtree(round_dir, raise_on_failure=True)
        todo_dir = round_dir / "TODO"
        success_dir = round_dir / "Success"
        todo_dir.mkdir(parents=True)
        success_dir.mkdir(parents=True)
        write_artifact_marker(
            round_dir,
            kind=ReductionArtifactKind.RUNTIME_ROUND,
            artifact_id=round_dir.name,
        )
        runtime_lease = ArtifactLease(round_dir).acquire()
        try:
            width = max(4, len(str(len(chunks) - 1)))
            prompt_generator_factory = self._prompt_generator_factory
            if prompt_generator_factory is None:
                from czjLLM.prompt_pipeline.prompt_generator import PromptGenerator

                prompt_generator_factory = PromptGenerator
            generator = prompt_generator_factory(derived)
            raise_if_execution_cancelled(self.ctx)
            expected_names = []
            try:
                for index, chunk in enumerate(chunks):
                    name = f"{index:0{width}d}.txt"
                    expected_names.append(name)
                    safe_atomic_write_text(
                        todo_dir / name, generator.build(chunk), encoding="utf-8"
                    )
            except Exception as exc:
                raise TextRoundRuntimeError(
                    f"prompt rendering failed for reduction round {next_round_index}: {exc}"
                ) from exc

            dispatch = self._llm_dispatch
            if dispatch is None:
                # Lazy import avoids a combine_utils -> runtime -> pipeline -> combine_utils cycle.
                from czjLLM.prompt_pipeline.pipeline_controller import call_llm_api

                dispatch = call_llm_api
            for allow_to_retry in (True, False):
                raise_if_execution_cancelled(self.ctx)
                runtime_lease.refresh()
                try:
                    dispatch(
                        [str(round_dir)],
                        derived,
                        allow_to_retry=allow_to_retry,
                        task_override=self.round_task,
                    )
                except ExecutionCancelled:
                    raise
                except Exception as exc:
                    raise TextRoundRuntimeError(
                        f"LLM execution failed for reduction round {next_round_index}: {exc}"
                    ) from exc
                raise_if_execution_cancelled(self.ctx)
                runtime_lease.refresh()

            raise_if_execution_cancelled(self.ctx)
            remaining = sorted(path.name for path in todo_dir.glob("*.txt"))
            if remaining:
                raise TextRoundRuntimeError(
                    f"incomplete reduction round {next_round_index}; TODO remains: {remaining}"
                )
            actual = sorted(path.name for path in success_dir.glob("*.txt"))
            if actual != expected_names:
                raise TextRoundRuntimeError(
                    f"reduction round {next_round_index} Success outputs do not match inputs"
                )
            outputs = [safe_read_text(success_dir / name, encoding="utf-8") for name in actual]
            if not outputs or any(not output.strip() for output in outputs):
                raise TextRoundRuntimeError(
                    f"reduction round {next_round_index} produced an empty map result"
                )
            raise_if_execution_cancelled(self.ctx)
            return [output if output.endswith("\n") else output + "\n" for output in outputs]
        finally:
            runtime_lease.release()
