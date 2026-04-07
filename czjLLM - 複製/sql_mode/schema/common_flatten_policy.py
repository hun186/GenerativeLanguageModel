# schema/common_flatten_policy.py
from ...job_manager.console_ui import tlog,tlog_warn
def ensure_common_flatten_policy(ctx):
    """
    決定是否把『原始輸入欄位』額外寫入子表，並設定 ctx.subtable_input_col。
    規則：
      - 若未開啟 save_raw_input_when_flatten → 關閉並 subtable_input_col=None
      - 若沒提供 input_col → 關閉並告警
      - 若 primary_key == input_col → 關閉（PK 即為原始輸入，不必重複）
      - 其餘 → subtable_input_col = input_col
    回傳 bool：最後是否會寫 raw input 欄位
    """
    want_raw = bool(getattr(ctx, "save_raw_input_when_flatten", False))
    if not want_raw:
        ctx.subtable_input_col = None
        return False

    input_col = getattr(ctx, "input_col", None)
    if not isinstance(input_col, str) or not input_col.strip():
        # 沒有可用的輸入欄位名 → 關閉
        try:
            tlog_warn("⚠️ save_raw_input_when_flatten=True，但未提供 input_col，略過原始輸入欄位。")
        except Exception as ex:
            print("When run ensure_common_flatten_policy, the following error occurs:\n{ex}")
            pass
        ctx.save_raw_input_when_flatten = False
        ctx.subtable_input_col = None
        return False

    if getattr(ctx, "primary_key", None) == input_col:
        # PK 就是輸入欄，避免重複
        ctx.save_raw_input_when_flatten = False
        ctx.subtable_input_col = None
        try:
            tlog("ℹ️ 子表主鍵與輸入欄相同；已自動關閉 raw input 複寫（PK 即為原始輸入）。")
        except Exception as ex:
            print("When run ensure_common_flatten_policy, the following error occurs:\n{ex}")
        return False

    ctx.subtable_input_col = input_col
    return True
