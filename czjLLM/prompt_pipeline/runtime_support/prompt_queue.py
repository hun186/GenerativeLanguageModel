"""Filesystem-backed prompt queue helpers for TODO/RUNNING/Success folders."""

import os
import stat
import tempfile
import time
import json
from collections import Counter
from pathlib import Path

from czjLLM.prompt_pipeline.runtime_support.queue_observation import record_queue_transition
from czjLLM.utilities.atomic_io import atomic_write_json


class QueueClaimRollbackError(RuntimeError):
    """An already-claimed source could not safely return to its original TODO.

    This terminal condition must reach the SQL/Table/ES coordinator; it is not
    an ordinary missing/blocked candidate and cannot be retried blindly.
    """


class QueueClaimSuccessConflictError(RuntimeError):
    """A pending source conflicts with an older, already published Success."""


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


def publish_success_text_no_clobber(destination: str, text: str) -> None:
    """Publish an exclusively-created Success result, never replace a prior result.

    Write a unique fsynced staging file on the same volume *outside the
    Success tree*, then use an atomic hardlink create-if-absent. Orphan
    staging files can never appear as additional Success merger input.
    """
    target = Path(destination)
    if any(p.is_symlink() for p in (target.parent, *target.parent.parents)):
        raise OSError("unsafe success output directory")
    target.parent.mkdir(parents=True, exist_ok=True)
    # Success can contain nested stage paths. Locate its outer Success
    # ancestor, then keep all disposable temporary hardlinks in a sibling
    # directory that cannot be enumerated by any Success-only merge reader.
    # Path.parents runs from nearest to farthest. Use the OUTERMOST
    # Success ancestor, otherwise Success/Success/... leaves stage files
    # inside the outer result namespace and the merger reads them twice.
    success_roots = [p for p in target.parents if p.name == "Success"]
    success_root = success_roots[-1] if success_roots else target.parent
    stage_dir = success_root.parent / ".success-publish-staging"
    if stage_dir.is_symlink():
        raise OSError("unsafe success staging directory")
    stage_dir.mkdir(parents=True, exist_ok=True)
    fd, staged_name = tempfile.mkstemp(
        dir=str(stage_dir), prefix=".success-", suffix=".tmp",
    )
    staged = Path(staged_name)
    try:
        with os.fdopen(fd, mode="w", encoding="utf-8", newline="") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        # Atomic no-clobber publication, not os.replace. If a success was
        # already published, preserve it and leave RUNNING for inspection.
        os.link(staged, target, follow_symlinks=False)
    finally:
        # Cleanup is best effort, *not* part of the publication outcome.
        # Once os.link succeeds the complete Success exists; a permission
        # error removing this disposable staging link must never turn that
        # committed output into a failed Worker or skip its identity journal.
        # On an earlier publish failure, also preserve the original error.
        try:
            staged.unlink()
        except OSError:
            pass


def require_no_pending_success_conflicts(item_dirs) -> None:
    """Detect permanently unclaimable TODO/Success pairs before producer ends.

    A successful rollback of a racing claim restores TODO but does not make
    the source claimable: the older Success remains and blocks all further
    claims. Signal a terminal condition without waiting for producer_done.
    """
    for item_dir in item_dirs:
        root = Path(item_dir)
        todo = root / "TODO"
        if not todo.is_dir():
            continue
        for source in todo.rglob("*"):
            if not (source.is_file() or source.is_symlink()):
                continue
            success = root / "Success" / source.name
            if success.exists() or success.is_symlink():
                raise QueueClaimSuccessConflictError(
                    "undispatched TODO conflicts with prior Success"
                )


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
            prior_success = Path(item_dir) / "Success" / src_p.name
            # A prior completed result is not evidence that this generation
            # succeeded. Refuse dispatch instead of allowing a stale Success
            # file to be mistaken for this new Worker's output.
            if prior_success.exists() or prior_success.is_symlink():
                continue
            if not _claim_regular_source_no_clobber(src_p, dst_p):
                continue
            # Another Worker may publish Success and release its former
            # RUNNING file between the above existence check and our exclusive
            # claim. Claiming is then possible only AFTER that old output is
            # already present. Recheck *after* the successful claim and restore
            # our source to its exact original TODO path before dispatching.
            # Do not create a claim event, Worker call or false completion.
            if prior_success.exists() or prior_success.is_symlink():
                if not _claim_regular_source_no_clobber(dst_p, src_p):
                    # Preserve all evidence; never schedule an ambiguous
                    # RUNNING/Success pair or silently report it as claimed.
                    raise QueueClaimRollbackError("queue claim collision recovery incomplete")
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


def requeue_running_no_clobber(pf_running: str) -> bool:
    """Fail closed when restoring exactly one interrupted RUNNING source.

    A timeout/restart is not permission to replace a new TODO generation.
    A false result leaves RUNNING untouched (or retains hardlink evidence
    after interrupted unlink), and the consumer must signal terminal block.
    """
    source = Path(pf_running)
    if source.parent.name != "RUNNING":
        return False
    try:
        target = Path(_to_todo(pf_running))
    except (OSError, ValueError):
        return False
    # An existing TODO is a deterministic generation conflict, not a
    # transient filesystem failure. Never retry and never overwrite it.
    if target.exists() or target.is_symlink():
        return False
    for attempt in range(RECOVERY_MAX_ATTEMPTS):
        if _claim_regular_source_no_clobber(source, target):
            break
        if target.exists() or target.is_symlink():
            return False
        if attempt + 1 < RECOVERY_MAX_ATTEMPTS:
            time.sleep(RECOVERY_RETRY_DELAY_SEC)
    else:
        return False
    # Transition evidence only after the actual no-clobber move completes.
    try:
        record_queue_transition(target, "requeued", previous_path=source)
    except Exception:
        pass
    return True


RECOVERY_MAX_ATTEMPTS = 3
RECOVERY_RETRY_DELAY_SEC = 0.05
RECOVERY_MARKER_NAME = "queue_recovery_status.json"


def _strict_running_files(run: Path):
    """Fully enumerate before any moves. Unlike pathlib.rglob, propagate errors.

    No symlinks/reparse points, special files or unexpectedly large trees.
    Path-based scanning is NOT a concurrent-writer-safe or no-follow proof:
    real operator acceptance remains separately gated.
    """
    files = []
    stack = [run]
    total = 0
    while stack:
        directory = stack.pop()
        if directory.is_symlink():
            raise QueueClaimRollbackError("unsafe restart directory")
        # scandir, including iterator advancement, propagates EACCES/EIO.
        with os.scandir(directory) as entries:
            for entry in entries:
                total += 1
                if total > 10000:
                    raise QueueClaimRollbackError("restart entry limit exceeded")
                info = entry.stat(follow_symlinks=False)
                if getattr(info, "st_file_attributes", 0) & 0x400:
                    raise QueueClaimRollbackError("unsafe reparse entry")
                path = Path(entry.path)
                if stat.S_ISDIR(info.st_mode):
                    stack.append(path)
                elif stat.S_ISREG(info.st_mode):
                    files.append(path)
                else:
                    raise QueueClaimRollbackError("unsafe restart queue entry")
    return sorted(files, key=str)


def recovery_status_path(item_dir):
    return Path(item_dir) / "_extract_slice_identity" / RECOVERY_MARKER_NAME


def read_recovery_status(item_dir):
    """Read opaque recovery state; corrupt/aliased records fail closed."""
    path = recovery_status_path(item_dir)
    if path.is_symlink() or path.parent.is_symlink():
        raise QueueClaimRollbackError("unsafe recovery status marker")
    try:
        # FIFO/device entries can block forever on ordinary path.open().
        # Precheck and then verify the opened descriptor again; on POSIX,
        # O_NOFOLLOW closes the final symlink-swap race.
        if not stat.S_ISREG(path.lstat().st_mode):
            raise ValueError("nonregular recovery marker")
        flags = (os.O_RDONLY | getattr(os, "O_BINARY", 0)
                 | getattr(os, "O_NONBLOCK", 0)
                 | getattr(os, "O_NOFOLLOW", 0))
        fd = os.open(path, flags)
        with os.fdopen(fd, "rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise ValueError("nonregular opened recovery marker")
            raw = stream.read(4097)
        if len(raw) > 4096:
            raise ValueError("oversize recovery marker")
        record = json.loads(raw.decode("utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError, TypeError) as exc:
        raise QueueClaimRollbackError("unreadable recovery status marker") from exc
    if (not isinstance(record, dict) or record.get("version") != 1
            or record.get("integrity") != "incomplete"
            or record.get("state") != "blocked"
            or record.get("code") not in {
                "TODO_CONFLICT", "UNSAFE_QUEUE_ENTRY", "RECOVERY_RETRIES_EXHAUSTED",
                "RECOVERY_SCAN_INCOMPLETE",
            }):
        raise QueueClaimRollbackError("invalid recovery status marker")
    return record


def mark_recovery_blocked(item_dir, code, attempts):
    """Persist non-sensitive, item-scoped logical quarantine, not a file move."""
    if code not in {
        "TODO_CONFLICT", "UNSAFE_QUEUE_ENTRY", "RECOVERY_RETRIES_EXHAUSTED",
        "RECOVERY_SCAN_INCOMPLETE",
    }:
        raise ValueError("invalid recovery status code")
    path = recovery_status_path(item_dir)
    if path.is_symlink() or path.parent.is_symlink():
        raise QueueClaimRollbackError("unsafe recovery status directory")
    if path.exists():
        # Existing operator hold must not be silently overwritten/released.
        return read_recovery_status(item_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "version": 1, "state": "blocked", "integrity": "incomplete",
        "code": code, "attempts": int(attempts),
        "manual_review_required": True,
        "source_files_modified_by_quarantine": False,
    }
    atomic_write_json(str(path), record)
    return record


def recover_running_to_todo(item_dirs, *, require_complete=False,
                            max_attempts=RECOVERY_MAX_ATTEMPTS,
                            retry_delay=RECOVERY_RETRY_DELAY_SEC):
    """Requeue crashed RUNNING files without clobbering.

    Default remains legacy count-only. Strict mode scans every file before
    mutation, refuses errors and retries transient no-clobber failures at
    most max_attempts. Deterministic conflicts are not retried; never
    auto-overwrite, auto-delete or silently recover a quarantined item.
    """
    if not 1 <= max_attempts <= RECOVERY_MAX_ATTEMPTS:
        raise ValueError("invalid recovery retry limit")
    moved = 0
    for item_dir in item_dirs:
        if require_complete and read_recovery_status(item_dir) is not None:
            raise QueueClaimRollbackError("operator review required for blocked item")
        run = Path(item_dir) / "RUNNING"
        todo = Path(item_dir) / "TODO"
        if require_complete:
            try:
                # pathlib.is_dir() can hide some OS errors on supported Python
                # versions; absence is the ONLY benign non-directory result.
                run_info = run.lstat()
            except FileNotFoundError:
                continue
            except OSError as exc:
                raise QueueClaimRollbackError("restart directory metadata unavailable") from exc
            if (not stat.S_ISDIR(run_info.st_mode)
                    or any(parent.is_symlink() for parent in run.parents)
                    or todo.is_symlink()):
                raise QueueClaimRollbackError("unsafe restart queue directory")
            try:
                sources = _strict_running_files(run)
            except (OSError, ValueError) as exc:
                raise QueueClaimRollbackError("restart enumeration incomplete") from exc
        elif not run.is_dir():
            continue
        else:
            sources = [p for p in run.rglob("*") if p.is_file()]
        todo.mkdir(parents=True, exist_ok=True)
        for p in sources:
            rel = p.relative_to(run)
            dst = todo / rel
            if require_complete and (dst.exists() or dst.is_symlink()):
                raise QueueClaimRollbackError("restart TODO basename collision")
            dst.parent.mkdir(parents=True, exist_ok=True)
            attempts = max_attempts if require_complete else 1
            success = False
            for attempt in range(attempts):
                if _claim_regular_source_no_clobber(p, dst):
                    success = True
                    break
                if not require_complete:
                    break
                # A competing producer may have published a new generation.
                # Never retry a deterministic name collision or interrupted
                # link+unlink with two paths pointing to one inode.
                if dst.exists() or dst.is_symlink():
                    break
                if attempt + 1 < attempts:
                    time.sleep(retry_delay)
            if not success:
                if require_complete:
                    raise QueueClaimRollbackError("restart RUNNING recovery incomplete")
                continue
            try:
                record_queue_transition(dst, "requeued", previous_path=p)
            except Exception:
                pass
            moved += 1
    return moved
