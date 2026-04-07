from __future__ import annotations

from typing import Any, Dict, Iterable, List


def safe_update_context(obj: Any, field_name: str, value: Any) -> None:
    if not hasattr(obj, field_name):
        raise AttributeError(f"PipelineContext has no field: {field_name}")
    setattr(obj, field_name, value)


def split_text_to_chunks(raw_text: str, chunk_size: int = 2000) -> List[str]:
    if not raw_text:
        return []
    if chunk_size <= 0:
        raise ValueError("chunk_size must be > 0")
    return [raw_text[i:i + chunk_size] for i in range(0, len(raw_text), chunk_size)]


def build_doctype_input(
    article_title: str,
    raw_text: str,
    chunk_summaries: List[Dict[str, Any]],
    head_chars: int = 1200,
    tail_chars: int = 800,
) -> str:
    title_block = f"Title: {article_title}\n\n" if article_title else ""
    head_block = raw_text[:head_chars].strip()
    tail_block = raw_text[-tail_chars:].strip() if len(raw_text) > tail_chars else ""
    summary_lines = []
    for idx, item in enumerate(chunk_summaries):
        summary = item.get("summary", "")
        role = item.get("rough_role", "")
        summary_lines.append(f"[Chunk {idx}] role={role} summary={summary}")
    summary_block = "\n".join(summary_lines)

    return (
        f"{title_block}"
        f"=== HEAD ===\n{head_block}\n\n"
        f"=== TAIL ===\n{tail_block}\n\n"
        f"=== CHUNK SUMMARIES ===\n{summary_block}"
    )


def make_stage_result(
    stage_name: str,
    success: bool,
    data: Dict[str, Any] | None = None,
    debug: Dict[str, Any] | None = None,
    errors: Iterable[str] | None = None,
) -> Dict[str, Any]:
    return {
        "stage_name": stage_name,
        "success": success,
        "data": data or {},
        "debug": debug or {},
        "errors": list(errors or []),
    }
