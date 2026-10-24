"""Read-only diagnosis or operator-approved rollback of interrupted JSONL rotation."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from czjLLM.utilities.processing_quality_recovery import (
    inspect_interrupted_rotation, rollback_interrupted_rotation,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Inspect sealed quality archive recovery without touching event data"
    )
    parser.add_argument("--audit-path", type=Path, required=True)
    parser.add_argument(
        "--rollback", action="store_true",
        help="restore one unmatched unsealed archive to the absent active file",
    )
    parser.add_argument(
        "--confirm-stopped", action="store_true",
        help="acknowledge all event producers and GUI readers are stopped",
    )
    args = parser.parse_args(argv)
    if args.rollback and not args.confirm_stopped:
        parser.error("--rollback requires --confirm-stopped")
    if args.confirm_stopped and not args.rollback:
        parser.error("--confirm-stopped is only valid with --rollback")
    try:
        result = (
            rollback_interrupted_rotation(args.audit_path) if args.rollback
            else inspect_interrupted_rotation(args.audit_path)
        )
    except (OSError, ValueError) as exc:
        # A raw exception may contain local paths or sensitive source identity.
        parser.error("quality rotation recovery refused: " + type(exc).__name__)
    print(json.dumps({"mode": "quality_rotation_recovery", **result}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
