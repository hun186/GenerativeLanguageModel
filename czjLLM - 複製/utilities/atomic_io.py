# utilities/atomic_io.py
import os, json, tempfile, time
from typing import Any, Callable

def atomic_write_json(path: str, data, *, ensure_ascii=False, retries: int = 5, delay: float = 0.05):
    import json, os, time, tempfile
    dirname = os.path.dirname(path) or "."
    os.makedirs(dirname, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=os.path.basename(path) + ".tmp.", dir=dirname)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fp:
            json.dump(data, fp, ensure_ascii=ensure_ascii)
            fp.flush()
            os.fsync(fp.fileno())
        for i in range(retries):
            try:
                os.replace(tmp, path)
                return
            except PermissionError:
                time.sleep(delay * (i + 1))
        os.replace(tmp, path)  # 最後再試一次，還不行就丟出
    finally:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass
        
def atomic_write_json_OLD(path: str, data: Any, encoding: str = "utf-8") -> None:
    """先寫到同目錄 tmp，fsync 後 os.replace 原子覆蓋。"""
    d = os.path.dirname(path) or "."
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=os.path.basename(path)+".tmp.", dir=d)
    try:
        with os.fdopen(fd, "w", encoding=encoding) as f:
            json.dump(data, f, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)  # Windows 上也原子
    finally:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass

def robust_json_read(path: str,
                     default_factory: Callable[[], Any] = dict,
                     retries: int = 20,
                     delay: float = 0.05) -> Any:
    """讀檔遇到 PermissionError/JSONDecodeError 時短暫重試。"""
    last_err = None
    for _ in range(retries):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            return default_factory()
        except (PermissionError, json.JSONDecodeError) as e:
            last_err = e
            time.sleep(delay)
    # 最終保底
    return default_factory()
