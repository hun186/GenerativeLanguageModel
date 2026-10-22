"""Count legacy Reduction artifacts without inspecting payloads or writing files."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict

from czjLLM.reduction.maintenance import inventory_legacy_reduction_artifacts
from czjLLM.reduction.retention import (
    DEFAULT_SCAN_LIMIT,
    item_retention_root,
    prompt_container_retention_root,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Read-only bounded inventory of unmarked Reduction artifacts (never migrates/deletes)."
    )
    parser.add_argument("--item-root", action="append", default=[], metavar="DIR",
                        help="Approved individual item directory (repeatable)")
    parser.add_argument("--prompt-root", action="append", default=[], metavar="DIR",
                        help="Approved prompt container; inspect immediate item directories only")
    parser.add_argument("--max-scan-entries", type=int, default=DEFAULT_SCAN_LIMIT,
                        metavar="N", help="Shared discovery bound (default: 10000)")
    args = parser.parse_args(argv)
    if not args.item_root and not args.prompt_root:
        parser.error("specify at least one --item-root or --prompt-root")
    roots = [item_retention_root(path) for path in args.item_root]
    roots += [prompt_container_retention_root(path) for path in args.prompt_root]
    try:
        report = inventory_legacy_reduction_artifacts(
            roots, max_scan_entries=args.max_scan_entries,
        )
    except (OSError, ValueError, RuntimeError):
        # Do not expose absolute source paths or filesystem exception bodies.
        print("Inventory failed: invalid root, scan bound, or inaccessible entry.",
              file=sys.stderr)
        return 2
    print(json.dumps(asdict(report), sort_keys=True, separators=(",", ":")))
    return 2 if report.scan_limit_reached else 0


if __name__ == "__main__":
    raise SystemExit(main())
