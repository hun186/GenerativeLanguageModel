"""Read-only, payload-free evidence report for one LLM audit CSV."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from czjLLM.utilities.llm_lineage_evidence import summarize_llm_lineage_evidence


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Bounded per-run LLM audit correlation coverage (not retry proof)"
    )
    parser.add_argument(
        "--audit-path", type=Path, required=True,
        help="one llm_call_audit_<run_id>.csv (read-only)",
    )
    args = parser.parse_args(argv)
    try:
        report = summarize_llm_lineage_evidence(args.audit_path)
    except (OSError, ValueError) as exc:
        # Never echo user paths, CSV raw error text or endpoint credentials.
        parser.error("invalid, unstable or oversized LLM audit stream")
    print(json.dumps(report, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
