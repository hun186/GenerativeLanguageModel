"""Optional, read-only per-document *observed* LLM model/IP projection.

Evidence is the current run's completed LLM-call CSV rows. A model configured
for dispatch is NOT evidence that a particular Worker used that model or IP.
No DNS lookup, queue scan, endpoint probing, model invocation or sink access.
"""
from __future__ import annotations

import ipaddress
from pathlib import Path
import re
from urllib.parse import urlsplit

from czjLLM.utilities.llm_failure_summary import (
    _iter_audit_csv_rows,
    _read_bounded_csv,
    MAX_AUDIT_FILE_BYTES,
)

_MODEL_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:/+\-]{0,79}\Z")


def _audit_path_key(value: object) -> str:
    """Match Windows and POSIX *literal* item descendants, not basename guesses."""
    if not isinstance(value, str) or not value or len(value) > 4096:
        return ""
    parts = value.replace("\\", "/").split("/")
    if any(part in {".", ".."} or not part.isprintable() for part in parts):
        return ""
    return "/".join(parts).rstrip("/").casefold()


def _endpoint_ip(value: object) -> str:
    """Only a literal IP (with optional port), never credentials/URL/path."""
    if not isinstance(value, str) or not 0 < len(value) <= 2048:
        return ""
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            return ""
        if parsed.username is not None or parsed.password is not None:
            return ""
        host = parsed.hostname
        if not host:
            return ""
        address = ipaddress.ip_address(host)
        port = parsed.port
        display = f"[{address}]" if address.version == 6 else str(address)
        return f"{display}:{port}" if port is not None else display
    except (ValueError, AttributeError):
        return ""


def observed_model_endpoint_pairs(audit_path: str | Path,
                                  item_dirs: dict[str, object]) -> dict[str, dict]:
    """For the *selected page only*, join exact item descendants to audit rows.

    The snapshot is bounded to the existing 16 MiB strict audit reader; if a
    run exceeds that limit the GUI marks evidence unavailable, never guesses.
    Any malformed CSV record (including extra fields) fails the whole view
    rather than importing unverifiable partial metadata.
    """
    requested = {key: _audit_path_key(path) for key, path in item_dirs.items()}
    requested = {key: path for key, path in requested.items() if path}
    result = {
        key: {"latest": "", "pairs": [], "more_pairs": False}
        for key in item_dirs
    }
    if not requested:
        return result
    contents, _size = _read_bounded_csv(Path(audit_path), max_bytes=MAX_AUDIT_FILE_BYTES)
    field_limit = [128]
    reader = iter(_iter_audit_csv_rows(contents, field_limit=field_limit))
    header = next(reader, [])
    required = ("prompt_file", "model", "base_url")
    if not header or len(header) != len(set(header)) or any(header.count(f) != 1 for f in required):
        raise ValueError("audit model/endpoint evidence headers are unavailable")
    field_limit[0] = len(header)
    idx = {name: header.index(name) for name in required}
    for record in reader:
        if len(record) != len(header):
            raise ValueError("audit model/endpoint evidence has incomplete row")
        filename = _audit_path_key(record[idx["prompt_file"]])
        if not filename:
            continue
        model = record[idx["model"]]
        if not _MODEL_NAME.fullmatch(model):
            continue
        endpoint = _endpoint_ip(record[idx["base_url"]])
        # No private URL, credential, DNS hostname or source path in the UI.
        display = f"{model} · {endpoint or 'IP 未記錄'}"
        for key, path in requested.items():
            if filename.startswith(path + "/"):
                evidence = result[key]
                # Update on *every* observation. A -> B -> A must show A,
                # including when A was already in the bounded distinct set.
                evidence["latest"] = display
                distinct = evidence["pairs"]
                if display not in distinct:
                    if len(distinct) < 6:
                        distinct.append(display)
                    else:
                        # Do not claim an exact distinct count after the cap.
                        # We still preserve the actual latest observation.
                        evidence["more_pairs"] = True
    return result


def summarize_model_endpoint_pairs(evidence: dict) -> str:
    """A single narrow Treeview column, latest observed pair and diversity."""
    if not isinstance(evidence, dict):
        return "—"
    latest = evidence.get("latest", "")
    if not latest:
        return "—"
    pairs = evidence.get("pairs") or []
    extra = (len(pairs) if evidence.get("more_pairs") else len(pairs) - 1)
    suffix = (f" (+{extra}+ 組)" if evidence.get("more_pairs")
              else f" (+{extra} 組)" if extra > 0 else "")
    return latest[:94] + ("…" if len(latest) > 94 else "") + suffix
