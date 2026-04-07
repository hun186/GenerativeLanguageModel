from __future__ import annotations

from typing import Any, Dict

from .pipeline_config import PIPELINE_CONFIG
from .pipeline_context import PipelineContext
from .pipeline_utils import split_text_to_chunks
from .steps.chunk_summary import run_chunk_summary
from .steps.doc_type_classification import run_doc_type_classification
from .steps.extraction_multidim import run_extraction_multidim
from .steps.merge_multidim import run_merge_multidim


STEP_RUNNERS = {
    "chunk_summary": run_chunk_summary,
    "doc_type_classification": run_doc_type_classification,
    "extraction_multidim": run_extraction_multidim,
    "merge_multidim": run_merge_multidim,
}


def run_pipeline(pipeline_name: str, text: str, metadata: Dict[str, Any] | None = None) -> Dict[str, Any]:
    if pipeline_name not in PIPELINE_CONFIG:
        raise ValueError(f"Unknown pipeline: {pipeline_name}")

    context = PipelineContext(raw_text=text, metadata=metadata or {})
    context.chunks = split_text_to_chunks(text)

    for step_name in PIPELINE_CONFIG[pipeline_name]:
        runner = STEP_RUNNERS[step_name]
        result = runner(context)
        if not result.get("success", False):
            raise RuntimeError(f"Pipeline step failed: {step_name} | {result.get('errors', [])}")

    return context.merged_result or {}
