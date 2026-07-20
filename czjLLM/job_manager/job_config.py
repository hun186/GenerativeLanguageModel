import os
import json
from pathlib import Path
import re
from colorama import Fore#, Back, Style
import inspect
import importlib.util
import yaml
import math
import shutil
import subprocess
from collections.abc import Mapping

from czjLLM.utilities.path_utils import llm_channel_dir


from utils.selector import OptionSelector
from utils.utilities import countdown_pause
from utils.utilities_path import MKDIR
from utils.utilities_path import getSubdirectory

from GenerativeLanguageModel.czjLLM.taskConfig import taskSetting
from GenerativeLanguageModel.czjLLM.modelConfig import modelSetting

#DEFAULT_MODEL = 'qwen3:32b-ctx-32k-premises-q4'
#DEFAULT_MODEL = 'gpt-oss:latest-ctx-32k-premises-MXFP4'
DEFAULT_MODEL = 'gpt-oss:120b-ctx-32k-premises-MXFP4'


def load_config_from_file(PGMSubDir="", config_path=""):
    paths_to_try = [
        config_path,
        os.path.join(PGMSubDir, config_path)
    ]

    for path in paths_to_try:
        #print("paths_to_try",path)
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f)

    print(f"❌ 找不到設定檔：{config_path} 或 {paths_to_try[1]}")
    raise FileNotFoundError("設定檔不存在")

def load_sql_config_from_file(config_path: str) -> dict:
    ext = os.path.splitext(config_path)[1].lower()
    #print("config_path",config_path)
    if ext == ".py":
        spec = importlib.util.spec_from_file_location("sql_config", config_path)
        config_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(config_module)
        return {k: getattr(config_module, k) for k in dir(config_module) if not k.startswith("__")}

    elif ext in [".yaml", ".yml"]:
        with open(config_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)

    else:
        raise ValueError(f"❌ 不支援的設定檔副檔名：{ext}")

def load_es_config_from_file(config_path: str) -> dict:
    """
    與 load_sql_config_from_file 相同，只是命名區分 ES
    """
    ext = os.path.splitext(config_path)[1].lower()
    if ext == ".py":
        spec = importlib.util.spec_from_file_location("es_config", config_path)
        config_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(config_module)
        return {k: getattr(config_module, k) for k in dir(config_module) if not k.startswith("__")}

    elif ext in [".yaml", ".yml"]:
        with open(config_path, "r", encoding="utf-8") as f:
            #print("load es config res",yaml.safe_load(f))
            return yaml.safe_load(f)

    else:
        raise ValueError(f"❌ 不支援的設定檔副檔名：{ext}")
    

def resolve_task_spec(task, task_pool=None):
    """Classify whether ``task`` is a known task name or an inline task spec.

    This exists because ``handle_txt_file`` already imports it before deciding
    whether to call ``showTemplate`` for named tasks or to print an inline-task
    preview.
    """
    pool = task_pool if isinstance(task_pool, Mapping) else taskSetting

    if isinstance(task, str) and task in pool:
        return "named", pool[task]
    if isinstance(task, str) and task in taskSetting:
        return "named", taskSetting[task]
    return "custom", task


def _preview_callable(func):
    try:
        return inspect.getsource(func).strip()
    except (OSError, TypeError):
        try:
            return f"{getattr(func, '__name__', '<callable>')}{inspect.signature(func)}"
        except (TypeError, ValueError):
            return "<callable>"


def task_template_preview(task, task_pool=None):
    """Return text used only for diagnostic preview output.

    ``pipeline_controller`` imports this function at module import time.  Keeping
    it in ``job_config`` fixes that import path while preserving the previous
    behavior of previewing a task mapping's ``template`` when one is present.
    """
    _kind, spec = resolve_task_spec(task, task_pool=task_pool)

    if isinstance(spec, Mapping):
        template = spec.get("template")
        if callable(template):
            return _preview_callable(template)
        if template is not None:
            return str(template)
        return str(dict(spec))

    if callable(spec):
        return _preview_callable(spec)

    return str(spec or "")

class LLMJobConfig:
    def __init__(self):
        self.PGMSubDir = ""
        self.mode = ""
        self.task = "Summary-toTWZH"
        # 統一把全域 taskSetting 掛到 ctx，讓 ES/SQL/Table/TXT 與 row-scoped
        # CtxOverlay 都透過同一個 ctx.taskSetting 解析 @taskSetting。
        self.taskSetting = taskSetting
        #self.textclass_tuple = None
        self.textClass = ""
        self.exclusiveTextClass = ""
        self.keyConsiderations = ""
        #self.model_spec_name = "deepseek-v3-num-16k-max_token-8k-cloud"
        self.model_spec_name = "gpt-oss:latest-ctx-32k-premises-MXFP4"
        self.model_spec = {}
        self.merge_slices = False
        self.prompt_dir = "Prompt"
        self.llm_source_dir = ""
        self.llm_source_backup_dir = ""
        self.llm_source_finished_dir = ""
        self.work_pool_root = ""
        self.on_premises = True
        self.max_tokens = 4096
        self.n_process = 1
        self.channel = ""
        self.input_excel_file = ""
        self.output_excel_file = ""
        self.input_col = ""
        self.output_col = ""
        self.output_profile = "auto"
        self.pipeline_name = ""
        self.stage_cfg = {}
        self.record_update_time = None
        self.sql_config_file = ""
        self.flatten_json_output = False
        self.allowed_output_fields = []  # 允許從 JSON 中展平的欄位名稱
        self.save_raw_input_when_flatten = None  # 展平時仍備查存入原始欄位輸入
        #self.save_raw_output_when_flatten = None  # 展平時仍備查存入原始欄位輸出
        self.debug = False
        self.removeFinPromptFile = True
        self.mp_for_all_call = True
        #self.no_think = True
        #self.think_mode = False
        self.think_mode = True
        self.current_file = None
        self.main_file_name = None
        self.n_cut = 0
        self.removeFinPromptFile = True
        self.load_low_watermark = 8
        self.load_high_watermark = 20
        self.per_round_limit = 128
        self.llm_round_debug = None
        self.combine_debug = False
    def __repr__(self):
        return "no show temp"
    def __repr__pending(self):
        import io, datetime, pathlib, json
        def safe(o):
            if o is Ellipsis:
                return "..."
            if isinstance(o, (str, int, float, bool)) or o is None:
                return o
            if isinstance(o, pathlib.Path):
                return str(o)
            if isinstance(o, (list, tuple, set)):
                return [safe(x) for x in o]
            if isinstance(o, dict):
                return {str(safe(k)): safe(v) for k, v in o.items()}
            if isinstance(o, (datetime.date, datetime.datetime)):
                return o.isoformat()
            if isinstance(o, io.IOBase):
                # 避免把整個 file handle 丟進 JSON
                name = getattr(o, "name", "")
                return f"<{o.__class__.__name__} {name}>"
            return repr(o)
    
        # 避免把私有屬性（如我們新增的 debug handle 等）也丟進去
        safe_dict = {k: safe(v) for k, v in self.__dict__.items() if not k.startswith("_")}
        try:
            return json.dumps(safe_dict, indent=2, ensure_ascii=False)
        except Exception:
            # 萬一還是失敗，就輸出最小必要資訊
            minimal = {k: safe_dict.get(k) for k in ("PGMSubDir","mode","task","model_spec_name","model_spec","n_process")}
            return json.dumps(minimal, indent=2, ensure_ascii=False)
    def __repr__old(self):
        def safe(obj):
            if isinstance(obj, Path):
                return str(obj)
            return obj
    
        safe_dict = {k: safe(v) for k, v in self.__dict__.items()}
        return json.dumps(safe_dict, indent=2, ensure_ascii=False)
    
class CtxOverlay:
    """Row-scoped 覆寫視圖：只記錄 overrides，其餘屬性回退到 base ctx。"""
    __slots__ = ("_base", "_ov")
    def __init__(self, base, **overrides):
        object.__setattr__(self, "_base", base)
        object.__setattr__(self, "_ov", dict(overrides))

    def __getattr__(self, key):
        ov = object.__getattribute__(self, "_ov")
        if key in ov:
            return ov[key]
        base = object.__getattribute__(self, "_base")
        return getattr(base, key)

    def __setattr__(self, key, value):
        if key in ("_base", "_ov"):
            object.__setattr__(self, key, value)
        else:
            self._ov[key] = value
            
def initialize_config(PGMSubDir, mode="txt", channel=None, model_spec_name=None, merge_slices=False,task_name=None):
    ctx = LLMJobConfig()

    ctx.PGMSubDir=PGMSubDir
    # 模型名稱（預設 deepseek-v2.5-ctx-8k-premises）
    ctx.mode = mode
    if ctx.mode in ["sql_to_excel"]:
        return ctx
    #print("modelSetting",modelSetting)
    ctx.model_spec_name = model_spec_name or set_model_spec()
    ctx.model_spec = modelSetting.get(ctx.model_spec_name)
    ensure_merge_defaults(ctx)

    if merge_slices is None:
        # 僅呼叫讓它修改 ctx，別把回傳值塞進 merge_slices
        set_merge_spec(ctx)
    else:
        ctx.merge_slices = bool(merge_slices)
    if ctx.model_spec is None:
        raise ValueError(f"❌ 找不到模型設定: {ctx.model_spec_name}")

    ctx.max_tokens = ctx.model_spec.get("num_ctx", 8192) // 2
    ctx.on_premises = ctx.model_spec.get("on_premises", True)
    ctx.n_process = set_nProcess(ctx.on_premises, ctx.model_spec["base_url"])
    ctx.load_low_watermark = 4*ctx.n_process
    ctx.load_high_watermark = 10*ctx.n_process
    
    # 任務
    # LLMJobConfig.__init__ 已設定；這裡再次刷新，避免測試或外部載入流程替換 taskSetting 後 ctx 仍保留舊引用。
    ctx.taskSetting = taskSetting
    ctx.task = task_name or set_task(ctx)

    # 頻道（txt 模式才有）
    if ctx.mode == "txt":
        ctx.channel = channel or set_channel(os.path.join(PGMSubDir, "LLMSourcePool"))
    elif ctx.mode == "table":
        ctx.channel = "excel_source"
    elif ctx.mode in ["sql","sql_to_excel"]:
        ctx.channel = "sql_cache"
    else:
        ctx.channel = "unspecified_channel"

    ctx.prompt_dir = os.path.join(PGMSubDir, "WorkPool_czjLLM", ctx.channel, "Prompt")
    ctx.llm_source_dir = llm_channel_dir(Path(PGMSubDir), ctx.channel)
    ctx.llm_source_backup_dir = llm_channel_dir(Path(PGMSubDir), ctx.channel, "_origin_backup")
    ctx.llm_source_finished_dir = llm_channel_dir(Path(PGMSubDir), ctx.channel, "_Finished")
    ctx.no_think = "qwen3" in ctx.model_spec_name

    def _sanitize(v):
        if v is Ellipsis:
            return None
        if isinstance(v, dict):
            return {k: _sanitize(x) for k, x in v.items()}
        if isinstance(v, (list, tuple, set)):
            return [ _sanitize(x) for x in v ]
        return v
    
    # 把 ctx 的屬性做一層清洗
    for k, v in list(ctx.__dict__.items()):
        ctx.__dict__[k] = _sanitize(v)
        
    return ctx

def init_task_context(ctx):
    task = ctx.task

    if task == "CLASS EXT":
        ctx.textClass = getTextClass(exclusive=False)[0]

    elif task == "CLASS Diff EXT":
        ctx.textclass_tuple = getTextClass(exclusive=True)
        ctx.textClass = ctx.textclass_tuple[0]
        ctx.exclusiveTextClass = ctx.textclass_tuple[1]

    elif task == "Risk Indicator Extraction":
        ctx.keyConsiderations = getKeyConsiderations()
        
def set_task(ctx):
    options = {k: v["CT_name"] for k, v in taskSetting.items()}
    ctx.task = OptionSelector(options=options, question="請選擇一個任務：").proc()
    init_task_context(ctx)
    return ctx.task


def extract_ctx_key(model_key):
    """
    從模型名稱中提取 ctx 數字，例如 'qwen2.5-ctx-32k-premises-q4' → (model_family, 32)
    """
    ctx_match = re.search(r"ctx-(\d+)k", model_key)
    ctx_value = int(ctx_match.group(1)) if ctx_match else 0
    family_prefix = model_key.split("-ctx")[0]
    return (family_prefix, ctx_value)

def set_model_spec():
    # 排序模型 key：依模型家族名稱 + ctx 數字排序
    sorted_keys = sorted(modelSetting.keys(), key=extract_ctx_key)

    # 建立選項清單
    options = {
        key: f'建議任務：{modelSetting[key]["recommend_task"]}' if "recommend_task" in modelSetting[key] else ""
        for key in sorted_keys
    }

    print("=" * 50)
    model_spec = OptionSelector(
        options=options,
        question=f"{Fore.LIGHTYELLOW_EX}請選擇一個模型：{Fore.RESET}",
        #default='qwen2.5-ctx-32k-premises-q4'
        #default='qwen3:30b-a3b-ctx-32k-premises-q4'
        default=DEFAULT_MODEL
    ).proc()
    return model_spec

def ensure_merge_defaults(ctx):
    """
    設定（僅當未設置時）預設值：預設不合併。
    """
    ctx.merge_slices = bool(getattr(ctx, "merge_slices", False))

    ctx.merge_conflict_policy = str(getattr(ctx, "merge_conflict_policy", "prefer_left"))
    ctx.merge_dedup_lists = bool(getattr(ctx, "merge_dedup_lists", True))
    ctx.merge_log_changes = bool(getattr(ctx, "merge_log_changes", True))
    ctx.merge_max_log = int(getattr(ctx, "merge_max_log", 10))
    ctx.merge_log_to_file = bool(getattr(ctx, "merge_log_to_file", False))
    ctx.merge_log_file = str(getattr(ctx, "merge_log_file", "merge_dict_slices_audited.log"))
    return ctx

def set_merge_spec(ctx):
    """
    互動式詢問：是否啟用切片合併 ->（若啟用）選擇衝突策略與去重、是否記錄變更。
    預設不合併。
    """
    ensure_merge_defaults(ctx)

    print("=" * 50)
    yn = OptionSelector(
        options={
            "off": "不合併（預設）—保留每個切片各自結果",
            "on":  "合併為單一結構（可選策略與列表去重）",
        },
        question=f"{Fore.LIGHTYELLOW_EX}是否啟用『切片合併』？{Fore.RESET}",
        default=("on" if ctx.merge_slices else "off"),
    ).proc()

    ctx.merge_slices = (yn == "on")

    if not ctx.merge_slices:
        print("切片合併：關閉（將直接寫回 list[dict] 結果）")
        return ctx
    #ensure_merge_defaults(ctx)
    # 衝突策略
    policy = OptionSelector(
        options={
            "prefer_left":  "遇到同鍵衝突：保留左側（較早切片）",
            "prefer_right": "遇到同鍵衝突：保留右側（較晚切片）",
        },
        question=f"{Fore.LIGHTYELLOW_EX}選擇合併『衝突策略』：{Fore.RESET}",
        default=ctx.merge_conflict_policy,
    ).proc()
    ctx.merge_conflict_policy = policy

    # 列表去重
    dedup = OptionSelector(
        options={
            "true":  "列表合併時去重（建議）",
            "false": "列表合併時不去重",
        },
        question=f"{Fore.LIGHTYELLOW_EX}列表去重設定：{Fore.RESET}",
        default=("true" if ctx.merge_dedup_lists else "false"),
    ).proc()
    ctx.merge_dedup_lists = (dedup == "true")

    # 是否顯示變更摘要（stdout）
    logchg = OptionSelector(
        options={
            "true":  "顯示變更摘要（列出少量樣本）",
            "false": "不顯示變更摘要",
        },
        question=f"{Fore.LIGHTYELLOW_EX}是否顯示合併『變更摘要』？{Fore.RESET}",
        default=("true" if ctx.merge_log_changes else "false"),
    ).proc()
    ctx.merge_log_changes = (logchg == "true")

    # 是否寫檔（可選）
    logfile = OptionSelector(
        options={
            "off": "不寫檔（僅 stdout）",
            "on":  f"寫入檔案：{ctx.merge_log_file}",
        },
        question=f"{Fore.LIGHTYELLOW_EX}是否將變更摘要寫入檔案？{Fore.RESET}",
        default=("on" if ctx.merge_log_to_file else "off"),
    ).proc()
    ctx.merge_log_to_file = (logfile == "on")

    print(f"切片合併：啟用，策略={ctx.merge_conflict_policy}，列表去重={ctx.merge_dedup_lists}，"
         f"變更摘要={'on' if ctx.merge_log_changes else 'off'}，落檔={'on' if ctx.merge_log_to_file else 'off'}")
    return ctx.merge_slices
    
def set_channel(LLMSourceDirROOT):
    if not os.path.isdir(LLMSourceDirROOT):
        MKDIR(LLMSourceDirROOT)
    default_chan = "default channel"

    # 🔸 只列出非 excel_source 或 sql_cache 的子資料夾
    all_subdirs = getSubdirectory(ROOTPATH=LLMSourceDirROOT)
    filtered_subdirs = [subDir for subDir in all_subdirs if subDir not in ["excel_source","sql_cache"]]

    options = {subDir: "" for subDir in filtered_subdirs + [default_chan]}
    print("="*50)
    channel_dir = OptionSelector(
        options=options,question=f"{Fore.LIGHTYELLOW_EX}請輸入任務頻道名稱：{Fore.RESET}",
        default=default_chan
        ).proc()
    return channel_dir

'''
def set_nProcess(On_Premises,base_url):
    if On_Premises:
        #base_url有多個選擇時：
        if isinstance(base_url,list):
            return len(base_url)*2
        #如果base_url是惟一選擇的單一字串表示法情況時，則不使用len。
        else:
            return 1
    else:
        return 6
'''  

def _detect_gpu_count() -> int | None:
    """回傳可見 GPU 張數；偵測不到則回傳 None。"""

    # 1) 先看容器/環境變數（最便宜）
    for env_name in ("CUDA_VISIBLE_DEVICES", "NVIDIA_VISIBLE_DEVICES"):
        devices = os.environ.get(env_name)
        if devices:
            s = devices.strip().lower()
            if s in {"", "none", "void", "nodevfiles", "-1"}:
                return 0
            if s != "all":
                # 逗號分隔的 index/UUID/MIG ID
                parts = [p for p in re.split(r"\s*,\s*", devices) if p]
                if parts:
                    return len(parts)
            # 若是 "all" 就交由後續方法偵測

    # 2) PyTorch（若有安裝）
    try:
        import torch
        cnt = torch.cuda.device_count()
        if cnt is not None:
            return int(cnt)
    except Exception:
        pass

    # 3) NVIDIA：nvidia-smi
    try:
        if shutil.which("nvidia-smi"):
            # nvidia-smi -L：一行一張 GPU
            out = subprocess.run(
                ["nvidia-smi", "-L"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, timeout=3
            )
            if out.returncode == 0:
                lines = [ln for ln in out.stdout.splitlines() if ln.strip()]
                if lines:
                    return len(lines)

            # 後備：查詢 "Attached GPUs"
            out = subprocess.run(
                ["nvidia-smi", "-q"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, timeout=5
            )
            if out.returncode == 0:
                m = re.search(r"Attached GPUs\s*:\s*(\d+)", out.stdout)
                if m:
                    return int(m.group(1))
    except Exception:
        pass

    # 4) AMD ROCm：rocm-smi
    try:
        if shutil.which("rocm-smi"):
            out = subprocess.run(
                ["rocm-smi", "-i"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, timeout=3
            )
            # rocm-smi -i 會列出 GPU[0], GPU[1]... 的行
            cnt = len(re.findall(r"GPU\[\d+\]", out.stdout))
            if cnt:
                return cnt
    except Exception:
        pass

    return None


def _scale_by_gpu(multiplier: float = 2.5, fallback: int = 6) -> int:
    """以 GPU 張數 * multiplier（進位）計算，偵測不到則回退 fallback。"""
    g = _detect_gpu_count()
    if g is None or g <= 0:
        return fallback
    return max(1, math.ceil(g * multiplier))


def set_nProcess(On_Premises, base_url, multiplier: float = 2.5, fallback: int = 6) -> int:
    if On_Premises:
        # base_url 有多個選擇時
        if isinstance(base_url, list):
            return len(base_url) * 2
        # base_url 為單一字串時
        else:
            return 1
    else:
        # 智慧化：GPU 張數的 2.5 倍（進位），偵測不到回退為 6
        return _scale_by_gpu(multiplier=multiplier, fallback=fallback)

def getKeyConsiderations():
    # 讀取使用者輸入
    if not "keyConsiderations" in globals():
        global keyConsiderations
        keyConsiderations = input("請輸入關注風險指標：")
        print(f"輸入的關注風險指標為: {keyConsiderations}")
    return keyConsiderations

def getTextClass(exclusive = False):
    # 讀取使用者輸入
    if not "textClass" in globals():
        global textClass
        textClass = input("請輸入抽取目標類別：")
        print(f"輸入的類別為: {textClass}")
    if exclusive == True:
        if not "exclusiveTextClass" in globals():
            global exclusiveTextClass
            exclusiveTextClass = input("請輸入抽取目標排除類別：")
            print(f"輸入的排除類別為: {exclusiveTextClass}")
    else:
        exclusiveTextClass = None
    return textClass,exclusiveTextClass


def showTemplate(task=None):
    assert task in taskSetting,f"{task}不在taskSetting鍵值選項中！"
    print(f"{Fore.LIGHTYELLOW_EX}將執行任務{task}，template為{Fore.RESET}")
    source = inspect.getsource(taskSetting[task]["template"])
    varDic = globals().copy()
    for var in varDic.keys():
        if "_Rule" in var:
            source = source.replace("{"+var+"}",varDic[var])
    if task in ["CLASS EXT","CLASS Diff EXT"]:
        global textClass
        source = source.replace("{textClass}", f"{Fore.LIGHTGREEN_EX}{textClass}{Fore.RESET}")
        if task == "CLASS Diff EXT":
            global exclusiveTextClass
            source = source.replace("{exclusiveTextClass}", f"{Fore.LIGHTYELLOW_EX}{exclusiveTextClass}{Fore.RESET}")
    if "Translation" in task:
        if os.path.isfile("GenerativeLanguageModel/czjLLM/pre_trans_ak.py"):
            from GenerativeLanguageModel.czjLLM.pre_trans_ak import pre_trans
        if "pre_trans" in globals():
            from GenerativeLanguageModel.czjLLM.taskConfig_ANKInt import DETAIL_EXT_TRANS_Rule
            DETAIL_EXT_TRANS_Rule += f"特殊翻譯對照表字典如下 {pre_trans}"
            print(f"已載入特殊翻譯對照表字典，DETAIL_EXT_TRANS_Rule為{DETAIL_EXT_TRANS_Rule}")
            countdown_pause(15)
    
    print(source.strip().split('"template":')[1].strip())