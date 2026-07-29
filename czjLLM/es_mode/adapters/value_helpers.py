"""Pure value traversal and validation helpers for Elasticsearch documents."""

import re
from datetime import datetime
from typing import Any, List


def extract_by_path(src: dict, path: str):
    """Return a dotted-path value, or ``None`` when traversal fails."""
    try:
        cur = src
        for key in path.split("."):
            if cur is None:
                return None
            cur = cur.get(key)
        return cur
    except Exception:
        return None


def deep_collect_by_path(cur: Any, path: str) -> List[Any]:
    """Collect all values matching a dotted path through dictionaries/lists."""
    parts = path.split(".") if isinstance(path, str) else list(path)

    def walk(node: Any, index: int) -> List[Any]:
        if index >= len(parts):
            return [node]
        if isinstance(node, list):
            values = []
            for item in node:
                values.extend(walk(item, index))
            return values
        if isinstance(node, dict):
            key = parts[index]
            if key not in node:
                return []
            return walk(node.get(key), index + 1)
        return []

    return walk(cur, 0)


def flatten_list(values: List[Any]) -> List[Any]:
    """Recursively flatten nested lists."""
    flattened = []
    for value in values:
        if isinstance(value, list):
            flattened.extend(flatten_list(value))
        else:
            flattened.append(value)
    return flattened


def is_valid_date_string(value: Any, fmt: str = "yyyy-MM-dd") -> bool:
    if value is None:
        return False
    if isinstance(value, (list, tuple)):
        if not value:
            return False
        value = value[0]
    text = str(value).strip()
    if not text:
        return False
    if fmt == "yyyy-MM-dd":
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
            return False
        try:
            datetime.strptime(text, "%Y-%m-%d")
        except Exception:
            return False
        return True
    if fmt in ("iso8601", "strict_date_optional_time"):
        try:
            datetime.fromisoformat(text.replace("Z", "+00:00"))
        except Exception:
            return False
        return True
    return True


def is_non_empty_deep(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple)):
        return any(is_non_empty_deep(item) for item in value)
    if isinstance(value, dict):
        return any(is_non_empty_deep(item) for item in value.values())
    return True


def normalize_scalar(value: Any):
    """Normalize a scalar identifier to text, taking the first list value."""
    if isinstance(value, (list, tuple)):
        value = value[0] if value else None
    return None if value is None else str(value)
