from __future__ import annotations

from typing import Dict

from ..pipeline_utils import make_stage_result


def run_extraction_multidim(context) -> Dict:
    # TODO:
    # 1. Build type-aware prompt from context.doc_type_result
    # 2. Reuse existing prompt_pipeline execution flow
    # 3. Preserve current extraction schema / compatibility
    results = []
    for idx, chunk in enumerate(context.chunks):
        results.append(
            {
                "_chunk_meta": {
                    "chunk_index": idx,
                    "doc_type": (context.doc_type_result or {}).get("doc_type", "mixed"),
                },
                "raw_chunk_preview": chunk[:200],
            }
        )

    context.extraction_results = results
    return make_stage_result(
        stage_name="extraction_multidim",
        success=True,
        data={"extraction_results": results},
        debug={"result_count": len(results)},
    )
