"""Validate or explicitly initialize the local quality archive consistency ledger."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re

from czjLLM.utilities.processing_quality import quality_event_path
from czjLLM.utilities.processing_quality_manifest import (
    initialize_quality_manifest, verify_quality_manifest,
)

_AUDIT_NAME = re.compile(r"llm_call_audit_[A-Za-z0-9][A-Za-z0-9_.-]{0,100}\.csv\Z")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Inspect quality archive SHA-256 consistency or seal legacy shards once"
    )
    parser.add_argument("--audit-path", type=Path, required=True)
    parser.add_argument(
        "--initialize", action="store_true",
        help="explicit trust-on-first-use: seal existing complete archives once",
    )
    parser.add_argument(
        "--confirm-stopped", action="store_true",
        help="acknowledge all event producers and quality readers are stopped before sealing",
    )
    args = parser.parse_args(argv)
    if not _AUDIT_NAME.fullmatch(args.audit_path.name):
        parser.error("invalid quality audit filename")
    if args.initialize and not args.confirm_stopped:
        parser.error("initialization requires --confirm-stopped")
    if args.confirm_stopped and not args.initialize:
        parser.error("--confirm-stopped is only for --initialize")
    try:
        if args.initialize:
            result = initialize_quality_manifest(args.audit_path)
        else:
            active = quality_event_path(str(args.audit_path))
            if active is None:
                raise ValueError("invalid quality audit filename")
            result = verify_quality_manifest(active)
    except (OSError, ValueError) as exc:
        # Never expose file names, raw JSONL records or other private payload.
        parser.error("quality manifest operation refused: " + type(exc).__name__)
    print(json.dumps({"mode": "quality_archive_manifest", **result}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
