"""Production TaskRuntime adapter reusing the prompt-pipeline LLM stack."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping

from czjLLM.reduction.execution import TaskCallResult, _stable_semantics


PROMPT_RENDERER_CONTRACT_VERSION = "stage-task-renderer-v1"
TASK_RUNTIME_CONTRACT_VERSION = "production-task-runtime-v2"
TOKENIZER_CONTRACT_VERSION = "tokenizer-wrapper-v1"
CONTENT_PREPARATION_CONTRACT_VERSION = "production-prompt-aware-split-v1"
_MODEL_SEMANTIC_KEYS = frozenset({
    "model_name", "model", "model_version", "version", "temperature", "top_p",
    "top_k", "seed", "repeat_penalty", "frequency_penalty", "presence_penalty",
    "num_ctx", "context_window", "stop", "mock_llm_mode",
})


@dataclass(frozen=True)
class TaskPromptPreflight:
    """Bounded result from rendering and tokenizing one prospective task call."""

    fits_one_chunk: bool
    rendered_prompt: str
    chunk_count: int


class ProductionTaskRuntime:
    def __init__(self, runtime_ctx: Any, *, tokenizer_factory: Callable[..., Any] | None = None,
                 pipeline_factory: Callable[..., Any] | None = None,
                 lease_factory: Callable[..., Any] | None = None,
                 renderer: Callable[..., str] | None = None) -> None:
        self.ctx = runtime_ctx
        self._tokenizer_factory = tokenizer_factory
        self._pipeline_factory = pipeline_factory
        self._lease_factory = lease_factory
        self._renderer = renderer

    def for_context(self, runtime_ctx: Any) -> "ProductionTaskRuntime":
        """Bind one pipeline invocation to its authoritative effective task pool."""
        return type(self)(runtime_ctx, tokenizer_factory=self._tokenizer_factory,
                          pipeline_factory=self._pipeline_factory,
                          lease_factory=self._lease_factory, renderer=self._renderer)

    def _task_pool(self) -> Mapping[str, Any]:
        pool = getattr(self.ctx, "taskSetting", None)
        if isinstance(pool, Mapping):
            return pool
        from czjLLM.taskConfig import taskSetting
        return taskSetting

    def effective_task_pool(self) -> Mapping[str, Any]:
        """Return the exact pool used by rendering, tokenization, and identity."""
        return self._task_pool()

    def _effective_task_spec(self, task: Any) -> Any:
        if isinstance(task, Mapping):
            return task
        key = str(task or "").strip()
        pool = self._task_pool()
        return pool[key] if key and key in pool else task

    def _task_resolution_chain(self, task: Any) -> tuple[Any, ...]:
        """Follow renderer task mappings once per key and terminate on cycles."""
        pool = self._task_pool()
        current = task
        seen: set[str] = set()
        chain: list[Any] = []
        while True:
            if isinstance(current, str):
                key = current.strip()
                if not key or key not in pool or key in seen:
                    chain.append(current)
                    break
                seen.add(key)
                current = pool[key]
                continue
            chain.append(current)
            if not isinstance(current, Mapping):
                break
            mapped = current.get("task", current.get("prompt", ""))
            key = str(mapped or "").strip()
            if not key or key not in pool or key in seen or pool[key] is current:
                break
            seen.add(key)
            current = pool[key]
        return tuple(chain)

    def _resolved_task_semantics(self, task: Any) -> Any:
        return [_stable_semantics(spec) for spec in self._task_resolution_chain(task)]

    def effective_task_semantics(self, task: Any) -> Mapping[str, Any]:
        return {"requested_task": _stable_semantics(task),
                "effective_task_spec": self._resolved_task_semantics(task),
                "effective_input_cut_len": self.effective_input_cut_len(task)}

    def effective_input_cut_len(self, task: Any) -> int | None:
        for spec in self._task_resolution_chain(task):
            if isinstance(spec, Mapping) and type(spec.get("InputCutLen")) is int:
                return spec["InputCutLen"]
        if isinstance(getattr(self.ctx, "taskSetting", None), Mapping):
            return 3000
        return 3000

    def render_task_prompt(self, task: Any, content: str) -> str:
        if not isinstance(content, str):
            raise TypeError("production task runtime requires text content")
        renderer = self._renderer
        if renderer is None:
            from czjLLM.prompt_pipeline.pipeline_controller import render_stage_task_prompt
            renderer = render_stage_task_prompt
        prompt = renderer(task, content, self.ctx)
        if not isinstance(prompt, str) or not prompt.strip():
            raise RuntimeError("task prompt rendering returned blank text")
        return prompt

    def _tokenize(self, *, task: Any, text: str) -> tuple[str, ...]:
        tokenizer_factory = self._tokenizer_factory
        if tokenizer_factory is None:
            from czjLLM.tokenizer_utils import TokenizerWrapper
            tokenizer_factory = TokenizerWrapper
        tokenizer = tokenizer_factory(
            model_name=self.ctx.model_spec_name, task=_tokenizer_task(task),
            max_tokens=self.ctx.max_tokens,
        )
        tokenizer.max_input_tokens = self.effective_input_cut_len(task)
        chunks = tokenizer.tokenize(
            text=text, adjust=True, max_tokens=self.ctx.max_tokens, quiet=True
        )["ctxCut"]
        if not isinstance(chunks, (list, tuple)) or any(
                not isinstance(chunk, str) for chunk in chunks):
            raise RuntimeError("task tokenizer returned invalid chunks")
        return tuple(chunks)

    def preflight_task_content(self, *, task: Any, content: str) -> TaskPromptPreflight:
        """Render and tokenize exactly as execute() does, without LLM work or a lease."""
        prompt = self.render_task_prompt(task, content)
        chunks = self._tokenize(task=task, text=prompt)
        return TaskPromptPreflight(
            fits_one_chunk=len(chunks) == 1 and chunks[0] == prompt,
            rendered_prompt=prompt,
            chunk_count=len(chunks),
        )

    def prepare_content_chunks(self, *, task: Any, content: str) -> tuple[str, ...]:
        """Split source content until every exact rendered prompt passes preflight."""
        if not isinstance(content, str):
            raise TypeError("production content preparation requires text content")
        if not content.strip():
            raise RuntimeError("production content preparation requires nonblank text")
        if not self.preflight_task_content(task=task, content="").fits_one_chunk:
            raise RuntimeError("task prompt overhead exceeds configured one-chunk limit")

        initial = self._tokenize(task=task, text=content)
        # A tokenizer used for source preparation must be lossless. Fall back to
        # refining the complete source rather than accepting a lossy boundary.
        pending = list(initial) if initial and "".join(initial) == content and all(
            chunk.strip() for chunk in initial
        ) else [content]
        accepted: list[str] = []
        while pending:
            candidate = pending.pop(0)
            if self.preflight_task_content(task=task, content=candidate).fits_one_chunk:
                accepted.append(candidate)
                continue
            split_at = _strict_source_split(candidate)
            if split_at is None:
                raise RuntimeError(
                    "smallest usable source fragment exceeds configured one-chunk limit"
                )
            left, right = candidate[:split_at], candidate[split_at:]
            pending[0:0] = [left, right]
        if not accepted or "".join(accepted) != content or any(not chunk.strip() for chunk in accepted):
            raise RuntimeError("prompt-aware content preparation did not preserve source content")
        return tuple(accepted)

    def execute(self, *, task: Any, content: str) -> TaskCallResult:
        preflight = self.preflight_task_content(task=task, content=content)
        prompt = preflight.rendered_prompt
        if not preflight.fits_one_chunk:
            raise RuntimeError("final task prompt exceeds one configured token chunk")
        task_key = _tokenizer_task(task)
        pipeline_factory = self._pipeline_factory
        if pipeline_factory is None:
            from czjLLM.prompt_pipeline.pipeline_controller import PromptAPIPipeline
            pipeline_factory = PromptAPIPipeline
        pipeline = pipeline_factory(
            task=task_key, content=prompt, OutputSaveFN="", allow_to_retry=False,
            max_tokens=self.ctx.max_tokens, model_spec=self.ctx.model_spec,
            include_think=False, PGMSubDir=getattr(self.ctx, "PGMSubDir", ""),
            audit_run_id=getattr(self.ctx, "llm_call_audit_run_id", ""),
            audit_path=getattr(self.ctx, "llm_call_audit_path", ""),
        )
        lease_factory = self._lease_factory
        if lease_factory is None:
            from czjLLM.prompt_pipeline.dispatch_parallelism import lease_execution_workers
            lease_factory = lease_execution_workers
        with lease_factory(self.ctx, 1):
            response = pipeline.proc()
        if not isinstance(response, dict) or not response.get("ok"):
            detail = response.get("error", "invalid runtime result") if isinstance(response, dict) else "invalid runtime result"
            raise RuntimeError(f"task LLM execution failed: {detail}")
        output = response.get("output")
        model_spec = getattr(pipeline, "model_spec", {})
        return TaskCallResult(output=output, ok=True,
                              model_name=str(model_spec.get("model_name", "")),
                              cost_twd=float(response.get("cost", 0) or 0))

    def fingerprint_metadata(self) -> Mapping[str, Any]:
        spec = getattr(self.ctx, "model_spec", {})
        safe_model = ({key: _stable_semantics(spec[key]) for key in sorted(spec)
                       if key in _MODEL_SEMANTIC_KEYS} if isinstance(spec, Mapping) else {})
        return {"runtime_contract_version": TASK_RUNTIME_CONTRACT_VERSION,
                "prompt_renderer_contract_version": PROMPT_RENDERER_CONTRACT_VERSION,
                "tokenizer_contract_version": TOKENIZER_CONTRACT_VERSION,
                "model_spec_name": str(getattr(self.ctx, "model_spec_name", "") or ""),
                "model": safe_model,
                "max_tokens": getattr(self.ctx, "max_tokens", None),
                "think_mode": bool(getattr(self.ctx, "think_mode", True)),
                "include_think": False,
                "mock_llm_mode": bool(getattr(self.ctx, "mock_llm_mode", False) or
                                      (isinstance(spec, Mapping) and spec.get("mock_llm_mode", False)))}


def _strict_source_split(content: str) -> int | None:
    """Choose a deterministic split with two shorter, nonblank source fragments."""
    if len(content) < 2:
        return None
    midpoint = len(content) // 2
    indexes = sorted(range(1, len(content)), key=lambda index: (abs(index - midpoint), index))
    for index in indexes:
        if content[:index].strip() and content[index:].strip():
            return index
    return None


def _tokenizer_task(task: Any) -> str:
    if isinstance(task, Mapping):
        value = task.get("task", task.get("prompt", "reduction_task"))
    else:
        value = task
    return str(value or "reduction_task").strip() or "reduction_task"
