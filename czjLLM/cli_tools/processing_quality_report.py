# -*- coding: utf-8 -*-
"""Read-only, offline reports from the existing per-run quality JSONL streams.

This module never invokes an LLM, opens a database, or modifies an audit log.
Results are observational, not an ES read-after-refresh or cross-sink success gate.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from czjLLM.utilities.atomic_io import atomic_write_json
from czjLLM.utilities.processing_quality import QualityTailReader, quality_event_path

LOW_SAMPLE_ADVISORY_THRESHOLD = 30
_METRIC_DENOMINATORS = {
    "slice_initial_invalid_pct": "slice_validation_attempts",
    "repair_success_pct": "repair_attempts",
    "document_schema_reject_pct": "documents_decided",
}
_FILE_PREFIX = "processing_quality_events_"
_FILE_SUFFIX = ".jsonl"


def summarize_quality_stream(path: str | Path) -> dict[str, Any]:
    """Summarize one explicit log, without including document IDs or event payloads."""
    source = Path(path)
    if source.is_symlink():
        raise ValueError("refusing a symlink quality event stream")
    if not source.is_file():
        raise FileNotFoundError(f"quality event stream does not exist: {source.name}")
    reader = QualityTailReader(str(source))
    _, stats = reader.poll()
    # The writer may append while we read; a partial final line is never counted.
    incomplete = source.stat().st_size > reader.offset
    sample_notes = {}
    for pct, denom in _METRIC_DENOMINATORS.items():
        n = int(stats[denom])
        if n == 0:
            sample_notes[pct] = "no observed denominator; rate is unknown"
        elif n < LOW_SAMPLE_ADVISORY_THRESHOLD:
            sample_notes[pct] = (
                f"small observed denominator (n={n}); interpret rate cautiously"
            )
    return {
        "log_file": source.name,
        "state": "incomplete_tail" if incomplete else (
            "no_valid_events" if not stats["events"] else "observed"
        ),
        "metrics": stats,
        "sample_advisories": sample_notes,
        "incomplete_or_concurrent_append": incomplete,
    }


def report_for_audit(audit_path: str | Path) -> dict[str, Any]:
    """Derive the companion JSONL from the canonical LLM audit CSV filename."""
    audit = Path(audit_path)
    if audit.suffix.lower() != ".csv" or not audit.name.startswith("llm_call_audit_"):
        raise ValueError("expected llm_call_audit_<run_id>.csv")
    companion = quality_event_path(str(audit))
    if companion is None:
        raise ValueError("missing audit path")
    return {
        "report_version": 1,
        "mode": "single_run",
        "denominator_contract": "observed events only; not all processed documents",
        "confirmed_writeback_contract": "explicit sink acknowledgement only (currently ES); not ES readback",
        "run": summarize_quality_stream(companion),
    }


def report_history(audit_dir: str | Path, *, limit: int = 20) -> dict[str, Any]:
    """Show the latest named run streams, ordered by sortable timestamped run ID."""
    directory = Path(audit_dir)
    if not directory.is_dir():
        raise FileNotFoundError(f"audit directory does not exist: {directory}")
    if directory.is_symlink():
        raise ValueError("refusing a symlink audit directory")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
        raise ValueError("limit must be an integer between 1 and 100")
    candidates = sorted(
        (p for p in directory.glob(_FILE_PREFIX + "*" + _FILE_SUFFIX)
         if p.is_file() and not p.is_symlink()),
        key=lambda p: p.name, reverse=True,
    )
    runs = [summarize_quality_stream(p) for p in candidates[:limit]]
    return {
        "report_version": 1,
        "mode": "run_history",
        "denominator_contract": "each run is isolated; no cross-run denominator aggregation",
        "confirmed_writeback_contract": "explicit sink acknowledgement only (currently ES); not ES readback",
        "available_run_files": len(candidates),
        "selected_run_files": len(runs),
        "runs": runs,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Offline read-only quality summary from logs/llm_call_audit"
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--audit-path", type=Path, help="llm_call_audit_<run_id>.csv")
    source.add_argument("--audit-dir", type=Path, help="directory of per-run JSONL logs")
    parser.add_argument("--limit", type=int, default=20, help="history rows (1..100)")
    parser.add_argument("--output", type=Path, help="optional atomic JSON report output")
    args = parser.parse_args(argv)
    try:
        result = (
            report_for_audit(args.audit_path) if args.audit_path is not None
            else report_history(args.audit_dir, limit=args.limit)
        )
        if args.output is not None:
            if args.output.suffix.lower() != ".json":
                raise ValueError("output path must end in .json, not a source log")
            # Never overwrite an input CSV/JSONL. This is a report-only writer.
            atomic_write_json(str(args.output), result, ensure_ascii=False)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
