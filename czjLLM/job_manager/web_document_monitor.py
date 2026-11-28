"""Bounded, redacted document view shared with the desktop meter reader.

The producer alone selects the meter. HTTP consumers cannot provide a path,
filter or page. The local unauthenticated endpoint exposes no document keys,
filenames, models, IP addresses, audit paths or raw content.
"""
import hashlib
import hmac
import os
import threading
import time

from czjLLM.job_manager.document_progress import (
    read_meter_strict, project_meter, PAGE_SIZE, MAX_PAGE_ACTIVITY_CALLS,
    capture_activity_clock, format_activity_clock,
)
from czjLLM.job_manager.worker_dispatch_observation import read_visible_dispatch_observations
from czjLLM.job_manager.audit_distribution_incremental import IncrementalAuditReader

REFRESH_SECONDS = 2.0
MAX_AGE_SECONDS = 8.0


def _alias(salt, domain, value):
    return hmac.new(salt, (domain + "\0" + value).encode("utf-8", errors="surrogatepass"),
                    hashlib.sha256).hexdigest()[:20]


def project_public_documents(meter, salt, *, audit_path="", wall_ns=None, monotonic_s=None):
    view = project_meter(meter, mode="目前處理", page=0, page_size=PAGE_SIZE)
    rows = []
    for item in view["shown"]:
        alias = _alias(salt, "row", item["key"])
        rows.append({
            "alias": alias, "stage": item["stage"],
            "done": item["done"], "total": item["total"],
            "pending": item["pending"], "running": item["running"],
        })
    return {
        "status": "observed", "all": view["all"], "active": view["active"],
        "errors": view["errors"], "matching": view["matching"],
        "omitted": view["matching"] - len(rows), "rows": rows,
        "sink_readback_verified": False,
        "workers": _project_workers(meter, view, salt, audit_path,
                                    wall_ns=wall_ns, monotonic_s=monotonic_s),
    }


def _project_workers(meter, view, salt, audit_path, *, wall_ns, monotonic_s):
    if not audit_path:
        return {"status": "waiting_for_audit", "calls": []}
    running = [item for item in view["shown"]
               if item["state"] == "in_progress" and (item["running"] or 0) > 0]
    item_dirs = {}
    for item in running:
        source = meter["rows"].get(item["key"])
        if isinstance(source, dict) and isinstance(source.get("item_dir"), str) and source["item_dir"]:
            item_dirs[item["key"]] = source["item_dir"]
    try:
        evidence = read_visible_dispatch_observations(audit_path, item_dirs)
    except (ValueError, OSError, UnicodeError):
        return {"status": "unavailable", "calls": []}
    wall_ns = time.time_ns() if wall_ns is None else wall_ns
    monotonic_s = time.monotonic() if monotonic_s is None else monotonic_s
    count = 0
    calls = []
    for item in running:
        key = item["key"]
        current = evidence.get(key, {})
        count += current.get("active_count", 0)
        for call in current.get("active_calls", []):
            if len(calls) >= MAX_PAGE_ACTIVITY_CALLS:
                break
            detail = call.get("stream_activity")
            endpoint = call["endpoint_ip"]
            calls.append({
                "row_alias": _alias(salt, "row", key),
                "endpoint_alias": _alias(salt, "endpoint", endpoint) if endpoint else None,
                "status": call["status"],
                "stream_event": detail["event"] if detail is not None else None,
                "chunks": detail["chunks"] if detail is not None else None,
                "thinking_seen": detail["thinking_seen"] if detail is not None else None,
                "content_seen": detail["content_seen"] if detail is not None else None,
                "_clock": capture_activity_clock(call, wall_ns=wall_ns, monotonic_s=monotonic_s),
            })
    return {"status": "observed", "scope": "visible_page_last_observed",
            "calls": calls, "count": count, "omitted": count - len(calls),
            "running_rows_without_observations": sum(
                not evidence.get(row["key"], {}).get("active_count") for row in running),
            "gpu_utilization_known": False}


def _render_workers(workers, monotonic_s):
    # Return only fixed public fields; never transmit the internal clock anchor.
    result = dict(workers)
    result["calls"] = [
        {**{k: v for k, v in call.items() if k != "_clock"},
         "clock_text": format_activity_clock(call["_clock"], monotonic_s=monotonic_s)}
        for call in workers.get("calls", [])
    ]
    return result


class DocumentMonitor:
    """One reader per run, independent of HTTP clients and request rate."""

    def __init__(self, *, clock=time.monotonic):
        self._lock = threading.Lock()
        self._path = ""
        self._audit_path = ""
        self._generation = 0
        self._salt = os.urandom(32)
        self._clock = clock
        self._observed_at = None
        self._view = {"status": "waiting_for_meter", "rows": []}
        self._audit = {"status": "waiting_for_audit"}
        self._audit_observed_at = None
        self._audit_reader = IncrementalAuditReader()

    def set_path(self, path):
        if not isinstance(path, str) or len(path) > 4096 or "\x00" in path:
            path = ""
        with self._lock:
            if path != self._path:
                self._path = path
                self._generation += 1
                self._observed_at = None
                self._view = {"status": "waiting_for_meter", "rows": []}

    def set_audit_path(self, path):
        if not isinstance(path, str) or len(path) > 4096 or "\x00" in path:
            path = ""
        with self._lock:
            if path != self._audit_path:
                self._audit_path = path
                self._generation += 1
                self._observed_at = None
                self._view = {"status": "waiting_for_meter", "rows": []}
                self._audit = {"status": "waiting_for_audit"}
                self._audit_observed_at = None
                self._audit_reader = IncrementalAuditReader()

    def refresh_once(self):
        with self._lock:
            path, audit_path, generation = self._path, self._audit_path, self._generation
            reader = self._audit_reader
        started = self._clock()
        try:
            view = (project_public_documents(read_meter_strict(path), self._salt,
                                             audit_path=audit_path) if path else
                    {"status": "waiting_for_meter", "rows": []})
        except FileNotFoundError:
            view = {"status": "waiting_for_meter", "rows": []}
        except Exception:
            # No exception details, stale rows, or synthetic successful empty run.
            view = {"status": "unavailable", "rows": []}
        audit_started = self._clock()
        audit = reader.read(audit_path)
        with self._lock:
            if self._generation == generation:
                self._view = view
                self._observed_at = started
                self._audit = audit
                self._audit_observed_at = audit_started

    def run(self, stop):
        while not stop.is_set():
            self.refresh_once()
            stop.wait(REFRESH_SECONDS)

    def snapshot(self):
        with self._lock:
            if self._observed_at is not None:
                age = self._clock() - self._observed_at
                if not 0 <= age <= MAX_AGE_SECONDS:
                    return {"status": "stale", "rows": []}
            view = dict(self._view)
            if "workers" in view:
                view["workers"] = _render_workers(view["workers"], time.monotonic())
            return view


    def audit_snapshot(self):
        with self._lock:
            if self._audit_observed_at is not None:
                age = self._clock() - self._audit_observed_at
                if not 0 <= age <= MAX_AGE_SECONDS:
                    return {"status": "stale"}
            return dict(self._audit)
