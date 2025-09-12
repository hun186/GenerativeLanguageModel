import random
from colorama import Fore, Style
import threading

from utils.selector import OptionSelector
from cli_tools.cli_utils import print_cli_usage_hint

from job_manager.console_ui import tlog_warn

from row_processors.flatten_utils import auto_setup_subtable_if_needed
from sql_utils.column_utils import reset_output_col_with_backup
from sql_utils.common import build_sql_connection_string
from utils.utilities_path import is_sqlite_path

from sql_mode.config.config_loader import load_sql_cfg, InteractivePolicy, NonInteractivePolicy
from sql_mode.adapters.sqlite_adapter import SQLiteAdapter
from sql_mode.adapters.mssql_adapter import MSSQLAdapter
from sql_mode.schema.schema_ops import ensure_main_schema
from sql_mode.runtime.orchestrator import run_pipeline

#_signal_drain_stop = threading.Event()

def handle_sql_mode(ctx, get_param, args):
    ctx.save_raw_input_when_flatten = get_param("save_raw_input_when_flatten", ctx.save_raw_input_when_flatten)
    ctx.save_raw_output_when_flatten = get_param("save_raw_output_when_flatten", ctx.save_raw_output_when_flatten)
    print("🔗 SQL 模式啟動：將逐筆處理資料庫")
    # === 新管線：可用環境變數 NEW_SQL_PIPELINE=1 啟用 ===


    #要不要用互動方式選sql設定檔，policy作法尚未實作
    policy = NonInteractivePolicy(args) if args.config else InteractivePolicy()
    sql_cfg = load_sql_cfg(ctx, get_param, args, policy)

    # 設定基本欄位（沿用舊行為）
    server = sql_cfg.get("server", "").strip()
    if not server:
        server = input("🔹 請輸入 server（可為 IP 或 SQLite 檔案路徑），注意如果是SQLite檔案相對路徑，目前目錄為TopicClassification：").strip()
    
    ctx.sql_table = sql_cfg.get("table_name") or input("📋 請輸入來源的資料表名稱：").strip()
    #ctx.target_table = sql_cfg.get("target_table") or ctx.sql_table
    ctx.primary_key = sql_cfg.get("primary_key", "")

    # 決定 adapter 與連線字串（同時把必要資訊寫回 ctx，供 consumer/watchdog 使用）
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

    ctx.target_table = sql_cfg.get("target_table")
    
    if not ctx.target_table:
        ctx.target_table = input(f"💾 請輸入目標資料表名稱（預設為 {ctx.sql_table}）：").strip()
        if not ctx.target_table:
            ctx.target_table = ctx.sql_table
    # 互動指定 input/output 欄位（維持舊行為）
    with adapter.connect():
        columns = adapter.list_columns(ctx.sql_table)
        if ctx.primary_key not in columns:
            ctx.primary_key = OptionSelector(
                options={col: "" for col in columns},
                question="🔑 請選擇主鍵欄位："
            ).proc()

        ctx.input_col = get_param("input_col", sql_cfg.get("input_col", ""))
        if ctx.input_col not in columns:
            ctx.input_col = OptionSelector(
                options={col: "" for col in columns},
                question="📝 請選擇輸入欄位："
            ).proc()

        ctx.output_col = get_param("output_col", sql_cfg.get("output_col", ""))
        if not ctx.output_col:
            DEFAULT_OUTPUT_COL = f"{ctx.input_col}_result"
            ctx.output_col = input(f"💾 請輸入輸出欄位名稱（預設為 {DEFAULT_OUTPUT_COL}）：").strip() or DEFAULT_OUTPUT_COL

        # 避免輸入欄位與輸出欄位相同
        if ctx.sql_table.strip().lower() == ctx.target_table.strip().lower():
            if ctx.input_col == ctx.output_col:
                print(f"⚠️ 輸入欄位（{ctx.input_col}）與輸出欄位相同，這可能會導致原始資料被覆蓋。")
                confirm_same_col = OptionSelector(
                    options={"no": "否，讓我重新選擇輸出欄位", "yes": "是，我確定要覆蓋原欄位"},
                    question="❗您是否確定要使用相同欄位作為輸出？",
                    default="no"
                ).proc()
                if confirm_same_col != "yes":
                    # 重新選擇輸出欄位
                    default_output_col = ctx.input_col + "_result"
                    ctx.output_col = OptionSelector(
                        options={col: "" for col in columns + [default_output_col]},
                        question="🔁 請重新選擇輸出欄位（建議使用不同名稱）："
                    ).proc()
                    
        # 是否記錄 update_time（保留舊互動）
        ctx.record_update_time = get_param("record_update_time")
        if ctx.record_update_time is None:
            record_update_time = input("⏱️ 是否在每筆更新時記錄 update_time？(Y/n)：").strip().lower()
            ctx.record_update_time = (record_update_time != "n")

        ctx.flatten_json_output = get_param("flatten_json_output")
        ctx.allowed_output_fields = get_param("allowed_output_fields")
        # 只有在 CLI 模式下才詢問JSON展平
        if not args.config:
            if not ctx.flatten_json_output:
                flatten = input("🔧 是否將 JSON 結果展平成多個欄位？(y/N)：").strip().lower()
                ctx.flatten_json_output = flatten == "y"
    
            if ctx.flatten_json_output:
                if not ctx.allowed_output_fields:
                    raw_fields = input("📝 請輸入要寫入的 JSON 欄位名稱（以逗號分隔，例如 summary,score）：").strip()
                    ctx.allowed_output_fields = [f.strip() for f in raw_fields.split(",") if f.strip()]
                # 詢問是否也保留原始結果
                save_raw_output = input("📦 是否同時將原始 JSON 結果寫入主欄位（作為備查）？(y/N)：").strip().lower()
                ctx.save_raw_output_when_flatten = save_raw_output == "y"
                # 詢問是否也保留原始輸入
                save_raw_input = input("📦 是否同時將原始輸入寫入子表（作為備查）？(y/N)：").strip().lower()
                ctx.save_raw_input_when_flatten = save_raw_input == "y"    
                
        # 目標表／欄位就緒
        ensure_main_schema(ctx, adapter, columns, sql_cfg)
        # ✅ 若啟用 JSON 展平，先嘗試建立子表（避免 watchdog 取用 subtable_name 炸掉）
        if getattr(ctx, "flatten_json_output", False):
            try:
                auto_setup_subtable_if_needed(ctx, adapter.cur, is_sqlite)
                try:
                    adapter.conn.commit()
                except Exception:
                    pass
            except Exception as ex:
                tlog_warn(f"⚠️ 子表自動建立失敗：{ex}")
                
        # 是否重設輸出欄位（保留舊驗證碼機制）
        ctx.reset_output = sql_cfg.get("reset_output", None)
        ctx.reset_confirm_code = sql_cfg.get("reset_confirm_code", None)
        if ctx.reset_output is None:
            r = OptionSelector(
                options={"no": "否（僅處理尚未有結果的列）", "yes": "是（清空所有資料重新處理）"},
                question=f"⚠️ 是否要重設 {ctx.output_col} 欄位的所有資料？",
                default="no"
            ).proc()
            ctx.reset_output = (r == "yes")
        if ctx.reset_output:
            if ctx.reset_confirm_code is not None:
                user_input = ctx.reset_confirm_code
            else:
                code = str(random.randint(10000, 99999))
                print(f"🔐 為避免誤操作，請輸入以下驗證碼以繼續：{Fore.YELLOW}{code}{Style.RESET_ALL}")
                user_input = input("請輸入驗證碼：").strip()
                if user_input != code:
                    print("❌ 驗證碼錯誤，取消重設。")
                    ctx.reset_output = False
            if ctx.reset_output:
                reset_output_col_with_backup(ctx, is_sqlite)
                
        if not args.config:
            print_cli_usage_hint(ctx)
        
        ctx.error_log_path = f"{ctx.sql_table}_{ctx.output_col}_error_log.txt"
        
        # 以新管線執行：串流抓待處理列
        pending_iter = adapter.select_pending_rows(
            src_table=ctx.sql_table, tgt_table=ctx.target_table,
            pk=ctx.primary_key, input_col=ctx.input_col,
            output_cols=[ctx.output_col],
            record_update_time=ctx.record_update_time,
            fetch_size=500
        )
        run_pipeline(ctx, pending_iter, is_sqlite=is_sqlite)
    return
