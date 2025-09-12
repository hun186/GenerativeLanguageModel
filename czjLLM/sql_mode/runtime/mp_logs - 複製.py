# sql_mode/mp_logs.py
import multiprocessing as mp, threading
import queue as pyqueue
from tqdm import tqdm
from ..utils.term_lock import TQDM_LOCK
import re
import time
import collections

# 偵測 tqdm 進度列樣式（避免把它們重新寫回主控台）
_TQDM_BAR_RE = re.compile(r'^\s*\d+%?\|[^\n]*\|\s*\d+/\d+\s*\[[^\]]*\]')

def start_mp_log_listener_fail():
    q = mp.Queue()
    stop_ev = threading.Event()

    def _listener(q_, stop_):
        last_seen_ts = {}
        window = collections.deque(maxlen=128)

        while not stop_.is_set():
            try:
                line = q_.get(timeout=0.2)
            except pyqueue.Empty:
                continue

            s = str(line).rstrip()
            # 1) 丟掉 tqdm 樣式的行
            if _TQDM_BAR_RE.match(s):
                continue

            # 2) 0.5 秒內的重複訊息去重
            key = s[:200]
            now = time.time()
            ts = last_seen_ts.get(key)
            if ts is not None and (now - ts) < 0.5:
                continue
            last_seen_ts[key] = now
            window.append(key)

            try:
                with TQDM_LOCK:
                    tqdm.write(s)
            except Exception as ex:
                print("ex",ex)
                pass

    th = threading.Thread(target=_listener, args=(q, stop_ev), daemon=True)
    th.start()
    return q, stop_ev, th

def start_mp_log_listener_fail2():
    import threading, multiprocessing as mp
    import queue as pyqueue
    import time, re
    from tqdm import tqdm

    q = mp.Queue()
    stop_ev = threading.Event()

    # 簡易辨識 tqdm bar 的 Regex（避免把 bar 自己的行再寫出來亂版）
    TQDM_BAR_RE = re.compile(r"^\s*\d+%?\|[^\n]*\|")
    # 不用 tqdm.get_lock()（不是所有版本都有）；用 thread-local 鎖即可
    LOCK = threading.Lock()

    def _listener(q_, stop_):
        last_seen_ts = {}

        while not stop_.is_set():
            try:
                line = q_.get(timeout=0.2)
            except pyqueue.Empty:
                continue
            try:
                s = str(line).rstrip()

                # 1) 過濾 tqdm bar 行
                if TQDM_BAR_RE.match(s):
                    continue

                # 2) 0.5 秒內的重複訊息去重（避免瘋狂刷同一句）
                key = s[:200]
                now = time.time()
                ts = last_seen_ts.get(key)
                if ts is not None and (now - ts) < 0.5:
                    continue
                last_seen_ts[key] = now

                with LOCK:
                    tqdm.write(s)
            except Exception as ex:
                # 無論任何問題都不能讓 listener 掛掉
                print("ex",ex)
                pass

    th = threading.Thread(target=_listener, args=(q, stop_ev), daemon=True)
    th.start()
    return q, stop_ev, th
    
def start_mp_log_listener():
    """啟動子程序 stdout/stderr 轉發器，回傳 (q, stop_ev, thread)。"""
    #import multiprocessing as mp
    import threading
    q = mp.Queue()
    stop_ev = threading.Event()

    def _mp_log_listener(q_, stop_):
        #import queue as pyqueue
        while not stop_.is_set():
            try:
                line = q_.get(timeout=0.2)
            except pyqueue.Empty:
                continue
            try:
                # 用 tqdm.write 不會破壞進度條
                #from tqdm import tqdm
                tqdm.write(str(line))
            except Exception as ex:
                print(f"Error in start_mp_log_listener:{ex}")
                pass

    th = threading.Thread(target=_mp_log_listener, args=(q, stop_ev), daemon=True)
    th.start()
    return q, stop_ev, th

def stop_mp_log_listener(q, stop_ev, th):
    try: stop_ev.set()
    except Exception: pass
    try:
        if th.is_alive(): th.join(timeout=1.0)
    except Exception: pass
    try: q.cancel_join_thread()
    except Exception: pass
    try: q.close()
    except Exception: pass