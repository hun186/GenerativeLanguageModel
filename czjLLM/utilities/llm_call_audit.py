# -*- coding: utf-8 -*-
"""Append-only audit log for every LLM call in one czjLLM run."""

from __future__ import annotations

import csv
import json
import os
import threading
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse, urlunparse
from urllib.request import Request, urlopen
from xml.sax.saxutils import escape

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
    "task_text_tokens",
    "template_tokens",
    "rendered_prompt_tokens",
    "prompt_component_token_source",
    "token_usage_source",
    "cached_input_tokens",
    "cached_input_token_source",
    "stage_identity",
    "context_limit_tokens",
    "context_limit_source",
    "context_usage_ratio",
    "context_exhausted",
    "context_remaining_tokens",
    "max_output_tokens",
    "effective_output_token_budget",
    "max_tokens",
    "elapsed_seconds",
    "processing_tps",
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
    xlsx_path = root / f"llm_call_audit_{run_id}.xlsx"
    _ensure_header(csv_path)
    _write_xlsx_from_csv(csv_path, xlsx_path)
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
    latest_xlsx = root / "latest_llm_call_audit.xlsx"
    try:
        if latest_xlsx.exists() or latest_xlsx.is_symlink():
            latest_xlsx.unlink()
        latest_xlsx.symlink_to(xlsx_path.name)
    except Exception:
        try:
            latest_xlsx.write_text(str(xlsx_path), encoding="utf-8")
        except Exception:
            pass
    print(f"[llm-audit] 本次 LLM 呼叫記錄總表: {csv_path}")
    print(f"[llm-audit] 本次 LLM 呼叫 Excel 總表: {xlsx_path}")
    return {
        "llm_call_audit_run_id": run_id,
        "llm_call_audit_path": str(csv_path),
        "llm_call_audit_xlsx_path": str(xlsx_path),
    }


_PROMPT_TOKEN_META_SUFFIX = ".audit_tokens.json"


def prompt_token_metadata_path(prompt_file: str) -> Path:
    """Return metadata outside TODO/RUNNING so queue claiming never sees it."""
    path = Path(str(prompt_file or ""))
    if path.parent.name in {"TODO", "RUNNING", "Success"}:
        audit_dir = path.parent.parent / ".llm_audit_tokens"
        return audit_dir / f"{path.name}{_PROMPT_TOKEN_META_SUFFIX}"
    return Path(str(prompt_file or "") + _PROMPT_TOKEN_META_SUFFIX)


def clear_prompt_token_metadata(prompt_file: str) -> None:
    """Remove stale numeric prompt-component metadata for a prompt basename."""
    if not prompt_file:
        return
    try:
        prompt_token_metadata_path(prompt_file).unlink()
    except FileNotFoundError:
        pass
    except OSError:
        pass


def write_prompt_token_metadata(
    prompt_file: str,
    *,
    task_text_tokens: int,
    template_tokens: int,
    rendered_prompt_tokens: int,
    source: str = "local_tokenizer_no_special_tokens",
    stage_identity: str = "",
) -> None:
    """Persist numeric-only prompt component metadata next to a TODO prompt."""
    if not prompt_file:
        return
    path = prompt_token_metadata_path(prompt_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "task_text_tokens": max(0, int(task_text_tokens or 0)),
        "template_tokens": max(0, int(template_tokens or 0)),
        "rendered_prompt_tokens": max(0, int(rendered_prompt_tokens or 0)),
        "prompt_component_token_source": str(source or ""),
        "stage_identity": str(stage_identity or ""),
    }
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as fp:
        json.dump(payload, fp, ensure_ascii=False, sort_keys=True)
        fp.flush()
        os.fsync(fp.fileno())
    os.replace(tmp, path)


def read_prompt_token_metadata(prompt_file: str) -> dict[str, Any]:
    """Read numeric-only prompt component metadata; missing/invalid stays unknown."""
    if not prompt_file:
        return {}
    path = prompt_token_metadata_path(prompt_file)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return {}
    if not isinstance(raw, Mapping):
        return {}
    out: dict[str, Any] = {}
    for key in ("task_text_tokens", "template_tokens", "rendered_prompt_tokens"):
        value = raw.get(key)
        try:
            parsed = int(value)
        except Exception:
            continue
        if parsed >= 0:
            out[key] = parsed
    source = raw.get("prompt_component_token_source")
    if isinstance(source, str) and source:
        out["prompt_component_token_source"] = source
    stage = raw.get("stage_identity")
    if isinstance(stage, str) and stage:
        out["stage_identity"] = stage
    return out


def _provider_cached_input_tokens(usage: Any) -> tuple[int | None, str]:
    """Read explicit provider-reported cache usage; a reported zero is valid."""
    if usage is None:
        return None, ""

    def field(obj, key):
        return obj.get(key) if isinstance(obj, Mapping) else getattr(obj, key, None)

    for obj, key in (
        (usage, "prompt_cache_hit_tokens"),
        (field(usage, "prompt_tokens_details"), "cached_tokens"),
        (field(usage, "input_tokens_details"), "cached_tokens"),
    ):
        raw = field(obj, key) if obj is not None else None
        if raw is None or isinstance(raw, bool):
            continue
        try:
            count = int(raw)
        except (ValueError, TypeError, OverflowError):
            continue
        if count >= 0:
            return count, "provider_usage"
    return None, ""


def relabel_prompt_token_stage(prompt_file: str, stage_identity: str) -> bool:
    """Retag an unchanged staged prompt, preserving only existing numeric counts.

    An original first-stage TODO prompt is copied without re-rendering; its
    previously counted tokens remain valid, but its stage label must change.
    Never create synthetic component counts if the original sidecar is absent.
    """
    metadata = read_prompt_token_metadata(prompt_file)
    keys = ("task_text_tokens", "template_tokens", "rendered_prompt_tokens")
    if not stage_identity or not all(key in metadata for key in keys):
        return False
    write_prompt_token_metadata(
        prompt_file,
        task_text_tokens=metadata["task_text_tokens"],
        template_tokens=metadata["template_tokens"],
        rendered_prompt_tokens=metadata["rendered_prompt_tokens"],
        source=metadata.get("prompt_component_token_source", ""),
        stage_identity=stage_identity,
    )
    return True


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
    elapsed_seconds: float | None = None,
    processing_tps: float | None = None,
    task_text_tokens: int | None = None,
    template_tokens: int | None = None,
    rendered_prompt_tokens: int | None = None,
    prompt_component_token_source: str = "",
    stage_identity: str = "",
) -> None:
    """Append one LLM call row. Missing usage/context fields are recorded as 0/blank."""
    if not audit_path:
        return
    spec = dict(model_spec or {})
    model = str(spec.get("model_name") or spec.get("model") or "")
    usage = getattr(response, "usage", None)
    token_usage_source = "llm_api_usage" if usage else "unavailable"
    input_tokens = _int_attr(usage, "prompt_tokens")
    output_tokens = _int_attr(usage, "completion_tokens")
    total_tokens = _int_attr(usage, "total_tokens") or input_tokens + output_tokens
    cached_input_tokens, cached_source = _provider_cached_input_tokens(usage)
    context_limit, context_source = resolve_context_limit(spec, response=response)
    ratio = (float(total_tokens) / float(context_limit)) if context_limit > 0 else 0.0
    context_exhausted = bool(context_limit > 0 and total_tokens >= context_limit)
    max_output_tokens = int(max_tokens or 0)
    context_remaining = max(context_limit - total_tokens, 0) if context_limit > 0 else 0
    effective_output_budget = (
        min(max_output_tokens, context_remaining)
        if max_output_tokens > 0 and context_limit > 0
        else max_output_tokens
    )
    elapsed_value = _float_or_attr(response, "_czjllm_elapsed_seconds", elapsed_seconds)
    tps_value = _float_or_attr(response, "_czjllm_processing_tps", processing_tps)
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
        "task_text_tokens": "" if task_text_tokens is None else max(0, int(task_text_tokens)),
        "template_tokens": "" if template_tokens is None else max(0, int(template_tokens)),
        "rendered_prompt_tokens": "" if rendered_prompt_tokens is None else max(0, int(rendered_prompt_tokens)),
        "prompt_component_token_source": str(prompt_component_token_source or ""),
        "token_usage_source": token_usage_source,
        "cached_input_tokens": "" if cached_input_tokens is None else cached_input_tokens,
        "cached_input_token_source": cached_source,
        "stage_identity": str(stage_identity or ""),
        "context_limit_tokens": context_limit,
        "context_limit_source": context_source,
        "context_usage_ratio": f"{ratio:.6f}" if context_limit > 0 else "",
        "context_exhausted": "YES" if context_exhausted else "NO",
        "context_remaining_tokens": context_remaining,
        "max_output_tokens": max_output_tokens,
        "effective_output_token_budget": effective_output_budget,
        "max_tokens": max_output_tokens,
        "elapsed_seconds": f"{elapsed_value:.2f}" if elapsed_value > 0 else "",
        "processing_tps": f"{tps_value:.2f}" if tps_value > 0 else "",
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
        _write_xlsx_from_csv(path, path.with_suffix(".xlsx"))


def resolve_context_limit(
    model_spec: Mapping[str, Any] | None,
    *,
    response: Any = None,
) -> tuple[int, str]:
    """Resolve context limit without guessing from model names.

    Priority:
    1. OpenAI-compatible response extensions, if a server returns one.
    2. Ollama native `/api/ps` metadata for the currently loaded model.
    3. Explicit local model configuration (`num_ctx`, `context_window`, ...).

    The OpenAI chat completion usage block normally reports token counts only, not
    the active model context window. Ollama `/api/show` exposes model capability,
    not necessarily the runtime CONTEXT shown by `ollama ps`, so it is not used
    for context-usage percentages. When the active limit cannot be resolved, the
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


def _write_xlsx_from_csv(csv_path: Path, xlsx_path: Path) -> None:
    rows = _read_csv_rows(csv_path)
    tmp_path = xlsx_path.with_suffix(xlsx_path.suffix + ".tmp")
    with zipfile.ZipFile(tmp_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", _xlsx_content_types_xml())
        zf.writestr("_rels/.rels", _xlsx_root_rels_xml())
        zf.writestr("xl/workbook.xml", _xlsx_workbook_xml())
        zf.writestr("xl/_rels/workbook.xml.rels", _xlsx_workbook_rels_xml())
        zf.writestr("xl/styles.xml", _xlsx_styles_xml())
        zf.writestr("xl/worksheets/sheet1.xml", _xlsx_sheet_xml(rows))
    os.replace(tmp_path, xlsx_path)


def _read_csv_rows(csv_path: Path) -> list[list[str]]:
    if not csv_path.exists():
        return [_FIELDS]
    with csv_path.open("r", newline="", encoding="utf-8") as fp:
        return [[str(cell or "") for cell in row] for row in csv.reader(fp)]


def _xlsx_sheet_xml(rows: list[list[str]]) -> str:
    sheet_rows = []
    for row_idx, row in enumerate(rows, start=1):
        cells = []
        for col_idx, value in enumerate(row, start=1):
            ref = f"{_xlsx_col_name(col_idx)}{row_idx}"
            cells.append(
                f'<c r="{ref}" t="inlineStr"><is><t>{escape(value)}</t></is></c>'
            )
        sheet_rows.append(f'<row r="{row_idx}">{"".join(cells)}</row>')
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<sheetData>' + "".join(sheet_rows) + '</sheetData>'
        '</worksheet>'
    )


def _xlsx_col_name(col_idx: int) -> str:
    name = ""
    while col_idx:
        col_idx, rem = divmod(col_idx - 1, 26)
        name = chr(65 + rem) + name
    return name


def _xlsx_content_types_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
        '</Types>'
    )


def _xlsx_root_rels_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
        '</Relationships>'
    )


def _xlsx_workbook_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheets><sheet name="llm_call_audit" sheetId="1" r:id="rId1"/></sheets>'
        '</workbook>'
    )


def _xlsx_workbook_rels_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
        '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
        '</Relationships>'
    )


def _xlsx_styles_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<fonts count="1"><font><sz val="11"/><name val="Calibri"/></font></fonts>'
        '<fills count="1"><fill><patternFill patternType="none"/></fill></fills>'
        '<borders count="1"><border/></borders>'
        '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
        '<cellXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/></cellXfs>'
        '</styleSheet>'
    )


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


def _float_or_attr(obj: Any, name: str, fallback: float | None = None) -> float:
    try:
        value = getattr(obj, name, None) if obj is not None else None
        if value is None:
            value = fallback
        return float(value or 0.0)
    except Exception:
        return 0.0


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
    ps_url = _ollama_api_url(base_url, "/api/ps")
    if not ps_url:
        _CONTEXT_CACHE[cache_key] = (0, "unknown")
        return _CONTEXT_CACHE[cache_key]
    req = Request(ps_url, method="GET")
    try:
        with urlopen(req, timeout=2.0) as resp:
            data = json.loads(resp.read().decode("utf-8") or "{}")
    except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError, ValueError):
        _CONTEXT_CACHE[cache_key] = (0, "unknown")
        return _CONTEXT_CACHE[cache_key]
    value = _context_from_ollama_ps(data, model=model)
    _CONTEXT_CACHE[cache_key] = (value, "ollama_api_ps" if value > 0 else "unknown")
    return _CONTEXT_CACHE[cache_key]


def _ollama_api_url(base_url: str, api_path: str) -> str:
    parsed = urlparse(str(base_url or "").rstrip("/"))
    if not parsed.scheme or not parsed.netloc:
        return ""
    path = parsed.path.rstrip("/")
    if path.endswith("/v1"):
        path = path[:-3]
    api_path = "/" + str(api_path or "").strip("/")
    full_path = f"{path}{api_path}" if path else api_path
    return urlunparse((parsed.scheme, parsed.netloc, full_path, "", "", ""))


def _context_from_ollama_ps(data: Mapping[str, Any], *, model: str) -> int:
    models = data.get("models") if isinstance(data, Mapping) else None
    if not isinstance(models, list):
        return 0
    wanted = _normalize_model_name(model)
    fallback = 0
    matched_count = 0
    for entry in models:
        if not isinstance(entry, Mapping):
            continue
        value = _context_from_nested_values(entry)
        if value <= 0:
            continue
        names = {
            _normalize_model_name(entry.get("name")),
            _normalize_model_name(entry.get("model")),
            _normalize_model_name(entry.get("digest")),
        }
        if wanted and wanted in names:
            return value
        matched_count += 1
        if fallback <= 0:
            fallback = value
    return fallback if matched_count == 1 else 0


def _normalize_model_name(value: Any) -> str:
    return str(value or "").strip().lower()


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
