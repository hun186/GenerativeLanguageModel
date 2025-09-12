import os
from utils.MP_utils import MPlogger

def CostLog(PGMSubDir = "", ArtCost=dict(),item="",costList=[],mode="singleArt"):
    ArtC = sum(costList)
    if mode == "singleArt":
        with open(os.path.join(PGMSubDir,"logs","CostRec.tsv"),'at',encoding='utf-8') as fp:
            fp.write(f"{item}\t{ArtC:.5f}\n")
        MES = f'{"☆"*50}\n處理{item} 花費新臺幣 {ArtC:.3f}元\n{"☆"*50}'
        ArtCost[item] = ArtC
    elif mode == "AllArt":
        MES = f'{"✯"*50}\n此次批次共處理{len(costList)}個物件，共花費新臺幣 {ArtC:.3f}元\n{"✯"*50}'
    MPlogger(os.path.join(PGMSubDir,"logs"),logFile="CostRec.log").logW(MES=MES)
    return ArtCost

def log_error(idx: int, reason: str, log_path: str):
    """
    記錄 Excel 某列處理失敗的錯誤資訊
    """
    err_msg = f"[第 {idx} 列] 處理失敗：{reason}"
    print(f"\033[91m{err_msg}\033[0m")  # 紅色輸出
    with open(log_path, "a", encoding="utf-8") as logf:
        logf.write(err_msg + "\n")