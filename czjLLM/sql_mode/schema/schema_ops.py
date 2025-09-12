# schema/schema_ops.py
from typing import List, Tuple

# 仍沿用你既有工具；此步先包裝，不更動內部行為
from sql_utils.column_utils import ensure_sql_columns_exist  # 仍可保留以後用
from sql_utils.column_utils import reset_output_col_with_backup
from row_processors.flatten_utils import auto_setup_subtable_if_needed

def ensure_main_schema(ctx, adapter, columns_in_src: List[str], cfg: dict):
    """
    1) 若 target_table 與 src_table 不同，先確保目標表存在（含 PK）。
    2) 確保輸出欄位與 update_time 欄位存在（型別由 adapter 決定）。
    3) 子表（flatten）先略過，後續步驟再接（避免一次改太多）。
    """
    if ctx.target_table != ctx.sql_table:
        adapter.ensure_table(ctx.target_table, ctx.primary_key)

    need_cols: List[Tuple[str, str]] = [(ctx.output_col, "NVARCHAR(MAX)")]
    if getattr(ctx, "record_update_time", False):
        need_cols.append(("update_time", "DATETIME"))

    adapter.ensure_columns(ctx.target_table, need_cols)

def ensure_flatten_schema(ctx, cursor, is_sqlite: bool):
    """
    確保扁平化子表存在且欄位就緒（只做 DDL，不處理 DML）。
    """
    auto_setup_subtable_if_needed(ctx, cursor, is_sqlite)
    
def maybe_reset_output(ctx, is_sqlite: bool):
    """
    保留你原本的「備份後重置輸出欄位」流程。
    """
    reset_output_col_with_backup(ctx, is_sqlite)
