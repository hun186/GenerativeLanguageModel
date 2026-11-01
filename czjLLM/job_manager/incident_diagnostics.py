"""Bounded, read-only diagnostic evidence for operator clipboard sharing.

The packet separates per-item direct evidence from run-scoped context.
Missing correlations are *not* invented. No prompts, sink payloads, request
URLs, credentials, raw exceptions, primary keys or full logs are exported.
"""
from __future__ import annotations

import csv
from datetime import datetime, timezone
import json
import os
import platform
import re
import stat
import sys
from pathlib import Path

from czjLLM.prompt_pipeline.runtime_support.prompt_queue import (
    QueueClaimRollbackError, read_recovery_record,
)
from czjLLM.job_manager.recovery_review import (
    _read_action_history, format_incident_debug_report, MAX_DEBUG_ITEMS,
)

MAX_AUDIT_BYTES = 2_000_000
MAX_QUALITY_BYTES = 1_000_000
MAX_QUALITY_EVENTS = 12
MAX_ACTIONS = 12
MAX_ROLE_ENTRIES = 1000
_SAFE_MODEL = re.compile(r"^[A-Za-z0-9_.:/+-]{1,100}$")
_SAFE_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d\d:\d\d)$")
_EVENT_CODES = {
    "consumer_orchestration_failure": {
        "CONSUMER_ROUND_TIMEOUT", "CONSUMER_ROUND_EXCEPTION", "CONSUMER_TERMINATED"},
    "row_merger_retryable_failure": {
        "ROW_MERGER_PREPARE_RETRY", "ROW_MERGER_WRITEBACK_RETRY"},
    "producer_operational_failure": {
        "PRODUCER_SCHEDULE_EXCEPTION", "PRODUCER_BACKPRESSURE_EXCEPTION",
        "PRODUCER_FUTURE_EXCEPTION"},
    "stage_orchestration_failure": {"STAGE_PREPARE_EXCEPTION", "STAGE_RUNNER_EXCEPTION"},
    "worker_phase_failure": {
        "WORKER_PRECALL_EXCEPTION", "WORKER_LLM_CALL_EXCEPTION",
        "WORKER_RESPONSE_EXCEPTION", "WORKER_PERSIST_EXCEPTION",
        "WORKER_LLM_TIMEOUT_EXCEPTION", "WORKER_LLM_CONNECTION_EXCEPTION",
        "WORKER_LLM_RATE_LIMIT_EXCEPTION", "WORKER_LLM_HTTP_SERVER_EXCEPTION",
        "WORKER_LLM_HTTP_CLIENT_EXCEPTION",
        "WORKER_LLM_RESPONSE_VALIDATION_EXCEPTION"},
    "queue_recovery": {"VERIFIED_EXISTING_TODO", "OPERATOR_ACTION_REQUIRED"},
}


def _clock(ts):
    if type(ts) not in (int, float) or not 946684800 <= ts <= 4102444800:
        return "未記錄"
    try:
        return datetime.fromtimestamp(ts, timezone.utc).isoformat().replace("+00:00", "Z")
    except (OverflowError, ValueError, OSError):
        return "未記錄"


def _number(value):
    if isinstance(value, bool):
        return "未記錄"
    try:
        n = float(value)
        if n < 0 or n > 10**10 or n != n or n == float("inf"):
            return "未記錄"
        return str(int(n)) if n.is_integer() else f"{n:.2f}"
    except (TypeError, ValueError, OverflowError):
        return "未記錄"


def _safe_model(value):
    if not isinstance(value, str) or not _SAFE_MODEL.fullmatch(value):
        return None
    if any(part in value.lower() for part in ("sk-", "password", "secret", "token=", "api_key", "apikey")):
        return None
    return value


def _regular_file(path, max_bytes):
    """Reject symlink ancestors and nonregular files; do not read oversized."""
    p = Path(path)
    if any(q.is_symlink() for q in (p, *p.parents)):
        return False
    try:
        st = p.lstat()
        return stat.S_ISREG(st.st_mode) and st.st_size <= max_bytes
    except OSError:
        return False


def _read_meter(meter_path):
    if not meter_path:
        return {}, "未提供"
    if not _regular_file(meter_path, 2_000_000):
        return {}, "不存在／超過 2MB／路徑不安全"
    try:
        from czjLLM.prompt_pipeline.runtime_support.load_meter import meter_read
        m = meter_read(str(meter_path))
        return (m, "已讀取") if isinstance(m, dict) else ({}, "內容不正確")
    except (OSError, ValueError, TypeError, KeyError):
        return {}, "讀取失敗"


def _item_meter_row(meter, item_dir):
    rows = meter.get("rows", {})
    if not isinstance(rows, dict):
        return {}
    # Unique exact path match; NEVER infer the row from integer/string PK.
    matched = [r for r in rows.values() if
               isinstance(r, dict) and r.get("item_dir") == str(item_dir)]
    return matched[0] if len(matched) == 1 else {}


def _role_state(item_dir, role):
    root = Path(item_dir)
    if any(p.is_symlink() for p in (root, *root.parents)):
        return "不安全路徑，未掃描"
    p = root / role
    try:
        st = p.lstat()
        if not stat.S_ISDIR(st.st_mode):
            return "不是正常目錄（未讀取）"
        count = 0
        with os.scandir(p) as entries:
            for child in entries:
                count += 1
                if count > MAX_ROLE_ENTRIES:
                    return "頂層項目超過安全上限，未完整掃描"
                if child.is_symlink():
                    return "包含連結，未完整掃描"
        return f"存在；頂層項目數={count}（非遞迴計數）"
    except FileNotFoundError:
        return "不存在"
    except OSError:
        return "讀取失敗"


def _audit_context(audit_path, selected_items=()):
    """Run-wide aggregate ONLY, not item-specific evidence."""
    if not audit_path:
        return {"status": "未提供"}
    if not _regular_file(audit_path, MAX_AUDIT_BYTES):
        return {"status": "不存在／超過 2MB／路徑不安全"}
    try:
        selected = {
            str(path): [] for path in selected_items
            if isinstance(path, str) and path
        }
        with open(audit_path, "r", encoding="utf-8", newline="") as fp:
            reader = csv.DictReader(fp)
            calls = errors = 0
            in_tokens = out_tokens = 0.
            elapsed = 0.
            measured = 0
            models = set()
            for row in reader:
                if not isinstance(row, dict):
                    continue
                calls += 1
                if calls > 10000:
                    return {"status": "超過 10000 筆安全上限"}
                model = _safe_model(row.get("model"))
                # Match path containment by directory boundary rather than
                # naive prefix (job/1 must never match job/10).
                prompt_file = row.get("prompt_file")
                matched = []
                if isinstance(prompt_file, str) and prompt_file:
                    try:
                        full_prompt = os.path.normcase(os.path.abspath(prompt_file))
                        for item_path in selected:
                            root = os.path.normcase(os.path.abspath(item_path))
                            if os.path.commonpath((root, full_prompt)) == root:
                                matched.append(item_path)
                    except (ValueError, OSError):
                        matched = []
                if len(matched) == 1:
                    target = selected[matched[0]]
                    attempt_time = next((
                        value for value in (
                            row.get("timestamp"), row.get("start_time"),
                            row.get("time_iso"),
                        ) if isinstance(value, str) and
                        _SAFE_ISO.fullmatch(value)
                    ), "未記錄")
                    item_attempt = {
                        "time_utc": attempt_time,
                        "model": model or "未記錄",
                        "ok": row.get("ok") if row.get("ok") in {"YES", "NO"} else "未記錄",
                        "elapsed_s": _number(row.get("elapsed_seconds")),
                        "input_tokens": _number(row.get("input_tokens")),
                        "output_tokens": _number(row.get("output_tokens")),
                    }
                    target.append(item_attempt)
                    if len(target) > 10:
                        target.pop(0)
                if model and len(models) < 5:
                    models.add(model)
                if str(row.get("ok") or "").strip().upper() == "NO":
                    errors += 1
                i = _number(row.get("input_tokens"))
                o = _number(row.get("output_tokens"))
                e = _number(row.get("elapsed_seconds"))
                if i != "未記錄":
                    in_tokens += float(i)
                if o != "未記錄":
                    out_tokens += float(o)
                if e != "未記錄":
                    elapsed += float(e)
                    measured += 1
            return {"status": "已讀取（整次 Run，非指定 item）",
                    "calls": calls, "failed_rows": errors,
                    "models": sorted(models), "in_tokens": int(in_tokens),
                    "out_tokens": int(out_tokens),
                    "elapsed_sum_s": round(elapsed, 2),
                    "elapsed_sample_count": measured,
                    "item_attempts": selected}
    except (OSError, ValueError, UnicodeError, csv.Error, TypeError):
        return {"status": "讀取失敗"}


def _quality_context(audit_path):
    """Run-scoped recent fixed-code events; NEVER attribute to one item."""
    if not audit_path:
        return {"status": "未提供", "events": []}
    from czjLLM.utilities.processing_quality import quality_event_path
    path = quality_event_path(str(audit_path))
    if not path or not _regular_file(path, MAX_QUALITY_BYTES):
        return {"status": "不存在／超過 1MB／路徑不安全", "events": []}
    events = []
    try:
        with open(path, "r", encoding="utf-8") as file:
            for n, line in enumerate(file):
                if n >= 10000:
                    return {"status": "超過 10000 行安全上限", "events": []}
                if len(line) > 16384:
                    return {"status": "存在過長行，拒絕輸出", "events": []}
                rec = json.loads(line)
                if not isinstance(rec, dict) or rec.get("scope") != "run":
                    continue
                kind = rec.get("event")
                if kind not in _EVENT_CODES or rec.get("code") not in _EVENT_CODES[kind]:
                    continue
                timestamp = rec.get("ts")
                events.append({
                    "time_utc": timestamp if isinstance(timestamp, str)
                    and _SAFE_ISO.fullmatch(timestamp) else "未記錄",
                    "event": kind, "code": rec["code"],
                })
                if len(events) > MAX_QUALITY_EVENTS:
                    events.pop(0)
        return {"status": "已讀取；僅顯示 Run 範圍事件", "events": events}
    except (ValueError, TypeError, OSError, UnicodeError):
        return {"status": "證據格式異常，未輸出", "events": []}


def _marker_context(item_dir):
    try:
        return read_recovery_record(item_dir) or {}, "正常讀取"
    except (QueueClaimRollbackError, ValueError, OSError):
        return {}, "復原標記不可讀，請人工檢查"


def _action_timeline(item_dir):
    try:
        records = _read_action_history(item_dir)
        return [{"time_utc": _clock(a.get("ts")), "action": a.get("action")}
                for a in records[-MAX_ACTIONS:]
                if isinstance(a, dict) and a.get("action") in {
                    "resolved", "ignored", "deleted", "open"}], "已讀取"
    except (QueueClaimRollbackError, OSError, ValueError):
        return [], "檢閱歷史不可讀"


def build_detailed_debug_report(incidents, *, meter_path=None,
                                audit_path=None, include_paths=False):
    """Collect and format bounded current evidence for copy on a WORKER thread.

    Additional local paths require explicit operator opt-in. Never upload.
    """
    incidents = list(incidents)
    if not 1 <= len(incidents) <= MAX_DEBUG_ITEMS:
        raise ValueError("debug report requires 1..100 incidents")
    meter, meter_status = _read_meter(meter_path)
    audit = _audit_context(audit_path, [
        item.get("item_dir") for item in incidents if isinstance(item, dict)
    ])
    quality = _quality_context(audit_path)
    q = meter.get("queue", {}) if isinstance(meter.get("queue"), dict) else {}
    timing = meter.get("progress", {}) if isinstance(meter.get("progress"), dict) else {}
    run_id = meter.get("session_run_id") if isinstance(meter.get("session_run_id"), str) else None
    # Run IDs may be arbitrary in a modified meter. Use opaque hash rather than
    # raw IDs (and never print PK, user filename or session paths).
    import hashlib
    run_ref = "sha256:" + hashlib.sha256(run_id.encode("utf-8")).hexdigest()[:16] if run_id else "未記錄"
    lines = [
        format_incident_debug_report(incidents).rstrip(),
        "",
        "# 詳細補充證據（唯讀快照）",
        f"採集時間（UTC）：{datetime.now(timezone.utc).isoformat()}",
        f"系統：{platform.system()} {platform.release()}",
        f"Python：{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        "Commit SHA：未由此介面驗證（請另附當前 Git commit）",
        f"Meter：{meter_status}",
        f"Run 識別摘要：{run_ref}",
        "執行模式／任務名稱：未記錄或不在安全診斷欄位",
        "模型呼叫對應單一 item：未證明（下列為整個 Run 的聚合資訊）",
        "來源時間欄位：UTC；需轉換本地時間請依時間戳處理",
        "整次 Run Queue：pending=" + _number(q.get("pending"))
            + " running=" + _number(q.get("running"))
            + " completed=" + _number(q.get("completed")),
        "最後計量進度（UTC）：" + _clock(timing.get("last_progress_ts")),
        "",
        "# LLM 呼叫：Run 範圍聚合，非此異常的呼叫",
        "Audit 狀態：" + audit["status"],
    ]
    for name, label in (
        ("models", "模型名稱"), ("calls", "Audit 記錄筆數"),
        ("failed_rows", "Audit 回傳失敗筆數"),
        ("in_tokens", "輸入 Token 合計（有記錄欄位）"),
        ("out_tokens", "輸出 Token 合計（有記錄欄位）"),
        ("elapsed_sum_s", "有記錄呼叫耗時合計（秒）"),
    ):
        if name in audit:
            val = audit[name]
            lines.append(f"{label}：" + (", ".join(val) if isinstance(val, list)
                                          else str(val)))
    lines += ["", "# Run 範圍關鍵事件（不能直接歸因於單筆工作）",
              "Quality Stream：" + quality["status"]]
    for ev in quality["events"]:
        lines.append(f"- {ev['time_utc']} | {ev['event']} | {ev['code']}")
    if not quality["events"]:
        lines.append("- 無可讀取的 Run 範圍事件")

    for idx, item in enumerate(incidents, 1):
        if not isinstance(item, dict):
            item = {}
        path = item.get("item_dir")
        lines += ["", f"# 工作項目 #{idx} 的直接證據"]
        if not isinstance(path, str) or not path:
            lines.append("工作目錄：未記錄")
            continue
        lines.append("工作目錄：" + (
            path.replace("\n", "[NL]").replace("\r", "[CR]")[:512]
            if include_paths else "已隱藏（可手動勾選包含本機路徑）"))
        record, marker_status = _marker_context(path)
        row = _item_meter_row(meter, path)
        lines.extend([
            "復原狀態檔：" + marker_status,
            "首次異常（UTC）：" + _clock(record.get("first_seen_ts")),
            "最近復查（UTC）：" + _clock(record.get("last_check_ts")),
            "下次預定復查（UTC）：" + _clock(record.get("next_check_ts")),
            "初次移動嘗試次數：" + _number(record.get("attempts")),
            "復查狀態：" + (record.get("recheck_state")
                           if record.get("recheck_state") in {
                               "scheduled", "candidate", "resolved",
                               "operator_required"} else "未記錄"),
            "復原結果：" + (record.get("resolution")
                           if record.get("resolution") == "VERIFIED_EXISTING_TODO"
                           else "未記錄"),
            "Queue 待處理計數：" + _number(row.get("queue_pending")),
            "Queue 執行中計數：" + _number(row.get("queue_running")),
            "工作完成切片數：" + _number(row.get("done")),
            "工作切片總數：" + _number(row.get("total")),
            "TODO：" + _role_state(path, "TODO"),
            "RUNNING：" + _role_state(path, "RUNNING"),
            "Success：" + _role_state(path, "Success"),
            "SQL／ES 寫回回執：未直接取得；不得將 Success 當成確認寫回",
        ])
        history, history_status = _action_timeline(path)
        attempts = audit.get("item_attempts", {}).get(path, [])
        lines.append("LLM 呼叫（僅以 Audit prompt_file 在此工作目錄下關聯）：")
        if attempts:
            for call in attempts:
                lines.append(
                    "- " + call["time_utc"] + " | model=" + call["model"]
                    + " | ok=" + call["ok"]
                    + " | elapsed_s=" + call["elapsed_s"]
                    + " | in=" + call["input_tokens"]
                    + " | out=" + call["output_tokens"]
                    + "；尚未確認 provider 單次請求／重試身分"
                )
        else:
            lines.append("- 未找到具工作目錄關聯的 Audit 列（不代表沒有呼叫）")
        lines.append("檢閱處置歷史：" + history_status)
        for ev in history:
            lines.append(f"- {ev['time_utc']} | {ev['action']}")
        if not history:
            lines.append("- 未記錄")
        lines.append(
            "處理過程完整度：以上僅為現存標記、Meter、操作紀錄與檔案"
            "頂層狀態；未保存的逐步動作、個別 LLM 呼叫時間/錯誤不可推論。"
        )
    lines += ["",
              "# 請 ChatGPT 優先檢查",
              "1. 依時間和階段建立事件假說，明確區分已證實與推測。",
              "2. 指出缺少的關鍵資料（例如單筆 LLM attempt ID、例外類型、"
              "SQL/ES sink acknowledgment），提出安全的補證方法。",
              "3. 不清空 Queue/Success、不覆寫 TODO/RUNNING，未核實下游寫回"
              "前不重新送出可能重複的資料。",
              "4. 不要把 Run 範圍的模型呼叫或 Quality 事件當作此筆 item 的因果證據。",
              ]
    return "\n".join(lines) + "\n"
