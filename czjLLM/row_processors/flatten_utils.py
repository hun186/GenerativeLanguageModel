import json
from czjLLM.sql_utils.schema_manager import ensure_subtable_exists
from czjLLM.sql_utils.column_utils import ensure_sql_columns_exist
from czjLLM.job_manager.console_ui import tlog_warn
from czjLLM.utilities.json_text_utils import loads_json_flexible

def auto_setup_subtable_if_needed(ctx, cursor, is_sqlite=False):
    if not hasattr(ctx, "subtable_name") or not ctx.subtable_name:
        ctx.subtable_name = f"{ctx.target_table}_{ctx.output_col}_flattened"
    if not hasattr(ctx, "subtable_json_field") or not ctx.subtable_json_field:
        ctx.subtable_json_field = "items"
    ensure_subtable_exists(
        cursor,
        ctx.subtable_name,
        key_col=ctx.primary_key,
        input_col=ctx.input_col,
        seq_col="seq",
        is_sqlite=is_sqlite
    )
    
    save_raw_input = bool(getattr(ctx, "save_raw_input_when_flatten", False))
    if not save_raw_input:
        return  # 不需要原始輸入欄位，直接結束

    # 只要能拿到**非空**的欄位名才建立；否則告警並略過
    sub_input_col = getattr(ctx, "input_col", None)
    if not sub_input_col or not str(sub_input_col).strip():
        # 告警並略過（不建立、不寫入）
        try:
            tlog_warn("⚠️ save_raw_input_when_flatten=True，但未提供 subtable_input_col 或 input_col，略過原始輸入欄位。")
        except Exception:
            print("⚠️ save_raw_input_when_flatten=True，但未提供 subtable_input_col 或 input_col，略過原始輸入欄位。")
        # 明確關閉當前流程對原始輸入欄位的寫入（避免後續誤用舊值）
        ctx.save_raw_input_when_flatten = False
        #ctx.subtable_input_col = None
        return

    if ctx.primary_key == ctx.input_col:
        # 不建立 raw input 欄，因為 PK 就是原始輸入
        return
    # 正常情況：建立該欄位並記錄下來供後續寫入使用
    ensure_sql_columns_exist(cursor, ctx.subtable_name, [sub_input_col], is_sqlite)
    #ctx.subtable_input_col = sub_input_col
    
def extract_json_list_for_flatten(result, allowed_fields=None):
    """
    輸入result為字典清單，
    可依 allowed_fields 篩選result清單中各字典的留下欄位。
    """
    try:
        
        if isinstance(result, str):
            result = loads_json_flexible(result)
        # 允許 dict 直接展平成單筆，避免 source 設到 object JSON 時整批掉空。
        if isinstance(result, dict):
            result = [result]
        if not isinstance(result, list):
            raise TypeError(f"expect list/dict JSON, got {type(result).__name__}")
        
        cleaned = []

        for row in result:
            if not isinstance(row, dict):
                continue
            if allowed_fields:
                cleaned.append({k: row.get(k, "") for k in allowed_fields})
            else:
                cleaned.append(row)
        return cleaned
        
    except Exception as e:
        print(f"⚠️ JSON 解析失敗：{e}")
        return []
