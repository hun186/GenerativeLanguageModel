"""Production TaskRuntime adapter reusing the prompt-pipeline LLM stack."""

from __future__ import annotations

from typing import Any, Callable, Mapping

from czjLLM.reduction.execution import TaskCallResult, _stable_semantics


PROMPT_RENDERER_CONTRACT_VERSION = "stage-task-renderer-v1"
TASK_RUNTIME_CONTRACT_VERSION = "production-task-runtime-v2"
TOKENIZER_CONTRACT_VERSION = "tokenizer-wrapper-v1"
_MODEL_SEMANTIC_KEYS = frozenset({
    "model_name", "model", "model_version", "version", "temperature", "top_p",
    "top_k", "seed", "repeat_penalty", "frequency_penalty", "presence_penalty",
    "num_ctx", "context_window", "stop", "mock_llm_mode",
})


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

    def execute(self, *, task: Any, content: str) -> TaskCallResult:
        if not isinstance(content, str):
            raise TypeError("production task runtime requires text content")
        renderer = self._renderer
        if renderer is None:
            from czjLLM.prompt_pipeline.pipeline_controller import render_stage_task_prompt
            renderer = render_stage_task_prompt
        prompt = renderer(task, content, self.ctx)
        if not isinstance(prompt, str) or not prompt.strip():
            raise RuntimeError("task prompt rendering returned blank text")
        task_key = _tokenizer_task(task)
        tokenizer_factory = self._tokenizer_factory
        if tokenizer_factory is None:
            from czjLLM.tokenizer_utils import TokenizerWrapper
            tokenizer_factory = TokenizerWrapper
        tokenizer = tokenizer_factory(model_name=self.ctx.model_spec_name, task=task_key,
                                      max_tokens=self.ctx.max_tokens)
        input_cut_len = self.effective_input_cut_len(task)
        tokenizer.max_input_tokens = input_cut_len
        chunks = tokenizer.tokenize(text=prompt, adjust=True, max_tokens=self.ctx.max_tokens,
                                    quiet=True)["ctxCut"]
        if len(chunks) != 1 or chunks[0] != prompt:
            raise RuntimeError("final task prompt exceeds one configured token chunk")
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


def _tokenizer_task(task: Any) -> str:
    if isinstance(task, Mapping):
        value = task.get("task", task.get("prompt", "reduction_task"))
    else:
        value = task
    return str(value or "reduction_task").strip() or "reduction_task"
