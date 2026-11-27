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

from czjLLM.job_manager.document_progress import read_meter_strict, project_meter, PAGE_SIZE

REFRESH_SECONDS = 2.0
MAX_AGE_SECONDS = 8.0


def project_public_documents(meter, salt):
    view = project_meter(meter, mode="目前處理", page=0, page_size=PAGE_SIZE)
    rows = []
    for item in view["shown"]:
        alias = hmac.new(salt, item["key"].encode("utf-8", errors="surrogatepass"),
                         hashlib.sha256).hexdigest()[:20]
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
    }


class DocumentMonitor:
    """One reader per run, independent of HTTP clients and request rate."""

    def __init__(self, *, clock=time.monotonic):
        self._lock = threading.Lock()
        self._path = ""
        self._generation = 0
        self._salt = os.urandom(32)
        self._clock = clock
        self._observed_at = None
        self._view = {"status": "waiting_for_meter", "rows": []}

    def set_path(self, path):
        if not isinstance(path, str) or len(path) > 4096 or "\x00" in path:
            path = ""
        with self._lock:
            if path != self._path:
                self._path = path
                self._generation += 1
                self._observed_at = None
                self._view = {"status": "waiting_for_meter", "rows": []}

    def refresh_once(self):
        with self._lock:
            path, generation = self._path, self._generation
        if not path:
            return
        try:
            view = project_public_documents(read_meter_strict(path), self._salt)
        except FileNotFoundError:
            view = {"status": "waiting_for_meter", "rows": []}
        except Exception:
            # No exception details, stale rows, or synthetic successful empty run.
            view = {"status": "unavailable", "rows": []}
        with self._lock:
            if self._generation == generation:
                self._view = view
                self._observed_at = self._clock()

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
            return self._view
