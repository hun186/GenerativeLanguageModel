import json
import re
from utilities.combine_utils import combine_json_return

class PromptResultHandler:
    def __init__(self, task, include_think=False):
        self.task = task
        self.include_think = include_think

    def clean_output(self, raw_text: str):
        if raw_text.replace(" ", "").replace("\n", "") == "<EMPTY>":
            return ""

        if not self.include_think:
            raw_text = re.sub(r'<think>.*?</think>', '', raw_text, flags=re.DOTALL)

        if "to json" in self.task.lower():
            raw_text = raw_text.replace("```json", "").replace("```", "").strip()

        return raw_text

    def validate_json(self, text: str):
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