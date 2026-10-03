# schema/schema_ops.py
from typing import List, Tuple

# 仍沿用你既有工具；此步先包裝，不更動內部行為
from czjLLM.sql_utils.column_utils import ensure_sql_columns_exist  # 仍可保留以後用
from czjLLM.sql_utils.column_utils import reset_output_col_with_backup

def ensure_main_schema(ctx, adapter, columns_in_src: List[str], cfg: dict):
    """
    1) 若 target_table 與 src_table 不同，先確保目標表存在（含 PK）。
    2) 確保輸出欄位與 update_time 欄位存在（型別由 adapter 決定）。
    3) 子表（flatten）先略過，後續步驟再接（避免一次改太多）。
    """
    if ctx.target_table != ctx.sql_table:
        adapter.ensure_table(ctx.target_table, ctx.primary_key)

    output_cols = []
    if isinstance(getattr(ctx, "output_cols", None), list) and ctx.output_cols:
        output_cols.extend([str(c).strip() for c in ctx.output_cols if str(c).strip()])
    else:
        output_cols.append(str(ctx.output_col).strip())

    for rule in (getattr(ctx, "sql_writeback_rules", None) or []):
        if isinstance(rule, dict):
            c = str(rule.get("output_col", "")).strip()
            if c:
                output_cols.append(c)

    if bool(getattr(ctx, "sql_expand_json_to_columns", False)):
        raw = getattr(ctx, "allowed_output_fields", None)
        if isinstance(raw, (list, tuple)):
            prefix = str(getattr(ctx, "sql_expand_json_prefix", "") or "").strip()
            for c in raw:
                name = str(c).strip()
                if name:
                    output_cols.append(f"{prefix}{name}" if prefix else name)

    seen = set()
    dedup_cols = []
    for c in output_cols:
        if c and c not in seen:
            seen.add(c)
            dedup_cols.append(c)

    need_cols: List[Tuple[str, str]] = [(c, "NVARCHAR(MAX)") for c in dedup_cols]
    identity_column = str(getattr(ctx, "processing_identity_column", "") or "").strip()
    if getattr(ctx, "expected_execution_fingerprint", None) and identity_column:
        need_cols.append((identity_column, "NVARCHAR(255)"))
    if getattr(ctx, "record_update_time", False):
        need_cols.append(("update_time", "DATETIME"))

    adapter.ensure_columns(ctx.target_table, need_cols)

def ensure_flatten_schema(ctx, cursor, is_sqlite: bool):
    """
    確保扁平化子表存在且欄位就緒（只做 DDL，不處理 DML）。
    """
    from czjLLM.row_processors.flatten_utils import auto_setup_subtable_if_needed
    auto_setup_subtable_if_needed(ctx, cursor, is_sqlite)
    
def maybe_reset_output(ctx, is_sqlite: bool):
    """
    保留你原本的「備份後重置輸出欄位」流程。
    """
    reset_output_col_with_backup(ctx, is_sqlite)
