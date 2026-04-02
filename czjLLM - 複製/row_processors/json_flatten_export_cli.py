#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
通用 CLI：讀取 JSON 物件 txt 檔（頂層陣列或 NDJSON）→ 展平 → 輸出 Excel 與/或 SQLite

需求：
  pip install pandas openpyxl

範例：
  python json_flatten_export_cli.py -i merged.txt -x out/data.xlsx -S out/data.db \
    --table-name records --int-cols rank_in_facet,rank_global,is_in_global_top10,importance_score,impact,novelty,coverage,credibility \
    --date-cols date_start,date_end \
    --select-cols group_key,facet_code,rank_in_facet,title,summary,date_start,date_end,importance_score,impact,coverage,credibility,novelty,generated_at,version \
    --rename title_tw:title --rename summary_tw:summary
"""

from __future__ import annotations
import argparse
import json
import os
import sys
import sqlite3
import datetime
from typing import List, Dict, Any, Optional, Sequence

import pandas as pd

# -------------------------- 檔案與輸入 -------------------------- #

def _ensure_parent_dir(path: str) -> None:
    d = os.path.dirname(os.path.abspath(path))
    if d and not os.path.exists(d):
        os.makedirs(d, exist_ok=True)

def load_records_from_txt(json_txt_path: str, *, encoding: str = "utf-8-sig") -> List[Dict[str, Any]]:
    """
    讀入 txt 檔，支援：
      1) 頂層陣列 JSON：[{...},{...}]
      2) NDJSON：每行一筆 JSON
    """
    with open(json_txt_path, "r", encoding=encoding) as f:
        first = f.read(1)
        f.seek(0)
        if first == "[":
            data = json.load(f)
            if not isinstance(data, list):
                raise ValueError("頂層必須是 JSON 陣列（[{...},{...}]）。")
            for i, r in enumerate(data, 1):
                if not isinstance(r, dict):
                    raise ValueError(f"第 {i} 筆非 JSON 物件：{type(r)}")
            return data
        else:
            records: List[Dict[str, Any]] = []
            for ln, line in enumerate(f, 1):
                s = line.strip()
                if not s:
                    continue
                try:
                    rec = json.loads(s)
                except json.JSONDecodeError as e:
                    raise ValueError(f"第 {ln} 行不是合法 JSON：{e}") from e
                if not isinstance(rec, dict):
                    raise ValueError(f"第 {ln} 行 JSON 非物件：{rec!r}")
                records.append(rec)
            return records

# -------------------------- 欄位處理 -------------------------- #

def _parse_csv_list(s: Optional[str]) -> Optional[List[str]]:
    if not s:
        return None
    return [x.strip() for x in s.split(",") if x.strip()]

def _parse_renames(pairs: Optional[List[str]]) -> Dict[str, str]:
    """
    解析 --rename old:new 多次指定
    """
    mapping: Dict[str, str] = {}
    if not pairs:
        return mapping
    for p in pairs:
        if ":" not in p:
            raise ValueError(f"--rename 格式錯誤：{p}（需為 old:new）")
        old, new = p.split(":", 1)
        old, new = old.strip(), new.strip()
        if not old or not new:
            raise ValueError(f"--rename 空白欄名：{p}")
        mapping[old] = new
    return mapping

def _project_columns(
    df: pd.DataFrame,
    *,
    select_cols: Optional[Sequence[str]] = None,
    drop_cols: Optional[Sequence[str]] = None,
    rename_map: Optional[Dict[str, str]] = None,
    ensure_cols: Optional[Sequence[str]] = None,
    int_cols: Optional[Sequence[str]] = None
) -> pd.DataFrame:
    # 先改名，避免後續 select/drop 名稱不一致
    if rename_map:
        df = df.rename(columns=rename_map)

    # 白名單（同時決定輸出順序）
    if select_cols:
        for c in select_cols:
            if c not in df.columns:
                if int_cols and c in int_cols:
                    df[c] = pd.Series([pd.NA] * len(df), dtype="Int64")
                else:
                    df[c] = ""
        df = df[[c for c in select_cols]]
    else:
        # 黑名單
        if drop_cols:
            df = df.drop(columns=[c for c in drop_cols if c in df.columns], errors="ignore")

    # 確保固定欄位存在
    if ensure_cols:
        for c in ensure_cols:
            if c not in df.columns:
                if int_cols and c in int_cols:
                    df[c] = pd.Series([pd.NA] * len(df), dtype="Int64")
                else:
                    df[c] = ""

    return df

# -------------------------- 展平與轉型 -------------------------- #

def normalize_df(
    records: List[Dict[str, Any]],
    *,
    sep: str = "_",
    int_cols: Optional[Sequence[str]] = None,
    date_cols: Optional[Sequence[str]] = None,
    list_joiner: str = "|",
    force_str: bool = True,
    select_cols: Optional[Sequence[str]] = None,
    drop_cols: Optional[Sequence[str]] = None,
    rename_map: Optional[Dict[str, str]] = None,
    ensure_cols: Optional[Sequence[str]] = None
) -> pd.DataFrame:
    """
    展平成 DataFrame：
      - 巢狀鍵以 sep 串接
      - list 欄位串接為字串（list_joiner）
      - 指定整數/日期欄位轉型
      - 欄位白名單/黑名單/改名/補欄
      - 可選：強制非 Int 欄位轉字串（避免 Excel 自動轉型）
    """
    if not records:
        return pd.DataFrame()

    df = pd.json_normalize(records, sep=sep)

    # 將仍是 list 的欄位串接為字串
    for c in df.columns:
        if df[c].apply(lambda x: isinstance(x, list)).any():
            df[c] = df[c].apply(lambda v: list_joiner.join(map(str, v)) if isinstance(v, list) else v)

    # 整數欄位 → Int64（可空）
    if int_cols:
        for c in int_cols:
            if c in df.columns:
                df[c] = pd.to_numeric(df[c], errors="coerce").astype("Int64")

    # 日期欄位 → yyyy-mm-dd
    if date_cols:
        for c in date_cols:
            if c in df.columns:
                dt = pd.to_datetime(df[c], errors="coerce", utc=False)
                df[c] = dt.dt.strftime("%Y-%m-%d")

    # 補 generated_at（如未提供）
    if "generated_at" not in df.columns:
        now = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
        df.insert(0, "generated_at", now)

    # 欄位投影/改名/補欄
    df = _project_columns(
        df,
        select_cols=select_cols,
        drop_cols=drop_cols,
        rename_map=rename_map,
        ensure_cols=ensure_cols,
        int_cols=int_cols
    )

    # 強制字串（保留 Int64 欄位）
    if force_str:
        int_set = set(int_cols or [])
        for c in df.columns:
            if c not in int_set:
                df[c] = df[c].astype(str)

    return df

# -------------------------- 輸出 -------------------------- #

def export_to_excel(
    df: pd.DataFrame,
    excel_path: str,
    sheet_name: str = "data",
    max_width_sample: int = 500
) -> None:
    """輸出 Excel：凍結首列、篩選、自動欄寬（取樣 max_width_sample 筆）。"""
    _ensure_parent_dir(excel_path)
    try:
        import openpyxl  # noqa: F401
    except Exception as e:
        raise RuntimeError("需要安裝 openpyxl 才能輸出 Excel：pip install openpyxl") from e

    with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name=sheet_name, index=False)
        ws = writer.sheets[sheet_name]
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = ws.dimensions

        try:
            from openpyxl.utils import get_column_letter
            sample_n = min(len(df), max_width_sample)
            for idx, col in enumerate(df.columns, start=1):
                series = df[col].iloc[:sample_n].astype(str)
                max_len = max([len(str(col))] + [len(x) for x in series])
                ws.column_dimensions[get_column_letter(idx)].width = max(12, min(max_len + 2, 60))
        except Exception:
            pass  # 欄寬設定失敗不影響資料

def export_to_sqlite(
    df: pd.DataFrame,
    sqlite_path: str,
    table_name: str = "records",
    *,
    if_exists: str = "replace",
    chunksize: int = 1000
) -> None:
    """輸出 SQLite；if_exists 可選 replace 或 append。"""
    if if_exists not in {"replace", "append"}:
        raise ValueError("--sqlite-if-exists 僅能為 replace 或 append")
    _ensure_parent_dir(sqlite_path)
    with sqlite3.connect(sqlite_path) as conn:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        df.to_sql(table_name, conn, if_exists=if_exists, index=False, chunksize=chunksize)

# -------------------------- 主流程 -------------------------- #

def flatten_and_export(
    json_txt_path: str,
    *,
    excel_path: Optional[str] = None,
    sqlite_path: Optional[str] = None,
    table_name: str = "records",
    sep: str = "_",
    int_cols: Optional[Sequence[str]] = None,
    date_cols: Optional[Sequence[str]] = None,
    list_joiner: str = "|",
    force_str: bool = True,
    select_cols: Optional[Sequence[str]] = None,
    drop_cols: Optional[Sequence[str]] = None,
    rename_map: Optional[Dict[str, str]] = None,
    ensure_cols: Optional[Sequence[str]] = None,
    sqlite_if_exists: str = "replace",
    sqlite_chunksize: int = 1000,
    sheet_name: str = "data",
    max_width_sample: int = 500,
    encoding: str = "utf-8-sig"
) -> Dict[str, Any]:
    if not excel_path and not sqlite_path:
        raise ValueError("至少指定 --excel 或 --sqlite 其中一種輸出。")

    records = load_records_from_txt(json_txt_path, encoding=encoding)
    df = normalize_df(
        records,
        sep=sep,
        int_cols=int_cols,
        date_cols=date_cols,
        list_joiner=list_joiner,
        force_str=force_str,
        select_cols=select_cols,
        drop_cols=drop_cols,
        rename_map=rename_map,
        ensure_cols=ensure_cols,
    )

    outputs = {}
    if excel_path:
        export_to_excel(df, excel_path, sheet_name=sheet_name, max_width_sample=max_width_sample)
        outputs["excel_path"] = os.path.abspath(excel_path)

    if sqlite_path:
        export_to_sqlite(
            df, sqlite_path, table_name=table_name,
            if_exists=sqlite_if_exists, chunksize=sqlite_chunksize
        )
        outputs["sqlite_path"] = os.path.abspath(sqlite_path)
        outputs["sqlite_table"] = table_name
        outputs["sqlite_if_exists"] = sqlite_if_exists

    return {
        "rows": int(len(df)),
        "columns": list(df.columns),
        **outputs
    }

# -------------------------- CLI -------------------------- #

def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="json_flatten_export_cli",
        description="讀取 JSON 陣列或 NDJSON → 展平 → 輸出 Excel / SQLite（可同時）。"
    )
    p.add_argument("-i", "--input", required=True, help="輸入 txt 檔（JSON 陣列或 NDJSON）")
    p.add_argument("-x", "--excel", help="輸出 Excel 路徑（.xlsx）")
    p.add_argument("-S", "--sqlite", help="輸出 SQLite 路徑（.db 或 .sqlite）")
    p.add_argument("--table-name", default="records", help="SQLite 資料表名稱（預設：records）")
    p.add_argument("--sqlite-if-exists", choices=["replace", "append"], default="replace",
                   help="SQLite 寫入策略（replace/append，預設 replace）")
    p.add_argument("--sqlite-chunksize", type=int, default=1000, help="SQLite 批次寫入筆數（預設 1000）")
    p.add_argument("--sheet-name", default="data", help="Excel 工作表名稱（預設 data）")
    p.add_argument("--max-width-sample", type=int, default=500, help="自動欄寬取樣筆數（預設 500）")
    p.add_argument("--encoding", default="utf-8-sig", help="輸入檔編碼（預設 utf-8-sig）")

    # 結構與型別
    p.add_argument("--sep", default="_", help="巢狀鍵展平用分隔符（預設 _ ）")
    p.add_argument("--list-joiner", default="|", help="list 欄位串接符（預設 | ）")
    p.add_argument("--int-cols", help="要轉為整數(Int64)之欄位，逗號分隔")
    p.add_argument("--date-cols", help="要轉為日期(yyyy-mm-dd)之欄位，逗號分隔")
    p.add_argument("--no-force-str", action="store_true", help="不要強制非 Int 欄位轉為字串")

    # 欄位控制
    p.add_argument("--select-cols", help="白名單＋輸出順序（逗號分隔）。指定後將忽略 drop-cols。")
    p.add_argument("--drop-cols", help="黑名單（逗號分隔）。僅在未指定 select-cols 時生效。")
    p.add_argument("--ensure-cols", help="固定必出欄位（逗號分隔），缺則補空值/NA。")
    p.add_argument("--rename", action="append",
                   help="改名規則，可多次指定。格式 old:new，例如 --rename title_tw:title")

    return p

def main(argv: Optional[List[str]] = None) -> int:
    ap = build_arg_parser()
    args = ap.parse_args(argv)

    try:
        result = flatten_and_export(
            json_txt_path=args.input,
            excel_path=args.excel,
            sqlite_path=args.sqlite,
            table_name=args.table_name,
            sep=args.sep,
            int_cols=_parse_csv_list(args.int_cols),
            date_cols=_parse_csv_list(args.date_cols),
            list_joiner=args.list_joiner,
            force_str=not args.no_force_str,
            select_cols=_parse_csv_list(args.select_cols),
            drop_cols=_parse_csv_list(args.drop_cols),
            rename_map=_parse_renames(args.rename),
            ensure_cols=_parse_csv_list(args.ensure_cols),
            sqlite_if_exists=args.sqlite_if_exists,
            sqlite_chunksize=args.sqlite_chunksize,
            sheet_name=args.sheet_name,
            max_width_sample=args.max_width_sample,
            encoding=args.encoding,
        )
        # 將處理摘要以 JSON 輸出到 stdout，便於管線化
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Exception as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        return 1

if __name__ == "__main__":
    sys.exit(main())
