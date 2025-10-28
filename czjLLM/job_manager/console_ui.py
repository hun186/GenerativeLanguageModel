# console_ui.py
import io, sys, time, queue, logging
import threading
from threading import RLock, Thread
from tqdm import tqdm
from tqdm.contrib.logging import logging_redirect_tqdm
from colorama import Fore, Style
from datetime import datetime, timedelta
from typing import Callable, List
import re

# 讓 tqdm 多緒安全
tqdm.set_lock(RLock())

# 記錄主執行緒 id：僅主執行緒能用 tqdm.write，其他執行緒改走原生 stream
_MAIN_TID = threading.get_ident()


# 1) 移除真正的 ANSI/OSC/單字元 ESC
_ANSI_ALL = re.compile(
    r'(?:\x1b\[[0-?]*[ -/]*[@-~]'          # CSI
    r'|\x1b\][^\x07]*(?:\x07|\x1b\\)'      # OSC
    r'|\x1b[@-_])'                         # 單字元 ESC
)

# 2) 兼容「文字版 ESC」與 caret 代碼（例如： "ESC [A"、"^[A"、"^[[2K"）
_ESC_WORD = re.compile(r'(?:^|\s)ESC\s*\[[0-9;?]*[ -/]*[@-~]?', re.IGNORECASE)
_CARET_SEQ = re.compile(r'\^\[(?:\[[0-9;?]*[ -/]*[@-~]|[0-9;?]*[A-Za-z])')

def _sanitize_terminal(s: str) -> str:
    """去除所有終端控制碼變體：ANSI、OSC、'ESC [A'、'^[[A' 等，並移除 '\r'。"""
    if not s:
        return s
    s = _ANSI_ALL.sub('', s).replace('\r', '')
    s = _ESC_WORD.sub('', s)
    s = _CARET_SEQ.sub('', s)
    return s


# 簡單的錯誤訊息偵測（大小寫不敏感）
_ERROR_PAT = re.compile(r'(?i)\b(traceback|exception|error|critical|fatal)\b')
def _looks_like_error(line: str) -> bool:
    return bool(_ERROR_PAT.search(line))

# 顏色對照（主控台用；GUI sink 會收到無 ANSI 的純文字）
_LEVEL_COLOR = {
    "ERROR": Fore.RED,
    "WARN":  Fore.YELLOW,
    "OK":    Fore.GREEN,
    "INFO":  Fore.CYAN,
    #"INFO":  Fore.WHITE,
}




# 可選：你的過濾器（若無，讓它 pass）
try:
    _ = _CONSOLE_FILTERS
except NameError:
    class _NoopFilter:
        def apply(self, line: str): return line
    _CONSOLE_FILTERS = _NoopFilter()

# ---- 把 print 重導到 tqdm.write（可選，但很實用）----
_REAL_STDOUT = sys.__stdout__
_REAL_STDERR = sys.__stderr__

class _StdToTqdm(io.TextIOBase):
    def __init__(self, real_stream, level="INFO"):
        self._real = real_stream
        self._level = level            # "INFO" / "ERROR" / "AUTO"
        self._buf = []
        self._lock = RLock()
        self._max_buf_bytes = 4096

    @property
    def encoding(self):
        return getattr(self._real, "encoding", "utf-8")

    def _eff_level(self, text_line: str) -> str:
        if self._level != "AUTO":
            return self._level
        return "ERROR" if _looks_like_error(text_line) else "INFO"

    def write(self, s):
        if not s: return 0
        with self._lock:
            s = str(s).replace("\r\n", "\n").replace("\r", "\n")
            self._buf.append(s)
            joined = "".join(self._buf)
            if "\n" in joined:
                parts = joined.split("\n")
                self._buf = [parts[-1]]
                for line in parts[:-1]:
                    lvl = self._eff_level(line)
                    _emit(lvl, line, stream=self._real)
            else:
                if len(joined) >= self._max_buf_bytes:
                    self._buf = []
                    lvl = self._eff_level(joined)
                    _emit(lvl, joined, stream=self._real)
            return len(s)

    def flush(self):
        with self._lock:
            if self._buf:
                pending = "".join(self._buf)
                self._buf = []
                if pending.strip():
                    lvl = self._eff_level(pending)
                    _emit(lvl, pending, stream=self._real)
            try:
                self._real.flush()
            except Exception:
                pass

    def isatty(self): return True
    def readable(self): return False
    def writable(self): return True
    def seekable(self): return False

# ---- 建立兩條「相鄰」的進度條 + 安全輸出 ----
# ---- 建立兩條「相鄰」的進度條 + 安全輸出 ----
def setup_console_ui(total_rows: int, ncols: int = 90):
    import time, threading
    from threading import RLock
    from tqdm import tqdm

    #bar_fmt = "{l_bar}{bar} | {n_fmt}/{total_fmt} [{elapsed}<{remaining}, {rate_fmt}]{postfix}"
    bar_fmt = "{l_bar}{bar} | {n_fmt}/{total_fmt} [{elapsed}, {rate_fmt}]{postfix}"

    p_sched = tqdm(total=total_rows,
                   desc=Fore.LIGHTYELLOW_EX + "排程進度(切片/入佇列)" + Style.RESET_ALL,
                   position=0, leave=False, ncols=ncols, colour="yellow",
                   bar_format=bar_fmt, unit="列", mininterval=0.1)

    p_done = tqdm(total=total_rows,
                  desc=Fore.LIGHTYELLOW_EX + "完成進度(合併+寫回)" + Style.RESET_ALL,
                  position=1, leave=True, ncols=ncols, colour="yellow",
                  bar_format=bar_fmt, unit="列", mininterval=0.1)

    _ALPHA = 0.30
    eta_stop = threading.Event()

    # ★ 共享鎖：保護「讀寫 pbar 屬性」與「刷新」免於競態
    _bars_lock = RLock()  # tqdm.set_lock 只保護其內部 print，這把鎖保護你的邏輯

    # ★ 安全刷新：變更 total 後一定要觸發重繪
    def _safe_refresh(pbar):
        try:
            pbar.update(0)
            pbar.refresh()
        except Exception:
            pass

    def _make_state(pbar):
        now_mono = time.perf_counter()
        return {
            "last_t_mono": now_mono,
            "last_n": pbar.n or 0,
            "tpu_ema": -1.0,
            "last_eta_str": "",
        }

    def _step(state, pbar, _ALPHA=0.30):
        now_mono = time.perf_counter()
        dn = pbar.n - state["last_n"]
        if dn > 0:
            dt = max(1e-9, now_mono - state["last_t_mono"])
            inst_tpu = dt / max(1, dn)
            tpu_ema = state["tpu_ema"]
            state["tpu_ema"] = inst_tpu if tpu_ema <= 0 else (1 - _ALPHA) * tpu_ema + _ALPHA * inst_tpu
            state["last_t_mono"] = now_mono
            state["last_n"] = pbar.n
    
        tpu = state["tpu_ema"]
        if pbar.total and tpu > 0:
            remain_sec = max(0.0, (pbar.total - pbar.n) * tpu)
            eta_dt = datetime.now().astimezone() + timedelta(seconds=remain_sec)
            eta_str = eta_dt.strftime("%H:%M:%S")
            state["last_eta_str"] = eta_str
            pbar.set_postfix_str(f" ETA {eta_str}", refresh=(dn > 0))
        else:
            pbar.set_postfix_str(f" ETA {state['last_eta_str']}", refresh=False)

    # ★ 別漏這兩行（你上一版貼的程式碼裡看不到）
    st_sched = _make_state(p_sched)
    st_done  = _make_state(p_done)

    def _eta_loop():
        while not eta_stop.is_set():
            try:
                # ★ 背景讀/寫 pbar（含 postfix）時加鎖，避免與 set_total 競態
                with _bars_lock:
                    _step(st_sched, p_sched)
                    _step(st_done,  p_done)
            except Exception as e:
                # 不要吞錯，至少留一行可診斷
                tqdm.write(f"[ETA] {type(e).__name__}: {e}")
            time.sleep(0.5)

    eta_th = threading.Thread(target=_eta_loop, name="tqdm-eta", daemon=True)
    eta_th.start()

    # ★ 提供一個對外 API：在切片總數改變時呼叫它
    def set_total(which: str, new_total: int):
        """
        which: 'sched' | 'done' | 'both'
        new_total: 新的總列數（不可小於當前進度 n）
        """
        with _bars_lock:
            targets = []
            if which in ('sched', 'both'): targets.append(p_sched)
            if which in ('done',  'both'): targets.append(p_done)
            for bar in targets:
                bar.total = max(int(new_total), int(bar.n))  # 防止 n > total
                _safe_refresh(bar)

    # 安全導向 stdout/stderr 與 logging（維持你原本的做法）
    stdout_bak, stderr_bak = sys.stdout, sys.stderr
    sys.stdout = _StdToTqdm(_REAL_STDOUT, level="INFO")
    sys.stderr = _StdToTqdm(_REAL_STDERR, level="AUTO")
    log_ctx = logging_redirect_tqdm(); log_ctx.__enter__()

    def restore():
        try:
            eta_stop.set(); eta_th.join(timeout=1.0)
        except Exception:
            pass
        try:
            sys.stdout.flush(); sys.stderr.flush()
        except Exception:
            pass
        try:
            log_ctx.__exit__(None, None, None)
        except Exception:
            pass
        sys.stdout, sys.stderr = stdout_bak, stderr_bak
        try:
            p_sched.close(); p_done.close()
        except Exception:
            pass

    # ★ 多回傳一個 set_total，方便外部在實際總數變動時同步兩條 bar
    return p_sched, p_done, restore, set_total



def setup_console_ui_OLD(total_rows: int, ncols: int = 90):
    """
    回傳 (p_sched, p_done, restore_fn)
    - p_sched：排程(切片/入佇列)
    - p_done ：完成(合併+寫回)
    - restore_fn：收尾時還原 stdout/stderr/logging
    """
    # 兩條條形圖固定 0/1 位置，皆為黃字
    p_sched = tqdm(total=total_rows,
                   desc=Fore.LIGHTYELLOW_EX + "排程進度(切片/入佇列)" + Style.RESET_ALL,
                   position=0, leave=False, ncols=ncols, colour="yellow",
                   bar_format="{l_bar}{bar} | {n_fmt}/{total_fmt} [{elapsed}<{remaining}]",
                   unit="列", mininterval=0.1)
    
    p_done = tqdm(total=total_rows,
                  desc=Fore.LIGHTYELLOW_EX + "完成進度(合併+寫回)" + Style.RESET_ALL,
                  position=1, leave=True, ncols=ncols, colour="yellow",
                  bar_format="{l_bar}{bar} | {n_fmt}/{total_fmt} [{elapsed}<{remaining}]",
                  unit="列", mininterval=0.1)


    # 把 print/logging 安全導向 tqdm（但輸出寫到原生 stream，避免遞迴）
    stdout_bak, stderr_bak = sys.stdout, sys.stderr
    sys.stdout = _StdToTqdm(_REAL_STDOUT, level="INFO")
    sys.stderr = _StdToTqdm(_REAL_STDERR, level="AUTO")   # 由內容決定 ERROR/INFO

    log_ctx = logging_redirect_tqdm()  # logging.* → tqdm.write（內部也會避開干擾進度條）

    # 進入 logging redirect
    log_ctx.__enter__()

    def restore():
        # 先把包裝器 flush 到原生流
        try:
            sys.stdout.flush()
            sys.stderr.flush()
        except Exception:
            pass
        # 還原 logging 與 std streams
        try:
            log_ctx.__exit__(None, None, None)
        except Exception:
            pass
        sys.stdout, sys.stderr = stdout_bak, stderr_bak
        try:
            p_sched.close(); p_done.close()
        except Exception:
            pass

    return p_sched, p_done, restore


'''
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")

def _strip_ansi(s: str) -> str:
    return _ANSI_RE.sub("", s)
'''

# 全域 sink 註冊表
#_SINKS: List[Callable[[str, str], None]] = []  # (level, message) -> None
_SINKS = []
_SINK_LOCK = RLock()

def add_log_sink(sink): 
    with _SINK_LOCK:
        if sink not in _SINKS: _SINKS.append(sink)
def remove_log_sink(sink):
    with _SINK_LOCK:
        if sink in _SINKS: _SINKS.remove(sink)

def _emit(level: str, line: str, *, stream):
    '''
    if line is None: return
    line = line.rstrip("\n")
    if not line.strip(): return

    # 過濾器（若你有 _CONSOLE_FILTERS）
    try:
        line2 = _CONSOLE_FILTERS.apply(line)
        if not line2: return
        line = line2
    except NameError:
        pass

    # 主控台輸出（彩色）
    color = _LEVEL_COLOR.get(level, "")
    tqdm.write(f"{color}{line}{Style.RESET_ALL}", file=stream)

    # 廣播到 sinks（去除 ANSI）
    #plain = _strip_ansi(line).strip()
    plain = _sanitize_terminal(line).strip()

    if not plain:
        return
    with _SINK_LOCK:
        for sink in list(_SINKS):
            try:
                sink(level, plain)
            except Exception:
                pass
    '''
    if line is None: return
    line = line.rstrip("\n")
    if not line.strip(): return

    # 過濾器（若你有 _CONSOLE_FILTERS）
    try:
        line2 = _CONSOLE_FILTERS.apply(line)
        if not line2: return
        line = line2
    except NameError:
        pass

    # 準備輸出內容（彩色）
    color = _LEVEL_COLOR.get(level, "")
    out = f"{color}{line}{Style.RESET_ALL}"

    # 僅主執行緒使用 tqdm.write，其餘執行緒改用原生 stream，避免 tqdm 內鎖互卡
    try:
        if threading.get_ident() == _MAIN_TID:
            tqdm.write(out, file=stream)
        else:
            stream.write(out + "\n")
            stream.flush()
    except Exception:
        # 最後防線，別讓寫出錯又阻塞
        try:
            _REAL_STDERR.write(out + "\n")
            _REAL_STDERR.flush()
        except Exception:
            pass

    # 廣播到 sinks（去除控制碼）
    plain = _sanitize_terminal(line).strip()
    if not plain:
        return
    with _SINK_LOCK:
        for sink in list(_SINKS):
            try:
                sink(level, plain)
            except Exception:
                pass
def tlog(msg):      _emit("INFO",  str(msg), stream=_REAL_STDOUT)
def tlog_ok(msg):   _emit("OK",    str(msg), stream=_REAL_STDOUT)
def tlog_warn(msg): _emit("WARN",  str(msg), stream=_REAL_STDOUT)
def tlog_err(msg):  _emit("ERROR", str(msg), stream=_REAL_STDERR)

def clear_log_sinks() -> None:
    with _SINK_LOCK:
        _SINKS.clear()