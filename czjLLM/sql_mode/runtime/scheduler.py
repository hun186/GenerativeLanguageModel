# sql_mode/scheduler.py
import os
from typing import Any
from prompt_pipeline.pipeline_controller import find_item_dir_for, meter_update
from utilities.file_utils import save_text_as_temp_file
from utils.utilities_path import getMFNFromFN, OSWALK
from job_manager.console_ui import tlog
from handlers.handle_txt_file import handle_single_input_file  # 延用現有函式

def schedule_one_row(ctx, registry, meter_fn, idx: int, pk: Any, text: str):
    """切片 -> 建 TODO -> 登錄 registry 與 meter。"""   

    temp_txt_path = save_text_as_temp_file(
        text=text, base_dir=os.path.join(ctx.llm_source_dir,"cache"), index=idx)
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
    registry.add(item_dir, pk, temp_txt_path)

    def _on_add_row(d):
        d["rows"].setdefault(pk, {
            "item_dir": item_dir,
            "temp_txt": temp_txt_path,
            "total": 0, "done": 0, "status": "in_progress"
        })
        d["rows"][pk]["total"] = total_chunks
        d["queue"]["pending"] += total_chunks

    meter_update(meter_fn, _on_add_row)
    tlog(f"[sched] pk={pk} added, chunks={total_chunks}, dir={os.path.basename(item_dir)}")
    return total_chunks