# -*- coding: utf-8 -*-
"""Append-only audit log for every LLM call in one czjLLM run."""

from __future__ import annotations

import csv
import json
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse, urlunparse
from urllib.request import Request, urlopen

_LOCK = threading.Lock()
_CONTEXT_CACHE: dict[tuple[str, str], tuple[int, str]] = {}
_FIELDS = [
    "timestamp",
    "run_id",
    "task",
    "prompt_file",
    "model",
    "base_url",
    "input_tokens",
    "output_tokens",
    "total_tokens",
    "context_limit_tokens",
    "context_limit_source",
    "context_usage_ratio",
    "context_exhausted",
    "max_tokens",
    "cost_twd",
    "ok",
    "error",
]


def create_llm_call_audit_run(PGMSubDir: str = "") -> dict[str, str]:
    """Create per-process run metadata and return fields stored on ctx."""
    now = datetime.now()
    run_id = f"{now.strftime('%Y%m%d-%H%M%S')}-{os.getpid()}"
    root = Path(PGMSubDir or ".") / "logs" / "llm_call_audit"
    root.mkdir(parents=True, exist_ok=True)
    csv_path = root / f"llm_call_audit_{run_id}.csv"
    _ensure_header(csv_path)
    latest = root / "latest_llm_call_audit.csv"
    try:
        if latest.exists() or latest.is_symlink():
            latest.unlink()
        latest.symlink_to(csv_path.name)
    except Exception:
        try:
            latest.write_text(str(csv_path), encoding="utf-8")
        except Exception:
            pass
    print(f"[llm-audit] 本次 LLM 呼叫記錄總表: {csv_path}")
    return {"llm_call_audit_run_id": run_id, "llm_call_audit_path": str(csv_path)}


def log_llm_call(
    *,
    audit_path: str | None,
    run_id: str | None,
    task: str = "",
    prompt_file: str = "",
    model_spec: Mapping[str, Any] | None = None,
    response: Any = None,
    max_tokens: int | None = None,
    cost_twd: float = 0.0,
    ok: bool = True,
    error: str = "",
) -> None:
    """Append one LLM call row. Missing usage/context fields are recorded as 0/blank."""
    if not audit_path:
        return
    spec = dict(model_spec or {})
    model = str(spec.get("model_name") or spec.get("model") or "")
    usage = getattr(response, "usage", None)
    input_tokens = _int_attr(usage, "prompt_tokens")
    output_tokens = _int_attr(usage, "completion_tokens")
    total_tokens = _int_attr(usage, "total_tokens") or input_tokens + output_tokens
    context_limit, context_source = resolve_context_limit(spec, response=response)
    ratio = (float(total_tokens) / float(context_limit)) if context_limit > 0 else 0.0
    context_exhausted = bool(context_limit > 0 and total_tokens >= context_limit)
    row = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "run_id": run_id or "",
        "task": str(task or ""),
        "prompt_file": str(prompt_file or ""),
        "model": model,
        "base_url": str(spec.get("base_url") or ""),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "context_limit_tokens": context_limit,
        "context_limit_source": context_source,
        "context_usage_ratio": f"{ratio:.6f}" if context_limit > 0 else "",
        "context_exhausted": "YES" if context_exhausted else "NO",
        "max_tokens": int(max_tokens or 0),
        "cost_twd": f"{float(cost_twd or 0):.6f}",
        "ok": "YES" if ok else "NO",
        "error": str(error or ""),
    }
    path = Path(audit_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with _LOCK:
        _ensure_header(path)
        with path.open("a", newline="", encoding="utf-8") as fp:
            writer = csv.DictWriter(fp, fieldnames=_FIELDS)
            writer.writerow(row)


def resolve_context_limit(
    model_spec: Mapping[str, Any] | None,
    *,
    response: Any = None,
) -> tuple[int, str]:
    """Resolve context limit without guessing from model names.

    Priority:
    1. OpenAI-compatible response extensions, if a server returns one.
    2. Ollama native `/api/show` metadata for the selected endpoint/model.
    3. Explicit local model configuration (`num_ctx`, `context_window`, ...).

    The OpenAI chat completion usage block normally reports token counts only, not
    the model context window. When the endpoint cannot expose model metadata, the
    limit stays unknown instead of being inferred from the display name.
    """
    spec = dict(model_spec or {})
    value = _context_from_response(response)
    if value > 0:
        return value, "response"

    model = str(spec.get("model_name") or spec.get("model") or "")
    base_url = str(spec.get("base_url") or "")
    cached = _context_from_endpoint(base_url=base_url, model=model)
    if cached[0] > 0:
        return cached

    value = _context_from_model_spec(spec)
    if value > 0:
        return value, "model_spec"
    return 0, "unknown"


def _ensure_header(path: Path) -> None:
    if path.exists() and path.stat().st_size > 0:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fp:
        writer = csv.DictWriter(fp, fieldnames=_FIELDS)
        writer.writeheader()


def _int_attr(obj: Any, name: str) -> int:
    try:
        return int(getattr(obj, name, 0) or 0)
    except Exception:
        return 0


def _context_from_model_spec(spec: Mapping[str, Any]) -> int:
    for key in ("num_ctx", "context_window", "context_limit", "max_context_tokens", "max_context"):
        try:
            value = int(spec.get(key) or 0)
            if value > 0:
                return value
        except Exception:
            pass
    return 0


def _context_from_response(response: Any) -> int:
    if response is None:
        return 0
    candidates = [
        response,
        getattr(response, "model_info", None),
        getattr(response, "metadata", None),
        getattr(response, "usage", None),
    ]
    for obj in candidates:
        value = _context_from_mapping_or_object(obj)
        if value > 0:
            return value
    return 0


def _context_from_mapping_or_object(obj: Any) -> int:
    if obj is None:
        return 0
    keys = ("num_ctx", "context_window", "context_length", "max_context_tokens", "max_context")
    if isinstance(obj, Mapping):
        for key in keys:
            value = _safe_int(obj.get(key))
            if value > 0:
                return value
        return 0
    for key in keys:
        value = _safe_int(getattr(obj, key, 0))
        if value > 0:
            return value
    return 0


def _context_from_endpoint(*, base_url: str, model: str) -> tuple[int, str]:
    if not base_url or not model:
        return 0, "unknown"
    cache_key = (base_url.rstrip("/"), model)
    if cache_key in _CONTEXT_CACHE:
        return _CONTEXT_CACHE[cache_key]
    show_url = _ollama_show_url(base_url)
    if not show_url:
        _CONTEXT_CACHE[cache_key] = (0, "unknown")
        return _CONTEXT_CACHE[cache_key]
    payload = json.dumps({"model": model}).encode("utf-8")
    req = Request(show_url, data=payload, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urlopen(req, timeout=2.0) as resp:
            data = json.loads(resp.read().decode("utf-8") or "{}")
    except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError, ValueError):
        _CONTEXT_CACHE[cache_key] = (0, "unknown")
        return _CONTEXT_CACHE[cache_key]
    value = _context_from_ollama_show(data)
    _CONTEXT_CACHE[cache_key] = (value, "ollama_api_show" if value > 0 else "unknown")
    return _CONTEXT_CACHE[cache_key]


def _ollama_show_url(base_url: str) -> str:
    parsed = urlparse(str(base_url or "").rstrip("/"))
    if not parsed.scheme or not parsed.netloc:
        return ""
    path = parsed.path.rstrip("/")
    if path.endswith("/v1"):
        path = path[:-3]
    show_path = f"{path}/api/show" if path else "/api/show"
    return urlunparse((parsed.scheme, parsed.netloc, show_path, "", "", ""))


def _context_from_ollama_show(data: Mapping[str, Any]) -> int:
    for section_name in ("model_info", "details", "parameters", "options"):
        section = data.get(section_name)
        value = _context_from_nested_values(section)
        if value > 0:
            return value
    return _context_from_nested_values(data)


def _context_from_nested_values(obj: Any) -> int:
    direct = _context_from_mapping_or_object(obj)
    if direct > 0:
        return direct
    if isinstance(obj, Mapping):
        for key, value in obj.items():
            key_l = str(key).lower()
            if key_l.endswith("context_length") or key_l.endswith(".context_length"):
                parsed = _safe_int(value)
                if parsed > 0:
                    return parsed
            if key_l in {"num_ctx", "context_window", "context_length", "max_context_tokens", "max_context"}:
                parsed = _safe_int(value)
                if parsed > 0:
                    return parsed
            nested = _context_from_nested_values(value)
            if nested > 0:
                return nested
    if isinstance(obj, list):
        for value in obj:
            nested = _context_from_nested_values(value)
            if nested > 0:
                return nested
    return 0


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except Exception:
        return 0
