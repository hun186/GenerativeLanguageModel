#!/usr/bin/env python3
"""Bounded read-only LLM dispatch snapshot. Never prints private source fields."""
from __future__ import annotations

import argparse
import csv
from datetime import datetime
import io
import json
import math
import os
from pathlib import Path
import stat
import sys
import time

REPARSE = 0x400
MAX_JSON = 4 * 1024 * 1024
MAX_CSV = 16 * 1024 * 1024
MAX_FILES = 512
MAX_ROWS = 30000
MAX_ENDPOINTS = 64
MAX_LEASES = 4096


class Unavailable(ValueError):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


def _unsafe(st):
    return stat.S_ISLNK(st.st_mode) or bool(
        getattr(st, "st_file_attributes", 0) & REPARSE
    )


def _safe_dir(p):
    try:
        s = p.lstat()
    except OSError:
        raise Unavailable("MISSING") from None
    if _unsafe(s) or not stat.S_ISDIR(s.st_mode):
        raise Unavailable("UNSAFE_PATH")


def _read(p, limit):
    try:
        old = p.lstat()
        if _unsafe(old) or not stat.S_ISREG(old.st_mode):
            raise Unavailable("UNSAFE_PATH")
        if old.st_size > limit:
            raise Unavailable("SIZE_LIMIT")
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
        fd = os.open(p, flags)
        with os.fdopen(fd, "rb") as f:
            opened = os.fstat(f.fileno())
            if (not stat.S_ISREG(opened.st_mode) or
                    (opened.st_dev, opened.st_ino) != (old.st_dev, old.st_ino)):
                raise Unavailable("CHANGED_DURING_READ")
            data = f.read(limit + 1)
            end = os.fstat(f.fileno())
        new = p.lstat()
        if _unsafe(new) or not stat.S_ISREG(new.st_mode):
            raise Unavailable("CHANGED_DURING_READ")
        identity = lambda x: (x.st_dev, x.st_ino, x.st_size, x.st_mtime_ns)
        if identity(old) != identity(opened) or identity(old) != identity(end) or identity(old) != identity(new):
            raise Unavailable("CHANGED_DURING_READ")
        if len(data) != old.st_size or len(data) > limit:
            raise Unavailable("SIZE_LIMIT")
        return data
    except Unavailable:
        raise
    except FileNotFoundError:
        raise Unavailable("MISSING") from None
    except (OSError, ValueError):
        raise Unavailable("READ_FAILED") from None


def _latest(folder, prefix, suffix):
    _safe_dir(folder)
    candidates = []
    try:
        with os.scandir(folder) as it:
            for index, entry in enumerate(it, 1):
                if index > MAX_FILES:
                    raise Unavailable("ENTRY_LIMIT")
                if entry.name.startswith(prefix) and entry.name.endswith(suffix):
                    s = entry.stat(follow_symlinks=False)
                    if _unsafe(s) or not stat.S_ISREG(s.st_mode):
                        raise Unavailable("UNSAFE_PATH")
                    candidates.append((s.st_mtime_ns, entry.name))
    except Unavailable:
        raise
    except OSError:
        raise Unavailable("READ_FAILED") from None
    if not candidates:
        raise Unavailable("MISSING")
    return folder / max(candidates)[1]


def _json(p):
    try:
        x = json.loads(_read(p, MAX_JSON).decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        raise Unavailable("MALFORMED") from None
    if not isinstance(x, dict):
        raise Unavailable("MALFORMED")
    return x


def _count(x, limit=100000000):
    if type(x) is not int or x < 0 or x > limit:
        raise Unavailable("MALFORMED")
    return x


def _time(x):
    if type(x) not in (int, float) or not math.isfinite(x) or x <= 0 or x >= 1e12:
        return None
    return float(x)


def _age(stamp, now):
    return max(0, int(now - stamp)) if stamp is not None else None


def _meter(logs, now):
    data = _json(_latest(logs, "loadmeter_", ".json"))
    q = data.get("queue")
    if not isinstance(q, dict):
        raise Unavailable("MALFORMED")
    workers = data.get("workers")
    width = workers.get("n_process") if isinstance(workers, dict) else None
    if width is not None:
        width = _count(width, 100000) or None
    consumer = data.get("consumer")
    round_ts = _time(consumer.get("last_round_ts")) if isinstance(consumer, dict) else None
    return {
        "status": "OBSERVED",
        "pending": _count(q.get("pending")), "running": _count(q.get("running")),
        "completed": _count(q.get("completed", 0)),
        "configured_worker_width": width,
        "last_round_completion_age_seconds": _age(round_ts, now),
        "warning": "METER_NOT_GPU_OR_HTTP_AUTHORITY",
    }


def _load(logs, now):
    data = _json(logs / "base_url_load.json")
    if len(data) > MAX_ENDPOINTS:
        raise Unavailable("ENDPOINT_LIMIT")
    labels, items = {}, []
    for i, url in enumerate(sorted(data), 1):
        record = data[url]
        if not isinstance(url, str) or not isinstance(record, dict):
            raise Unavailable("MALFORMED")
        raw = record.get("leases")
        if not isinstance(raw, list) or len(raw) > MAX_LEASES:
            raise Unavailable("LEASE_LIMIT")
        timestamps = [_time(x) for x in raw]
        if any(x is None for x in timestamps):
            raise Unavailable("MALFORMED")
        label = f"endpoint_{i:02d}"
        labels[url] = label
        items.append({
            "id": label,
            "active_lease_count": sum(x > now for x in timestamps),
            "expired_lease_count": sum(x <= now for x in timestamps),
            "last_state_update_age_seconds": _age(_time(record.get("last_update")), now),
        })
    return {
        "status": "OBSERVED", "endpoint_count": len(items),
        "active_leases_total": sum(x["active_lease_count"] for x in items),
        "expired_leases_total": sum(x["expired_lease_count"] for x in items),
        "endpoints": items,
        "warning": "TTL_LEASE_NOT_CONFIRMED_HTTP_INFLIGHT",
    }, labels


def _audit(logs, labels, now, window):
    file = _latest(logs / "llm_call_audit", "llm_call_audit_", ".csv")
    try:
        text = _read(file, MAX_CSV).decode("utf-8-sig")
        # An interrupted append may leave a stable, unterminated final row.
        # Never count it as a completed Worker call merely because the file
        # metadata stayed unchanged during this read.
        if not text.endswith("\n"):
            raise Unavailable("INCOMPLETE")
        reader = csv.DictReader(io.StringIO(text, newline=""), strict=True)
        required = {"timestamp", "base_url", "ok", "call_llm_api_returned"}
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            raise Unavailable("SCHEMA_MISMATCH")
        rows = recent = passed = failed = returned = invalid = other = 0
        latest = None
        per_endpoint = {v: {"audit_rows": 0, "ok_rows": 0} for v in labels.values()}
        for row in reader:
            # DictReader otherwise fills missing columns with None and puts
            # extra columns under a None key, silently accepting a torn row.
            if None in row or any(value is None for value in row.values()):
                raise Unavailable("INCOMPLETE")
            rows += 1
            if rows > MAX_ROWS:
                raise Unavailable("ROW_LIMIT")
            try:
                stamp = datetime.fromisoformat(row.get("timestamp", ""))
                if stamp.tzinfo is None:
                    raise ValueError("naive timestamp")
                ts = stamp.timestamp()
                if not math.isfinite(ts):
                    raise ValueError("non-finite timestamp")
            except (TypeError, ValueError, OverflowError):
                invalid += 1
                continue
            if not now - window <= ts <= now + 30:
                continue
            recent += 1
            latest = max(ts, latest) if latest is not None else ts
            passed += row.get("ok") == "YES"
            failed += row.get("ok") == "NO"
            returned += row.get("call_llm_api_returned") == "YES"
            label = labels.get(row.get("base_url"))
            if label is None:
                other += 1
            else:
                per_endpoint[label]["audit_rows"] += 1
                per_endpoint[label]["ok_rows"] += row.get("ok") == "YES"
    except Unavailable:
        raise
    except csv.Error:
        raise Unavailable("INCOMPLETE") from None
    except (UnicodeError, TypeError, ValueError):
        raise Unavailable("MALFORMED") from None
    return {
        "status": "INCOMPLETE" if invalid else "OBSERVED",
        "window_seconds": window, "recent_completed_audit_rows": recent,
        "recent_ok_rows": passed, "recent_failed_rows": failed,
        "recent_wrapper_returned_rows": returned,
        "invalid_timestamp_rows": invalid, "unknown_endpoint_rows": other,
        "last_audit_completion_age_seconds": _age(latest, now),
        "by_endpoint": per_endpoint,
        "warning": "POSTPROCESS_COMPLETION_AUDIT_NOT_DISPATCH_OR_SINK_ACK",
    }


def snapshot(logs: Path, *, now=None, window=900):
    now = time.time() if now is None else float(now)
    result = {
        "schema_version": 1, "diagnosis_status": "UNVERIFIED",
        "root_cause_status": "NOT_DETERMINED",
        "gpu_utilization_status": "NOT_OBSERVED",
        "http_inflight_status": "NOT_OBSERVED",
        "sources": {}, "signals": [],
    }
    try:
        _safe_dir(logs)
    except Unavailable as e:
        result["sources"] = {k: {"status": e.code} for k in ("meter", "load", "audit")}
        return result
    labels = {}
    for name, reader in (
        ("meter", lambda: _meter(logs, now)),
        ("load", lambda: _load(logs, now)),
        ("audit", lambda: _audit(logs, labels, now, window)),
    ):
        try:
            value = reader()
            if name == "load":
                value, labels = value
            result["sources"][name] = value
        except Unavailable as e:
            result["sources"][name] = {"status": e.code}
    meter, load, audit = (result["sources"][k] for k in ("meter", "load", "audit"))
    if meter["status"] == "OBSERVED":
        if meter["pending"] and not meter["running"]:
            result["signals"].append("PENDING_WITHOUT_RUNNING")
        if (meter["pending"] and meter["running"] and meter["configured_worker_width"]
                and meter["running"] < meter["configured_worker_width"]):
            result["signals"].append("POSSIBLE_BATCH_TAIL_OR_DISPATCH_GAP")
        age = meter["last_round_completion_age_seconds"]
        if meter["pending"] and age is not None and age >= 300:
            result["signals"].append("LAST_ROUND_COMPLETION_OLD")
    if load["status"] == "OBSERVED":
        if load["expired_leases_total"]:
            result["signals"].append("EXPIRED_LEASE_RECORDS_UNCLEANED")
        if meter["status"] == "OBSERVED" and meter["running"] and not load["active_leases_total"]:
            result["signals"].append("RUNNING_WITHOUT_ACTIVE_LEASE")
    if (audit["status"] == "OBSERVED" and meter["status"] == "OBSERVED"
            and meter["pending"] and not audit["recent_completed_audit_rows"]):
        result["signals"].append("PENDING_WITH_NO_RECENT_COMPLETION_AUDIT")
    if all(result["sources"][k]["status"] == "OBSERVED" for k in ("meter", "load", "audit")):
        result["diagnosis_status"] = "OBSERVED_NOT_PROVEN"
    return result



# Only fields generated by snapshot() are rendered. Never echo raw file
# contents, directory paths, URLs, run identity, PKs or exception details.
_SOURCE_LABELS = {"meter": "Queue 計量", "load": "端點負載租約", "audit": "LLM 完成稽核"}
_SOURCE_STATES = {
    "OBSERVED": "已讀取（非實機驗收）",
    "INCOMPLETE": "紀錄不完整",
    "MISSING": "找不到資料",
    "UNSAFE_PATH": "不安全的路徑或連結",
    "SIZE_LIMIT": "超出檔案大小限制",
    "READ_FAILED": "無法讀取",
    "CHANGED_DURING_READ": "讀取時資料變動",
    "MALFORMED": "資料格式不正確",
    "SCHEMA_MISMATCH": "Audit 欄位不相容",
    "ENTRY_LIMIT": "超出目錄筆數上限",
    "ROW_LIMIT": "超出 Audit 筆數上限",
    "ENDPOINT_LIMIT": "超出端點數量上限",
    "LEASE_LIMIT": "超出端點租約上限",
}
_SIGNAL_LABELS = {
    "PENDING_WITHOUT_RUNNING": "仍有待處理項目，但目前 Running 為 0",
    "POSSIBLE_BATCH_TAIL_OR_DISPATCH_GAP": "Running 少於設定併行數；可能是批次尾端等待或派工空檔",
    "LAST_ROUND_COMPLETION_OLD": "Queue 最近一輪完成時間偏久",
    "EXPIRED_LEASE_RECORDS_UNCLEANED": "負載檔包含已過期租約（尚未清理）",
    "RUNNING_WITHOUT_ACTIVE_LEASE": "Queue 顯示 Running，但負載檔沒有有效租約",
    "PENDING_WITH_NO_RECENT_COMPLETION_AUDIT": "仍有待辦，但回溯期間沒有最近的完成 Audit",
}


def _human_number(value):
    """Refuse to print arbitrary untrusted strings in local human summaries."""
    return str(value) if type(value) is int and 0 <= value <= 100000000 else "未取得"


def format_human_report(report: dict, *, default_logs: bool = True) -> str:
    """Readable, bounded and metadata-only Chinese operator summary."""
    lines = [
        "========== LLM／GPU 派工診斷（唯讀）==========",
        ("日誌來源：專案根目錄 logs（完整路徑隱藏）"
         if default_logs else "日誌來源：指定的 --logs-dir（完整路徑隱藏）"),
        "注意：本工具不直接量測 GPU，也不驗證實際 HTTP 請求或 SQL／ES 寫回。",
        "",
        "【資料讀取】",
    ]
    sources = report.get("sources", {})
    for key, name in _SOURCE_LABELS.items():
        status = sources.get(key, {}).get("status")
        lines.append(f"  {name}：{_SOURCE_STATES.get(status, '無法判讀')}")
    meter = sources.get("meter", {})
    if meter.get("status") == "OBSERVED":
        lines.extend([
            "",
            "【Queue 工作狀態】",
            f"  Pending：{_human_number(meter.get('pending'))}",
            f"  Running：{_human_number(meter.get('running'))}",
            f"  Completed：{_human_number(meter.get('completed'))}",
            f"  設定併行數：{_human_number(meter.get('configured_worker_width'))}",
        ])
    load = sources.get("load", {})
    if load.get("status") == "OBSERVED":
        lines.extend([
            "",
            "【端點負載估計】",
            f"  已記錄端點：{_human_number(load.get('endpoint_count'))}",
            f"  尚未到期租約：{_human_number(load.get('active_leases_total'))}",
            f"  已到期租約：{_human_number(load.get('expired_leases_total'))}",
        ])
        for endpoint in load.get("endpoints", [])[:64]:
            label = endpoint.get("id")
            if isinstance(label, str) and label.startswith("endpoint_") and label[9:].isdigit() and len(label) == 11:
                lines.append(
                    f"    {label}：有效 {_human_number(endpoint.get('active_lease_count'))}，"
                    f"已到期 {_human_number(endpoint.get('expired_lease_count'))}"
                )
    audit = sources.get("audit", {})
    if audit.get("status") in {"OBSERVED", "INCOMPLETE"} and "recent_completed_audit_rows" in audit:
        lines.extend([
            "",
            "【最近完成 Audit】",
            f"  已記錄呼叫：{_human_number(audit.get('recent_completed_audit_rows'))}",
            f"  成功：{_human_number(audit.get('recent_ok_rows'))}",
            f"  失敗：{_human_number(audit.get('recent_failed_rows'))}",
        ])
    signals = [label for key in report.get("signals", []) if (label := _SIGNAL_LABELS.get(key))]
    lines.extend(["", "【可能的停滯線索（不代表根因已確認）】"])
    lines.extend(f"  - {line}" for line in signals) if signals else lines.append("  尚未觀察到定義內的候選線索")
    lines.extend([
        "",
        ("結果：證據已讀取，但不能據此認定 GPU 正常／異常。"
         if report.get("diagnosis_status") == "OBSERVED_NOT_PROVEN"
         else "結果：資料不足或不完整，無法完成此次觀測。"),
        "安全限制：沒有修改 Queue、租約、LLM 或 GPU 狀態。",
        "============================================",
    ])
    return "\n".join(lines)

def main(argv=None):
    parser = argparse.ArgumentParser(description="Local read-only LLM dispatch evidence; not live GPU telemetry")
    parser.add_argument("--logs-dir", type=Path, default=Path("logs"), help="LLM 執行時的 logs 目錄，預設為專案 logs")
    parser.add_argument("--human", action="store_true", help="輸出繁體中文摘要（不顯示私有路徑或端點）")
    parser.add_argument("--samples", type=int, default=1)
    parser.add_argument("--interval-seconds", type=float, default=30.0)
    parser.add_argument("--window-seconds", type=int, default=900)
    args = parser.parse_args(argv)
    if not (1 <= args.samples <= 20 and math.isfinite(args.interval_seconds)
            and 0 <= args.interval_seconds <= 3600 and 60 <= args.window_seconds <= 86400):
        parser.error("bounded sampling settings required")
    all_observed = True
    for i in range(args.samples):
        if i:
            time.sleep(args.interval_seconds)
        doc = snapshot(args.logs_dir, window=args.window_seconds)
        doc["sample_number"] = i + 1
        if args.human:
            print(format_human_report(doc, default_logs=args.logs_dir == Path("logs")), flush=True)
        else:
            print(json.dumps(doc, ensure_ascii=False, sort_keys=True, separators=(",", ":")), flush=True)
        all_observed &= doc["diagnosis_status"] == "OBSERVED_NOT_PROVEN"
    return 0 if all_observed else 2


if __name__ == "__main__":
    sys.exit(main())
