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
from ..prompt_pipeline.pipeline_controller import start_watchdogs
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

# ---------- ES 版 steps ----------
# 延遲匯入，避免在 sql/table 模式下強依賴 elasticsearch 套件

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

# ---------- ES Backend ----------
def _es_resolve_old(ctx, get_param, args):
    es_client, index, es_cfg = resolve_es_connection(ctx, get_param, args)
    return {
        "es_client": es_client,
        "index": index,  # 改成 "index" 與其他函式一致
		"es_cfg":es_cfg
    }

def _es_resolve(ctx, get_param, args):
    from ..es_mode.entry.steps_es import resolve_es_connection
    adapter, es_cfg = resolve_es_connection(ctx, get_param, args)
    return {"adapter": adapter, "es_cfg": es_cfg, "connection_ctx": adapter}

def _es_choose_old(ctx, env, get_param, args):
    # 與 SQL 對齊：把 adapter 丟進去
    return choose_columns_es(ctx, get_param, env["adapter"], args)

def _es_choose(ctx, env, get_param, args):
    from ..es_mode.entry.steps_es import choose_columns_es
    return choose_columns_es(ctx, env, get_param, args)


def _es_configure(ctx, get_param, args):
    from ..es_mode.entry.steps_es import configure_flatten_es as cfg_es
    return cfg_es(ctx, get_param, args)

def _es_ensure(ctx, env, columns):
    from ..es_mode.entry.steps_es import ensure_schemas_es as ensure_es
    ensure_es(ctx, env["adapter"], columns, None)

def _es_reset(ctx, env, columns, args):
    from ..es_mode.entry.steps_es import maybe_reset_output_es as reset_es
    reset_es(ctx, env["adapter"], columns, args)

def _es_build_iter(ctx, env):
    from ..es_mode.entry.steps_es import build_pending_iter_es as build_es_iter
    return build_es_iter(env["adapter"], ctx)

def _es_sink(ctx, env):
    from ..es_mode.runtime.sinks.es_sink import ESSink
    adapter = env["adapter"]
    cfg = adapter.cfg
    rr = (cfg.get("rerun", {}) or {})

    # --- 萃取較短的 model_tag（保留你的智慧取法） ---
    def _short_tag_from_spec(spec: str) -> str:
        if not spec:
            return ""
        s = str(spec)
        for sep in ["premises", "MXFP", "@", "#"]:
            if sep in s:
                s = s.split(sep, 1)[0].rstrip("-_")
        # 例：gpt-oss:latest-ctx-32k-premises-MXFP4 -> gpt-oss:latest-ctx-32k
        return s

    # 1) 先用 rerun.model_tag，其次 ctx.model_tag，再次從 ctx.model_spec 推短標
    model_tag = rr.get("model_tag") \
        or getattr(ctx, "model_tag", None) \
        or (_short_tag_from_spec(getattr(ctx, "model_spec", "")) or None)

    # 2) pipeline_hash 維持以 rerun 為準（若無可再考慮自動推）
    pipeline_hash = rr.get("pipeline_hash")

    # 3) meta_field 預設為 output_col + "_meta"
    meta_field = rr.get("meta_field") or (getattr(ctx, "output_col", "LLM_result") + "_meta")

    # 4) 初始 meta_base（其餘欄位交由 ESSink._build_meta() 自動補齊）
    meta_base = {
        "model_tag":     model_tag,                          # ← 你的智慧取法保留
        "pipeline_hash": pipeline_hash,
        #"model_spec":    getattr(ctx, "model_spec", None),   # 完整模型名便於稽核
        "channel":       getattr(ctx, "channel", None),
        "source":        getattr(ctx, "source", None),
        "task":          getattr(ctx, "task", None),
        # "force_reason" 讓 _build_meta() 依 rerun 條件自動組合
    }

    return ESSink(
        ctx,
        es_client=adapter.es,
        index=cfg["tgt_index"],
        output_col=ctx.output_col,
        meta_field=meta_field,
        meta_base=meta_base
    )
    
def _es_sink_old(ctx, env):
    from ..es_mode.runtime.sinks.es_sink import ESSink
    # 你的 ESSink 若需要 es_client/index，可從 adapter.es / adapter.cfg 取
    # 也可讓 ESSink 直接吃 adapter，統一介面
    return ESSink(
        ctx,
        es_client=env["adapter"].es,
        index=env["adapter"].cfg["tgt_index"],
        output_col=ctx.output_col  # 若 ESSink 需要
    )

def _es_err_old(ctx, env):
    return f"{env['index']}_{ctx.output_col}_error_log.txt"

def _es_err(ctx, env):
    index = env["adapter"].cfg["tgt_index"] or env["adapter"].cfg["src_index"]
    return f"{index}_{ctx.output_col}_error_log.txt"

ES_BACKEND = Backend(
    name="es",
    resolve=_es_resolve,
    choose_columns=_es_choose,
    configure_flatten=_es_configure,
    ensure_schemas=_es_ensure,
    maybe_reset_output=_es_reset,
    build_pending_iter=_es_build_iter,
    make_sink=_es_sink,
    error_log_name=_es_err,
)

# ---------- 後端選擇 ----------
#def _select_backend(ctx, get_param) -> Backend:
#    mode = getattr(ctx, "mode", "").lower()
#    return SQL_BACKEND if mode == "sql" else TABLE_BACKEND

def _select_backend(ctx, get_param) -> Backend:
    mode = getattr(ctx, "mode", "").lower()
    if mode == "sql":
        return SQL_BACKEND
    elif mode in ["table", "csv", "excel"]:
        return TABLE_BACKEND
    elif mode == "es":
        return ES_BACKEND
    else:
        raise ValueError(f"未知的 backend mode: {mode}")
        
# ---------- 單一入口 ----------
def handle_data_mode(ctx, get_param, args):
    #print("ctx in handle_data_mode",ctx)
    backend = _select_backend(ctx, get_param)

    env = backend.resolve(ctx, get_param, args)
    cm = env.get(backend.connection_ctx_key)
    enter_cm = (cm is not None)
    # ★ 將 ES adapter 放進 ctx（讓 run_pipeline 取用）
    if backend.name == "es":
        ctx._es_adapter = env.get("adapter")
    else:
        ctx._es_adapter = None

    def _run():
        cols = backend.choose_columns(ctx, env, get_param, args)
        backend.configure_flatten(ctx, get_param, args)
        backend.ensure_schemas(ctx, env, cols)
        backend.maybe_reset_output(ctx, env, cols, args)
        #print("ctx in handle_data_mode",ctx)
        if not args.config:
            print_cli_usage_hint(ctx)
        ctx.error_log_path = backend.error_log_name(ctx, env)
        '''
        # ✅ 啟動 watchdog（ES 傳 adapter；其他 backend 傳 None）
        if backend.name == "es":
            start_watchdogs(
                ctx,
                env.get("adapter"),  # 這裡是 ElasticsearchAdapter
                ping_interval_sec=60,
                stall_idle_threshold_sec=600,
                stall_interval_sec=60,
                stacks_path=None,  # 走預設：work_dir/stacks.log
            )
        else:
            start_watchdogs(ctx, None)  # 只有進度停滯偵測
        '''  
        pending_iter = backend.build_pending_iter(ctx, env)
        sink = backend.make_sink(ctx, env)
        #print("sink in handle_data_mode",sink)
        run_pipeline(ctx, pending_iter, is_sqlite=env.get("is_sqlite", False), sink=sink)

    if enter_cm:
        with cm:
            _run()
    else:
        _run()
