# excel_mode/entry/handle_excel.py
from .steps import (
    resolve_file, choose_columns, maybe_reset_output_col,
    build_pending_iter, configure_flatten_options, ensure_schemas
)
from ..runtime.sinks.excel_sink import ExcelSink
from ...sql_mode.runtime.orchestrator import run_pipeline  # 共用同一 orchestrator
from cli_tools.cli_utils import print_cli_usage_hint

def handle_excel_mode(ctx, get_param, args):
    print("📄 Excel 模式：將逐列處理指定檔案")

    # 1) 選檔案 & 路徑
    input_path, output_path = resolve_file(ctx, get_param, args)

    # 2) 挑欄位（input/output）
    columns = choose_columns(ctx, input_path, get_param, args)

    # 3) 展平選項（跟 SQL 流程一致）
    configure_flatten_options(ctx, get_param, args)

    # 4) 確保主檔欄位（output / update_time），子表先不強制建立，交給 sink 的 ensure_flatten_schema
    ensure_schemas(ctx, input_path, output_path)

    # 5) 是否重置輸出欄位
    maybe_reset_output_col(ctx, input_path, output_path, args)

    if not args.config:
        print_cli_usage_hint(ctx)
    ctx.error_log_path = f"{ctx.task}_{ctx.output_col}_excel_error_log.txt"

    # 6) pending iterator
    pending_iter = build_pending_iter(ctx, input_path, output_path)

    # 7) 啟動管線（帶 ExcelSink）
    sink = ExcelSink(ctx, input_path=input_path, output_path=output_path, flush_every=10, main_sheet = "LLM_result")
    run_pipeline(ctx, pending_iter, is_sqlite=False, sink=sink)
