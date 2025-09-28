# handlers/handle_data_mode.py
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Any

from ..cli_tools.cli_utils import print_cli_usage_hint
from ..sql_mode.runtime.orchestrator import run_pipeline
from ..sql_mode.runtime.sinks.sql_sink import SqlSink
from ..sql_mode.runtime.sinks.excel_sink import ExcelSink
from ..tabular_mode.runtime.sinks.csv_sink import CSVSink
#from czjLLM.tabular_mode.runtime.sinks.csv_sink import CSVSink  # 你的 CSVSink

# ---------- SQL 版 steps（沿用你現有的） ----------
from ..sql_mode.entry.steps import (
    resolve_connection,                     # (ctx, get_param, args) -> (adapter, is_sqlite, sql_cfg)
    choose_columns_and_io_cols,             # (ctx, get_param, adapter, sql_cfg, args) -> columns
    configure_flatten_options as cfg_sql,   # (ctx, get_param, args) -> None
    ensure_schemas as ensure_sql,           # (ctx, adapter, columns, is_sqlite, sql_cfg)
    maybe_reset_output_col as reset_sql,    # (ctx, is_sqlite, sql_cfg, columns, args)
    build_pending_iter as build_sql_iter,   # (adapter, ctx)
)

# ---------- Table 共用 steps（Excel/CSV 同構） ----------
#from tabular.steps import (
from ..tabular_mode.entry.steps import (
    resolve_tabular_paths,          # (ctx, get_param, args) -> (input_path, output_path)
    choose_columns_common,          # (ctx, input_path, get_param, args) -> columns
    configure_flatten_common,       # (ctx, get_param, args) -> None
    ensure_schemas_tabular,         # (ctx, input_path, output_path, fmt) -> None
    maybe_reset_output_tabular,     # (ctx, input_path, output_path, fmt, args) -> None
    build_pending_iter_tabular,     # (ctx, input_path, output_path, fmt) -> iterator
)

@dataclass(frozen=True)
class Backend:
    name: str
    resolve: Callable[[Any, Callable, Any], Dict[str, Any]]
    choose_columns: Callable[[Any, Dict[str, Any], Callable, Any], Any]
    configure_flatten: Callable[[Any, Callable, Any], None]
    ensure_schemas: Callable[[Any, Dict[str, Any], Any], None]
    maybe_reset_output: Callable[[Any, Dict[str, Any], Any, Any], None]
    build_pending_iter: Callable[[Any, Dict[str, Any]], Any]
    make_sink: Callable[[Any, Dict[str, Any]], Any]
    error_log_name: Callable[[Any, Dict[str, Any]], str]
    connection_ctx_key: str = "connection_ctx"

# ---------- SQL Backend ----------
def _sql_resolve(ctx, get_param, args):
    adapter, is_sqlite, sql_cfg = resolve_connection(ctx, get_param, args)
    return {
        "adapter": adapter,
        "is_sqlite": is_sqlite,
        "sql_cfg": sql_cfg,
        "connection_ctx": adapter.connect(),
    }

def _sql_choose(ctx, env, get_param, args):
    return choose_columns_and_io_cols(ctx, get_param, env["adapter"], env["sql_cfg"], args)

def _sql_ensure(ctx, env, columns):
    ensure_sql(ctx, env["adapter"], columns, env["is_sqlite"], env["sql_cfg"])

def _sql_reset(ctx, env, columns, args):
    reset_sql(ctx, env["is_sqlite"], env["sql_cfg"], columns, args)

def _sql_build_iter(ctx, env):
    return build_sql_iter(env["adapter"], ctx)

def _sql_sink(ctx, env):
    return SqlSink(ctx, is_sqlite=env["is_sqlite"])

def _sql_err(ctx, env):
    tbl = getattr(ctx, "target_table", None) or ctx.sql_table
    return f"{tbl}_{ctx.output_col}_error_log.txt"

SQL_BACKEND = Backend(
    name="sql",
    resolve=_sql_resolve,
    choose_columns=_sql_choose,
    configure_flatten=cfg_sql,
    ensure_schemas=_sql_ensure,
    maybe_reset_output=_sql_reset,
    build_pending_iter=_sql_build_iter,
    make_sink=_sql_sink,
    error_log_name=_sql_err,
)

# ---------- TABLE Backend（Excel/CSV 同一套 steps，依副檔名挑 Sink） ----------
def _table_resolve(ctx, get_param, args):
    in_path, out_path = resolve_tabular_paths(ctx, get_param, args)
    ctx.current_input_path  = os.path.abspath(in_path)
    ctx.current_output_path = os.path.abspath(out_path)
    fmt = "csv" if str(out_path).lower().endswith(".csv") else "excel"
    #print("~"*50)
    #print("fmt in _table_resolve",fmt)
    return {
        #"input_path": in_path, 
        #"output_path": out_path, 
        "input_path": ctx.current_input_path,   # 或直接用當下取到的 input_path
        "output_path": ctx.current_output_path,
        "fmt": fmt, "connection_ctx": None, "is_sqlite": False}

def _table_choose(ctx, env, get_param, args):
    return choose_columns_common(ctx, env["input_path"], get_param, args)

def _table_ensure(ctx, env, columns):
    ensure_schemas_tabular(ctx, env["input_path"], env["output_path"], env["fmt"])

def _table_reset(ctx, env, columns, args):
    maybe_reset_output_tabular(ctx, env["input_path"], env["output_path"], env["fmt"], args)

def _table_build_iter(ctx, env):
    return build_pending_iter_tabular(ctx, env["input_path"], env["output_path"], env["fmt"])

def _table_sink(ctx, env):
    print(f"returning the table sink for {ctx}")
    if env["fmt"] == "excel":
        return ExcelSink(ctx, 
                         input_path=env["input_path"], output_path=env["output_path"],
                        #input_path=getattr(ctx, "current_input_path", None) or getattr(ctx, "input_excel_file", ""),
                        #output_path=getattr(ctx, "current_output_path", None) or getattr(ctx, "output_excel_file", ""),
                        main_sheet = "LLM_result",
                         flush_main_every=10, flush_sub_every=10)
    else:
        return CSVSink(ctx, main_csv=env["output_path"])


def _table_err(ctx, env):
    return f"{Path(env['output_path']).stem}_{ctx.output_col}_{env['fmt']}_error_log.txt"

TABLE_BACKEND = Backend(
    name="table",
    resolve=_table_resolve,
    choose_columns=_table_choose,
    configure_flatten=configure_flatten_common,
    ensure_schemas=_table_ensure,
    maybe_reset_output=_table_reset,
    build_pending_iter=_table_build_iter,
    make_sink=_table_sink,
    error_log_name=_table_err,
)

# ---------- 後端選擇 ----------
def _select_backend(ctx, get_param) -> Backend:
    mode = getattr(ctx, "mode", "").lower()
    return SQL_BACKEND if mode == "sql" else TABLE_BACKEND

# ---------- 單一入口 ----------
def handle_data_mode(ctx, get_param, args):
    backend = _select_backend(ctx, get_param)

    env = backend.resolve(ctx, get_param, args)
    cm = env.get(backend.connection_ctx_key)
    enter_cm = (cm is not None)

    def _run():
        cols = backend.choose_columns(ctx, env, get_param, args)
        backend.configure_flatten(ctx, get_param, args)
        backend.ensure_schemas(ctx, env, cols)
        backend.maybe_reset_output(ctx, env, cols, args)
        #print("ctx in handle_data_mode",ctx)
        if not args.config:
            print_cli_usage_hint(ctx)
        ctx.error_log_path = backend.error_log_name(ctx, env)

        pending_iter = backend.build_pending_iter(ctx, env)
        sink = backend.make_sink(ctx, env)
        run_pipeline(ctx, pending_iter, is_sqlite=env.get("is_sqlite", False), sink=sink)

    if enter_cm:
        with cm:
            _run()
    else:
        _run()
