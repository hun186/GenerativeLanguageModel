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


def main(argv=None):
    parser = argparse.ArgumentParser(description="Local read-only LLM dispatch evidence; not live GPU telemetry")
    parser.add_argument("--logs-dir", type=Path, default=Path("logs"))
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
        print(json.dumps(doc, ensure_ascii=False, sort_keys=True, separators=(",", ":")), flush=True)
        all_observed &= doc["diagnosis_status"] == "OBSERVED_NOT_PROVEN"
    return 0 if all_observed else 2


if __name__ == "__main__":
    sys.exit(main())
