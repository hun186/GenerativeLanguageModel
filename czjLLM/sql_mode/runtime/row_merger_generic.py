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

                CombBackFN = get_combined_result_path(temp_txt, ctx)
                if not os.path.isfile(CombBackFN):
                    continue

                try:
                    with open(CombBackFN, "r", encoding="utf-8") as fp:
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
                    progressed = True
                except Exception as e:
                    tlog_warn(f"Row Merger 寫回失敗 pk={pk}: {e}")

            if not progressed:
                time.sleep(scan_interval)
    finally:
        try: sink.close()
        except Exception: pass
