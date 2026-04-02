# csv_mode/entry/steps.py
import os, random
import pandas as pd
from typing import Iterable, List, Tuple
from colorama import Fore, Style
from utils.selector import OptionSelector
from czjLLM.job_manager.console_ui import tlog_warn
from czjLLM.utilities.excel_utils import backup_table_file  # 直接沿用你的備份工具

# ---------- 1) 路徑 ----------
def resolve_file(ctx, get_param, args):
    in_path  = get_param("input_csv_file")
    out_path = get_param("output_csv_file")
    if not in_path:
        in_path = input("📄 請輸入來源 CSV 檔路徑：").strip()
    if not out_path:
        default_out = os.path.splitext(in_path)[0] + "_with_result.csv"
        out_path = input(f"💾 請輸入輸出 CSV 檔（預設 {default_out}）：").strip() or default_out
    print(f"📄 正在讀取檔案：{in_path}")
    df = pd.read_csv(in_path, nrows=2)
    print(f"✅ 成功讀取 {len(df)} 筆（示意），欄位數：{len(df.columns)}")
    return in_path, out_path

# ---------- 2) 選欄 ----------
def choose_columns(ctx, input_path, get_param, args) -> List[str]:
    df = pd.read_csv(input_path, nrows=2)
    cols = list(df.columns)

    ctx.input_col = get_param("input_col")
    if not ctx.input_col or ctx.input_col not in cols:
        ctx.input_col = OptionSelector({c:"" for c in cols}, "🔍 請選擇輸入欄位：").proc()

    # 主鍵（可選 row_id）
    ctx.primary_key = get_param("primary_key")
    if not ctx.primary_key or ctx.primary_key not in cols:
        ctx.primary_key = OptionSelector(
            {**{c:"" for c in cols}, "row_id":"(使用列序作為主鍵)"},
            "🔑 請選擇 CSV 主鍵欄位（或選 row_id）：", default="row_id"
        ).proc()

    ctx.output_col = get_param("output_col")
    if not ctx.output_col:
        default_out = f"{ctx.input_col}_result"
        ctx.output_col = input(f"💾 請輸入輸出欄位（預設 {default_out}）：").strip() or default_out

    ctx.record_update_time = get_param("record_update_time")
    if ctx.record_update_time is None:
        ctx.record_update_time = (input("⏱️ 要不要寫 update_time？(Y/n)：").strip().lower() != "n")

    return cols

# ---------- 3) 展平設定（直接沿用 SQL/Excel 的 configure_flatten_options） ----------

# ---------- 4) Schema ----------
def ensure_schemas(ctx, input_path: str, output_path: str):
    """
    - 若 output 不存在：從 input 複製到 output，補上主鍵/輸出/時間欄位
    - 若 output 存在：若欄位被刪掉，溫和補回
    """
    output_exists = os.path.isfile(output_path)
    path = output_path if output_exists else input_path
    df = pd.read_csv(path)

    changed = False
    pk = ctx.primary_key or "row_id"
    ctx.primary_key = pk
    if pk == "row_id":
        if "row_id" not in df.columns:
            df["row_id"] = range(len(df)); changed = True
    else:
        if pk not in df.columns:
            try:
                src = pd.read_csv(input_path)
                if pk in src.columns:
                    df[pk] = src[pk].reset_index(drop=True); changed = True
                else:
                    tlog_warn(f"⚠️ 找不到主鍵 {pk}，改用 row_id")
                    ctx.primary_key = "row_id"
                    if "row_id" not in df.columns:
                        df["row_id"] = range(len(df)); changed = True
            except Exception as ex:
                tlog_warn(f"⚠️ 回補主鍵失敗：{ex}，改用 row_id")
                ctx.primary_key = "row_id"
                if "row_id" not in df.columns:
                    df["row_id"] = range(len(df)); changed = True

    if ctx.output_col not in df.columns:
        df[ctx.output_col] = ""; changed = True
    if getattr(ctx, "record_update_time", False) and "update_time" not in df.columns:
        df["update_time"] = ""; changed = True

    if not output_exists:
        backup_table_file(input_path)
        df.to_csv(output_path, index=False)
    else:
        if changed:
            df.to_csv(output_path, index=False)

# ---------- 5) reset output（與 SQL/Excel 同語意） ----------
def maybe_reset_output_col(ctx, input_path, output_path, args):
    reset = getattr(ctx, "reset_output", None)
    if reset is None:
        if not args.config:
            from utils.selector import OptionSelector
            r = OptionSelector({"no":"否","yes":"是（清空重跑）"},
                               f"⚠️ 要重設 {ctx.output_col} 欄位嗎？", default="no").proc()
            reset = (r == "yes")
        else:
            reset = False
    if reset:
        code = str(random.randint(10000, 99999))
        print(f"🔐 請輸入驗證碼以繼續：{Fore.YELLOW}{code}{Style.RESET_ALL}")
        user_input = input("請輸入驗證碼：").strip()
        if user_input != code:
            print("❌ 驗證碼錯誤，取消重設。"); return
        df = pd.read_csv(output_path if os.path.isfile(output_path) else input_path)
        if ctx.output_col in df.columns:
            df[ctx.output_col] = ""
        if getattr(ctx, "record_update_time", False) and "update_time" in df.columns:
            df["update_time"] = ""
        df.to_csv(output_path, index=False)

# ---------- 6) pending ----------
def build_pending_iter(ctx, input_path: str, output_path: str) -> Iterable:
    path = output_path if os.path.isfile(output_path) else input_path
    df = pd.read_csv(path).reset_index(drop=True)

    out_col = ctx.output_col
    in_col  = ctx.input_col
    if out_col not in df.columns: df[out_col] = ""

    def _empty(v):
        if v is None: return True
        if isinstance(v, float) and pd.isna(v): return True
        if isinstance(v, str) and v.strip().lower() in {"", "nan", "none", "null"}: return True
        return False

    # 若初跑，先把 schema 落到 output，方便續跑
    if path != output_path:
        df.to_csv(output_path, index=False)

    def _gen():
        for _, row in df.iterrows():
            if not _empty(row.get(out_col, None)):  # 已有結果 → 跳過
                continue
            txt = row.get(in_col, None)
            if _empty(txt):
                continue
            # pk 值：直接用主鍵欄位的值（支援重複鍵→Sink 會扇出寫回）
            pk_val = row.get(ctx.primary_key, None) if ctx.primary_key in row else None
            yield (pk_val, str(txt))

    return _gen()
