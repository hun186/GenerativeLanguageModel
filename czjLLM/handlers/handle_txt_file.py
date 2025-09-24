import os
import shutil
from tqdm import tqdm
from colorama import Fore, Style#, Back
from typing import Callable

from czjLLM.prompt_pipeline.prompt_generator import process_file_to_prompt
from czjLLM.prompt_pipeline.pipeline_controller import process_prompt_and_merge
from czjLLM.job_manager.job_config import showTemplate
from czjLLM.job_manager.job_config import LLMJobConfig

from czjLLM.cli_tools.cli_utils import print_cli_usage_hint
from utils.utilities import countdown_pause
from utils.utilities import tlog
from utils.utilities_path import OSWALK
from utils.utilities_path import MKDIR
from utils.utilities_path import getPathFromFN
from utils.utilities_path import DirReplace
from utils.utilities_path import remove_empty_dirs

#from colorama import Fore, Style
#tlog = lambda s: tqdm.write(Fore.CYAN + s + Style.RESET_ALL)

# 定義一個介面：負責「依 ctx+file 處理並回傳輸出檔路徑」
LLMRunner = Callable[[LLMJobConfig, str], str]

def handle_single_input_file(
    file: str,
    ctx: LLMJobConfig | None = None,
    adjust: bool = True,
    pause_seconds: int = 0,
    defer_merge: bool = False,
    run_merge: LLMRunner | None = None,   # ← 改成 None
):
    ctx = ctx or LLMJobConfig()
    # A. 切片並產生 prompt
    #print("ctx in handle_single_input_file",ctx)
    process_file_to_prompt(file, ctx, adjust=adjust)
    #print("file name in handle_single_input_file",file)
    # 只在第一個檔案顯示範本＋倒數
    if not getattr(ctx, "shown_template", False):
        showTemplate(task=ctx.task)
        countdown_pause(pause_seconds)
        ctx.shown_template = True

    if defer_merge:
        return  # Streaming 模式下，合併交給消費者

    # **在執行時**才決定用哪個 run_merge（此時 monkeypatch 已生效）
    if run_merge is None:
        # 注意：這裡用模組層的名稱查找，會取到被 monkeypatch 後的版本
        run_merge = process_prompt_and_merge
        
    # 舊行為：單檔就地完成
    #CombBackFN = process_prompt_and_merge(ctx, file)
    CombBackFN = run_merge(ctx, file)
    des = DirReplace(file, ctx.llm_source_dir, ctx.llm_source_backup_dir)
    MKDIR(getPathFromFN(des))
    shutil.move(file, des)
    return CombBackFN

def handle_txt_mode(ctx, args): 
    # CLI 教學提示（如果來自互動模式）
    if not args.config:
        print_cli_usage_hint(ctx)
    all_files = [f for f in OSWALK(ctx.llm_source_dir) if os.path.splitext(f)[1].lower() == ".txt"]
    first = True
    for file in tqdm(all_files, desc=Fore.LIGHTGREEN_EX + "📁 檔案處理進度" + Style.RESET_ALL, ncols=80):
        print(f"\n🔄 正在處理檔案：{file}")
        if first:
            pause_seconds = 10
            #print("first")
            first = False
        else:
            pause_seconds = 0
        handle_single_input_file(file, ctx, pause_seconds=pause_seconds)
    remove_empty_dirs(ctx.prompt_dir)