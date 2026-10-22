"""Offline read-only LLM call failure taxonomy report (not document failures)."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import sys

from czjLLM.utilities.atomic_io import atomic_write_json
from czjLLM.utilities.llm_failure_summary import (
    llm_failure_history, summarize_llm_failure_audit,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Payload-free LLM-call failure audit summary")
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--audit-path", type=Path, help="one llm_call_audit_<run_id>.csv")
    inputs.add_argument("--audit-dir", type=Path, help="per-run audit CSV directory")
    parser.add_argument("--limit", type=int, default=20, help="maximum history runs (1..100)")
    parser.add_argument("--output", type=Path, help="optional separate atomic JSON report")
    args = parser.parse_args(argv)
    try:
        if args.audit_path is not None:
            result = {
                "report_version": 1,
                "mode": "single_run",
                "denominator_contract": "observed LLM call attempts; not whole-pipeline or document rate",
                "run": summarize_llm_failure_audit(args.audit_path),
            }
        else:
            result = llm_failure_history(args.audit_dir, limit=args.limit)
        if args.output is not None:
            destination = args.output
            if destination.suffix.lower() != ".json" or destination.is_symlink():
                raise ValueError("report output must be a non-symlink .json file")
            source_dir = args.audit_path.parent if args.audit_path else args.audit_dir
            if destination.resolve(strict=False).parent == source_dir.resolve(strict=True):
                if destination.name.startswith(("llm_call_audit_", "processing_quality_events_")):
                    raise ValueError("refusing to overwrite an audit artifact")
            atomic_write_json(str(destination), result)
    except (OSError, ValueError, csv.Error) as exc:
        # Do not echo untrusted error bodies, paths or credentials.
        parser.error("audit failed: invalid/unstable input, budget or output location")
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
