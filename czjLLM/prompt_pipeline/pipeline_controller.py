# pipeline_controller.py
import os
import errno
#from colorama import Fore, Style
from tqdm import tqdm
import re
#import random
import json
import hashlib
import time
import threading
#import queue
from collections import Counter
from datetime import datetime
import multiprocessing
import time as _time
#import sqlite3
#import pyodbc
import shutil
from copy import deepcopy
from dataclasses import dataclass
from collections.abc import Mapping
from pathlib import Path
import faulthandler

#from czjLLM.prompt_pipeline.result_handler import PromptResultHandler
from czjLLM.prompt_pipeline.prompt_generator import generate_prompt, _render_raw_task_prompt
from czjLLM.taskConfig import taskSetting
from czjLLM.prompt_pipeline.llm_caller import CallLLMAPI
from czjLLM.prompt_pipeline.debug_snapshot import build_debug_snapshot
from czjLLM.prompt_pipeline.stage_runtime import (
    ChunkStageRuntime,
    should_persist_output,
)
from czjLLM.prompt_pipeline.stage_orchestrator import (
    execute_stage_round as _execute_stage_round,
    init_chunk_stage_runtime as _init_chunk_stage_runtime,
    plan_chunk_stage_dispatch as _plan_chunk_stage_dispatch,
    resolve_pipeline_stages as _resolve_pipeline_stages,
    run_stage_pipeline as _run_stage_pipeline,
    update_chunk_stage_runtime as _update_chunk_stage_runtime,
)
from czjLLM.utilities.atomic_io import atomic_write_json, robust_json_read
from czjLLM.job_manager.job_config import LLMJobConfig, task_template_preview
#from czjLLM.job_manager.end_point_manager import get_available_end_points
from czjLLM.job_manager.end_point_manager import select_model
#from job_manager.win_gui import try_start_gui  # 為避免循環，可移到檔頭

from czjLLM.utilities.combine_utils import combine_api_finished_item
from czjLLM.utilities.combine_utils import combine_json_return
from czjLLM.utilities.logging_utils import CostLog
from czjLLM.utilities.env_overrides import env_bool, env_int, load_czjllm_env_files_once
from czjLLM.tokenizer_utils import TokenizerWrapper
#from czjLLM.utilities.logging_utils import log_error
from utils.utilities_path import OSWALK
from utils.utilities_path import getPathFromFN
#from utils.utilities_path import DirReplace
from utils.utilities_path import MKDIR
#from utils.utilities_path import safe_move
from utils.utilities import flattenList
from utils.utilities import tlog
from utils.MP_utils import multicoreJob

from czjLLM.infrastructure.ollama_lb import select_idle_ollama_url,release_url_load

#from czjLLM.sql_utils.common import quote_column
#from czjLLM.sql_utils.writer import flatten_row_based_json_array_to_subtable
#from czjLLM.sql_utils.row_utils import upsert_single_value
#from czjLLM.row_processors.flatten_utils import extract_json_list_for_flatten
#from czjLLM.utilities.path_utils import get_combined_result_path
from czjLLM.job_manager.console_ui import  tlog_warn

def _canon_path(p: str) -> str:
    # 轉絕對路徑 + 正規化分隔 + Windows 大小寫無關
    return os.path.normcase(os.path.normpath(os.path.abspath(p)))

def _bump(ctx):
    try:
        ctx.last_progress_ts = time.time()
    except Exception:
        pass
        
# [ADD] －－－－ Global Load Meter / Registry －－－－

class ItemsRegistry:
    """
    執行緒安全：註冊「每列」的 item 目錄（含 TODO/Success）與對應 pk、暫存 txt。
    """
    def __init__(self):
        self.lock = threading.Lock()
        self._items = {}  # item_dir -> {"pk":..., "temp_txt":...}

    #def add(self, item_dir, pk, temp_txt):
    #   with self.lock:
    #        self._items[item_dir] = {"pk": pk, "temp_txt": temp_txt}
    def add(self, item_dir, pk, temp_txt, comb_back_fn):
        with self.lock:
            self._items[item_dir] = {
                "pk": pk,
                "temp_txt": temp_txt,
                "CombBackFN": comb_back_fn
            }
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


# ── 供 watchdog 觀察的最小狀態（不鎖，僅追蹤心跳/派工時間）
#
CONSUMER_STATE = {
    "last_dispatch_ts": 0.0,   # 上次成功取回結果或派工的時間（monotonic）
    "pool_alive": False,       # 是否有活著的 worker（粗略）
}

def run_round(jobs, n_proc: int):
    """
    最小保險絲：根據 n_proc 與 jobs 數量決定單工或多程序。
    - 單工：同步逐一跑（避免進入死池時整批卡住）
    - 多工：交由 multicoreJob，但用 try/except 保護；失敗時回傳空結果讓上層下一輪重試
    """
    use_mp = (n_proc > 1) and (len(jobs) > 1)
    CONSUMER_STATE["pool_alive"] = False

    if not use_mp:
        out = []
        for j in jobs:
            try:
                out.append(j.proc())
                CONSUMER_STATE["last_dispatch_ts"] = _time.monotonic()
            except Exception as ex:
                tlog_warn(f"[single] worker error: {ex}")
        return out

    # 多程序路徑：仍沿用現有 multicoreJob（最小入侵）
    try:
        CONSUMER_STATE["pool_alive"] = True
        res = multicoreJob(DTBJobs=jobs, nProcess=n_proc, ShuffleJobs=False).run()
        CONSUMER_STATE["last_dispatch_ts"] = _time.monotonic()
        return res
    except Exception as e:
        tlog_warn(f"[mp] Pool error: {e}; will retry next round")
        return []
    finally:
        # 粗略偵測仍有無存活的 child（可能因平臺差異不準，但足夠觸發保險絲邏輯）
        try:
            CONSUMER_STATE["pool_alive"] = any(p.is_alive() for p in multiprocessing.active_children())
        except Exception:
            CONSUMER_STATE["pool_alive"] = False
            

def meter_init(meter_fn, ctx, low=None, high=None):
    low  = low  if low  is not None else getattr(ctx, "n_process", 4) * 2
    high = high if high is not None else getattr(ctx, "n_process", 4) * 3
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
    lock = _lock_path(meter_fn)
    fd = _acquire_file_lock(lock)  # 逾時則回傳 None
    try:
        if fd is None:
            # 策略1：短暫睡一下重試；或策略2：直接放棄這次更新
            # 這裡示範重試一次（你也可以 while 重試多次）
            time.sleep(0.05)
            fd = _acquire_file_lock(lock)
            if fd is None:
                # 放棄這次更新，避免破壞其他程序的鎖
                return meter_read(meter_fn)

        d = meter_read(meter_fn)
        if not isinstance(d, dict):
            d = {"rows": {}, "queue": {"pending": 0, "running": 0}}
        mutator(d)
        atomic_write_json(meter_fn, d)
        return d
    finally:
        if fd is not None:             # ✅ 只有真的持鎖才釋放/刪鎖
            _release_file_lock(fd, lock)

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
    if fd is None:
        return
    try:
        os.close(fd)
    finally:
        try:
            os.remove(lock_path)
        except FileNotFoundError:
            pass
        except OSError:
            pass

def safe_unlink(path: str, retries: int = 5, delay: float = 0.1) -> None:
    for i in range(retries):
        try:
            os.unlink(path)
            return
        except FileNotFoundError:
            # 已被其他 worker 刪掉 → 當成功處理
            return
        except PermissionError:
            # Windows 偶發鎖檔 → 稍等再試
            time.sleep(delay)
        except OSError as e:
            # 例如跨掛載點暫態 I/O，僅對「暫態型」再試一次
            if e.errno in (errno.EBUSY, errno.ETXTBSY):
                time.sleep(delay)
            else:
                # 非暫態就直接忽略（不阻塞主流程）
                return
            
def find_item_dir_for(ctx, main_file_name: str) -> str:
    """
    從 ctx.prompt_dir 掃描出對應的 item 目錄（父級，底下有 TODO/Success）。
    """
    candidates = []
    for f in OSWALK(ctx.prompt_dir):
        parts = getPathFromFN(f).split("/")
        if parts[-1] in ["TODO", "Success"]:
            parent = "/".join(parts[:-1])
            parent_name = Path(parent).name
            if parent_name == main_file_name or parent_name.startswith(f"{main_file_name}_"):
                candidates.append(parent)
    uniq = list(set(candidates))
    if not uniq:
        raise RuntimeError(f"找不到 item 目錄：{main_file_name}")
    return uniq[0]

# [ADD] －－－－ Streaming Consumer：批次消化 TODO 檔 －－－－
'''
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
'''
def pick_and_claim_next_prompts(item_dirs, per_round_limit=128):
    """
    從各 item_dir 的 TODO 中挑選檔案，並立即以 os.replace() 更名為 RUNNING/xxx.txt。
    回傳 [(pf_running, item_dir), ...]，其中 pf_running 位於 RUNNING 目錄。
    """
    claimed = []
    for item_dir in item_dirs:
        todo = Path(item_dir) / "TODO"
        run  = Path(item_dir) / "RUNNING"
        if not todo.is_dir():
            continue
        run.mkdir(parents=True, exist_ok=True)

        # 排序讓行為穩定
        for src in sorted(OSWALK(str(todo))):
            src_p = Path(src)
            dst_p = run / src_p.name
            try:
                # 同一檔案系統才是原子；務必確保三個目錄在同一磁碟/掛載點
                os.replace(str(src_p), str(dst_p))
            except FileNotFoundError:
                # 已被其他 worker 抢先
                continue
            except PermissionError:
                # 偶發鎖檔（Windows/防毒）→ 略過
                continue
            except OSError:
                # 其它 I/O 異常 → 略過
                continue

            claimed.append((str(dst_p), str(item_dir)))
            if len(claimed) >= per_round_limit:
                return claimed
    return claimed

def _to_success(pf_running: str) -> str:
    p = Path(pf_running)
    assert p.parent.name == "RUNNING"
    suc = p.parent.parent / "Success"
    suc.mkdir(parents=True, exist_ok=True)
    return str(suc / p.name)

def _to_todo(pf_running: str) -> str:
    p = Path(pf_running)
    # pf 必須是 .../RUNNING/xxx.txt
    if p.parent.name != "RUNNING":
        # 保守：不是 RUNNING 就照原路徑回傳
        return pf_running
    todo_dir = p.parent.parent / "TODO"
    todo_dir.mkdir(parents=True, exist_ok=True)
    return str(todo_dir / p.name)

def _running_to_todo(pf_running: str) -> str:
    p = Path(pf_running)
    if p.parent.name == "RUNNING":
        todo_dir = p.parent.parent / "TODO"
        todo_dir.mkdir(parents=True, exist_ok=True)
        return str(todo_dir / p.name)
    return pf_running

def _ensure_in_todo(pf_any: str) -> str:
    """
    不管輸入在 TODO/RUNNING/Success，回傳「對應 TODO 的路徑」。
    主要給 split 產新檔名用。
    """
    p = Path(pf_any)
    parent = p.parent.name
    if parent in ("RUNNING", "Success", "TODO"):
        todo_dir = p.parent.parent / "TODO"
        todo_dir.mkdir(parents=True, exist_ok=True)
        return str(todo_dir / p.name)
    # 不在隊列結構下，就原樣回傳
    return pf_any
    
def recover_running_to_todo(item_dirs):
    """
    僅在流程「啟動前」呼叫一次：
    將前次異常留下的 RUNNING/* 移回 TODO/*，讓它們能被重新排程。
    """
    for item_dir in item_dirs:
        run  = Path(item_dir) / "RUNNING"
        todo = Path(item_dir) / "TODO"
        if not run.is_dir():
            continue
        todo.mkdir(parents=True, exist_ok=True)
        for p in run.rglob("*"):
            if not p.is_file():
                continue
            rel = p.relative_to(run)
            dst = todo / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.replace(str(p), str(dst))  # 原子搬移
            except FileNotFoundError:
                # 另一個程序可能已處理，略過即可
                pass
            except PermissionError:
                # 偶發網路磁碟忙碌，可視需要加上短暫重試
                pass
                
def llm_stream_consumer(ctx, registry: ItemsRegistry, meter_fn: str,
                        stop_event: threading.Event,
                        restart_event: threading.Event,   # ★ 新增
                        is_sqlite=False, per_round_limit=128):
    """
    連續從所有 item_dir 的 TODO 中抓取 prompt 檔，以小批次呼叫 LLM。
    - 僅使用呼叫端傳入的 `meter_fn`（不可於此處重算路徑）
    - 每回合：pending->running；跑完後依「實際完成」回補 running/completed 與 rows[pk].done
    - 無 TODO 且 stop_event 設定後結束
    """
    # 關閉子層 tqdm，避免覆蓋主進度條
    import os as _os
    _os.environ.setdefault("TQDM_DISABLE", "1")
    _os.environ.setdefault("DISABLE_INNER_TQDM", "1")

    try:
        try:
            stage_defs = resolve_pipeline_stages(ctx)
        except Exception:
            stage_defs = []
        multistage_mode = len(stage_defs) > 1
        if multistage_mode:
            try:
                tlog("[consumer] multistage mode enabled (SQL/Table stream will run process_prompt_and_merge per row)")
            except Exception:
                pass

        tlog(f"[consumer] using meter: {meter_fn}")  # 診斷：應與 orchestrator 印出的路徑一致
        print("meter_fn in llm_stream_consumer",meter_fn)
        #did_recover = False  # ← 新增：只復原一次
        while True:
            # 🔸 A. 若收到了「重啟」信號 → 做一次 RUNNING→TODO 的復原，然後清掉事件
            if restart_event is not None and restart_event.is_set():
                try:
                    items_map = registry.list_items()
                    item_dirs = list(items_map.keys())
                    recover_running_to_todo(item_dirs)   # 你的舊工具函式，或實作將 RUNNING 檔移回 TODO
                    meter_update(meter_fn, lambda d: d.setdefault("consumer", {}).update({"last_dispatch_ts": time.time()}))
                    tlog_warn("[consumer] restart_event 收到 → 已復原 RUNNING→TODO，繼續派工")
                except Exception as ex:
                    tlog_warn(f"[consumer] restart 恢復失敗：{ex}")
                finally:
                    restart_event.clear()
                    
            round_start = time.time()
            dispatched_n = 0
            finished_n   = 0
            
            '''
            # ★ 熱重啟：僅重置 consumer 狀態，不動 stop_event
            if restart_event.is_set():
                tlog_warn("[consumer] 收到重啟訊號 → 重置狀態（必要時還原 RUNNING → TODO）")
                restart_event.clear()
                try:
                    # 若你有這個函式，這裡做一次還原；沒有就略過
                    if not did_recover:
                        item_dirs_for_recover = list(registry.list_items().keys())
                        try:
                            recover_running_to_todo(item_dirs_for_recover)
                        except Exception:
                            pass
                        did_recover = True
                except Exception as _:
                    pass
                time.sleep(0.5)  # 小讓步，避免緊黏檔案系統
                continue
            '''

            items_map = registry.list_items()
            item_dirs = list(items_map.keys())

            # ★ 啟動後第一次迴圈：復原 RUNNING → TODO
            #if not did_recover:
            #    recover_running_to_todo(item_dirs)
            #    did_recover = True
            # 🔸 B. 這裡用「可鎖定切片」的 pick（你已經在用）
            #batch = pick_next_prompts(item_dirs, per_round_limit=per_round_limit)
            batch = pick_and_claim_next_prompts(item_dirs, per_round_limit=per_round_limit)

            if not batch:
                # 若無可派發任務：producer 已宣告結束且再檢一次仍空 → 收尾
                if stop_event.is_set():
                    #if not pick_next_prompts(item_dirs, per_round_limit=1):
                    if not pick_and_claim_next_prompts(item_dirs, per_round_limit=1):
                        break
                time.sleep(0.1)
                continue

            prompt_files = [pf for pf, _ in batch]
            # 這是「欲派發」的每列切片數；真正完成數稍後以實際檔案狀態重算
            count_by_item_sched = Counter(item for _, item in batch)

            # ---- 1) 更新 meter：pending -= n_sched, running += n_sched
            n_sched = len(prompt_files)
            try:
                meter_update(meter_fn, lambda d: _meter_on_dispatch(d, items_map, count_by_item_sched, n_sched))
                _bump(ctx)  # ✅ 有派工作就算進展
            except Exception as ex:
                tlog_warn(f"⚠️ meter_on_dispatch 失敗：{ex}")

            # ★★ 派工心跳：讓 watchdog 能知道「最近有派工」
            try:
                CONSUMER_STATE["last_dispatch_ts"] = time.monotonic()
            except Exception:
                pass
                
            # ---- 2) 建立 Jobs 並執行（multicore）
            DTBJobs = []
            #print("in pipeline_controller, ctx.model_spec",ctx.model_spec)
            for pf, item_dir in batch:
                out_fn = _to_success(pf)  # RUNNING → Success（用兄弟目錄推導，別用字串 replace）
                job_spec = deepcopy(ctx.model_spec)  # ★ 每個 job 拿各自副本
                if bool(getattr(ctx, "mock_llm_mode", False)):
                    job_spec["mock_llm_mode"] = True
                DTBJobs.append(PromptAPIPipeline(
                    task=ctx.task,
                    promptFile=pf,
                    #OutputSaveFN=pf.replace("TODO", "Success"),
                    OutputSaveFN=out_fn,
                    removeFinPromptFile=getattr(ctx, "removeFinPromptFile", True),
                    max_tokens=ctx.max_tokens,
                    allow_to_retry=True,
                    #model_spec=ctx.model_spec,
                    model_spec=job_spec,           # ★ 用副本，不要用 ctx.model_spec 本體
                    PGMSubDir=ctx.PGMSubDir,
                ))

            dispatched_n = len(DTBJobs)
            if dispatched_n == 0:
                time.sleep(0.2)
                continue

            try:
                MPresult = run_round(DTBJobs, ctx.n_process)
            except Exception as ex:
                # 不讓整輪報廢；下一輪再吃
                tlog_warn(f"❌ run_round 例外：{ex}")
                #MPresult = []
                
            # ---- 2.5) 以「實際完成」回報（檔案是否仍存在於 TODO）
            # 規則：成功 → 會移除 TODO/建立 Success；失敗 → TODO 留存（或重建），下輪再吃
            '''
            done_prompt_files = [pf for pf, _ in batch if not os.path.exists(pf)]
            n_done = len(done_prompt_files)
            count_by_item_done = Counter(item for pf, item in batch if not os.path.exists(pf))
            '''
            '''#0112
            def _success_path(pf: str) -> str:
                return pf.replace("TODO", "Success")
                
            
            done_prompt_files = []
            for pf, _ in batch:
                ok = False
                if os.path.exists(_success_path(pf)):   # 成功寫回
                    ok = True
                elif not os.path.exists(pf):            # 原 TODO 已被替換/刪除（例如切分重試）
                    ok = True
                if ok:
                    done_prompt_files.append(pf)
            
            n_done = len(done_prompt_files)
            count_by_item_done = Counter(item for pf, item in batch if pf in done_prompt_files)
            finished_n += n_done
            '''#0112
            done = []
            requeued = []
            still_running = []
            
            for pf, item in batch:
                # pf 是 RUNNING/xxx.txt
                suc = _to_success(pf)   # RUNNING -> Success/xxx.txt
                todo = _to_todo(pf)     # RUNNING -> TODO/xxx.txt
            
                if os.path.exists(suc):
                    # ✅ 成功：Success 存在
                    done.append((pf, item))
                elif os.path.exists(pf):
                    # ✅ 仍在 RUNNING：表示這輪可能還沒寫完/或 job 卡住
                    still_running.append((pf, item))
                elif os.path.exists(todo):
                    # ✅ 退回 TODO（例如 retry/split 或 exception 退回）：要把 pending 加回來
                    requeued.append((pf, item))
                else:
                    # 檔案消失：避免 running 永遠扣不回，保守視為 done
                    done.append((pf, item))
            
            n_done = len(done)
            n_requeued = len(requeued)
            
            count_by_item_done = Counter(item for _, item in done)
            count_by_item_requeued = Counter(item for _, item in requeued)
            
            finished_n += n_done

            # ---- 3) 更新 meter：running -= n_done, completed += n_done, rows[pk].done += 每列完成量
            try:
                '''#0112
                meter_after = meter_update(
                    meter_fn,
                    lambda d: _meter_on_finish_batch(d, items_map, count_by_item_done, n_done)
                )
                '''#0112
                meter_after = meter_update(
                    meter_fn,
                    lambda d: _meter_on_finish_batch_v2(
                        d,
                        items_map,
                        count_by_item_done=count_by_item_done,
                        n_done=n_done,
                        count_by_item_requeued=count_by_item_requeued,
                        n_requeued=n_requeued,
                    )
                )

                _bump(ctx)  # ✅ 有完成也戳
            except Exception as ex:
                tlog_warn(f"⚠️ meter_on_finish_batch 失敗：{ex}")
                #meter_after = None

            # ---- 4) 心跳：告訴外界 consumer 還活著
            try:
                meter_update(meter_fn, lambda d: d.setdefault("consumer", {}).update({
                    "alive": True, "last_round_ts": time.time()
                }))
                _bump(ctx)  # ✅ consumer 每輪都算活著
            except Exception:
                pass

            took = time.time() - round_start
            try:
                m = meter_read(meter_fn)
                q = m.get("queue", {})
                tlog(
                    f"🧵 consumer round: +dispatched={dispatched_n}, finished={finished_n}, "
                    f"pending={q.get('pending',0)}, running={q.get('running',0)}, took={took:.2f}s"
                )
            except Exception:
                pass

            # 小讓步，避免緊貼檔案系統
            time.sleep(0.01)

    except Exception as ex:
        # **最外層保護**：任何沒抓到的例外都要吼一聲，並標記 consumer 死亡
        try:
            tlog_warn(f"❌ consumer 未捕捉例外：{ex}")
        except Exception:
            pass
    finally:
        try:
            meter_update(meter_fn, lambda d: d.setdefault("consumer", {}).update({"alive": False}))
        except Exception:
            pass


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

def _meter_on_finish_batch_v2(d, items_map,
                             count_by_item_done, n_done,
                             count_by_item_requeued, n_requeued):
    q = d.setdefault("queue", {})
    q["running"] = max(0, int(q.get("running", 0)) - (n_done + n_requeued))
    q["completed"] = int(q.get("completed", 0)) + n_done
    q["pending"] = int(q.get("pending", 0)) + n_requeued

    rows = d.setdefault("rows", {})

    # ✅ completed per item（只算 done）
    for item_dir, cnt in count_by_item_done.items():
        #row = rows.setdefault(item_dir, {})
        pk = items_map.get(item_dir, {}).get("pk", item_dir)  # 保底
        row = rows.setdefault(pk, {})
        row["done"] = int(row.get("done", 0)) + int(cnt)

    # ✅ requeued per item（可選：記錄一下）
    if n_requeued:
        cons = d.setdefault("consumer", {})
        cons["last_requeued"] = int(n_requeued)
        cons["last_requeued_ts"] = time.time()

    return d


def _es_heartbeat_loop(adapter, interval_sec=60):
    while True:
        try:
            ok = bool(getattr(adapter, "es", None)) and adapter.es.ping(request_timeout=3)
            if not ok:
                print("[watchdog] ES ping 失敗", flush=True)
        except Exception as e:
            print(f"[watchdog] ES ping 例外: {e}", flush=True)
        time.sleep(interval_sec)

def _stall_watchdog(ctx, adapter, idle_threshold_sec=600, interval_sec=60,
                    stacks_path="stacks.log", meter_fn=None, restart_cb=None):
    stacks_file = open(stacks_path, "a", buffering=1, encoding="utf-8")
    try:
        faulthandler.enable()
    except Exception:
        pass

    MAX_STACKS_BYTES = 20 * 1024 * 1024  # 20MB

    while True:
        try:
            now = time.time()

            # --- 1) 讀 meter consumer 心跳 ---
            m = {}
            q = {}
            consumer = {}
            try:
                m = meter_read(meter_fn) if meter_fn else {}
                q = m.get("queue", {}) if isinstance(m, dict) else {}
                consumer = m.get("consumer", {}) if isinstance(m, dict) else {}
            except Exception:
                m, q, consumer = {}, {}, {}

            pending = int(q.get("pending", 0) or 0)
            running = int(q.get("running", 0) or 0)

            # --- 2) 組合多個「最近活動時間」 ---
            last_doc = getattr(ctx, "last_progress_ts", None)  # 文件級
            last_round = consumer.get("last_round_ts", None)   # 切片批次級
            last_dispatch_mono = CONSUMER_STATE.get("last_dispatch_ts", 0.0)

            # monotonic -> wall time 保守換算：用 now - (monotonic差) 當近似
            # 目的只是比較「多久以前」是否活著，不求精準時戳
            if last_dispatch_mono:
                last_dispatch = now - max(0.0, (time.monotonic() - last_dispatch_mono))
            else:
                last_dispatch = None

            # 取最大（最新）的活動時間
            candidates = [t for t in [last_doc, last_round, last_dispatch] if isinstance(t, (int, float)) and t > 0]
            last_any = max(candidates) if candidates else None

            # --- 3) 決策：只要 running>0 或最近有 round/dispatch，就不要誤判停滯 ---
            if last_any is not None:
                idle = now - last_any
            else:
                idle = 0

            # ✅ 關鍵：如果還有 running，而且 consumer 最近仍有 round/dispatch，視為正常
            alive_hint = False
            if running > 0:
                # 只要 2 分鐘內有 round 或 dispatch 就當活著（你可調）
                if (last_round and now - float(last_round) < 120) or (last_dispatch and now - float(last_dispatch) < 120):
                    alive_hint = True

            if (idle > idle_threshold_sec) and (not alive_hint):
                print("[watchdog] 10 分鐘無進度訊號（doc/round/dispatch），疑似停滯，請檢查 stacks.log 與 ES", flush=True)

                # stacks.log size rotate
                try:
                    if os.path.exists(stacks_path) and os.path.getsize(stacks_path) > MAX_STACKS_BYTES:
                        try:
                            stacks_file.close()
                        except Exception:
                            pass
                        stacks_file = open(stacks_path, "w", buffering=1, encoding="utf-8")
                        print(f"[watchdog] stacks.log 超過上限，已截斷重建（上限 {MAX_STACKS_BYTES} bytes）", flush=True)
                except Exception as e:
                    print(f"[watchdog] 檔案大小檢查失敗：{e}", flush=True)

                try:
                    faulthandler.dump_traceback(file=stacks_file)
                except Exception as e:
                    print(f"[watchdog] dump 例外: {e}", flush=True)

                # ES ping
                try:
                    ok = bool(getattr(adapter, "es", None)) and adapter.es.ping(request_timeout=3)
                    if not ok:
                        print("[watchdog] ES ping 失敗（stall）", flush=True)
                except Exception as e:
                    print(f"[watchdog] ES ping 例外（stall）: {e}", flush=True)

            # --- 4) 你原本的 restart 條件保留，但建議再加一個：running>0 就不要重啟 ---
            try:
                long_no_dispatch = (time.monotonic() - CONSUMER_STATE.get("last_dispatch_ts", 0.0) > 120.0)
                if pending > 0 and running == 0 and long_no_dispatch:
                    print("🧯 [watchdog] stall detected: pending>0, running=0, long_no_dispatch>120s", flush=True)
                    if callable(restart_cb):
                        try:
                            restart_cb()
                            print("🔄 [watchdog] restart_cb invoked", flush=True)
                        except Exception as re:
                            print(f"⚠️ [watchdog] restart_cb error: {re}", flush=True)
            except Exception:
                pass

        except Exception as e:
            print(f"[watchdog] 自身例外: {e}", flush=True)

        time.sleep(interval_sec)

def _stall_watchdog_0119(ctx, adapter, idle_threshold_sec=600, interval_sec=60, stacks_path="stacks.log",meter_fn=None, restart_cb=None):
    # 行緩衝，避免 Windows 下鎖太久
    stacks_file = open(stacks_path, "a", buffering=1, encoding="utf-8")
    try:
        faulthandler.enable()
    except Exception:
        pass


    # ← 你可在這裡調整上限大小
    MAX_STACKS_BYTES = 20 * 1024 * 1024  # 20MB
    
    while True:
        try:
            last = getattr(ctx, "last_progress_ts", None)
            if last is not None:
                idle = time.time() - last
                if idle > idle_threshold_sec:
                    print("[watchdog] 進度 10 分鐘無前進，疑似停滯，請檢查 stacks.log 與 ES", flush=True)
                                      
                    # === NEW: 檔案大小檢查；超過上限就用 w 重新開檔（截斷重建） ===
                    try:
                        if os.path.exists(stacks_path) and os.path.getsize(stacks_path) > MAX_STACKS_BYTES:
                            try:
                                stacks_file.close()
                            except Exception:
                                pass
                            stacks_file = open(stacks_path, "w", buffering=1, encoding="utf-8")
                            print(f"[watchdog] stacks.log 超過上限，已截斷重建（上限 {MAX_STACKS_BYTES} bytes）", flush=True)
                    except Exception as e:
                        print(f"[watchdog] 檔案大小檢查失敗：{e}", flush=True)
                        
                    try:
                        faulthandler.dump_traceback(file=stacks_file)
                    except Exception as e:
                        print(f"[watchdog] dump 例外: {e}", flush=True)
                    # 補一個 ES 心跳
                    try:
                        ok = bool(getattr(adapter, "es", None)) and adapter.es.ping(request_timeout=3)
                        if not ok:
                            print("[watchdog] ES ping 失敗（stall）", flush=True)
                    except Exception as e:
                        print(f"[watchdog] ES ping 例外（stall）: {e}", flush=True)
            # ── 追加：若 queue 仍有 pending 但沒有 running，且長時間沒有派工 → 嘗試重啟
            try:
                from czjLLM.prompt_pipeline.pipeline_controller import meter_read, CONSUMER_STATE
                m = meter_read(meter_fn) if meter_fn else {}
                q = m.get("queue", {})
                pending = int(q.get("pending", 0) or 0)
                running = int(q.get("running", 0) or 0)
                long_no_dispatch = (time.monotonic() - CONSUMER_STATE.get("last_dispatch_ts", 0.0) > 120.0)
                if pending > 0 and running == 0 and long_no_dispatch:
                    print("🧯 [watchdog] stall detected: pending>0, running=0, long_no_dispatch>120s", flush=True)
                    if callable(restart_cb):
                        try:
                            restart_cb()  # 封裝 terminate/join + 重建 consumer thread/pool + 續派工
                            print("🔄 [watchdog] restart_cb invoked", flush=True)
                        except Exception as re:
                            print(f"⚠️ [watchdog] restart_cb error: {re}", flush=True)
            except Exception:
                pass
        except Exception as e:
            print(f"[watchdog] 自身例外: {e}", flush=True)
        time.sleep(interval_sec)

def start_watchdogs(ctx, adapter=None, *, 
                    ping_interval_sec=60, 
                    stall_idle_threshold_sec=600, 
                    stall_interval_sec=60, 
                    stacks_path=None,
                    meter_fn=None,
                    restart_cb=None):
    """
    從 controller 啟動所有 watchdog。
    - ctx: 需要 last_progress_ts（orchestrator 每前進一次要更新）
    - adapter: ES 時傳入 ElasticsearchAdapter；其他 backend 可傳 None
    """
    # 避免重複啟動
    if getattr(ctx, "_watchdogs_started", False):
        return
    setattr(ctx, "_watchdogs_started", True)

    if getattr(ctx, "last_progress_ts", None) is None:
        ctx.last_progress_ts = time.time()

    if stacks_path is None:
        stacks_path = os.path.join(getattr(ctx, "work_dir", "."), "stacks.log")

    # 進度停滯偵測（所有 backend 都適用）
    threading.Thread(
        target=_stall_watchdog,
        args=(ctx, adapter),
        kwargs=dict(idle_threshold_sec=stall_idle_threshold_sec,
                    interval_sec=stall_interval_sec,
                    stacks_path=stacks_path,
                    meter_fn=meter_fn,
                    restart_cb=restart_cb),
        daemon=True
    ).start()

    # ES 心跳（只有 ES 時才開）
    if adapter is not None and getattr(adapter, "es", None) is not None:
        threading.Thread(
            target=_es_heartbeat_loop,
            args=(adapter,),
            kwargs=dict(interval_sec=ping_interval_sec),
            daemon=True
        ).start()



# [ADD] －－－－ Row Merger Watchdog：只要 TODO 清空就立刻合併寫回 －－－－
def row_is_ready(item_dir: str) -> bool:
    todo_dir = os.path.join(item_dir, "TODO")
    # TODO 目錄不存在或為空，都視為可合併
    return (not os.path.isdir(todo_dir)) or (len(OSWALK(todo_dir)) == 0)

@dataclass
class MergeOps:
    list_paths: callable = None        # (root: str) -> list[str]
    get_parent: callable = None        # (fn: str) -> str
    call_llm: callable = None          # (items: list[str], ctx, allow_to_retry: bool) -> None
    combine: callable = None           # (item_dir: str, ctx) -> str
    join: callable = os.path.join

    def __post_init__(self):
        self.list_paths = self.list_paths or OSWALK
        self.get_parent = self.get_parent or getPathFromFN
        self.call_llm  = self.call_llm  or call_llm_api
        self.combine   = self.combine   or combine_api_finished_item


def resolve_pipeline_stages(ctx):
    """
    將舊版 ctx.task 與新版 ctx.stages / ctx.task_config.stages 統一成 stages。
    """
    return _resolve_pipeline_stages(ctx)


def init_chunk_stage_runtime(ctx, chunk_ids: list[str]) -> dict[str, ChunkStageRuntime]:
    """
    初始化「切片 x 階段」狀態，用於後續階段監控/派工。
    """
    return _init_chunk_stage_runtime(ctx, chunk_ids)


def plan_chunk_stage_dispatch(ctx, runtime: dict[str, ChunkStageRuntime]):
    """根據 ctx 階段定義與 runtime 產生下一批可派工工作。"""
    return _plan_chunk_stage_dispatch(ctx, runtime)


def update_chunk_stage_runtime(runtime: dict[str, ChunkStageRuntime], results: list[dict]):
    """把 worker 執行結果回填到階段 runtime。"""
    _update_chunk_stage_runtime(runtime, results)


def execute_stage_round(ctx, runtime: dict[str, ChunkStageRuntime], runner):
    """
    執行一輪「階段派工 -> 執行 -> 回填」。
    runner 介面:
      runner(job, ctx) -> {"ok": bool, "error": "..."} 或 bool
    回傳輪次摘要，供監控/UI 顯示。
    """
    return _execute_stage_round(ctx, runtime, runner).as_dict()


def run_stage_pipeline(ctx, runtime: dict[str, ChunkStageRuntime], runner, max_rounds: int = 20):
    """
    連續執行多輪 stage round，直到：
    - 全部 chunk 完成
    - 本輪沒有可派工工作
    - 達到 max_rounds
    回傳包含各輪摘要的執行報告。
    """
    return _run_stage_pipeline(ctx, runtime, runner, max_rounds=max_rounds)


def _collect_prompt_items(prompt_dir: str, main_name: str, ops: MergeOps) -> list[str]:
    """
    從 prompt_dir 掃描出屬於 main_name 的 item 目錄（TODO/Success 的父層）。
    """
    prompt_items: list[str] = []
    for fn in ops.list_paths(prompt_dir):
        p = Path(fn)
        parts = list(p.parts)
        if "TODO" in parts:
            idx = parts.index("TODO")
            if idx > 0:
                item_dir = str(Path(*parts[:idx]))
                item_name = Path(item_dir).name
                if item_name == main_name or item_name.startswith(f"{main_name}_"):
                    prompt_items.append(item_dir)
        elif "Success" in parts:
            idx = parts.index("Success")
            if idx > 0:
                item_dir = str(Path(*parts[:idx]))
                item_name = Path(item_dir).name
                if item_name == main_name or item_name.startswith(f"{main_name}_"):
                    prompt_items.append(item_dir)
    return sorted(set(prompt_items))


def _call_llm_with_task_override(
    ops: MergeOps,
    items: list[str],
    ctx,
    allow_to_retry: bool,
    task_override,
    debug_print_llm_io: bool = False,
    debug_print_max_chars: int = 2000,
):
    """
    相容舊介面：
    - 新版 call_llm 可吃 task_override 參數
    - 舊版沒有此參數時，暫時覆寫 ctx.task 後呼叫
    """
    effective_task = task_override
    if isinstance(task_override, Mapping):
        # worker job 需要可 pickle 的純文字 task；mapping(dict 含 lambda) 會在 MP 序列化時失敗
        task_setting = getattr(ctx, "taskSetting", None)
        if isinstance(task_setting, Mapping):
            for k, v in task_setting.items():
                if v is task_override:
                    effective_task = str(k)
                    break
            else:
                ct_name = str(task_override.get("CT_name", "")).strip()
                for k, v in task_setting.items():
                    if isinstance(v, Mapping) and str(v.get("CT_name", "")).strip() == ct_name and ct_name:
                        effective_task = str(k)
                        break
                else:
                    effective_task = ct_name or str(task_override)
        else:
            effective_task = str(task_override.get("CT_name", "")).strip() or str(task_override)

    try:
        return ops.call_llm(
            items,
            ctx,
            allow_to_retry=allow_to_retry,
            task_override=effective_task,
            debug_print_llm_io=debug_print_llm_io,
            debug_print_max_chars=debug_print_max_chars,
        )
    except TypeError:
        # 兼容舊版 call_llm：先嘗試移除 debug 參數，但保留 task_override。
        try:
            return ops.call_llm(
                items,
                ctx,
                allow_to_retry=allow_to_retry,
                task_override=effective_task,
            )
        except TypeError:
            old_task = getattr(ctx, "task", "")
            try:
                ctx.task = effective_task
                return ops.call_llm(items, ctx, allow_to_retry=allow_to_retry)
            finally:
                ctx.task = old_task


def _build_stage_prompt_text(stage_task, content: str, ctx) -> str:
    """
    將 stage task 套用到文字內容，產生真正要放入 TODO 的 prompt 文字。
    """
    if isinstance(stage_task, Mapping):
        tpl = stage_task.get("template")
        if callable(tpl):
            try:
                return tpl(content=content)
            except TypeError:
                kwargs = {"content": content}
                if "MainFileName" in str(tpl):
                    kwargs["MainFileName"] = getattr(ctx, "main_file_name", "")
                if "keyConsiderations" in str(tpl):
                    kwargs["keyConsiderations"] = getattr(ctx, "keyConsiderations", "")
                return tpl(**kwargs)
        mapped_task = stage_task.get("task", stage_task.get("prompt", ""))
        if isinstance(mapped_task, str) and mapped_task.strip():
            task_name = mapped_task.strip()
            if task_name in taskSetting:
                return generate_prompt(
                    content=content,
                    keyConsiderations=getattr(ctx, "keyConsiderations", ""),
                    MainFileName=getattr(ctx, "main_file_name", ""),
                    task=task_name,
                    think_mode=getattr(ctx, "think_mode", True),
                )
            return _render_raw_task_prompt(task_name, content)
        return content

    task_name = str(stage_task or "").strip()
    if task_name and task_name in taskSetting:
        return generate_prompt(
            content=content,
            keyConsiderations=getattr(ctx, "keyConsiderations", ""),
            MainFileName=getattr(ctx, "main_file_name", ""),
            task=task_name,
            think_mode=getattr(ctx, "think_mode", True),
        )
    # 支援 multi-stage 直接填入 prompt 字串（非 taskSetting key）
    return _render_raw_task_prompt(task_name, content)


def _read_stage_snapshot_output(item: str, stage_name: str) -> str:
    """
    讀取某 stage snapshot 內容，回傳依檔名排序後的合併文字。
    給 stage runtime 存為 outputs_by_stage，以供後續 route_by 判斷。
    """
    snap_dir = _snapshot_dir(item, stage_name)
    if not os.path.isdir(snap_dir):
        return ""
    parts: list[str] = []
    for fp in _root_txt_files(snap_dir):
        try:
            parts.append(fp.read_text(encoding="utf-8"))
        except Exception:
            continue
    return "\n".join(parts).strip()


def _count_txt_files(dir_path: str, ops: MergeOps) -> int:
    if not os.path.isdir(dir_path):
        return 0
    return len([
        fp for fp in ops.list_paths(dir_path)
        if str(fp).lower().endswith(".txt") and os.path.isfile(fp)
    ])


def _clear_txt_files(dir_path: str, ops: MergeOps):
    if not os.path.isdir(dir_path):
        return
    for fp in ops.list_paths(dir_path):
        if str(fp).lower().endswith(".txt") and os.path.isfile(fp):
            os.remove(fp)


def _sanitize_stage_name(stage_name: str) -> str:
    return re.sub(r"[^0-9A-Za-z._-]+", "_", str(stage_name)).strip("_") or "stage"


def _sanitize_file_component(text: str) -> str:
    """將檔名片段標準化為可攜格式。"""
    return re.sub(r"[^0-9A-Za-z._-]+", "-", str(text or "")).strip("-._") or "na"


def _compact_stage_key_for_output(task_key: str, stage_name: str = "") -> str:
    """
    將 stage 的 task_key 精簡成較短、仍具可讀性的輸出片段，避免最終檔名過長。
    規則：
    1) 優先使用 task_key，若空則回退 stage_name
    2) 若含有 '-'（常用於「主標籤-補充說明」），僅取 '-' 前段
    3) 將連續空白收斂為單一空白
    4) 避免單段過長，最多保留 32 字元
    """
    raw = str(task_key or "").strip() or str(stage_name or "").strip()
    if not raw:
        return "stage"
    head = raw.split("-", 1)[0].strip()
    compact = re.sub(r"\s+", " ", head).strip()
    if not compact:
        compact = re.sub(r"\s+", " ", raw).strip()
    return compact[:32].strip() or "stage"


def _stage_todo_dir(item: str, stage_name: str) -> str:
    return os.path.join(item, "TODO", _sanitize_stage_name(stage_name))


def _snapshot_dir(item: str, name: str) -> str:
    return os.path.join(item, "_stage_outputs", name)


def _sync_stage_todo_to_root(item: str, stage_name: str, ops: MergeOps):
    root_todo = os.path.join(item, "TODO")
    stage_dir = _stage_todo_dir(item, stage_name)
    if os.path.isdir(root_todo):
        for fp in Path(root_todo).glob("*.txt"):
            if fp.is_file():
                fp.unlink()
    if not os.path.isdir(stage_dir):
        return
    for src_fp in sorted(ops.list_paths(stage_dir)):
        if not src_fp.lower().endswith(".txt") or not os.path.isfile(src_fp):
            continue
        dst_fp = os.path.join(root_todo, os.path.basename(src_fp))
        shutil.copy2(src_fp, dst_fp)


def _success_txt_signature_map(item: str) -> dict[str, tuple[int, int]]:
    """回傳 root Success 內 txt 的輕量簽章：{檔名: (mtime_ns, size)}。"""
    succ_dir = os.path.join(item, "Success")
    out: dict[str, tuple[int, int]] = {}
    if not os.path.isdir(succ_dir):
        return out
    for fp in Path(succ_dir).glob("*.txt"):
        if not fp.is_file():
            continue
        try:
            st = fp.stat()
            out[fp.name] = (int(st.st_mtime_ns), int(st.st_size))
        except Exception:
            continue
    return out


def _copy_stage_success_delta(item: str, stage_name: str, before_sig: dict[str, tuple[int, int]]):
    """
    僅將「本 stage 執行後新增/更新」的 Success txt 複製到 stage snapshot，
    避免把前一 stage 的舊輸出混入當前 stage。
    """
    snap_dir = _snapshot_dir(item, stage_name)
    MKDIR(snap_dir)
    _clear_txt_files(snap_dir, MergeOps())

    succ_dir = os.path.join(item, "Success")
    if not os.path.isdir(succ_dir):
        return

    for fp in sorted(Path(succ_dir).glob("*.txt")):
        if not fp.is_file():
            continue
        try:
            st = fp.stat()
            now_sig = (int(st.st_mtime_ns), int(st.st_size))
        except Exception:
            continue
        prev_sig = before_sig.get(fp.name)
        if prev_sig == now_sig:
            continue
        shutil.copy2(str(fp), os.path.join(snap_dir, fp.name))


def _root_txt_files(dir_path: str) -> list[Path]:
    p = Path(dir_path)
    if not p.is_dir():
        return []
    return [x for x in sorted(p.glob("*.txt")) if x.is_file()]


def _preview_text_for_debug(text: str, max_chars: int) -> str:
    value = str(text or "")
    if max_chars <= 0:
        return value
    if len(value) <= max_chars:
        return value
    return f"{value[:max_chars]}\n...<truncated {len(value) - max_chars} chars>"


def _resolve_llm_debug_flags(stage_debug_enabled: bool, stage_debug_max_chars: int) -> tuple[bool, int]:
    load_czjllm_env_files_once()
    env_debug = env_bool("CZJLLM_DEBUG_PRINT_LLM_IO")
    env_max = env_int("CZJLLM_DEBUG_PRINT_MAX_CHARS")
    enabled = stage_debug_enabled if env_debug is None else env_debug
    max_chars = stage_debug_max_chars if env_max is None else env_max
    return bool(enabled), int(max_chars)


def _print_stage_llm_io_debug(item: str, stage_name: str, max_chars: int, mode: str):
    """
    mode:
      - prompt: 印出該 stage 送往 LLM 的 TODO 內容
      - output: 印出該 stage LLM 寫回 Success 的內容
    """
    target_dir = os.path.join(item, "TODO" if mode == "prompt" else "Success")
    stage_dir = _stage_todo_dir(item, stage_name) if mode == "prompt" else ""
    title = "送往LLM(Prompt)" if mode == "prompt" else "LLM輸出(Output)"
    files = _root_txt_files(target_dir)
    # prompt debug 優先讀 root TODO；若在 race/清理時機下為空，回退讀 stage 專屬 TODO
    if (not files) and stage_dir:
        files = _root_txt_files(stage_dir)
    if not files:
        extra = f", stage_dir={stage_dir}" if stage_dir else ""
        print(f"[stage:{stage_name}] 🪵 debug {title}: 無 .txt 可顯示（dir={target_dir}{extra}）")
        return
    for fp in files:
        try:
            with open(fp, "r", encoding="utf-8") as f:
                body = f.read()
        except Exception as ex:
            print(f"[stage:{stage_name}] 🪵 debug {title}: 讀取失敗 {fp.name}: {ex}")
            continue
        print(f"[stage:{stage_name}] 🪵 debug {title} file={fp.name}\n{_preview_text_for_debug(body, max_chars)}")


def _append_resume_log(ctx, message: str):
    prompt_dir = getattr(ctx, "prompt_dir", "") if ctx is not None else ""
    if not prompt_dir:
        return
    log_dir = os.path.join(prompt_dir, "_resume_logs")
    os.makedirs(log_dir, exist_ok=True)
    log_fn = os.path.join(log_dir, "resume_events.log")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(log_fn, "a", encoding="utf-8") as f:
        f.write(f"[{now}] {message}\n")


def _print_resume_plan(policy: str, prompt_items: list[str], ops: MergeOps, ctx=None):
    print("=" * 50)
    print(f"♻️ 恢復策略：{policy}")
    print("  - resume: 保留 Success，回收 RUNNING，並盡量跳過已完成切片（hash/mtime 比對）")
    print("  - smart_reset: resume 行為 + 清除 stage 快照/暫存（不清 Success）")
    print("  - full_restart: smart_reset 行為 + 清除 Success（全量重跑）")
    _append_resume_log(ctx, f"resume_policy={policy}, items={len(prompt_items)}")
    for item in prompt_items:
        todo_n = len(_root_txt_files(ops.join(item, "TODO")))
        succ_n = len(_root_txt_files(ops.join(item, "Success")))
        running_n = len(_root_txt_files(ops.join(item, "RUNNING")))
        print(f"  - {Path(item).name}: TODO={todo_n}, Success={succ_n}, RUNNING={running_n}")
        _append_resume_log(
            ctx,
            f"item={Path(item).name} TODO={todo_n} Success={succ_n} RUNNING={running_n}",
        )
    print("=" * 50)


def _drop_resumed_todo_by_success(item: str, ctx=None) -> int:
    """
    resume/smart_reset 模式下，避免已成功切片重跑：
    - 只處理 root TODO/*.txt 與 root Success/*.txt
    - 優先用 hash 比對（內容相同才刪），失敗時退回 mtime 規則
    - mtime 規則：Success 檔案時間 >= TODO 檔案時間才視為「已完成」
      （避免把上一階段殘留的 Success 過度誤判成當前階段完成）
    """
    todo_dir = Path(item) / "TODO"
    succ_dir = Path(item) / "Success"
    if (not todo_dir.is_dir()) or (not succ_dir.is_dir()):
        return 0

    succ_map = {p.name: p for p in _root_txt_files(str(succ_dir))}
    dropped = 0

    def _file_sha1(fp: Path) -> str:
        h = hashlib.sha1()
        with open(fp, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()

    for todo_fp in _root_txt_files(str(todo_dir)):
        succ_fp = succ_map.get(todo_fp.name)
        if succ_fp is None:
            continue
        try:
            same_hash = (_file_sha1(succ_fp) == _file_sha1(todo_fp))
            if same_hash or (succ_fp.stat().st_mtime >= todo_fp.stat().st_mtime):
                todo_fp.unlink()
                dropped += 1
        except FileNotFoundError:
            continue
    if dropped > 0:
        print(f"[resume] {Path(item).name} 已跳過 {dropped} 個已完成 TODO 切片")
        _append_resume_log(ctx, f"action=drop_todo_by_success item={Path(item).name} dropped={dropped}")
    return dropped


def _root_resume_counts(item: str) -> tuple[int, int, int]:
    """回傳 root-level (TODO, Success, RUNNING) 的 txt 檔數。"""
    todo_n = len(_root_txt_files(str(Path(item) / "TODO")))
    succ_n = len(_root_txt_files(str(Path(item) / "Success")))
    running_n = len(_root_txt_files(str(Path(item) / "RUNNING")))
    return todo_n, succ_n, running_n


def _log_resume_before_after(item: str, before: tuple[int, int, int], after: tuple[int, int, int], ctx=None):
    """
    寫入 resume 前後統計：
    - before: 套用 resume policy 前
    - after : 套用 resume policy 後
    """
    name = Path(item).name
    b_todo, b_succ, b_run = before
    a_todo, a_succ, a_run = after
    print(
        f"[resume] {name} before(T/S/R)={b_todo}/{b_succ}/{b_run} "
        f"after={a_todo}/{a_succ}/{a_run} Δ={a_todo-b_todo}/{a_succ-b_succ}/{a_run-b_run}"
    )
    _append_resume_log(
        ctx,
        (
            f"resume_delta item={name} "
            f"before(TODO/Success/RUNNING)={b_todo}/{b_succ}/{b_run} "
            f"after={a_todo}/{a_succ}/{a_run} "
            f"delta={a_todo-b_todo}/{a_succ-b_succ}/{a_run-b_run}"
        ),
    )


def _apply_resume_policy_multistage(policy: str, prompt_items: list[str], ops: MergeOps, ctx=None):
    """
    resume:
      - 回收 RUNNING 到 TODO，保留 Success
    smart_reset:
      - resume 行為 + 清除 _stage_outputs 快照（避免讀到舊快照）
    full_restart:
      - smart_reset 行為 + 清除 Success（強制所有切片重跑）
    """
    recover_running_to_todo(prompt_items)
    _append_resume_log(ctx, "action=recover_running_to_todo(multistage)")
    for item in prompt_items:
        before_counts = _root_resume_counts(item)
        if policy in {"smart_reset", "full_restart"}:
            stage_outputs = ops.join(item, "_stage_outputs")
            if os.path.isdir(stage_outputs):
                shutil.rmtree(stage_outputs, ignore_errors=True)
                _append_resume_log(ctx, f"action=clear stage_outputs item={Path(item).name}")
        if policy == "full_restart":
            _clear_txt_files(ops.join(item, "Success"), ops)
            _append_resume_log(ctx, f"action=clear Success item={Path(item).name}")
        else:
            _drop_resumed_todo_by_success(item, ctx=ctx)
        if policy in {"smart_reset", "full_restart"}:
            for p in list(Path(item, "TODO").glob("*")):
                if p.is_dir():
                    shutil.rmtree(p, ignore_errors=True)
                    _append_resume_log(ctx, f"action=clear stage_todo_dir item={Path(item).name} dir={p.name}")
        after_counts = _root_resume_counts(item)
        _log_resume_before_after(item, before_counts, after_counts, ctx=ctx)


def _apply_resume_policy_single_stage(policy: str, prompt_items: list[str], ops: MergeOps, ctx=None):
    recover_running_to_todo(prompt_items)
    _append_resume_log(ctx, "action=recover_running_to_todo(single)")
    for item in prompt_items:
        before_counts = _root_resume_counts(item)
        if policy == "full_restart":
            _clear_txt_files(ops.join(item, "Success"), ops)
            _append_resume_log(ctx, f"action=clear Success item={Path(item).name}")
        else:
            _drop_resumed_todo_by_success(item, ctx=ctx)
        after_counts = _root_resume_counts(item)
        _log_resume_before_after(item, before_counts, after_counts, ctx=ctx)


def process_prompt_and_merge_multistage(ctx, file_path: str, ops: MergeOps | None = None, max_rounds: int = 20) -> str:
    """
    多階段版本：
    - 以 stage_runtime 的 chunk x stage 狀態驅動派工
    - 每個 chunk/階段執行兩輪 LLM（retry / non-retry）
    - 每個 chunk 所有階段完成後再進行 combine
    """
    ops = ops or MergeOps()
    main_name = getattr(ctx, "main_file_name", Path(file_path).stem)
    prompt_items = _collect_prompt_items(ctx.prompt_dir, main_name, ops)
    if not prompt_items:
        return ""
    resume_policy = str(getattr(ctx, "resume_policy", "resume") or "resume").strip().lower()
    if resume_policy not in {"resume", "smart_reset", "full_restart"}:
        print(f"⚠️ 未知 resume_policy={resume_policy}，將使用 resume")
        resume_policy = "resume"
    _print_resume_plan(resume_policy, prompt_items, ops, ctx=ctx)
    _apply_resume_policy_multistage(resume_policy, prompt_items, ops, ctx=ctx)

    runtime = init_chunk_stage_runtime(ctx, prompt_items)
    stage_defs = resolve_pipeline_stages(ctx)
    stage_map = {s.name: s for s in stage_defs}
    stage_order = [s.name for s in stage_defs]
    forced_stage_names: set[str] = set()
    for _rule in (getattr(ctx, "sql_writeback_rules", None) or []):
        if not isinstance(_rule, dict):
            continue
        if str(_rule.get("source", _rule.get("sql_writeback_source", "")) or "").strip().lower() != "stage":
            continue
        forced = str(_rule.get("stage", _rule.get("sql_writeback_stage", "")) or "").strip()
        if forced:
            forced_stage_names.add(forced)

    last_stage_name = stage_order[-1] if stage_order else ""
    for s in stage_defs:
        if str(getattr(s, "persist_output", "")).strip().lower() != "final":
            continue
        if s.name == last_stage_name:
            continue
        if s.name in forced_stage_names:
            print(
                f"ℹ️ [stage:{s.name}] persist_output=final 且非最後一段；"
                "因 sql_writeback_rules 引用此 stage，將強制輸出 merged 檔。"
            )
        else:
            print(
                f"⚠️ [stage:{s.name}] persist_output=final 但非最後一段，"
                "不會產生 stage merged 檔。若需供寫回/追蹤，請改成 always 或在 sql_writeback_rules 指定 source=stage。"
            )
    shown_stage_tasks: set[str] = set()
    total_segments = 0
    for item in prompt_items:
        total_segments += len(_root_txt_files(ops.join(item, "TODO")))

    print("=" * 50)
    print("🔁 多階段流程啟動：")
    print(f"  - input_units: {len(prompt_items)}")
    print(f"  - source_slices(total txt): {total_segments}")
    print(f"  - stages: {[s.name for s in stage_defs]}")
    print("=" * 50)

    def _copy_txts(src_dir: str, dst_dir: str):
        MKDIR(dst_dir)
        for fp in ops.list_paths(src_dir):
            if fp.lower().endswith(".txt") and os.path.isfile(fp):
                shutil.copy2(fp, os.path.join(dst_dir, os.path.basename(fp)))

    def _copy_root_todo_txts(src_dir: str, dst_dir: str):
        MKDIR(dst_dir)
        for fp in _root_txt_files(src_dir):
            shutil.copy2(str(fp), os.path.join(dst_dir, fp.name))

    def _write_original_snapshot_from_source(item: str) -> bool:
        """
        嘗試直接以原始檔案重切片，保存純內容快照，避免把第一階段 prompt 模板誤當成 original。
        只有在切片數量與 root TODO 完全一致時才覆蓋快照；否則回退舊行為。
        """
        root_files = _root_txt_files(ops.join(item, "TODO"))
        if not root_files:
            return False
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                source_text = f.read()
            tokenizer = TokenizerWrapper(
                model_name=getattr(ctx, "model_spec_name", ""),
                task=getattr(ctx, "task", ""),
            )
            chunks = tokenizer.tokenize(
                text=source_text,
                adjust=True,
                max_tokens=getattr(ctx, "max_tokens", 12000),
            )
            src_chunks = list(chunks.get("ctxCut", []))
        except Exception:
            return False

        if len(src_chunks) != len(root_files):
            return False

        snap_dir = _snapshot_dir(item, "original")
        MKDIR(snap_dir)
        _clear_txt_files(snap_dir, ops)
        for fp, chunk_text in zip(root_files, src_chunks):
            dst_fp = os.path.join(snap_dir, fp.name)
            with open(dst_fp, "w", encoding="utf-8") as f:
                f.write(chunk_text)
        return True

    # 先保存 original（第一次切片後的 TODO 內容）
    for item in prompt_items:
        if not _write_original_snapshot_from_source(item):
            _copy_root_todo_txts(ops.join(item, "TODO"), _snapshot_dir(item, "original"))

    def _prepare_todo_for_stage(item: str, stage_name: str, stage_task):
        stage_def = stage_map[stage_name]
        effective_input_from = stage_def.input_from
        if isinstance(stage_task, Mapping):
            override_input_from = stage_task.get("input_from")
            if override_input_from is not None:
                effective_input_from = str(override_input_from).strip()
        todo_dir = _stage_todo_dir(item, stage_name)
        root_todo_dir = ops.join(item, "TODO")
        stage_cfg = next((s for s in (getattr(ctx, "stages", None) or []) if isinstance(s, dict) and s.get("name") == stage_name), {})
        stage_input_col = str(stage_cfg.get("input_col", "")).strip() if isinstance(stage_cfg, dict) else ""
        if isinstance(stage_task, Mapping):
            route_input_col_raw = stage_task.get("input_col", stage_task.get("from_col", stage_input_col))
            stage_input_col = "" if route_input_col_raw is None else str(route_input_col_raw).strip()

        stage_source_inputs = getattr(ctx, "stage_source_inputs", {}) or {}
        if stage_input_col and stage_input_col in stage_source_inputs:
            src_text = str(stage_source_inputs.get(stage_input_col, "") or "")
            MKDIR(todo_dir)
            _clear_txt_files(todo_dir, ops)
            for fp in _root_txt_files(root_todo_dir):
                prompt_text = _build_stage_prompt_text(stage_task, src_text, ctx)
                dst_fp = os.path.join(todo_dir, fp.name)
                with open(dst_fp, "w", encoding="utf-8") as f:
                    f.write(prompt_text)
            return
        if (
            stage_name == stage_defs[0].name
            and effective_input_from == "original"
            and len(_root_txt_files(root_todo_dir)) > 0
        ):
            MKDIR(todo_dir)
            _clear_txt_files(todo_dir, ops)
            for fp in _root_txt_files(root_todo_dir):
                shutil.copy2(str(fp), os.path.join(todo_dir, fp.name))
            return  # 已有 TODO，不覆蓋

        if effective_input_from in {"", "none", "null"}:
            src_dir = ""
        elif effective_input_from == "original":
            src_dir = _snapshot_dir(item, "original")
        elif effective_input_from == "previous":
            idx = [s.name for s in stage_defs].index(stage_name)
            prev_name = stage_defs[idx - 1].name if idx > 0 else "original"
            src_dir = _snapshot_dir(item, prev_name)
        else:
            src_dir = _snapshot_dir(item, effective_input_from)

        if effective_input_from in {"", "none", "null"}:
            MKDIR(todo_dir)
            _clear_txt_files(todo_dir, ops)
            for fp in _root_txt_files(root_todo_dir):
                prompt_text = _build_stage_prompt_text(stage_task, "", ctx)
                dst_fp = os.path.join(todo_dir, fp.name)
                with open(dst_fp, "w", encoding="utf-8") as f:
                    f.write(prompt_text)
            return

        if not os.path.isdir(src_dir):
            return
        MKDIR(todo_dir)
        for fp in ops.list_paths(todo_dir):
            if os.path.isfile(fp):
                os.remove(fp)
        for src_fp in sorted(ops.list_paths(src_dir)):
            if not src_fp.lower().endswith(".txt") or not os.path.isfile(src_fp):
                continue
            with open(src_fp, "r", encoding="utf-8") as f:
                source_text = f.read()
            prompt_text = _build_stage_prompt_text(stage_task, source_text, ctx)
            dst_fp = os.path.join(todo_dir, os.path.basename(src_fp))
            with open(dst_fp, "w", encoding="utf-8") as f:
                f.write(prompt_text)

    def _stage_task_debug_text(stage_task) -> str:
        """優先顯示 template 原文；若無法取得則回退為精簡規格。"""
        preview = task_template_preview(stage_task)
        if isinstance(stage_task, Mapping):
            if preview.strip() == str(stage_task).strip():
                compact = {}
                for k in ("CT_name", "InputCutLen"):
                    if k in stage_task:
                        compact[k] = stage_task.get(k)
                if "template" in stage_task:
                    compact["template"] = "<callable>" if callable(stage_task.get("template")) else "<unavailable>"
                return str(compact or {"task": "<mapping>"})
        return preview

    def runner(job, _ctx, _input_text=None):
        if job.stage_name not in shown_stage_tasks:
            print(f"[stage:{job.stage_name}] 📝 使用任務：\n{_stage_task_debug_text(job.stage_task)}")
            shown_stage_tasks.add(job.stage_name)
        print(f"[stage:{job.stage_name}] ▶ 開始處理輸入單位(input_unit): {Path(job.chunk_id).name}")
        _prepare_todo_for_stage(job.chunk_id, job.stage_name, job.stage_task)
        _sync_stage_todo_to_root(job.chunk_id, job.stage_name, ops)
        stage_def = stage_map[job.stage_name]
        debug_enabled, debug_max_chars = _resolve_llm_debug_flags(
            stage_debug_enabled=stage_def.debug_print_llm_io,
            stage_debug_max_chars=stage_def.debug_print_max_chars,
        )
        if debug_enabled:
            _print_stage_llm_io_debug(
                item=job.chunk_id,
                stage_name=job.stage_name,
                max_chars=debug_max_chars,
                mode="prompt",
            )
        before_success_sig = _success_txt_signature_map(job.chunk_id)
        _call_llm_with_task_override(
            ops,
            [job.chunk_id],
            ctx,
            allow_to_retry=True,
            task_override=job.stage_task,
            debug_print_llm_io=debug_enabled,
            debug_print_max_chars=debug_max_chars,
        )
        _call_llm_with_task_override(
            ops,
            [job.chunk_id],
            ctx,
            allow_to_retry=False,
            task_override=job.stage_task,
            debug_print_llm_io=debug_enabled,
            debug_print_max_chars=debug_max_chars,
        )
        if debug_enabled:
            _print_stage_llm_io_debug(
                item=job.chunk_id,
                stage_name=job.stage_name,
                max_chars=debug_max_chars,
                mode="output",
            )
        # 保存本階段 Success 作為後續 stage 可引用輸入
        _copy_stage_success_delta(job.chunk_id, job.stage_name, before_success_sig)
        stage_output_text = _read_stage_snapshot_output(job.chunk_id, job.stage_name)
        todo_files = [str(x) for x in _root_txt_files(ops.join(job.chunk_id, "TODO"))]
        if todo_files:
            return {"ok": False, "error": f"todo_remaining:{len(todo_files)}"}
        print(f"[stage:{job.stage_name}] ✅ 完成輸入單位(input_unit): {Path(job.chunk_id).name}")
        return {"ok": True, "output": stage_output_text}

    run_stage_pipeline(ctx, runtime, runner, max_rounds=max_rounds)

    # 聚合每個 stage 的輸出，保留「全切片視角」的存檔，便於 stage-by-stage 追蹤。
    stage_merge_base = (
        getattr(ctx, "temp_txt_finished_dir", "")
        or getattr(ctx, "llm_source_finished_dir", "")
        or ctx.prompt_dir
    )
    stage_merge_root = ops.join(stage_merge_base, "_stage_merges", main_name)
    MKDIR(stage_merge_root)
    stage_manifest: list[dict] = []
    last_stage_name = stage_defs[-1].name if stage_defs else ""

    for idx, stage in enumerate(stage_defs, start=1):
        should_merge = should_persist_output(stage, last_stage_name=last_stage_name) or (stage.name in forced_stage_names)
        merged_file = ""
        merged_parts: list[str] = []
        if should_merge:
            for item in sorted(prompt_items):
                src_dir = _snapshot_dir(item, stage.name)
                if not os.path.isdir(src_dir):
                    continue
                for fp in sorted(ops.list_paths(src_dir)):
                    if fp.lower().endswith(".txt") and os.path.isfile(fp):
                        with open(fp, "r", encoding="utf-8") as f:
                            merged_parts.append(f.read())
            safe_stage_name = _sanitize_file_component(stage.name)
            safe_stage_key = _sanitize_file_component(getattr(stage, "task_key", ""))
            stage_merged_name = f"{idx:02d}_{safe_stage_name}"
            if safe_stage_key != "na":
                stage_merged_name = f"{stage_merged_name}_{safe_stage_key}"
            stage_merged_fn = ops.join(stage_merge_root, f"{stage_merged_name}.txt")
            with open(stage_merged_fn, "w", encoding="utf-8") as f:
                f.write("\n".join(merged_parts))
            merged_file = os.path.basename(stage_merged_fn)
            print(f"[stage:{stage.name}] 🧩 合併完成，輸出：{stage_merged_fn}（pieces={len(merged_parts)}）")
        else:
            print(f"[stage:{stage.name}] ⏭️ 依 persist_output={stage.persist_output} 跳過 stage 合併輸出")
        stage_entry = {
            "index": idx,
            "name": stage.name,
            "input_from": stage.input_from,
            "persist_output": stage.persist_output,
            "merged": should_merge,
            "merged_file": merged_file,
            "pieces": len(merged_parts),
        }
        if str(stage.task_key).strip():
            stage_entry["task_key"] = stage.task_key
        if isinstance(stage.task, str) and stage.task.strip() and not str(stage.task_key).strip():
            stage_entry["prompt"] = stage.task
        stage_manifest.append(stage_entry)

    manifest_path = ops.join(stage_merge_root, "manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "source": getattr(ctx, "main_file_name", main_name),
                "generated_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
                "stages": stage_manifest,
            },
            f,
            ensure_ascii=False,
            indent=2,
        )
    print(f"[multistage] 🗂️ 已輸出 stage 清單：{manifest_path}")

    def _infer_combine_task_name(stage_obj, stage_task):
        """為最終 combine 輸出推導可讀且穩定的 task 名稱（避免整段 prompt 當檔名）。"""
        if isinstance(stage_task, Mapping):
            return (
                str(stage_task.get("CT_name", "")).strip()
                or str(getattr(stage_obj, "task_key", "")).strip()
                or str(getattr(stage_obj, "name", "")).strip()
                or "stage"
            )

        task_text = str(stage_task or "").strip()
        task_key = str(getattr(stage_obj, "task_key", "")).strip()
        stage_name = str(getattr(stage_obj, "name", "")).strip() or "stage"
        if task_key:
            return task_key

        # freeform prompt：優先用 stage 名稱，避免把整段 prompt 直接塞進檔名。
        if task_text.startswith("@taskSetting:"):
            return task_text.split(":", 1)[1].strip() or stage_name
        if task_text and task_text in taskSetting:
            return task_text
        return f"prompt_{stage_name}"

    def _infer_multistage_combine_task_name(stage_objs) -> str:
        """
        多階段輸出檔名：優先以每段 task_key（無則 stage 名稱）組成可讀短名。
        例：PDF OPT-Instruction First / Translation-toTWZH / Summary-toTWZH
        -> PDF OPT_Translation_Summary
        """
        parts: list[str] = []
        for s in stage_objs or []:
            part = _compact_stage_key_for_output(
                getattr(s, "task_key", ""),
                getattr(s, "name", ""),
            )
            if part:
                parts.append(part)
        if parts:
            return "_".join(parts)
        if stage_objs:
            last = stage_objs[-1]
            return _infer_combine_task_name(last, getattr(last, "task", ""))
        return "stage"

    comb_back_fn = ""
    old_task = getattr(ctx, "task", "")
    try:
        if stage_defs:
            ctx.task = _infer_multistage_combine_task_name(stage_defs)
        for item in prompt_items:
            todo_files = [str(x) for x in _root_txt_files(ops.join(item, "TODO"))]
            if not todo_files:
                combine_out = ops.combine(item, ctx)
                if combine_out:
                    comb_back_fn = combine_out
            else:
                print(f"{item} 尚有 {len(todo_files)} 個段落未處理")
    finally:
        ctx.task = old_task
    return comb_back_fn


def process_prompt_and_merge(ctx, file_path: str, ops: MergeOps | None = None) -> str:
    """
    掃描 ctx.prompt_dir 找出含 main_file_name 的 TODO/Success 目錄父層，呼叫 LLM，完成則合併。
    回傳最後一次成功合併的檔名（若有多個 item，依序覆寫），若皆未完成則回傳空字串。
    """
    ops = ops or MergeOps()
    try:
        stages = resolve_pipeline_stages(ctx)
    except Exception as e:
        # 若使用者有明確配置多階段，解析失敗時不可靜默降級為單階段，
        # 否則會出現「看似成功但只跑第一段」的隱性錯誤。
        has_explicit_stages = bool(getattr(ctx, "stages", None))
        task_cfg = getattr(ctx, "task_config", None)
        if not has_explicit_stages and isinstance(task_cfg, dict):
            has_explicit_stages = "stages" in task_cfg
        if has_explicit_stages:
            raise RuntimeError(f"多階段設定解析失敗，已停止執行：{e}") from e
        stages = []
    if len(stages) > 1:
        return process_prompt_and_merge_multistage(ctx, file_path=file_path, ops=ops)

    main_name = getattr(ctx, "main_file_name", Path(file_path).stem)
    prompt_items = _collect_prompt_items(ctx.prompt_dir, main_name, ops)

    if not prompt_items:
        # 沒東西可處理：建議回傳空字串或擲例外，依你原本語意
        return ""
    resume_policy = str(getattr(ctx, "resume_policy", "resume") or "resume").strip().lower()
    if resume_policy not in {"resume", "smart_reset", "full_restart"}:
        print(f"⚠️ 未知 resume_policy={resume_policy}，將使用 resume")
        resume_policy = "resume"
    _print_resume_plan(resume_policy, prompt_items, ops, ctx=ctx)
    _apply_resume_policy_single_stage(resume_policy, prompt_items, ops, ctx=ctx)

    # 2) 呼叫 LLM（兩輪：允許重試 / 不允許重試）
    ops.call_llm(prompt_items, ctx, allow_to_retry=True)
    ops.call_llm(prompt_items, ctx, allow_to_retry=False)

    # 3) 合併已完成者；若尚有 TODO，僅列印提示
    comb_back_fn = ""
    for item in prompt_items:
        todo_dir = ops.join(item, "TODO")
        todo_files = ops.list_paths(todo_dir)
        if not todo_files:
            combine_out = ops.combine(item, ctx)
            if combine_out:
                comb_back_fn = combine_out
        else:
            print(f"{item} 尚有 {len(todo_files)} 個段落未處理")

    return comb_back_fn


def process_prompt_and_merge_OLD(ctx, file_path):
    # 取得該檔案產生的 prompt 所在目錄
    #print("file name in process_prompt_and_merge",file_path)
    prompt_items = []
    
    #ctx.prompt_dir = ctx.prompt_dir or "./"
    #print("ctx.prompt_dir process_prompt_and_merge",ctx.prompt_dir)
    for file in OSWALK(ctx.prompt_dir):
        path_list = getPathFromFN(file).split("/")
        if path_list[-1] in ["TODO", "Success"]:
            parent_dir = "/".join(path_list[:-1])
            if ctx.main_file_name in parent_dir:
                prompt_items.append(parent_dir)
    prompt_items = list(set(prompt_items))
    #print("prompt_items",prompt_items)
    # 呼叫 LLM API（可以開平行化）
    call_llm_api(prompt_items, ctx, allow_to_retry=True)
    call_llm_api(prompt_items, ctx, allow_to_retry=False)

    # 合併輸出
    for item in prompt_items:
        TodoSubDir = os.path.join(item, "TODO")
        if len(OSWALK(TodoSubDir)) == 0:
            CombBackFN = combine_api_finished_item(item, ctx)
        else:
            print(f"{item} 尚有 {len(OSWALK(TodoSubDir))} 個段落未處理")
            CombBackFN = ""
    return CombBackFN


def _mock_llm_text(task_text: str, content: str, ctx) -> str:
    """本地 mock LLM：在無模型環境下提供可重現輸出，供 E2E 驗證。"""
    task_l = str(task_text or "").lower()
    if any(k in task_l for k in ["route", "分類", "classify"]):
        return json.dumps({"route": "org"}, ensure_ascii=False)

    fields = getattr(ctx, "allowed_output_fields", None)
    if isinstance(fields, (list, tuple)) and fields:
        payload = {str(f): f"mock_{str(f)}" for f in fields if str(f).strip()}
        if payload:
            return json.dumps(payload, ensure_ascii=False)
    # fallback
    return json.dumps({"mock_result": content[:120]}, ensure_ascii=False)


def _run_mock_llm_api(itemList, ctx, allow_to_retry=True, task_override: str | None = None):
    for item in itemList:
        todo_dir = os.path.join(item, "TODO")
        for promptFile in _root_txt_files(todo_dir):
            pf = str(promptFile)
            out_fn = pf.replace("TODO", "Success")
            MKDIR(getPathFromFN(out_fn))
            try:
                with open(pf, mode='rt', encoding='utf-8') as fp:
                    content = fp.read()
            except Exception:
                content = ""
            task_text = task_override if task_override is not None else getattr(ctx, "task", "")
            out_text = _mock_llm_text(task_text, content, ctx)
            with open(out_fn, mode='wt', encoding='utf-8') as fw:
                fw.write(out_text)
            try:
                safe_unlink(pf)
            except Exception:
                pass
    return []


def call_llm_api(
    itemList,
    ctx,
    allow_to_retry=True,
    PGMSubDir="",
    task_override: str | None = None,
    debug_print_llm_io: bool = False,
    debug_print_max_chars: int = 2000,
):
    if bool(getattr(ctx, "mock_llm_mode", False)):
        return _run_mock_llm_api(itemList, ctx, allow_to_retry=allow_to_retry, task_override=task_override)

    ArtCost = dict()
    DTBJobs_Retry = []
    def create_jobs(item,model_spec):
        TodoSubDir = os.path.join(item, "TODO")
        return [PromptAPIPipeline(
            task=task_override if task_override is not None else ctx.task,
            promptFile=str(promptFile),
            OutputSaveFN=str(promptFile).replace("TODO", "Success"),
            removeFinPromptFile=ctx.removeFinPromptFile,
            max_tokens=ctx.max_tokens,
            #On_Premises=ctx.on_premises,
            allow_to_retry=allow_to_retry,
            model_spec=(
                dict(deepcopy(model_spec), mock_llm_mode=True)
                if bool(getattr(ctx, "mock_llm_mode", False))
                else model_spec
            ),
            PGMSubDir=ctx.PGMSubDir,
            debug_print_llm_io=debug_print_llm_io,
            debug_print_max_chars=debug_print_max_chars,
        ) for promptFile in _root_txt_files(TodoSubDir)]

    if ctx.mp_for_all_call:
        DTBJobs = []
        for item in itemList:
            DTBJobs.extend(create_jobs(item,ctx.model_spec))
        MPresult = multicoreJob(DTBJobs=DTBJobs, nProcess=ctx.n_process, ShuffleJobs=False).run()
        #if MPresult:
        #    responseList, costList, DTBJobs_Retry = zip(*MPresult)
        #    CostLog(PGMSubDir = PGMSubDir, costList=costList, mode="AllArt")
        if MPresult:
            # MPresult 每個元素都是 dict
            #outputs = [r.get("output", "") for r in MPresult]
            costList = [float(r.get("cost", 0) or 0) for r in MPresult]
            # 你現在 queue 模式其實不需要 retry jobs 物件了
            DTBJobs_Retry = []
            CostLog(PGMSubDir=PGMSubDir, costList=costList, mode="AllArt")
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
                 max_tokens=8192,
                 #On_Premises=False,
                 allow_to_retry=True,
                 model_spec: dict | None = None, #避免可變預設
                 #model_spec = dict(),
                 include_think = False,
                 PGMSubDir = "",
                 debug_print_llm_io: bool = False,
                 debug_print_max_chars: int = 2000,
                 
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
        self.debug_print_llm_io = bool(debug_print_llm_io)
        self.debug_print_max_chars = int(debug_print_max_chars)
        
        # 1) 拿到規格的「私有」副本
        spec = deepcopy(model_spec) if model_spec else {}

        # 2) 不足就補（確保回傳的是新 dict；保守點再 deepcopy 一次）
        if not all(k in spec for k in ("base_url", "model_name")):
            spec = deepcopy(select_model(spec) or {})

        # 3) 正規化 base_url → list，但只動「自己的」 spec
        bul = spec.get("base_url")
        if bul is None:
            spec["base_url"] = []
        elif isinstance(bul, str):
            spec["base_url"] = [bul]
        else:
            spec["base_url"] = list(bul)
        self.model_spec = spec
        self.PGMSubDir = PGMSubDir
        #print("model_spec b4",model_spec)
        '''#0112
        if not all(key in self.model_spec for key in ["base_url", "model_name"]):
            self.model_spec = select_model(self.model_spec)
        self.model_spec["base_url"] = [self.model_spec["base_url"]] if isinstance(
            self.model_spec.get("base_url"), str) else self.model_spec["base_url"]
        '''#0112

        

        
    def show(self,):
        print("輸入prompt檔案",self.promptFile)
        print("輸出儲存檔案",self.OutputSaveFN)
        if self.debug_print_llm_io:
            print(
                "[llm-io] 送往LLM(Prompt) [preflight]\n"
                f"{_preview_text_for_debug(self.content, self.debug_print_max_chars)}"
            )

    def _is_mock_mode(self) -> bool:
        model_name = str(self.model_spec.get("model_name", "") or "").lower()
        if model_name.startswith("mock"):
            return True
        return bool(self.model_spec.get("mock_llm_mode", False))

    def _build_mock_output(self) -> str:
        task_l = str(self.task or "").lower()
        if any(k in task_l for k in ["route", "分類", "classify"]):
            return json.dumps({"route": "org"}, ensure_ascii=False)
        if "to json" in task_l:
            return json.dumps({"mock_result": (self.content or "")[:120]}, ensure_ascii=False)
        return f"mock_result: {(self.content or '')[:120]}"

    def proc(self):
        print("="*50)
    
        # ====== 先初始化：避免例外時 retMES/cost 未定義 ======
        retMES = ""
        cost = 0
        err = ""
        ok = False
        base_url = None
        DTBJobs_Retry = []
    
        if self.promptFile == "":
            print(f"No promptFile is input, run for content: {self.content[:200]}...")
            if len(self.content) > 300:
                print(f"{self.content[-100:]}")
        else:
            print(f"Calling LLM API for promptFile: {self.promptFile}")
        if self.debug_print_llm_io:
            print(
                "[llm-io] 送往LLM(Prompt)\n"
                f"{_preview_text_for_debug(self.content, self.debug_print_max_chars)}"
            )
        print("allow_to_retry is ", self.allow_to_retry)
    
        try:
            # mock 模式：不進 LLM 呼叫，直接產生可驗證輸出
            if self._is_mock_mode():
                retMES = self._build_mock_output()
                if self.OutputSaveFN != "":
                    MKDIR(os.path.dirname(self.OutputSaveFN))
                    tmp_fn = self.OutputSaveFN + ".tmp"
                    with open(tmp_fn, mode='wt', encoding='utf-8') as fp:
                        fp.write(retMES)
                        fp.flush()
                        os.fsync(fp.fileno())
                    os.replace(tmp_fn, self.OutputSaveFN)
                    if self.removeFinPromptFile and self.promptFile:
                        safe_unlink(self.promptFile)
                ok = bool(retMES)
                err = ""
                ret_dict = {
                    "promptFile": self.promptFile,
                    "outputSaveFN": self.OutputSaveFN,
                    "output": retMES,
                    "cost": 0.0,
                    "ok": ok,
                    "error": err,
                }
                return ret_dict

            # 1) 選 base_url
            base_url = select_idle_ollama_url(self.model_spec["base_url"], PGMSubDir=self.PGMSubDir)
            self.model_spec["base_url"] = base_url
    
            if "api_key" not in self.model_spec:
                self.model_spec["api_key"] = "ThisIsFakeKey"
    
            # 2) 呼叫 LLM
            response, cost = CallLLMAPI(
                self.content,
                max_tokens=self.max_tokens,
                model_spec=self.model_spec
            )
    
            # 3) token 警告
            if response.usage.completion_tokens >= self.max_tokens:
                log_dir = "logs"
                os.makedirs(log_dir, exist_ok=True)
                log_file = os.path.join(log_dir, "Completion_tokens.txt")
                MES = (
                    f"⚠️ Warning! Completion tokens reached {response.usage.completion_tokens} "
                    f"(max {self.max_tokens}) for content: {self.content[:200]}..."
                )
                print(MES)
                with open(log_file, "a", encoding="utf-8") as fp:
                    fp.write(MES + "\n")
    
            # 4) 取出結果並清理
            retMES = response.choices[0].message.content
            if self.debug_print_llm_io:
                print(
                    "[llm-io] LLM輸出(Output)\n"
                    f"{_preview_text_for_debug(retMES, self.debug_print_max_chars)}"
                )
    
            if self.include_think == False:
                retMES = re.sub(r'<think>.*?</think>', '', retMES, flags=re.DOTALL)
    
            if retMES.replace(" ", "").replace("\n", "") == "<EMPTY>":
                retMES = ""
    
            if "to json" in self.task.lower():
                retMES = retMES.replace('```json', '').replace('```', '').strip()
    
            # 5) JSON 驗證與重試任務
            if self.allow_to_retry and "to json" in self.task.lower():
                DTBJobs_Retry, retMES = self.handle_json_output(retMES)
    
            # 6) 落地 Success（只有沒有 retry 且有內容才寫）
            if self.OutputSaveFN != "" and DTBJobs_Retry == [] and retMES != "":
                MKDIR(os.path.dirname(self.OutputSaveFN))
                tmp_fn = self.OutputSaveFN + ".tmp"
                with open(tmp_fn, mode='wt', encoding='utf-8') as fp:
                    fp.write(retMES)
                    fp.flush()
                    os.fsync(fp.fileno())
                os.replace(tmp_fn, self.OutputSaveFN)
    
                if self.removeFinPromptFile and self.promptFile:
                    safe_unlink(self.promptFile)
    
            # 7) 成功旗標
            ok = bool(retMES)
            err = ""
    
            # 你如果後面還會用 response 物件可留著；但回傳不要回傳它
            response.choices[0].message.content = retMES
    
        except Exception as ex:
            # ====== 這裡就是你問的「例外時回」 ======
            retMES = ""
            ok = False
            err = str(ex)
            if not cost:
                cost = 0
    
            print(f"When run PromptAPIPipeline, the following error occurs for promptFile {self.promptFile}:\n {ex}")
            print(f"self.model_spec:{self.model_spec}")
    
        finally:
            try:
                if base_url:
                    release_url_load(base_url, PGMSubDir=self.PGMSubDir)
            except Exception:
                pass
    
        # ====== 診斷：改成檢查 dict 可 pickle ======
        ret_dict = {
            "promptFile": self.promptFile,
            "outputSaveFN": self.OutputSaveFN,
            "output": retMES,
            "cost": float(cost or 0),
            "ok": ok,
            "error": err,
        }
    
        try:
            import pickle
            data = pickle.dumps(ret_dict, protocol=pickle.HIGHEST_PROTOCOL)
            print(f"[diag] worker return picklable, size={len(data)} bytes")
        except Exception as e:
            print(f"[diag] worker return NOT picklable: {type(e).__name__}: {e}")
            try:
                print(f"[diag] ret_dict keys={list(ret_dict.keys())}")
            except Exception:
                pass
    
        return ret_dict
        
    def proc_0112(self, ):
        print("="*50)
        if self.promptFile == "":
            #print(f"Calling LLM API for promptFile: {self.promptFile}")
            print(f"No promptFile is input, run for content: {self.content[:200]}...")
            if len(self.content)>300:
                 print(f"{self.content[-100:]}")
            #print(f"No promptFile is input, run for content: {self.content}")
        else:
            print(f"Calling LLM API for promptFile: {self.promptFile}")
        print("allow_to_retry is ",self.allow_to_retry)
        DTBJobs_Retry = []
        try:
            # 在這裡選擇負載最輕的 base_url
            #print("inputing base url in pipeline_controller",self.model_spec["base_url"])
            base_url = select_idle_ollama_url(self.model_spec["base_url"],PGMSubDir=self.PGMSubDir)
            
            self.model_spec["base_url"] = base_url  # 更新 model_spec 的 base_url
            #print(f"已分配 base_url: {base_url} 進行處理")  # 顯示選擇的 base_url
            #print("Start to run CallLLMAPI in PromptAPIPipeline")
            #print("self.model_spec in PromptAPIPipeline",self.model_spec)
            if "api_key" not in self.model_spec:
                self.model_spec["api_key"]=("ThisIsFakeKey")
            response,cost = CallLLMAPI(
                self.content,max_tokens=self.max_tokens,
                #On_Premises=self.On_Premises,
                model_spec=self.model_spec)
            #print("Finished CallLLMAPI in PromptAPIPipeline")

            
            if response.usage.completion_tokens >= self.max_tokens:
                log_dir = "logs"
                os.makedirs(log_dir, exist_ok=True)
                log_file = os.path.join(log_dir, "Completion_tokens.txt")
                MES = (
                    f"⚠️ Warning! Completion tokens reached {response.usage.completion_tokens} "
                    f"(max {self.max_tokens}) for content: {self.content[:200]}..."
                )
                print(MES)
                with open(log_file, "a", encoding="utf-8") as fp:
                    fp.write(MES + "\n")
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
            #print("-"*50)
            #if self.removeFinPromptFile == True and self.promptFile != "":
            #    os.remove(self.promptFile)
            
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
            #if self.OutputSaveFN != "" and DTBJobs_Retry == []:
            if self.OutputSaveFN != "" and DTBJobs_Retry == [] and retMES != "":
                MKDIR(os.path.dirname(self.OutputSaveFN))
                tmp_fn = self.OutputSaveFN + ".tmp"
                #print(f"Start to run os.sync for tmp_fn {tmp_fn}")
                with open(tmp_fn, mode='wt', encoding='utf-8') as fp:
                    fp.write(retMES)
                    fp.flush()
                    os.fsync(fp.fileno())  # 確保落地
                #print(f"Finished running os.sync for tmp_fn {tmp_fn}")
                #print(f"Start to run os.replace for tmp_fn {tmp_fn}")
                os.replace(tmp_fn, self.OutputSaveFN)  # ✅ 原子替換
                #print(f"Finished running os.replace for tmp_fn {tmp_fn}")
                if self.removeFinPromptFile and self.promptFile:
                    #print(f"Start to run os.remove for self.promptFile {self.promptFile}")
                    #os.remove(self.promptFile)         # ✅ 再刪 TODO
                    safe_unlink(self.promptFile)  # 刪 RUNNING/xxx.txt
                    #print(f"Finished running os.remove for self.promptFile {self.promptFile}")
                    

            #將處理過的文字訊息回填response物件
            response.choices[0].message.content = retMES
            
            
        except Exception as ex:
            if not "response" in locals():
                response = None
                cost = 0
            print(f"When run PromptAPIPipeline, the following error occurs for promptFile {self.promptFile}:\n {ex}")
            print(f"self.model_spec:{self.model_spec}")
            #countdown_pause(30)
            
        finally:
            try:
                # 任務完成後釋放負載
                release_url_load(base_url, PGMSubDir=self.PGMSubDir)
            except Exception:
                pass
        # ---- 返還前：診斷是否可被 pickl e（只做一次即可）----
        '''#0112
        try:
            import pickle
            ret_tuple = (response, cost, DTBJobs_Retry)
            data = pickle.dumps(ret_tuple, protocol=pickle.HIGHEST_PROTOCOL)
            print(f"[diag] worker return picklable, size={len(data)} bytes")
        except Exception as e:
            # 這裡若進來，就 100% 證明「回傳值不可 pickl e」
            print(f"[diag] worker return NOT picklable: {type(e).__name__}: {e}")
            # 再列一下各成員的型別，方便你知道是誰作怪
            try:
                print(f"[diag] response type={type(response)}, cost type={type(cost)}, DTBJobs_Retry type={type(DTBJobs_Retry)}")
                if DTBJobs_Retry:
                    print(f"[diag] DTBJobs_Retry[0] type={type(DTBJobs_Retry[0])}")
            except Exception:
                pass
        '''#0112        
                

        try:
            import pickle
            ret = {
                "promptFile": self.promptFile,
                "output": retMES,
                "cost": float(cost or 0),
                "ok": bool(retMES),
                "error": ""
            }
            pickle.dumps(ret, protocol=pickle.HIGHEST_PROTOCOL)
        except Exception as e:
            print(f"[diag] return NOT picklable: {type(e).__name__}: {e}")
            
            #return response, cost, DTBJobs_Retry
            # ✅ 回傳可序列化資料
            return {
                "promptFile": self.promptFile,
                "outputSaveFN": self.OutputSaveFN,
                "output": retMES,
                "cost": float(cost or 0),
                "ok": bool(retMES),          # 有產出就算成功
                "error": ""                  # 失敗時放錯誤訊息
            }

    def handle_json_output(self, retMES):
        '''
        嘗試用json.loads驗證回傳訊息json正確性，
        回傳值為空清單或重跑任務物件清單跟修正後訊息。
        '''
        retMES_rep = None
        try:
            #print("raise Exception to debug json output")
            #raise Exception
            json.loads(retMES)
            return [],retMES
        except json.JSONDecodeError:
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
                if retMES_rep is not None:
                    print("retMES_rep", retMES_rep)
                MainFileName,input_text,keyConsiderations = self.extract_MainFileName_and_input_text()
                if input_text:
                    # ✅ 改成：只產生新 TODO prompt 檔，不回傳 job 物件
                    self.split_and_generate_new_prompts(
                        input_text=input_text,
                        keyConsiderations=keyConsiderations,
                        MainFileName=MainFileName
                    )
                    # ✅ 回傳空清單 + 空字串：告訴上層「這次不要產出結果檔」
                    return [], ""
                else:
                    print("未於prompt中截獲非空的原始輸入任務文本，不生成再次嘗試的新prompt。")
                    return [], ""
                '''#0112
                if input_text:
                    DTBJobs_Retry = self.split_and_generate_new_prompts(
                        input_text=input_text,keyConsiderations=keyConsiderations,
                        MainFileName=MainFileName)
                else:
                    DTBJobs_Retry = []
                    print("未於prompt中截獲非空的原始輸入任務文本，不生成再次嘗試的新prompt。")
                return DTBJobs_Retry,""
                '''#0112

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
        
    def split_and_generate_new_prompts(self, input_text, MainFileName="", keyConsiderations=""):
        half_length = len(input_text) // 2
        first_half = input_text[:half_length]
        second_half = input_text[half_length:]
    
        # ✅ 1) 不要用 RUNNING 當 base_name；先取得「TODO 對應路徑」當基準
        todo_pf = _ensure_in_todo(self.promptFile)  # 例如 .../TODO/xxx.txt
        p = Path(todo_pf)
        todo_dir = p.parent
        stem = p.stem  # xxx
        new_prompt_file_0 = str(todo_dir / f"{stem}-0.txt")
        new_prompt_file_1 = str(todo_dir / f"{stem}-1.txt")
    
        print("start to generate new prompt.")
        print("self.task", self.task)
        print("MainFileName", MainFileName)
    
        prompt_0 = generate_prompt(
            content=first_half, keyConsiderations=keyConsiderations,
            task=self.task, MainFileName=MainFileName
        )
        prompt_1 = generate_prompt(
            content=second_half, keyConsiderations=keyConsiderations,
            task=self.task, MainFileName=MainFileName
        )
    
        # ✅ 2) 新檔直接寫入 TODO，下一輪 consumer 才會 pick 到
        for prompt, fn in [(prompt_0, new_prompt_file_0), (prompt_1, new_prompt_file_1)]:
            with open(fn, "wt", encoding="utf-8") as fp:
                fp.write(prompt)
    
        # ✅ 3) 刪掉「目前這筆」的 prompt 檔：它現在通常在 RUNNING
        # 目的：讓 consumer 能判定這筆已釋放（你後面會把它當 requeued）
        try:
            safe_unlink(self.promptFile)  # 你已有的安全刪除
        except Exception as e:
            print(f"warn: failed to remove original prompt {self.promptFile}: {e}")
    
        print(f"Generated new TODO prompt files: {new_prompt_file_0}, {new_prompt_file_1}")
    
        # ✅ 4) 在「檔案隊列」模式下，其實不需要回傳 DTBJobs_Retry 物件
        # 讓 consumer 下一輪從 TODO 讀檔即可
        return []
        
    def split_and_generate_new_prompts_0112(self, input_text,MainFileName="",keyConsiderations=""):
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
        # 生成新 prompt 後，移除舊 TODO（很重要！讓 consumer 能判定這筆已完成／釋放 running）
        try:
            os.remove(self.promptFile)
        except Exception as e:
            print(f"warn: failed to remove original prompt {self.promptFile}: {e}")
        
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
    '''#0112
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
    '''#0112
    ret = PromptAPIPipeline(
        content=prompt,
        task=task,
        removeFinPromptFile=True,
        max_tokens=max_tokens,
        model_spec=model_spec
    ).proc()
    
    if not ret or not ret.get("ok"):
        return None
    
    return combine_json_return(ret.get("output", ""))[0]



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
    
    
def producer_backpressure_wait(ctx: LLMJobConfig,
                               low: int,
                               meter_fn: str,
                               stop_event,
                               consumer_thread=None,
                               registry=None,
                               soft_timeout: float = 30.0,
                               hard_timeout: float = 120.0,
                               sleep_step: float = 0.05):
    """
    等待 outstanding <= low，帶超時與健檢。
    - soft_timeout：超過此秒數無進度，印一次快照（若可）。
    - hard_timeout：超過此秒數仍未下降，放行（避免永久卡住）。
    """
    start = time.time()
    last_outstanding = None
    last_change_ts = start

    while True:
        # 停止訊號 → 直接返回
        if stop_event.is_set():
            return

        # 消費者緒死亡 → 不等，放行並警告
        if consumer_thread is not None and not consumer_thread.is_alive():
            try:
                tlog_warn("⚠️ 背壓等待中偵測到消費者緒已終止，略過等待並繼續補貨。")
            except Exception:
                print("⚠️ 背壓等待中偵測到消費者緒已終止，略過等待並繼續補貨。")
            # 只送一次（可選）
            if not getattr(ctx, "_restart_sent", False):
                setattr(ctx, "_restart_sent", True)
                from czjLLM.sql_mode.runtime.workers import consumer_restart_cb
                try:
                    consumer_restart_cb(ctx)
                except NameError:
                    try: tlog_warn("[restart_cb] 未找到 consumer_restart_cb，請確認已匯入。")
                    except Exception: print("[restart_cb] 未找到 consumer_restart_cb，請確認已匯入。")
                except Exception as e:
                    try: tlog_warn(f"[restart_cb] 送出重啟信號時發生例外：{e}")
                    except Exception: print(f"[restart_cb] 送出重啟信號時發生例外：{e}")
            return

        # 讀取 outstanding（容錯）
        try:
            m = meter_read(meter_fn)
            q = m.get("queue", {})
            outstanding = int(q.get("pending", 0)) + int(q.get("running", 0))
            if outstanding < 0:
                outstanding = 0
        except Exception:
            # 讀取計量檔失敗 → 短暫等待再試；不要卡死
            time.sleep(min(0.2, sleep_step * 4))
            continue

        if outstanding <= low:
            return  # 條件達成

        # 追蹤是否有變化
        now = time.time()
        if last_outstanding is None or outstanding != last_outstanding:
            last_outstanding = outstanding
            last_change_ts = now

        # soft timeout：吐快照一次（不結束）
        if (now - last_change_ts) >= soft_timeout:
            try:
                if build_debug_snapshot and registry is not None:
                    snap = build_debug_snapshot(ctx, registry, meter_fn)
                    tlog_warn(f"🛠 背壓等待已 {int(now - last_change_ts)}s 無下降，狀態快照：\n{snap}")
                else:
                    tlog_warn(f"🛠 背壓等待已 {int(now - last_change_ts)}s 無下降（outstanding={outstanding}, low={low}）。")
            except Exception:
                print(f"🛠 背壓等待已 {int(now - last_change_ts)}s 無下降（outstanding={outstanding}, low={low}）。")
            # 重設 soft 計時，避免狂刷
            last_change_ts = now

        # hard timeout：直接放行，避免永久卡死
        if (now - start) >= hard_timeout:
            try:
                tlog_warn(f"⏱️ 背壓等待超過 {int(hard_timeout)}s，放行補貨（outstanding={outstanding}, low={low}）。")
            except Exception:
                print(f"⏱️ 背壓等待超過 {int(hard_timeout)}s，放行補貨（outstanding={outstanding}, low={low}）。")
            return

        time.sleep(sleep_step)
