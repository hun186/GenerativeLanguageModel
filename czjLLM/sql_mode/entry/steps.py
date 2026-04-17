# sql_mode/entry/steps.py
import random
from colorama import Fore, Style
from utils.selector import OptionSelector
#from cli_tools.cli_utils import print_cli_usage_hint
from utils.utilities_path import is_sqlite_path
from czjLLM.sql_utils.common import build_sql_connection_string
from czjLLM.sql_utils.column_utils import reset_output_col_with_backup
from czjLLM.sql_mode.config.config_loader import load_sql_cfg, InteractivePolicy, NonInteractivePolicy
from czjLLM.sql_mode.adapters.sqlite_adapter import SQLiteAdapter
from czjLLM.sql_mode.adapters.mssql_adapter import MSSQLAdapter
from czjLLM.sql_mode.schema.schema_ops import ensure_main_schema, ensure_flatten_schema
from czjLLM.sql_mode.schema.common_flatten_policy import ensure_common_flatten_policy


def _normalize_writeback_rules(get_param):
    rules = get_param("sql_writeback_rules", None)
    out = []
    if not isinstance(rules, list):
        return out
    for item in rules:
        if not isinstance(item, dict):
            continue
        col = str(item.get("output_col", "")).strip()
        if not col:
            continue
        src = str(item.get("source", "combined") or "combined").strip().lower()
        if src not in {"combined", "stage"}:
            src = "combined"
        out.append({"output_col": col, "source": src, "stage": item.get("stage", None)})
    return out

def _normalize_flatten_writeback_rules(get_param, writeback_rules):
    """
    支援多來源 flatten：
    - 新參數：sql_flatten_writeback_rules: [{writeback_rule, enabled, allowed_output_fields, save_raw_input_when_flatten}, ...]
    - 舊參數：sql_flatten_writeback_rule: <int>
    """
    cfg = get_param("sql_flatten_writeback_rules", None)
    out = []

    if isinstance(cfg, list):
        for item in cfg:
            if not isinstance(item, dict):
                continue
            try:
                idx = int(
                    item.get(
                        "writeback_rule",
                        item.get("rule_idx", item.get("sql_flatten_writeback_rule", 0)),
                    )
                    or 0
                )
            except Exception:
                idx = 0
            if idx < 0:
                idx = 0
            enabled = bool(item.get("enabled", True))
            allowed = item.get("allowed_output_fields", None)
            if isinstance(allowed, (list, tuple)):
                allowed = [str(x).strip() for x in allowed if str(x).strip()]
            else:
                allowed = None
            save_raw = item.get(
                "save_raw_input_when_flatten",
                item.get("flatten_store_input_col", item.get("save_input_col_when_flatten", None)),
            )
            out.append(
                {
                    "writeback_rule": idx,
                    "enabled": enabled,
                    "allowed_output_fields": allowed,
                    "save_raw_input_when_flatten": save_raw,
                }
            )

    if out:
        return out

    # backward-compatible：若未提供新參數，退回舊單一來源設定
    try:
        idx = int(get_param("sql_flatten_writeback_rule", 0) or 0)
    except Exception:
        idx = 0
    if idx < 0:
        idx = 0

    # 若沒有 writeback rules，保留舊行為（以主輸出欄位為來源）
    if not writeback_rules:
        return [{"writeback_rule": 0, "enabled": True}]
    return [{"writeback_rule": idx, "enabled": True}]

def _has_enabled_flatten_writeback_rules(ctx) -> bool:
    rules = getattr(ctx, "sql_flatten_writeback_rules", None)
    if not isinstance(rules, list):
        return False
    for item in rules:
        if not isinstance(item, dict):
            continue
        if bool(item.get("enabled", True)):
            return True
    return False

def resolve_connection(ctx, get_param, args):
    policy = NonInteractivePolicy(args) if args.config else InteractivePolicy()
    sql_cfg = load_sql_cfg(ctx, get_param, args, policy)

    server = (sql_cfg.get("server", "") or
              input("🔹 請輸入 server（IP 或 SQLite 檔案路徑）：").strip())
    ctx.sql_table    = sql_cfg.get("table_name") or input("📋 請輸入來源表名：").strip()
    ctx.primary_key  = sql_cfg.get("primary_key", "")
    ctx.target_table = sql_cfg.get("target_table") or ctx.sql_table

    if is_sqlite_path(server):
        ctx.sqlite_path = server
        adapter = SQLiteAdapter(sql_cfg)
        ctx.sql_connection_string = None
        is_sqlite = True
    else:
        conn_str = build_sql_connection_string(sql_cfg)
        sql_cfg["connection_string"] = conn_str
        adapter = MSSQLAdapter(sql_cfg)
        ctx.sql_connection_string = conn_str
        is_sqlite = False
    return adapter, is_sqlite, sql_cfg

def choose_columns_and_io_cols(ctx, get_param, adapter, sql_cfg, args):
    columns = adapter.list_columns(ctx.sql_table)

    if ctx.primary_key not in columns:
        ctx.primary_key = OptionSelector(
            options={c:"" for c in columns}, question="🔑 請選擇主鍵欄位："
        ).proc()
        
        
    ctx.input_col = get_param("input_col", sql_cfg.get("input_col", ""))
    if ctx.input_col not in columns:
        ctx.input_col = OptionSelector(
            options={col: "" for col in columns},
            question="📝 請選擇輸入欄位："
        ).proc()

    ctx.output_col = get_param("output_col", sql_cfg.get("output_col", ""))  
    if isinstance(ctx.output_col, list):
        ctx.output_cols = [str(c).strip() for c in ctx.output_col if str(c).strip()]
        ctx.output_col = ctx.output_cols[0] if ctx.output_cols else ""
    else:
        ctx.output_cols = [str(ctx.output_col).strip()] if str(ctx.output_col).strip() else []

    ctx.sql_writeback_rules = _normalize_writeback_rules(get_param)
    # 指定「哪一條 writeback rule」作為 flatten / expand JSON 的來源（0-based）
    # 例如 sql_flatten_writeback_rule: 1 代表使用第 2 條規則。
    try:
        ctx.sql_flatten_writeback_rule = int(get_param("sql_flatten_writeback_rule", 0) or 0)
    except Exception:
        ctx.sql_flatten_writeback_rule = 0
    ctx.sql_flatten_writeback_rules = _normalize_flatten_writeback_rules(get_param, ctx.sql_writeback_rules)
    for r in ctx.sql_writeback_rules:
        c = r.get("output_col")
        if c and c not in ctx.output_cols:
            ctx.output_cols.append(c)

    if not ctx.output_col:
        default_out = f"{ctx.input_col}_result"
        ctx.output_col = input(f"💾 請輸入輸出欄位名稱（預設為 {default_out}）：").strip() or default_out


    # 同表時避免覆蓋
    if ctx.sql_table.strip().lower() == ctx.target_table.strip().lower():
        if ctx.input_col == ctx.output_col:
            ok = OptionSelector(
                options={"no":"否，重選", "yes":"是，我確定要覆蓋"},
                question="❗輸入/輸出欄位相同，確定覆蓋？", default="no"
            ).proc()
            if ok != "yes":
                ctx.output_col = OptionSelector(
                    options={c:"" for c in columns+[default_out]},
                    question="🔁 請重新選擇輸出欄位："
                ).proc()

    # 是否記錄 update_time（保留舊互動）
    ctx.record_update_time = get_param("record_update_time")
    if ctx.record_update_time is None:
        record_update_time = input("⏱️ 是否記錄 update_time？(Y/n)：").strip().lower()
        ctx.record_update_time = (record_update_time != "n")

    return columns

def configure_flatten_options(ctx, get_param, args):
    default_save_raw = True if bool(getattr(ctx, "is_sqlite", False)) else False
    ctx.flatten_json_output      = get_param("flatten_json_output", getattr(ctx, "flatten_json_output", None))
    ctx.allowed_output_fields    = get_param("allowed_output_fields", getattr(ctx, "allowed_output_fields", None))
    #ctx.save_raw_output_when_flatten = get_param("save_raw_output_when_flatten", getattr(ctx, "save_raw_output_when_flatten", False))
    ctx.save_raw_input_when_flatten  = get_param(
        "save_raw_input_when_flatten",
        get_param(
            "flatten_store_input_col",
            get_param(
                "save_input_col_when_flatten",
                getattr(ctx, "save_raw_input_when_flatten", default_save_raw),
            ),
        ),
    )
    if not bool(ctx.flatten_json_output) and _has_enabled_flatten_writeback_rules(ctx):
        ctx.flatten_json_output = True
    #print("args.config in configure_flatten_options", args.config)
    #print("ctx",ctx)
    # 只有在 CLI 模式下才詢問JSON展平
    if not args.config:
        if not ctx.flatten_json_output:
            ctx.flatten_json_output = (input("🔧 JSON 結果要展平？(y/N)：").strip().lower() == "y")
        if ctx.flatten_json_output and not ctx.allowed_output_fields:
            raw = input("📝 請輸入要寫入的 JSON 欄位（逗號分隔）：").strip()
            ctx.allowed_output_fields = [s.strip() for s in raw.split(",") if s.strip()]
        if ctx.flatten_json_output:
            #ctx.save_raw_output_when_flatten = (input("📦 子表是否同時保留原始 JSON 輸出？(y/N)：").strip().lower()=="y")
            if bool(getattr(ctx, "is_sqlite", False)):
                user_in = input("📦 子表是否保留原始輸入？(Y/n)：").strip().lower()
                ctx.save_raw_input_when_flatten = (user_in != "n")
            else:
                ctx.save_raw_input_when_flatten = (input("📦 子表是否保留原始輸入？(y/N)：").strip().lower() == "y")

    # 若主鍵就是輸入欄，展平時不再另存 raw input 欄位（PK 就是原始輸入）
    #print("in configure_flatten_options,ctx",ctx)
    '''
    if getattr(ctx, "flatten_json_output", False) and ctx.primary_key == ctx.input_col:
        ctx.save_raw_input_when_flatten = False     # 關閉另存
        ctx.subtable_input_col = None               # 不建立子表的 raw input 欄
        # 可選：告知一次
        try:
            print(f"ℹ️ 主鍵=輸入欄（{ctx.primary_key}），子表直接以主鍵保存原始輸入，不再建立額外欄位。")
        except Exception:
            pass
    '''
    ensure_common_flatten_policy(ctx)
    
def ensure_schemas(ctx, adapter, columns, is_sqlite, sql_cfg):
    # 主表/欄位
    ensure_main_schema(ctx, adapter, columns, sql_cfg)
    # 子表（若啟用展平）
    if getattr(ctx, "flatten_json_output", False):
        # 這裡統一走 schema 層（與前面討論一致）
        ensure_flatten_schema(ctx, adapter.cur, is_sqlite)
        try: adapter.conn.commit()
        except Exception: pass

def maybe_reset_output_col(ctx, is_sqlite, sql_cfg, columns, args):
    ctx.reset_output       = sql_cfg.get("reset_output", None)
    ctx.reset_confirm_code = sql_cfg.get("reset_confirm_code", None)

    if ctx.reset_output is None:
        if not args.config:
            r = OptionSelector(
                options={"no":"否（僅處理尚未有結果）","yes":"是（清空重跑）"},
                question=f"⚠️ 要重設 {ctx.output_col} 欄位嗎？", default="no"
            ).proc()
            ctx.reset_output = (r=="yes")
        else:
            ctx.reset_output = False

    if ctx.reset_output:
        user_input = ctx.reset_confirm_code
        if user_input is None:
            code = str(random.randint(10000, 99999))
            print(f"🔐 請輸入驗證碼繼續：{Fore.YELLOW}{code}{Style.RESET_ALL}")
            user_input = input("請輸入驗證碼：").strip()
            if user_input != code:
                print("❌ 驗證碼錯誤，取消重設。")
                ctx.reset_output = False
        if ctx.reset_output:
            reset_output_col_with_backup(ctx, is_sqlite)

def build_pending_iter(adapter, ctx):
    # 以第一個輸出欄位作為 pending 判斷主欄（其餘欄位可由 sql_writeback_rules 擴充寫入）
    output_cols = getattr(ctx, "output_cols", None) or [ctx.output_col]
    return adapter.select_pending_rows(
        src_table=ctx.sql_table, tgt_table=ctx.target_table,
        pk=ctx.primary_key, input_col=ctx.input_col,
        output_cols=output_cols,
        record_update_time=ctx.record_update_time,
        fetch_size=500
    )
