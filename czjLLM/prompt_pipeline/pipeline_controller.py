# pipeline_controller.py
import os
import errno
#from colorama import Fore, Style
from tqdm import tqdm
import re
#import random
import json
import hashlib
import inspect
import time
import uuid
import threading
#import queue
from collections import Counter
from datetime import datetime
#import sqlite3
#import pyodbc
import shutil
from copy import deepcopy
from dataclasses import dataclass
from collections.abc import Mapping
from pathlib import Path
import faulthandler

#from czjLLM.prompt_pipeline.result_handler import PromptResultHandler
from czjLLM.prompt_pipeline.prompt_generator import generate_prompt, _render_raw_task_prompt, write_prompt_component_metrics
from czjLLM.taskConfig import taskSetting
from czjLLM.prompt_pipeline.llm_caller import CallLLMAPI, classify_llm_call_exception
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
from czjLLM.job_manager import job_config as _job_config
from czjLLM.job_manager.job_config import LLMJobConfig, task_template_preview
#from czjLLM.job_manager.end_point_manager import get_available_end_points
from czjLLM.job_manager.end_point_manager import select_model
#from job_manager.win_gui import try_start_gui  # 為避免循環，可移到檔頭

from czjLLM.utilities.combine_utils import combine_api_finished_item
from czjLLM.utilities.combine_utils import combine_json_return
from czjLLM.utilities.slice_merge import (
    merge_dict_slices_audited, is_multidim_event_slice_merge,
    is_multidim_event_source_merge, needs_per_output_slice_merge,
    should_merge_slices,
)
from czjLLM.prompt_pipeline.task_fingerprint import fingerprint_task
from czjLLM.prompt_pipeline.slice_identity import (
    committed_split_parent_identities, digest_text,
    include_committed_split_roots, install_split_prompts,
    is_verified_queued_split_child, reconcile_split_transitions,
    verified_queued_prompt_source, verified_split_family_id,
    record_success_identity, resolve_success_leaves,
    restore_full_restart_parent, valid_success,
)
from czjLLM.utilities.logging_utils import CostLog
from czjLLM.utilities.llm_call_audit import log_llm_call, read_prompt_token_metadata, relabel_prompt_token_stage
from czjLLM.utilities.processing_quality import emit_quality_event
from czjLLM.reduction.execution import ExecutionCancelled
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
from czjLLM.prompt_pipeline.dispatch_parallelism import (
    lease_execution_workers,
    resolve_slice_parallelism,
)

from czjLLM.infrastructure.ollama_lb import select_idle_ollama_url,release_url_load

#from czjLLM.sql_utils.common import quote_column
#from czjLLM.sql_utils.writer import flatten_row_based_json_array_to_subtable
#from czjLLM.sql_utils.row_utils import upsert_single_value
#from czjLLM.row_processors.flatten_utils import extract_json_list_for_flatten
#from czjLLM.utilities.path_utils import get_combined_result_path
from czjLLM.job_manager.console_ui import  tlog_warn
from czjLLM.prompt_pipeline.round_runner import (
    BatchRunTimeout,
    CONSUMER_STATE,
    run_round,
)
from czjLLM.prompt_pipeline.runtime_support.load_meter import (
    ItemsRegistry,
    find_item_dir_for,
    meter_init,
    meter_path_init,
    meter_read,
    meter_update,
    safe_unlink,
)
from czjLLM.prompt_pipeline.runtime_support.queue_observation import record_queue_transition, verified_claim_observation
from czjLLM.prompt_pipeline.runtime_support.prompt_queue import (
    _ensure_in_todo,
    _running_to_todo,
    _to_success,
    _to_todo,
    pick_and_claim_next_prompts,
    recover_running_to_todo,
    require_no_pending_todo_sources,
    publish_success_text_no_clobber,
    QueueClaimRollbackError,
    QueueClaimSuccessConflictError,
    require_no_pending_success_conflicts,
)
from czjLLM.prompt_pipeline.runtime_support.stage_mode import (
    explicit_stage_flow as _explicit_stage_flow,
    stage_cfg_declares_flow as _stage_cfg_declares_flow,
)
from czjLLM.prompt_pipeline.runtime_support.watchdogs import (
    _es_heartbeat_loop,
    _stall_watchdog,
    _stall_watchdog_0119,
    start_watchdogs,
)

def _canon_path(p: str) -> str:
    # 轉絕對路徑 + 正規化分隔 + Windows 大小寫無關
    return os.path.normcase(os.path.normpath(os.path.abspath(p)))

def _bump(ctx):
    try:
        ctx.last_progress_ts = time.time()
    except Exception:
        pass
        
# Load meter / registry helpers are implemented in focused modules and re-exported here
# for backwards-compatible imports from pipeline_controller.

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


def _audit_consumer_orchestration_failure(ctx, code: str) -> None:
    """Count one run-scoped incident, never a slice/document or API failure.

    Audit failures must not affect existing retry, cancellation or teardown.
    """
    try:
        emit_quality_event(
            getattr(ctx, "llm_call_audit_path", ""),
            run_id=getattr(ctx, "llm_call_audit_run_id", ""),
            event="consumer_orchestration_failure", code=code,
            scope="run", outcome="observed",
        )
    except Exception as audit_error:
        try:
            tlog_warn(
                "⚠️ consumer quality audit failed: "
                f"{type(audit_error).__name__}"
            )
        except Exception:
            pass


def _audit_leaf_worker_phase_failure(audit_path: str, run_id: str, code: str) -> None:
    """Observe the actual leaf Worker boundary without payload or row identity.

    This is a best-effort phase attribution, NOT proof of provider root cause.
    The existing request CSV audit and error/return behavior stay unchanged.
    """
    try:
        emit_quality_event(
            audit_path, run_id=run_id,
            event="worker_phase_failure", code=code,
            scope="run", outcome="observed",
        )
    except Exception:
        # Never make audit persistence a second Worker failure.
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

    round_timed_out = False
    MPresult = []
    ok_prompt_files = set()

    try:
        try:
            stage_defs = resolve_pipeline_stages(ctx)
        except Exception:
            stage_defs = []
            
        #multistage_mode = len(stage_defs) > 1
        
        stage_writeback_rules = [
            r for r in (
                getattr(ctx, "es_writeback_rules", None)
                or getattr(ctx, "sql_writeback_rules", None)
                or []
            )
            if isinstance(r, dict)
            and str(r.get("source", "")).strip().lower() == "stage"
        ]
        
        # Do not repeat the old bug here: ES entry setup may attach an empty
        # or compatibility-only stage_cfg (for example name=single_stage,
        # enabled=False) even when the YAML is a legacy single-task job.  Only
        # a stage_cfg that declares runnable flow should disable this consumer.
        stage_cfg_has_flow = _stage_cfg_declares_flow(getattr(ctx, "stage_cfg", None))
        
        stage_managed_mode = (
            len(stage_defs) > 1
            or bool(stage_writeback_rules)
            or stage_cfg_has_flow
        )
        
        if stage_managed_mode:
            try:
                tlog("[consumer] stage-managed mode enabled; consumer will not pick TODO files")
                
        #if multistage_mode:
        #    try:
        #        tlog("[consumer] multistage mode enabled; consumer will not pick TODO files because process_prompt_and_merge handles stages per row")
            except Exception:
                pass
        
            try:
                meter_update(meter_fn, lambda d: d.setdefault("consumer", {}).update({
                    "alive": False,
                    "disabled_for_multistage": True,
                    "disabled_ts": time.time(),
                }))
            except Exception:
                pass
        
            return

        tlog(f"[consumer] using meter: {meter_fn}")  # 診斷：應與 orchestrator 印出的路徑一致
        print("meter_fn in llm_stream_consumer",meter_fn)
        #did_recover = False  # ← 新增：只復原一次
        while True:
            # 🔸 A. 若收到了「重啟」信號 → 做一次 RUNNING→TODO 的復原，然後清掉事件
            if restart_event is not None and restart_event.is_set():
                try:
                    items_map = registry.list_items()
                    item_dirs = list(items_map.keys())
                    n_requeued = recover_running_to_todo(item_dirs)
                    def _mark_restart_requeue(d, _n=n_requeued):
                        q = d.setdefault("queue", {})
                        if _n:
                            q["running"] = max(0, int(q.get("running", 0) or 0) - int(_n))
                            q["pending"] = int(q.get("pending", 0) or 0) + int(_n)
                        cons = d.setdefault("consumer", {})
                        cons.update({
                            "last_dispatch_ts": time.time(),
                            "last_restart_requeued": int(_n),
                            "last_restart_requeued_ts": time.time(),
                        })
                    meter_update(meter_fn, _mark_restart_requeue)
                    tlog_warn(f"[consumer] restart_event 收到 → 已復原 RUNNING→TODO {n_requeued} 個切片，繼續派工")
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
            claimed_evidence = {}
            try:
                batch = pick_and_claim_next_prompts(
                    item_dirs, per_round_limit=per_round_limit,
                    claim_ids_out=claimed_evidence,
                )
            except QueueClaimRollbackError:
                # Rollback itself failed after a real claim; preserve all
                # filesystem evidence, but tell the coordinator that pending
                # work cannot be completed by this now-terminating consumer.
                # Producer done is independent from the teardown stop event.
                blocked = getattr(ctx, "_queue_claim_blocked_event", None)
                if blocked is not None:
                    blocked.set()
                raise

            if not batch:
                # A TODO with an older Success is permanently unclaimable.
                # The older Worker may have published between our initial
                # check and a fresh claim, which was safely restored. Unlike
                # generic contention, we know this cannot drain even if the
                # Producer is still blocked under backpressure. Signal now,
                # independently of producer_done, so Producer and coordinator
                # both terminate the run as failed without fabricating work.
                try:
                    require_no_pending_success_conflicts(item_dirs)
                except QueueClaimSuccessConflictError:
                    blocked = getattr(ctx, "_queue_claim_blocked_event", None)
                    if blocked is not None:
                        blocked.set()
                    raise
                # Producer completion is NOT stop_event: in SQL/Table/ES,
                # teardown sets stop_event only after the coordinator finishes.
                # If the producer is done and there are no in-flight sources,
                # an unclaimable TODO cannot drain itself. Signal the shared
                # coordinator before it waits forever for pending==0.
                producer_done = getattr(ctx, "_producer_done_flag", None)
                if (producer_done is not None and producer_done.is_set()
                        and not stop_event.is_set()):
                    meter = meter_read(meter_fn)
                    queue_state = meter.get("queue", {})
                    running = int(queue_state.get("running", 0) or 0)
                    running_files = any(
                        (Path(d) / "RUNNING").is_dir() and
                        any(p.is_file() or p.is_symlink()
                            for p in (Path(d) / "RUNNING").rglob("*"))
                        for d in item_dirs
                    )
                    if running == 0 and not running_files:
                        try:
                            require_no_pending_todo_sources(item_dirs)
                        except RuntimeError:
                            blocked = getattr(ctx, "_queue_claim_blocked_event", None)
                            if blocked is not None:
                                blocked.set()
                            raise
                # 若無可派發任務：teardown 已設定 stop_event 時才收尾
                if stop_event.is_set():
                    #if not pick_next_prompts(item_dirs, per_round_limit=1):
                    if not pick_and_claim_next_prompts(item_dirs, per_round_limit=1):
                        # A safe claim can be blocked by a basename collision,
                        # an in-flight RUNNING target, filesystem restrictions,
                        # or an interrupted prior operation. Never report the
                        # consumer as drained while actual TODO sources remain.
                        require_no_pending_todo_sources(item_dirs)
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
                    queue_claim_event_id=claimed_evidence.get(pf, ""),
                    **_llm_call_audit_kwargs(ctx),
                ))

            dispatched_n = len(DTBJobs)
            if dispatched_n == 0:
                time.sleep(0.2)
                continue

            round_timed_out = False
            try:
                MPresult = _run_legacy_leaf_round(ctx, DTBJobs)
                ok_prompt_files = set()
                
                for ret in MPresult or []:
                    if isinstance(ret, dict) and ret.get("ok"):
                        pf0 = str(ret.get("prompt_file", ""))
                        if pf0:
                            ok_prompt_files.add(_canon_path(pf0))
            except BatchRunTimeout as ex:
                round_timed_out = True
                MPresult = []
                _audit_consumer_orchestration_failure(ctx, "CONSUMER_ROUND_TIMEOUT")
                tlog_warn(
                    f"⏱️ LLM 批次超時：{ex}；將本輪仍在 RUNNING 的切片退回 TODO，避免派工永久卡住。"
                )
            except Exception as ex:
                # 不讓整輪報廢；把本輪仍在 RUNNING 的切片退回 TODO，下一輪再吃。
                round_timed_out = True
                MPresult = []
                _audit_consumer_orchestration_failure(ctx, "CONSUMER_ROUND_EXCEPTION")
                tlog_warn(f"❌ run_round 例外：{ex}；將本輪 RUNNING 切片退回 TODO 後重試")
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
                    if round_timed_out or restart_event.is_set():
                        # 批次已被硬超時中止（或 watchdog 要求熱重啟）：
                        # 把仍卡在 RUNNING 的切片原子移回 TODO，並回補 meter，
                        # 下一輪可重新派工，不會永遠顯示 queue.running > 0。
                        try:
                            todo_dst = _to_todo(pf)
                            os.replace(pf, todo_dst)
                            # Only after the explicit timeout/restart requeue;
                            # never infer retries from error text or basenames.
                            try:
                                record_queue_transition(todo_dst, "requeued", previous_path=pf)
                            except Exception:
                                pass
                        except FileNotFoundError:
                            pass
                        except Exception as ex:
                            tlog_warn(f"⚠️ RUNNING→TODO 退回失敗：{pf}: {ex}")
                            still_running.append((pf, item))
                            continue
                        requeued.append((pf, item))
                    else:
                        # ✅ 仍在 RUNNING：表示這輪可能還沒寫完/或 job 卡住
                        still_running.append((pf, item))
                elif os.path.exists(todo):
                    # ✅ 退回 TODO（例如 retry/split 或 exception 退回）：要把 pending 加回來
                    requeued.append((pf, item))
                else:
                    if _canon_path(pf) in ok_prompt_files:
                        # worker 明確成功，只是 RUNNING 檔已被 proc/merge 移除
                        done.append((pf, item))
                    else:
                        tlog_warn(f"[consumer] prompt vanished but worker not ok; keep running: {pf}")
                        still_running.append((pf, item))
            
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
        _audit_consumer_orchestration_failure(ctx, "CONSUMER_TERMINATED")
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
        # worker job 需要可 pickle 的純文字 task；mapping(dict 含 lambda) 會在 MP 序列化時失敗。
        # 先找 ctx.taskSetting；若 ES/CLI ctx 沒帶 taskSetting，回退到全域 taskSetting。
        task_pools = []
        ctx_task_setting = getattr(ctx, "taskSetting", None)
        if isinstance(ctx_task_setting, Mapping):
            task_pools.append(ctx_task_setting)
        if isinstance(taskSetting, Mapping) and taskSetting is not ctx_task_setting:
            task_pools.append(taskSetting)

        found_key = ""
        ct_name = str(task_override.get("CT_name", "")).strip()
        for pool in task_pools:
            for k, v in pool.items():
                if v is task_override:
                    found_key = str(k)
                    break
            if found_key:
                break
            for k, v in pool.items():
                if isinstance(v, Mapping) and str(v.get("CT_name", "")).strip() == ct_name and ct_name:
                    found_key = str(k)
                    break
            if found_key:
                break

        if found_key:
            effective_task = found_key
        else:
            mapped_task = task_override.get("task", task_override.get("prompt", task_override.get("template", "")))
            effective_task = (
                str(mapped_task).strip()
                or ct_name
                or str(task_override)
            )

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


def _ctx_task_pool(ctx):
    pool = getattr(ctx, "taskSetting", None)
    return pool if isinstance(pool, Mapping) else taskSetting


def _render_task_mapping_prompt(task_spec: Mapping, content: str, ctx) -> str:
    tpl = task_spec.get("template")
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
    mapped_task = task_spec.get("task", task_spec.get("prompt", ""))
    if isinstance(mapped_task, str) and mapped_task.strip():
        mapped_name = mapped_task.strip()
        pool = _ctx_task_pool(ctx)
        if isinstance(pool, Mapping) and mapped_name in pool and pool[mapped_name] is not task_spec:
            nested_spec = pool[mapped_name]
            if isinstance(nested_spec, Mapping):
                return _render_task_mapping_prompt(nested_spec, content, ctx)
            return _render_raw_task_prompt(str(nested_spec or "").strip(), content)
        if mapped_name in taskSetting and taskSetting[mapped_name] is not task_spec:
            return generate_prompt(
                content=content,
                keyConsiderations=getattr(ctx, "keyConsiderations", ""),
                MainFileName=getattr(ctx, "main_file_name", ""),
                task=mapped_name,
                think_mode=getattr(ctx, "think_mode", True),
            )
        return _render_raw_task_prompt(mapped_name, content)
    return content


def render_stage_task_prompt(stage_task, content: str, ctx) -> str:
    """
    將 stage task 套用到文字內容，產生真正要放入 TODO 的 prompt 文字。
    """
    task_pool = _ctx_task_pool(ctx)
    if isinstance(stage_task, Mapping):
        return _render_task_mapping_prompt(stage_task, content, ctx)

    task_name = str(stage_task or "").strip()
    if task_name and isinstance(task_pool, Mapping) and task_name in task_pool:
        task_spec = task_pool[task_name]
        if isinstance(task_spec, Mapping):
            return _render_task_mapping_prompt(task_spec, content, ctx)
        return _render_raw_task_prompt(str(task_spec or "").strip(), content)
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


def _build_stage_prompt_text(stage_task, content: str, ctx) -> str:
    """Compatibility surface; delegate to the public authoritative renderer."""
    return render_stage_task_prompt(stage_task, content, ctx)


def _extract_renderer_task_dependencies(stage_task, ctx):
    """Resolve only entries the renderer can actually reach, without rendering.

    Stage task mappings can be aliases. Hashing just {"task": "alias"} misses
    changed ctx.taskSetting["alias"] (and any further alias mapping). Mirror
    _render_task_mapping_prompt's lookup precedence and stop on cycles.
    """
    pool = _ctx_task_pool(ctx)
    seen = set()

    def mapping_dependency(spec):
        if id(spec) in seen:
            raise ValueError("cyclic extract task-setting aliases")
        seen.add(id(spec))
        try:
            if callable(spec.get("template")):
                return {"mapping": spec, "mode": "callable"}
            mapped = spec.get("task", spec.get("prompt", ""))
            if isinstance(mapped, str) and mapped.strip():
                name = mapped.strip()
                if isinstance(pool, Mapping) and name in pool and pool[name] is not spec:
                    nested = pool[name]
                    if isinstance(nested, Mapping):
                        return {"mapping": spec, "alias": name,
                                "resolved": mapping_dependency(nested)}
                    return {"mapping": spec, "alias": name,
                            "raw": str(nested or "").strip()}
                if name in taskSetting and taskSetting[name] is not spec:
                    return {"mapping": spec, "global_key": name,
                            "global_setting": taskSetting[name]}
            return {"mapping": spec}
        finally:
            seen.remove(id(spec))

    if isinstance(stage_task, Mapping):
        return mapping_dependency(stage_task)

    name = str(stage_task or "").strip()
    if name and isinstance(pool, Mapping) and name in pool:
        spec = pool[name]
        if isinstance(spec, Mapping):
            return {"key": name, "resolved": mapping_dependency(spec)}
        return {"key": name, "raw": str(spec or "").strip()}
    if name and name in taskSetting:
        return {"key": name, "global_setting": taskSetting[name]}
    return {"raw": name}


def _extract_global_prompt_fallback(renderer_dependencies, ctx):
    """Fingerprint implicit global inputs that generate_prompt actually reads.

    The legacy generate_prompt() routine chooses MainFileName first, then risk
    criteria (from ctx or the interactive process-global fallback), and only
    then the CLASS EXT / CLASS Diff EXT branches. Do not call input() as part
    of resume verification; missing process-global values must fail closed.
    """
    dependency = renderer_dependencies
    while isinstance(dependency, Mapping):
        if "global_setting" in dependency:
            task_name = dependency.get("global_key", dependency.get("key", ""))
            setting = dependency["global_setting"]
            template = setting.get("template") if isinstance(setting, Mapping) else None
            if not callable(template):
                raise ValueError("global extract task has no fingerprintable template")
            try:
                source = inspect.getsource(template)
            except (OSError, TypeError) as exc:
                raise ValueError(
                    "cannot verify global extract task prompt fallback"
                ) from exc
            # Match generate_prompt's mutually exclusive source/branch order.
            if "主檔名" in source:
                return None
            if "風險關注指標" in source or "風險等級與說明" in source:
                if getattr(ctx, "keyConsiderations", "") != "":
                    return None
                resolved = getattr(_job_config, "keyConsiderations", None)
                if not isinstance(resolved, str) or not resolved:
                    raise ValueError(
                        "unresolved risk criteria fallback; provide explicit "
                        "ctx.keyConsiderations before extract resume"
                    )
                return {"keyConsiderations": resolved}
            if task_name in {"CLASS EXT", "CLASS Diff EXT"}:
                text_class = getattr(_job_config, "textClass", None)
                if not isinstance(text_class, str):
                    raise ValueError(
                        "unresolved classification criteria fallback: textClass"
                    )
                resolved = {"textClass": text_class}
                if task_name == "CLASS Diff EXT":
                    excluded = getattr(_job_config, "exclusiveTextClass", None)
                    if not isinstance(excluded, str):
                        raise ValueError(
                            "unresolved classification criteria fallback: exclusiveTextClass"
                        )
                    resolved["exclusiveTextClass"] = excluded
                return resolved
            return None
        dependency = dependency.get("resolved")
    return None

def _extract_stage_provenance_fingerprint(stage_task, ctx) -> str:
    """Bind the scoped extract's task AND prompt-affecting renderer context.

    Even when every source slice is already Success, a changed renderer
    configuration must invalidate cached output *before* the zero-TODO
    fast path. The manifest stores only this digest, never prompt contents.
    """
    model_spec = getattr(ctx, "model_spec", None)
    if model_spec is None:
        model_spec = {}
    if not isinstance(model_spec, Mapping):
        raise ValueError("extract model_spec must be a mapping for provenance")
    renderer_dependencies = _extract_renderer_task_dependencies(stage_task, ctx)
    return fingerprint_task({
        "stage_task": stage_task,
        "renderer_dependencies": renderer_dependencies,
        # Hash only the resolved fallback criterion for global risk templates.
        # Never persist the raw criteria or invoke interactive input() here.
        "resolved_global_prompt_inputs": _extract_global_prompt_fallback(
            renderer_dependencies, ctx,
        ),
        # CallLLMAPI finalizes the dispatched user prompt using these values.
        # Persist only their combined digest, NEVER model_spec (API credentials).
        # Include them even for the zero-TODO all-Success resume fast path.
        "dispatch_finalization": {
            "model_name": str(model_spec.get("model_name", "") or ""),
            "no_think_suffix": model_spec.get("no_think_suffix"),
        },
        "render_context": {
            "keyConsiderations": getattr(ctx, "keyConsiderations", ""),
            "think_mode": getattr(ctx, "think_mode", True),
            "main_file_name": getattr(ctx, "main_file_name", ""),
            "initial_task": getattr(ctx, "task", ""),
        },
    })


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


def _original_source_manifest_path(item: str) -> Path:
    """Durable *hash-only* source identity outside resettable stage snapshots."""
    return Path(item) / "_extract_slice_identity" / "source" / "original.json"


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


def _drop_resumed_todo_by_success(item: str, ctx=None, *, require_prompt_identity=False) -> int:
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
            if require_prompt_identity:
                # Success stores an output; a basename or mtime cannot prove
                # that output belongs to the current generated input prompt.
                current_hash = digest_text(todo_fp.read_text(encoding="utf-8"))
                reuse = valid_success(item, todo_fp.name, current_hash)
            else:
                same_hash = (_file_sha1(succ_fp) == _file_sha1(todo_fp))
                reuse = same_hash or (succ_fp.stat().st_mtime >= todo_fp.stat().st_mtime)
            if reuse:
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


def _apply_resume_policy_multistage(
    policy: str, prompt_items: list[str], ops: MergeOps, ctx=None,
    *, require_prompt_identity=False,
):
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
            _drop_resumed_todo_by_success(
                item, ctx=ctx, require_prompt_identity=require_prompt_identity,
            )
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


def _has_explicit_stage_flow(ctx) -> bool:
    return bool(_explicit_stage_flow(ctx))

def _single_extract_stage_writeback_enabled(stage_defs, ctx) -> bool:
    """Limit the legacy JSON-merge compatibility path to one extract stage."""
    return (
        len(stage_defs) == 1
        and stage_defs[0].name == "extract"
        and should_merge_slices(ctx)
        and any(
            isinstance(rule, dict)
            and str(rule.get("source", rule.get("sql_writeback_source", "")) or "").strip().lower() == "stage"
            and str(rule.get("stage", rule.get("sql_writeback_stage", "")) or "").strip() == "extract"
            for rule in (getattr(ctx, "sql_writeback_rules", None) or [])
        )
    )


def _expected_single_extract_slice_files(prompt_items: list[str]) -> dict[str, dict[str, str]]:
    """Freeze current member names and hashes before resume prunes TODO.

    TODO takes precedence over RUNNING for same names. Historical Success
    does not establish current input identity.
    """
    expected: dict[str, dict[str, str]] = {}
    for item in prompt_items:
        members: dict[str, str] = {}
        for directory in ("RUNNING", "TODO"):
            for fp in _root_txt_files(os.path.join(item, directory)):
                members[fp.name] = digest_text(fp.read_text(encoding="utf-8"))
        expected[item] = include_committed_split_roots(item, members)
    return expected


def _restore_single_extract_full_restart_parents(
    prompt_items: list[str], ctx, stage_def,
) -> None:
    """Rebuild committed split roots *before* full_restart clears Success.

    Stage-source SQL/Excel rows can reproduce the original dispatched parent
    prompt. Verify its fingerprint first, and fail without deleting any
    Success data if exact reconstruction is unavailable.
    """
    plans: list[tuple[str, str, str, str]] = []
    configured = next(
        (s for s in (getattr(ctx, "stages", None) or [])
         if isinstance(s, dict) and s.get("name") == stage_def.name),
        {},
    )
    input_col = str(configured.get("input_col") or getattr(ctx, "input_col", "") or "")
    sources = getattr(ctx, "stage_source_inputs", None) or {}
    for item in prompt_items:
        expected = _expected_single_extract_slice_files([item])[item]
        queued = {
            fp.name
            for subdir in ("TODO", "RUNNING")
            for fp in _root_txt_files(os.path.join(item, subdir))
        }
        # Full restart is deliberately distinct from ordinary resume:
        # a committed split can have *no* queued descendant once every
        # child has finished. Read the durable top-level parent identities,
        # but accept one only when the freshly rendered current source
        # matches its exact saved prompt hash.
        parents = committed_split_parent_identities(item)
        for name, prompt_hash in expected.items():
            if name not in queued and name not in parents:
                raise RuntimeError("full_restart missing committed split parent identity")
        for name, prompt_hash in parents.items():
            if name in expected and expected[name] != prompt_hash:
                raise RuntimeError("full_restart conflicting split parent identity")
        for name, prompt_hash in {**expected, **parents}.items():
            if name in queued:
                continue
            # Clear Success only *after* the original split parent can
            # be reconstructed from a verified current source.
            if not input_col or input_col not in sources:
                raise RuntimeError(
                    "full_restart cannot safely rebuild split parent: "
                    "current stage source is missing"
                )
            reconstructed = _build_stage_prompt_text(
                stage_def.task, str(sources[input_col] or ""), ctx,
            )
            if digest_text(reconstructed) != prompt_hash:
                raise RuntimeError(
                    "full_restart cannot safely rebuild split parent: "
                    "source does not match the saved prompt identity"
                )
            plans.append((item, name, reconstructed, prompt_hash))

    # Prevalidate every row before mutating any input queue or Success tree.
    for item, name, reconstructed, prompt_hash in plans:
        restore_full_restart_parent(item, name, reconstructed, prompt_hash)


def _require_complete_single_extract_stage(report, runtime, prompt_items, expected_files) -> None:
    """Check every current prompt or its verified recursive retry children.

    Both output and prompt SHA-256 hashes are verified. Any missing success,
    stale same-name output, or incomplete split fails before snapshot creation.
    """
    finished = int((report.get("final") or {}).get("finished_chunks", 0))
    if not runtime or len(runtime) != len(prompt_items) or finished != len(runtime):
        raise RuntimeError("extract stage incomplete: not every input unit finished")
    selected: dict[str, list[str]] = {}
    for item in prompt_items:
        chunk = runtime.get(item)
        status = chunk.stages.get("extract") if chunk is not None else None
        if status is None or status.state != "success":
            raise RuntimeError("extract stage incomplete: an input unit failed")
        expected = expected_files.get(item)
        if not expected:
            raise RuntimeError("extract stage incomplete: missing expected current input slices")
        leaves: list[str] = []
        try:
            for name, prompt_hash in expected.items():
                leaves.extend(resolve_success_leaves(item, name, prompt_hash))
        except (ValueError, OSError) as exc:
            raise RuntimeError(
                "extract stage incomplete: missing or mismatched Success slice coverage"
            ) from exc
        if len(leaves) != len(set(leaves)):
            raise RuntimeError("extract stage incomplete: overlapping split lineage")
        selected[item] = leaves

    # All inputs validated before touching any stage snapshot.
    for item in prompt_items:
        snapshot = _snapshot_dir(item, "extract")
        MKDIR(snapshot)
        _clear_txt_files(snapshot, MergeOps())
        for name in selected[item]:
            shutil.copy2(
                os.path.join(item, "Success", name),
                os.path.join(snapshot, name),
            )


def _merge_single_extract_stage_json_parts(parts: list[str], ctx) -> str:
    """Apply legacy JSON slice merge to one extract-stage writeback artifact.

    Only called for the one-stage extract compatibility path with explicit
    stage writeback and merge_slices enabled. Validate every slice before
    materializing a stage manifest so malformed/partial input cannot silently
    become a writeback-ready concatenation of JSON documents.
    """
    if not parts:
        raise ValueError("extract stage JSON slices are missing")
    rows = []
    for index, text in enumerate(parts):
        try:
            value = json.loads(text)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"extract stage JSON slice {index} is invalid") from exc
        if isinstance(value, dict):
            rows.append(value)
        elif isinstance(value, list) and all(isinstance(row, dict) for row in value):
            rows.extend(value)
        else:
            raise ValueError(f"extract stage JSON slice {index} must contain dicts")

    if len(parts) == 1:
        # Match legacy behavior: one JSON-list slice keeps its list envelope.
        return parts[0]
    if not rows:
        return "[]"
    if needs_per_output_slice_merge(ctx, source="stage"):
        # One stage artifact cannot simultaneously represent generic Event IDs
        # and rewritten strict references. Keep the original slice records for
        # Row Merger's per-destination semantic merge.
        return json.dumps(rows, ensure_ascii=False, indent=2)
    merged, _report = merge_dict_slices_audited(
        rows,
        conflict_policy=str(getattr(ctx, "merge_conflict_policy", "prefer_left")),
        dedup_lists=bool(getattr(ctx, "merge_dedup_lists", True)),
        audit=bool(getattr(ctx, "merge_log_changes", True)),
        logger=None,
        max_log=int(getattr(ctx, "merge_max_log", 10)),
        multidim_event=is_multidim_event_source_merge(ctx, source="stage"),
    )
    # Stage-sourced writeback is not wrapped by Row Merger's combined-source
    # compatibility path. Preserve the ES article array envelope here.
    payload = [merged] if is_multidim_event_source_merge(ctx, source="stage") else merged
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _rebuild_full_restart_from_verified_source(
    prompt_items: list[str], ctx, file_path: str, stage_def,
) -> set[str]:
    """Prepare current task prompts before destructive full_restart cleanup.

    For workspaces with durable original-source provenance, the entire
    current source must still match its saved A/B boundaries. Unlike resume,
    an explicit full restart is allowed to change the effective extract task;
    old Success and dispatch fingerprints are no longer reusable.
    """
    plans: list[tuple[str, Path, dict, list[tuple[str, str]]]] = []
    for item in prompt_items:
        marker = _original_source_manifest_path(item)
        if not marker.exists():
            continue
        saved = robust_json_read(str(marker))
        names = saved.get("names") if isinstance(saved, dict) else None
        parts_hash = saved.get("part_sha256") if isinstance(saved, dict) else None
        if not (
            isinstance(saved, dict) and saved.get("version") == 1
            and isinstance(names, list) and len(names) > 0
            and len(set(names)) == len(names)
            and all(isinstance(n, str) and n.endswith(".txt")
                    and Path(n).name == n for n in names)
            and isinstance(parts_hash, list) and len(parts_hash) == len(names)
        ):
            raise RuntimeError("full_restart invalid saved original source identity")
        try:
            source = Path(file_path).read_text(encoding="utf-8")
            pieces = list(TokenizerWrapper(
                model_name=getattr(ctx, "model_spec_name", ""),
                task=getattr(ctx, "task", ""),
            ).tokenize(
                text=source, adjust=True,
                max_tokens=getattr(ctx, "max_tokens", 12000),
            ).get("ctxCut", []))
        except (OSError, UnicodeError, ValueError) as exc:
            raise RuntimeError("full_restart cannot verify current raw input") from exc
        if (
            saved.get("source_sha256") != digest_text(source)
            or len(pieces) != len(names)
            or [digest_text(str(part)) for part in pieces] != parts_hash
        ):
            raise RuntimeError(
                "full_restart original source has changed; keep old Success"
            )
        rebuilt = [
            (name, _build_stage_prompt_text(stage_def.task, str(piece), ctx))
            for name, piece in zip(names, pieces)
        ]
        plans.append((item, marker, saved, rebuilt))

    # The plan for every affected item is fully validated before changing a
    # single Success file or existing TODO. Keep the original queue usable
    # until each new prompt has been staged and fsynced.
    for item, marker, saved, rebuilt in plans:
        todo_dir = Path(item) / "TODO"
        todo_dir.mkdir(parents=True, exist_ok=True)
        stage_dir = Path(item) / "_extract_slice_identity" / "restart_staging" / uuid.uuid4().hex
        stage_dir.mkdir(parents=True, exist_ok=False)
        try:
            for name, prompt in rebuilt:
                file = stage_dir / name
                with file.open("w", encoding="utf-8", newline="") as handle:
                    handle.write(prompt)
                    handle.flush()
                    os.fsync(handle.fileno())
            for fp in _root_txt_files(str(todo_dir)):
                fp.unlink()
            for name, _prompt in rebuilt:
                os.replace(stage_dir / name, todo_dir / name)
        finally:
            shutil.rmtree(stage_dir, ignore_errors=True)
        # All retried descendants belonged to the previous task. Their
        # old intent is not a valid lineage for fresh original source roots.
        split_dir = Path(item) / "_extract_slice_identity" / "splits"
        if split_dir.is_dir():
            shutil.rmtree(split_dir)
        saved.pop("dispatch_sha256", None)
        saved.pop("stage_task_sha256", None)
        # Full restart intentionally replaces every original TODO prompt;
        # reset its pre-dispatch identity to the newly verified source render.
        saved["initial_prompt_sha256"] = {
            name: digest_text(prompt) for name, prompt in rebuilt
        }
        atomic_write_json(str(marker), saved)
    return {item for item, _marker, _saved, _rebuilt in plans}


def process_prompt_and_merge_multistage(ctx, file_path: str, ops: MergeOps | None = None, max_rounds: int = 20) -> str:
    from czjLLM.reduction.production_control import raise_if_execution_cancelled
    raise_if_execution_cancelled(ctx)
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
    stage_defs = resolve_pipeline_stages(ctx)
    single_extract_stage_writeback = _single_extract_stage_writeback_enabled(stage_defs, ctx)
    if single_extract_stage_writeback:
        # No single-extract policy may render prompts or reconcile/move queue
        # files until its effective renderer is proven fingerprintable. Fresh
        # and resume paths can also hit input(), open(), breakpoint(), or
        # untracked globals before the later first-dispatch provenance write.
        # This is a read-only preflight for resume, smart_reset, full_restart.
        _extract_stage_provenance_fingerprint(stage_defs[0].task, ctx)
        # Full restart must first regenerate completed split branches from
        # the current source. Otherwise clearing Success loses their prompts.
        if resume_policy == "full_restart":
            # The later resume-policy step would otherwise move stale RUNNING
            # prompts into TODO *after* the fresh source prompts were staged,
            # overwriting them via os.replace(). Recover the queue first.
            recover_running_to_todo(prompt_items)
            restored = _rebuild_full_restart_from_verified_source(
                prompt_items, ctx, file_path, stage_defs[0],
            )
            remaining = [item for item in prompt_items if item not in restored]
            if remaining:
                _restore_single_extract_full_restart_parents(
                    remaining, ctx, stage_defs[0],
                )
        # Journal reconciliation must precede input-membership capture.
        # An interrupted split can otherwise surface parent and children as
        # independent roots and duplicate SQL/Excel writeback content.
        for item in prompt_items:
            reconcile_split_transitions(item)
    expected_extract_files = (
        _expected_single_extract_slice_files(prompt_items)
        if single_extract_stage_writeback else {}
    )
    _apply_resume_policy_multistage(
        resume_policy, prompt_items, ops, ctx=ctx,
        require_prompt_identity=single_extract_stage_writeback,
    )

    runtime = init_chunk_stage_runtime(ctx, prompt_items)
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
        """Build or validate durable raw slices for effective-task rerendering.

        A partial resume can have only B in TODO after A reached Success.
        Preserve the A/B source-to-basename mapping recorded *before* dispatch;
        do not remap a surviving B to source chunk A or turn prompt copies
        into trusted source fragments.
        """
        root_files = _root_txt_files(ops.join(item, "TODO"))
        snapshot_dir = Path(_snapshot_dir(item, "original"))
        manifest_path = _original_source_manifest_path(item)
        try:
            with open(file_path, "r", encoding="utf-8") as handle:
                source_text = handle.read()
            tokenizer = TokenizerWrapper(
                model_name=getattr(ctx, "model_spec_name", ""),
                task=getattr(ctx, "task", ""),
            )
            chunks = tokenizer.tokenize(
                text=source_text, adjust=True,
                max_tokens=getattr(ctx, "max_tokens", 12000),
            )
            source_parts = list(chunks.get("ctxCut", []))
        except Exception:
            if single_extract_stage_writeback and manifest_path.exists():
                raise RuntimeError("cannot verify saved raw slices against current source")
            return False

        if not source_parts:
            return False
        source_hash = digest_text(source_text)
        part_hashes = [digest_text(str(part)) for part in source_parts]
        todo_names = {fp.name for fp in root_files}

        if not single_extract_stage_writeback:
            # The durable hash-only source manifest is solely for Issue #211's
            # single-extract writeback path. Normal multistage jobs must follow
            # their pre-existing source snapshot lifecycle; a stale marker left
            # by a previous run must never pin them to old stage inputs.
            if len(source_parts) != len(root_files):
                return False
            MKDIR(str(snapshot_dir))
            _clear_txt_files(str(snapshot_dir), ops)
            for fp, part in zip(root_files, source_parts):
                with (snapshot_dir / fp.name).open(
                    "w", encoding="utf-8", newline=""
                ) as handle:
                    handle.write(str(part))
            return True

        if manifest_path.exists():
            # A saved snapshot is authoritative only if current source and
            # EVERY on-disk raw slice still match the committed identity.
            # Never silently overwrite a stale manifest or adopt a prompt
            # copy as a raw source slice on resume.
            saved = robust_json_read(str(manifest_path))
            names = saved.get("names") if isinstance(saved, dict) else None
            valid = (
                isinstance(saved, dict)
                and saved.get("version") == 1
                and saved.get("source_sha256") == source_hash
                and isinstance(names, list)
                and len(names) == len(source_parts)
                and len(set(names)) == len(names)
                and all(isinstance(name, str) and name.endswith(".txt")
                        and Path(name).name == name for name in names)
                and saved.get("part_sha256") == part_hashes
                and all(
                    name in set(names)
                    or is_verified_queued_split_child(
                        item, name,
                        (Path(item) / "TODO" / name).read_text(encoding="utf-8"),
                    )
                    for name in todo_names
                )
            )
            if valid:
                if not snapshot_dir.exists() and resume_policy in {"smart_reset", "full_restart"}:
                    # The reset intentionally removed volatile stage snapshots,
                    # not the durable hash-only identity. Reconstitute raw
                    # fragments solely from source parts verified above.
                    MKDIR(str(snapshot_dir))
                    for name, part in zip(names, source_parts):
                        dest = snapshot_dir / name
                        staged = snapshot_dir / (name + ".pending")
                        try:
                            with open(staged, "w", encoding="utf-8", newline="") as handle:
                                handle.write(str(part))
                                handle.flush()
                                os.fsync(handle.fileno())
                            os.replace(staged, dest)
                        finally:
                            staged.unlink(missing_ok=True)
                valid = all(
                    (snapshot_dir / name).is_file()
                    and digest_text((snapshot_dir / name).read_text(encoding="utf-8")) == part_hashes[index]
                    for index, name in enumerate(names)
                )
            if valid and resume_policy != "full_restart":
                # A crash can occur after committing the source manifest but
                # before the runner records any dispatch_sha256. Do not adopt
                # the first matching-name TODO as trusted without validating
                # the prompt bytes committed at the source boundary.
                prior_dispatch = saved.get("dispatch_sha256", {})
                initial_prompts = saved.get("initial_prompt_sha256", {})
                if not isinstance(prior_dispatch, dict) or not isinstance(initial_prompts, dict):
                    raise RuntimeError("invalid saved original prompt provenance")
                for index, name in enumerate(names):
                    queued = Path(item) / "TODO" / name
                    if name in prior_dispatch:
                        continue
                    if not queued.is_file():
                        # A verified source member with no dispatch record
                        # cannot vanish: otherwise the surviving subset could
                        # be merged as a complete SQLite/Excel result.
                        raise RuntimeError(
                            "missing undispatched extract source member: " + name
                        )
                    initial_hash = initial_prompts.get(name)
                    if not isinstance(initial_hash, str) or len(initial_hash) != 64:
                        raise RuntimeError(
                            "missing initial extract queued prompt provenance; full_restart required"
                        )
                    observed = digest_text(queued.read_text(encoding="utf-8"))
                    if observed != initial_hash:
                        # An interrupted task override may already have
                        # replaced the generator's prompt with a deterministic
                        # stage prompt before the first dispatch manifest write.
                        # Accept only exact rerendering from verified raw input.
                        expected = _build_stage_prompt_text(
                            stage_defs[0].task, str(source_parts[index]), ctx,
                        )
                        if observed != digest_text(expected):
                            raise RuntimeError(
                                "saved initial extract queued prompt changed since source snapshot"
                            )
            if not valid:
                if single_extract_stage_writeback:
                    raise RuntimeError(
                        "saved original source-slice provenance mismatches current source or queue"
                    )
                return False
            return True

        # First attempt: all original prompts must still be queued and the
        # full mapping is captured BEFORE any first-stage LLM call.
        if len(source_parts) != len(root_files):
            if single_extract_stage_writeback and _root_txt_files(
                ops.join(item, "Success")
            ):
                raise RuntimeError(
                    "cannot reconstruct all source slices for partial Success without provenance"
                )
            return False

        names = [fp.name for fp in root_files]
        MKDIR(str(snapshot_dir))
        _clear_txt_files(str(snapshot_dir), ops)
        for name, text_piece in zip(names, source_parts):
            dst = snapshot_dir / name
            # Per-file temp + replace ensures a crashed first attempt cannot
            # expose truncated raw fragments with an apparently valid manifest.
            staged = snapshot_dir / (name + ".pending")
            try:
                with open(staged, "w", encoding="utf-8", newline="") as handle:
                    handle.write(str(text_piece))
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(staged, dst)
            finally:
                if staged.exists():
                    staged.unlink()
        # Persist first-queued prompt hashes in the SAME atomic transaction
        # as source membership. A crash before the first dispatch fingerprint
        # can then never adopt a tampered TODO as its original identity.
        initial_prompts = {
            fp.name: digest_text(fp.read_text(encoding="utf-8"))
            for fp in root_files
        }
        atomic_write_json(
            str(manifest_path),
            {"version": 1, "source_sha256": source_hash,
             "names": names, "part_sha256": part_hashes,
             "initial_prompt_sha256": initial_prompts},
        )
        return True

    # Raw-source snapshots remain valid when some prompts have moved from
    # TODO into Success. Only fall back to copied prompt snapshots for old
    # non-source flows; a persisted provenance manifest is never overwritten
    # with prompt text merely because the current TODO count is smaller.
    source_slice_verified: dict[str, bool] = {}
    for item in prompt_items:
        from_source = _write_original_snapshot_from_source(item)
        source_slice_verified[item] = from_source
        if not from_source:
            marker = _original_source_manifest_path(item)
            if not single_extract_stage_writeback:
                # Non-single-extract multistage inputs may have been freshly
                # regenerated with different counts or changed source.
                # Never let an unrelated legacy marker suppress fallback.
                _clear_txt_files(_snapshot_dir(item, "original"), ops)
                _copy_root_todo_txts(ops.join(item, "TODO"), _snapshot_dir(item, "original"))
            elif not marker.exists():
                _copy_root_todo_txts(ops.join(item, "TODO"), _snapshot_dir(item, "original"))

    # Recover the full frozen input identity after a partial resume. A verified
    # Success A no longer has a TODO file, but it still belongs to this
    # extract's A+B source. The dispatch hashes were committed before the LLM
    # call, and source-slice hashes were just independently revalidated.
    if single_extract_stage_writeback:
        for item in prompt_items:
            if not source_slice_verified.get(item, False):
                continue
            manifest = robust_json_read(str(_original_source_manifest_path(item)))
            dispatched = manifest.get("dispatch_sha256", {})
            if not dispatched:
                continue
            expected_stage = _extract_stage_provenance_fingerprint(stage_defs[0].task, ctx)
            if manifest.get("stage_task_sha256") != expected_stage:
                if resume_policy != "full_restart":
                    raise RuntimeError(
                        "extract stage task changed since partial Success; "
                        "explicit full_restart is required"
                    )
                # Explicit full_restart has already rebuilt every current
                # input prompt, and must not resurrect old Success coverage.
                dispatched = {}
            allowed = set(manifest.get("names", ()))
            if not isinstance(dispatched, dict) or not set(dispatched).issubset(allowed):
                raise RuntimeError("invalid saved extract dispatch provenance")
            for name, recorded_hash in dispatched.items():
                if not isinstance(recorded_hash, str) or len(recorded_hash) != 64:
                    raise RuntimeError("invalid saved extract dispatch digest")
                if name not in expected_extract_files[item]:
                    # Completed members remain mandatory; the final Success
                    # coverage gate verifies prompt AND output SHA-256.
                    expected_extract_files[item][name] = recorded_hash

    def _refresh_stage_prompt_metrics(root_todo_dir: str, filename: str, task_text: str, prompt_text: str, stage_identity: str):
        # The worker claims root TODO/<basename> into RUNNING/<basename>.
        # Refresh metadata against that logical prompt basename so every stage
        # gets the metrics for the prompt actually dispatched.
        logical_prompt = os.path.join(root_todo_dir, filename)
        write_prompt_component_metrics(
            logical_prompt,
            task_text,
            prompt_text,
            model_name=getattr(ctx, "model_spec_name", "") or "",
            model_spec=getattr(ctx, "model_spec", None),
            task=str(getattr(ctx, "task", "") or ""),
            stage_identity=stage_identity,
            quiet=bool(getattr(ctx, "suppress_prompt_diagnostics", False)),
        )

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
        anchor_files = _root_txt_files(root_todo_dir)
        if not anchor_files:
            # 在多階段中，前一階段可能已清空 root TODO；此時回退用 original 快照作為切片錨點。
            anchor_files = _root_txt_files(_snapshot_dir(item, "original"))
        if stage_input_col and stage_input_col in stage_source_inputs:
            src_text = str(stage_source_inputs.get(stage_input_col, "") or "")
            MKDIR(todo_dir)
            _clear_txt_files(todo_dir, ops)
            # In the scoped single-extract JSON writeback flow the producer
            # already rendered each initial input slice using extract's task.
            # Rerendering *every* slice from the entire primary SQL/Excel
            # source collapses N distinct prompts to N full-row duplicates.
            # Keep the original verified slice prompt and dispatch it once.
            if (
                single_extract_stage_writeback
                and stage_name == stage_defs[0].name
                and stage_input_col == str(getattr(ctx, "input_col", "") or "").strip()
                and anchor_files
                and all(fp.parent == Path(root_todo_dir) for fp in anchor_files)
            ):
                # The generator used ctx.task; the orchestrator may resolve
                # task_key over a different fallback task. Never silently
                # reuse an initial prompt built from the wrong template.
                initial_task = getattr(ctx, "task", "")
                generated_task = (
                    taskSetting.get(initial_task, initial_task)
                    if isinstance(initial_task, str) else initial_task
                )
                if generated_task == stage_task:
                    for fp in anchor_files:
                        shutil.copy2(str(fp), os.path.join(todo_dir, fp.name))
                        relabel_prompt_token_stage(str(fp), stage_name)
                    return
                # Re-render from the real verified per-slice raw input,
                # not from the full row and not from copied prompt fallback.
                if not source_slice_verified.get(item, False):
                    raise RuntimeError(
                        "extract stage task differs from generated slice task "
                        "and original source slices cannot be verified"
                    )
                originals = Path(_snapshot_dir(item, "original"))
                for fp in anchor_files:
                    if is_verified_queued_split_child(
                        item, fp.name, fp.read_text(encoding="utf-8"),
                    ):
                        shutil.copy2(str(fp), os.path.join(todo_dir, fp.name))
                        relabel_prompt_token_stage(str(fp), stage_name)
                        continue
                    raw_slice = originals / fp.name
                    if not raw_slice.is_file():
                        raise RuntimeError(
                            "extract stage task mismatch with missing original input slice"
                        )
                    content_slice = raw_slice.read_text(encoding="utf-8")
                    effective_prompt = _build_stage_prompt_text(
                        stage_task, content_slice, ctx,
                    )
                    dst = os.path.join(todo_dir, fp.name)
                    with open(dst, "w", encoding="utf-8", newline="") as handle:
                        handle.write(effective_prompt)
                    _refresh_stage_prompt_metrics(
                        root_todo_dir, fp.name, content_slice,
                        effective_prompt, stage_name,
                    )
                return
            for fp in anchor_files:
                # A committed split's queued descendant is an already
                # rendered fragment prompt. Replacing it with the complete
                # SQL/Excel source destroys its verified split identity.
                existing_text = fp.read_text(encoding="utf-8")
                if single_extract_stage_writeback and is_verified_queued_split_child(
                    item, fp.name, existing_text,
                ):
                    prompt_text = existing_text
                else:
                    prompt_text = _build_stage_prompt_text(stage_task, src_text, ctx)
                dst_fp = os.path.join(todo_dir, fp.name)
                with open(dst_fp, "w", encoding="utf-8", newline="") as f:
                    f.write(prompt_text)
                _refresh_stage_prompt_metrics(root_todo_dir, fp.name, src_text, prompt_text, stage_name)
            return
        if (
            stage_name == stage_defs[0].name
            and effective_input_from == "original"
            and len(_root_txt_files(root_todo_dir)) > 0
        ):
            MKDIR(todo_dir)
            _clear_txt_files(todo_dir, ops)
            initial_task = getattr(ctx, "task", "")
            generated_task = (
                taskSetting.get(initial_task, initial_task)
                if isinstance(initial_task, str) else initial_task
            )
            task_mismatch = (
                single_extract_stage_writeback
                and generated_task != stage_task
            )
            if task_mismatch and not source_slice_verified.get(item, False):
                raise RuntimeError(
                    "extract stage task differs from generated slice task "
                    "and original source slices cannot be verified"
                )
            for fp in _root_txt_files(root_todo_dir):
                dst = os.path.join(todo_dir, fp.name)
                if task_mismatch:
                    if is_verified_queued_split_child(
                        item, fp.name, fp.read_text(encoding="utf-8"),
                    ):
                        shutil.copy2(str(fp), dst)
                        relabel_prompt_token_stage(str(fp), stage_name)
                        continue
                    raw = Path(_snapshot_dir(item, "original")) / fp.name
                    if not raw.is_file():
                        raise RuntimeError(
                            "extract stage task mismatch with missing original input slice"
                        )
                    source_piece = raw.read_text(encoding="utf-8")
                    effective = _build_stage_prompt_text(stage_task, source_piece, ctx)
                    with open(dst, "w", encoding="utf-8", newline="") as handle:
                        handle.write(effective)
                    _refresh_stage_prompt_metrics(
                        root_todo_dir, fp.name, source_piece, effective, stage_name,
                    )
                else:
                    shutil.copy2(str(fp), dst)
                    # Same effective task: preserve exact per-slice prompt.
                    relabel_prompt_token_stage(str(fp), stage_name)
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
            for fp in anchor_files:
                prompt_text = _build_stage_prompt_text(stage_task, "", ctx)
                dst_fp = os.path.join(todo_dir, fp.name)
                with open(dst_fp, "w", encoding="utf-8") as f:
                    f.write(prompt_text)
                _refresh_stage_prompt_metrics(root_todo_dir, fp.name, "", prompt_text, stage_name)
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
            _refresh_stage_prompt_metrics(
                root_todo_dir, os.path.basename(src_fp), source_text, prompt_text, stage_name
            )

    def _stage_task_debug_text(stage_task) -> str:
        """優先顯示 template 原文；若無法取得則回退為精簡規格。"""
        preview = task_template_preview(stage_task)
        if isinstance(stage_task, Mapping):
            if preview.strip() == str(stage_task).strip():
                compact = {}
                for k in ("CT_name", "InputCutLen"):
                    if k in stage_task:
                        compact[k] = stage_task.get(k)
                inline_task = stage_task.get("task", stage_task.get("prompt", ""))
                if isinstance(inline_task, str) and inline_task.strip():
                    compact["task"] = inline_task.strip()
                if "template" in stage_task:
                    compact["template"] = "<callable>" if callable(stage_task.get("template")) else "<unavailable>"
                return str(compact or {"task": "<mapping>"})
        return preview

    def runner(job, _ctx, _input_text=None):
        raise_if_execution_cancelled(ctx)
        if (
            single_extract_stage_writeback
            and resume_policy in {"resume", "smart_reset"}
            and not _root_txt_files(ops.join(job.chunk_id, "TODO"))
            and expected_extract_files.get(job.chunk_id)
        ):
            # A fully completed input has no pending prompts. smart_reset
            # deletes stage snapshots but intentionally keeps Success: do not
            # regenerate original slices as TODO and call the provider again.
            # Verify every saved output's prompt/output fingerprint, including
            # any recursively split descendants, before the final coverage
            # gate reconstructs the extract snapshot for stage writeback.
            for name, prompt_hash in expected_extract_files[job.chunk_id].items():
                try:
                    resolve_success_leaves(job.chunk_id, name, prompt_hash)
                except (ValueError, OSError) as exc:
                    raise RuntimeError(
                        "cannot reuse completed extract: invalid Success identity"
                    ) from exc
            return {"ok": True, "output": ""}
        if job.stage_name not in shown_stage_tasks:
            print(f"[stage:{job.stage_name}] 📝 使用任務：\n{_stage_task_debug_text(job.stage_task)}")
            shown_stage_tasks.add(job.stage_name)
        print(f"[stage:{job.stage_name}] ▶ 開始處理輸入單位(input_unit): {Path(job.chunk_id).name}")
        _prepare_todo_for_stage(job.chunk_id, job.stage_name, job.stage_task)
        _sync_stage_todo_to_root(job.chunk_id, job.stage_name, ops)
        if single_extract_stage_writeback:
            # Bind to the actually dispatched prompt, and durably retain the
            # complete original membership even after Success prunes TODO.
            current = expected_extract_files[job.chunk_id]
            raw_manifest = str(_original_source_manifest_path(job.chunk_id))
            record = robust_json_read(raw_manifest) if source_slice_verified.get(job.chunk_id) else {}
            previous = record.get("dispatch_sha256", {}) if record else {}
            if not isinstance(previous, dict):
                raise RuntimeError("invalid persisted extract dispatch provenance")
            all_sent = dict(previous)
            pending = _root_txt_files(ops.join(job.chunk_id, "TODO"))
            actual = {
                prompt_path.name: digest_text(
                    prompt_path.read_text(encoding="utf-8")
                ) for prompt_path in pending
            }
            # A source/task-identical partial resume may only dispatch the
            # *same* input for a previously recorded logical slice. Otherwise
            # a regenerated/corrupted/nondeterministic TODO can silently mix
            # A's old Success with a semantically different B.
            if resume_policy != "full_restart":
                baseline = record.get("initial_prompt_sha256", {}) if record else {}
                for name, prompt_hash in actual.items():
                    saved_hash = previous.get(name)
                    if saved_hash is not None:
                        if saved_hash != prompt_hash:
                            raise RuntimeError(
                                "extract dispatch prompt changed since previous "
                                "attempt: refuse mixed-identity partial writeback"
                            )
                    elif record and name in record.get("names", ()):
                        # Never grant a previously undispatched original TODO
                        # its first trusted hash merely because its basename
                        # belongs to a verified source-slice manifest.
                        baseline_hash = baseline.get(name) if isinstance(baseline, dict) else None
                        if not isinstance(baseline_hash, str) or len(baseline_hash) != 64:
                            raise RuntimeError("missing initial extract queued prompt provenance")
                        if prompt_hash != baseline_hash:
                            source = Path(_snapshot_dir(job.chunk_id, "original")) / name
                            if not source.is_file() or prompt_hash != digest_text(
                                _build_stage_prompt_text(
                                    job.stage_task, source.read_text(encoding="utf-8"), ctx,
                                )
                            ):
                                raise RuntimeError(
                                    "extract first dispatch prompt differs from verified source"
                                )
            for name, prompt_hash in actual.items():
                if name in current:
                    current[name] = prompt_hash
                if record and name in record.get("names", []):
                    all_sent[name] = prompt_hash
            if record:
                record["dispatch_sha256"] = all_sent
                record["stage_task_sha256"] = _extract_stage_provenance_fingerprint(stage_defs[0].task, ctx)
                atomic_write_json(raw_manifest, record)
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
        raise_if_execution_cancelled(ctx)
        _call_llm_with_task_override(
            ops,
            [job.chunk_id],
            ctx,
            allow_to_retry=True,
            task_override=job.stage_task,
            debug_print_llm_io=debug_enabled,
            debug_print_max_chars=debug_max_chars,
        )
        raise_if_execution_cancelled(ctx)
        _call_llm_with_task_override(
            ops,
            [job.chunk_id],
            ctx,
            allow_to_retry=False,
            task_override=job.stage_task,
            debug_print_llm_io=debug_enabled,
            debug_print_max_chars=debug_max_chars,
        )
        raise_if_execution_cancelled(ctx)
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

    stage_report = run_stage_pipeline(ctx, runtime, runner, max_rounds=max_rounds)
    raise_if_execution_cancelled(ctx)
    if single_extract_stage_writeback:
        _require_complete_single_extract_stage(
            stage_report, runtime, prompt_items, expected_extract_files,
        )

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
            # For the legacy-compatible *single extract stage* only, a
            # newline join is not valid JSON when multiple slices succeed.
            # Existing genuine multistage stage outputs stay unchanged.
            if single_extract_stage_writeback and stage.name == "extract":
                stage_text = _merge_single_extract_stage_json_parts(merged_parts, ctx)
            else:
                stage_text = "\n".join(merged_parts)
            with open(stage_merged_fn, "w", encoding="utf-8") as f:
                f.write(stage_text)
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

    stage_writeback_rules = [
        rule for rule in (getattr(ctx, "sql_writeback_rules", None) or [])
        if isinstance(rule, dict)
        and str(rule.get("source", rule.get("sql_writeback_source", "")) or "").strip().lower() == "stage"
    ]
    # Stage writeback can use _stage_merges/manifest.json, but keep the legacy
    # final prompt combine enabled by default because existing SQL multistage
    # deployments may rely on its side effects/output path.  Operators can opt
    # into skipping it with multistage_stage_writeback_skip_final_combine=True.
    #skip_final_combine = bool(stage_writeback_rules) and bool(
    #    getattr(ctx, "multistage_stage_writeback_skip_final_combine", False)
    #)
    skip_final_combine = bool(stage_writeback_rules)
    if skip_final_combine:
        marker_parts = []
        for entry in stage_manifest:
            merged_file = str(entry.get("merged_file", "") or "").strip()
            if not merged_file:
                continue
            merged_path = ops.join(stage_merge_root, merged_file)
            if os.path.isfile(merged_path):
                with open(merged_path, "r", encoding="utf-8") as f:
                    marker_parts.append(f.read())
        final_marker_fn = ops.join(stage_merge_root, f"{main_name}_multistage_combined.txt")
        with open(final_marker_fn, "w", encoding="utf-8") as f:
            f.write("\n".join(marker_parts))
        print(
            "[multistage] ↪ 偵測到 stage SQL writeback rules，"
            f"跳過最終 prompt combine，使用 stage manifest marker：{final_marker_fn}"
        )
        return final_marker_fn

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
    from czjLLM.reduction.production_control import raise_if_execution_cancelled
    raise_if_execution_cancelled(ctx)
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
    if len(stages) > 1 or (len(stages) == 1 and _has_explicit_stage_flow(ctx)):
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
    # 單階段（legacy）也支援 YAML 頂層 debug_print_llm_io /
    # debug_print_max_chars；多階段則由各 stage definition 覆寫。
    debug_enabled, debug_max_chars = _resolve_llm_debug_flags(
        stage_debug_enabled=bool(getattr(ctx, "debug_print_llm_io", False)),
        stage_debug_max_chars=int(getattr(ctx, "debug_print_max_chars", 2000) or 2000),
    )
    _call_llm_with_task_override(
        ops,
        prompt_items,
        ctx,
        allow_to_retry=True,
        task_override=None,
        debug_print_llm_io=debug_enabled,
        debug_print_max_chars=debug_max_chars,
    )
    raise_if_execution_cancelled(ctx)
    _call_llm_with_task_override(
        ops,
        prompt_items,
        ctx,
        allow_to_retry=False,
        task_override=None,
        debug_print_llm_io=debug_enabled,
        debug_print_max_chars=debug_max_chars,
    )
    raise_if_execution_cancelled(ctx)

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
            with open(out_fn, mode='wt', encoding='utf-8', newline='') as fw:
                fw.write(out_text)
            record_success_identity(pf, out_fn, content, out_text)
            try:
                safe_unlink(pf)
            except Exception:
                pass
    return []


def _llm_call_audit_kwargs(ctx) -> dict[str, str]:
    """Copy the per-run audit destination into every worker job."""
    return {
        "audit_run_id": str(getattr(ctx, "llm_call_audit_run_id", "") or ""),
        "audit_path": str(getattr(ctx, "llm_call_audit_path", "") or ""),
    }


def _run_multicore_leaf_batch(ctx, jobs, desired_workers):
    """Run one LLM leaf pool while holding exactly its granted permits."""
    with lease_execution_workers(ctx, desired_workers) as granted_workers:
        return multicoreJob(
            DTBJobs=jobs,
            nProcess=granted_workers,
            ShuffleJobs=False,
            mp_debug=getattr(ctx, "mp_debug", False),
        ).run()


def _run_legacy_leaf_round(ctx, jobs):
    """Run one legacy streaming leaf round under the shared process budget."""
    requested_workers = max(1, min(int(ctx.n_process), len(jobs)))
    with lease_execution_workers(ctx, requested_workers) as granted_workers:
        return run_round(
            jobs,
            granted_workers,
            timeout_sec=getattr(ctx, "llm_round_timeout_sec", None),
            debug_enabled=getattr(ctx, "llm_round_debug", None),
        )


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
            **_llm_call_audit_kwargs(ctx),
        ) for promptFile in _root_txt_files(TodoSubDir)]

    if ctx.mp_for_all_call:
        DTBJobs = []
        for item in itemList:
            DTBJobs.extend(create_jobs(item,ctx.model_spec))
        slice_workers = resolve_slice_parallelism(ctx, len(DTBJobs))
        print(
            "[llm-dispatch] slice-level parallelism: "
            f"jobs={len(DTBJobs)}, workers={slice_workers}"
        )
        MPresult = _run_multicore_leaf_batch(ctx, DTBJobs, slice_workers)
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
            slice_workers = resolve_slice_parallelism(ctx, len(DTBJobs))
            print(
                "[llm-dispatch] slice-level parallelism: "
                f"jobs={len(DTBJobs)}, workers={slice_workers}"
            )
            MPresult = _run_multicore_leaf_batch(ctx, DTBJobs, slice_workers)
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
                 audit_run_id: str = "",
                 audit_path: str = "",
                 queue_claim_event_id: str = "",
                 
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
        self.audit_run_id = audit_run_id
        self.audit_path = audit_path
        self.queue_claim_event_id = queue_claim_event_id
        self.audit_prompt_tokens = read_prompt_token_metadata(self.promptFile)
        
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
        response = None
        llm_request_attempted = False
        worker_call_id = ""  # Filled only at the real CallLLMAPI boundary.
        split_source_verified = False
        verified_queue_claim_id = ""
        call_llm_api_returned = False  # Actual wrapper return, not provider HTTP proof.
        # Explicit execution site, never inferred from exception text.
        worker_failure_code = "WORKER_PRECALL_EXCEPTION"
        DTBJobs_Retry = []
        # Fixed payload-free audit code, reset for each invocation.
        self._llm_json_failure_code = ""
    
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
                # Synthetic/no-provider mode is not a production Worker incident.
                worker_failure_code = ""
                retMES = self._build_mock_output()
                if self.OutputSaveFN != "":
                    MKDIR(os.path.dirname(self.OutputSaveFN))
                    publish_success_text_no_clobber(self.OutputSaveFN, retMES)
                    record_success_identity(
                        self.promptFile, self.OutputSaveFN, self.content, retMES,
                    )

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
            worker_failure_code = "WORKER_LLM_CALL_EXCEPTION"
            worker_call_id = uuid.uuid4().hex
            try:
                split_source_verified = verified_queued_prompt_source(
                    self.promptFile, self.content,
                )
            except Exception:
                split_source_verified = False
            if split_source_verified:
                try:
                    verified_queue_claim_id = verified_claim_observation(
                        self.promptFile, getattr(self, "queue_claim_event_id", ""),
                    )
                except Exception:
                    verified_queue_claim_id = ""
            llm_request_attempted = True
            response, cost = CallLLMAPI(
                self.content,
                max_tokens=self.max_tokens,
                model_spec=self.model_spec
            )
            call_llm_api_returned = True
            worker_failure_code = "WORKER_RESPONSE_EXCEPTION"
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
            worker_failure_code = "WORKER_PERSIST_EXCEPTION"
            if self.OutputSaveFN != "" and DTBJobs_Retry == [] and retMES != "":
                MKDIR(os.path.dirname(self.OutputSaveFN))
                publish_success_text_no_clobber(self.OutputSaveFN, retMES)
                record_success_identity(
                    self.promptFile, self.OutputSaveFN, self.content, retMES,
                )
    
                if self.removeFinPromptFile and self.promptFile:
                    safe_unlink(self.promptFile)
    
            # 7) 成功旗標
            worker_failure_code = "WORKER_RESPONSE_EXCEPTION"
            ok = bool(retMES)
            # Internally handled JSON repair failure needs an audit signal.
            err = (self._llm_json_failure_code if not ok else "")
    
            # 你如果後面還會用 response 物件可留著；但回傳不要回傳它
            response.choices[0].message.content = retMES
    
        except Exception as ex:
            # Preserve legacy caught-error return and per-request CSV audit.
            # Cooperative cancellation and synthetic mock faults are not incidents.
            if worker_failure_code and not isinstance(ex, ExecutionCancelled):
                quality_code = worker_failure_code
                if worker_failure_code == "WORKER_LLM_CALL_EXCEPTION":
                    try:
                        quality_code = classify_llm_call_exception(ex)
                    except Exception:
                        # Telemetry may never replace the original caught error.
                        quality_code = worker_failure_code
                _audit_leaf_worker_phase_failure(
                    self.audit_path, self.audit_run_id, quality_code,
                )
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

        # One row per actual LLM request. Defer audit until post-processing and
        # persistence settle so a successful HTTP response followed by a local
        # failure cannot create both success and failure rows.
        if llm_request_attempted:
            try:
                # Initial failed parent journal may be written DURING repair.
                # Require a pre-call disk snapshot, then verify intent after.
                split_family_id = ""
                if split_source_verified:
                    try:
                        split_family_id = verified_split_family_id(
                            self.promptFile, self.content,
                        )
                    except Exception:
                        pass
                log_llm_call(
                    audit_path=self.audit_path,
                    run_id=self.audit_run_id,
                    task=self.task,
                    prompt_file=self.promptFile,
                    model_spec=self.model_spec,
                    response=response,
                    max_tokens=self.max_tokens,
                    cost_twd=cost,
                    ok=ok,
                    error=err,
                    task_text_tokens=self.audit_prompt_tokens.get("task_text_tokens"),
                    template_tokens=self.audit_prompt_tokens.get("template_tokens"),
                    rendered_prompt_tokens=self.audit_prompt_tokens.get("rendered_prompt_tokens"),
                    prompt_component_token_source=self.audit_prompt_tokens.get(
                        "prompt_component_token_source", ""
                    ),
                    stage_identity=self.audit_prompt_tokens.get("stage_identity", ""),
                    worker_call_id=worker_call_id,
                    call_llm_api_returned=call_llm_api_returned,
                    split_family_id=split_family_id,
                    queue_claim_event_id=verified_queue_claim_id,
                )
            except Exception as audit_ex:
                print(
                    "⚠️ llm_call_audit write failed after request finalization: "
                    f"{type(audit_ex).__name__}"
                )
    
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
                publish_success_text_no_clobber(self.OutputSaveFN, retMES)
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
            log_llm_call(
                audit_path=self.audit_path,
                run_id=self.audit_run_id,
                task=self.task,
                prompt_file=self.promptFile,
                model_spec=self.model_spec,
                response=None,
                max_tokens=self.max_tokens,
                cost_twd=cost,
                ok=False,
                error=str(ex),
            )
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

    def _emit_json_quality(self, event: str, code: str, outcome: str) -> None:
        # A failed audit must not mutate outputs or requeue LLM work.
        try:
            emit_quality_event(
                self.audit_path, run_id=self.audit_run_id,
                event=event, code=code, scope="slice", outcome=outcome,
                slice_id=self.promptFile,
            )
        except Exception as audit_error:
            print(f"⚠️ processing_quality audit failed: {type(audit_error).__name__}")

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
            self._emit_json_quality("slice_json_validation", "JSON_VALID", "accepted")
            return [],retMES
        except json.JSONDecodeError:
            self._emit_json_quality("slice_json_validation", "JSON_SYNTAX_INVALID", "rejected")
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
                    audit_run_id=self.audit_run_id,
                    audit_path=self.audit_path,
                    #no_think = should_disable_think(self.model_spec["model_name"])
                    )
                json.loads(retMES_rep)
                self._emit_json_quality("slice_json_repair", "JSON_REPAIR_SUCCEEDED", "recovered")
                print("Successfully repair with LLM.")
                print("repaired retMES_rep",retMES_rep)
                return [],retMES_rep
            except Exception as ex_json:
                self._llm_json_failure_code = "JSON_POSTPROCESSING_FAILED"
                self._emit_json_quality("slice_json_repair", "JSON_REPAIR_FAILED", "not_recovered")
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
    
        # Journal intent BEFORE either child is written. Each child is
        # installed atomically, and the original parent is removed only once
        # both children exist. Resume can roll back a partial transition.
        install_split_prompts(
            self.promptFile, self.content,
            [(Path(new_prompt_file_0).name, prompt_0),
             (Path(new_prompt_file_1).name, prompt_1)],
        )

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
                    allow_to_retry=False,  # 不允許再次重試
                    model_spec=self.model_spec,
                    audit_run_id=self.audit_run_id,
                    audit_path=self.audit_path,
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
                       audit_run_id: str = "",
                       audit_path: str = "",
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
        # model_spec credentials must come from environment-backed model config.
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
        model_spec=model_spec,
        audit_run_id=audit_run_id,
        audit_path=audit_path,
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
        # A terminal claim rollback cannot be drained by the stopped consumer.
        # The producer must unwind immediately (no more dispatch), even when
        # ordinary stop_event is not yet set by the coordinator teardown.
        blocked = getattr(ctx, "_queue_claim_blocked_event", None)
        if blocked is not None and blocked.is_set():
            return
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
