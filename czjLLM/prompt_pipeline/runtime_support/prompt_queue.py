"""Filesystem-backed prompt queue helpers for TODO/RUNNING/Success folders."""

import os
from pathlib import Path


def pick_and_claim_next_prompts(item_dirs, per_round_limit=128):
    """
    從各 item_dir 的 TODO 中挑選檔案，並立即以 os.replace() 更名為 RUNNING/xxx.txt。
    回傳 [(pf_running, item_dir), ...]，其中 pf_running 位於 RUNNING 目錄。
    """
    claimed = []
    for item_dir in item_dirs:
        todo = Path(item_dir) / "TODO"
        run = Path(item_dir) / "RUNNING"
        if not todo.is_dir():
            continue
        run.mkdir(parents=True, exist_ok=True)

        # 排序讓行為穩定
        for src in sorted(str(path) for path in todo.rglob("*") if path.is_file()):
            src_p = Path(src)
            dst_p = run / src_p.name
            try:
                os.replace(str(src_p), str(dst_p))
            except FileNotFoundError:
                continue
            except PermissionError:
                continue
            except OSError:
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
    if p.parent.name != "RUNNING":
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
    return pf_any


def recover_running_to_todo(item_dirs):
    """
    將 RUNNING/* 移回 TODO/*，讓它們能被重新排程。

    回傳實際退回的切片數；舊呼叫端可忽略回傳值。
    """
    moved = 0
    for item_dir in item_dirs:
        run = Path(item_dir) / "RUNNING"
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
                os.replace(str(p), str(dst))
                moved += 1
            except FileNotFoundError:
                pass
            except PermissionError:
                pass
    return moved
