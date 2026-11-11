#!/usr/bin/env python3
"""Private local NDJSON -> fixed aggregate event-time report; no ES/LLM calls."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import stat
import sys

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from czjLLM.common.multidim_time_audit import summarize_stored_documents

MAX_BYTES = 16 * 1024 * 1024
MAX_LINE_BYTES = 512 * 1024


def _identity(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)


def _read_sources(path):
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError("UNSAFE_PATH")
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_BYTES:
        raise ValueError("UNAVAILABLE")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    fd = os.open(path, flags)
    with os.fdopen(fd, "rb") as handle:
        opened = os.fstat(handle.fileno())
        if not stat.S_ISREG(opened.st_mode) or _identity(opened) != _identity(before):
            raise ValueError("CHANGED_DURING_READ")
        payload = handle.read(MAX_BYTES + 1)
        finished = os.fstat(handle.fileno())
    after = path.lstat()
    if (_identity(before) != _identity(finished)
            or _identity(before) != _identity(after)
            or len(payload) != before.st_size or len(payload) > MAX_BYTES):
        raise ValueError("CHANGED_DURING_READ")
    if payload and not payload.endswith(b"\n"):
        raise ValueError("INCOMPLETE_NDJSON")
    lines = payload.splitlines()
    if len(lines) > 20_000:
        raise ValueError("DOCUMENT_LIMIT")
    docs = []
    for line in lines:
        if not line or len(line) > MAX_LINE_BYTES:
            raise ValueError("MALFORMED_NDJSON")
        doc = json.loads(line.decode("utf-8"))
        if not isinstance(doc, dict):
            raise ValueError("MALFORMED_NDJSON")
        docs.append(doc)
    return docs


def collect(path):
    try:
        docs = _read_sources(path)
        return summarize_stored_documents(docs)
    except (OSError, ValueError, UnicodeError, TypeError, KeyError, OverflowError):
        return {
            "schema_version": 1,
            "status": "UNAVAILABLE",
            "reason_code": "UNVERIFIED_INPUT",
            "source_date_fidelity": "NOT_VERIFIED",
            "actual_rerun_policy": "NOT_CHANGED_OR_EVALUATED",
            "sink_writeback": "NOT_PERFORMED",
            "safety": "READ_ONLY_NO_ES_NO_LLM_NO_REPLAY",
        }


def human(report):
    lines = [
        "【多維事件時間・唯讀稽核】",
        "狀態：" + report["status"],
        "不連接 ES／LLM，不重跑、不覆寫任何資料。",
    ]
    if "counts" in report:
        labels = {
            "EVENT_DATE_EMPTY_TIMELINE": "Event 有合規日期、Timeline 為空（舊規則可能誤判）",
            "EVENT_AND_TIMELINE_DATES": "Event 與 Timeline 皆有合規日期",
            "EVENT_DATE_OTHER_TIMELINE": "Event 有合規日期、Timeline 無合規日期但非空",
            "TIMELINE_DATE_ONLY": "只有 Timeline 有合規日期",
            "NO_RELIABLE_DATE": "沒有已驗證日期（不代表原文沒有日期）",
            "INVALID_TIME_FIELDS": "時間欄位無法通過現有 Profile 規則",
            "UNVERIFIED_STRUCTURE": "結構或欄位證據不足",
        }
        lines.append("觀察筆數：" + str(report["total_documents"]))
        for code, label in labels.items():
            lines.append(label + "：" + str(report["counts"][code]))
    else:
        lines.append("輸入不可驗證，不把缺失資料視為成功。")
    lines.append("此報告未驗證原文日期忠實性，未修改實際重跑政策。")
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Aggregate-only multidim event time audit from local NDJSON."
    )
    parser.add_argument("--input-ndjson", required=True, type=Path,
                        help="Exact local NDJSON path; never printed.")
    parser.add_argument("--human", action="store_true")
    args = parser.parse_args(argv)
    result = collect(args.input_ndjson)
    print(human(result) if args.human
          else json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["status"] == "OBSERVED_NOT_PROVEN" else 2


if __name__ == "__main__":
    raise SystemExit(main())
