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


def loads_json_flexible_deep(raw: Any, max_depth: int = 3) -> Any:
    """
    深層容錯 JSON 解析：
    - 先做 loads_json_flexible
    - 若結果仍是「看起來像 JSON 的字串」，再遞迴解析（最多 max_depth 層）
    用於處理模型回傳「JSON 字串包 JSON」的情境。
    """
    val = raw
    for _ in range(max(1, int(max_depth))):
        parsed = loads_json_flexible(val)
        if not isinstance(parsed, str):
            return parsed
        text = parsed.strip()
        if not text:
            return parsed
        # 只在看起來像 JSON 或 fenced JSON 時繼續嘗試，避免誤解析一般文字
        is_fenced = bool(_FENCED_JSON_RE.match(text))
        looks_json = text[:1] in "{[\""
        if not (is_fenced or looks_json):
            return parsed
        val = parsed
    return val
