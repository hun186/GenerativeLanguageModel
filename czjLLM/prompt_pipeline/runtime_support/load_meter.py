"""Load-meter and item-registry helpers for prompt pipeline execution."""

import errno
import os
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

from czjLLM.utilities.atomic_io import atomic_write_json, robust_json_read


def _oswalk_files(root):
    for path in Path(root).rglob("*"):
        if path.is_file():
            yield str(path)


def _normalized_parent_path(filename):
    return str(Path(filename).parent).replace(os.sep, "/")


class ItemsRegistry:
    """
    執行緒安全：註冊「每列」的 item 目錄（含 TODO/Success）與對應 pk、暫存 txt。
    """

    def __init__(self):
        self.lock = threading.Lock()
        self._items = {}  # item_dir -> {"pk":..., "temp_txt":...}

    def add(self, item_dir, pk, temp_txt, comb_back_fn):
        with self.lock:
            self._items[item_dir] = {
                "pk": pk,
                "temp_txt": temp_txt,
                "CombBackFN": comb_back_fn,
            }

    def list_items(self):
        with self.lock:
            return dict(self._items)

    def get(self, item_dir):
        with self.lock:
            return self._items.get(item_dir)

    def update(self, item_dir, **fields):
        with self.lock:
            if item_dir in self._items:
                self._items[item_dir].update(fields)

    def remove(self, item_dir):
        with self.lock:
            self._items.pop(item_dir, None)


def meter_path_init(ctx):
    """
    建議：檔名含 session 起始時間、pid 與短 UUID，避免不同主程序互蓋。

    Watchdog 的「多久沒有分片完成」判斷只應觀察本主程序自己的
    meter。若自動排程在同一秒啟動多個主程序，單靠秒級 timestamp
    可能產生相同檔名，導致 completed/pending/running 互相污染並誤判。
    """
    if not hasattr(ctx, "session_start_ts"):
        ctx.session_start_ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    if not hasattr(ctx, "session_run_id"):
        ctx.session_run_id = f"{os.getpid()}_{uuid.uuid4().hex[:8]}"
    base_dir = getattr(ctx, "meter_dir", getattr(ctx, "PGMSubDir", "."))
    base_dir = os.path.join(base_dir, "logs")
    os.makedirs(base_dir, exist_ok=True)
    fn = os.path.join(base_dir, f"loadmeter_{ctx.session_start_ts}_{ctx.session_run_id}.json")
    init = {"rows": {}, "queue": {"pending": 0, "running": 0}}
    atomic_write_json(fn, init)
    return fn


def meter_init(meter_fn, ctx, low=None, high=None):
    low = low if low is not None else getattr(ctx, "n_process", 4) * 2
    high = high if high is not None else getattr(ctx, "n_process", 4) * 3
    data = {
        "session_id": getattr(ctx, "session_start_ts", ""),
        "session_run_id": getattr(ctx, "session_run_id", ""),
        "pid": os.getpid(),
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "thresholds": {"low": low, "high": high},
        "workers": {"n_process": getattr(ctx, "n_process", 4)},
        "queue": {"pending": 0, "running": 0, "completed": 0},
        "rows": {},
    }
    atomic_write_json(meter_fn, data)
    return data


def meter_read(meter_fn):
    # 讀取時容忍 PermissionError/半寫入狀態
    return robust_json_read(
        meter_fn,
        default_factory=lambda: {"rows": {}, "queue": {"pending": 0, "running": 0}},
        retries=20,
        delay=0.05,
    )


def meter_update(meter_fn: str, mutator):
    lock = _lock_path(meter_fn)
    fd = _acquire_file_lock(lock)
    try:
        if fd is None:
            time.sleep(0.05)
            fd = _acquire_file_lock(lock)
            if fd is None:
                return meter_read(meter_fn)

        d = meter_read(meter_fn)
        if not isinstance(d, dict):
            d = {"rows": {}, "queue": {"pending": 0, "running": 0}}
        mutator(d)
        atomic_write_json(meter_fn, d)
        return d
    finally:
        if fd is not None:
            _release_file_lock(fd, lock)


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
    for _ in range(retries):
        try:
            os.unlink(path)
            return
        except FileNotFoundError:
            return
        except PermissionError:
            time.sleep(delay)
        except OSError as e:
            if e.errno in (errno.EBUSY, errno.ETXTBSY):
                time.sleep(delay)
            else:
                return


def find_item_dir_for(ctx, main_file_name: str) -> str:
    """
    從 ctx.prompt_dir 掃描出對應的 item 目錄（父級，底下有 TODO/Success）。
    """
    candidates = []
    for f in _oswalk_files(ctx.prompt_dir):
        parts = _normalized_parent_path(f).split("/")
        if parts[-1] in ["TODO", "Success"]:
            parent = "/".join(parts[:-1])
            parent_name = Path(parent).name
            if parent_name == main_file_name or parent_name.startswith(f"{main_file_name}_"):
                candidates.append(parent)
    uniq = list(set(candidates))
    if not uniq:
        raise RuntimeError(f"找不到 item 目錄：{main_file_name}")
    return uniq[0]
