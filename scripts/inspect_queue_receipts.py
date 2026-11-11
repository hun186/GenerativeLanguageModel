#!/usr/bin/env python3
"""Read-only inventory of ONE explicitly selected per-run Queue Meter."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from czjLLM.job_manager.document_progress import read_meter_strict
from czjLLM.job_manager.queue_receipt_inventory import summarize_meter


def _identity(info):
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns


def collect(meter_file: Path):
    """No implicit newest-run selection or inspection of source/Queue files."""
    try:
        before = meter_file.lstat()
        meter = read_meter_strict(meter_file)
        after = meter_file.lstat()
        if _identity(before) != _identity(after):
            raise ValueError("meter changed during inventory")
        return summarize_meter(meter)
    except (ValueError, TypeError, KeyError, OSError, UnicodeError):
        # Never echo the exception: it may contain an absolute private path.
        return {
            "schema_version": 1,
            "status": "UNAVAILABLE",
            "source": "EXPLICIT_RUN_METER",
            "reason_code": "UNVERIFIED_METER",
            "gpu_utilization": "NOT_MEASURED",
            "sink_readback": "NOT_MEASURED",
            "safety": "READ_ONLY_NO_ACK_NO_REPLAY_NO_CLEANUP",
        }


def human_summary(report):
    """Fixed labels and numeric counts only; no user-controlled identifiers."""
    lines = [
        "【Queue 收據唯讀盤點】",
        "資料狀態：" + report["status"],
        "來源：明確指定的一次 Run Meter（不自動猜測最新 Run）",
        "不會檢查 GPU、HTTP、SQL／ES 寫回，也不會清除／重送 Queue。",
    ]
    queue = report.get("queue")
    if queue is not None:
        lines.append(
            "全域 Queue：pending={}，running={}，completed={}".format(
                queue["pending"] if queue["pending"] is not None else "未知",
                queue["running"] if queue["running"] is not None else "未知",
                queue["completed"] if queue["completed"] is not None else "未知",
            )
        )
        rows = report["row_receipts"]
        lines.append(
            "列收據：共 {} 列；歸零 {}，仍有工作 {}，未知 {}。".format(
                rows["total_rows"], rows["settled_rows"],
                rows["outstanding_rows"], rows["unknown_receipt_rows"],
            )
        )
        lines.append(
            "已標終態但收據未歸零：{} 列（running {}／pending {}）。".format(
                rows["terminal_rows_with_outstanding_receipts"],
                rows["terminal_running_receipts"],
                rows["terminal_pending_receipts"],
            )
        )
        lines.append(
            "已標終態但收據未知：{} 列。".format(
                rows["terminal_rows_with_unknown_receipts"],
            )
        )
    else:
        lines.append("Meter 不可驗證；不以缺失資料推論 Queue 已清空。")
    lines.append("以上僅為非原子唯讀快照，不代表可安全復原或已完成寫回。")
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Read-only aggregate Queue receipt inventory; explicit meter required."
    )
    parser.add_argument(
        "--meter-file", type=Path, required=True,
        help="Exact per-run loadmeter_*.json path (never printed, no auto-discovery).",
    )
    parser.add_argument("--human", action="store_true",
                        help="Traditional Chinese fixed-label summary.")
    args = parser.parse_args(argv)
    report = collect(args.meter_file)
    print(human_summary(report) if args.human
          else json.dumps(report, ensure_ascii=False, sort_keys=True))
    # Exit 0 means the snapshot was parsable, NOT that Queue or sink is healthy.
    return 0 if report["status"] == "OBSERVED_NOT_PROVEN" else 2


if __name__ == "__main__":
    raise SystemExit(main())
