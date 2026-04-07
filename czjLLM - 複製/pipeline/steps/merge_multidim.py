from __future__ import annotations

from typing import Dict

from ..merge.merge_selector import get_merge_strategy
from ..pipeline_utils import make_stage_result


def run_merge_multidim(context) -> Dict:
    doc_type = (context.doc_type_result or {}).get("doc_type", "mixed")
    strategy = get_merge_strategy(doc_type)
    merged = strategy.merge(context.extraction_results, context)

    context.merged_result = merged
    return make_stage_result(
        stage_name="merge_multidim",
        success=True,
        data={"merged_result": merged},
        debug={"strategy": strategy.__class__.__name__},
    )
