#!/usr/bin/env python3
"""Bounded, metadata-only queue recovery follow-up for a stopped/live run.

One shot by default. --watch performs a finite number of cooldown-spaced
rechecks; schedule it explicitly in the deployment environment to run after
the main producer exits. Never invokes LLM, SQL/ES writes or full_restart.
Inputs and JSON output never disclose source text, item paths or filenames.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
import sys


def inspect_once(item_dirs):
    from czjLLM.prompt_pipeline.runtime_support.prompt_queue import (
        QueueClaimRollbackError, recheck_blocked_recovery,
    )
    results = []
    for ordinal, item in enumerate(item_dirs, 1):
        try:
            observation = recheck_blocked_recovery(item)
            results.append({
                "item": ordinal,
                "outcome": observation["outcome"],
                "checks": observation["checks"],
            })
        except (QueueClaimRollbackError, OSError, ValueError):
            # Unknown/corrupt markers cannot be auto-cleared.
            results.append({
                "item": ordinal, "outcome": "operator_required", "checks": None,
            })
    statuses = [r["outcome"] for r in results]
    return {
        "version": 1, "mode": "metadata_only_non_atomic",
        "items": results,
        "blocked_items": sum(x not in {"clear", "recovered"} for x in statuses),
        "manual_review_required": "operator_required" in statuses,
        "all_recovered_or_clear": all(x in {"clear", "recovered"} for x in statuses),
        "warning": "A returned TODO is PENDING, not confirmed Success or sink writeback.",
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--item-dir", action="append", required=True)
    parser.add_argument("--watch", action="store_true",
                        help="Finite periodic recheck; never an infinite service")
    parser.add_argument("--interval", type=int, default=30,
                        help="Seconds between observed checks; at least 30")
    parser.add_argument("--max-rounds", type=int, default=5,
                        help="At most 5 watch polls; no unbounded retries")
    args = parser.parse_args(argv)
    if (len(args.item_dir) > 100 or args.interval < 30
            or not 1 <= args.max_rounds <= 5):
        parser.error("maximum 100 items; interval >=30; max-rounds 1..5")
    report = None
    for index in range(args.max_rounds if args.watch else 1):
        report = inspect_once(args.item_dir)
        print(json.dumps(report, sort_keys=True, ensure_ascii=True), flush=True)
        if report["all_recovered_or_clear"] or report["manual_review_required"]:
            break
        if args.watch and index + 1 < args.max_rounds:
            time.sleep(args.interval)
    if report["manual_review_required"]:
        return 2
    return 0 if report["all_recovered_or_clear"] else 1


if __name__ == "__main__":
    if not __package__:
        module_root = str(Path(__file__).resolve().parent.parent)
        if module_root not in sys.path:
            sys.path.insert(0, module_root)
    raise SystemExit(main())
