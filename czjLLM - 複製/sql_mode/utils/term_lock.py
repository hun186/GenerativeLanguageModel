import threading

# 嘗試多種 import 方式；若失敗就回退到 RLock
try:
    from tqdm import tqdm as _tqdm_cls
    TQDM_LOCK = _tqdm_cls.get_lock()
except Exception:
    try:
        import tqdm as _tqdm_mod
        TQDM_LOCK = _tqdm_mod.tqdm.get_lock()
    except Exception:
        TQDM_LOCK = threading.RLock()