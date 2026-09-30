"""Production bridge from semantic reduction to the existing LLM stack."""

from __future__ import annotations

from typing import Any, Callable, Optional

from czjLLM.reduction.reducers.semantic import SemanticCallResult, SemanticReducerError


class SemanticRuntimeError(SemanticReducerError):
    """The production semantic call failed or exceeded its one-call budget."""


class _SemanticContextView:
    def __init__(self, base: Any, task: str) -> None:
        self._base = base
        self.task = task

    def __getattr__(self, name: str) -> Any:
        return getattr(self._base, name)


class SemanticLLMRuntimeAdapter:
    """Render, preflight and execute exactly one inherited-budget LLM call."""

    def __init__(self, *, ctx: Any, tokenizer_factory: Optional[Callable[..., Any]] = None,
                 prompt_generator_factory: Optional[Callable[..., Any]] = None,
                 pipeline_factory: Optional[Callable[..., Any]] = None,
                 lease_factory: Optional[Callable[..., Any]] = None) -> None:
        self.ctx = ctx
        self._tokenizer_factory = tokenizer_factory
        self._prompt_generator_factory = prompt_generator_factory
        self._pipeline_factory = pipeline_factory
        self._lease_factory = lease_factory

    def execute(self, *, task: str, content: str) -> SemanticCallResult:
        if not isinstance(task, str) or not task.strip():
            raise SemanticRuntimeError("semantic task must be non-blank")
        derived = _SemanticContextView(self.ctx, task)
        prompt_factory = self._prompt_generator_factory
        if prompt_factory is None:
            from czjLLM.prompt_pipeline.prompt_generator import PromptGenerator
            prompt_factory = PromptGenerator
        try:
            prompt = prompt_factory(derived).build(content)
        except Exception as exc:
            raise SemanticRuntimeError(f"semantic prompt rendering failed: {exc}") from exc

        tokenizer_factory = self._tokenizer_factory
        if tokenizer_factory is None:
            from czjLLM.tokenizer_utils import TokenizerWrapper
            tokenizer_factory = TokenizerWrapper
        try:
            tokenizer = tokenizer_factory(model_name=derived.model_spec_name, task=task,
                                          max_tokens=derived.max_tokens)
            chunks = tokenizer.tokenize(text=prompt, adjust=True, max_tokens=derived.max_tokens,
                                        quiet=True)["ctxCut"]
        except Exception as exc:
            raise SemanticRuntimeError(f"semantic token preflight failed: {exc}") from exc
        if len(chunks) != 1 or chunks[0] != prompt:
            raise SemanticRuntimeError(
                "semantic prompt exceeds one configured token chunk; apply deterministic "
                "pre-reduction or another higher-level reduction strategy"
            )

        pipeline_factory = self._pipeline_factory
        if pipeline_factory is None:
            from czjLLM.prompt_pipeline.pipeline_controller import PromptAPIPipeline
            pipeline_factory = PromptAPIPipeline
        lease_factory = self._lease_factory
        if lease_factory is None:
            from czjLLM.prompt_pipeline.dispatch_parallelism import lease_execution_workers
            lease_factory = lease_execution_workers
        pipeline = pipeline_factory(
            task=task, content=prompt, OutputSaveFN="", allow_to_retry=False,
            max_tokens=derived.max_tokens, model_spec=derived.model_spec,
            include_think=bool(getattr(derived, "think_mode", False)),
            PGMSubDir=getattr(derived, "PGMSubDir", ""),
            audit_run_id=getattr(derived, "llm_call_audit_run_id", ""),
            audit_path=getattr(derived, "llm_call_audit_path", ""),
        )
        try:
            with lease_factory(derived, 1):
                response = pipeline.proc()
        except Exception as exc:
            raise SemanticRuntimeError(f"semantic LLM execution failed: {exc}") from exc
        if not isinstance(response, dict) or not response.get("ok"):
            detail = response.get("error", "invalid runtime result") if isinstance(response, dict) else "invalid runtime result"
            raise SemanticRuntimeError(f"semantic LLM execution failed: {detail}")
        output = response.get("output")
        if not isinstance(output, str) or not output.strip():
            raise SemanticRuntimeError("semantic LLM returned empty output")
        model_spec = getattr(pipeline, "model_spec", {})
        model_name = model_spec.get("model_name", "") if isinstance(model_spec, dict) else ""
        return SemanticCallResult(output=output, cost_twd=float(response.get("cost", 0) or 0),
                                  model_name=str(model_name or ""))
