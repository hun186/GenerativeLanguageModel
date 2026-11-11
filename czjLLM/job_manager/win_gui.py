# czjLLM/job_manager/win_gui.py
import csv
import math
from decimal import Decimal, ROUND_HALF_UP
import os
import sys
import multiprocessing as mp
import queue as pyqueue
import threading
from dataclasses import dataclass
from czjLLM.utilities.processing_quality import (
    QualityAccumulator, QualityCapacityExceeded,
)
from czjLLM.utilities.processing_quality_run_reader import QualityRunTailReader

# 僅 Windows 啟用 GUI；其他平台回傳 None
IS_WIN = (sys.platform == "win32")

@dataclass
class _GuiEvents:
    INC_SCHED: str = "inc_sched"
    INC_DONE:  str = "inc_done"
    LOG:       str = "log"
    CLOSE:     str = "close"
    SET_TOTAL: str = "set_total"
    RECHECK:   str = "recheck"
    REDUCTION: str = "reduction"
    AUDIT_PATH: str = "audit_path"
    QUALITY_PATH: str = "quality_path"
    RECOVERY_METER: str = "recovery_meter"



_AUDIT_SERIES = (
    ("input_tokens", "Input tokens", False),
    ("output_tokens", "Output tokens", False),
    ("template_tokens", "Template tokens", False),
    ("task_text_tokens", "Task text tokens", False),
    ("context_usage_ratio", "Context usage", True),
    ("elapsed_seconds", "Slice time", False),
    ("total_tok_per_s", "Total tok/s", False),
    ("effective_tok_per_s_est", "Effective tok/s (est.)", False),
)


_AUDIT_DISTRIBUTION_HELP = {
    "input_tokens": (
        "Input：每次 LLM request 由 API 回報的 prompt/input tokens，"
        "代表實際送進模型的輸入 token。"
    ),
    "output_tokens": (
        "Output：每次 LLM request 由 API 回報的 completion/output tokens，"
        "代表模型實際輸出的 token。"
    ),
    "template_tokens": (
        "Template：本地 tokenizer 估算的 finalized prompt tokens − task text tokens，"
        "代表模板、指令、格式與 runtime suffix 等額外負擔；不是 API 計費 usage。"
    ),
    "task_text_tokens": (
        "Task text：本地 tokenizer 估算的任務文本切片 token 數，不含模板。"
    ),
    "context_usage_ratio": (
        "Context %：(API input tokens + output tokens) ÷ context limit × 100%。"
        "越接近 100% 代表越逼近模型上下文上限。"
    ),
    "elapsed_seconds": (
        "Slice time（切片耗時）：有 prompt_file 的切片 LLM request，"
        "從真正送出 API 呼叫到取得模型回應的 elapsed_seconds。"
        "不包含等待 worker/queue、response 後處理、merge/reduction 或輸出寫檔時間；"
        "也不混入 JSON repair 等非切片 direct call。"
    ),
    "total_tok_per_s": (
        "Total tok/s：(API input tokens + output tokens) ÷ Slice time。"
        "這是 observed request-level throughput，不區分 KV-cache / prefix cache 重用。"
        "耗時包含網路、排程、TTFT 與生成；不是純 GPU kernel token/s。"
    ),
    "effective_tok_per_s_est": (
        "Effective tok/s (est.)：(估算未快取 input tokens + output tokens) ÷ Slice time。"
        "provider 回報 cached prompt/input tokens 時優先使用，包含明確的 0 hit。"
        "否則同 model、endpoint、task、YAML stage 的模板需至少兩筆先前近似穩定樣本，"
        "最多以模板 token 最小值的 50% 當作可能 cacheable proxy。"
        "heuristic / estimated 不是 API cache-hit 真值；動態欄位、runtime suffix、"
        "prefix、token boundary 和 provider policy 會影響準確度。"
        "這仍是 observed request-level throughput，不是純 GPU token/s。"
    ),
}


def format_audit_distribution_help(metric_key: str = "") -> str:
    """Human-readable explanation for the GUI distribution curves."""
    general = (
        "這是分布圖，不是時間序列。\n"
        "橫向：指標值由低到高（最多 24 個區間）；縱向：落在各區間的樣本數。"
        "曲線越高，表示該數值區間的樣本越集中。\n"
        "每張小圖的高度都以自己的峰值正規化，所以不能拿不同小圖的線高互相比大小。\n"
        "n = 有效樣本數；P50 = 中位數；P95 = 95% 樣本不超過此值；max = 最大值。"
        "Template 通常在同一 YAML stage 內固定或近固定，因此只在標題摘要顯示 P50/P95，不另外畫曲線。"
        "樣本很少時曲線形狀容易跳動，應優先看 P50 / P95 / max。"
    )
    detail = _AUDIT_DISTRIBUTION_HELP.get(str(metric_key or ""), "")
    return f"{detail}\n\n{general}" if detail else general


def _monitor_work_area_at(
    pointer_x: int,
    pointer_y: int,
    fallback_x: int,
    fallback_y: int,
    fallback_width: int,
    fallback_height: int,
) -> tuple[int, int, int, int]:
    """Return the Windows work area containing the pointer; fall back safely elsewhere."""
    fallback = (
        int(fallback_x),
        int(fallback_y),
        max(1, int(fallback_width)),
        max(1, int(fallback_height)),
    )
    if not IS_WIN:
        return fallback
    try:
        import ctypes
        from ctypes import wintypes

        class _POINT(ctypes.Structure):
            _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

        class _RECT(ctypes.Structure):
            _fields_ = [
                ("left", ctypes.c_long),
                ("top", ctypes.c_long),
                ("right", ctypes.c_long),
                ("bottom", ctypes.c_long),
            ]

        class _MONITORINFO(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.DWORD),
                ("rcMonitor", _RECT),
                ("rcWork", _RECT),
                ("dwFlags", wintypes.DWORD),
            ]

        user32 = ctypes.windll.user32
        user32.MonitorFromPoint.argtypes = [_POINT, wintypes.DWORD]
        user32.MonitorFromPoint.restype = ctypes.c_void_p
        user32.GetMonitorInfoW.argtypes = [ctypes.c_void_p, ctypes.POINTER(_MONITORINFO)]
        user32.GetMonitorInfoW.restype = wintypes.BOOL

        monitor = user32.MonitorFromPoint(
            _POINT(int(pointer_x), int(pointer_y)),
            2,  # MONITOR_DEFAULTTONEAREST
        )
        if not monitor:
            return fallback
        info = _MONITORINFO()
        info.cbSize = ctypes.sizeof(_MONITORINFO)
        if not user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
            return fallback
        work = info.rcWork
        width = max(1, int(work.right - work.left))
        height = max(1, int(work.bottom - work.top))
        return int(work.left), int(work.top), width, height
    except Exception:
        return fallback


def _tooltip_screen_position(
    pointer_x: int,
    pointer_y: int,
    tooltip_width: int,
    tooltip_height: int,
    screen_x: int,
    screen_y: int,
    screen_width: int,
    screen_height: int,
    *,
    gap_x: int = 14,
    gap_y: int = 16,
) -> tuple[int, int]:
    """Place a tooltip near the pointer while keeping it within virtual-screen bounds."""
    left = int(screen_x)
    top = int(screen_y)
    right = left + max(1, int(screen_width))
    bottom = top + max(1, int(screen_height))
    width = max(1, int(tooltip_width))
    height = max(1, int(tooltip_height))
    px = int(pointer_x)
    py = int(pointer_y)

    x = px + int(gap_x)
    if x + width > right:
        x = px - width - int(gap_x)
    y = py + int(gap_y)
    if y + height > bottom:
        y = py - height - int(gap_y)

    max_x = max(left, right - width)
    max_y = max(top, bottom - height)
    return (
        min(max(x, left), max_x),
        min(max(y, top), max_y),
    )


def _tk_geometry_axis(
    position: int,
    window_size: int,
    screen_origin: int,
    screen_extent: int,
) -> str:
    """Convert an absolute virtual-desktop coordinate to Tk wm-geometry syntax."""
    pos = int(position)
    size = max(1, int(window_size))
    origin = int(screen_origin)
    extent = max(1, int(screen_extent))
    if pos >= 0:
        return f"+{pos:d}"
    far_edge = origin + extent
    edge_offset = max(0, int(far_edge - (pos + size)))
    return f"-{edge_offset:d}"


def _audit_float(value):
    try:
        if value is None or str(value).strip() == "":
            return None
        parsed = float(value)
        return parsed if math.isfinite(parsed) else None
    except Exception:
        return None


def _audit_percentile(values, q: float) -> float:
    ordered = sorted(float(v) for v in values)
    if not ordered:
        return 0.0
    if len(ordered) == 1:
        return ordered[0]
    pos = min(max(float(q), 0.0), 1.0) * (len(ordered) - 1)
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return ordered[lo]
    weight = pos - lo
    return ordered[lo] * (1.0 - weight) + ordered[hi] * weight


def _audit_metric_snapshot(values, bins: int = 24) -> dict:
    vals = [float(v) for v in values if v is not None and math.isfinite(float(v))]
    if not vals:
        return {
            "count": 0, "min": 0.0, "p50": 0.0, "p95": 0.0, "max": 0.0,
            "mean": 0.0, "histogram": (),
        }
    lo, hi = min(vals), max(vals)
    bucket_count = max(1, int(bins))
    counts = [0] * bucket_count
    if hi <= lo:
        counts[0] = len(vals)
    else:
        span = hi - lo
        for value in vals:
            idx = min(bucket_count - 1, int(((value - lo) / span) * bucket_count))
            counts[idx] += 1
    return {
        "count": len(vals),
        "min": lo,
        "p50": _audit_percentile(vals, 0.50),
        "p95": _audit_percentile(vals, 0.95),
        "max": hi,
        "mean": sum(vals) / len(vals),
        "histogram": tuple(counts),
    }


def select_audit_axis_ticks(snapshot: dict, plot_width: float, suffix: str = "") -> tuple[dict, ...]:
    """Select min/P50/P95/max labels while avoiding duplicate/overlapping text."""
    if int(snapshot.get("count", 0) or 0) <= 0:
        return ()
    lo, hi = float(snapshot["min"]), float(snapshot["max"])
    width = max(1.0, float(plot_width))
    if not math.isfinite(lo) or not math.isfinite(hi):
        return ()
    candidates = (("P50", float(snapshot["p50"])), ("P95", float(snapshot["p95"])),
                  ("min", lo), ("max", hi))
    accepted = []
    for name, value in candidates:
        if not math.isfinite(value):
            continue
        if any(abs(value - old["value"]) <= 1e-9 * max(1.0, abs(value)) for old in accepted):
            continue
        label = f"{name} {_fmt_audit_number(value)}{suffix}"
        label_width = min(width, max(28.0, len(label) * 5.6))
        fraction = min(1.0, max(0.0, (value - lo) / (hi - lo))) if hi > lo else 0.5
        x = min(width - label_width / 2.0, max(label_width / 2.0, fraction * width))
        if any(abs(x - old["x"]) < (label_width + old["width"]) / 2.0 + 5.0 for old in accepted):
            continue
        accepted.append({"name": name, "value": value, "label": label, "x": x, "width": label_width})
    return tuple(sorted(accepted, key=lambda item: item["x"]))


def load_llm_audit_distribution(audit_path: str) -> dict:
    """Read the append-only numeric audit metadata; never read prompt/output payloads."""
    values = {name: [] for name, _, _ in _AUDIT_SERIES}
    calls = failures = component_rows = 0
    provider_rows = heuristic_rows = 0
    prior_templates = {}
    if audit_path:
        try:
            with open(audit_path, "r", newline="", encoding="utf-8") as fp:
                for row in csv.DictReader(fp):
                    if not isinstance(row, dict):
                        continue
                    calls += 1
                    if str(row.get("ok", "")).strip().upper() == "NO":
                        failures += 1
                    usage_source = str(row.get("token_usage_source", "") or "").strip().lower()
                    has_api_usage = usage_source in {"", "llm_api_usage"}
                    is_slice = bool(str(row.get("prompt_file", "") or "").strip())
                    has_components = False
                    for name, _, as_percent in _AUDIT_SERIES:
                        if name in {"total_tok_per_s", "effective_tok_per_s_est"}:
                            continue
                        if name in {"input_tokens", "output_tokens", "context_usage_ratio"} and not has_api_usage:
                            continue
                        if name == "elapsed_seconds" and not is_slice:
                            continue
                        parsed = _audit_float(row.get(name))
                        if parsed is None:
                            continue
                        values[name].append(parsed * 100.0 if as_percent else parsed)
                        if name in {"template_tokens", "task_text_tokens"}:
                            has_components = True
                    if has_components:
                        component_rows += 1

                    # Derive directly from API In + Out; existing processing_tps
                    # uses API total_tokens and has a different zero-time fallback.
                    if not is_slice or usage_source != "llm_api_usage":
                        continue
                    elapsed = _audit_float(row.get("elapsed_seconds"))
                    inp = _audit_float(row.get("input_tokens"))
                    out = _audit_float(row.get("output_tokens"))
                    if elapsed is None or elapsed <= 0 or inp is None or out is None or min(inp, out) < 0:
                        continue
                    values["total_tok_per_s"].append((inp + out) / elapsed)
                    cached = _audit_float(row.get("cached_input_tokens"))
                    if (row.get("cached_input_token_source") == "provider_usage"
                            and cached is not None and 0 <= cached <= inp):
                        values["effective_tok_per_s_est"].append((inp - cached + out) / elapsed)
                        provider_rows += 1
                        continue

                    task_tokens = _audit_float(row.get("task_text_tokens"))
                    template = _audit_float(row.get("template_tokens"))
                    stage = str(row.get("stage_identity", "") or "").strip()
                    source = str(row.get("prompt_component_token_source", "") or "").strip()
                    if (not stage or not source or task_tokens is None or template is None
                            or min(task_tokens, template) < 0):
                        continue
                    group = (row.get("model", ""), row.get("base_url", ""),
                             row.get("task", ""), stage, source)
                    # Running floor/ceiling avoid O(n²) rescans on long jobs.
                    prior = prior_templates.setdefault(
                        group, {"count": 0, "min": template, "max": template}
                    )
                    if prior["count"] >= 2:
                        floor, ceiling = prior["min"], prior["max"]
                        tolerance = max(1.0, floor * 0.05)
                        # Not token-level prefix proof. Require stable stage/size
                        # across prior requests; discount possible reusable floor.
                        if ceiling - floor <= tolerance and abs(template - floor) <= tolerance:
                            possibly_cached = min(template, floor * 0.5)
                            estimated_input = task_tokens + max(0.0, template - possibly_cached)
                            values["effective_tok_per_s_est"].append((estimated_input + out) / elapsed)
                            heuristic_rows += 1
                    prior["count"] += 1
                    prior["min"] = min(prior["min"], template)
                    prior["max"] = max(prior["max"], template)
        except (OSError, csv.Error, UnicodeError):
            pass
    return {
        "calls": calls, "failures": failures, "component_rows": component_rows,
        "effective_provider_rows": provider_rows,
        "effective_heuristic_rows": heuristic_rows,
        "metrics": {name: _audit_metric_snapshot(values[name]) for name, _, _ in _AUDIT_SERIES},
    }


def _fmt_audit_number(value: float) -> str:
    # Normalize binary percentile-interpolation artifacts (e.g. 67.74999..)
    # before decimal half-up rounding, preserving full comma-grouped digits.
    number = float(value or 0.0)
    if not math.isfinite(number):
        return "unknown"
    decimal_value = Decimal(format(number, ".15g"))
    return f"{decimal_value.quantize(Decimal('0.1'), rounding=ROUND_HALF_UP):,.1f}"


def format_llm_audit_summary(stats: dict) -> str:
    calls = int(stats.get("calls", 0) or 0)
    if calls <= 0:
        return "No LLM calls yet"
    metrics = stats.get("metrics", {}) or {}
    context = metrics.get("context_usage_ratio", {}) or {}
    input_stats = metrics.get("input_tokens", {}) or {}
    output_stats = metrics.get("output_tokens", {}) or {}
    template_stats = metrics.get("template_tokens", {}) or {}
    latency = metrics.get("elapsed_seconds", {}) or {}
    component_rows = int(stats.get("component_rows", 0) or 0)
    context_text = (
        f"Context P50 {_fmt_audit_number(context.get('p50', 0))}% / "
        f"P95 {_fmt_audit_number(context.get('p95', 0))}%"
        if int(context.get("count", 0) or 0) > 0 else "Context unknown"
    )
    latency_text = (
        f"Slice time P50/P95 {_fmt_audit_number(latency.get('p50', 0))}/"
        f"{_fmt_audit_number(latency.get('p95', 0))}s"
        if int(latency.get("count", 0) or 0) > 0 else "Slice time unknown"
    )
    template_text = (
        f"Template P50/P95 {_fmt_audit_number(template_stats.get('p50', 0))}/"
        f"{_fmt_audit_number(template_stats.get('p95', 0))}"
        if int(template_stats.get("count", 0) or 0) > 0 else "Template unknown"
    )
    input_text = (
        f"In P50 {_fmt_audit_number(input_stats.get('p50', 0))}"
        if int(input_stats.get("count", 0) or 0) > 0 else "In unknown"
    )
    output_text = (
        f"Out P50 {_fmt_audit_number(output_stats.get('p50', 0))}"
        if int(output_stats.get("count", 0) or 0) > 0 else "Out unknown"
    )
    return (
        f"Calls {calls:,} · {context_text} · "
        f"{input_text} · {output_text} · {template_text} · "
        f"{latency_text} · Components {component_rows:,}/{calls:,}"
    )

def _reduction_mode(stats: dict) -> str:
    return str(stats.get("activity_mode", "") or "").strip().lower()


def format_reduction_summary(stats: dict) -> str:
    mode = _reduction_mode(stats)
    if mode == "legacy_merge_slices":
        return (
            "Legacy merge_slices · "
            f"Merged {int(stats.get('legacy_merges_completed', 0) or 0):,}/"
            f"{int(stats.get('legacy_merges_started', 0) or 0):,} · "
            f"Errors {int(stats.get('legacy_merges_failed', 0) or 0):,}"
        )
    if mode == "inactive":
        return "Reduction Engine inactive"
    if mode == "configured_reduction":
        return f"Configured reduction · {str(stats.get('run_status', 'running')).replace('_', ' ').title()}"
    if mode == "reduction_stage":
        return (
            f"Stages {int(stats.get('stages_completed', 0) or 0):,}/"
            f"{int(stats.get('stages_started', 0) or 0):,} · "
            f"Members {int(stats.get('members_succeeded', 0) or 0):,}/"
            f"{int(stats.get('members_attempted', 0) or 0):,} · "
            f"Errors {int(stats.get('stages_failed', 0) or 0):,}"
        )
    return "Waiting for runtime status"


def format_reduction_stats(stats: dict) -> str:
    status = str(stats.get("run_status", "running") or "running").replace("_", " ").title()
    mode = _reduction_mode(stats)
    if mode == "legacy_merge_slices":
        failed = int(stats.get("legacy_merges_failed", 0) or 0)
        return (
            "Mode: Legacy merge_slices (ReductionStage not active)\n"
            f"Merge attempts: {int(stats.get('legacy_merges_completed', 0) or 0):,} / "
            f"{int(stats.get('legacy_merges_started', 0) or 0):,}   Failed: {failed:,}\n"
            f"Cancellation: {status}   Errors: {failed:,}"
        )
    if mode == "inactive":
        return (
            "Reduction Engine: Not active\n"
            "Legacy merge_slices: off\n"
            f"Cancellation: {status}   Errors: 0"
        )
    mode_line = (
        "Mode: Configured reduction"
        if mode == "configured_reduction"
        else "Mode: ReductionStage"
        if mode == "reduction_stage"
        else "Mode: Waiting for runtime status"
    )
    return (
        f"{mode_line}\n"
        f"Stages: {int(stats.get('stages_completed', 0) or 0):,} / "
        f"{int(stats.get('stages_started', 0) or 0):,}\n"
        f"Members: {int(stats.get('members_succeeded', 0) or 0):,} / "
        f"{int(stats.get('members_attempted', 0) or 0):,}   "
        f"Failed: {int(stats.get('members_failed', 0) or 0):,}\n"
        f"Partial accepted: {int(stats.get('partial_accepted', 0) or 0):,}   "
        f"Rejected: {int(stats.get('partial_rejected', 0) or 0):,}\n"
        f"Cancellation: {status}   Errors: {int(stats.get('stages_failed', 0) or 0):,}"
    )


def reduction_status_is_error(stats: dict) -> bool:
    return (
        int(stats.get("stages_failed", 0) or 0) > 0
        or int(stats.get("legacy_merges_failed", 0) or 0) > 0
    )


def format_recheck_summary(stats: dict) -> str:
    return (
        f"Checked {int(stats.get('checked', 0) or 0):,} · "
        f"Need {int(stats.get('pending', 0) or 0):,} · "
        f"Skipped {int(stats.get('already_completed', 0) or 0):,} · "
        f"Errors {int(stats.get('errors', 0) or 0):,}"
    )


def format_recheck_stats(stats: dict) -> str:
    checked = int(stats.get("checked", 0) or 0)
    skipped = int(stats.get("already_completed", 0) or 0)
    rate = skipped / checked if checked else 0.0
    return (
        "Pending Recheck\n"
        f"Checked: {checked:,}   Skipped: {skipped:,} ({rate:.1%})   "
        f"Need processing: {int(stats.get('pending', 0) or 0):,}\n"
        f"Semantic stale: {int(stats.get('semantic_stale_count', 0) or 0):,}   "
        f"Recheck Errors: {int(stats.get('errors', 0) or 0):,}"
    )


def recheck_status_is_error(stats: dict) -> bool:
    return int(stats.get("errors", 0) or 0) > 0

# ---------- 子行程：Tk 主迴圈 ----------

def _enable_windows_dpi_awareness():
    if not IS_WIN:
        return
    try:
        import ctypes
        user32 = ctypes.windll.user32
        # Windows 10優先 PER_MONITOR_AWARE_V2(-4) → (-3) → (-2)
        for ctx in (-4, -3, -2):
            try:
                if hasattr(user32, "SetProcessDpiAwarenessContext"):
                    if user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(ctx)):
                        return
            except Exception:
                pass
        # 8.1 備援
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
            return
        except Exception:
            pass
        # 最後備援
        try:
            user32.SetProcessDPIAware()
        except Exception:
            pass
    except Exception:
        pass


def incident_button_state(quality: dict, recheck: dict, reduction: dict):
    """Per-run indicator; never misrepresent event counts as incident rows.

    Numeric badges count only operational failure *events*. Recheck/Reduction
    errors and unresolved document decisions have distinct denominators.
    """
    stream = str(quality.get("quality_stream_status") or "")
    unavailable = stream in {"unverified", "capacity_exceeded"}
    incomplete = stream in {"unsealed_legacy", "degraded_corrupt_lines", "incomplete_tail"}
    events = sum(max(0, int(quality.get(key, 0) or 0)) for key in (
        "consumer_orchestration_failure_events", "row_merger_retryable_failure_events",
        "producer_operational_failure_events", "stage_orchestration_failure_events",
        "worker_phase_failure_events",
    ))
    documents = max(0, int(quality.get("documents_schema_pending", 0) or 0))
    recheck_errors = max(0, int(recheck.get("errors", 0) or 0))
    reduction_errors = (
        max(0, int(reduction.get("stages_failed", 0) or 0))
        + max(0, int(reduction.get("legacy_merges_failed", 0) or 0))
    )
    detail = (
        "重大異常檢閱／管理（點擊開啟浮動視窗）\n"
        "僅顯示本次已觀察到的狀態；不是全部檢閱條目數。\n"
        f"Producer／Stage／Worker／Consumer／Row Merger 事件：{events:,} 次（非文件數）\n"
        f"待處理文件結構異常：{documents:,} 筆\n"
        f"Recheck 錯誤：{recheck_errors:,} 次；Reduction 錯誤：{reduction_errors:,} 次"
    )
    if unavailable:
        return "⚠ ?", "#b00020", detail + "\n品質事件資料不可用，不能視為零異常。"
    if events or documents or recheck_errors or reduction_errors:
        badge = (f"{min(events, 99)}{'+' if events > 99 else ''}"
                 if events else "•")
        return f"⚠ {badge}", "#b00020", detail
    if incomplete:
        return "⚠ ?", "#b45309", detail + "\n品質紀錄不完整，不能視為零異常。"
    return "⚠", "#666666", detail + "\n未觀察到上述異常；不代表其他來源已驗證。"


_REPAIR_ANALYSIS_LABELS = {
    "JSON_REPAIR_SYNTAX_CANDIDATE": "疑似符號修補",
    "JSON_REPAIR_TAIL_CANDIDATE": "疑似尾端補全",
    "JSON_REPAIR_CONTENT_EDIT": "內容有變動",
    "JSON_REPAIR_LARGE_CHANGE": "內容大幅變更",
    "JSON_REPAIR_COMPARISON_UNAVAILABLE": "無法可靠比較",
}
_REPAIR_ERROR_LABELS = {
    "UNTERMINATED_STRING": "字串未結束",
    "EXPECTED_DELIMITER": "分隔符號／必要值",
    "EXTRA_DATA": "額外內容",
    "INVALID_ESCAPE": "跳脫／控制字元",
    "OTHER": "其他語法錯誤",
}


def format_json_repair_analysis_summary(stats: dict) -> str:
    """Real repair comparisons only; historical runs cannot be backfilled."""
    status = stats.get("quality_stream_status")
    if status in {"unverified", "capacity_exceeded"}:
        return "JSON 修復差異：品質紀錄不可驗證（未提供分類）"
    count = int(stats.get("repair_analysis_count", 0) or 0)
    if count == 0:
        return "JSON 修復差異：尚無可比較紀錄（舊版修復不回補）"
    category = stats.get("repair_analysis_categories") or {}
    counts = "｜".join(
        f"{name} {int(category.get(code, 0) or 0)}"
        for code, name in _REPAIR_ANALYSIS_LABELS.items()
    )
    return f"JSON 修復前後（已觀察 {count} 次）：{counts}"


def format_json_repair_analysis_case(case: dict) -> tuple[str, ...]:
    detail = case.get("detail") or {}
    code = case.get("code") or ""
    pct = (f"{detail.get('same_literal_pct', 0)}%" if code in {
        "JSON_REPAIR_SYNTAX_CANDIDATE", "JSON_REPAIR_CONTENT_EDIT",
        "JSON_REPAIR_LARGE_CHANGE",
    } else "—")
    return (
        str(case.get("ts") or "—"),
        str(case.get("run_id") or "—"),
        str(case.get("slice_hint") or "—"),
        str(case.get("event_hint") or "—"),
        _REPAIR_ANALYSIS_LABELS.get(code, "無法判定"),
        f"{int(detail.get('original_chars', 0)):,} → {int(detail.get('repaired_chars', 0)):,}",
        f"{int(detail.get('error_pos_pct', 0))}%",
        pct,
        f"{int(detail.get('before_key_patterns', 0))} → {int(detail.get('after_key_patterns', 0))}",
    )


def format_json_repair_analysis_case_detail(case: dict) -> str:
    detail = case.get("detail") or {}
    err = _REPAIR_ERROR_LABELS.get(detail.get("error_kind"), "未知")
    prefix = int(detail.get("common_prefix_chars", 0))
    suffix = int(detail.get("common_suffix_chars", 0))
    return (
        f"原始解析錯誤：{err}（約 {detail.get('error_pos_pct', 0)}% 位置）；"
        f"共同前綴 {prefix:,} 字／共同後綴 {suffix:,} 字。"
        " 字面值相同率為詞法估計，疑似鍵名片段數為近似掃描數（非唯一 dict key 數）；"
        " 無法據此證實事件、欄位或內容完整保留，亦不能推論原始輸出已截斷。"
    )


def format_json_repair_metric_help() -> str:
    """Explain the two different event denominators, without implying lineage."""
    return (
        "初次 JSON 不合法：不合法驗證事件數／所有已記錄的切片 JSON 驗證事件數。\n"
        "JSON 修復成功：成功修復事件數／所有已記錄的修復嘗試事件數。\n"
        "兩者的分母不同；修復成功率 100% 不代表所有不合法 JSON 都已修復。\n"
        "這裡統計的是事件／嘗試，不是不同文件數，也不能直接推算尚待修復筆數。"
    )


def format_quality_summary(stats: dict) -> str:
    """Keep incompatible slice/document denominators separate in the header."""
    status = stats.get("quality_stream_status", "")
    if status == "unverified":
        return "⚠️ 品質事件封存或檔案驗證異常，統計暫不可用；請檢查離線報告"
    if status == "capacity_exceeded":
        return "⚠️ 品質事件超過 GUI 安全累計上限，統計暫不可用；請使用離線報告"
    if status == "not_initialized":
        return "尚未取得此次執行的品質事件"
    advisory = {
        "unsealed_legacy": "⚠️ 歷史封存未建立完整性驗證基準｜",
        "degraded_corrupt_lines": "⚠️ 品質事件含損毀紀錄，統計不完整｜",
        "incomplete_tail": "品質事件末行寫入中（僅統計完整紀錄）｜",
    }.get(status, "")
    def percent(key, n):
        value = stats.get(key)
        return "— (樣本不足)" if value is None else f"{value:.1f}% (n={n:,})"

    def observed_ratio(numerator_key, denominator_key, percent_key, unit):
        numerator = stats.get(numerator_key)
        denominator = stats.get(denominator_key)
        percentage = stats.get(percent_key)
        # Never invent a numerator for older/missing quality snapshots and
        # never present a nonexistent 0/0 sample as 0% or full recovery.
        if numerator is None or denominator is None or percentage is None:
            return "—（樣本不足）"
        numerator = int(numerator)
        denominator = int(denominator)
        if denominator <= 0 or numerator < 0 or numerator > denominator:
            return "—（樣本不足）"
        return f"{numerator:,}/{denominator:,} {unit}（{percentage:.1f}%）"

    return (
        advisory +
        "初次 JSON 不合法 "
        + observed_ratio(
            "slice_initial_invalid", "slice_validation_attempts",
            "slice_initial_invalid_pct", "次驗證",
        )
        + "  ｜  JSON 修復成功 "
        + observed_ratio(
            "repair_succeeded", "repair_attempts",
            "repair_success_pct", "次修復嘗試",
        )
        + f"  ｜  LLM 文件結構異常（待處理） {percent('document_schema_reject_pct', int(stats.get('documents_decided', 0)))}"
        f"  ｜  確認式 Sink 寫回 {int(stats.get('documents_writeback_confirmed', 0)):,} 筆"
        f"  ｜  Consumer 調度異常 {int(stats.get('consumer_orchestration_failure_events', 0)):,} 次（事件數）"
        f"  ｜  Row Merger 暫時異常 {int(stats.get('row_merger_retryable_failure_events', 0)):,} 次（節流事件數）"
        f"  ｜  Producer 執行異常 {int(stats.get('producer_operational_failure_events', 0)):,} 次（事件數）"
        f"  ｜  Stage 調度例外 {int(stats.get('stage_orchestration_failure_events', 0)):,} 次（事件數）"
        f"  ｜  Worker 階段例外 {int(stats.get('worker_phase_failure_events', 0)):,} 次（事件數）"
    )


def _quality_reader_worker(path_queue, result_queue, stop_event, poll_interval: float = 1.0):
    """Reconcile sealed archives + active JSONL off the Tk event loop."""
    reader = QualityRunTailReader()
    last_published = None

    def publish(stats):
        nonlocal last_published
        if stats == last_published:
            return
        try:
            while True:
                result_queue.get_nowait()
        except pyqueue.Empty:
            pass
        try:
            result_queue.put_nowait(stats)
            last_published = stats
        except pyqueue.Full:
            pass

    while not stop_event.is_set():
        try:
            while True:
                path = str(path_queue.get_nowait() or "")
                reader = QualityRunTailReader(path)
        except pyqueue.Empty:
            pass
        try:
            _, stats = reader.poll()
            # Publish even when the reader's counters did not change: after a
            # previous integrity failure the last GUI snapshot was marked
            # unverified, and identical restored counters must become visible.
            # publish() deduplicates unchanged successful snapshots.
            publish(stats)
        except QualityCapacityExceeded:
            # Exact counters cannot fit the GUI cardinality/line budgets.
            # Preserve files and explicitly direct operators to offline report.
            unavailable = QualityAccumulator().snapshot()
            unavailable["quality_stream_status"] = "capacity_exceeded"
            publish(unavailable)
        except (OSError, ValueError):
            # A failed ledger, vanished known shard or unsafe link means the
            # whole snapshot is unknown. Never silently keep old green values.
            unavailable = QualityAccumulator().snapshot()
            unavailable["quality_stream_status"] = "unverified"
            publish(unavailable)
        stop_event.wait(max(0.05, float(poll_interval)))


def _audit_reader_worker(path_queue, result_queue, stop_event, poll_interval: float = 1.0):
    """Parse growing audit CSVs off the Tk event-loop thread."""
    audit_path = ""
    mtime_ns = None
    while not stop_event.is_set():
        try:
            while True:
                audit_path = str(path_queue.get_nowait() or "")
                mtime_ns = None
        except pyqueue.Empty:
            pass

        if audit_path:
            try:
                stat = os.stat(audit_path)
                current_mtime = getattr(
                    stat, "st_mtime_ns", int(stat.st_mtime * 1_000_000_000)
                )
            except OSError:
                current_mtime = None
            if current_mtime is not None and current_mtime != mtime_ns:
                mtime_ns = current_mtime
                stats = load_llm_audit_distribution(audit_path)
                try:
                    while True:
                        result_queue.get_nowait()
                except pyqueue.Empty:
                    pass
                try:
                    result_queue.put_nowait(stats)
                except pyqueue.Full:
                    pass

        stop_event.wait(max(0.05, float(poll_interval)))


# Document progress columns obey their measured viewport, rather than Tk's
# opportunistic stretch weights that can push the last column off-screen.
_DOCUMENT_COLUMN_WEIGHTS = (3, 1, 2, 4, 0, 0, 0)
_DOCUMENT_COLUMN_GUTTER = 12


def fit_document_column_widths(
    available_width: int,
    minimums: tuple[int, ...],
    weights: tuple[int, ...] = _DOCUMENT_COLUMN_WEIGHTS,
    *,
    gutter: int = _DOCUMENT_COLUMN_GUTTER,
) -> tuple[tuple[int, ...], bool]:
    """Allocate Treeview widths exactly within the usable viewport.

    Fixed small counters stay at their minima. When even the minima cannot
    fit, return them unchanged and signal the existing horizontal scrollbar.
    This pure helper is independent of Tk and Windows DPI.
    """
    if (not minimums or len(minimums) != len(weights)
            or any(not isinstance(v, int) or v <= 0 for v in minimums)
            or any(not isinstance(v, int) or v < 0 for v in weights)
            or not isinstance(available_width, int) or not isinstance(gutter, int)):
        raise ValueError("invalid document column layout")
    target = max(0, available_width - max(0, gutter))
    base = sum(minimums)
    if target < base:
        return tuple(minimums), True
    remaining = target - base
    total_weight = sum(weights)
    if remaining == 0 or total_weight == 0:
        return tuple(minimums), False
    increments = [remaining * weight // total_weight for weight in weights]
    extra = remaining - sum(increments)
    # Largest remainders prevent one extra pixel being added beyond viewport.
    if extra:
        order = sorted(
            (i for i, w in enumerate(weights) if w),
            key=lambda i: (-(remaining * weights[i] % total_weight), i),
        )
        for idx in order[:extra]:
            increments[idx] += 1
    return tuple(v + inc for v, inc in zip(minimums, increments)), False


def main_page_needs_vertical_scroll(content_height: int, viewport_height: int) -> bool:
    """Show a vertical bar only when the complete GUI page exceeds its viewport.

    Heights are actual Tk pixel measurements after layout/DPI scaling,
    not assumptions about expanded sections or screen resolution.
    """
    if (not isinstance(content_height, int)
            or not isinstance(viewport_height, int)):
        raise ValueError("GUI layout heights must be integer pixels")
    return content_height > max(0, viewport_height)


def main_page_mouse_wheel_units(delta: int) -> int:
    """Windows wheel delta to canvas scroll units; support touchpad deltas."""
    if not isinstance(delta, int) or delta == 0:
        return 0
    magnitude = min(8, max(1, (abs(delta) + 119) // 120))
    return -magnitude if delta > 0 else magnitude


def _gui_proc_main(q: "mp.Queue", cancel_event, total: int, title: str):
    """子行程內執行：所有 Tk 操作都在這裡，避免跨緒/跨行程錯誤。"""
    _enable_windows_dpi_awareness()
    try:
        import tkinter as tk
        from tkinter import ttk
        import tkinter.font as tkfont
        import time
    except Exception:
        # 無法載入 Tk，直接吃掉隊列直到 CLOSE
        while True:
            try:
                evt, _ = q.get(timeout=0.5)
                if evt == _GuiEvents.CLOSE:
                    break
            except pyqueue.Empty:
                pass
        return

    root = tk.Tk()
    root.title(title or "LLM 分析進度")
    root.geometry("760x500")  # 高度略增，容納 ETA 區塊

    # DPI-aware scaling
    try:
        dpi = float(root.winfo_fpixels("1i"))
        root.tk.call("tk", "scaling", max(1.0, dpi / 72.0))
    except Exception:
        pass

    # 字型調整：Segoe UI / Consolas
    try:
        for name, size in [
            ("TkDefaultFont", 10),
            ("TkTextFont",    10),
            ("TkFixedFont",   10),
            ("TkMenuFont",    10),
            ("TkHeadingFont", 11),
        ]:
            try:
                f = tkfont.nametofont(name)
                if name == "TkFixedFont":
                    f.configure(family="Consolas", size=size)
                else:
                    f.configure(family="Segoe UI", size=size)
            except Exception:
                pass
        style = ttk.Style()
        style.configure(".", font=("Segoe UI", 10))
    except Exception:
        pass

    # The whole page must be scrollable, not just the bottom console.
    # A separate Canvas is already used by the audit chart and keeps its
    # own rendering; this *outer* canvas only moves the Tk page window.
    page_shell = ttk.Frame(root)
    page_shell.pack(fill="both", expand=True)
    page_canvas = tk.Canvas(
        page_shell, width=1, height=1, borderwidth=0,
        highlightthickness=0, background=root.cget("bg"),
    )
    page_scrollbar = ttk.Scrollbar(
        page_shell, orient="vertical", command=page_canvas.yview,
    )
    page_canvas.configure(yscrollcommand=page_scrollbar.set)
    page_canvas.pack(side="left", fill="both", expand=True)
    frm = ttk.Frame(page_canvas, padding=10)
    page_window = page_canvas.create_window((0, 0), window=frm, anchor="nw")
    _page_scroll_refresh_pending = False

    def _refresh_page_scroll():
        nonlocal _page_scroll_refresh_pending
        _page_scroll_refresh_pending = False
        try:
            width = int(page_canvas.winfo_width())
            viewport = int(page_canvas.winfo_height())
            if width <= 1 or viewport <= 1:
                return
            page_canvas.itemconfigure(page_window, width=width)
            # reqheight reflects collapsed/expanded panel heights and live
            # text wrapping. Do not use the screen's unscaled geometry.
            content_height = max(1, int(frm.winfo_reqheight()))
            page_canvas.configure(
                scrollregion=(0, 0, width, content_height),
            )
            overflowing = main_page_needs_vertical_scroll(
                content_height, viewport,
            )
            if overflowing and not page_scrollbar.winfo_manager():
                page_scrollbar.pack(side="right", fill="y", before=page_canvas)
            elif not overflowing and page_scrollbar.winfo_manager():
                page_scrollbar.pack_forget()
                page_canvas.yview_moveto(0)
        except tk.TclError:
            # The GUI may close during a queued idle layout callback.
            pass

    def _schedule_page_scroll_refresh(_event=None):
        nonlocal _page_scroll_refresh_pending
        if not _page_scroll_refresh_pending:
            _page_scroll_refresh_pending = True
            root.after_idle(_refresh_page_scroll)

    def _page_viewport_resized(event):
        try:
            page_canvas.itemconfigure(page_window, width=max(1, int(event.width)))
        except tk.TclError:
            return
        _schedule_page_scroll_refresh()

    page_canvas.bind("<Configure>", _page_viewport_resized)
    frm.bind("<Configure>", _schedule_page_scroll_refresh)

    def _on_page_mousewheel(event):
        # Tk routes child-widget wheel events through the root toplevel
        # bindtag. Respect Text, Treeview and combobox's own scrollbars.
        try:
            widget = event.widget
            if (widget.winfo_toplevel() is not root
                    or isinstance(widget, (tk.Text, ttk.Treeview, ttk.Combobox))
                    or not page_scrollbar.winfo_manager()
                    or (int(getattr(event, "state", 0)) & 0x0004)):
                return None
            units = main_page_mouse_wheel_units(int(getattr(event, "delta", 0)))
            if units:
                page_canvas.yview_scroll(units, "units")
                return "break"
        except (tk.TclError, ValueError, TypeError):
            pass
        return None

    root.bind("<MouseWheel>", _on_page_mousewheel)
    _schedule_page_scroll_refresh()

    # 內部狀態
    _tot = max(1, int(total))
    _done_cnt  = 0
    _sched_cnt = 0
    _recheck_stats = {}
    _recheck_error_visible = False
    _reduction_stats = {}
    _audit_stats = load_llm_audit_distribution("")
    _audit_path = ""
    _recovery_meter_path = ""
    _recovery_review_window = None
    _audit_path_queue = pyqueue.Queue(maxsize=2)
    _audit_result_queue = pyqueue.Queue(maxsize=1)
    _audit_reader_stop = threading.Event()
    _audit_reader_thread = threading.Thread(
        target=_audit_reader_worker,
        args=(_audit_path_queue, _audit_result_queue, _audit_reader_stop),
        name="llm-audit-gui-reader",
        daemon=True,
    )
    _audit_reader_thread.start()
    _quality_stats = QualityAccumulator().snapshot()
    _quality_path_queue = pyqueue.Queue(maxsize=2)
    _quality_result_queue = pyqueue.Queue(maxsize=1)
    _quality_reader_stop = threading.Event()
    _quality_reader_thread = threading.Thread(
        target=_quality_reader_worker,
        args=(_quality_path_queue, _quality_result_queue, _quality_reader_stop),
        name="quality-gui-reader", daemon=True,
    )
    _quality_reader_thread.start()
    _quality_expanded = False
    _recheck_expanded = False
    _reduction_expanded = False
    _audit_expanded = False

    # ---- ETA 估算狀態（指數平滑，降低抖動）----
    _t0 = None            # 開始時間（第一次排程/完成時啟動）
    _last_ts = None       # 上次完成事件時間
    _last_done = 0        # 上次完成數
    _rate_ema = 0.0       # 平滑後速率（列/秒）
    _ALPHA = 0.25         # 平滑係數（越大越敏感）

    def _fmt(n: int) -> str:
        return f"{n:,}"

    def _pct(n: int, d: int) -> str:
        return f"{(n/d*100):.0f}%" if d > 0 else "0%"

    def _fmt_dur(sec: float | None) -> str:
        if sec is None:
            return "—"
        sec = max(0, int(sec))
        h = sec // 3600
        m = (sec % 3600) // 60
        s = sec % 60
        return f"{h}:{m:02d}:{s:02d}" if h > 0 else f"{m:02d}:{s:02d}"

    def _maybe_boot_timer():
        nonlocal _t0, _last_ts
        if _t0 is None:
            _t0 = _last_ts = time.time()

    def _accumulate_rate(on_inc_done: int):
        """完成事件時更新速率 EMA。"""
        nonlocal _last_ts, _last_done, _rate_ema
        now = time.time()
        if _last_ts is None:
            _last_ts = now
            _last_done = _done_cnt - on_inc_done
        dt = max(1e-6, now - _last_ts)
        ddone = max(0, (_done_cnt - _last_done))
        inst_rate = ddone / dt if ddone > 0 else 0.0
        if inst_rate > 0:
            _rate_ema = inst_rate if _rate_ema <= 0 else (1 - _ALPHA) * _rate_ema + _ALPHA * inst_rate
            _last_ts = now
            _last_done = _done_cnt

    def _eta_text():
        if _t0 is None:
            return "⏱ 已用時 00:00｜剩餘 —｜預計完成 —｜速度 — 列/秒"
        now = time.time()
        elapsed = now - _t0
        if _rate_ema > 0.0:
            remain = (_tot - _done_cnt) / _rate_ema
            finish_ts = now + remain
            finish_str = time.strftime("%H:%M:%S", time.localtime(finish_ts))
            rate_str = f"{_rate_ema:.2f} 列/秒"
        else:
            remain = None
            finish_str = "—"
            rate_str = "—"
        return f"⏱ 已用時 {_fmt_dur(elapsed)}｜剩餘 {_fmt_dur(remain)}｜預計完成 {finish_str}｜速度 {rate_str}"

    def _update_labels():
        lbl_sched.configure(text=f"排程進度（切片／入佇列） {_fmt(_sched_cnt)}/{_fmt(_tot)}  ({_pct(_sched_cnt, _tot)})")
        lbl_done.configure(text=f"完成進度（合併＋寫回）  {_fmt(_done_cnt)}/{_fmt(_tot)}  ({_pct(_done_cnt, _tot)})")
        lbl_eta.configure(text=_eta_text())

    lbl_sched = ttk.Label(frm)
    bar_sched = ttk.Progressbar(frm, maximum=_tot, value=0, length=680)

    lbl_done  = ttk.Label(frm)
    bar_done  = ttk.Progressbar(frm, maximum=_tot, value=0, length=680)

    lbl_sched.pack(anchor="w"); bar_sched.pack(fill="x", pady=(0,8))
    lbl_done.pack(anchor="w");  bar_done.pack(fill="x", pady=(0,8))

    # ---- ETA 顯示（新增）----
    lbl_eta = ttk.Label(frm, foreground="#555")
    lbl_eta.pack(anchor="w", pady=(0, 8))

    # Shared review popup; the launch icon lives in the Processing Quality
    # header. Review actions never clear queue holds or delete Success.
    def _open_recovery_review():
        nonlocal _recovery_review_window
        try:
            if (_recovery_review_window is not None
                    and _recovery_review_window.winfo_exists()):
                _recovery_review_window.lift()
                _recovery_review_window.focus_set()
                return
            from czjLLM.job_manager.recovery_review_gui import show_recovery_review
            _recovery_review_window = show_recovery_review(
                root, lambda: _recovery_meter_path,
                audit_path_provider=lambda: _audit_path,
            )
        except Exception as exc:
            from tkinter import messagebox
            messagebox.showerror(
                "檢閱介面無法開啟", type(exc).__name__, parent=root,
            )

    # Recheck / Reduction 都是短摘要＋可展開細節；並排可把垂直空間
    # 留給主要執行日誌。兩欄等寬，展開狀態仍各自獨立。
    status_row = ttk.Frame(frm)
    status_row.pack(fill="x", pady=(0, 4))
    status_row.columnconfigure(0, weight=1, uniform="status")
    status_row.columnconfigure(1, weight=1, uniform="status")

    recheck_section = ttk.Frame(status_row)
    recheck_section.grid(row=0, column=0, sticky="nsew", padx=(0, 4))
    recheck_toggle = ttk.Button(recheck_section)
    recheck_toggle.pack(fill="x")
    recheck_frame = ttk.Frame(recheck_section, padding=(8, 5))
    lbl_recheck = ttk.Label(
        recheck_frame, text=format_recheck_stats({}), justify="left", wraplength=320
    )
    lbl_recheck.pack(anchor="w")

    reduction_section = ttk.Frame(status_row)
    reduction_section.grid(row=0, column=1, sticky="nsew", padx=(4, 0))
    reduction_header = ttk.Frame(reduction_section)
    reduction_header.pack(fill="x")
    # 右側控制區先 pack，確保窄視窗／DPI scaling 下 Cancel 不會被
    # 左側可伸展的摘要按鈕擠出可視範圍。
    reduction_controls = ttk.Frame(reduction_header)
    reduction_controls.pack(side="right")
    cancel_status = ttk.Label(reduction_controls, text="Running")
    cancel_status.pack(side="left", padx=(8, 6))
    reduction_toggle = ttk.Button(reduction_header)
    reduction_toggle.pack(side="left", fill="x", expand=True)
    reduction_frame = ttk.Frame(reduction_section, padding=(8, 5))
    lbl_reduction = ttk.Label(
        reduction_frame, text=format_reduction_stats({}), justify="left", wraplength=320
    )
    lbl_reduction.pack(anchor="w")

    def _resize_status_detail_wrap(event):
        # Each status section owns half the row. Leave room for the inter-panel
        # gutter and the detail-frame padding, then let long diagnostic lines
        # wrap instead of disappearing beyond the visible column.
        column_width = max(180, (int(event.width) - 8) // 2)
        wrap = max(160, column_width - 24)
        lbl_recheck.configure(wraplength=wrap)
        lbl_reduction.configure(wraplength=wrap)

    status_row.bind("<Configure>", _resize_status_detail_wrap)

    # Run-scoped quality is separate from LLM performance distributions.
    quality_section = ttk.Frame(frm)
    quality_section.pack(fill="x", pady=(0, 4))
    # 重大異常檢閱／管理：right-hand icon, not a dedicated row.
    quality_header = ttk.Frame(quality_section)
    quality_header.pack(fill="x")
    recovery_button = tk.Button(
        quality_header, text="⚠", command=_open_recovery_review,
        font=("Segoe UI", 11), relief="flat", borderwidth=0,
        padx=8, pady=0, highlightthickness=1, takefocus=True,
        cursor="hand2", background=root.cget("bg"),
    )
    recovery_button.pack(side="right", padx=(4, 0))
    quality_toggle = ttk.Button(quality_header)
    quality_toggle.pack(side="left", fill="x", expand=True)
    # JSON-only diagnostic details live in an on-demand Toplevel, not an
    # always-present table that consumes height for non-JSON tasks.
    quality_summary_row = ttk.Frame(quality_section)
    quality_summary_row.pack(fill="x", padx=8, pady=(2, 3))
    _repair_review_window = None

    def _open_json_repair_review():
        nonlocal _repair_review_window
        try:
            if (_repair_review_window is not None
                    and _repair_review_window.winfo_exists()):
                _repair_review_window.lift()
                _repair_review_window.focus_set()
                return
            from czjLLM.job_manager.json_repair_review_gui import show_json_repair_review
            _repair_review_window = show_json_repair_review(
                root, lambda: _quality_stats,
                format_json_repair_analysis_case,
                format_json_repair_analysis_summary,
                format_json_repair_analysis_case_detail,
            )
        except Exception as error:
            from tkinter import messagebox
            messagebox.showerror(
                "JSON 修復差異視窗無法開啟", type(error).__name__, parent=root,
            )

    repair_analysis_button = tk.Button(
        quality_summary_row, text="🔎 JSON 差異",
        command=_open_json_repair_review,
        font=("Segoe UI", 9, "bold"), relief="raised", borderwidth=1,
        background="#ffe7a0", foreground="#4e3400",
        activebackground="#ffd16b", padx=8, pady=3,
        takefocus=True, cursor="hand2",
    )
    quality_summary = ttk.Label(
        quality_summary_row, text=format_quality_summary(_quality_stats),
        anchor="w", justify="left", wraplength=720,
    )
    quality_summary.pack(side="left", fill="x", expand=True)
    # Button is packed by _refresh_quality() only when this run has JSON
    # repair attempts or genuine before/after observations.
    quality_frame = ttk.Frame(quality_section, padding=(8, 5))
    quality_metrics = {}
    _quality_help_labels = []
    for key, title in (
        ("slice_initial_invalid_pct", "初次 JSON 不合法 / 已驗證切片"),
        ("repair_success_pct", "修復成功 / 已完成修復嘗試"),
        ("document_schema_reject_pct", "文件結構驗證未通過 / 已判定文件"),
    ):
        label = ttk.Label(quality_frame, text=title)
        label.pack(anchor="w")
        if key in {"slice_initial_invalid_pct", "repair_success_pct"}:
            _quality_help_labels.append(label)
        quality_metrics[key] = ttk.Progressbar(
            quality_frame, maximum=100, value=0,
        )
        quality_metrics[key].pack(fill="x", pady=(0, 3))
    quality_codes = ttk.Label(quality_frame, anchor="w", justify="left", wraplength=720)
    quality_codes.pack(fill="x")

    # Use the full window width rather than a hard-coded 720px text column.
    def _resize_quality_wrap(event):
        width = max(280, int(event.width) - 16)
        quality_summary.configure(wraplength=width)
        quality_codes.configure(wraplength=width)

    quality_section.bind("<Configure>", _resize_quality_wrap)

    _incident_tooltip_text = ""
    def _refresh_incident_button():
        nonlocal _incident_tooltip_text
        text, color, detail = incident_button_state(
            _quality_stats, _recheck_stats, _reduction_stats,
        )
        _incident_tooltip_text = detail
        recovery_button.configure(
            text=text, foreground=color, activeforeground=color,
        )

    def _refresh_quality():
        quality_toggle.configure(text=f"{'▼' if _quality_expanded else '▶'} Processing Quality / 異常監控")
        quality_summary.configure(text=format_quality_summary(_quality_stats))
        for key, widget in quality_metrics.items():
            widget.configure(value=float(_quality_stats.get(key) or 0))
        codes = _quality_stats.get("error_codes", {}) or {}
        top = sorted(codes.items(), key=lambda pair: (-pair[1], pair[0]))[:5]
        unusable = _quality_stats.get("quality_stream_status") in (
            "unverified", "capacity_exceeded",
        )
        quality_codes.configure(
            text=("品質事件尚無可靠統計，請查閱離線報告並檢查封存狀態" if unusable
                  else "主要錯誤（事件次數）： " + (
                      "｜".join(f"{code}: {count:,}" for code, count in top)
                      if top else "尚無錯誤事件"))
        )

        nonlocal _repair_review_window
        observed = (
            int(_quality_stats.get("repair_attempts", 0) or 0) > 0 or
            int(_quality_stats.get("repair_analysis_count", 0) or 0) > 0
        )
        if observed and not repair_analysis_button.winfo_manager():
            repair_analysis_button.pack(side="right", padx=(8, 0))
        elif not observed and repair_analysis_button.winfo_manager():
            repair_analysis_button.pack_forget()
        repair_analysis_button.configure(
            text=f"🔎 JSON 差異 ({int(_quality_stats.get('repair_analysis_count', 0) or 0)})",
        )
        if _repair_review_window is not None:
            try:
                if _repair_review_window.winfo_exists():
                    _repair_review_window.refresh_repair_analysis()
                else:
                    _repair_review_window = None
            except (tk.TclError, AttributeError):
                _repair_review_window = None
        _refresh_incident_button()

    def _toggle_quality():
        nonlocal _quality_expanded
        _quality_expanded = not _quality_expanded
        if _quality_expanded:
            quality_frame.pack(fill="x")
        else:
            quality_frame.pack_forget()
        _refresh_quality()

    quality_toggle.configure(command=_toggle_quality)
    _refresh_quality()

    # LLM token/context distributions are collapsed by default. The GUI reads
    # the append-only audit CSV so worker execution does not need GUI coupling.
    audit_section = ttk.Frame(frm)
    audit_section.pack(fill="x", pady=(0, 4))
    audit_toggle = ttk.Button(audit_section)
    audit_toggle.pack(fill="x")
    audit_summary = ttk.Label(
        audit_section,
        text=format_llm_audit_summary(_audit_stats),
        justify="left",
        anchor="w",
        wraplength=720,
    )
    audit_summary.pack(fill="x", padx=8, pady=(2, 3))
    audit_frame = ttk.Frame(audit_section, padding=(8, 5))
    audit_canvas = tk.Canvas(
        audit_frame, height=340, highlightthickness=0, background="white"
    )
    audit_canvas.pack(fill="x", expand=True)
    _audit_tooltip = None
    _audit_tooltip_key = None
    _audit_chart_keys = (
        "input_tokens", "output_tokens", "elapsed_seconds",
        "task_text_tokens", "context_usage_ratio",
        "total_tok_per_s", "effective_tok_per_s_est",
    )

    def _hide_audit_tooltip(_event=None):
        nonlocal _audit_tooltip, _audit_tooltip_key
        if _audit_tooltip is not None:
            try:
                _audit_tooltip.destroy()
            except Exception:
                pass
        _audit_tooltip = None
        _audit_tooltip_key = None

    def _show_audit_tooltip(text: str, x_root: int, y_root: int, key: str):
        nonlocal _audit_tooltip, _audit_tooltip_key
        if _audit_tooltip is None:
            _audit_tooltip = tk.Toplevel(root)
            _audit_tooltip.overrideredirect(True)
            try:
                _audit_tooltip.attributes("-topmost", True)
            except Exception:
                pass
            label = tk.Label(
                _audit_tooltip,
                text=text,
                justify="left",
                anchor="nw",
                wraplength=520,
                padx=10,
                pady=8,
                background="#fffbe6",
                foreground="#222222",
                relief="solid",
                borderwidth=1,
                font=("Segoe UI", 9),
            )
            label.pack()
        elif _audit_tooltip_key != key:
            children = _audit_tooltip.winfo_children()
            if children:
                children[0].configure(text=text)
        _audit_tooltip_key = key
        _audit_tooltip.update_idletasks()
        tooltip_width = max(1, int(_audit_tooltip.winfo_reqwidth() or 1))
        tooltip_height = max(1, int(_audit_tooltip.winfo_reqheight() or 1))
        screen_x = int(root.winfo_vrootx() or 0)
        screen_y = int(root.winfo_vrooty() or 0)
        screen_width = max(1, int(root.winfo_vrootwidth() or root.winfo_screenwidth() or 1))
        screen_height = max(1, int(root.winfo_vrootheight() or root.winfo_screenheight() or 1))
        monitor_x, monitor_y, monitor_width, monitor_height = _monitor_work_area_at(
            x_root,
            y_root,
            screen_x,
            screen_y,
            screen_width,
            screen_height,
        )
        tooltip_x, tooltip_y = _tooltip_screen_position(
            x_root,
            y_root,
            tooltip_width,
            tooltip_height,
            monitor_x,
            monitor_y,
            monitor_width,
            monitor_height,
        )
        geometry_x = _tk_geometry_axis(
            tooltip_x, tooltip_width, screen_x, screen_width
        )
        geometry_y = _tk_geometry_axis(
            tooltip_y, tooltip_height, screen_y, screen_height
        )
        _audit_tooltip.geometry(f"{geometry_x}{geometry_y}")

    def _audit_canvas_layout_width():
        return max(640, int(audit_canvas.winfo_width() or 640))

    def _audit_canvas_layout_height():
        return max(340, int(audit_canvas.winfo_height() or 340))

    def _audit_canvas_help(event):
        width = _audit_canvas_layout_width()
        height = _audit_canvas_layout_height()
        row = 0 if float(event.y) < (height / 2.0) else 1
        cols = 3 if row == 0 else 4
        col = min(cols - 1, max(0, int(float(event.x) / max(width / cols, 1.0))))
        idx = col if row == 0 else 3 + col
        if idx >= len(_audit_chart_keys):
            _hide_audit_tooltip()
            return
        key = _audit_chart_keys[idx]
        _show_audit_tooltip(
            format_audit_distribution_help(key),
            event.x_root,
            event.y_root,
            key,
        )

    def _audit_header_help(event):
        _show_audit_tooltip(
            format_audit_distribution_help("template_tokens"),
            event.x_root,
            event.y_root,
            "__general__",
        )

    audit_canvas.bind("<Motion>", _audit_canvas_help)
    audit_canvas.bind("<Leave>", _hide_audit_tooltip)
    audit_toggle.bind("<Enter>", _audit_header_help)
    audit_toggle.bind("<Leave>", _hide_audit_tooltip)
    audit_summary.bind("<Enter>", _audit_header_help)
    audit_summary.bind("<Leave>", _hide_audit_tooltip)
    # Explain the event and repair-attempt denominators at the values
    # themselves, without adding a separate toolbar row.
    def _quality_ratio_help(event):
        _show_audit_tooltip(
            format_json_repair_metric_help(), event.x_root, event.y_root,
            "__quality_ratio__",
        )

    for label in (quality_summary, *_quality_help_labels):
        label.bind("<Enter>", _quality_ratio_help)
        label.bind("<Leave>", _hide_audit_tooltip)

    # Reuse the monitor-bounded Toplevel tooltip. The click still opens the
    # existing review window and never manipulates queue/source/sink state.
    recovery_button.bind(
        "<Enter>", lambda event: _show_audit_tooltip(
            _incident_tooltip_text, event.x_root, event.y_root,
            "__incident__:" + _incident_tooltip_text,
        ),
    )
    recovery_button.bind("<Leave>", _hide_audit_tooltip)
    recovery_button.bind("<FocusOut>", _hide_audit_tooltip)
    recovery_button.bind("<Button-1>", _hide_audit_tooltip)

    def _draw_audit_distribution():
        audit_canvas.delete("all")
        width = _audit_canvas_layout_width()
        height = _audit_canvas_layout_height()
        metrics = (_audit_stats.get("metrics", {}) or {})
        series = [
            ("input_tokens", "Input", "#2f6fed"),
            ("output_tokens", "Output", "#18864b"),
            ("elapsed_seconds", "Slice time", "#6b7280"),
            ("task_text_tokens", "Task text", "#7a4cc2"),
            ("context_usage_ratio", "Context %", "#b00020"),
            ("total_tok_per_s", "Total tok/s", "#007c91"),
            ("effective_tok_per_s_est", "Effective tok/s (est.)", "#bd6d14"),
        ]
        cell_h = height / 2
        for idx, (key, title, color) in enumerate(series):
            row = 0 if idx < 3 else 1
            cols = 3 if row == 0 else 4
            col = idx if row == 0 else idx - 3
            cell_w = width / cols
            x0, y0 = col * cell_w + 8, row * cell_h + 6
            x1, y1 = (col + 1) * cell_w - 8, (row + 1) * cell_h - 10
            snap = metrics.get(key, {}) or {}
            count = int(snap.get("count", 0) or 0)
            suffix = "%" if key == "context_usage_ratio" else "s" if key == "elapsed_seconds" else ""
            audit_canvas.create_text(
                x0, y0, anchor="nw", text=title,
                fill="#222222", font=("Segoe UI", 9, "bold")
            )
            if key == "effective_tok_per_s_est":
                provenance = (
                    f"n={count:,}  API={int(_audit_stats.get('effective_provider_rows', 0) or 0):,}"
                    f"  H={int(_audit_stats.get('effective_heuristic_rows', 0) or 0):,}"
                )
            else:
                provenance = f"n={count:,}"
            audit_canvas.create_text(
                x0, y0 + 17, anchor="nw", text=provenance,
                fill="#777777", font=("Segoe UI", 7),
            )
            if count:
                entries = (
                    f"P50 {_fmt_audit_number(snap.get('p50', 0))}{suffix}",
                    f"P95 {_fmt_audit_number(snap.get('p95', 0))}{suffix}",
                    f"max {_fmt_audit_number(snap.get('max', 0))}{suffix}",
                )
            else:
                entries = ("P50 unknown", "P95 unknown", "max unknown")
            for line_idx, line in enumerate(entries):
                audit_canvas.create_text(
                    x0, y0 + 33 + line_idx * 14, anchor="nw",
                    text=line, fill="#555555", font=("Segoe UI", 8),
                )
            top = y0 + 78
            bottom = max(top + 1, y1 - 18)
            audit_canvas.create_line(x0, bottom, x1, bottom, fill="#dddddd")
            histogram = tuple(snap.get("histogram", ()) or ())
            peak = max(histogram) if histogram else 0
            if peak <= 0 or len(histogram) < 2:
                audit_canvas.create_text(
                    (x0 + x1) / 2, (top + bottom) / 2,
                    text="waiting for data", fill="#999999", font=("Segoe UI", 8)
                )
                continue
            points = []
            for bucket_idx, bucket_value in enumerate(histogram):
                x = x0 + (x1 - x0) * bucket_idx / max(1, len(histogram) - 1)
                y = bottom - (bottom - top) * float(bucket_value) / float(peak)
                points.extend((x, y))
            audit_canvas.create_line(*points, fill=color, width=2, smooth=True)
            for tick in select_audit_axis_ticks(snap, x1 - x0, suffix):
                tx = x0 + tick["x"]
                audit_canvas.create_line(tx, bottom, tx, bottom + 3, fill="#aaaaaa")
                audit_canvas.create_text(
                    tx, bottom + 5, anchor="n", text=tick["label"],
                    fill="#777777", font=("Segoe UI", 7),
                )

    def _audit_canvas_resized(_event=None):
        if _audit_expanded:
            root.after_idle(_draw_audit_distribution)

    audit_canvas.bind("<Configure>", _audit_canvas_resized)

    def _resize_audit_summary_wrap(event):
        audit_summary.configure(wraplength=max(240, int(event.width) - 16))

    audit_section.bind("<Configure>", _resize_audit_summary_wrap)

    def _refresh_audit_header():
        arrow = "▼" if _audit_expanded else "▶"
        audit_toggle.configure(text=f"{arrow} LLM Token / Context Distribution ⓘ")
        audit_summary.configure(text=format_llm_audit_summary(_audit_stats))

    def _toggle_audit():
        nonlocal _audit_expanded
        _audit_expanded = not _audit_expanded
        if _audit_expanded:
            audit_frame.pack(fill="x")
            root.after_idle(_draw_audit_distribution)
        else:
            audit_frame.pack_forget()
        _refresh_audit_header()

    audit_toggle.configure(command=_toggle_audit)
    _refresh_audit_header()

    def _refresh_recheck_header():
        arrow = "▼" if _recheck_expanded else "▶"
        recheck_toggle.configure(
            text=f"{arrow} Recheck Status — {format_recheck_summary(_recheck_stats)}"
        )

    def _refresh_reduction_header():
        arrow = "▼" if _reduction_expanded else "▶"
        reduction_toggle.configure(
            text=f"{arrow} Reduction Status — {format_reduction_summary(_reduction_stats)}"
        )

    def _toggle_recheck():
        nonlocal _recheck_expanded
        _recheck_expanded = not _recheck_expanded
        if _recheck_expanded:
            recheck_frame.pack(fill="x")
        else:
            recheck_frame.pack_forget()
        _refresh_recheck_header()

    def _toggle_reduction():
        nonlocal _reduction_expanded
        _reduction_expanded = not _reduction_expanded
        if _reduction_expanded:
            reduction_frame.pack(fill="x")
        else:
            reduction_frame.pack_forget()
        _refresh_reduction_header()

    recheck_toggle.configure(command=_toggle_recheck)
    reduction_toggle.configure(command=_toggle_reduction)

    def _request_cancel():
        if not cancel_event.is_set():
            cancel_event.set()
        cancel_button.configure(state="disabled")
        cancel_status.configure(text="Cancellation requested")

    cancel_button = ttk.Button(reduction_controls, text="Cancel", command=_request_cancel)
    cancel_button.pack(side="right")
    _refresh_recheck_header()
    _refresh_reduction_header()

    _update_labels()

    # Per-document progress is collapsed by default. The child GUI process
    # reads its own run-scoped Meter off the Tk thread, only when expanded.
    # One worker at a time and one page of rows keep large SQL/ES runs usable.
    document_section = ttk.Frame(frm)
    document_section.pack(fill="x", pady=(0, 5))
    document_toggle = ttk.Button(document_section)
    document_toggle.pack(fill="x")
    _document_expanded = False
    _document_busy = False
    _document_last_refresh = 0.0
    _document_snapshot = {}
    _document_page = 0
    _document_snapshot_args = None
    _document_results = pyqueue.Queue(maxsize=1)
    _document_filter = tk.StringVar(value="目前處理")
    _document_query = tk.StringVar(value="")

    document_frame = ttk.Frame(document_section, padding=(5, 4))
    document_controls = ttk.Frame(document_frame)
    document_controls.pack(fill="x", pady=(0, 3))
    ttk.Label(document_controls, text="顯示：").pack(side="left")
    document_filter = ttk.Combobox(
        document_controls, state="readonly", width=11,
        textvariable=_document_filter, values=("目前處理", "異常", "全部"),
    )
    document_filter.pack(side="left", padx=(0, 7))
    ttk.Label(document_controls, text="查找列 ID：").pack(side="left")
    document_search = ttk.Entry(
        document_controls, width=15, textvariable=_document_query,
    )
    document_search.pack(side="left", padx=(0, 7))
    document_refresh = ttk.Button(document_controls, text="更新")
    document_refresh.pack(side="left")
    document_previous = ttk.Button(document_controls, text="上一頁")
    document_next = ttk.Button(document_controls, text="下一頁")
    document_next.pack(side="right")
    document_previous.pack(side="right", padx=(0, 5))
    document_page_label = ttk.Label(document_controls, text="第 1/1 頁")
    document_page_label.pack(side="right", padx=(0, 10))
    document_columns = (
        ("document", "列／文件 ID", 205),
        ("stage", "目前階段", 115),
        ("progress", "切片進度（非寫回進度）", 182),
        ("model_endpoint", "模型／端點 IP（已記錄）", 270),
        ("pending", "等待", 55),
        ("running", "執行", 55),
        ("updated", "最後更新", 91),
    )
    # ttk.Treeview default row height need not follow scaled Segoe UI font.
    # Font line metrics (after Tk DPI setup) preserve full glyph descent.
    document_style = ttk.Style()
    try:
        document_line_height = int(tkfont.nametofont("TkDefaultFont").metrics("linespace"))
    except (tk.TclError, ValueError, TypeError):
        document_line_height = 20
    document_style.configure(
        "DocumentProgress.Treeview", font="TkDefaultFont",
        rowheight=max(28, document_line_height + 10),
    )
    document_style.configure(
        "DocumentProgress.Treeview.Heading", font="TkHeadingFont",
        padding=(4, 5),
    )
    document_grid = ttk.Treeview(
        document_frame,
        columns=tuple(c[0] for c in document_columns),
        show="headings", height=9, selectmode="browse",
        style="DocumentProgress.Treeview",
    )
    # Heading text is DPI-scaled, so minima must be measured *after* Tk's
    # Windows DPI/font setup. The longest row content remains accessible via
    # selection details or horizontal scroll at genuinely narrow widths.
    try:
        heading_font = tkfont.nametofont("TkHeadingFont")
        document_mins = tuple(
            max(base, int(heading_font.measure(title_text)) + 18)
            for _col, title_text, base in document_columns
        )
    except (tk.TclError, ValueError, TypeError):
        document_mins = tuple(base for _col, _title, base in document_columns)
    for (col, title_text, _base), minimum in zip(document_columns, document_mins):
        document_grid.heading(col, text=title_text)
        document_grid.column(
            col, width=minimum, minwidth=minimum,
            anchor="w" if col in
            {"document", "stage", "progress", "model_endpoint"} else "center",
            stretch=False,
        )
    document_grid.tag_configure("error", foreground="#b00020")
    document_grid.tag_configure("running", foreground="#175b99")
    document_grid.pack(fill="x")
    # Keep the new evidence column accessible at narrower Windows DPI.
    document_xscroll = ttk.Scrollbar(
        document_frame, orient="horizontal", command=document_grid.xview,
    )
    document_grid.configure(xscrollcommand=document_xscroll.set)
    # Never leave a needless horizontal scrollbar when the columns fit.
    document_xscroll.pack_forget()
    _document_widths = None

    def _resize_document_columns(event=None):
        nonlocal _document_widths
        width = int(event.width) if event is not None else document_grid.winfo_width()
        if width <= 1:
            return
        widths, overflow = fit_document_column_widths(width, document_mins)
        if widths != _document_widths:
            for (col, _title, _base), target in zip(document_columns, widths):
                document_grid.column(col, width=target)
            _document_widths = widths
        if overflow:
            if not document_xscroll.winfo_manager():
                document_xscroll.pack(fill="x", after=document_grid)
        elif document_xscroll.winfo_manager():
            document_xscroll.pack_forget()

    document_grid.bind("<Configure>", _resize_document_columns)
    document_detail = ttk.Label(
        document_frame, foreground="#555",
        text="切片完成不等於已合併或 SQL/ES 寫回成功。每次只顯示目前頁。",
        wraplength=720,
    )
    document_detail.pack(anchor="w", pady=(4, 0))
    # One native ttk progress bar for whichever row the user selects;
    # all other rows remain lightweight progress glyphs inside Treeview.
    document_selected_label = ttk.Label(
        document_frame, text="點選一列可查看該工作切片進度", foreground="#444",
    )
    document_selected_label.pack(fill="x", pady=(5, 1))
    document_selected_bar = ttk.Progressbar(
        document_frame, maximum=100, value=0,
    )
    document_selected_bar.pack(fill="x", pady=(0, 3))

    def _document_selected(_event=None):
        sel = document_grid.selection()
        rows_now = _document_snapshot.get("shown", [])
        if not sel:
            document_selected_label.configure(
                text="點選一列可查看該工作切片進度"
            )
            document_selected_bar.configure(value=0)
            return
        try:
            idx = int(sel[0])
            row = rows_now[idx]
        except (ValueError, TypeError, IndexError, KeyError):
            document_selected_bar.configure(value=0)
            return
        count = row["done"]
        total = row["total"]
        if count is not None and total is not None and total > 0:
            pct = min(100, max(0, round(100 * count / total)))
        else:
            pct = 0
        document_selected_bar.configure(value=pct)
        document_selected_label.configure(
            text=f"列 {row['label']}｜{row['stage']}｜"
                 f"{row['progress']}｜模型／端點 {row['model_endpoint']}｜"
                 f"最後更新 {row['updated_text']}"
        )

    document_grid.bind("<<TreeviewSelect>>", _document_selected)

    def _document_header():
        arrow = "▼" if _document_expanded else "▶"
        if _document_snapshot:
            summary = (
                f"{_document_snapshot.get('all', 0)} 列｜"
                f"進行中 {_document_snapshot.get('active', 0)}｜"
                f"異常 {_document_snapshot.get('errors', 0)}"
            )
        else:
            summary = "展開查看每列的切片、合併與寫回狀態"
        document_toggle.configure(
            text=f"{arrow} 各列／文件進度 — {summary}",
        )

    def _request_document_snapshot(force=False):
        nonlocal _document_busy, _document_last_refresh, _document_snapshot_args
        if not _document_expanded or _document_busy:
            return
        now = time.monotonic()
        if not force and now - _document_last_refresh < 1.5:
            return
        args = (
            _recovery_meter_path, _document_filter.get(),
            _document_query.get().strip()[:100], _document_page,
            _audit_path,
        )
        _document_busy = True
        _document_last_refresh = now
        _document_snapshot_args = args
        def worker():
            from czjLLM.job_manager.document_progress import read_document_progress
            try:
                result = (True, read_document_progress(
                    args[0], mode=args[1], search=args[2],
                    page=args[3], audit_path=args[4],
                ))
            except Exception as exc:
                result = (False, type(exc).__name__)
            _document_results.put(result)
        threading.Thread(
            target=worker, daemon=True, name="row-progress-meter-reader",
        ).start()

    def _document_results_poll():
        nonlocal _document_busy, _document_snapshot, _document_page
        if not root.winfo_exists():
            return
        try:
            ok, result = _document_results.get_nowait()
        except pyqueue.Empty:
            pass
        else:
            _document_busy = False
            if ok:
                _document_snapshot = result
                _document_page = result["page"]
                if _document_expanded:
                    previous_selection = document_grid.selection()
                    old_key = ""
                    if previous_selection:
                        vals = document_grid.item(previous_selection[0], "values")
                        if vals:
                            old_key = str(vals[0])
                    children = document_grid.get_children()
                    if children:
                        document_grid.delete(*children)
                    restored_iid = None
                    for idx, item in enumerate(result["shown"]):
                        if item["label"] == old_key:
                            restored_iid = str(idx)
                        tag = ("error",) if item["error"] else (
                            ("running",) if (item["running"] or 0) else ()
                        )
                        document_grid.insert(
                            "", "end", iid=str(idx), tags=tag,
                            values=(
                                item["label"], item["stage"], item["progress"],
                                item["model_endpoint"], item["pending_text"],
                                item["running_text"],
                                item["updated_text"],
                            ),
                        )
                    if restored_iid is not None:
                        document_grid.selection_set(restored_iid)
                    _document_selected()
                    document_page_label.configure(
                        text=f"第 {result['page'] + 1}/{result['pages']} 頁"
                    )
                    document_previous.configure(
                        state="normal" if result["page"] > 0 else "disabled"
                    )
                    document_next.configure(
                        state="normal" if result["page"] + 1 < result["pages"]
                        else "disabled"
                    )
                    document_detail.configure(
                        text=(result.get("notice") or "")
                        + f"；顯示 {len(result['shown'])}/{result['matching']} 筆。"
                        + "切片100%≠寫回完成；模型／IP 僅顯示已記錄的 LLM Audit，"
                        + "並非未完成呼叫的即時端點；merged 非獨立 sink readback。"
                    )
                _document_header()
            else:
                document_detail.configure(
                    text=f"列進度暫無法讀取（{result}）。原始任務不受影響。"
                )
        if _document_expanded:
            _request_document_snapshot()
        root.after(250, _document_results_poll)

    def _toggle_document():
        nonlocal _document_expanded, _document_last_refresh
        _document_expanded = not _document_expanded
        if _document_expanded:
            document_frame.pack(fill="x")
            # Reclaim log request-height rather than creating two overflowing
            # scroll regions at 125%/150% Windows DPI; log remains available.
            txt.configure(height=6)
            width = max(760, root.winfo_width())
            height = min(max(690, root.winfo_height()),
                         max(500, root.winfo_screenheight() - 75))
            root.geometry(f"{width}x{height}")
            _document_last_refresh = 0
            _request_document_snapshot(force=True)
        else:
            document_frame.pack_forget()
            txt.configure(height=15)
        _document_header()

    def _document_page_delta(delta):
        nonlocal _document_page
        _document_page = max(0, _document_page + delta)
        _request_document_snapshot(force=True)

    def _document_change(_event=None):
        nonlocal _document_page
        _document_page = 0
        _request_document_snapshot(force=True)

    document_toggle.configure(command=_toggle_document)
    document_previous.configure(command=lambda: _document_page_delta(-1))
    document_next.configure(command=lambda: _document_page_delta(1))
    document_refresh.configure(command=lambda: _request_document_snapshot(force=True))
    document_filter.bind("<<ComboboxSelected>>", _document_change)
    document_search.bind("<Return>", _document_change)
    _document_header()
    root.after(250, _document_results_poll)

    txt = tk.Text(frm, height=15, wrap="word")
    scr = ttk.Scrollbar(frm, command=txt.yview)
    txt.configure(yscrollcommand=scr.set, font=("Consolas", 10), bg="white", fg="black",
                  insertbackground="black", spacing1=2, spacing2=1, spacing3=2)
    txt.pack(side="left", fill="both", expand=True)
    scr.pack(side="right", fill="y")

    def append(msg: str):
        if not msg:
            return
        txt.insert("end", msg.rstrip() + "\n")
        txt.see("end")

    def set_total(v: int):
        nonlocal _tot
        _tot = max(1, int(v))
        bar_done.configure(maximum=_tot)
        bar_sched.configure(maximum=_tot)
        bar_done["value"]  = min(bar_done["value"],  _tot)
        bar_sched["value"] = min(bar_sched["value"], _tot)
        _update_labels()

    def _shutdown():
        _quality_reader_stop.set()
        _audit_reader_stop.set()
        try:
            root.quit()
        except Exception:
            pass
        try:
            root.destroy()
        except Exception:
            pass

    root.protocol("WM_DELETE_WINDOW", _shutdown)

    # 事件輪詢：全部在 Tk 主緒
    def poll():
        nonlocal _tot, _done_cnt, _sched_cnt, _recheck_stats, _recheck_error_visible, _reduction_stats
        nonlocal _audit_stats, _audit_path, _quality_stats, _recovery_meter_path
        try:
            updated = False
            while True:
                evt, payload = q.get_nowait()
                if evt == _GuiEvents.INC_SCHED:
                    _maybe_boot_timer()
                    inc = int(payload or 1)
                    _sched_cnt = min(_sched_cnt + inc, _tot)
                    bar_sched["value"] = _sched_cnt
                    updated = True
                elif evt == _GuiEvents.INC_DONE:
                    _maybe_boot_timer()
                    inc = int(payload or 1)
                    _done_cnt = min(_done_cnt + inc, _tot)
                    bar_done["value"] = _done_cnt
                    _accumulate_rate(inc)
                    updated = True
                elif evt == _GuiEvents.LOG:
                    append(str(payload))
                elif evt == _GuiEvents.SET_TOTAL:
                    set_total(int(payload)); updated = True
                elif evt == _GuiEvents.RECHECK:
                    _recheck_stats = dict(payload or {})
                    has_error = recheck_status_is_error(_recheck_stats)
                    lbl_recheck.configure(
                        text=format_recheck_stats(_recheck_stats),
                        foreground="#b00020" if has_error else "#333333",
                    )
                    _refresh_recheck_header()
                    _refresh_incident_button()
                    if has_error and not _recheck_error_visible:
                        append(f"⚠️ Pending recheck errors: {_recheck_stats.get('errors', 0)}")
                    _recheck_error_visible = has_error
                elif evt == _GuiEvents.REDUCTION:
                    _reduction_stats = dict(payload or {})
                    lbl_reduction.configure(
                        text=format_reduction_stats(_reduction_stats),
                        foreground="#b00020" if reduction_status_is_error(_reduction_stats) else "#333333",
                    )
                    _refresh_reduction_header()
                    _refresh_incident_button()
                    if _reduction_stats.get("run_status") == "cancelled":
                        cancel_status.configure(text="Cancelled / safely drained")
                        cancel_button.configure(state="disabled")
                elif evt == _GuiEvents.QUALITY_PATH:
                    try:
                        while True:
                            _quality_path_queue.get_nowait()
                    except pyqueue.Empty:
                        pass
                    try:
                        _quality_path_queue.put_nowait(str(payload or ""))
                    except pyqueue.Full:
                        pass
                elif evt == _GuiEvents.RECOVERY_METER:
                    _recovery_meter_path = str(payload or "")
                elif evt == _GuiEvents.AUDIT_PATH:
                    _audit_path = str(payload or "")
                    try:
                        while True:
                            _audit_path_queue.get_nowait()
                    except pyqueue.Empty:
                        pass
                    try:
                        _audit_path_queue.put_nowait(_audit_path)
                    except pyqueue.Full:
                        pass
                elif evt == _GuiEvents.CLOSE:
                    _shutdown(); return
        except pyqueue.Empty:
            pass

        quality_updated = False
        try:
            while True:
                _quality_stats = _quality_result_queue.get_nowait()
                quality_updated = True
        except pyqueue.Empty:
            pass
        if quality_updated:
            _refresh_quality()

        audit_updated = False
        try:
            while True:
                _audit_stats = _audit_result_queue.get_nowait()
                audit_updated = True
        except pyqueue.Empty:
            pass
        if audit_updated:
            _refresh_audit_header()
            if _audit_expanded:
                _draw_audit_distribution()

        if updated or _t0 is not None:
            _update_labels()

        root.after(200, poll)  # 200ms 更新一次即可

    root.after(100, poll)
    try:
        root.mainloop()
    except Exception:
        pass


# ---------- 主行程：薄客戶端（丟訊息而已） ----------

class _GUIClient:
    def __init__(self, q: "mp.Queue", proc: "mp.Process", cancel_event=None):
        self._q = q
        self._proc = proc
        self._cancel_event = cancel_event

    def inc_sched(self, n: int = 1): self._q.put((_GuiEvents.INC_SCHED, n))
    def inc_done(self,  n: int = 1): self._q.put((_GuiEvents.INC_DONE,  n))
    def log(self, text: str):        self._q.put((_GuiEvents.LOG, text))
    def set_total(self, total: int): self._q.put((_GuiEvents.SET_TOTAL, int(total)))
    def update_recheck_stats(self, stats: dict): self._q.put((_GuiEvents.RECHECK, dict(stats)))
    def update_reduction_stats(self, stats: dict, final: bool = False):
        self._q.put((_GuiEvents.REDUCTION, dict(stats)))
    def set_audit_path(self, audit_path: str):
        self._q.put((_GuiEvents.AUDIT_PATH, str(audit_path or "")))
    def set_quality_event_path(self, path: str):
        self._q.put((_GuiEvents.QUALITY_PATH, str(path or "")))
    def set_recovery_meter_path(self, path: str):
        self._q.put((_GuiEvents.RECOVERY_METER, str(path or "")))
    def cancellation_requested(self) -> bool:
        return bool(self._cancel_event is not None and self._cancel_event.is_set())

    def close(self):
        try:
            self._q.put((_GuiEvents.CLOSE, None))
        except Exception:
            pass
        if self._proc.is_alive():
            self._proc.join(timeout=5.0)

# 對外：Windows 才啟動 GUI；失敗則回 None（不影響主流程）
def try_start_gui(total: int, title: str = "LLM 分析進度（Windows GUI）"):
    if not IS_WIN:
        return None
    try:
        ctx = mp.get_context("spawn")  # Windows 安全模式
        q = ctx.Queue()
        cancel_event = ctx.Event()
        p = ctx.Process(target=_gui_proc_main, args=(q, cancel_event, int(total), title), daemon=False)
        p.start()
        return _GUIClient(q, p, cancel_event)
    except Exception as ex:
        #print(ex)
        return None

# 提供 sink：把 console/log 訊息同步到 GUI（仍建議用在 Windows）
def make_gui_sink(gui: _GUIClient):
    def sink(level: str, message: str):
        try:
            prefix = {"ERROR": "[ERR] ", "WARN": "[WARN] ", "OK": "[OK] ", "INFO": ""}.get(level, "")
            gui.log(prefix + message)
        except Exception:
            pass
    return sink
