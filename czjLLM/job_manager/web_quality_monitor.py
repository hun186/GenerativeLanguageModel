"""Run-scoped, numeric-only quality observation for the local HTTP monitor."""
from copy import deepcopy
import math
from pathlib import Path
import stat
import threading
import time

from czjLLM.utilities.processing_quality import QualityCapacityExceeded, RUN_INCIDENT_CODES
from czjLLM.utilities.processing_quality_run_reader import QualityRunTailReader
from czjLLM.utilities.processing_quality_manifest import manifest_path
from czjLLM.utilities.processing_quality_rotation import quality_stream_segments

MAX_SOURCE_BYTES = 64 * 1024 * 1024
MAX_SEGMENTS = 64
REFRESH_SECONDS = 2
MAX_AGE_SECONDS = 8
_COUNTS = ("events", "slice_validation_attempts", "slice_initial_invalid",
           "repair_attempts", "repair_succeeded", "documents_decided",
           "documents_schema_pending", "documents_writeback_confirmed",
           "consumer_orchestration_failure_events", "row_merger_retryable_failure_events",
           "producer_operational_failure_events", "stage_orchestration_failure_events",
           "worker_phase_failure_events")
_RATIOS = {
    "slice_initial_invalid_pct": ("slice_initial_invalid", "slice_validation_attempts"),
    "repair_success_pct": ("repair_succeeded", "repair_attempts"),
    "document_schema_reject_pct": ("documents_schema_pending", "documents_decided"),
}
_RUN_CODES = frozenset().union(*RUN_INCIDENT_CODES.values())
_NONOBSERVED = {"not_initialized", "unsealed_legacy", "degraded_corrupt_lines", "incomplete_tail"}


def _count(value):
    if type(value) is not int or not 0 <= value <= (1 << 53) - 1:
        raise ValueError("invalid quality count")
    return value


def public_quality(stats):
    """Project only known counts, independent denominators and run incident codes."""
    status = stats.get("quality_stream_status")
    if status in _NONOBSERVED:
        # Do not show partial/unsealed data as complete observed counters.
        return {"status": status}
    if status != "observed":
        return {"status": "unverified"}
    result = {key: _count(stats.get(key)) for key in _COUNTS}
    for key, (num, den) in _RATIOS.items():
        n, d = result[num], result[den]
        if n > d:
            raise ValueError("invalid quality denominator")
        result[key] = round(100 * n / d, 2) if d else None
    codes = stats.get("error_codes", {})
    if not isinstance(codes, dict):
        raise ValueError("invalid quality code map")
    result["incident_codes"] = {key: _count(codes[key]) for key in sorted(_RUN_CODES) if key in codes}
    result["status"] = "observed"
    result["scope"] = "observed_quality_events_current_run"
    result["sink_readback_verified"] = False
    return result


def _check_locator(path):
    p = Path(path).absolute()
    if not p.name.startswith("processing_quality_events_") or p.suffix != ".jsonl":
        raise ValueError("noncanonical quality locator")
    # Trusted producer IPC locator, not a browser argument. Existing local
    # reader assumes cooperating writers; this is not a hostile-FS sandbox.
    for node in reversed((p, *p.parents)):
        try:
            info = node.lstat()
        except FileNotFoundError:
            continue
        if (stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0)
                & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)):
            raise ValueError("unsafe quality locator")
        if node != p and not stat.S_ISDIR(info.st_mode):
            raise ValueError("unsafe quality parent")
    total = 0
    for node in (p, manifest_path(p), *quality_stream_segments(p, max_segments=MAX_SEGMENTS)):
        try:
            info = node.lstat()
        except FileNotFoundError:
            continue
        if (not stat.S_ISREG(info.st_mode) or getattr(info, "st_file_attributes", 0)
                & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)):
            raise ValueError("unsafe quality file")
        total += info.st_size
        if total > MAX_SOURCE_BYTES:
            raise QualityCapacityExceeded("quality source byte budget exceeded")


class WebQualityMonitor:
    """Separate background owner; never read files on HTTP requests."""
    def __init__(self, *, clock=time.monotonic):
        self._clock = clock
        self._lock = threading.Lock()
        self._path = ""
        self._generation = 0
        self._reader = QualityRunTailReader()
        self._view = {"status": "waiting_for_quality"}
        self._observed_at = None

    def set_path(self, path):
        if not isinstance(path, str) or len(path) > 4096 or "\x00" in path:
            path = ""
        with self._lock:
            if path != self._path:
                self._path = path
                self._generation += 1
                self._reader = QualityRunTailReader(path)
                self._view = {"status": "waiting_for_quality"}
                self._observed_at = None

    def refresh_once(self):
        with self._lock:
            path, generation, reader = self._path, self._generation, self._reader
        started = self._clock()
        try:
            if not path:
                result = {"status": "waiting_for_quality"}
            else:
                _check_locator(path)
                _, stats = reader.poll()
                _check_locator(path)
                result = public_quality(stats)
        except QualityCapacityExceeded:
            result = {"status": "capacity_exceeded"}
        except Exception:
            # Fixed diagnostic only. Reader failure must not stop other panels.
            result = {"status": "unverified"}
        with self._lock:
            if generation == self._generation:
                self._view = result
                self._observed_at = started

    def run(self, stop):
        while not stop.is_set():
            self.refresh_once()
            stop.wait(REFRESH_SECONDS)

    def snapshot(self):
        with self._lock:
            if self._observed_at is not None:
                age = self._clock() - self._observed_at
                if not 0 <= age <= MAX_AGE_SECONDS:
                    return {"status": "stale"}
            return deepcopy(self._view)
