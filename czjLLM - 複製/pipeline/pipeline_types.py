from typing import Any, Dict, List, TypedDict


class PipelineResult(TypedDict):
    stage_name: str
    success: bool
    data: Dict[str, Any]
    debug: Dict[str, Any]
    errors: List[str]
