from czjLLM.utilities.file_utils import save_text_as_temp_file
from czjLLM.utilities.logging_utils import log_error
from czjLLM.utilities.path_utils import get_combined_result_path
from czjLLM.handlers.handle_txt_file import handle_single_input_file
import os
from colorama import Fore

def process_row_and_get_result(text: str, idx: int, ctx, pause_seconds: int) -> str:
    """
    給定輸入文字與索引，執行 prompt 處理流程，並傳回結果文字。
    如失敗則回傳 None。
    """
    if not text.strip():
        print(f"⚠️ 第 {idx+1} 筆輸入為空白，跳過")
        return None
    
    try:
        temp_txt_path = save_text_as_temp_file(text, ctx.llm_source_dir, idx)
        handle_single_input_file(temp_txt_path, ctx, pause_seconds=pause_seconds)
        CombBackFN = get_combined_result_path(temp_txt_path, ctx)

        if os.path.isfile(CombBackFN):
            with open(CombBackFN, "r", encoding="utf-8") as fp:
                return fp.read()
        else:
            raise FileNotFoundError(f"❌ 找不到輸出檔案：{CombBackFN}")
    except Exception as e:
        log_error(idx, str(e), ctx.error_log_path)
        print(Fore.RED + f"[第 {idx+1} 筆] 錯誤：{e}" + Fore.RESET)
        return None