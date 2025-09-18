#czjLLM\utilities\path_utils.py
import os
from pathlib import Path
import sys
from typing import Any, Dict, Iterable, Optional


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


def get_combined_result_path(temp_txt_path: str, ctx) -> str:
    """
    根據暫存 txt 路徑與 ctx，取得合併後輸出的檔案路徑
    """
    from utils.utilities_path import DirReplace
    result_path = DirReplace(
        FilePath=temp_txt_path,
        SrcDir=ctx.llm_source_dir,
        DesDir=ctx.llm_source_finished_dir
    )
    result_path = os.path.splitext(result_path)[0] + f"_{ctx.task}.txt"
    return result_path

