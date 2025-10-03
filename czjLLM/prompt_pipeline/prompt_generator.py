import os
from colorama import Fore#, Back, Style
from ..taskConfig import taskSetting
#from czjLLM_utils import generate_prompt

import inspect

from ..tokenizer_utils import TokenizerWrapper
from ..job_manager.job_config import LLMJobConfig
from ..job_manager.job_config import getTextClass
from ..job_manager.job_config import getKeyConsiderations

from utils.utilities import countdown_pause
from utils.utilities_path import MKDIR
from utils.utilities_path import getPathFromFN
from utils.utilities_path import getMFNFromFN
from utils.utilities_path import DirReplace
from utils.utilities_path import clean_path_end_chars

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

# 建立 module-level 記憶
_input_memory = {}

class PromptGenerator:
    def __init__(self, ctx):
        self.ctx = ctx
        #print("self.ctx",self.ctx)
        
    def build(self, content: str) -> str:
        if not content.strip():
            print("⚠️ generate_prompt: content 為空，請確認是否為預期行為。")

        task = self.ctx.task
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
            prompt = template_function(textClass=self.ctx.textClass,
                                       exclusiveTextClass=self.ctx.exclusiveTextClass,
                                       content=content)

        # 其他一般任務
        else:
            prompt = template_function(content=content)

        return prompt + "\n/no_think" if not self.ctx.think_mode else prompt

def process_file_to_prompt(file_path, ctx, adjust=True):
    print(f"Start to run process_file_to_prompt for {file_path}")
    MainFileName = getMFNFromFN(file_path)
    with open(file_path, 'rt', encoding='utf-8') as fp:
        content = fp.read()
    tokenizer = TokenizerWrapper(model_name=ctx.model_spec_name, task=ctx.task)
    chunks = tokenizer.tokenize(text=content, adjust=adjust, max_tokens=ctx.max_tokens)

    ctx.current_file = file_path
    if ctx.llm_source_dir == "":
        ctx.llm_source_dir = os.path.dirname(ctx.current_file)
    ctx.main_file_name = MainFileName
    ctx.n_cut = len(chunks["ctxCut"])
    #print("ctx in process_file_to_prompt",ctx)
    for idx, CTXPiece in enumerate(chunks["ctxCut"]):
        #print("process_chunk_to_generate_prompt for i,CTXPiece",idx,CTXPiece)
        process_chunk_to_generate_prompt(idx, CTXPiece, ctx)
        
def process_chunk_to_generate_prompt(idx: int, ctx_piece: str, ctx: LLMJobConfig):
    if not ctx_piece.strip():
        print(f"⚠️ 第 {idx} 段內容為空，跳過。")
        return
    #print("ctx in process_chunk_to_generate_prompt",ctx)
    generator = PromptGenerator(ctx)
    prompt = generator.build(content=ctx_piece)
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
    except Exception as e:
        print(f"❌ 寫入 {todo_fn} 失敗：{e}")

def should_disable_think(model_name: str) -> bool:
    return any(kw in model_name for kw in ["qwen3"])