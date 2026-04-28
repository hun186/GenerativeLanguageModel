# utilities/file_utils.py
import os, hashlib, uuid

def _ensure_dir(path: str):
    """確保資料夾存在（跨緒/跨程序安全：exist_ok=True）。"""
    os.makedirs(path, exist_ok=True)
    return path

def save_text_as_temp_file(text: str, base_dir: str, index: int,
                           *, prefix: str = "excel_input", ext: str = ".txt",
                           row_key: object | None = None) -> str:
    """
    在 base_dir 產生唯一檔名並寫入文字：
    - 會先建立 base_dir（避免 FileNotFoundError）
    - 檔名：{prefix}_{index}_{hash8}.{ext}
    - 含一次 FileNotFoundError 的重試（處理極端時序）
    """
    # 正規化 + 建立資料夾
    base_dir = os.path.normpath(os.path.abspath(base_dir))
    _ensure_dir(base_dir)

    # 內容雜湊避免過長檔名；失敗就用 uuid 退回
    try:
        h = hashlib.md5(text.encode("utf-8")).hexdigest()[:8]
    except Exception:
        h = uuid.uuid4().hex[:8]

    safe_row_key = ""
    if row_key is not None:
        try:
            raw = str(row_key).strip()
            if raw:
                safe = "".join(ch if (ch.isalnum() or ch in ("-", "_")) else "_" for ch in raw)
                safe_row_key = safe[:64]
        except Exception:
            safe_row_key = ""

    name_parts = [prefix, str(index)]
    if safe_row_key:
        name_parts.append(safe_row_key)
    name_parts.append(h)
    filename = os.path.join(base_dir, f"{'_'.join(name_parts)}{ext}")

    # 極端情況下父目錄可能被外部刪掉，這裡加一次重試
    for attempt in (1, 2):
        try:
            _ensure_dir(os.path.dirname(filename))
            with open(filename, "w", encoding="utf-8", newline="") as f:
                f.write(text)
            return filename
        except FileNotFoundError:
            if attempt == 2:
                raise  # 第二次還失敗就讓呼叫端看到錯誤

    return filename  # 理論上到不了這行
