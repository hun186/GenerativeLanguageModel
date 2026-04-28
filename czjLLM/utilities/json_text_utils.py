import json
import re
from typing import Any


_FENCED_JSON_RE = re.compile(
    r"^\s*```(?:json)?\s*(.*?)\s*```\s*$",
    flags=re.IGNORECASE | re.DOTALL,
)


def strip_markdown_code_fence(raw: str) -> str:
    """
    去除常見 LLM 輸出的 markdown code fence（```json ... ``` / ``` ... ```）。
    若非完整 fence 包裹，回傳原字串（僅 strip 外層空白）。
    """
    text = str(raw or "").strip()
    if not text:
        return text
    m = _FENCED_JSON_RE.match(text)
    return m.group(1).strip() if m else text


def loads_json_flexible(raw: Any) -> Any:
    """
    容錯 JSON 解析：
    1) 直接 json.loads
    2) 失敗時，先去除 markdown code fence 再 json.loads
    """
    if not isinstance(raw, str):
        return raw
    try:
        return json.loads(raw)
    except Exception:
        cleaned = strip_markdown_code_fence(raw)
        if cleaned == raw:
            raise
        return json.loads(cleaned)
