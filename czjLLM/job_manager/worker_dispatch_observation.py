"""Best-effort, per-Worker-call dispatched model/IP observation for GUI.

This is not an authenticated provider HTTP receipt, a Queue claim, a sink ACK,
or a retry-family authority. Every call has its own atomic metadata-only file:
no SQL/ES writes, raw prompt/file paths, URL/query, credentials, or payloads.
Only jobs with an explicitly passed item_dir produce row-correlated evidence.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat
import time
from uuid import UUID

from czjLLM.job_manager.document_model_endpoint import (
    _MODEL_NAME, _audit_path_key, _endpoint_ip,
)
from czjLLM.utilities.llm_failure_summary import (
    _audit_file_name, _is_reparse_or_link, _snapshot_path_components,
)

MAX_CALLS_PER_ROW = 256
MAX_RECORD_BYTES = 2048
_ALLOWED_STATES = {"assigned", "calling", "returned", "failed"}


def _identity(value):
    key = _audit_path_key(value)
    return hashlib.sha256(key.encode("utf-8")).hexdigest() if key else ""


def _call_id(value):
    if not isinstance(value, str) or len(value) != 32:
        return False
    try:
        return UUID(hex=value).hex == value and UUID(hex=value).version == 4
    except ValueError:
        return False


def _observations_dir(audit_path):
    path = Path(audit_path)
    if not _audit_file_name(path):
        raise ValueError("not a canonical audit filename")
    _snapshot_path_components(path)
    return path.with_suffix(".dispatch")


def _check_dir(path):
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or _is_reparse_or_link(info):
        raise ValueError("unsafe dispatch directory")


def _ensure_dir(path):
    try:
        path.mkdir()
    except FileExistsError:
        pass
    _check_dir(path)


def write_worker_dispatch_observation(
    *, audit_path, item_dir, prompt_file, worker_call_id,
    model_spec, status,
):
    """Atomic lifecycle snapshot. Caller MUST contain telemetry exceptions.

    Multiple concurrent slices never clobber each other's state; successive
    states for the same Worker call atomically replace that call's file.
    """
    if status not in _ALLOWED_STATES or not _call_id(worker_call_id):
        raise ValueError("invalid dispatch state or call ID")
    item_hash = _identity(item_dir)
    slice_hash = _identity(prompt_file)
    if not item_hash or not slice_hash or not isinstance(model_spec, dict):
        raise ValueError("missing verified dispatch association")
    model = str(model_spec.get("model_name") or "")
    if not _MODEL_NAME.fullmatch(model):
        raise ValueError("model name not safely displayable")
    endpoint = _endpoint_ip(model_spec.get("base_url"))
    root = _observations_dir(audit_path)
    _ensure_dir(root)
    group = root / item_hash[:2]
    _ensure_dir(group)
    folder = group / item_hash
    _ensure_dir(folder)
    doc = {
        "version": 1,
        "item_hash": item_hash,
        "slice_hash": slice_hash,
        "worker_call_id": worker_call_id,
        "status": status,
        "model": model,
        "endpoint_ip": endpoint,
        "observed_ns": time.time_ns(),
    }
    payload = json.dumps(doc, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(payload) > MAX_RECORD_BYTES:
        raise ValueError("dispatch observation too large")
    target = folder / (worker_call_id + ".json")
    temp = folder / ("." + worker_call_id + "." + os.urandom(8).hex() + ".tmp")
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                 getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        with os.fdopen(fd, "wb") as fp:
            fp.write(payload)
            fp.flush()
            os.fsync(fp.fileno())
        _check_dir(folder)
        os.replace(temp, target)
    finally:
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            pass


def _read_one(path, expected_item_hash):
    before = path.lstat()
    if (not stat.S_ISREG(before.st_mode) or _is_reparse_or_link(before)
            or before.st_size > MAX_RECORD_BYTES):
        raise ValueError("unsafe dispatch record")
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_BINARY", 0) |
                 getattr(os, "O_NOFOLLOW", 0))
    try:
        opened = os.fstat(fd)
        if ((opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino)
                or not stat.S_ISREG(opened.st_mode)):
            raise ValueError("dispatch file changed")
        with os.fdopen(fd, "rb") as fp:
            contents = fp.read(MAX_RECORD_BYTES + 1)
            after = os.fstat(fp.fileno())
        fd = -1
        if len(contents) > MAX_RECORD_BYTES or before.st_size != len(contents):
            raise ValueError("invalid dispatch length")
        if (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns) != (
                opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns):
            raise ValueError("dispatch changed during read")
    finally:
        if fd >= 0:
            os.close(fd)
    data = json.loads(contents)
    if (not isinstance(data, dict) or data.get("version") != 1
            or data.get("item_hash") != expected_item_hash
            or not _call_id(data.get("worker_call_id"))
            or path.name != data["worker_call_id"] + ".json"
            or not isinstance(data.get("slice_hash"), str)
            or len(data["slice_hash"]) != 64
            or data.get("status") not in _ALLOWED_STATES
            or not isinstance(data.get("model"), str)
            or not _MODEL_NAME.fullmatch(data["model"])
            or not isinstance(data.get("endpoint_ip"), str)
            or len(data["endpoint_ip"]) > 64
            or not isinstance(data.get("observed_ns"), int)
            or data["observed_ns"] < 0):
        raise ValueError("malformed dispatch observation")
    # Endpoint has been sanitized by the writer; never trust an edited file.
    # Re-parse it as IP literal via a synthetic fixed-scheme URL.
    if data["endpoint_ip"]:
        ip = data["endpoint_ip"]
        if _endpoint_ip("http://" + ip) != ip:
            raise ValueError("dispatch IP not literal")
    return data


def read_visible_dispatch_observations(audit_path, item_dirs):
    """Bounded read for visible items only; no recursive run-wide directory walk.

    Unsafe/incomplete row evidence is marked unavailable rather than silently
    returning stale or partially valid results.
    """
    if len(item_dirs) > 100:
        raise ValueError("too many visible rows")
    results = {k: {"text": "", "status": "", "count": 0} for k in item_dirs}
    root = _observations_dir(audit_path)
    if not root.exists():
        return results
    _check_dir(root)
    for key, raw_path in item_dirs.items():
        item_hash = _identity(raw_path)
        if not item_hash:
            continue
        folder = root / item_hash[:2] / item_hash
        if not folder.exists():
            continue
        _check_dir(folder.parent)
        _check_dir(folder)
        observations = []
        with os.scandir(folder) as entries:
            for idx, entry in enumerate(entries):
                if idx >= MAX_CALLS_PER_ROW:
                    raise ValueError("dispatch observations exceed per-row budget")
                if not entry.name.endswith(".json") or not _call_id(entry.name[:-5]):
                    raise ValueError("unexpected dispatch record entry")
                observations.append(_read_one(Path(entry.path), item_hash))
        if not observations:
            continue
        # Active observations take priority over earlier completed calls.
        active = [v for v in observations if v["status"] in ("assigned", "calling")]
        selected = max(active or observations, key=lambda v: (
            v["observed_ns"], v["worker_call_id"],
        ))
        label = f'{selected["model"]} · {selected["endpoint_ip"] or "IP 未記錄"}'
        stage = {
            "assigned": "已分派（最後觀測）",
            "calling": "呼叫中（最後觀測）",
            "returned": "已回傳（最後觀測）",
            "failed": "失敗（最後觀測）",
        }[selected["status"]]
        count = len(active)
        results[key] = {
            "text": f"{label}｜{stage}" + (f" · {count} 呼叫" if count > 1 else ""),
            "status": selected["status"], "count": len(observations),
        }
    return results
