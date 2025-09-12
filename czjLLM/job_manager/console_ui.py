# console_ui.py
import io, sys, time, queue, logging
import threading
from threading import RLock, Thread
from tqdm import tqdm
from tqdm.contrib.logging import logging_redirect_tqdm
from colorama import Fore, Style

from typing import Callable, List
import re

# 讓 tqdm 多緒安全
tqdm.set_lock(RLock())




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


'''
def _emit(level: str, line: str, *, stream, color=""):
    if line is None:
        return
    line = line.rstrip("\r\n")
    if not line.strip():
        return
    # 過濾/縮寫（若有安裝 _CONSOLE_FILTERS）
    try:
        line2 = _CONSOLE_FILTERS.apply(line)
        if line2 is None or line2 == "":
            return
        line = line2
    except NameError:
        pass

    # 1) 主控台輸出（tqdm-safe）
    tqdm.write((color or "") + line + Style.RESET_ALL, file=stream)

    # 2) 廣播到所有 sinks（無 ANSI、純文字）
    msg_plain = _strip_ansi(line)
    with _SINK_LOCK:
        for sink in list(_SINKS):
            try:
                sink(level, msg_plain)
            except Exception:
                # 單一 sink 出錯不影響其他
                pass

def tlog(msg: str):      _emit("INFO",  str(msg), stream=_REAL_STDOUT, color=Fore.CYAN)
def tlog_ok(msg: str):   _emit("OK",    str(msg), stream=_REAL_STDOUT, color=Fore.GREEN)
def tlog_warn(msg: str): _emit("WARN",  str(msg), stream=_REAL_STDOUT, color=Fore.YELLOW)
def tlog_err(msg: str):  _emit("ERROR", str(msg), stream=_REAL_STDERR, color=Fore.RED)
'''
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
def setup_console_ui(total_rows: int, ncols: int = 90):
    """
    回傳 (p_sched, p_done, restore_fn)
    - p_sched：排程(切片/入佇列)
    - p_done ：完成(合併+寫回)
    - restore_fn：收尾時還原 stdout/stderr/logging
    """
    import time, threading

    # 讓 {postfix} 不帶任何前綴，避免出現 " | ," 這類重複符號
    bar_fmt = "{l_bar}{bar} | {n_fmt}/{total_fmt} [{elapsed}<{remaining}, {rate_fmt}]{postfix}"

    p_sched = tqdm(total=total_rows,
                   desc=Fore.LIGHTYELLOW_EX + "排程進度(切片/入佇列)" + Style.RESET_ALL,
                   position=0, leave=False, ncols=ncols, colour="yellow",
                   bar_format=bar_fmt, unit="列", mininterval=0.1)

    p_done = tqdm(total=total_rows,
                  desc=Fore.LIGHTYELLOW_EX + "完成進度(合併+寫回)" + Style.RESET_ALL,
                  position=1, leave=True, ncols=ncols, colour="yellow",
                  bar_format=bar_fmt, unit="列", mininterval=0.1)

    # --- ETA 背景更新：指數平滑降抖動 ---
    _ALPHA = 0.30
    eta_stop = threading.Event()

    def _make_state(pbar):
        now = time.time()
        return {"t0": now, "last_t": now, "last_n": pbar.n, "rate_ema": 0.0}

    st_sched = _make_state(p_sched)
    st_done  = _make_state(p_done)

    def _step(state, pbar):
        now = time.time()
        dt = max(1e-6, now - state["last_t"])
        dn = max(0, pbar.n - state["last_n"])
        inst_rate = dn / dt if dn > 0 else 0.0
        if inst_rate > 0:
            if state["rate_ema"] <= 0:
                state["rate_ema"] = inst_rate
            else:
                state["rate_ema"] = (1 - _ALPHA) * state["rate_ema"] + _ALPHA * inst_rate
        state["last_t"] = now
        state["last_n"] = pbar.n

        rate = state["rate_ema"]
        if (pbar.total and rate > 0):
            remain = max(0.0, (pbar.total - pbar.n) / rate)
            eta_ts = now + remain
            eta_str = time.strftime("%H:%M:%S", time.localtime(eta_ts))
            # 只顯示 ETA（速率已在 {rate_fmt}）
            pbar.set_postfix_str(f" ETA {eta_str}", refresh=False)
        else:
            pbar.set_postfix_str("", refresh=False)

    def _eta_loop():
        while not eta_stop.is_set():
            try:
                _step(st_sched, p_sched)
                _step(st_done,  p_done)
            except Exception:
                pass
            time.sleep(0.5)  # 每 0.5 秒更新一次

    eta_th = threading.Thread(target=_eta_loop, name="tqdm-eta", daemon=True)
    eta_th.start()

    # 把 print/logging 安全導向 tqdm（輸出寫到原生 stream，避免遞迴）
    stdout_bak, stderr_bak = sys.stdout, sys.stderr
    sys.stdout = _StdToTqdm(_REAL_STDOUT, level="INFO")
    sys.stderr = _StdToTqdm(_REAL_STDERR, level="AUTO")

    log_ctx = logging_redirect_tqdm()
    log_ctx.__enter__()

    def restore():
        # 停止 ETA 背景執行緒
        try:
            eta_stop.set()
            eta_th.join(timeout=1.0)
        except Exception:
            pass
        # flush 並還原 logging / streams
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

    return p_sched, p_done, restore


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

def tlog(msg):      _emit("INFO",  str(msg), stream=_REAL_STDOUT)
def tlog_ok(msg):   _emit("OK",    str(msg), stream=_REAL_STDOUT)
def tlog_warn(msg): _emit("WARN",  str(msg), stream=_REAL_STDOUT)
def tlog_err(msg):  _emit("ERROR", str(msg), stream=_REAL_STDERR)

def clear_log_sinks() -> None:
    with _SINK_LOCK:
        _SINKS.clear()