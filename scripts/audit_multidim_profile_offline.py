#!/usr/bin/env python3
"""Private NDJSON -> fixed, aggregate Output Profile observations; no ES I/O."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from czjLLM.common.multidim_profile_audit import CATEGORIES, summarize_stored_profiles
from scripts.audit_multidim_event_time import _read_sources


def collect(path: Path) -> dict:
    try:
        return summarize_stored_profiles(_read_sources(path))
    except Exception:
        # Avoid raw parser, path and Profile errors even on malformed exports.
        return {
            "schema_version": 1,
            "status": "UNAVAILABLE",
            "reason_code": "UNVERIFIED_INPUT",
            "actual_rerun_policy": "NOT_EVALUATED",
            "sink_writeback": "NOT_PERFORMED",
            "safety": "READ_ONLY_NO_ES_NO_LLM_NO_REPLAY",
        }


def human(report: dict) -> str:
    labels = {
        "SOURCE_UNVERIFIED": "來源封套無法驗證",
        "OUTPUT_ABSENT": "目標輸出缺失或為空",
        "PROFILE_REJECTED": "現有 Output Profile 不接受",
        "PROFILE_ACCEPTED_NO_EVENTS": "Profile 接受但 Event 為空",
        "PROFILE_ACCEPTED_EVENT_DATE_EMPTY_TIMELINE":
            "Profile 接受：Event 有日期、Timeline 明示為空",
        "PROFILE_ACCEPTED_EVENT_AND_TIMELINE_DATES":
            "Profile 接受：Event／Timeline 皆有日期",
        "PROFILE_ACCEPTED_TIMELINE_DATE_ONLY":
            "Profile 接受：僅 Timeline 有日期",
        "PROFILE_ACCEPTED_EVENT_DATE_OTHER":
            "Profile 接受：Event 有日期、Timeline 未驗證為全空",
        "PROFILE_ACCEPTED_DATE_UNKNOWN":
            "Profile 接受：沒有可驗證的日期",
    }
    lines = [
        "【多維事件 Output Profile・唯讀稽核】",
        "狀態：" + report["status"],
        "不連接 ES／LLM，不重跑、不寫回，也不輸出原文或文件 ID。",
    ]
    if report["status"] == "OBSERVED_NOT_PROVEN":
        lines.append("觀察筆數：" + str(report["total_documents"]))
        for code in CATEGORIES:
            lines.append(labels[code] + "：" + str(report["counts"][code]))
    else:
        lines.append("輸入不可驗證，沒有可使用的部分統計。")
    lines.append("Profile 格式合規不等於來源語意正確、SRAF 可檢索或實際可跳過重跑。")
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Read-only saved multidim Output Profile aggregate (no ES connection)."
    )
    parser.add_argument(
        "--input-ndjson", required=True, type=Path, help="Private local file; path never printed."
    )
    parser.add_argument("--human", action="store_true")
    args = parser.parse_args(argv)
    result = collect(args.input_ndjson)
    print(human(result) if args.human
          else json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["status"] == "OBSERVED_NOT_PROVEN" else 2


if __name__ == "__main__":
    raise SystemExit(main())
