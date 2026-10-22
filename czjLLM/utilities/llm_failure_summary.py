"""Read-only, payload-free counters from one LLM-call audit CSV.

This is a request-level observation, NOT a whole-pipeline or document
failure rate.  Raw exceptions, prompts, URLs and file paths never leave here.
"""

from __future__ import annotations

from collections import Counter
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
    ("json_postprocessing", re.compile(
        r"\bJSON_POSTPROCESSING_FAILED\b|jsondecodeerror|json (?:decode|parse|syntax) error", re.I)),
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


def _is_reparse_or_link(metadata) -> bool:
    """Reject symlinks and Windows reparse points without following them."""
    return (stat.S_ISLNK(metadata.st_mode) or
            bool(getattr(metadata, "st_file_attributes", 0) &
                 getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)))


def _has_untrusted_path_component(path: Path) -> bool:
    """Never accept a symlink or Windows junction in the entire supplied path."""
    absolute = path.absolute()
    return any(_is_reparse_or_link(component.lstat())
               for component in (absolute, *absolute.parents))


def _snapshot_path_components(path: Path) -> tuple:
    """Capture no-follow identities of every ancestor before opening the leaf."""
    absolute = path.absolute()
    snapshot = tuple((component, component.lstat())
                     for component in (absolute, *absolute.parents))
    if any(_is_reparse_or_link(info) for _, info in snapshot):
        raise ValueError("symlink or reparse audit path components are not allowed")
    return snapshot


def _verify_path_snapshot(snapshot: tuple) -> None:
    """Fail closed when a directory path was replaced during a snapshot read."""
    for component, before in snapshot:
        after = component.lstat()
        if (_is_reparse_or_link(after) or
                before.st_dev != after.st_dev or
                before.st_ino != after.st_ino or
                stat.S_IFMT(before.st_mode) != stat.S_IFMT(after.st_mode)):
            raise ValueError("audit directory identity changed during reading")


def _same_open_file(a, b) -> bool:
    """The path's pre/post lstat identity must match the opened descriptor."""
    return (stat.S_ISREG(a.st_mode) and stat.S_ISREG(b.st_mode)
            and a.st_dev == b.st_dev and a.st_ino == b.st_ino)


def _read_bounded_csv(path: Path, *, max_bytes: int) -> tuple[str, int]:
    if not _audit_file_name(path):
        raise ValueError("expected a canonical llm_call_audit_<run_id>.csv filename")
    component_snapshot = _snapshot_path_components(path)
    original = component_snapshot[0][1]
    if _is_reparse_or_link(original):
        raise ValueError("symlink or reparse audit streams are not allowed")
    if not stat.S_ISREG(original.st_mode):
        raise ValueError("audit stream must be a regular file")
    # O_NOFOLLOW closes the path-check/open gap on POSIX. On Windows, where
    # it is not portable, verify the descriptor against both lstat snapshots.
    # O_NONBLOCK avoids indefinite hangs if a file is replaced by a FIFO.
    flags = (os.O_RDONLY | getattr(os, "O_BINARY", 0)
             | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    descriptor = os.open(path, flags)
    with os.fdopen(descriptor, "rb") as stream:
        start = os.fstat(stream.fileno())
        if not _same_open_file(original, start):
            raise ValueError("audit path changed or was redirected during open")
        _verify_path_snapshot(component_snapshot)
        if start.st_size > max_bytes:
            raise ValueError("audit stream exceeds bounded read budget")
        data = stream.read(start.st_size + 1)
        end = os.fstat(stream.fileno())
        current = path.lstat()
        if (_is_reparse_or_link(current) or
                not _same_open_file(current, start) or
                len(data) != start.st_size or
                end.st_size != start.st_size or
                end.st_mtime_ns != start.st_mtime_ns):
            raise ValueError("audit stream changed during reading")
        _verify_path_snapshot(component_snapshot)
    if not data.endswith(b"\n"):
        raise ValueError("audit CSV has an incomplete trailing record")
    try:
        return data.decode("utf-8-sig"), len(data)
    except UnicodeDecodeError as exc:
        raise ValueError("audit CSV has invalid UTF-8") from exc


def _iter_audit_csv_rows(text: str):
    """Parse bounded producer-style CSV without changing global parser state.

    Accept CSV writer quoting, doubled quotes, commas and embedded CR/LF;
    preserve blank physical records as empty rows. Fail closed on malformed
    post-quote material and unterminated quoted fields. Input is already
    UTF-8 decoded and limited by the snapshot byte budget.
    """
    i = 0
    length = len(text)
    row = []
    field = []
    in_quotes = False
    ended_quotes = False
    at_field_start = True
    while i < length:
        ch = text[i]
        if in_quotes:
            if ch == '"':
                if i + 1 < length and text[i + 1] == '"':
                    field.append('"')
                    i += 2
                    continue
                in_quotes = False
                ended_quotes = True
            else:
                field.append(ch)
            i += 1
            continue
        if ch == ',':
            row.append(''.join(field))
            field = []
            at_field_start = True
            ended_quotes = False
            i += 1
            continue
        if ch in '\r\n':
            if row or not at_field_start or ended_quotes:
                row.append(''.join(field))
            yield row
            row = []
            field = []
            at_field_start = True
            ended_quotes = False
            i += 2 if ch == '\r' and i + 1 < length and text[i + 1] == '\n' else 1
            continue
        if ended_quotes:
            raise ValueError("audit CSV has malformed rows")
        if ch == '"' and at_field_start:
            in_quotes = True
            at_field_start = False
        else:
            field.append(ch)
            at_field_start = False
        i += 1
    if in_quotes:
        raise ValueError("audit CSV has malformed rows")
    if row or not at_field_start or ended_quotes:
        row.append(''.join(field))
        yield row


def _summarize_snapshot(path: Path, *, max_bytes: int) -> tuple[dict, int]:
    """Read one snapshot and report the verified bytes for history budgeting."""
    text, actual_size = _read_bounded_csv(path, max_bytes=max_bytes)
    reader = iter(_iter_audit_csv_rows(text))
    headers = next(reader, [])
    if (headers.count("ok") != 1 or headers.count("error") != 1
            or len(headers) != len(set(headers))):
        raise ValueError("audit CSV has invalid or duplicate required headers")
    ok_idx = headers.index("ok")
    error_idx = headers.index("error")
    successful = failed = invalid = 0
    counts = Counter()
    for row in reader:
        # Blank physical CSV rows are malformed observations, not successes.
        # Empty lines inside a quoted error string remain within that field.
        if len(row) != len(headers):
            invalid += 1
            continue
        outcome = row[ok_idx]
        if outcome == "YES":
            successful += 1
        elif outcome == "NO":
            failed += 1
            counts[classify_failed_call(row[error_idx])] += 1
        else:
            invalid += 1
    observed = successful + failed
    # Raw basenames are deliberately omitted: legacy names may embed private
    # document IDs even if they start with the expected audit prefix.
    result = {
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
    return result, actual_size


def summarize_llm_failure_audit(path: str | Path, *, max_bytes: int = MAX_AUDIT_FILE_BYTES) -> dict:
    """Read a bounded, no-follow immutable snapshot; never export file names."""
    if type(max_bytes) is not int or max_bytes <= 0 or max_bytes > MAX_AUDIT_FILE_BYTES:
        raise ValueError("invalid per-file read bound")
    return _summarize_snapshot(Path(path), max_bytes=max_bytes)[0]


def llm_failure_history(folder: str | Path, *, limit: int = 20) -> dict:
    """Latest bounded independent CSV snapshots; never pool run denominators."""
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("limit must be 1..100")
    root = Path(folder)
    # Bind discovery and every subsequent read to one approved directory
    # generation. A replacement with an ordinary directory (not a symlink)
    # must not silently supply a different set of audit files.
    root_snapshot = _snapshot_path_components(root)
    if not stat.S_ISDIR(root_snapshot[0][1].st_mode):
        raise ValueError("audit directory must be a real directory")
    _verify_path_snapshot(root_snapshot)
    found = []
    with os.scandir(root) as entries:
        for index, entry in enumerate(entries):
            if index >= MAX_HISTORY_ENTRIES:
                raise ValueError("audit directory exceeds discovery limit")
            if _audit_file_name(Path(entry.name)) and entry.is_file(follow_symlinks=False):
                found.append(root / entry.name)
    _verify_path_snapshot(root_snapshot)
    selected = sorted(found, key=lambda p: p.name, reverse=True)[:limit]
    snapshots = []
    consumed = 0
    for path in selected:
        _verify_path_snapshot(root_snapshot)
        remaining = MAX_HISTORY_BYTES - consumed
        if remaining <= 0:
            raise ValueError("selected audit history exceeds combined read budget")
        summary, size = _summarize_snapshot(
            path, max_bytes=min(MAX_AUDIT_FILE_BYTES, remaining))
        _verify_path_snapshot(root_snapshot)
        consumed += size
        snapshots.append(summary)
    # Also cover empty directories and swaps after the final selected read.
    _verify_path_snapshot(root_snapshot)
    return {
        "report_version": 1,
        "mode": "run_history",
        "denominator_contract": "observed LLM call attempts only; separate per run",
        "available_run_files": len(found),
        "selected_run_files": len(selected),
        "runs": snapshots,
    }
