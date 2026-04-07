from __future__ import annotations

from typing import Dict

from ..pipeline_utils import build_doctype_input, make_stage_result


def run_doc_type_classification(context) -> Dict:
    doctype_input = build_doctype_input(
        article_title=context.metadata.get("article_title", ""),
        raw_text=context.raw_text,
        chunk_summaries=context.chunk_summaries,
    )

    # TODO: Replace this heuristic with existing prompt_pipeline-based LLM execution.
    result = {
        "doc_type": "mixed",
        "doc_type_confidence": 0.25,
        "secondary_type": None,
        "has_primary_event": False,
        "routing_reason": "Skeleton placeholder classification.",
    }

    context.doc_type_result = result
    return make_stage_result(
        stage_name="doc_type_classification",
        success=True,
        data=result,
        debug={"doctype_input_preview": doctype_input[:500]},
    )
