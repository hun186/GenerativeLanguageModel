# excel_mode/schema/subtable_ops.py
from pathlib import Path
from czjLLM.job_manager.console_ui import tlog_warn

INVALID_SHEET_CHARS = set(':\\/?!*[]')  # Excel 不允許的字元

def _sanitize_sheet_name(name: str) -> str:
    if not name:
        return "flattened"
    # 移除不允許字元、修剪空白與單引號、限制長度 31
    cleaned = "".join(ch for ch in name if ch not in INVALID_SHEET_CHARS).strip().strip("'")
    return (cleaned or "flattened")[:31]

def ensure_excel_subtable_config(ctx, output_path: str):
    """
    - 設定 Excel 展平所需的子表(sheet)名稱與欄位規則
    - 規則：若主鍵 == 輸入欄，則不再另外把輸入欄寫入子表（避免重複/衝突）
    - ctx.subtable_input_col：實際要寫入子表的「原始輸入欄位名」，可能為 None
    """
    # 1) 預設主鍵（僅在未提供時才設）
    if not getattr(ctx, "primary_key", None):
        # 你可用 'row_id' 或其他 sentinel；務必與 ExcelSink 的查找邏輯一致
        ctx.primary_key = "row_id"

    # 2) 預設子表（工作表）名稱
    if not getattr(ctx, "subtable_name", None):
        # 用輸出欄組名，避免路徑太長
        ctx.subtable_name = f"{ctx.output_col}_flattened"
    # 若你的專案有此工具就保留；沒有可簡單替換不合法字元
    try:
        ctx.subtable_name = _sanitize_sheet_name(str(ctx.subtable_name))
    except Exception:
        # 簡易容錯：去除不合法字元並截長
        safe = str(ctx.subtable_name)
        for bad in r'[]:*?/\\':
            safe = safe.replace(bad, "_")
        ctx.subtable_name = safe[:31]  # Excel sheet 名最長 31 chars
