#prompt_pipeline/prompt_generator.py
import os
from colorama import Fore#, Back, Style
from typing import Optional
from ..taskConfig import taskSetting
#from czjLLM_utils import generate_prompt

import inspect

from ..tokenizer_utils import TokenizerWrapper
from ..utilities.llm_call_audit import clear_prompt_token_metadata, write_prompt_token_metadata
from ..job_manager.job_config import LLMJobConfig
from ..job_manager.job_config import getTextClass
from ..job_manager.job_config import getKeyConsiderations

from utils.utilities import countdown_pause
from utils.utilities_path import MKDIR
from utils.utilities_path import getPathFromFN
from utils.utilities_path import getMFNFromFN
from utils.utilities_path import DirReplace
from utils.utilities_path import clean_path_end_chars

# =========================
# /no_think 統一判斷與附加
# =========================

NO_THINK_SUFFIX = "/no_think"

# 只在此維護支援清單；外部程式碼只呼叫 should_disable_think()。
# 包含常見別名，順序由新到舊、精到泛，避免過度匹配。
_NO_THINK_MODELS = (
    "qwen3", "qwen-3",            # Qwen3 系列
    "qwen2.5", "qwen-2.5",        # Qwen2.5 系列
    "qwen2", "qwen-2",            # Qwen2 系列
    "qwen",                       # 泛匹配（最後）
)

def should_disable_think(model_name: str) -> bool:
    """
    回傳該模型是否建議自動附加 /no_think。
    目前針對 Qwen 家族（含 Qwen3 / Qwen2.5 / Qwen2 / Qwen）。
    """
    if not model_name:
        return False
    m = model_name.lower()
    return any(tag in m for tag in _NO_THINK_MODELS)

def _has_no_think_suffix(s: str, suffix: str = NO_THINK_SUFFIX) -> bool:
    """
    僅檢查「最後一行（忽略末尾空白行）」是否已以 suffix 結尾，
    避免重複附加。
    """
    if not s:
        return False
    last = next((ln for ln in reversed(s.rstrip().splitlines()) if ln.strip()), "")
    return last.rstrip().endswith(suffix)

def append_no_think_if_applicable(
    content: str,
    model_name: str,
    *,
    enabled: bool = True,
    override_suffix: Optional[str] = None,
    suffix: str = NO_THINK_SUFFIX,
) -> str:
    """
    依模型能力與設定決定是否附加 /no_think：

    - enabled=False：完全不處理（永不附加）。
    - override_suffix=None：依 should_disable_think(model_name) 自動判斷。
    - override_suffix=""（空字串）：明確「不要」附加（即使是 Qwen* 也不加）。
    - override_suffix="/no_think"：明確「強制」附加（若未重複才附）。
    """
    if not enabled:
        return content

    # 強制覆寫：空字串=不要；指定 suffix=強制附加（若未附加過）
    if override_suffix == "":
        return content
    if override_suffix == suffix:
        return content if _has_no_think_suffix(content, suffix) else (content.rstrip() + "\n" + suffix)

    # 自動判斷：只在 should_disable_think=True 時附加
    if not should_disable_think(model_name):
        return content
    return content if _has_no_think_suffix(content, suffix) else (content.rstrip() + "\n" + suffix)


def finalize_llm_user_content(
    content: str,
    *,
    model_spec=None,
    model_name: str = "",
    no_think_process: bool = True,
) -> str:
    """Apply the same runtime user-content suffix policy used at dispatch."""
    spec = dict(model_spec or {})
    effective_model = str(spec.get("model_name", model_name) or model_name or "")
    override_suffix = spec.get("no_think_suffix", None)
    return append_no_think_if_applicable(
        content=content,
        model_name=effective_model.lower(),
        enabled=bool(no_think_process),
        override_suffix=override_suffix,
    )


def _render_raw_task_prompt(task_text: str, content: str) -> str:
    """
    當 ctx.task 不是 taskSetting key（例如 multi-stage 直接給 prompt 字串）時，
    以「原樣提示詞 + 內容」方式產生 prompt，避免 KeyError 中斷切片流程。
    - 若 task_text 含 {content}，則以 format_map 注入。
    - 否則預設以兩行分隔拼接。
    """
    base = str(task_text or "").strip()
    if not base:
        return content

    if "{content}" in base:
        try:
            return base.format_map({"content": content})
        except Exception:
            # 格式化失敗（例如未轉義的大括號）時回退穩健拼接
            pass
    return f"{base}\n\n{content}"


def generate_prompt(content="",
                    keyConsiderations="",
                    MainFileName="",task = "",
                    think_mode = True):
    if task and task not in taskSetting.keys():
        print(f"taskSetting沒有任務{task}的設定。taskSetting任務有{taskSetting.keys()}")
    template_function = taskSetting[task]["template"]
    source_code = inspect.getsource(template_function)
    
    if content == "":
        print("WARNING! The input content for generate_prompt is empty, check if it is normal.")
    #if task in ["PDF OPT","PDF OPT-Instruction First"]:
    if "主檔名" in source_code:
        print(f"{Fore.LIGHTYELLOW_EX}輸入主檔名「{MainFileName}」至template_function。{Fore.RESET}")
        prompt = template_function(MainFileName=MainFileName,content=content)
    elif any([x in source_code for x in [
            "風險關注指標","風險等級與說明"]
              ]):
        if keyConsiderations == "":
            keyConsiderations = getKeyConsiderations()
        print(f"{Fore.LIGHTYELLOW_EX}輸入風險關注指標「{keyConsiderations}」至template_function。{Fore.RESET}")
        prompt = template_function(
            keyConsiderations=keyConsiderations,content=content)
    elif task in ["CLASS EXT","CLASS Diff EXT"]:
        if task == "CLASS Diff EXT":
            textClass,exclusiveTextClass = getTextClass(exclusive=True)
            prompt = template_function(
                textClass=textClass,exclusiveTextClass=exclusiveTextClass,content=content)
        else:
            textClass,_ = getTextClass(exclusive=False)
            prompt = template_function(textClass=textClass,content=content)
    elif task in taskSetting.keys():
        prompt = template_function(content=content)
    else:
        print(f'Allowed Task are {taskSetting.keys()}, not inclusive of the input task {task}')
        raise Exception
    #print("prompt",prompt)
    # ✅ 在此統一處理 no_think 的後綴
    return prompt + "\n/no_think" if not think_mode else prompt

def write_prompt_component_metrics(
    prompt_file: str,
    task_text: str,
    rendered_prompt: str,
    *,
    tokenizer: TokenizerWrapper | None = None,
    model_name: str = "",
    model_spec=None,
    no_think_process: bool = True,
    task: str = "",
    stage_identity: str = "",
    quiet: bool = False,
):
    """Refresh numeric prompt-component token metadata for the actual prompt.

    Existing metadata is cleared first so a tokenizer/count failure leaves the
    component metrics unknown instead of silently reusing stale stage values.
    """
    clear_prompt_token_metadata(prompt_file)
    tokenizer = tokenizer or TokenizerWrapper(model_name=model_name, task=task)
    try:
        task_text_tokens = tokenizer.count_tokens(task_text)
        finalized_prompt = finalize_llm_user_content(
            rendered_prompt,
            model_spec=model_spec,
            model_name=model_name,
            no_think_process=no_think_process,
        )
        rendered_prompt_tokens = tokenizer.count_tokens(finalized_prompt)
        metadata = {
            "task_text_tokens": task_text_tokens,
            "rendered_prompt_tokens": rendered_prompt_tokens,
            "template_tokens": max(rendered_prompt_tokens - task_text_tokens, 0),
        }
        write_prompt_token_metadata(prompt_file, stage_identity=stage_identity or task, **metadata)
        return metadata
    except Exception as exc:
        if not quiet:
            print(f"⚠️ prompt token component metrics unavailable: {type(exc).__name__}")
        return None


# 建立 module-level 記憶（若你後續要做跨段聚合可沿用）
_input_memory = {}

class PromptGenerator:
    """
    建議使用的產生器：集中管理 /no_think 判斷（依 model 與 think_mode）。
    - ctx.model_spec_name：模型名稱（如 "qwen3-32b-instruct"）
    - ctx.think_mode：True = 允許思考模式；False = 希望禁思考（若模型支援）
    """
    def __init__(self, ctx: LLMJobConfig):
        self.ctx = ctx

    def build(self, content: str) -> str:
        if not content.strip():
            print("⚠️ generate_prompt: content 為空，請確認是否為預期行為。")

        task = self.ctx.task
        if task not in taskSetting:
            prompt = _render_raw_task_prompt(str(task or ""), content)
            return append_no_think_if_applicable(
                prompt,
                getattr(self.ctx, "model_spec_name", "") or "",
                enabled=(not self.ctx.think_mode),
            )

        template_function = taskSetting[task]["template"]
        source_code = inspect.getsource(template_function)

        # 主檔名型任務
        if "主檔名" in source_code:
            print(f"{Fore.LIGHTYELLOW_EX}輸入主檔名「{self.ctx.main_file_name}」至 template_function。{Fore.RESET}")
            prompt = template_function(MainFileName=self.ctx.main_file_name, content=content)

        # 風險關注指標型任務
        elif any(x in source_code for x in ["風險關注指標", "風險等級與說明"]):
            print(f"{Fore.LIGHTYELLOW_EX}輸入風險關注指標「{self.ctx.keyConsiderations}」至 template_function。{Fore.RESET}")
            prompt = template_function(keyConsiderations=self.ctx.keyConsiderations, content=content)

        # 分類抽取任務
        elif task == "CLASS EXT":
            print(f"{Fore.LIGHTYELLOW_EX}輸入的類別為: {self.ctx.textClass}{Fore.RESET}")
            prompt = template_function(textClass=self.ctx.textClass, content=content)

        elif task == "CLASS Diff EXT":
            print(f"{Fore.LIGHTYELLOW_EX}目標類別為: {self.ctx.textClass}，排除類別為: {self.ctx.exclusiveTextClass}{Fore.RESET}")
            prompt = template_function(
                textClass=self.ctx.textClass,
                exclusiveTextClass=self.ctx.exclusiveTextClass,
                content=content,
            )

        # 其他一般任務
        else:
            prompt = template_function(content=content)

        # 新行為：依模型與 think_mode 決定是否附加 /no_think
        # enabled = not think_mode（希望禁思考才啟用附加邏輯）
        return append_no_think_if_applicable(
            prompt,
            getattr(self.ctx, "model_spec_name", "") or "",
            enabled=(not self.ctx.think_mode),
        )


def process_file_to_prompt(file_path, ctx, adjust=True):
    quiet = bool(getattr(ctx, "suppress_prompt_diagnostics", False))
    if not quiet:
        print(f"Start to run process_file_to_prompt for {file_path}")
    MainFileName = getMFNFromFN(file_path)
    with open(file_path, 'rt', encoding='utf-8') as fp:
        content = fp.read()
    tokenizer = TokenizerWrapper(model_name=ctx.model_spec_name, task=ctx.task)
    chunks = tokenizer.tokenize(text=content, adjust=adjust, max_tokens=ctx.max_tokens, quiet=quiet)

    ctx.current_file = file_path
    if ctx.llm_source_dir == "":
        ctx.llm_source_dir = os.path.dirname(ctx.current_file)
    ctx.main_file_name = MainFileName
    ctx.n_cut = len(chunks["ctxCut"])
    #print("ctx in process_file_to_prompt",ctx)
    for idx, CTXPiece in enumerate(chunks["ctxCut"]):
        #print("process_chunk_to_generate_prompt for i,CTXPiece",idx,CTXPiece)
        process_chunk_to_generate_prompt(idx, CTXPiece, ctx, tokenizer=tokenizer)
        
def process_chunk_to_generate_prompt(idx: int, ctx_piece: str, ctx: LLMJobConfig, tokenizer: TokenizerWrapper | None = None):
    if not ctx_piece.strip():
        print(f"⚠️ 第 {idx} 段內容為空，跳過。")
        return
    #print("ctx in process_chunk_to_generate_prompt",ctx)
    generator = PromptGenerator(ctx)
    prompt = generator.build(content=ctx_piece)
    tokenizer = tokenizer or TokenizerWrapper(
        model_name=ctx.model_spec_name, task=ctx.task
    )
    #print("ctx.current_file",ctx.current_file)
    #print("ctx.llm_source_dir",ctx.llm_source_dir)
    #print("ctx.prompt_dir",ctx.prompt_dir)
    prompt_output_dir = DirReplace(FilePath=ctx.current_file, SrcDir=ctx.llm_source_dir, DesDir=ctx.prompt_dir)
    #print("prompt_output_dir",prompt_output_dir)
    prompt_output_dir = os.path.join(getPathFromFN(prompt_output_dir), ctx.main_file_name, "TODO")
    prompt_output_dir = clean_path_end_chars(prompt_output_dir)
    MKDIR(prompt_output_dir)

    pad_len = len(str(ctx.n_cut))
    todo_fn = os.path.join(prompt_output_dir, f"{idx:0{pad_len}d}.txt")
    #print("os.path.dirname(todo_fn)",os.path.dirname(todo_fn))
    os.makedirs(os.path.dirname(todo_fn), exist_ok=True)
    #print("todo_fn",todo_fn)
    try:
        with open(todo_fn, 'wt', encoding='utf-8') as fp:
            #print(f"Writting prompt: {prompt} to {todo_fn}")
            #print("todo_fn",{todo_fn})
            fp.write(prompt)
        write_prompt_component_metrics(
            todo_fn,
            ctx_piece,
            prompt,
            tokenizer=tokenizer,
            model_name=ctx.model_spec_name,
            model_spec=getattr(ctx, "model_spec", None),
            task=ctx.task,
            stage_identity=str(ctx.task or ""),
            quiet=bool(getattr(ctx, "suppress_prompt_diagnostics", False)),
        )
    except Exception as e:
        print(f"❌ 寫入 {todo_fn} 失敗：{e}")

#def should_disable_think(model_name: str) -> bool:
#    return any(kw in model_name for kw in ["qwen3"])
