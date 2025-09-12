import json
import pyodbc
import sqlite3
from czjLLM.czjLLM_utils import quote_column


def flatten_json_result(json_str: str, allowed_keys: set[str]) -> list[dict]:
    """
    將 JSON 字串轉為多欄格式，每筆為 dict，僅保留白名單中的欄位
    """
    try:
        data = json.loads(json_str)
        if isinstance(data, dict):
            data = [data]
        if not isinstance(data, list):
            raise ValueError("輸出格式錯誤，非陣列")

        filtered = []
        for row in data:
            if isinstance(row, dict):
                filtered.append({k: row[k] for k in row if k in allowed_keys})
        return filtered
    except Exception as e:
        raise ValueError(f"JSON 解析錯誤：{e}")