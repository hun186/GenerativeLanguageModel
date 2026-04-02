from __future__ import annotations

from typing import Dict

from ..pipeline_utils import make_stage_result


def run_chunk_summary(context) -> Dict:
    summaries = []
    for idx, chunk in enumerate(context.chunks):
        snippet = chunk[:240].replace("\n", " ").strip()
        summaries.append(
            {
                "chunk_index": idx,
                "summary": snippet,
                "rough_role": "unknown",
            }
        )

    context.chunk_summaries = summaries
    return make_stage_result(
        stage_name="chunk_summary",
        success=True,
        data={"chunk_summaries": summaries},
        debug={"chunk_count": len(context.chunks)},
    )
