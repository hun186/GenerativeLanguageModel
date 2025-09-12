# tabular_mode/entry/steps.py
import os
import math
#from pathlib import Path
from typing import Tuple, List, Iterable

import pandas as pd
from utils.selector import OptionSelector
from utils.utilities_path import OSWALK, smart_detect_path, MKDIR
#from cli_tools.cli_utils import print_cli_usage_hint  # 若要在這層顯示提示可用
from job_manager.console_ui import tlog, tlog_warn

# 你現有的工具（同 excel 版）
from utilities.excel_utils import (
    read_dataframe, write_dataframe, backup_table_file, write_dataframe_sheet
)
from excel_mode.schema.subtable_ops import ensure_excel_subtable_config

# 直接沿用 SQL 那份互動式展平問答
#from sql_mode.entry.steps import configure_flatten_options as configure_flatten_common
from sql_mode.entry.steps import configure_flatten_options as _configure_flatten_sql


# ---------------------------
# Helpers
# ---------------------------
def _fmt_from_path(p: str) -> str:
    p = (p or "").lower()
    return "csv" if p.endswith(".csv") else "excel"

def _normalize_empty(v) -> str:
    if v is None:
        return ""
    # NaN
    try:
        if isinstance(v, float) and math.isnan(v):
            return ""
    except Exception:
        pass
    if isinstance(v, str):
        s = v.strip().lower()
        return "" if s in {"", "nan", "none", "null"} else v
    return v

def _is_empty(v) -> bool:
    if v is None:
        return True
    try:
        if isinstance(v, float) and math.isnan(v):
            return True
    except Exception:
        pass
    if isinstance(v, str):
        return v.strip().lower() in {"", "nan", "none", "null"}
    return False


# ---------------------------
# 1) 路徑解析（互動選檔）
# ---------------------------
def resolve_tabular_paths(ctx, get_param, args) -> Tuple[str, str]:
    """
    回傳 (input_path, output_path)；支援 .xlsx/.csv 混排清單中互動選檔。
    預設 output = input + '_with_result' + ext
    """
    # 先看 config 顯式設定
    input_path = get_param("input_excel_file") or get_param("input_csv_file")
    output_path = get_param("output_excel_file") or get_param("output_csv_file")

    if not input_path:
        base_dir = os.path.join(ctx.llm_source_dir)
        MKDIR(base_dir)
        candidates = [
            f for f in OSWALK(base_dir)
            if (f.lower().endswith(".xlsx") or f.lower().endswith(".csv"))
            and "_backup_excel" not in f
        ]
        if not candidates:
            raise FileNotFoundError(f"找不到 Excel/CSV 於：{base_dir}")

        options = {os.path.basename(f): f for f in candidates}
        chosen = OptionSelector(options=options, question="📄 請選擇欲處理的 Excel/CSV：").proc()
        input_path = options[chosen]

    input_path = smart_detect_path(ctx.PGMSubDir, input_path)
    if not input_path:
        raise FileNotFoundError("❌ 找不到指定的 Excel/CSV 檔案")

    # 預設輸出路徑：沿用副檔名
    if not output_path:
        base, ext = os.path.splitext(input_path)
        output_path = base + "_with_result" + ext

    output_path = smart_detect_path(ctx.PGMSubDir, output_path) or output_path
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    return input_path, output_path


# ---------------------------
# 2) 選欄（input / output / pk / update_time）
# ---------------------------
def choose_columns_common(ctx, input_path: str, get_param, args) -> List[str]:
    df_src = read_dataframe(input_path, nrows=2)
    columns = list(df_src.columns)

    # input_col
    ctx.input_col = get_param("input_col")
    if not ctx.input_col or ctx.input_col not in columns:
        ctx.input_col = OptionSelector(
            options={c: "" for c in columns},
            question="🔍 請選擇輸入欄位："
        ).proc()

    # primary_key（支援 row_id）
    pk_hint = (get_param("primary_key") or "").strip()
    if pk_hint and pk_hint in columns:
        ctx.primary_key = pk_hint
    else:
        candidates = {c: "" for c in columns}
        candidates["row_id"] = "使用列序作為主鍵"
        ctx.primary_key = OptionSelector(
            options=candidates,
            question="🔑 請選擇主鍵欄位（或選 row_id）：",
            default="row_id"
        ).proc()

    # output_col
    ctx.output_col = get_param("output_col")
    if not ctx.output_col:
        default_out = f"{ctx.input_col}_result"
        ctx.output_col = input(f"💾 請輸入輸出欄位（預設 {default_out}）：").strip() or default_out

    # record_update_time
    ctx.record_update_time = get_param("record_update_time")
    if ctx.record_update_time is None:
        ctx.record_update_time = (input("⏱️ 每筆更新要寫入 update_time？(Y/n)：").strip().lower() != "n")

    return columns


# ---------------------------
# 3) 展平設定（共用語意修正）
# ---------------------------
def configure_flatten_common(ctx, get_param, args) -> None:
    """
    先跑原本 SQL 版的互動設定，再套共用規則：
    - 若 pk == input_col，則不把 raw input 另外寫入子表（避免重複/衝突）
      → ctx.save_raw_input_when_flatten = False
      → ctx.subtable_input_col = None
    - 否則，若有啟用保留原始輸入，則 ctx.subtable_input_col = ctx.input_col
    """
    # 1) 先讓原本的互動式選項把 ctx.flatten_json_output / allowed_output_fields /
    #    save_raw_input_when_flatten 等旗標設定好
    _configure_flatten_sql(ctx, get_param, args)

    # 2) 共用規則修正
    save_raw = bool(getattr(ctx, "save_raw_input_when_flatten", False))
    if not save_raw:
        ctx.subtable_input_col = None
        return

    in_col = getattr(ctx, "input_col", None)
    pk_col = getattr(ctx, "primary_key", None)

    if not in_col or not str(in_col).strip():
        tlog_warn("⚠️ save_raw_input_when_flatten=True，但未提供 input_col，略過原始輸入欄位。")
        ctx.save_raw_input_when_flatten = False
        ctx.subtable_input_col = None
        return

    if pk_col == in_col:
        # PK 自身就是原始輸入，不再重複存於子表
        ctx.save_raw_input_when_flatten = False
        ctx.subtable_input_col = None
        try:
            tlog("ℹ️ 子表主鍵與輸入欄相同；已自動關閉 raw input 複寫（PK 即為原始輸入）。")
        except Exception:
            pass
    else:
        ctx.subtable_input_col = in_col


# ---------------------------
# 4) Schema（Excel/CSV 分支，但同一函式）
# ---------------------------
def ensure_schemas_tabular(ctx, input_path: str, output_path: str, fmt: str) -> None:
    """
    - 若 output 不存在：從 input 複製到 output，並加上主鍵欄、output_col、update_time（必要時）
    - 若 output 存在：視為續跑；若必要欄位被刪除，溫和補回（不中斷）
    - Excel：使用 write_dataframe_sheet 只覆蓋主表工作表，保留其他工作表
    - CSV：單檔覆蓋
    """
    output_exists = os.path.isfile(output_path)
    path = output_path if output_exists else input_path
    df = read_dataframe(path)

    changed = False

    # 主鍵欄位
    pk_name = getattr(ctx, "primary_key", None) or "row_id"
    ctx.primary_key = pk_name
    if pk_name == "row_id":
        if "row_id" not in df.columns:
            df = df.reset_index(drop=True)
            df["row_id"] = range(len(df))
            changed = True
    else:
        if pk_name not in df.columns:
            try:
                src_df = read_dataframe(input_path)
                if pk_name in src_df.columns:
                    df[pk_name] = src_df[pk_name].reset_index(drop=True)
                    changed = True
                else:
                    tlog_warn(f"⚠️ 找不到主鍵欄位 {pk_name}，改用 row_id。")
                    ctx.primary_key = "row_id"
                    if "row_id" not in df.columns:
                        df = df.reset_index(drop=True)
                        df["row_id"] = range(len(df))
                        changed = True
            except Exception as ex:
                tlog_warn(f"⚠️ 回補主鍵欄位失敗：{ex}，改用 row_id。")
                ctx.primary_key = "row_id"
                if "row_id" not in df.columns:
                    df = df.reset_index(drop=True)
                    df["row_id"] = range(len(df))
                    changed = True

    # 輸出欄位（盡量 string/object）
    out_col = ctx.output_col
    if out_col not in df.columns:
        try:
            df[out_col] = pd.Series([pd.NA] * len(df), dtype="string")
        except Exception:
            df[out_col] = df[out_col].astype("object")
        changed = True
    else:
        if str(df[out_col].dtype) not in ("string", "object"):
            try:
                df[out_col] = df[out_col].astype("string")
            except Exception:
                df[out_col] = df[out_col].astype("object")
            changed = True

    # update_time
    if getattr(ctx, "record_update_time", False):
        if "update_time" not in df.columns:
            if fmt == "excel":
                df["update_time"] = pd.NaT
            else:
                df["update_time"] = ""
            changed = True
        if fmt == "excel":
            # 真 datetime，避免 Excel 單引號
            try:
                df["update_time"] = pd.to_datetime(df["update_time"], errors="coerce")
            except Exception:
                pass

    # Excel 子表命名/設定（僅 Excel）
    if fmt == "excel" and getattr(ctx, "flatten_json_output", False):
        ensure_excel_subtable_config(ctx, output_path)

    # 主表工作表名（Excel）
    if fmt == "excel":
        main_sheet = getattr(ctx, "main_sheet_name", None) or "LLM_result"
        setattr(ctx, "main_sheet_name", main_sheet)

    # ---- 寫回 ----
    if not output_exists:
        backup_table_file(input_path)
        if fmt == "excel":
            write_dataframe_sheet(df, output_path, sheet_name=ctx.main_sheet_name, index=False)
        else:
            write_dataframe(df, output_path, index=False)
    else:
        if changed:
            if fmt == "excel":
                write_dataframe_sheet(df, output_path, sheet_name=ctx.main_sheet_name, index=False)
            else:
                write_dataframe(df, output_path, index=False)


# ---------------------------
# 5) 是否重設輸出欄位（Excel/CSV 共用）
# ---------------------------
def maybe_reset_output_tabular(ctx, input_path: str, output_path: str, fmt: str, args) -> None:
    reset_output       = getattr(ctx, "reset_output", None)
    reset_confirm_code = getattr(ctx, "reset_confirm_code", None)

    if reset_output is None and not args.config:
        r = OptionSelector(
            options={"no": "否（僅處理尚未有結果）", "yes": "是（清空重跑）"},
            question=f"⚠️ 要重設 {ctx.output_col} 欄位嗎？",
            default="no"
        ).proc()
        reset_output = (r == "yes")
    elif reset_output is None:
        reset_output = False

    if not reset_output:
        return

    # 驗證碼
    if reset_confirm_code is None:
        import random
        code = str(random.randint(10000, 99999))
        print(f"🔐 請輸入驗證碼以繼續：{code}")
        user_input = input("請輸入驗證碼：").strip()
        if user_input != code:
            print("❌ 驗證碼錯誤，取消重設。")
            return

    # 重設
    if fmt == "excel":
        # 僅重設主表工作表
        try:
            xls = pd.ExcelFile(output_path)
            sheet_name = getattr(ctx, "main_sheet_name", None) or "LLM_result"
            if sheet_name not in xls.sheet_names:
                # 找不到就退而讀預設
                df = read_dataframe(output_path)
            else:
                df = xls.parse(sheet_name)
        except Exception:
            df = read_dataframe(output_path)

        if ctx.output_col in df.columns:
            df[ctx.output_col] = ""
        if getattr(ctx, "record_update_time", False) and "update_time" in df.columns:
            df["update_time"] = pd.NaT
            try:
                df["update_time"] = pd.to_datetime(df["update_time"], errors="coerce")
            except Exception:
                pass

        backup_table_file(output_path)
        write_dataframe_sheet(df, output_path, sheet_name=getattr(ctx, "main_sheet_name", "LLM_result"), index=False)
    else:
        df = read_dataframe(output_path if os.path.isfile(output_path) else input_path)
        if ctx.output_col in df.columns:
            df[ctx.output_col] = ""
        if getattr(ctx, "record_update_time", False) and "update_time" in df.columns:
            df["update_time"] = ""
        backup_table_file(output_path if os.path.isfile(output_path) else input_path)
        write_dataframe(df, output_path, index=False)


# ---------------------------
# 6) 建立 pending iterator（Excel/CSV 共用）
# ---------------------------
def build_pending_iter_tabular(ctx, input_path: str, output_path: str, fmt: str) -> Iterable:
    """
    從 output（若無則 input）讀表，回傳所有『尚未有結果』的列：
        yield (pk, text)
    - pk 來自 ctx.primary_key 指定的欄位（若不存在則建立 row_id）
    - 正確處理 NaN / None / 空白 / "nan"/"null"/"none"
    - 有重複主鍵時「只派一次 LLM」，由 Sink 負責扇出回寫所有同鍵列
    - 初跑時把補齊後 schema 落到 output（Excel 用 sheet-safe；CSV 直接覆蓋）
    """
    output_exists = os.path.isfile(output_path)
    path = output_path if output_exists else input_path
    df = read_dataframe(path).reset_index(drop=True)

    # 主鍵欄位
    pk_col = getattr(ctx, "primary_key", None) or "row_id"
    if pk_col not in df.columns:
        df["row_id"] = range(len(df))
        ctx.primary_key = "row_id"
        pk_col = "row_id"

    # 必要欄位
    out_col = ctx.output_col
    in_col  = ctx.input_col
    if out_col not in df.columns:
        df[out_col] = ""
    if getattr(ctx, "record_update_time", False) and "update_time" not in df.columns:
        if fmt == "excel":
            df["update_time"] = pd.NaT
            try:
                df["update_time"] = pd.to_datetime(df["update_time"], errors="coerce")
            except Exception:
                pass
        else:
            df["update_time"] = ""

    # 初跑：把 schema 落到 output（保留 Excel 其他 sheet）
    if path != output_path:
        if fmt == "excel":
            main_sheet = getattr(ctx, "main_sheet_name", None) or "LLM_result"
            write_dataframe_sheet(df, output_path, sheet_name=main_sheet, index=False)
        else:
            write_dataframe(df, output_path, index=False)

    # 產生器（重複主鍵只派一次）
    seen = set()
    def _gen():
        for _, row in df.iterrows():
            pk = row.get(pk_col, None)
            if _is_empty(pk):
                continue
            if pk in seen:
                continue
            outv = row.get(out_col, None)
            if not _is_empty(outv):
                continue
            text = row.get(in_col, None)
            if _is_empty(text):
                continue
            seen.add(pk)
            yield (pk, str(text))
    return _gen()
