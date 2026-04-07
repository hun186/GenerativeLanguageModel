# czjLLM/prompt_pipeline/result_handler.py
from __future__ import annotations
import json
from typing import Any, Dict
import re
from czjLLM.utilities.combine_utils import combine_json_return

class PromptResultHandler:
    def __init__(self, task: str, include_think: bool = False):
        self.task = task or ""
        self.include_think = include_think

    def clean_output(self, raw_text: str) -> str:
        if raw_text.replace(" ", "").replace("\n", "") == "<EMPTY>":
            return ""
        if not self.include_think:
            raw_text = re.sub(r"<think>.*?</think>", "", raw_text, flags=re.DOTALL)
        if "to json" in self.task.lower():
            raw_text = raw_text.replace("```json", "").replace("```", "").strip()
        return raw_text

    def validate_json(self, text: str) -> tuple[bool, str]:
        try:
            json.loads(text)
            return True, text
        except Exception:
            repaired, _ = combine_json_return(text)
            try:
                json.loads(repaired)
                return True, repaired
            except Exception:
                return False, ""

def parse_result(raw: Any, task: str = "", include_think: bool = False) -> Dict[str, Any]:
    """公共介面：把任意 raw 解析成 dict；解析不了就回 {"text": ...}。"""
    if isinstance(raw, dict):
        return raw
    h = PromptResultHandler(task=task, include_think=include_think)
    s = raw if isinstance(raw, str) else str(raw)
    s = h.clean_output(s).strip()
    ok, fixed = h.validate_json(s)
    if ok:
        return json.loads(fixed)
    return {"text": s}
