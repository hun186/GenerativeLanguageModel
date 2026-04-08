#czjLLM\utilities\path_utils.py
import os
from pathlib import Path
import sys
from typing import Any, Dict, Iterable, Optional
import re
import hashlib
from utils.utilities_path import DirReplace, MKDIR, getMFNFromFN

def init_project_root(target="PackageImport.py", max_levels=10):
    current = Path(__file__).resolve().parent
    for _ in range(max_levels):
        if (current / target).exists():
            sys.path.insert(0, str(current))
            print(f"✔ 模組路徑已加入：{current}")
            return current
        current = current.parent
    raise FileNotFoundError(f"無法在 {max_levels} 層內找到 {target}")
    
def llm_channel_dir(base_dir: Path, channel: str, variant: str = "") -> Path:
    """
    建立 LLMSource 的子資料夾路徑。
    variant: 可為 "", "_origin_backup", "_Finished"
    """
    folder_name = f"LLMSourcePool{variant}"
    return base_dir / folder_name / channel


def _norm(p):  # 小工具：正規化路徑（大小寫無關、分隔一致）
    return os.path.normcase(os.path.normpath(p)) if p else ""

def get_relative_parent_path(file_path: str, root_dir: str) -> str:
    """
    取得 file_path 相對於 root_dir 的父層路徑。
    - 若 file_path 不在 root_dir 之下，回傳空字串
    - 若檔案位於 root_dir 根層，回傳空字串
    """
    root_dir = str(root_dir or "").strip()
    if not root_dir:
        return ""
    try:
        root_abs = os.path.abspath(root_dir)
        file_abs = os.path.abspath(file_path)
        if os.path.commonpath([root_abs, file_abs]) != root_abs:
            return ""
        rel_file = os.path.relpath(file_abs, root_abs)
    except Exception:
        return ""
    rel_parent = os.path.dirname(rel_file).strip()
    if not rel_parent or rel_parent in {".", os.curdir}:
        return ""
    return rel_parent

def safe_task_suffix(task: str, max_len: int = 96) -> str:
    """
    任務名安全化 + 長度保護：
    - 移除非法字元
    - 空白轉底線
    - 超長時截斷並附加 hash，避免檔名過長
    """
    cleaned = re.sub(r'[\\/:*?"<>|]+', "_", str(task or "")).strip()
    cleaned = re.sub(r"\s+", "_", cleaned).strip("._") or "result"
    if len(cleaned) <= max_len:
        return cleaned
    digest = hashlib.sha1(cleaned.encode("utf-8")).hexdigest()[:10]
    head_len = max(16, max_len - 11)  # 保留 "_" + 10碼 hash
    return f"{cleaned[:head_len]}_{digest}"

def get_combined_result_path(temp_txt_path: str, ctx) -> str:
    """
    以你原本邏輯為主，但：
    1) 先檢查 SrcDir 是否真的是 FilePath 的前綴，不是就走 fallback
    2) fallback 會用 llm_source_finished_dir\cache，最後才 LLMSourcePool -> LLMSourcePool_Finished
    3) sanitize task 名稱 + MKDIR 目標資料夾
    """
    #print("[gcrp] temp_txt_path=", temp_txt_path)
    #print("[gcrp] ctx.temp_txt_dir=", getattr(ctx,"temp_txt_dir", None))
    #print("[gcrp] ctx.temp_txt_finished_dir=", getattr(ctx,"temp_txt_finished_dir", None))
    main = getMFNFromFN(temp_txt_path)
    task = str(getattr(ctx, "task", "result"))
    safe_task = safe_task_suffix(task, max_len=96)

    file_path = _norm(temp_txt_path)
    src_dir   = _norm(getattr(ctx, "temp_txt_dir", ""))
    des_dir   = _norm(getattr(ctx, "temp_txt_finished_dir", ""))

    out_full = None

    # 先嘗試你原本的 DirReplace（成功機率最高）
    if src_dir and des_dir and file_path.startswith(src_dir):
        try:
            replaced = DirReplace(FilePath=temp_txt_path,
                                  SrcDir=getattr(ctx,"temp_txt_dir",""),
                                  DesDir=getattr(ctx,"temp_txt_finished_dir",""))
            out_full = os.path.splitext(replaced)[0] + f"_{safe_task}.txt"
        except Exception:
            out_full = None

    # Fallback 1：llm_source_finished_dir\cache
    if not out_full:
        lsd = getattr(ctx, "llm_source_finished_dir", None)
        if lsd:
            base = os.path.join(lsd, "cache")
            MKDIR(base)
            out_full = os.path.join(base, f"{main}_{safe_task}.txt")

    # Fallback 2：把 ...\LLMSourcePool\... 換成 ...\LLMSourcePool_Finished\...（仍放到 cache）
    if not out_full:
        parts = file_path.split(os.sep)
        try:
            i = parts.index("llmsourcepool")  # 已 normcase
            parts[i] = "LLMSourcePool_Finished"
            # i+1 位置通常是來源類型（如 excel_source），保留原層級
            rebuilt = os.path.join(*parts[:i+2])  # LLMSourcePool_Finished\excel_source
            base = os.path.join(rebuilt, "cache")
            MKDIR(base)
            out_full = os.path.join(base, f"{main}_{safe_task}.txt")
        except ValueError:
            # 最終保底：放在 temp 同層的 cache
            base = os.path.join(os.path.dirname(os.path.dirname(temp_txt_path)), "cache")
            MKDIR(base)
            out_full = os.path.join(base, f"{main}_{safe_task}.txt")

    # 確保目錄存在
    MKDIR(os.path.dirname(out_full))
    return out_full

def get_combined_result_path_old(temp_txt_path: str, ctx) -> str:
    """
    根據暫存 txt 路徑與 ctx，取得合併後輸出的檔案路徑
    """
    from utils.utilities_path import DirReplace
    result_path = DirReplace(
        FilePath=temp_txt_path,
        #SrcDir=ctx.llm_source_dir,
        #DesDir=ctx.llm_source_finished_dir
        SrcDir=ctx.temp_txt_dir,
        DesDir=ctx.temp_txt_finished_dir
    )
    result_path = os.path.splitext(result_path)[0] + f"_{ctx.task}.txt"
    return result_path
