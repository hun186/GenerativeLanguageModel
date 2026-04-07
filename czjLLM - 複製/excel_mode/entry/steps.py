# excel_mode/entry/steps.py
import os
from typing import Tuple, List, Iterable

from utils.selector import OptionSelector
from utils.utilities_path import OSWALK, smart_detect_path, MKDIR
from utilities.excel_utils import read_dataframe, write_dataframe, backup_table_file
from cli_tools.cli_utils import print_cli_usage_hint  # 若要在這層顯示提示可用
from excel_mode.schema.subtable_ops import ensure_excel_subtable_config
from job_manager.console_ui import tlog_warn
#from sql_mode.schema.common_flatten_policy import ensure_common_flatten_policy
from utilities.excel_utils import write_dataframe_sheet

import pandas as pd
import math


# ---------------------------
# 1) 選檔 + 輸出路徑
# ---------------------------
def resolve_file(ctx, get_param, args) -> Tuple[str, str]:
    """
    回傳 (input_path, output_path)
    """
    input_excel_file = get_param("input_excel_file")

    if not input_excel_file:
        # 從 llm_source_dir 掃描 Excel/CSV
        excel_dir = os.path.join(ctx.llm_source_dir)
        MKDIR(excel_dir)
        excel_files = [
            f for f in OSWALK(excel_dir)
            if (f.endswith(".xlsx") or f.endswith(".csv")) and "_backup_excel" not in f
        ]
        if not excel_files:
            raise FileNotFoundError(f"找不到 Excel/CSV 於：{excel_dir}")

        # 顯示選單（僅檔名），選完對應到完整路徑
        options = {os.path.basename(f): f for f in excel_files}
        chosen = OptionSelector(options=options, question="📄 請選擇欲處理的 Excel/CSV：").proc()
        input_excel_file = options[chosen]

    input_path = smart_detect_path(ctx.PGMSubDir, input_excel_file)
    if not input_path:
        raise FileNotFoundError("❌ 找不到指定的 Excel/CSV 檔案")

    output_excel_file = get_param("output_excel_file")
    if not output_excel_file:
        base, ext = os.path.splitext(input_path)
        output_excel_file = base + "_with_result" + ext

    output_path = smart_detect_path(ctx.PGMSubDir, output_excel_file) or output_excel_file
    # 確保輸出資料夾存在
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    return input_path, output_path


# ---------------------------
# 2) 挑欄位（input/output） + 是否記錄時間
# ---------------------------
def choose_columns(ctx, input_path: str, get_param, args) -> List[str]:
    """
    回傳來源欄位清單（供後續 reference）
    會寫入：ctx.input_col, ctx.output_col, ctx.record_update_time
    """
    # 如果已有結果檔，優先看結果檔（便於續跑）
    df_src = read_dataframe(input_path, nrows=2)
    columns = list(df_src.columns)

    ctx.input_col = get_param("input_col")
    if not ctx.input_col or ctx.input_col not in columns:
        ctx.input_col = OptionSelector(
            options={c: "" for c in columns},
            question="🔍 請選擇要處理的輸入欄位："
        ).proc()

    # 主鍵欄位（支援使用者自選，或特殊值 row_id）
    pk_hint = (get_param("primary_key") or "").strip()
    if pk_hint and pk_hint in columns:
        ctx.primary_key = pk_hint
    else:
        # 讓使用者從 [所有欄位 + "row_id"] 選
        candidates = {c:"" for c in columns}
        candidates["row_id"] = "使用列序作為主鍵"
        ctx.primary_key = OptionSelector(candidates, "🔑 請選擇 Excel 主鍵欄位（或選 row_id）：", default="row_id").proc()

        
    ctx.output_col = get_param("output_col")
    if not ctx.output_col:
        default_out = f"{ctx.input_col}_result"
        ctx.output_col = input(f"💾 請輸入輸出欄位（預設 {default_out}）：").strip() or default_out

    ctx.record_update_time = get_param("record_update_time")
    if ctx.record_update_time is None:
        ctx.record_update_time = (input("⏱️ 每筆更新要寫入 update_time？(Y/n)：").strip().lower() != "n")

    return columns


# ---------------------------
# 3) 展平選項（直接複用 SQL 版的 configure）
# ---------------------------
# 若你不想重複碼，可以直接 import SQL 那個：
from sql_mode.entry.steps import configure_flatten_options  # noqa: F401


# ---------------------------
# 4) 確保主檔欄位（output/update_time）
# ---------------------------
def ensure_schemas(ctx, input_path: str, output_path: str) -> None:
    """
    - 若 output 不存在：從 input 複製到 output，並加上主鍵欄、output_col、update_time（必要時）
    - 若 output 存在：視為續跑；若必要欄位被刪除，溫和補回（不中斷）
    - 若啟用展平：先設定好 Excel 子表（sheet 名稱、預設 pk、是否保留原始輸入）
    """
    # 子表設定（需要 ctx.primary_key / ctx.subtable_name）
    if getattr(ctx, "flatten_json_output", False):
        ensure_excel_subtable_config(ctx, output_path)

    output_exists = os.path.isfile(output_path)
    # 續跑用 output，初跑用 input
    path = output_path if output_exists else input_path
    df = read_dataframe(path)

    changed = False

    # ---- 主鍵欄位 ----
    # 若使用者選 "row_id" 當主鍵，就在檔案內建立固定序號欄位
    pk_name = getattr(ctx, "primary_key", None) or "row_id"
    ctx.primary_key = pk_name

    if pk_name == "row_id":
        if "row_id" not in df.columns:
            df["row_id"] = range(len(df))
            changed = True
    else:
        # 使用者指定的主鍵欄位必須存在於 output；若不在，嘗試從 input 補回（按列序對齊）
        if pk_name not in df.columns:
            try:
                src_df = read_dataframe(input_path)
                if pk_name in src_df.columns:
                    # 依列序補回（reset_index 保持對齊）
                    df[pk_name] = src_df[pk_name].reset_index(drop=True)
                    changed = True
                else:
                    tlog_warn(f"⚠️ 找不到主鍵欄位 {pk_name}，改用 row_id。")
                    ctx.primary_key = "row_id"
                    if "row_id" not in df.columns:
                        df["row_id"] = range(len(df))
                        changed = True
            except Exception as ex:
                tlog_warn(f"⚠️ 回補主鍵欄位失敗：{ex}，改用 row_id。")
                ctx.primary_key = "row_id"
                if "row_id" not in df.columns:
                    df["row_id"] = range(len(df))
                    changed = True

    # ---- 輸出欄位（文字型）----
    out_col = ctx.output_col
    if out_col not in df.columns:
        # 盡量用 string dtype，失敗就用 object
        try:
            df[out_col] = pd.Series([pd.NA] * len(df), dtype="string")
        except Exception:
            df[out_col] = df[out_col].astype("object")
        changed = True
    else:
        # 若不是文字欄，轉為 string/object，避免未來 pandas 警告
        if str(df[out_col].dtype) not in ("string", "object"):
            try:
                df[out_col] = df[out_col].astype("string")
            except Exception:
                df[out_col] = df[out_col].astype("object")
            changed = True

    # ---- update_time（真 datetime）----
    if getattr(ctx, "record_update_time", False):
        if "update_time" not in df.columns:
            df["update_time"] = pd.NaT
            changed = True
        # 轉為 datetime64[ns]，避免 Excel 看到字串而加前導單引號
        try:
            df["update_time"] = pd.to_datetime(df["update_time"], errors="coerce")
        except Exception:
            # 不致命，忽略
            pass
    '''
    # ---- 寫回 ----
    if not output_exists:
        # 初跑：先備份 input，再寫出 output
        backup_table_file(input_path)
        write_dataframe(df, output_path, index=False)
    else:
        # 續跑：只在補欄位時寫回
        if changed:
            write_dataframe(df, output_path, index=False)
    '''
    # 建議統一主表工作表名
    main_sheet = getattr(ctx, "main_sheet_name", None) or "LLM_result"
    setattr(ctx, "main_sheet_name", main_sheet)
    
    # ---- 寫回 ----
    if not output_exists:
        # 初跑：先備份 input，再只寫入主表工作表；其他既有工作表會被保留（若本來就有檔案）
        backup_table_file(input_path)
        write_dataframe_sheet(df, output_path, sheet_name=main_sheet, index=False)
    else:
        # 續跑：只在補欄位時才覆蓋主表工作表，其它 sheet 完整保留
        if changed:
            write_dataframe_sheet(df, output_path, sheet_name=main_sheet, index=False)


# ---------------------------
# 5) 是否重設輸出欄位（Excel版）
# ---------------------------
def _reset_excel_output_with_backup(ctx, output_path: str) -> None:
    """
    將 output_col 清空；若存在 update_time 一併清空；並備份 output 檔。
    """
    if not os.path.isfile(output_path):
        return
    backup_table_file(output_path)
    df = read_dataframe(output_path)
    if ctx.output_col in df.columns:
        df[ctx.output_col] = ""
    if ctx.record_update_time and "update_time" in df.columns:
        df["update_time"] = ""
    write_dataframe(df, output_path, index=False)

def maybe_reset_output_col(ctx, input_path: str, output_path: str, args) -> None:
    reset_output       = getattr(ctx, "reset_output", None)
    reset_confirm_code = getattr(ctx, "reset_confirm_code", None)

    # 互動模式才詢問，帶 config 時就保持預設 False
    if reset_output is None:
        if not args.config:
            r = OptionSelector(
                options={"no": "否（僅處理尚未有結果）", "yes": "是（清空重跑）"},
                question=f"⚠️ 要重設 {ctx.output_col} 欄位嗎？",
                default="no"
            ).proc()
            reset_output = (r == "yes")
        else:
            reset_output = False

    if reset_output:
        user_input = reset_confirm_code
        if user_input is None:
            import random
            code = str(random.randint(10000, 99999))
            print(f"🔐 請輸入驗證碼以繼續：{code}")
            user_input = input("請輸入驗證碼：").strip()
            if user_input != code:
                print("❌ 驗證碼錯誤，取消重設。")
                return
        _reset_excel_output_with_backup(ctx, output_path)


# ---------------------------
# 6) 建立 pending iterator（產生要處理的列）
# ---------------------------
def build_pending_iter(ctx, input_path: str, output_path: str) -> Iterable:
    """
    從 output（若無則 input）讀表，回傳所有『尚未有結果』的列：
        yield (pk, text)
    - pk 來自 ctx.primary_key 指定的欄位（若不存在則建立 row_id）
    - 正確處理 NaN / None / 空白 / "nan"/"null"/"none" 等
    - 會在 output 尚未建立時，先把補齊後的 schema 落到 output，方便續跑
    """
    # 1) 以 output 為準（續跑），沒有就用 input
    path = output_path if os.path.isfile(output_path) else input_path
    df = read_dataframe(path)

    # 2) 主鍵欄位就緒（找不到就建立 row_id）
    pk_col = getattr(ctx, "primary_key", None) or "row_id"
    if pk_col not in df.columns:
        # 依列序建立 row_id
        df = df.reset_index(drop=True)
        df["row_id"] = range(len(df))
        ctx.primary_key = "row_id"
        pk_col = "row_id"

    # 3) 確保必要欄位存在
    out_col = ctx.output_col
    in_col  = ctx.input_col
    if out_col not in df.columns:
        # 盡量用 string dtype 以避免未來 pandas 警告
        try:
            df[out_col] = pd.Series([pd.NA] * len(df), dtype="string")
        except Exception:
            df[out_col] = ""
    if getattr(ctx, "record_update_time", False) and "update_time" not in df.columns:
        df["update_time"] = pd.NaT  # 真 datetime 用 NaT 初始化

    # 4) 若此輪是從 input 開始，先把 schema 落到 output 以利續跑
    if path != output_path:
        write_dataframe(df, output_path, index=False)

    # 5) 正規化空值判斷
    def _is_empty(v) -> bool:
        if v is None: return True
        if isinstance(v, float) and math.isnan(v): return True
        if isinstance(v, str):
            s = v.strip().lower()
            return s in {"", "nan", "none", "null"}
        return False

    # 6) 產生器：只取『尚未有結果』且輸入欄位不為空的列
    seen = set()  # 避免重複主鍵（若有）
    def _gen():
        for _, row in df.iterrows():
            pk = row.get(pk_col, None)
            if _is_empty(pk):
                # 主鍵缺失就跳過（避免後續無法定位）
                continue
            if pk in seen:
                # 主鍵重複：僅處理第一個，其他跳過（也可改成 tlog_warn 提醒）
                continue
            outv = row.get(out_col, None)
            if not _is_empty(outv):
                # 已有結果 → 跳過
                continue
            text = row.get(in_col, None)
            if _is_empty(text):
                continue
            seen.add(pk)
            yield (pk, str(text))
    return _gen()
