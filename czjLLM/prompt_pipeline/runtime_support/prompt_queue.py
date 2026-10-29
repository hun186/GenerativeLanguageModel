"""Filesystem-backed prompt queue helpers for TODO/RUNNING/Success folders."""

import os
import stat
from collections import Counter
from pathlib import Path

from czjLLM.prompt_pipeline.runtime_support.queue_observation import record_queue_transition


def _claim_regular_source_no_clobber(source: Path, target: Path) -> bool:
    """Safely *avoid overwriting* an existing RUNNING destination.

    An exclusive same-filesystem hardlink is the publication point. Remove
    TODO only after verifying the linked inode. If the filesystem cannot
    hardlink, leave TODO untouched rather than falling back to os.replace.
    A crash between link and unlink leaves two paths; never dispatch in that
    state without a successful source unlink.
    """
    try:
        if any(p.is_symlink() for p in (source, *source.parents, target.parent, *target.parent.parents)):
            return False
        original = source.lstat()
        if not stat.S_ISREG(original.st_mode) or original.st_nlink != 1:
            return False
        # os.link atomically refuses to overwrite an existing target, even
        # when another scheduler creates it between checks.
        os.link(source, target, follow_symlinks=False)
        source_now = source.lstat()
        target_now = target.lstat()
        identity = lambda x: (x.st_dev, x.st_ino, x.st_size, x.st_mtime_ns)
        if (not stat.S_ISREG(target_now.st_mode)
                or identity(original) != identity(source_now)
                or identity(source_now) != identity(target_now)
                or source_now.st_nlink != 2 or target_now.st_nlink != 2):
            # Refuse dispatch and leave both copies for explicit recovery.
            return False
        source.unlink()
        return True
    except (OSError, ValueError):
        return False


def require_no_pending_todo_sources(item_dirs) -> None:
    """Fail instead of finalizing a consumer while unclaimable TODO files remain.

    Called only when the producer stopped and both regular claim sweeps found
    no claimable work. Never delete or implicitly rename private sources.
    """
    for item_dir in item_dirs:
        todo = Path(item_dir) / "TODO"
        if todo.is_dir() and any(p.is_file() or p.is_symlink() for p in todo.rglob("*")):
            raise RuntimeError("undispatched TODO sources remain after producer stopped")


def pick_and_claim_next_prompts(item_dirs, per_round_limit=128, *, claim_ids_out=None):
    """
    從各 item_dir 的 TODO 中挑選檔案，只領取不會覆寫 RUNNING 的檔案。
    同一 item 下名稱相同的巢狀 TODO 保留原狀，須先排除歧義。
    回傳 [(pf_running, item_dir), ...]，其中 pf_running 位於 RUNNING 目錄。
    """
    claimed = []
    # The legacy queue flattens nested TODO names into RUNNING/<basename>.
    # More than one real successful claim can therefore share a destination.
    # A path-keyed receipt must never be attributed to both scheduled jobs.
    seen_destinations = set()
    ambiguous_destinations = set()
    for item_dir in item_dirs:
        todo = Path(item_dir) / "TODO"
        run = Path(item_dir) / "RUNNING"
        if not todo.is_dir():
            continue
        run.mkdir(parents=True, exist_ok=True)

        # Snapshot candidate names before any mutation. The existing queue
        # flattens TODO subdirectories into RUNNING/<basename>; refuse *all*
        # collisions, not just the second file, so neither source can be lost.
        sources = sorted((path for path in todo.rglob("*") if path.is_file()),
                         key=lambda p: str(p))
        basename_counts = Counter(p.name for p in sources)
        for src_p in sources:
            if basename_counts[src_p.name] != 1:
                continue
            dst_p = run / src_p.name
            if not _claim_regular_source_no_clobber(src_p, dst_p):
                continue

            # Observe the real completed rename without changing the legacy
            # scheduling behavior. A duplicate destination (even when its
            # earlier observation write failed) is never safe to attribute.
            dst_key = str(dst_p)
            if claim_ids_out is not None:
                if dst_key in seen_destinations or dst_key in claim_ids_out:
                    ambiguous_destinations.add(dst_key)
                    claim_ids_out.pop(dst_key, None)
                seen_destinations.add(dst_key)
            try:
                claim_id = record_queue_transition(
                    dst_p, "claimed", previous_path=src_p,
                    return_event_id=claim_ids_out is not None,
                )
                if (claim_ids_out is not None and
                        dst_key not in ambiguous_destinations and
                        isinstance(claim_id, str)):
                    claim_ids_out[dst_key] = claim_id
            except Exception:
                pass
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
                # A successful requeue move is evidence of a queue transition,
                # not proof of a second LLM/provider invocation.
                try:
                    record_queue_transition(dst, "requeued", previous_path=p)
                except Exception:
                    pass
                moved += 1
            except FileNotFoundError:
                pass
            except PermissionError:
                pass
    return moved
