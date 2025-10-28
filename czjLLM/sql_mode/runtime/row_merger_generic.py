# sql_mode/runtime/row_merger_generic.py
import os, time, json
from datetime import datetime
from typing import Iterable, Tuple, Any, Optional, List, Dict

from czjLLM.job_manager.console_ui import tlog, tlog_warn
from utils.utilities_path import OSWALK, DirReplace, MKDIR, getPathFromFN
from utils.utilities_path import safe_move

from czjLLM.prompt_pipeline.pipeline_controller import (
    combine_api_finished_item, get_combined_result_path, row_is_ready, meter_update
)
from czjLLM.row_processors.flatten_utils import extract_json_list_for_flatten
#from czjLLM.prompt_pipeline.pipeline_controller import meter_update  # 檔頭若尚未 import



'''
def _extract_json_list(result_text: str, allowed_fields: Optional[List[str]]) -> List[Dict[str, Any]]:
    # 與你 SQL 版一致：回傳「list[dict]」
    try:
        data = json.loads(result_text)
        if isinstance(data, dict):
            data = [data]
        if not isinstance(data, list):
            return []
        out = []
        for obj in data:
            if not isinstance(obj, dict):
                continue
            if allowed_fields:
                out.append({k: obj.get(k) for k in allowed_fields if k in obj})
            else:
                out.append(obj)
        return out
    except Exception:
        return []
'''

def row_merger_watchdog_generic(ctx, registry, meter_fn, stop_event, sink,
                                scan_interval=0.5, done_q=None):
    # 只在 TODO/Success 計數有變化時才印一次
    if not hasattr(row_merger_watchdog_generic, "_last_state"):
        row_merger_watchdog_generic._last_state = {}

    def _log_state_once(item_dir):
        todo_dir = os.path.join(item_dir, "TODO")
        succ_dir = os.path.join(item_dir, "Success")
        state = (len(OSWALK(todo_dir)), len(OSWALK(succ_dir)))
        last = row_merger_watchdog_generic._last_state.get(item_dir)
        if last != state:
            tlog(f"🧩 merge check: {os.path.basename(item_dir)} TODO={state[0]}, Success={state[1]}")
            row_merger_watchdog_generic._last_state[item_dir] = state
        return state

    def _resolve_combined_path_old_1027(item_dir, meta, ctx, temp_txt):
        # 1) registry 內的 per-row 路徑（優先）
        p = meta.get("CombBackFN")
        if p and os.path.isfile(p):
            return p

        # 2) 退一步，用共享 ctx 推導（有些 combine 會寫到這）
        try:
            alt = get_combined_result_path(temp_txt, ctx)
            if alt and os.path.isfile(alt):
                return alt
        except Exception:
            pass

        # 3) 最後才嘗試合併（要有 Success 才做，避免洗版）
        succ_dir = os.path.join(item_dir, "Success")
        if len(OSWALK(succ_dir)) > 0:
            try:
                out = combine_api_finished_item(item_dir, ctx)  # 若你的實作會回傳路徑
                if out and os.path.isfile(out):
                    return out
            except Exception as e:
                tlog_warn(f"ℹ️ 合併提示（pk={meta.get('pk')}）：{e}")
        return None
    def _resolve_combined_path(item_dir, meta, ctx, temp_txt):
        # 1) registry 內的 per-row 路徑（優先）
        p = meta.get("CombBackFN")
        if p and os.path.isfile(p):
            return p
    
        # 2) 退一步，用共享 ctx 推導（有些 combine 會寫到這）
        try:
            alt = get_combined_result_path(temp_txt, ctx)
            if alt and os.path.isfile(alt):
                return alt
        except Exception:
            alt = None  # 讓後面還能用
    
        # 3) 最後才嘗試合併：用「預期輸出資料夾」覆寫 per-row finished 目錄後再合併
        succ_dir = os.path.join(item_dir, "Success")
        if len(OSWALK(succ_dir)) > 0:
            try:
                target_dir = os.path.dirname(p or alt or get_combined_result_path(temp_txt, ctx))
    
                class _CtxOverlay:
                    def __init__(self, base, **kw):
                        # 複製原 ctx 的屬性，再覆寫
                        self.__dict__.update(getattr(base, "__dict__", {}))
                        self.__dict__.update(kw)
    
                overlay = _CtxOverlay(ctx, temp_txt_finished_dir=target_dir)
                out = combine_api_finished_item(item_dir, overlay)
                if out and os.path.isfile(out):
                    return out
            except Exception as e:
                tlog_warn(f"ℹ️ 合併提示（pk={meta.get('pk')}）：{e}")
    
        return None

    sink.open()
    try:
        while True:
            items_map = registry.list_items()
            if not items_map and stop_event.is_set():
                break

            progressed = False
            for item_dir, meta in list(items_map.items()):
                pk = meta["pk"]; temp_txt = meta["temp_txt"]

                if not row_is_ready(item_dir):
                    _log_state_once(item_dir)
                    continue

                _log_state_once(item_dir)

                # ← 這裡不再一律呼叫 combine_api_finished_item，改用解析策略
                comb_back_fn = _resolve_combined_path(item_dir, meta, ctx, temp_txt)
                if not comb_back_fn or not os.path.isfile(comb_back_fn):
                    continue  # 沒合併檔就等下一輪

                try:
                    with open(comb_back_fn, "r", encoding="utf-8") as fp:
                        result_text = fp.read()

                    update_time = (datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                   if ctx.record_update_time else None)
                    sink.write_main(pk, result_text, update_time)

                    if getattr(ctx, "flatten_json_output", False):
                        raw_fields = getattr(ctx, "allowed_output_fields", None)
                        if isinstance(raw_fields, (list, tuple)):
                            allowed_fields = [str(f).strip() for f in raw_fields if f is not None and str(f).strip() != ""]
                            if not allowed_fields:
                                allowed_fields = None
                        else:
                            allowed_fields = None

                        try:
                            result_list = extract_json_list_for_flatten(result_text, allowed_fields)
                        except Exception as ex:
                            tlog_warn(f"⚠️ 解析展平欄位失敗（pk={pk}）：{ex}")
                            result_list = None

                        if result_list:
                            sink.ensure_flatten_schema(allowed_fields)
                            wants_raw = bool(getattr(ctx, "save_raw_input_when_flatten", False))
                            needs_raw_input = wants_raw and (getattr(ctx, "primary_key", None) != getattr(ctx, "input_col", None))
                            sub_input_col = getattr(ctx, "subtable_input_col", None) if needs_raw_input else None
                            input_val = sink.fetch_input(pk) if needs_raw_input else None
                            try:
                                sink.write_flatten(pk, result_list,
                                                   save_raw_input=needs_raw_input,
                                                   input_col=sub_input_col,
                                                   input_value=input_val)
                            except Exception as ex:
                                tlog_warn(f"⚠️ 子表寫回失敗（pk={pk}）：{ex}")

                    # 完成後收尾
                    registry.remove(item_dir)
                    if done_q is not None:
                        try: done_q.put_nowait(1)
                        except Exception: pass
                    try:
                        meter_update(meter_fn, lambda d, _pk=pk: d["rows"].setdefault(_pk, {}).update({"status":"merged"}))
                        meter_update(meter_fn, lambda d: d.setdefault("progress", {}).update({"last_progress_ts": time.time()}))
                    except Exception:
                        pass

                    # 備份原始 txt（慢 I/O 放最後）
                    try:
                        des = DirReplace(temp_txt, ctx.llm_source_dir, ctx.llm_source_backup_dir)
                        MKDIR(getPathFromFN(des)); safe_move(temp_txt, des)
                    except Exception as ex:
                        tlog_warn(f"⚠️ 備份原始 txt 失敗（pk={pk}）：{ex}")

                    tlog(f"✅ 逐列合併並寫回完成：{pk}")
                    progressed = True

                except Exception as e:
                    tlog_warn(f"Row Merger 寫回失敗 pk={pk}: {e}")
                    # 不要 raise；下一輪會再試
                    continue

            if not progressed:
                time.sleep(scan_interval)
    finally:
        try: sink.close()
        except Exception: pass
    

def row_merger_watchdog_generic_OLD_1027(ctx, registry, meter_fn, stop_event, sink,
                                scan_interval=0.2, done_q=None):
    sink.open()
    try:
        while True:
            items_map = registry.list_items()
            if not items_map and stop_event.is_set():
                break

            progressed = False
            for item_dir, meta in list(items_map.items()):
                pk = meta["pk"]
                temp_txt = meta["temp_txt"]
                comb_back_fn = meta["CombBackFN"]
                
                if not row_is_ready(item_dir):
                    continue

                # 合併檔產出（與舊版相同）
                try:
                    todo_dir = os.path.join(item_dir, "TODO")
                    succ_dir = os.path.join(item_dir, "Success")
                    try:
                        tlog(f"🧩 merge check: {os.path.basename(item_dir)} "
                             f"TODO={len(OSWALK(todo_dir))}, Success={len(OSWALK(succ_dir))}")
                    except Exception:
                        pass
                    combine_api_finished_item(item_dir, ctx)
                except Exception as e:
                    tlog_warn(f"ℹ️ 合併提示（pk={pk}）：{e}")

                #CombBackFN = get_combined_result_path(temp_txt, ctx)
                #print("CombBackFN from get_combined_result_path",CombBackFN)
                #if not os.path.isfile(CombBackFN):
                #    continue

                #try:
                #    with open(CombBackFN, "r", encoding="utf-8") as fp:
                #        result_text = fp.read()
                #print("comb_back_fn in row_merger",comb_back_fn)
                if not os.path.isfile(comb_back_fn):
                    continue
            
                try:
                    with open(comb_back_fn, "r", encoding="utf-8") as fp:
                        result_text = fp.read()
                    update_time = (datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                   if ctx.record_update_time else None)

                    # 1) 主表寫回（含 per-row commit）
                    sink.write_main(pk, result_text, update_time)
                    # 2) 子表展平（需要時；每批也 commit）
                    if getattr(ctx, "flatten_json_output", False):
                        # --- 正規化 allowed_output_fields，過濾 None / 空白 / 非字串 ---
                        raw_fields = getattr(ctx, "allowed_output_fields", None)
                        if isinstance(raw_fields, (list, tuple)):
                            allowed_fields = [
                                str(f).strip()
                                for f in raw_fields
                                if f is not None and str(f).strip() != ""
                            ]
                            if not allowed_fields:
                                allowed_fields = None  # 空清單等同「不限制欄位」
                        else:
                            allowed_fields = None  # 非 list/tuple 時一律交由 extractor 決定
                        # --- 做展平（以正規化後的欄位清單）---
                        try:
                            result_list = extract_json_list_for_flatten(result_text, allowed_fields)
                        except Exception as ex:
                            tlog_warn(f"⚠️ 解析展平欄位失敗（pk={pk}）：{ex}")
                            result_list = None

                        if result_list:
                            sink.ensure_flatten_schema(allowed_fields)

                            # 只有在「主鍵 != 輸入欄」且用戶要求另存 raw input 時才取 input 值
                            wants_raw = bool(getattr(ctx, "save_raw_input_when_flatten", False))
                            #print("wants_raw",wants_raw)
                            needs_raw_input = wants_raw and (getattr(ctx, "primary_key", None) != getattr(ctx, "input_col", None))
                            #print("needs_raw_input",needs_raw_input)
                            sub_input_col = getattr(ctx, "subtable_input_col", None) if needs_raw_input else None
                            #print("in row_merger_generic, sub_input_col",sub_input_col)
                            #print("primary key",getattr(ctx, "primary_key", None))
                            input_val = sink.fetch_input(pk) if needs_raw_input else None
                            try:
                                sink.write_flatten(
                                    pk, result_list,
                                    save_raw_input=needs_raw_input,
                                    input_col=sub_input_col,     # 可能為 None → 下游會略過
                                    input_value=input_val,
                                )
                            except Exception as ex:
                                tlog_warn(f"⚠️ 子表寫回失敗（pk={pk}）：{ex}")

                    # 3) 先回報完成與釋放背壓
                    registry.remove(item_dir)
                    if done_q is not None:
                        try: done_q.put_nowait(1)
                        except Exception: pass
                    try:
                        meter_update(meter_fn,
                            lambda d, _pk=pk: d["rows"].setdefault(_pk, {}).update({"status":"merged"}))
                    except Exception:
                        pass

                    # 4) 最後才做備份（慢 I/O 不卡住進度與背壓）
                    try:
                        des = DirReplace(temp_txt, ctx.llm_source_dir, ctx.llm_source_backup_dir)
                        MKDIR(getPathFromFN(des))
                        safe_move(temp_txt, des)
                    except Exception as ex:
                        tlog_warn(f"⚠️ 備份原始 txt 失敗（pk={pk}）：{ex}")

                    tlog(f"✅ 逐列合併並寫回完成：{pk}")
                    meter_update(meter_fn, lambda d: d.setdefault("progress", {}).update({"last_progress_ts": time.time()}))
                    progressed = True
                except Exception as e:
                    tlog_warn(f"Row Merger 寫回失敗 pk={pk}: {e}")
                    #with open("ERROR.txt","at") as f:
                    #    f.write(e)
                    #print("sleep 10 secs to debug")
                    #time.sleep(10)
                    raise Exception

            if not progressed:
                time.sleep(scan_interval)
    finally:
        try: sink.close()
        except Exception: pass
