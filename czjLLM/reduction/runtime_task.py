"""Production TaskRuntime adapter reusing the prompt-pipeline LLM stack."""

from __future__ import annotations

from typing import Any, Callable, Mapping

from czjLLM.reduction.execution import TaskCallResult


PROMPT_RENDERER_CONTRACT_VERSION = "stage-task-renderer-v1"


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
        if isinstance(task, Mapping) and type(task.get("InputCutLen")) is int:
            tokenizer.max_input_tokens = task["InputCutLen"]
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
        safe_keys = ("model_name", "temperature", "top_p", "seed", "frequency_penalty", "presence_penalty")
        return {"runtime_contract_version": "production-task-runtime-v1",
                "prompt_renderer_contract_version": PROMPT_RENDERER_CONTRACT_VERSION,
                "model": {key: spec[key] for key in safe_keys if isinstance(spec, Mapping) and key in spec},
                "max_tokens": getattr(self.ctx, "max_tokens", None),
                "think_mode": bool(getattr(self.ctx, "think_mode", True))}


def _tokenizer_task(task: Any) -> str:
    if isinstance(task, Mapping):
        value = task.get("task", task.get("prompt", "reduction_task"))
    else:
        value = task
    return str(value or "reduction_task").strip() or "reduction_task"
