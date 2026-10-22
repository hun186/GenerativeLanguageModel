"""Read-only, payload-free counters from one LLM-call audit CSV.

This is a request-level observation, NOT a whole-pipeline or document
failure rate.  Raw exceptions, prompts, URLs and file paths never leave here.
"""

from __future__ import annotations

from collections import Counter
import csv
import io
import os
from pathlib import Path
import re
import stat

MAX_AUDIT_FILE_BYTES = 16 * 1024 * 1024
MAX_HISTORY_BYTES = 64 * 1024 * 1024
MAX_HISTORY_ENTRIES = 10000
LOW_SAMPLE_THRESHOLD = 30
_AUDIT_FILENAME = re.compile(r"llm_call_audit_[A-Za-z0-9][A-Za-z0-9_.-]{0,100}\.csv\Z")

# Apply only to rows where ok=NO.  Patterns classify exceptions, never content.
_PATTERNS = (
    ("rate_limit", re.compile(r"\b429\b|rate[_\s-]*limit|too many requests", re.I)),
    ("timeout", re.compile(r"\btime(?:d)?\s*out\b|timeout(?:error)?", re.I)),
    ("context_budget", re.compile(r"context (?:length|window|limit)|maximum context|token limit exceeded", re.I)),
    ("transport", re.compile(r"connection (?:error|refused|reset|aborted|closed|failed)|"
                              r"connect(?:ion)?error|remoteprotocolerror|network (?:error|unreachable)|"
                              r"\b(?:502|503|504)\b", re.I)),
    ("json_postprocessing", re.compile(r"jsondecodeerror|json (?:decode|parse|syntax) error", re.I)),
)


def classify_failed_call(error: object) -> str:
    """Conservative allowlist; unknown exceptions must stay unknown."""
    if not isinstance(error, str):
        return "unclassified"
    for name, pattern in _PATTERNS:
        if pattern.search(error[:16384]):
            return name
    return "unclassified"


def _audit_file_name(path: Path) -> bool:
    return bool(_AUDIT_FILENAME.fullmatch(path.name))


def _read_bounded_csv(path: Path, *, max_bytes: int) -> str:
    if not _audit_file_name(path):
        raise ValueError("expected a canonical llm_call_audit_<run_id>.csv filename")
    if path.is_symlink():
        raise ValueError("symlink audit streams are not allowed")
    with path.open("rb") as stream:
        start = os.fstat(stream.fileno())
        if not stat.S_ISREG(start.st_mode):
            raise ValueError("audit stream must be a regular file")
        if start.st_size > max_bytes:
            raise ValueError("audit stream exceeds bounded read budget")
        data = stream.read(start.st_size + 1)
        end = os.fstat(stream.fileno())
        if len(data) != start.st_size or end.st_size != start.st_size:
            raise ValueError("audit stream changed during reading")
    # A half-written trailing CSV record cannot be a verified completed call.
    if not data.endswith(b"\n"):
        raise ValueError("audit CSV has an incomplete trailing record")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("audit CSV has invalid UTF-8") from exc


def summarize_llm_failure_audit(path: str | Path, *, max_bytes: int = MAX_AUDIT_FILE_BYTES) -> dict:
    """Summarize one immutable read snapshot; never emit raw errors or IDs."""
    if type(max_bytes) is not int or max_bytes <= 0 or max_bytes > MAX_AUDIT_FILE_BYTES:
        raise ValueError("invalid per-file read bound")
    source = Path(path)
    text = _read_bounded_csv(source, max_bytes=max_bytes)
    reader = csv.DictReader(io.StringIO(text, newline=""), strict=True)
    headers = reader.fieldnames or []
    if headers.count("ok") != 1 or headers.count("error") != 1 or len(headers) != len(set(headers)):
        raise ValueError("audit CSV has invalid or duplicate required headers")
    counts = Counter()
    successful = failed = invalid = 0
    try:
        for row in reader:
            if None in row or any(value is None for value in row.values()):
                invalid += 1
                continue
            outcome = row["ok"]
            if outcome == "YES":
                successful += 1
            elif outcome == "NO":
                failed += 1
                counts[classify_failed_call(row["error"])] += 1
            else:
                invalid += 1
    except (csv.Error, UnicodeError) as exc:
        raise ValueError("audit CSV has malformed rows") from exc
    observed = successful + failed
    return {
        "log_file": source.name,
        "state": "degraded_invalid_rows" if invalid else "observed" if observed else "no_observed_calls",
        "total_rows": observed + invalid,
        "observed_call_attempts": observed,
        "successful_call_attempts": successful,
        "failed_call_attempts": failed,
        "unclassified_or_invalid_status_rows": invalid,
        "failed_call_pct": round(failed * 100 / observed, 2) if observed else None,
        "failure_categories": {name: counts.get(name, 0) for name in (
            "rate_limit", "timeout", "context_budget", "transport",
            "json_postprocessing", "unclassified"
        )},
        "sample_advisory": ("no valid call outcomes; rate unknown" if not observed
                            else f"small denominator (n={observed}); interpret cautiously"
                            if observed < LOW_SAMPLE_THRESHOLD else ""),
    }


def llm_failure_history(folder: str | Path, *, limit: int = 20) -> dict:
    """Latest bounded independent CSV snapshots; never pool run denominators."""
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("limit must be 1..100")
    root = Path(folder)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("audit directory must be a real directory")
    found = []
    with os.scandir(root) as entries:
        for index, entry in enumerate(entries):
            if index >= MAX_HISTORY_ENTRIES:
                raise ValueError("audit directory exceeds discovery limit")
            if _audit_file_name(Path(entry.name)) and entry.is_file(follow_symlinks=False):
                found.append(root / entry.name)
    selected = sorted(found, key=lambda p: p.name, reverse=True)[:limit]
    if sum(path.stat().st_size for path in selected) > MAX_HISTORY_BYTES:
        raise ValueError("selected audit history exceeds combined read budget")
    return {
        "report_version": 1,
        "mode": "run_history",
        "denominator_contract": "observed LLM call attempts only; separate per run",
        "available_run_files": len(found),
        "selected_run_files": len(selected),
        "runs": [summarize_llm_failure_audit(path) for path in selected],
    }
