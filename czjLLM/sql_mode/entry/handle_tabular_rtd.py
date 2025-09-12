# sql_mode/entry/handle_tabular.py
import os
from dataclasses import dataclass
from typing import Callable, Dict, Any

from cli_tools.cli_utils import print_cli_usage_hint
from ..runtime.orchestrator import run_pipeline
from ..runtime.sinks.sql_sink import SqlSink
from ..runtime.sinks.excel_sink import ExcelSink
#from .steps import configure_flatten_options
from csv_mode.entry import steps as csv_steps
from ..runtime.sinks.csv_sink import CsvSink

# SQL 版 steps
from .steps import (
    resolve_connection, choose_columns_and_io_cols,
    configure_flatten_options as configure_flatten_sql,
    ensure_schemas as ensure_sql_schemas,
    maybe_reset_output_col as maybe_reset_sql_output,
    build_pending_iter as build_sql_pending_iter,
)

# Excel 版 steps
from excel_mode.entry.steps import (
    resolve_file, choose_columns,
    configure_flatten_options as configure_flatten_excel,
    ensure_schemas as ensure_excel_schemas,
    maybe_reset_output_col as maybe_reset_excel_output,
    build_pending_iter as build_excel_pending_iter,
)


@dataclass(frozen=True)
class Backend:
    # 封裝各步驟；每個 callable 都收 (ctx, env, get_param, args) 或類似語意
    name: str
    resolve: Callable[[Any, Callable, Any], Dict[str, Any]]
    choose_columns: Callable[[Any, Dict[str, Any], Callable, Any], Any]
    configure_flatten: Callable[[Any, Callable, Any], None]
    ensure_schemas: Callable[[Any, Dict[str, Any], Any], None]
    maybe_reset_output: Callable[[Any, Dict[str, Any], Any, Any], None]
    build_pending_iter: Callable[[Any, Dict[str, Any]], Any]
    make_sink: Callable[[Any, Dict[str, Any]], Any]
    error_log_name: Callable[[Any, Dict[str, Any]], str]
    connection_ctx_key: str = "connection_ctx"  # 若需要 with 連線情境（SQL 用）


# ------------ SQL backend 包裝 ------------
def _sql_resolve(ctx, get_param, args):
    adapter, is_sqlite, sql_cfg = resolve_connection(ctx, get_param, args)
    # 交回一個 env dict；把 contextmanager 也放進來，讓外層統一 with
    return {
        "adapter": adapter,
        "is_sqlite": is_sqlite,
        "sql_cfg": sql_cfg,
        "connection_ctx": adapter.connect(),
    }

def _sql_choose(ctx, env, get_param, args):
    return choose_columns_and_io_cols(ctx, get_param, env["adapter"], env["sql_cfg"], args)

def _sql_ensure(ctx, env, columns):
    ensure_sql_schemas(ctx, env["adapter"], columns, env["is_sqlite"], env["sql_cfg"])

def _sql_maybe_reset(ctx, env, columns, args):
    maybe_reset_sql_output(ctx, env["is_sqlite"], env["sql_cfg"], columns, args)

def _sql_build_iter(ctx, env):
    return build_sql_pending_iter(env["adapter"], ctx)

def _sql_sink(ctx, env):
    return SqlSink(ctx, is_sqlite=env["is_sqlite"])

def _sql_error_log(ctx, env):
    tbl = getattr(ctx, "target_table", None) or ctx.sql_table
    return f"{tbl}_{ctx.output_col}_error_log.txt"


SQL_BACKEND = Backend(
    name="sql",
    resolve=_sql_resolve,
    choose_columns=_sql_choose,
    configure_flatten=configure_flatten_sql,
    ensure_schemas=_sql_ensure,
    maybe_reset_output=_sql_maybe_reset,
    build_pending_iter=_sql_build_iter,
    make_sink=_sql_sink,
    error_log_name=_sql_error_log,
)


# ------------ Excel backend 包裝 ------------
def _excel_resolve(ctx, get_param, args):
    input_path, output_path = resolve_file(ctx, get_param, args)
    input_path  = os.path.abspath(input_path)
    output_path = os.path.abspath(output_path)

    # 寫回 ctx，便於其他模組/除錯
    ctx.input_excel_file  = input_path
    ctx.output_excel_file = output_path

    # Excel 模式不要有 DB 連線資訊，避免 consumer 嘗試連 DB
    ctx.sql_connection_string = None
    ctx.sqlite_path = None

    # 設定 Excel flow 的預設主鍵：用 DataFrame 的列索引
    if not getattr(ctx, "primary_key", None):
        ctx.primary_key = "row_id"   # 這只是子表用的欄位名；主表依舊靠 df.index 定位

    return {
        "input_path": input_path,
        "output_path": output_path,
        "is_sqlite": False,     # 跟 run_pipeline 介面保持一致
        "connection_ctx": None, # Excel 不需要 with 連線
    }


def _excel_choose(ctx, env, get_param, args):
    return choose_columns(ctx, env["input_path"], get_param, args)

def _excel_ensure(ctx, env, columns):
    ensure_excel_schemas(ctx, env["input_path"], env["output_path"])

def _excel_maybe_reset(ctx, env, columns, args):
    maybe_reset_excel_output(ctx, env["input_path"], env["output_path"], args)

def _excel_build_iter(ctx, env):
    return build_excel_pending_iter(ctx, env["input_path"], env["output_path"])

def _excel_sink(ctx, env):
    return ExcelSink(
        ctx,
        input_path=env["input_path"],
        output_path=env["output_path"],
        main_sheet = "LLM_result",
        flush_main_every=10,
        flush_sub_every=10,
    )
def _excel_error_log(ctx, env):
    return f"{ctx.task}_{ctx.output_col}_excel_error_log.txt"


EXCEL_BACKEND = Backend(
    name="table",
    resolve=_excel_resolve,
    choose_columns=_excel_choose,
    configure_flatten=configure_flatten_excel,
    ensure_schemas=_excel_ensure,
    maybe_reset_output=_excel_maybe_reset,
    build_pending_iter=_excel_build_iter,
    make_sink=_excel_sink,
    error_log_name=_excel_error_log,
)


# --- CSV backend ---
def _csv_resolve(ctx, get_param, args):
    input_path, output_path = csv_steps.resolve_file(ctx, get_param, args)
    return {"input_path": input_path, "output_path": output_path, "is_sqlite": False, "connection_ctx": None}

def _csv_choose(ctx, env, get_param, args):
    return csv_steps.choose_columns(ctx, env["input_path"], get_param, args)

def _csv_ensure(ctx, env, columns):
    csv_steps.ensure_schemas(ctx, env["input_path"], env["output_path"])

def _csv_maybe_reset(ctx, env, columns, args):
    csv_steps.maybe_reset_output_col(ctx, env["input_path"], env["output_path"], args)

def _csv_build_iter(ctx, env):
    return csv_steps.build_pending_iter(ctx, env["input_path"], env["output_path"])

def _csv_sink(ctx, env):
    return CsvSink(ctx, input_path=env["input_path"], output_path=env["output_path"],
                   flush_main_every=10, flush_sub_every=10)

def _csv_error_log(ctx, env):
    return f"{ctx.task}_{ctx.output_col}_csv_error_log.txt"

CSV_BACKEND = Backend(
    name="csv",
    resolve=_csv_resolve,
    choose_columns=_csv_choose,
    configure_flatten=configure_flatten_excel,   # 同一套問法即可
    ensure_schemas=_csv_ensure,
    maybe_reset_output=_csv_maybe_reset,
    build_pending_iter=_csv_build_iter,
    make_sink=_csv_sink,
    error_log_name=_csv_error_log,
)

# 選 backend：table 模式下依副檔名/設定判斷
def _select_backend(ctx, get_param) -> Backend:
    mode = getattr(ctx, "mode", "").lower()
    if mode != "table":
        return SQL_BACKEND

    # 先看明確設定
    in_csv  = get_param("input_csv_file")
    in_xlsx = get_param("input_excel_file")
    if in_csv:  return CSV_BACKEND
    if in_xlsx: return EXCEL_BACKEND

    # 退而求其次：看使用者輸入的路徑副檔名（若之後 resolve_file 會問，就先預測）
    # 允許兩邊同時沒設，先預設 Excel；使用者若輸入 .csv，resolve 後也不影響
    print("in_csv",in_csv)
    print("in_xlsx",in_csv)
    try:
        p = in_csv or in_xlsx or ""
        #p = in_xlsx or ""
        if str(p).lower().endswith(".csv"):  return CSV_BACKEND
        if str(p).lower().endswith((".xlsx", ".xls")): return EXCEL_BACKEND
    except Exception:
        pass
    return EXCEL_BACKEND


'''
def _select_backend(ctx) -> Backend:
    mode = getattr(ctx, "mode", "").lower()
    return EXCEL_BACKEND if mode == "table" else SQL_BACKEND
'''

def handle_tabular_mode(ctx, get_param, args):
    """
    單一入口：依 ctx.mode 自動走 SQL 或 Excel。
    （SQL/Excel 的差異都封裝在 Backend 物件）
    """
    backend = _select_backend(ctx, get_param)
    print("📄 CSV 模式：逐列處理" if backend.name == "csv"
          else ("📄 Excel 模式：逐列處理" if backend.name == "table"
                else "🔗 SQL 模式啟動：逐筆處理資料庫"))
    print("backend",backend)
    
    # 1) 解析環境（連線、路徑…）
    env = backend.resolve(ctx, get_param, args)

    # 2) 若有 connection context（SQL），在 with 內走完 schema 與選欄位等步驟
    cm = env.get(backend.connection_ctx_key)
    enter_cm = (cm is not None)

    def _run_inside():
        # 2.1 欄位選擇
        columns = backend.choose_columns(ctx, env, get_param, args)
        # 2.2 展平設定
        backend.configure_flatten(ctx, get_param, args)
        
        # 2.3 schema 檢查/建立
        backend.ensure_schemas(ctx, env, columns)
        # 2.4 是否重置輸出
        backend.maybe_reset_output(ctx, env, columns, args)

        # 2.5 CLI 提示與錯誤檔名
        if not args.config:
            print_cli_usage_hint(ctx)
        ctx.error_log_path = backend.error_log_name(ctx, env)

        # 2.6 建 pending 與 sink
        pending_iter = backend.build_pending_iter(ctx, env)
        sink = backend.make_sink(ctx, env)
        #print("sink in _run_inside",sink)
        #print("sink.main_sheet",sink.main_sheet)
        

        # 3) 進入通用管線（通用 watchdog + sink）
        run_pipeline(ctx, pending_iter, is_sqlite=env.get("is_sqlite", False), sink=sink)

    if enter_cm:
        with cm:
            _run_inside()
    else:
        _run_inside()
