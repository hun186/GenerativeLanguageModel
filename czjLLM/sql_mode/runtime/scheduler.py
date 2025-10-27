# sql_mode/scheduler.py
import os
import time
from typing import Any
from copy import deepcopy
from czjLLM.prompt_pipeline.pipeline_controller import find_item_dir_for, meter_update
from czjLLM.utilities.file_utils import save_text_as_temp_file
from utils.utilities_path import getMFNFromFN, OSWALK
from czjLLM.job_manager.console_ui import tlog, tlog_warn
from czjLLM.job_manager.job_config import CtxOverlay
from czjLLM.handlers.handle_txt_file import handle_single_input_file  # 延用現有函式
from czjLLM.prompt_pipeline.pipeline_controller import get_combined_result_path

def schedule_one_row(ctx, registry, meter_fn, idx: int, pk: Any, text: str):
    """切片 -> 建 TODO -> 登錄 registry 與 meter（使用 per-row ctx overlay，避免 deepcopy/Queue 錯誤）"""

    temp_dir = os.path.join(ctx.llm_source_dir, "cache")
    fin_dir  = os.path.join(ctx.llm_source_finished_dir, "cache")

    # 產原始臨時檔
    temp_txt_path = save_text_as_temp_file(text=text, base_dir=temp_dir, index=idx)
    main_name = getMFNFromFN(temp_txt_path)

    # 👉 這裡用 Overlay：只覆寫會被模板/切片讀到的變動欄位
    row_ctx = CtxOverlay(
        ctx,
        temp_txt_dir=temp_dir,
        temp_txt_finished_dir=fin_dir,
        main_file_name=main_name,
    )

    # 讓模板/切片在 row_ctx 上跑（不會動到共享 ctx）
    handle_single_input_file(
        temp_txt_path, row_ctx,
        adjust=True,
        pause_seconds=(10 if idx == 0 else 0),
        defer_merge=True
    )

    # 確認這列的 TODO 真的有產出，避免 consumer 找不到而卡住
    item_dir = None
    todo_dir = None
    t0 = time.time()
    while time.time() - t0 < 10.0:
        try:
            item_dir = find_item_dir_for(row_ctx, main_name)
            todo_dir = os.path.join(item_dir, "TODO")
            if os.path.isdir(todo_dir) and len(OSWALK(todo_dir)) > 0:
                break
        except Exception:
            pass
        time.sleep(0.1)

    if not item_dir or not os.path.isdir(todo_dir) or len(OSWALK(todo_dir)) == 0:
        tlog_warn(f"❌ TODO 未產生或為空（{main_name} / pk={pk}），略過此列以避免卡死。")
        return 0

    total_chunks = len(OSWALK(todo_dir))

    # 註冊給 row_merger（合併檔路徑用 row_ctx 算，不會串線）
    comb_back_fn = get_combined_result_path(temp_txt_path, row_ctx)
    registry.add(item_dir, pk, temp_txt_path, comb_back_fn)

    def _on_add_row(d):
        d["rows"].setdefault(pk, {
            "item_dir": item_dir,
            "temp_txt": temp_txt_path,
            "total": 0, "done": 0, "status": "in_progress"
        })
        d["rows"][pk]["total"] = total_chunks
        d["queue"]["pending"] += total_chunks

    meter_update(meter_fn, _on_add_row)
    meter_update(meter_fn, lambda d: d.setdefault("progress", {}).update({"last_progress_ts": time.time()}))

    tlog(f"[sched] pk={pk} added, chunks={total_chunks}, dir={os.path.basename(item_dir)}")
    return total_chunks
    
def schedule_one_row_OLD_1027(ctx, registry, meter_fn, idx: int, pk: Any, text: str):
    """切片 -> 建 TODO -> 登錄 registry 與 meter（使用 per-row ctx 避免 race）"""

    # 1) 建 per-row ctx（只在本列使用）
    row_ctx = deepcopy(ctx)
    row_ctx.temp_txt_dir = os.path.join(ctx.llm_source_dir, "cache")
    row_ctx.temp_txt_finished_dir = os.path.join(ctx.llm_source_finished_dir, "cache")

    # 2) 產生原始臨時輸入檔，並設定 row_ctx.main_file_name（template 會用到）
    temp_txt_path = save_text_as_temp_file(text=text, base_dir=row_ctx.temp_txt_dir, index=idx)
    row_ctx.main_file_name = getMFNFromFN(temp_txt_path)

    # 3) 讓 template/切片在 row_ctx 上運作（不碰共享 ctx）
    handle_single_input_file(
        temp_txt_path, row_ctx, adjust=True,
        pause_seconds=(10 if idx == 0 else 0),
        defer_merge=True
    )

    # 4) 驗證：這一列的 TODO 真的被產生（避免之後 consumer 找不到而卡住）
    item_dir = None
    todo_dir = None
    t0 = time.time()
    while time.time() - t0 < 10.0:
        try:
            item_dir = find_item_dir_for(row_ctx, row_ctx.main_file_name)
            todo_dir = os.path.join(item_dir, "TODO")
            if os.path.isdir(todo_dir) and len(OSWALK(todo_dir)) > 0:
                break
        except Exception:
            pass
        time.sleep(0.1)

    if not item_dir or not os.path.isdir(todo_dir) or len(OSWALK(todo_dir)) == 0:
        tlog_warn(f"❌ TODO 未產生或為空（{row_ctx.main_file_name} / pk={pk}），略過此列以避免卡死。")
        return 0

    total_chunks = len(OSWALK(todo_dir))

    # 5) 註冊到 registry（也用 row_ctx 算合併輸出檔名）
    comb_back_fn = get_combined_result_path(temp_txt_path, row_ctx)
    registry.add(item_dir, pk, temp_txt_path, comb_back_fn)

    # 6) 更新負載計量檔
    def _on_add_row(d):
        d["rows"].setdefault(pk, {
            "item_dir": item_dir,
            "temp_txt": temp_txt_path,
            "total": 0, "done": 0, "status": "in_progress"
        })
        d["rows"][pk]["total"] = total_chunks
        d["queue"]["pending"] += total_chunks

    meter_update(meter_fn, _on_add_row)
    meter_update(meter_fn, lambda d: d.setdefault("progress", {}).update({"last_progress_ts": time.time()}))

    tlog(f"[sched] pk={pk} added, chunks={total_chunks}, dir={os.path.basename(item_dir)}")
    return total_chunks

def schedule_one_row_OLD(ctx, registry, meter_fn, idx: int, pk: Any, text: str):
    """切片 -> 建 TODO -> 登錄 registry 與 meter。"""   
    ctx.temp_txt_dir = os.path.join(ctx.llm_source_dir,"cache")
    ctx.temp_txt_finished_dir = os.path.join(ctx.llm_source_finished_dir,"cache")
    temp_txt_path = save_text_as_temp_file(
        #text=text, base_dir=os.path.join(ctx.llm_source_dir,"cache"), index=idx)
        text=text, base_dir=ctx.temp_txt_dir, index=idx)
    handle_single_input_file(
        temp_txt_path, ctx, adjust=True,
        pause_seconds=(10 if idx == 0 else 0),
        defer_merge=True
    )
    print("temp_txt_path",temp_txt_path)
    main_file_name = getMFNFromFN(temp_txt_path)
    item_dir = find_item_dir_for(ctx, main_file_name)
    todo_dir = os.path.join(item_dir, "TODO")
    total_chunks = len(OSWALK(todo_dir))
    #registry.add(item_dir, pk, temp_txt_path)
    comb_back_fn = get_combined_result_path(temp_txt_path, ctx)
    registry.add(item_dir, pk, temp_txt_path, comb_back_fn)
    print("comb_back_fn in schedule_one_row for ",pk, comb_back_fn)
    def _on_add_row(d):
        d["rows"].setdefault(pk, {
            "item_dir": item_dir,
            "temp_txt": temp_txt_path,
            "total": 0, "done": 0, "status": "in_progress"
        })
        d["rows"][pk]["total"] = total_chunks
        d["queue"]["pending"] += total_chunks

    meter_update(meter_fn, _on_add_row)
    meter_update(meter_fn, lambda d: d.setdefault("progress", {}).update({"last_progress_ts": time.time()}))
    
    tlog(f"[sched] pk={pk} added, chunks={total_chunks}, dir={os.path.basename(item_dir)}")
    return total_chunks