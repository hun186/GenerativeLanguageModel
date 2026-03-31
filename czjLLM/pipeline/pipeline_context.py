from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class PipelineContext:
    raw_text: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    chunks: List[str] = field(default_factory=list)
    chunk_summaries: List[Dict[str, Any]] = field(default_factory=list)
    doc_type_result: Optional[Dict[str, Any]] = None
    extraction_results: List[Dict[str, Any]] = field(default_factory=list)
    merged_result: Optional[Dict[str, Any]] = None
