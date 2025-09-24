# czjLLM/utilities/logging_utils.py
from __future__ import annotations
import logging
from logging import Logger, FileHandler
from pathlib import Path
from typing import Dict, List, Optional

# 你原本用到的 MPlogger 還是保留；若不存在可拿掉
try:
    from utils.MP_utils import MPlogger  # pragma: no cover
except Exception:  # pragma: no cover
    MPlogger = None  # 減少在測試環境的依賴

def get_logger(
    name: str,
    log_file: Path | str,
    level: int = logging.INFO,
    fmt: str = "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    encoding: str = "utf-8",
    propagate: bool = False,
) -> Logger:
    """
    建立/取得一個綁定到特定檔案的 logger。
    - 會自動建立目錄
    - 避免重複加入相同檔案的 handler
    """
    log_path = Path(log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.propagate = propagate

    # 檢查是否已經有同一路徑的 FileHandler
    for h in logger.handlers:
        if isinstance(h, FileHandler):
            try:
                if Path(getattr(h, "baseFilename", "")).resolve() == log_path.resolve():
                    return logger
            except Exception:
                continue

    fh = logging.FileHandler(log_path, encoding=encoding, mode="a")
    fh.setLevel(level)
    fh.setFormatter(logging.Formatter(fmt))
    logger.addHandler(fh)
    return logger

def CostLog(
    PGMSubDir: str | Path = "",
    ArtCost: Optional[Dict[str, float]] = None,
    item: str = "",
    costList: Optional[List[float]] = None,
    mode: str = "singleArt",
) -> Dict[str, float]:
    """
    將花費寫入 TSV 與 log；修正了原本可變預設值（dict/list）造成的共享狀態風險。
    """
    ArtCost = ArtCost or {}
    costList = costList or []

    total = sum(costList)
    logs_dir = Path(PGMSubDir) / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    if mode == "singleArt":
        tsv = logs_dir / "CostRec.tsv"
        with tsv.open("a", encoding="utf-8") as fp:
            fp.write(f"{item}\t{total:.5f}\n")
        MES = f'{"☆"*50}\n處理{item} 花費新臺幣 {total:.3f}元\n{"☆"*50}'
        ArtCost[item] = total
    elif mode == "AllArt":
        MES = f'{"✯"*50}\n此次批次共處理{len(costList)}個物件，共花費新臺幣 {total:.3f}元\n{"✯"*50}'
    else:
        MES = f"未知模式 {mode}; 金額：{total:.3f}"

    # 若有 MPlogger 就用，否則退回到標準 logger
    if MPlogger:
        MPlogger(str(logs_dir), logFile="CostRec.log").logW(MES=MES)  # pragma: no cover
    else:
        lg = get_logger("cost", logs_dir / "CostRec.log")
        lg.info(MES)
    return ArtCost

def log_error(idx: int, reason: str, log_path: str | Path) -> None:
    """
    記錄 Excel 某列處理失敗的錯誤資訊
    """
    err_msg = f"[第 {idx} 列] 處理失敗：{reason}"
    print(f"\033[91m{err_msg}\033[0m")  # 紅色輸出
    Path(log_path).parent.mkdir(parents=True, exist_ok=True)
    with Path(log_path).open("a", encoding="utf-8") as logf:
        logf.write(err_msg + "\n")
