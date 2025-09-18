import sys
import os

def draw_progress_bar_old(current, total, msg="", bar_length=40):
    percent = current / total
    arrow = '█' * int(round(percent * bar_length))
    spaces = '-' * (bar_length - len(arrow))
    bar = f"[{arrow}{spaces}] {current}/{total}次 ({percent*100:.0f}%) {msg}"

    try:
        term_width = os.get_terminal_size().columns
    except OSError:
        term_width = 120  # fallback 寬度（在非終端環境下）

    if len(bar) > term_width:
        bar = bar[:term_width]
    else:
        bar = bar.ljust(term_width)

    #sys.stdout.write('\r' + bar)
    sys.stdout.write('\r\033[K' + bar)
    sys.stdout.flush()
    
    
def draw_progress_bar(current, total, msg="", bar_length=40, min_bar_length=5):
    percent = current / total

    try:
        term_width = os.get_terminal_size().columns
    except OSError:
        term_width = 120  # fallback 終端寬度

    # 預估文字開銷（例如 30/360次 (12%) 會用掉約 15~20 字元）
    static_info = f"{current}/{total}次 ({percent*100:.0f}%)"
    fixed_prefix = "[]  "  # 進度條左右加空格
    space_for_bar = term_width - len(fixed_prefix) - len(static_info) - len(msg) - 1

    # 自動調整 bar 長度，保留最小長度
    bar_len = max(min_bar_length, min(bar_length, space_for_bar))
    #bar_len = 4
    # 構建 bar
    arrow = '█' * int(round(percent * bar_len))
    spaces = '-' * (bar_len - len(arrow))
    bar = f"[{arrow}{spaces}] {static_info} {msg}"

    # 清尾補空白，避免殘影
    bar = bar.ljust(term_width)
    sys.stdout.write('\r\033[K' + bar)
    sys.stdout.flush()