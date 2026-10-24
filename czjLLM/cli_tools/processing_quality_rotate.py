"""Explicit no-delete quality JSONL maintenance rotation. Stop producers first."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re

from czjLLM.utilities.processing_quality_rotation import (
    MAX_QUALITY_SEGMENTS, rotate_quality_event_stream,
)

_CANONICAL_AUDIT = re.compile(
    r"llm_call_audit_[A-Za-z0-9][A-Za-z0-9_.-]{0,100}\.csv\Z"
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Manually rotate one completed, per-run quality JSONL without deleting data"
    )
    parser.add_argument("--audit-path", type=Path, required=True)
    parser.add_argument(
        "--confirm-stopped", action="store_true",
        help="confirm all writers and live quality-report readers are stopped",
    )
    parser.add_argument(
        "--max-segments", type=int, default=MAX_QUALITY_SEGMENTS,
        help=f"hard cap for archived generations, max {MAX_QUALITY_SEGMENTS}",
    )
    args = parser.parse_args(argv)
    if not args.confirm_stopped:
        parser.error("stop producers and readers, then explicitly pass --confirm-stopped")
    if not _CANONICAL_AUDIT.fullmatch(args.audit_path.name):
        parser.error("expected canonical llm_call_audit_<run_id>.csv filename")
    try:
        result = rotate_quality_event_stream(
            args.audit_path, max_segments=args.max_segments,
        )
    except (OSError, ValueError) as exc:
        parser.error(f"rotation refused: {type(exc).__name__}")
    print(json.dumps({"mode": "manual_quality_rotation", **result}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
