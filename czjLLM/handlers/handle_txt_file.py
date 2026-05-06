import os
import shutil
import threading
from tqdm import tqdm
from colorama import Fore, Style#, Back
from typing import Callable

from czjLLM.prompt_pipeline.prompt_generator import process_file_to_prompt
from czjLLM.prompt_pipeline.pipeline_controller import process_prompt_and_merge
from czjLLM.job_manager.job_config import showTemplate
from czjLLM.job_manager.job_config import LLMJobConfig
from czjLLM.job_manager.job_config import resolve_task_spec
from czjLLM.job_manager.job_config import task_template_preview

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


def _shared_ctx(ctx):
    """Return the underlying shared ctx for CtxOverlay-like row contexts."""
    try:
        return object.__getattribute__(ctx, "_base")
    except Exception:
        return ctx


def _consume_template_display_slot(ctx) -> bool:
    """Atomically reserve the one-time template/preview display slot.

    SQL/table row processing wraps the global context in per-row overlays.  Writing
    ``shown_template`` only to the overlay makes every row think it is first,
    causing the prompt template and countdown to be printed repeatedly.  Reserve
    the slot on the shared base context so all overlays see the same state.
    """
    shared = _shared_ctx(ctx)
    lock = getattr(shared, "_shown_template_lock", None)
    if lock is None:
        lock = threading.Lock()
        try:
            setattr(shared, "_shown_template_lock", lock)
        except Exception:
            # Some test doubles may reject new attrs; continue without a lock.
            lock = None

    def _reserve() -> bool:
        if getattr(shared, "shown_template", False):
            try:
                setattr(ctx, "shown_template", True)
            except Exception:
                pass
            return False
        try:
            setattr(shared, "shown_template", True)
            setattr(ctx, "shown_template", True)
        except Exception:
            pass
        return True

    if lock is None:
        return _reserve()
    with lock:
        return _reserve()


def handle_single_input_file(
    file: str,
    ctx: LLMJobConfig | None = None,
    adjust: bool = True,
    pause_seconds: int = 0,
    defer_merge: bool = False,
    run_merge: LLMRunner | None = None,   # ← 改成 None
):
    ctx = ctx or LLMJobConfig()
    # 在切片前先保留一次性顯示權限，讓 row-scoped CtxOverlay 也能共用
    # 同一個 shown_template 狀態，避免平行/批次排程時每列都印完整 prompt。
    should_show_template = _consume_template_display_slot(ctx)
    try:
        setattr(ctx, "suppress_prompt_diagnostics", not should_show_template)
    except Exception:
        pass

    # A. 切片並產生 prompt
    #print("ctx in handle_single_input_file",ctx)
    process_file_to_prompt(file, ctx, adjust=adjust)
    #print("file name in handle_single_input_file",file)
    # 只在第一個檔案顯示範本＋倒數
    if should_show_template:
        task_pool = getattr(ctx, "taskSetting", None)
        task_kind, task_spec = resolve_task_spec(ctx.task, task_pool=task_pool)
        if task_kind == "named":
            showTemplate(task=ctx.task)
        else:
            preview = task_template_preview(task_spec)
            tlog(f"ℹ️ 自訂任務（非 taskSetting 鍵值），預覽內容：{str(preview)[:200]}")
        countdown_pause(pause_seconds)

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
