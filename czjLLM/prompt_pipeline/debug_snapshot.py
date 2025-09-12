import os, time, json, glob
from typing import Dict, List, Tuple, Optional
from datetime import datetime
from utilities.atomic_io import robust_json_read  # 你前面已加過
from utils.utilities_path import OSWALK

def _age(ts: float) -> str:
    s = max(0, time.time() - ts)
    if s < 60: return f"{int(s)}s"
    m, s = divmod(int(s), 60); 
    if m < 60: return f"{m}m{s:02d}s"
    h, m = divmod(m, 60); return f"{h}h{m:02d}m"

def _file_age(p: str) -> str:
    try: return _age(os.path.getmtime(p))
    except: return "?"

def _count_dir(d: str) -> int:
    try: return len(OSWALK(d))
    except: return -1

def build_debug_snapshot(
    ctx,
    registry,                 # ItemsRegistry
    meter_fn: str,
    *,
    list_top: int = 8,
    base_url_load_fn: Optional[str] = None,
) -> str:
    """彙整目前狀態，用於「長時間無進度」時輸出。"""
    lines: List[str] = []
    # 1) queue / meter 狀態
    m = robust_json_read(meter_fn, default_factory=lambda: {"rows": {}, "queue": {"pending": 0, "running": 0}})
    q = m.get("queue", {})
    rows = m.get("rows", {})
    outstanding = int(q.get("pending", 0)) + int(q.get("running", 0))
    lines.append(f"Queue: pending={q.get('pending',0)}, running={q.get('running',0)}, outstanding={outstanding}")
    # 2) registry 狀態
    items = registry.list_items()
    lines.append(f"Registry items: {len(items)}")
    # 3) 每列概況（取前 N 個）
    cnt = 0
    for item_dir, meta in items.items():
        if cnt >= list_top: break
        todo = os.path.join(item_dir, "TODO")
        succ = os.path.join(item_dir, "Success")
        todo_n = _count_dir(todo)
        succ_n = _count_dir(succ)
        comb = f"{item_dir}_combined.txt"  # 你的 combine_api_finished_item 輸出名規則可能不同
        comb_exists = os.path.exists(comb)
        lines.append(f"- {os.path.basename(item_dir)}: TODO={todo_n}, Success={succ_n}, combined={'Y' if comb_exists else 'N'}")
        cnt += 1
    # 4) meter 鎖檔
    lck = meter_fn + ".lck"
    if os.path.exists(lck):
        lines.append(f"Meter lock present: age={_file_age(lck)}")
    else:
        lines.append("Meter lock: (none)")
    # 5) base_url 載重（若有）
    if base_url_load_fn is None:
        base_dir = getattr(ctx, "PGMSubDir")
        base_url_load_fn = os.path.join(base_dir, "logs", "base_url_load.json")
    if os.path.exists(base_url_load_fn):
        try:
            d = robust_json_read(base_url_load_fn, default_factory=dict)
            lines.append(f"base_url_load.json (age={_file_age(base_url_load_fn)}): {d}")
        except Exception as e:
            lines.append(f"base_url_load.json read error: {e}")
    else:
        lines.append("base_url_load.json: (missing)")
    return "\n".join(lines)
