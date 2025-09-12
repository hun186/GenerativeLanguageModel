# pipeline_controller.py
#from prompt_pipeline.llm_caller import LLMCaller
from prompt_pipeline.result_handler import PromptResultHandler
#from prompt_pipeline.retry_manager import PromptRetryManager
from prompt_pipeline.prompt_generator import generate_prompt
from prompt_pipeline.llm_caller import CallLLMAPI
from utilities.atomic_io import atomic_write_json, robust_json_read

from job_manager.end_point_manager import get_available_end_points
from job_manager.end_point_manager import select_model
#from job_manager.win_gui import try_start_gui  # 為避免循環，可移到檔頭
import os
from colorama import Fore, Style
from tqdm import tqdm
import re
import random
import json
import time
import threading, queue
from collections import defaultdict, Counter
from datetime import datetime
import sqlite3
import pyodbc
import shutil

from utilities.combine_utils import combine_api_finished_item
from utilities.combine_utils import combine_json_return
from utilities.logging_utils import CostLog
from utilities.logging_utils import log_error
from utils.utilities_path import OSWALK
from utils.utilities_path import getPathFromFN
from utils.utilities_path import DirReplace
from utils.utilities_path import MKDIR
from utils.utilities_path import safe_move
from utils.utilities import flattenList
from utils.utilities import tlog
from utils.MP_utils import multicoreJob

from sql_utils.common import quote_column
from sql_utils.writer import flatten_row_based_json_array_to_subtable
from sql_utils.row_utils import upsert_single_value
from row_processors.flatten_utils import extract_json_list_for_flatten
from utilities.path_utils import get_combined_result_path
from job_manager.console_ui import  tlog_warn

'''
class PromptPipelineController:
    def __init__(self, task, prompt_file, output_file, model_spec, content=""):
        self.task = task
        self.prompt_file = prompt_file
        #self.MainFileName = os.path.splitext(os.path.basename(self.prompt_file))[0]
        self.output_file = output_file
        self.model_spec = model_spec
        self.content = content or open(prompt_file, 'rt', encoding='utf-8').read()

    def run(self):
        #generator = PromptGenerator(
        #    task=self.task,
        #    MainFileName=self.MainFileName)
        #prompt = generator.build(self.content)

        llm = LLMCaller(model_spec=self.model_spec)
        response = llm.call(self.content,model_spec=self.model_spec)

        handler = PromptResultHandler(task=self.task)
        output = handler.clean_output(response.choices[0].message.content)

        if self.output_file:
            os.makedirs(os.path.dirname(self.output_file), exist_ok=True)
            with open(self.output_file, 'w', encoding='utf-8') as f:
                f.write(output)

        return output

class PromptPipelineControllerWrapper:
    def __init__(self, task, promptFile, OutputSaveFN, removeFinPromptFile,
                 max_tokens, #On_Premises, 
                 allow_to_retry, model_spec):
        self.task = task
        self.promptFile = promptFile
        
        self.OutputSaveFN = OutputSaveFN
        self.removeFinPromptFile = removeFinPromptFile
        self.max_tokens = max_tokens
        #self.On_Premises = On_Premises
        self.allow_to_retry = allow_to_retry
        self.model_spec = model_spec

        # 🔧 修正 base_url 為 list 的情況
        if isinstance(self.model_spec.get("base_url"), list):
            import random
            self.model_spec["base_url"] = random.choice(self.model_spec["base_url"])
            
        with open(promptFile, 'r', encoding='utf-8') as f:
            self.content = f.read()

        self.controller = PromptPipelineController(
            task=task,
            prompt_file=promptFile,
            output_file=OutputSaveFN,
            model_spec=model_spec,
            content=self.content
        )
        #self.MainFileName = os.path.splitext(os.path.basename(promptFile))[0]
    def proc(self):
        try:
            raw_text = self.controller.run()
            cost = 0
            retry_jobs = []

            # 處理與驗證結果
            result_handler = PromptResultHandler(task=self.task)
            cleaned_text = result_handler.clean_output(raw_text)

            if "to json" in self.task.lower() and self.allow_to_retry:
                valid, fixed_text = result_handler.validate_json(cleaned_text)
                if not valid:
                    print(f"⚠️ JSON 格式錯誤，將對 {self.promptFile} 進行切割重試")
                    retry_jobs = self.retry_with_split_input()
                    return "", cost, retry_jobs
                else:
                    cleaned_text = fixed_text

            # 寫入結果
            if self.OutputSaveFN and not retry_jobs:
                os.makedirs(os.path.dirname(self.OutputSaveFN), exist_ok=True)
                with open(self.OutputSaveFN, 'w', encoding='utf-8') as f:
                    f.write(cleaned_text)

            if self.removeFinPromptFile:
                os.remove(self.promptFile)

            return cleaned_text, cost, retry_jobs

        except Exception as e:
            print(f"❌ PromptPipelineControllerWrapper 錯誤：{e}")
            return None, 0, []

    def retry_with_split_input(self):
        # 從內容擷取輸入文字
        import re
        input_text = ""
        for pattern in [r"(?<=☆輸入文本：).*", r"(?<=☆下列為輸入任務文本：).*"]:
            m = re.search(pattern, self.content, re.DOTALL)
            if m:
                input_text = m.group().strip()
                break

        if not input_text:
            print("⚠️ 無法擷取原始輸入文本，放棄重試。")
            return []

        retry_mgr = PromptRetryManager(
            task=self.task,
            promptFile=self.promptFile,
            max_tokens=self.max_tokens,
            #on_premises=self.On_Premises,
            model_spec=self.model_spec
        )
        return retry_mgr.retry_split(input_text)
'''
# [ADD] －－－－ Global Load Meter / Registry －－－－

class ItemsRegistry:
    """
    執行緒安全：註冊「每列」的 item 目錄（含 TODO/Success）與對應 pk、暫存 txt。
    """
    def __init__(self):
        self.lock = threading.Lock()
        self._items = {}  # item_dir -> {"pk":..., "temp_txt":...}

    def add(self, item_dir, pk, temp_txt):
        with self.lock:
            self._items[item_dir] = {"pk": pk, "temp_txt": temp_txt}

    def list_items(self):
        with self.lock:
            return dict(self._items)

    def get(self, item_dir):
        with self.lock:
            return self._items.get(item_dir)

    def remove(self, item_dir):
        with self.lock:
            self._items.pop(item_dir, None)


def meter_path_init(ctx):
    """
    建議：檔名含 session 起始時間避免不同程序互蓋。
    """
    if not hasattr(ctx, "session_start_ts"):
        ctx.session_start_ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    #base_dir = getattr(ctx, "meter_dir", getattr(ctx, "llm_source_dir", "."))
    base_dir = getattr(ctx, "meter_dir", getattr(ctx, "PGMSubDir", "."))
    base_dir = os.path.join(base_dir,"logs")
    os.makedirs(base_dir, exist_ok=True)
    fn = os.path.join(base_dir, f"loadmeter_{ctx.session_start_ts}.json")
    # 初始內容
    init = {"rows": {}, "queue": {"pending": 0, "running": 0}}
    atomic_write_json(fn, init)
    return fn


def meter_init(meter_fn, ctx, low=None, high=None):
    low  = low  if low  is not None else max(16, getattr(ctx, "n_process", 4) * 4)
    high = high if high is not None else max(32, getattr(ctx, "n_process", 4) * 10)
    data = {
        "session_id": getattr(ctx, "session_start_ts", ""),
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "thresholds": {"low": low, "high": high},
        "workers": {"n_process": getattr(ctx, "n_process", 4)},
        "queue": {"pending": 0, "running": 0, "completed": 0},
        "rows": {}  # pk -> {"item_dir":..., "temp_txt":..., "total":0, "done":0, "status":"pending"}
    }
    #_meter_write_atomic(meter_fn, data)
    atomic_write_json(meter_fn, data)
    return data


def meter_read(meter_fn):
    #with open(meter_fn, "r", encoding="utf-8") as fp:
        #return json.load(fp)
    # 讀取時容忍 PermissionError/半寫入狀態
    return robust_json_read(
        meter_fn,
        default_factory=lambda: {"rows": {}, "queue": {"pending": 0, "running": 0}},
        retries=20,
        delay=0.05
    )


def meter_update(meter_fn: str, mutator):
    """
    讀→mutate→原子寫回。用 lock file 保護寫入（Windows 友善）。
    mutator: Callable(dict) -> None，原地修改字典。
    """
    lock = _lock_path(meter_fn)
    fd = _acquire_file_lock(lock)
    try:
        d = meter_read(meter_fn)
        if not isinstance(d, dict):
            d = {"rows": {}, "queue": {"pending": 0, "running": 0}}
        mutator(d)
        atomic_write_json(meter_fn, d)
        return d
    finally:
        _release_file_lock(fd, lock)
        
'''
def meter_update(meter_fn, updater):
    """
    原子更新：讀→改→寫（單程序多執行緒安全；跨程序並行風險較低，如需嚴格鎖可自行加入檔案鎖）
    """
    for _ in range(5):
        try:
            data = meter_read(meter_fn)
            updater(data)
            _meter_write_atomic(meter_fn, data)
            return data
        except Exception:
            time.sleep(0.05)
    # 最後一次嘗試
    data = meter_read(meter_fn)
    updater(data)
    _meter_write_atomic(meter_fn, data)
    return data
'''

'''
def _meter_write_atomic(meter_fn, data):
    tmp = meter_fn + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fp:
        json.dump(data, fp, ensure_ascii=False)
    os.replace(tmp, meter_fn)
'''

# —— 跨緒簡易鎖（lock file），避免多緒同時寫入 —— #
def _lock_path(meter_fn: str) -> str:
    return meter_fn + ".lck"

def _acquire_file_lock(lock_path: str, timeout: float = 10.0, stale: float = 120.0):
    """用 O_CREAT|O_EXCL 建 .lck；逾時或過期自動清除。回傳 fd 或 None。"""
    start = time.time()
    while True:
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, f"{os.getpid()}:{threading.get_ident()}:{time.time()}".encode())
            return fd
        except FileExistsError:
            # 鎖存在，檢查是否過期
            try:
                if time.time() - os.path.getmtime(lock_path) > stale:
                    os.remove(lock_path)
                    continue
            except FileNotFoundError:
                pass
            if time.time() - start > timeout:
                return None
            time.sleep(0.03)

def _release_file_lock(fd, lock_path: str):
    try:
        if fd is not None:
            os.close(fd)
        os.remove(lock_path)
    except FileNotFoundError:
        pass
    except OSError:
        pass
    
def find_item_dir_for(ctx, main_file_name: str) -> str:
    """
    從 ctx.prompt_dir 掃描出對應的 item 目錄（父級，底下有 TODO/Success）。
    """
    candidates = []
    for f in OSWALK(ctx.prompt_dir):
        parts = getPathFromFN(f).split("/")
        if parts[-1] in ["TODO", "Success"]:
            parent = "/".join(parts[:-1])
            if main_file_name in parent:
                candidates.append(parent)
    uniq = list(set(candidates))
    if not uniq:
        raise RuntimeError(f"找不到 item 目錄：{main_file_name}")
    return uniq[0]

# [ADD] －－－－ Streaming Consumer：批次消化 TODO 檔 －－－－

def pick_next_prompts(item_dirs, per_round_limit=128):
    """
    從多個 item_dir 挑選下一批 TODO prompt 檔（跨列混合），上限 per_round_limit。
    回傳 list[(prompt_file, item_dir)]
    """
    batch = []
    for item_dir in item_dirs:
        todo_dir = os.path.join(item_dir, "TODO")
        if not os.path.isdir(todo_dir):
            continue
        for pf in OSWALK(todo_dir):
            batch.append((pf, item_dir))
            if len(batch) >= per_round_limit:
                return batch
    return batch


def llm_stream_consumer(ctx, registry: ItemsRegistry, meter_fn: str, stop_event: threading.Event,
                        is_sqlite=False, per_round_limit=128):
    """
    持續從所有 item_dir 的 TODO 中抓取 prompt 檔，以小批次方式呼叫 LLM。
    － 每小批：pending->running->completed；按列累計 done，done==total 時合併寫回。
    － 無 TODO 且 stop_event 設定後結束。
    """
    # 單 Thread 中開 DB 連線，避免多執行緒/程序共用
    if getattr(ctx, "is_sqlite", is_sqlite):
        conn = sqlite3.connect(ctx.sqlite_path)
        cur = conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL;")
        cur.execute("PRAGMA synchronous=NORMAL;")
        cur.close()
    else:
        conn = pyodbc.connect(ctx.sql_connection_string)
    cursor = conn.cursor()

    try:
        while True:
            items_map = registry.list_items()
            item_dirs = list(items_map.keys())

            batch = pick_next_prompts(item_dirs, per_round_limit=per_round_limit)

            if not batch:
                # 沒事可做：若 producer 已結束且無 TODO，退出
                if stop_event.is_set():
                    # 再檢查一次是否真的都空了
                    if not pick_next_prompts(item_dirs, per_round_limit=1):
                        break
                time.sleep(0.1)
                continue

            prompt_files = [pf for pf, _ in batch]
            # 統計每個列（item_dir 對應 pk）的批次量
            count_by_item = Counter(item for _, item in batch)

            # ---- 1) 更新 meter：pending -= n, running += n
            total_n = len(prompt_files)
            meter_update(meter_fn, lambda d: _meter_on_dispatch(d, items_map, count_by_item, total_n))

            # ---- 2) 建立 Job 並執行（multicore）
            DTBJobs = []
            for pf, item_dir in batch:
                DTBJobs.append(PromptAPIPipeline(
                    task=ctx.task,
                    promptFile=pf,
                    OutputSaveFN=pf.replace("TODO", "Success"),
                    removeFinPromptFile=getattr(ctx, "removeFinPromptFile", True),
                    max_tokens=ctx.max_tokens,
                    allow_to_retry=True,
                    model_spec=ctx.model_spec,
                    PGMSubDir=ctx.PGMSubDir,
                ))
            MPresult = multicoreJob(DTBJobs=DTBJobs, nProcess=ctx.n_process, ShuffleJobs=False).run()
            # 失敗/重試的 prompt，會在 Pipeline 內生成新 TODO 檔，之後回合再吃

            # ---- 3) 更新 meter：running -= n, completed += n, rows[pk].done += 每列批次量
            meter_after = meter_update(meter_fn, lambda d: _meter_on_finish_batch(d, items_map, count_by_item, total_n))
            '''
            # ---- 4) 對「完成的列」合併與寫回
            done_pks = [pk for pk, st in meter_after["rows"].items() if st.get("status") == "ready_to_merge"]
            for pk in done_pks:
                st = meter_after["rows"][pk]
                _merge_and_write_single_row(ctx, pk, st, cursor, is_sqlite=is_sqlite)
                # 設為 merged
                meter_update(meter_fn, lambda d, _pk=pk: d["rows"][_pk].update({"status": "merged"}))
                # 備份原始 txt
                des = DirReplace(st["temp_txt"], ctx.llm_source_dir, ctx.llm_source_backup_dir)
                MKDIR(getPathFromFN(des))
                shutil.move(st["temp_txt"], des)
                # 從註冊器移除
                registry.remove(st["item_dir"])
            '''
    finally:
        cursor.close()
        conn.close()


def _meter_on_dispatch(d, items_map, count_by_item, total_n):
    d["queue"]["pending"]  = max(0, d["queue"]["pending"] - total_n)
    d["queue"]["running"] += total_n
    # 每列暫時不動 done/total；dispatch 僅改 queue 層級
    # 確保 rows entry 存在
    for item_dir, cnt in count_by_item.items():
        pk = items_map[item_dir]["pk"]
        d["rows"].setdefault(pk, {})


def _meter_on_finish_batch(d, items_map, count_by_item, total_n):
    d["queue"]["running"]   = max(0, d["queue"]["running"] - total_n)
    d["queue"]["completed"] += total_n
    for item_dir, cnt in count_by_item.items():
        pk = items_map[item_dir]["pk"]
        row = d["rows"].setdefault(pk, {})
        row["done"] = row.get("done", 0) + cnt
        total = row.get("total", 0)
        if total > 0 and row["done"] >= total and row.get("status") not in ("ready_to_merge", "merged"):
            row["status"] = "ready_to_merge"
    return d


'''
def _merge_and_write_single_row(ctx, pk, st, cursor, is_sqlite=False):
    item_dir = st["item_dir"]
    temp_txt = st["temp_txt"]
    # TODO 清空才合併（保險）
    todo_dir = os.path.join(item_dir, "TODO")
    if len(OSWALK(todo_dir)) == 0:
        combine_api_finished_item(item_dir, ctx)

    CombBackFN = get_combined_result_path(temp_txt, ctx)
    if not os.path.isfile(CombBackFN):
        raise FileNotFoundError(f"找不到輸出檔案：{CombBackFN}")

    with open(CombBackFN, "r", encoding="utf-8") as fp:
        result_text = fp.read()

    update_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S") if ctx.record_update_time else None
    upsert_single_value(ctx, cursor, pk, result_text,
                        is_sqlite=is_sqlite, update_time=update_time)

    if ctx.flatten_json_output:
        result_list = extract_json_list_for_flatten(result_text, ctx.allowed_output_fields)
        if result_list and ctx.subtable_name and ctx.allowed_output_fields:
            flatten_row_based_json_array_to_subtable(
                cursor=cursor,
                sub_table_name=ctx.subtable_name,
                pk_value=pk,
                json_array=result_list,
                key_col=ctx.primary_key,
                input_col=ctx.input_col,
                seq_col="seq",
                is_sqlite=is_sqlite
            )
    cursor.connection.commit()
    print(f"✅ 合併並寫入完成：{pk}")
'''

# [ADD] －－－－ Row Merger Watchdog：只要 TODO 清空就立刻合併寫回 －－－－
def row_is_ready(item_dir: str) -> bool:
    todo_dir = os.path.join(item_dir, "TODO")
    # TODO 目錄不存在或為空，都視為可合併
    return (not os.path.isdir(todo_dir)) or (len(OSWALK(todo_dir)) == 0)

from functools import partial
#from colorama import Fore, Style
#tlog = lambda s: tqdm.write(Fore.CYAN + s + Style.RESET_ALL)

def row_merger_watchdog(ctx, registry: ItemsRegistry, meter_fn: str, stop_event: threading.Event,
                        is_sqlite=False, scan_interval=0.2, done_q=None):
    """
    週期性掃描所有 item_dir：
    - 若 TODO 清空 → combine → upsert → commit → 備份原始 txt
    - 不依賴『done/total』計數，純看檔案狀態，確保「有 Success 就能寫回」
    """
    # Writer 專用連線
    if getattr(ctx, "is_sqlite", is_sqlite):
        conn = sqlite3.connect(ctx.sqlite_path, timeout=60)
        cur = conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL;")
        cur.execute("PRAGMA synchronous=NORMAL;")
        cur.close()
    else:
        conn = pyodbc.connect(ctx.sql_connection_string)
    cursor = conn.cursor()

    try:
        while True:
            items_map = registry.list_items()
            #print("items_map in row_merger_watchdog",items_map)
            if not items_map and stop_event.is_set():
                # 沒待合併的列且主流程告知可收尾 → 結束
                break

            progressed = False
            for item_dir, meta in list(items_map.items()):
                pk = meta["pk"]
                temp_txt = meta["temp_txt"]

                if not row_is_ready(item_dir):
                    continue  # TODO 尚未清空

                # 嘗試合併（idempotent）
                try:
                    combine_api_finished_item(item_dir, ctx)
                except Exception as e:
                    # 有些情況合併結果已存在，或 Success 尚未完全落地；下次再試
                    print(f"ℹ️ 合併提示（pk={pk}）：{e}")

                # 讀合併檔
                CombBackFN = get_combined_result_path(temp_txt, ctx)
                if not os.path.isfile(CombBackFN):
                    # 合併檔尚未產出（可能剛好 race），下輪再掃
                    continue

                try:
                    with open(CombBackFN, "r", encoding="utf-8") as fp:
                        result_text = fp.read()

                    update_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S") if ctx.record_update_time else None
                    upsert_single_value(ctx, cursor, pk, result_text,
                                        is_sqlite=is_sqlite, update_time=update_time)

                    if ctx.flatten_json_output:
                        result_list = extract_json_list_for_flatten(result_text, ctx.allowed_output_fields)
                        if result_list and ctx.subtable_name and ctx.allowed_output_fields:
                            save_input = bool(getattr(ctx, "save_raw_input_when_flatten", False))
                            input_col_value = None
                    
                            if save_input:
                                # 從主表撈回原始輸入文字（用主鍵比對）
                                try:
                                    fetch_sql = (
                                        f"SELECT {quote_column(ctx.input_col)} "
                                        f"FROM {quote_column(ctx.sql_table)} "
                                        f"WHERE {quote_column(ctx.primary_key)} = ?"
                                    )
                                    cursor.execute(fetch_sql, (pk,))
                                    r = cursor.fetchone()
                                    input_col_value = r[0] if r else None
                                except Exception as ex:
                                    tlog_warn(f"⚠️ 無法撈回原始輸入（pk={pk}）：{ex}")
                                    # 改為不寫入原始輸入
                                    save_input = False
                                    input_col_value = None
                            
                            flatten_row_based_json_array_to_subtable(
                                cursor=cursor,
                                sub_table_name=ctx.subtable_name,
                                pk_value=pk,
                                json_array=result_list,
                                key_col=ctx.primary_key,
                                seq_col="seq",
                                save_raw_input=save_input, # ✅ 開關
                                input_col=ctx.input_col, #子表欄位名，僅在 save_input=True 時生效/建立
                                input_col_value=input_col_value,# ✅ 值（可為 None）
                                is_sqlite=is_sqlite,
                            )

                    conn.commit()  # ✅ 用 conn.commit() 確保落地
                    tlog(f"✅ 逐列合併並寫入完成：{pk}")

                    # 備份原始 txt
                    des = DirReplace(temp_txt, ctx.llm_source_dir, ctx.llm_source_backup_dir)
                    MKDIR(getPathFromFN(des))
                    #shutil.move(temp_txt, des)
                    safe_move(temp_txt, des)

                    # 從 registry 移除，不再重複處理
                    registry.remove(item_dir)
                    
                    # [ADD] 告訴進度條：完成了一列
                    if done_q is not None:
                        done_q.put(pk)
                    try:
                        if hasattr(ctx, "gui_handle") and ctx.gui_handle:
                            ctx.gui_handle.inc_done(1)
                    except Exception:
                        pass
                        
                    # 更新負載檔狀態（若有）
                    try:
                        meter_update(meter_fn, lambda d, _pk=pk: d["rows"].setdefault(_pk, {}).update({"status": "merged"}))
                    except Exception:
                        pass

                    progressed = True
                except Exception as e:
                    log_error(-1, f"Row Merger 寫回失敗 pk={pk}: {e}", ctx.error_log_path)
                    # 寫回失敗不移除，下一輪重試

            if not progressed:
                time.sleep(scan_interval)
    finally:
        cursor.close()
        conn.close()









def process_prompt_and_merge(ctx, file_path):
    # 取得該檔案產生的 prompt 所在目錄
    prompt_items = []
    for file in OSWALK(ctx.prompt_dir):
        path_list = getPathFromFN(file).split("/")
        if path_list[-1] in ["TODO", "Success"]:
            parent_dir = "/".join(path_list[:-1])
            if ctx.main_file_name in parent_dir:
                prompt_items.append(parent_dir)
    prompt_items = list(set(prompt_items))

    # 呼叫 LLM API（可以開平行化）
    call_llm_api(prompt_items, ctx, allow_to_retry=True)
    call_llm_api(prompt_items, ctx, allow_to_retry=False)

    # 合併輸出
    for item in prompt_items:
        TodoSubDir = os.path.join(item, "TODO")
        if len(OSWALK(TodoSubDir)) == 0:
            combine_api_finished_item(item, ctx)
        else:
            print(f"{item} 尚有 {len(OSWALK(TodoSubDir))} 未處理")
            
def select_idle_ollama_url(base_urls, PGMSubDir=""):
    """
    在每次調用前，選擇負載最輕的 base_url。
    如果有多個 base_url 擁有相同的最小負載，則從中隨機選擇一個。
    如果 base_url 的負載檔案已經過期（超過10分鐘未更新），則重設負載。
    負載完成後釋放負載。
    """
    #print("base_urls in select_idle_ollama_url b4, base_urls",base_urls)
    #print("type(base_urls) b4",type(base_urls))
    if isinstance(base_urls,str):
        base_urls = [base_urls]
        #print("base_urls af",base_urls)
        #print("type(base_urls) af",type(base_urls))
    load_file = os.path.join(PGMSubDir, "base_url_load.json")
    
    # 檢查檔案是否存在並且過期（超過10分鐘未更新）
    if os.path.exists(load_file):
        file_mod_time = os.path.getmtime(load_file)
        current_time = time.time()
        
        # 如果檔案修改時間超過10分鐘，重設負載
        if current_time - file_mod_time > 600:  # 600秒 = 10分鐘
            print("檔案過期，重設負載數據。")
            load_data = {url: 0 for url in base_urls}
        else:
            try:
                with open(load_file, 'r') as f:
                    load_data = json.load(f)
            except (json.JSONDecodeError, ValueError) as e:
                # 如果讀取檔案或解析 JSON 失敗，重設負載
                print(f"讀取或解析檔案失敗，錯誤: {e}，重設負載數據。")
                load_data = {url: 0 for url in base_urls}
    else:
        # 如果檔案不存在，初始化負載數據
        load_data = {url: 0 for url in base_urls}

    for url in base_urls:
        if not isinstance(load_data.get(url), (int, float)):
            load_data[url] = 0
            
    # 找出最小負載的值
    min_load = min(load_data.values())
    
    # 找出所有負載為最小值的 base_url
    min_urls = [url for url, load in load_data.items() if load == min_load]

    # 如果有多個 base_url 擁有相同的最小負載，隨機選擇一個
    min_url = random.choice(min_urls)

    # 顯示選擇的 base_url 和當前負載
    print(f"選擇負載最輕的 base_url: {min_url}，當前負載: {load_data[min_url]}")
    
    # 更新負載，增加該 base_url 的負載
    load_data[min_url] += 1

    # 寫回負載數據
    with open(load_file, 'w') as f:
        json.dump(load_data, f)

    return min_url


def release_url_load(base_url, PGMSubDir=""):
    """
    釋放該 base_url 的負載，減少負載數據
    """
    load_file = os.path.join(PGMSubDir, "base_url_load.json")
    
    # 讀取當前負載情況
    if os.path.exists(load_file):
        try:
            with open(load_file, 'r') as f:
                load_data = json.load(f)
        except (json.JSONDecodeError, ValueError) as e:
            print(f"讀取負載檔案失敗，錯誤: {e}，重設負載數據。")
            load_data = {}

    else:
        load_data = {}

    # 減少選定 base_url 的負載
    if base_url in load_data and load_data[base_url] > 0:
        load_data[base_url] -= 1
        # 顯示釋放負載後的情況
        print(f"釋放 base_url: {base_url} 的負載，當前負載: {load_data[base_url]}")
        
    # 寫回更新後的負載數據
    try:
        with open(load_file, 'w') as f:
            json.dump(load_data, f)
    except IOError as e:
        print(f"無法寫入負載檔案，錯誤: {e}")

def call_llm_api(itemList, ctx, allow_to_retry=True,PGMSubDir=""):
    ArtCost = dict()
    DTBJobs_Retry = []
    def create_jobs(item,model_spec):
        TodoSubDir = os.path.join(item, "TODO")
        return [PromptAPIPipeline(
            task=ctx.task,
            promptFile=promptFile,
            OutputSaveFN=promptFile.replace("TODO", "Success"),
            removeFinPromptFile=ctx.removeFinPromptFile,
            max_tokens=ctx.max_tokens,
            #On_Premises=ctx.on_premises,
            allow_to_retry=allow_to_retry,
            model_spec=ctx.model_spec,
            PGMSubDir=ctx.PGMSubDir,
        ) for promptFile in OSWALK(TodoSubDir)]

    if ctx.mp_for_all_call:
        DTBJobs = []
        for item in itemList:
            DTBJobs.extend(create_jobs(item,ctx.model_spec))
        MPresult = multicoreJob(DTBJobs=DTBJobs, nProcess=ctx.n_process, ShuffleJobs=False).run()
        if MPresult:
            responseList, costList, DTBJobs_Retry = zip(*MPresult)
            CostLog(PGMSubDir = PGMSubDir, costList=costList, mode="AllArt")
    else:
        for item in tqdm(itemList, desc="LLM API呼叫之文章物件數完成度", ascii=False, ncols=75):
            DTBJobs = create_jobs(item,ctx.model_spec)
            MPresult = multicoreJob(DTBJobs=DTBJobs, nProcess=ctx.n_process, ShuffleJobs=False).run()
            if MPresult:
                responseList, costList, item_retry = zip(*MPresult)
                ArtCost = CostLog(ArtCost=ArtCost, item=item, costList=costList, mode="singleArt")
                DTBJobs_Retry.extend(item_retry)
        CostLog(costList=ArtCost.values(), mode="AllArt")
    return flattenList(DTBJobs_Retry)


class PromptAPIPipeline:
    def __init__(self, 
                 task="",
                 #MainFileName="", #切割前原來文檔的主檔名
                 content="",
                 promptFile="",OutputSaveFN="",
                 removeFinPromptFile=False,
                 max_tokens=4096,
                 #On_Premises=False,
                 allow_to_retry=False,
                 model_spec = dict(),
                 include_think = False,
                 PGMSubDir = "",
                 ):
        self.task = task
        #self.MainFileName = MainFileName
        self.include_think = include_think
        self.content = content
        self.promptFile = promptFile
        if self.content == "" and self.promptFile != "":
            with open(self.promptFile,mode='rt',encoding='utf-8') as fp:
                self.content = fp.read()
        self.OutputSaveFN = OutputSaveFN   
        self.removeFinPromptFile = removeFinPromptFile
        self.max_tokens = max_tokens
        #self.On_Premises = On_Premises
        self.allow_to_retry = allow_to_retry
        self.model_spec = model_spec
        self.PGMSubDir = PGMSubDir
        #print("model_spec b4",model_spec)
        if not all(key in self.model_spec for key in ["base_url", "model_name"]):
            self.model_spec = select_model(self.model_spec)
            #print("model_spec af select",model_spec)
        self.model_spec["base_url"] = [self.model_spec["base_url"]] if isinstance(
            self.model_spec.get("base_url"), str) else self.model_spec["base_url"]
        #print("model_spec af ck",model_spec)

        
    def show(self,):
        print("輸入prompt檔案",self.promptFile)
        print("輸出儲存檔案",self.OutputSaveFN)

    def proc(self, ):
        print("="*50)
        print("Calling LLM API for promptFile",self.promptFile)
        DTBJobs_Retry = []
        try:
            # 在這裡選擇負載最輕的 base_url
            base_url = select_idle_ollama_url(self.model_spec["base_url"],PGMSubDir=self.PGMSubDir)
            self.model_spec["base_url"] = base_url  # 更新 model_spec 的 base_url
            #print(f"已分配 base_url: {base_url} 進行處理")  # 顯示選擇的 base_url
            #print("Start to run CallLLMAPI in PromptAPIPipeline")
            response,cost = CallLLMAPI(
                self.content,max_tokens=self.max_tokens,
                #On_Premises=self.On_Premises,
                model_spec=self.model_spec)
            #print("Finished CallLLMAPI in PromptAPIPipeline")
            retMES = response.choices[0].message.content
            #print("retMES in pipeline b4",retMES)
            #清除前面<think>的思考內容
            #retMES = re.sub(r"<think>.*?</think>\s*", "", retMES, flags=re.DOTALL)
            #print("retMES b4",retMES)
            if self.include_think == False:
                retMES = re.sub(r'<think>.*?</think>', '', retMES, flags=re.DOTALL)
            if retMES.replace(" ","").replace("\n","") == "<EMPTY>":
                retMES = ""  # 替換為空字串

            #print("retMES af1",retMES)
            #print("retMES in pipeline af",retMES)
            #print("retMES bf",retMES)
            if "to json" in self.task.lower():
                retMES = retMES.replace('```json', '').replace('```', '').strip()
            #print("retMES af",retMES)
            # 移除成功呼叫結束之Todo Prompt檔案。
            #print("retMES af2",retMES)
            print("-"*50)
            if self.removeFinPromptFile == True and self.promptFile != "":
                os.remove(self.promptFile)
            
            # 如果預設輸出為json，進行輸出成功性驗證，如果不通過，則將輸入分割為兩段後，
            # 生成新的PromptFile，再試一次。
            if self.allow_to_retry == True:
                if "to json" in self.task.lower():
                    DTBJobs_Retry,retMES = self.handle_json_output(retMES)

            #如果有重試任務，則不儲存目前結果到Success
            '''
            if self.OutputSaveFN != "" and DTBJobs_Retry == []:
                MKDIR(os.path.dirname(self.OutputSaveFN))
                print("OutputSaveFN",self.OutputSaveFN)
                with open(self.OutputSaveFN,mode='wt',encoding='utf-8') as fp:
                    fp.write(retMES)
            '''
            if self.OutputSaveFN != "" and DTBJobs_Retry == []:
                MKDIR(os.path.dirname(self.OutputSaveFN))
                tmp_fn = self.OutputSaveFN + ".tmp"
                with open(tmp_fn, mode='wt', encoding='utf-8') as fp:
                    fp.write(retMES)
                    fp.flush()
                    os.fsync(fp.fileno())  # 確保落地
                os.replace(tmp_fn, self.OutputSaveFN)  # ✅ 原子替換
                    

            #將處理過的文字訊息回填response物件
            response.choices[0].message.content = retMES
            # 任務完成後釋放負載
            release_url_load(base_url,PGMSubDir=self.PGMSubDir)
            
        except Exception as ex:
            if not "response" in locals():
                response = None
                cost = 0
            print(f"When run PromptAPIPipeline, the following error occurs:\n {ex}")
            #countdown_pause(30)
        return response,cost,DTBJobs_Retry

    def handle_json_output(self, retMES):
        '''
        嘗試用json.loads驗證回傳訊息json正確性，
        回傳值為空清單或重跑任務物件清單跟修正後訊息。
        '''
        try:
            #print("raise Exception to debug json output")
            #raise Exception
            json.loads(retMES)
            return [],retMES
        except:
            #如果json格式驗證失敗，那麼切割後再產生新的Job重試。
            print("json format verification failed.")
            print("retMES:",retMES)
            
            
            try:
                print(f'Try using LLM {self.model_spec["model_name"]} to repair.')
                #print("disable think status",should_disable_think(self.model_spec["model_name"]))
                MainFileName,input_text,keyConsiderations = self.extract_MainFileName_and_input_text()
                retMES_rep = json_format_caller(
                    task="json format Repair",
                    content=retMES,
                    MainFileName=MainFileName,
                    max_tokens=self.max_tokens,
                    model_spec=self.model_spec,
                    #no_think = should_disable_think(self.model_spec["model_name"])
                    )
                json.loads(retMES_rep)
                print("Successfully repair with LLM.")
                print("repaired retMES_rep",retMES_rep)
                return [],retMES_rep
            except Exception as ex_json:
                print("ex_json",ex_json)
                print("Fail to repair with LLM.")
                print("retMES_rep",retMES_rep)
                MainFileName,input_text,keyConsiderations = self.extract_MainFileName_and_input_text()
                if input_text:
                    DTBJobs_Retry = self.split_and_generate_new_prompts(
                        input_text=input_text,keyConsiderations=keyConsiderations,
                        MainFileName=MainFileName)
                else:
                    DTBJobs_Retry = []
                    print("未於prompt中截獲非空的原始輸入任務文本，不生成再次嘗試的新prompt。")
                return DTBJobs_Retry,""

    def extract_MainFileName_and_input_text(self):
        input_text = None
        # 依序檢查各種 pattern，找到非空結果時就跳出迴圈
        for pattern in [r"(?<=☆輸入文本：).*", r"(?<=☆下列為輸入任務文本：).*"]:
            m = re.search(pattern, self.content, re.DOTALL)
            if m:
                candidate = m.group().strip()  # 去除前後空白
                if candidate:  # 如果有意義的文字
                    input_text = candidate
                    break  # 找到後不再繼續搜尋
        # 取得主檔名
        m2 = re.search(r'主檔名為「([^」]+)」', self.content)
        MainFileName = m2.group(1) if m2 else None
        m3 = re.search(r'風險關注指標為「([^」]+)」', self.content)
        keyConsiderations = m3.group(1) if m3 else None
        return MainFileName, input_text, keyConsiderations
    
    def split_and_generate_new_prompts(self, input_text,MainFileName="",keyConsiderations=""):
        half_length = len(input_text) // 2
        first_half = input_text[:half_length]
        second_half = input_text[half_length:]
        
        base_name = os.path.splitext(self.promptFile)[0]
        new_prompt_file_0 = f"{base_name}-0.txt"
        new_prompt_file_1 = f"{base_name}-1.txt"
        
        print("start to generate new prompt.")
        print("self.task",self.task)
        print("MainFileName",MainFileName)
        prompt_0 = generate_prompt(
            content=first_half, keyConsiderations=keyConsiderations,
            task=self.task, MainFileName=MainFileName)
        prompt_1 = generate_prompt(
            content=second_half, keyConsiderations=keyConsiderations,
            task=self.task, MainFileName=MainFileName)       
        for prompt,promptFile in [(prompt_0,new_prompt_file_0),(prompt_1,new_prompt_file_1)]:
            with open(promptFile, 'wt', encoding='utf-8') as fp:
                fp.write(prompt)
        
        # 移除原始 prompt 檔案
        #os.remove(self.promptFile)
        
        print(f"Generated new prompt files: {new_prompt_file_0}, {new_prompt_file_1}")
        # 創建新的 PromptAPIPipeline 工作物件
        DTBJobs_Retry = []
        for promptFile in [new_prompt_file_0,new_prompt_file_1]:
            DTBJobs_Retry.append(
                PromptAPIPipeline(
                    task=self.task,
                    #MainFileName=self.MainFileName,
                    promptFile=promptFile,
                    OutputSaveFN=promptFile.replace("TODO", "Success"),
                    removeFinPromptFile=True,
                    max_tokens=self.max_tokens,
                    #On_Premises=self.On_Premises,
                    allow_to_retry=False  # 不允許再次重試
                    )
                )
        
        return DTBJobs_Retry
    
    



def json_format_caller(content,
                       #On_Premises=True,
                       task = "json format Repair",
                       keyConsiderations="",
                       MainFileName="",
                       model_spec=dict(),
                       max_tokens=8*1024, #切片結果合併後的json可能會很長，
                       #nothink = True
                       ):
    #content = preprocess(content)  # 可選擇加入你的前處理函式
    #print("Running json_format_caller")
    prompt = generate_prompt(
        content=content,
		keyConsiderations=keyConsiderations,
        task=task,
        MainFileName=MainFileName
    )
    #print("Running PromptAPIPipeline for json_format_caller")
    response, cost, _ = PromptAPIPipeline(
        content=prompt,
        task=task,
        removeFinPromptFile=True,
        max_tokens=max_tokens,
        #model_spec = {'api_key':'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpZCI6IjIyYzIzYWVkLWM4YzktNGZhYS1hNGRkLTg1NGNlZDg0YTE3ZCJ9.zP5xKqCemX2J3GFra03jMYPngipCbCUfFfIUyO96JOQ'},
        #On_Premises=On_Premises,  # 視是否使用本地模型
        model_spec=model_spec
    ).proc()
    
    if response is None:
        return None
    return combine_json_return(response.choices[0].message.content)[0]



class PromptRetryManager:
    def __init__(self, task, promptFile, max_tokens, 
                 #on_premises,
                 model_spec):
        self.task = task
        self.promptFile = promptFile
        self.max_tokens = max_tokens
        #self.on_premises = on_premises
        self.model_spec = model_spec

    def retry_split(self, input_text, MainFileName="", keyConsiderations=""):
        half = len(input_text) // 2
        chunks = [input_text[:half], input_text[half:]]
        jobs = []
        
        for i, chunk in enumerate(chunks):
            new_prompt_file = self.promptFile.replace(".txt", f"-{i}.txt")
            print(f"Generated new prompt files: {new_prompt_file}")
            prompt = generate_prompt(content=chunk, keyConsiderations=keyConsiderations,
                                     task=self.task, MainFileName=MainFileName)
            with open(new_prompt_file, 'w', encoding='utf-8') as fp:
                fp.write(prompt)

            jobs.append(PromptAPIPipeline(
                task=self.task,
                promptFile=new_prompt_file,
                OutputSaveFN=new_prompt_file.replace("TODO", "Success"),
                removeFinPromptFile=True,
                max_tokens=self.max_tokens,
                #On_Premises=self.on_premises,
                allow_to_retry=False,
                model_spec=self.model_spec
            ))

        return jobs