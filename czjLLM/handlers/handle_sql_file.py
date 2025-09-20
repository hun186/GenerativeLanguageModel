
import os
import pyodbc
import sqlite3
import random
import getpass
from colorama import Fore, Style
from tqdm import tqdm
from datetime import datetime
import json

#from handlers.export_sql_to_excel import export_sql_to_excel
from utils.selector import OptionSelector
from cli_tools.cli_utils import print_cli_usage_hint
from row_processors.row_runner import process_row_and_get_result
from row_processors.flatten_utils import extract_json_list_for_flatten
from row_processors.flatten_utils import auto_setup_subtable_if_needed
from sql_utils.column_utils import reset_output_col_with_backup
from config_ui.interactive_config_loader import load_sql_config_interactively

from sql_utils.common import build_sql_connection_string
from sql_utils.column_utils import ensure_sql_columns_exist
from sql_utils.schema_manager import ensure_subtable_exists
from sql_utils.writer import write_flattened_json_to_sql

from sql_utils.writer import flatten_row_based_json_array_to_subtable
from sql_utils.common import quote_column
from sql_utils.common import safe_sql_value
from sql_utils.row_utils import upsert_single_value
from utilities.logging_utils import log_error
from utils.utilities_path import is_sqlite_path


def handle_sql_mode(ctx, get_param, args):
    ctx.save_raw_output_when_flatten = get_param("save_raw_output_when_flatten", ctx.save_raw_output_when_flatten)
    print("🔗 SQL 模式啟動：將逐筆處理資料庫")
    
    sql_cfg = load_sql_config_interactively(ctx.PGMSubDir, get_param, ctx)
    # === 智慧補齊資訊 ===
    server = sql_cfg.get("server", "").strip()
    if not server:
        server = input("🔹 請輸入 server（可為 IP 或 SQLite 檔案路徑），注意如果是SQLite檔案相對路徑，目前目錄為TopicClassification：").strip()
    
    # 根據 server 判斷使用 SQLite 或 SQL Server
    if is_sqlite_path(server):
        ctx.sqlite_path = server
        ctx.sql_table = sql_cfg.get("table_name") or input("📋 請輸入 SQLite 表格名稱：").strip()
        ctx.primary_key = sql_cfg.get("primary_key", "")
        conn = sqlite3.connect(ctx.sqlite_path)
        cursor = conn.cursor()
        cursor.execute(f"PRAGMA table_info({ctx.sql_table})")
        columns = [row[1] for row in cursor.fetchall()]
        conn.close()
        is_sqlite = True
    else:
    # 遠端 SQL Server 模式
        ctx.sql_connection_string = build_sql_connection_string(sql_cfg)
        conn = pyodbc.connect(ctx.sql_connection_string)
        ctx.sql_table = sql_cfg.get("table_name") or input("📋 請輸入資料表名稱：").strip()        
        ctx.primary_key = sql_cfg.get("primary_key", "")
        cursor = conn.cursor()
        cursor.execute(f"SELECT TOP 1 * FROM {ctx.sql_table}")
        columns = [desc[0] for desc in cursor.description]
        conn.close()
        is_sqlite = False

    ctx.reset_output = sql_cfg.get("reset_output", None)
    ctx.reset_confirm_code = sql_cfg.get("reset_confirm_code",None)

    if ctx.reset_output is None:
        ctx.reset_output = OptionSelector(
            options={"no": "否（僅處理尚未有結果的列）", "yes": "是（清空所有資料重新處理）"},
            question=f"⚠️ 是否要重設 {ctx.output_col} 欄位的所有資料？",
            default="no"
        ).proc()
        ctx.reset_output = True if ctx.reset_output == "yes" else False
    # 若有預先設定驗證碼，則跳過輸入
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
        
    ctx.target_table = sql_cfg.get("target_table")
    #print("ctx",ctx)
    if not ctx.target_table:
        ctx.target_table = input(f"💾 請輸入目標資料表名稱（預設為 {ctx.sql_table}）：").strip()
        if not ctx.target_table:
            ctx.target_table = ctx.sql_table
            
    # === 主鍵 / 輸入 / 輸出欄位確認 ===
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
        ctx.output_col = input(f"💾 請輸入輸出欄位名稱（預設為 {ctx.input_col}_result）：").strip()
        if not ctx.output_col:
            ctx.output_col = ctx.input_col + "_result"
    
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
            save_raw = input("📦 是否同時將原始 JSON 結果寫入主欄位（作為備查）？(y/N)：").strip().lower()
            ctx.save_raw_output_when_flatten = save_raw == "y"
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
        
    if not args.config:
        print_cli_usage_hint(ctx)
    
    if ctx.reset_output:
        reset_output_col_with_backup(ctx, is_sqlite)
    handle_sql_row_by_row(ctx,is_sqlite=is_sqlite)



def handle_sql_row_by_row(ctx,is_sqlite=False):
  
    if is_sqlite:
        conn = sqlite3.connect(ctx.sqlite_path)
    else:
        conn = pyodbc.connect(ctx.sql_connection_string)
    cursor = conn.cursor()

    if ctx.target_table != ctx.sql_table:
        if is_sqlite:
            cursor.execute(f"""
                CREATE TABLE IF NOT EXISTS {quote_column(ctx.target_table)} (
                    {quote_column(ctx.primary_key)} TEXT PRIMARY KEY
                )
            """)
        else:
            cursor.execute(f"""
                IF OBJECT_ID(N'{ctx.target_table}', N'U') IS NULL
                BEGIN
                    CREATE TABLE {quote_column(ctx.target_table)} (
                        {quote_column(ctx.primary_key)} NVARCHAR(255) PRIMARY KEY,
                    )
                END
            """)
        conn.commit()
    #ensure_sql_columns_exist(cursor, ctx.target_table, [ctx.output_col], is_sqlite)

    # 🔍 判斷要根據哪些欄位來判定是否已處理過
    #if ctx.flatten_json_output and not ctx.save_raw_output_when_flatten:
    #    check_cols = ctx.allowed_output_fields
    #else:
    #    check_cols = [ctx.output_col]
    check_cols = [ctx.output_col]
    # 🔍 組合 WHERE 條件：所有欄位為 NULL 或空
    def build_where_clause(cols, prefix=""):
        return " AND ".join(
            f"({prefix}{quote_column(col)} IS NULL OR {prefix}{quote_column(col)} = '')"
            for col in cols
        )
    # 補上必要的欄位（避免 SELECT 判斷欄位不存在）
    extra_cols = check_cols[:]
    if ctx.record_update_time:
        extra_cols.append("update_time")

    ensure_sql_columns_exist(cursor, ctx.target_table, extra_cols, is_sqlite)
    auto_setup_subtable_if_needed(ctx, cursor, is_sqlite)
    # ===== 撈出待處理列 =====
    if ctx.target_table.strip().lower() == ctx.sql_table.strip().lower():
        # 寫回原表
        select_sql = (
            f"SELECT {quote_column(ctx.primary_key)}, {quote_column(ctx.input_col)} "
            f"FROM {quote_column(ctx.sql_table)} "
            f"WHERE {build_where_clause(check_cols)} "
            f"{'LIMIT -1' if is_sqlite else ''}"
        )
    else:
        # 寫入不同表（LEFT JOIN）
        select_sql = (
            f"SELECT src.{quote_column(ctx.primary_key)}, src.{quote_column(ctx.input_col)} "
            f"FROM {quote_column(ctx.sql_table)} AS src "
            f"LEFT JOIN {quote_column(ctx.target_table)} AS tgt "
            f"ON src.{quote_column(ctx.primary_key)} = tgt.{quote_column(ctx.primary_key)} "
            f"WHERE {build_where_clause(check_cols, 'tgt.')}"
        )
    #print("select_sql",select_sql)
    cursor.execute(select_sql)
    rows = cursor.fetchall()
    total = len(rows)
    print(f"🔄 共 {total} 筆待處理資料")
    ctx.error_log_path = f"{ctx.sql_table}_error_log.txt"

    #allowed_fields = set(ctx.allowed_output_keys) if hasattr(ctx, "allowed_output_keys") else {ctx.output_col}
    #ensured = False  # 避免每行都重複確認欄位結構
    
    # ===== 處理每一列並更新資料 =====

    #print("allowed_output_fields",ctx.allowed_output_fields)
    for idx, row in tqdm(enumerate(rows), total=total,
                         desc=Fore.LIGHTYELLOW_EX + "列處理進度" + Style.RESET_ALL, ncols=80):
        pk = row[0]
        text = str(row[1])
        pause = 10 if idx == 0 else 0
        result = process_row_and_get_result(text, idx, ctx, pause_seconds=pause)
        if result is not None:
            try:
                update_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S") if ctx.record_update_time else None
                upsert_single_value(ctx, cursor, pk, result, is_sqlite=is_sqlite, update_time=update_time)
    
    
                if ctx.flatten_json_output:
                    result_list = extract_json_list_for_flatten(result, ctx.allowed_output_fields)
                    if not result_list:
                        print(f"⚠️ 第 {idx+1} 筆展平結果為空，跳過寫入主鍵 {pk}")
                        continue
                    
                    for i, result_dict in enumerate(result_list):
                        result_dict = {k: safe_sql_value(v) for k, v in result_dict.items()}
                    
                        if ctx.save_raw_output_when_flatten and ctx.output_col not in result_dict:
                            result_dict[ctx.output_col] = safe_sql_value(result)
                    
                        if ctx.record_update_time:
                            result_dict["update_time"] = update_time
                    
                        #if not ensured:
                            #ensure_sql_columns_exist(cursor, ctx.target_table, result_dict.keys(), is_sqlite)
                            #ensure_subtable_exists(cursor,ctx.subtable_name,key_col=ctx.primary_key,seq_col="seq",is_sqlite=is_sqlite)
                            #ensured = True
                    
                        #write_flattened_json_to_sql(
                        #    cursor, ctx.target_table, ctx.primary_key, pk,
                        #    result_dict, is_sqlite, is_update_only=(ctx.target_table == ctx.sql_table)
                        #)
                    
                        # 🔄 寫入子表（可根據需要加判斷，只針對特定欄位做）
                        if ctx.subtable_name and ctx.allowed_output_fields:
                            flatten_row_based_json_array_to_subtable(
                                cursor=cursor,
                                sub_table_name=ctx.subtable_name,
                                pk_value=pk,
                                json_array=result_list,
                                key_col=ctx.primary_key,
                                seq_col="seq",
                                is_sqlite=is_sqlite
                            )

    
                conn.commit()
                print(f"✅ 第 {idx+1} 筆已寫入：{pk}")
            except Exception as e:
                log_error(idx, f"更新失敗：{e}", ctx.error_log_path)


    cursor.close()
    conn.close()
    print("🎉 資料處理完成！")