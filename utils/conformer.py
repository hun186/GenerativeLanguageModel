import time
import sys
import os
import psutil
from utils.progress_utils import draw_progress_bar
from utils.MP_utils import MPlogger
#from utils.utilities import GPU_mem_report  # 你自己已有的版本
import GPUtil

try:
    import humanize
    _use_humanize = True
except ImportError:
    _use_humanize = False

def format_bytes(mb: int) -> str:
    """
    將 MB 單位的數值轉換為人類可讀的格式，例如 '44.3GB' 或 '643MB'
    若有安裝 humanize 套件則使用，否則 fallback 為自訂格式。
    """
    if _use_humanize:
        return humanize.naturalsize(mb * 1024 * 1024, binary=True)
    else:
        if mb >= 1024:
            return f"{mb / 1024:.1f}GB"
        else:
            return f"{mb}MB"


def mem_report():
    memReport = psutil.virtual_memory()
    mem_report = {
        "total":memReport.total,
        "available":memReport.available,
        "used":memReport.used,
        }
    return mem_report

def GPU_mem_report(show_log=True):
    try:
        import pynvml
        pynvml.nvmlInit()
        deviceCount = pynvml.nvmlDeviceGetCount()
        results = []
        for i in range(deviceCount):
            handle = pynvml.nvmlDeviceGetHandleByIndex(i)
            mem_info = pynvml.nvmlDeviceGetMemoryInfo(handle)
            util = pynvml.nvmlDeviceGetUtilizationRates(handle)
            results.append((i, mem_info.free // 1024**2, mem_info.used // 1024**2, util.gpu))
        pynvml.nvmlShutdown()
        return results
    except Exception as e:
        if show_log:
            print(f"[GPU_mem_report] ⚠️ GPU info unavailable: {e}")
        return []  # 回傳空清單，讓 HybridConformer 正常處理

        
class HybridConformer:
    def __init__(self,
                 ObjectName="",
                 cpuUsageThreshold=90.0,        # CPU 閾值 %
                 gpuMemThresholdMB=3000,        # GPU 可用記憶體 (MB)
                 EachWaitTime=10,               # 等待秒數
                 RetryLimit=360,
                 ReachLimitContinueMode=False,
                 requireGPU=False,
                 logFile="Exception.log", logSubDir="logs"):
        self.ObjectName = ObjectName
        self.cpuUsageThreshold = cpuUsageThreshold
        self.gpuMemThresholdMB = gpuMemThresholdMB
        self.EachWaitTime = EachWaitTime
        self.RetryLimit = RetryLimit
        self.ReachLimitContinueMode = ReachLimitContinueMode
        self.requireGPU = requireGPU
        self.logFile = logFile
        self.logSubDir = logSubDir
        self._proc_called = False

        
    def __del__(self):
        if not self._proc_called:
            MPlogger().logW(
                f"[{self.ObjectName}] ⚠️ HybridConformer instance was destroyed but `.proc()` was never called.",
                logFile="hybridConformer.log", logSubDir=self.logSubDir,
                printOnScreen=True)
            
    def proc(self) -> bool:
        self._proc_called = True
        MPlogger().logW(
            f"[{self.ObjectName}] Start CPU+GPU hybrid check: CPU < {self.cpuUsageThreshold}%, GPU > {self.gpuMemThresholdMB}MB",
            logFile="hybridConformer.log", logSubDir=self.logSubDir)

        retry = 0
        printed_start = False

        while retry < self.RetryLimit:
            cpu_usage = psutil.cpu_percent(interval=1)
            gpu_mem_info = GPU_mem_report(show_log=False)
            
            if not gpu_mem_info and not self.requireGPU:
                # 沒有 GPU，且不強制檢查 GPU，視為 has_free_gpu = True
                has_free_gpu = True
                most_free = (0, 0, 0, 0)
            else:
                has_free_gpu = any(gpu[1] >= self.gpuMemThresholdMB for gpu in gpu_mem_info)
                most_free = max(gpu_mem_info, key=lambda x: x[1]) if gpu_mem_info else (0, 0, 0, 0)
            
            if cpu_usage < self.cpuUsageThreshold and has_free_gpu:
                sys.stdout.write("\n")
                MPlogger().logW(
                    f"[{self.ObjectName}] ✅ Resources OK: CPU {cpu_usage:.1f}%, GPU {most_free[1]:.0f}MB Free",
                    logFile="hybridConformer.log", logSubDir=self.logSubDir)
                return True

            retry += 1
            #msg = f"CPU: {cpu_usage:.1f}%, GPU {most_free[0]} Free={most_free[1]:.0f}MB/{most_free[2]:.0f}MB Util={most_free[3]}%"
            msg = (f"CPU: {cpu_usage:.1f}%, "
                   f"GPU {most_free[0]}: Free={most_free[1]}MB, "
                   f"Used={most_free[2]}MB, Total={most_free[1]+most_free[2]}MB, "
                   f"Util={most_free[3]}%")

            msg = (f"CPU: {cpu_usage:.0f}%, "
                   f"GPU {most_free[0]}: "
                   f"Free={format_bytes(most_free[1])}, "
                   f"Used={format_bytes(most_free[2])}, "
                   #f"Total={format_bytes(most_free[1] + most_free[2])}, "
                   f"Util={most_free[3]}%")

            MES = (f"[{self.ObjectName}] CPU or GPU resources insufficient. "
                   f"CPU={cpu_usage:.1f}%, most free GPU={msg}. "
                   f"Waited {(retry * self.EachWaitTime) / 60:.2f} mins. Retrying in {self.EachWaitTime} sec.")

            MPlogger().logW(
                MES,
                printOnScreen=(not printed_start),
                logFile="hybridConformer.log",
                logSubDir=self.logSubDir
            )
            printed_start = True

            draw_progress_bar(retry, self.RetryLimit, msg)
            time.sleep(self.EachWaitTime)

        sys.stdout.write("\n")

        MES = (f"[{self.ObjectName}] ❌ Resource check timeout after "
               f"{(self.EachWaitTime * self.RetryLimit) / 60:.1f} mins. "
               f"CPU and GPU did not reach idle condition.")

        MPlogger().logW(MES, logFile=self.logFile, logSubDir=self.logSubDir)

        if not self.ReachLimitContinueMode:
            raise Exception(MES)
        return False
    
class freeGPUConformer:
    def __init__(self, ObjectName="",
                 freeGPUmemReq=3000,  # MB
                 EachWaitTime=10,     # second
                 RetryLimit=360,
                 ReachLimitContinueMode=False,
                 logFile="Exception.log", logSubDir="../"):
        self.ObjectName = ObjectName
        self.freeGPUmemReq = freeGPUmemReq
        self.EachWaitTime = EachWaitTime
        self.RetryLimit = RetryLimit
        self.logFile = logFile
        self.logSubDir = logSubDir
        self.ReachLimitContinueMode = ReachLimitContinueMode

    def proc(self) -> bool:
        MPlogger().logW(f"[{self.ObjectName}] Start GPU memory check, threshold: {self.freeGPUmemReq}MB",
                        logFile="freeGPUConformer.log", logSubDir="logs")

        retry = 0
        try:
            GPU_mem = GPU_mem_report(show_log=False)
            if GPU_mem is None:
                raise RuntimeError("GPU_mem_report() returned None.")
        except Exception as e:
            MPlogger().logW(f"[{self.ObjectName}] GPU_mem_report() failed: {e}",
                            logFile=self.logFile, logSubDir=self.logSubDir)
            return self.ReachLimitContinueMode

        printed_start = False
        
        while len(GPU_mem) > 0 and retry < self.RetryLimit:
            if not all(gpu[1] < self.freeGPUmemReq for gpu in GPU_mem):
                sys.stdout.write("\n")
                MPlogger().logW(f"[{self.ObjectName}] Found GPU with sufficient memory.",
                                logFile="freeGPUConformer.log", logSubDir="logs")
                return True

            retry += 1
            most_free = max(GPU_mem, key=lambda x: x[1])
            gpu_msg = f"GPU {most_free[0]}: Free={most_free[1]:.0f}MB/{most_free[2]:.0f}MB Util={most_free[3]}%"
        
            MES = (f"[{self.ObjectName}] Mem of all GPU < "
                   f"{self.freeGPUmemReq}MB (most free: {gpu_msg}). "
                   f"Waited {(retry * self.EachWaitTime) / 60:.2f} mins. Retrying in {self.EachWaitTime} sec.")
        
            MPlogger().logW(
                MES,
                printOnScreen=(not printed_start),  # ✅ 只有第一次印
                logFile="freeGPUConformer.log",
                logSubDir="logs"
            )
            printed_start = True

            draw_progress_bar(retry, self.RetryLimit, gpu_msg)
            time.sleep(self.EachWaitTime)
            GPU_mem = GPU_mem_report(show_log=False)

        sys.stdout.write("\n")  # 最後一筆完成後換行

        if retry >= self.RetryLimit:
            MES = (f"[{self.ObjectName}] Waited {(self.EachWaitTime * self.RetryLimit) / 3600:.2f} hours "
                   f"({self.RetryLimit} retries) without finding enough GPU memory.")
            MPlogger().logW(MES, logFile="Exception.log", logSubDir="logs")
            if not self.ReachLimitContinueMode:
                raise Exception(MES)
            return False

        return True
    
class freeCPUConformer:
    def __init__(self, ObjectName="",
                 cpuUsageThreshold=90.0,  # %
                 EachWaitTime=10,         # 秒
                 RetryLimit=360,
                 ReachLimitContinueMode=False,
                 logFile="Exception.log", logSubDir="logs"):
        self.ObjectName = ObjectName
        self.cpuUsageThreshold = cpuUsageThreshold
        self.EachWaitTime = EachWaitTime
        self.RetryLimit = RetryLimit
        self.ReachLimitContinueMode = ReachLimitContinueMode
        self.logFile = logFile
        self.logSubDir = logSubDir

    def proc(self) -> bool:
        MPlogger().logW(f"[{self.ObjectName}] Start CPU usage check, threshold: {self.cpuUsageThreshold}%",
                        logFile="freeCPUConformer.log", logSubDir=self.logSubDir)

        retry = 0
        printed_start = False

        while retry < self.RetryLimit:
            cpu_usage = psutil.cpu_percent(interval=1)

            if cpu_usage < self.cpuUsageThreshold:
                sys.stdout.write("\n")
                MPlogger().logW(f"[{self.ObjectName}] CPU usage is acceptable: {cpu_usage:.1f}%",
                                logFile="freeCPUConformer.log", logSubDir=self.logSubDir)
                return True

            retry += 1
            msg = f"CPU: {cpu_usage:.1f}% used"
            MES = (f"[{self.ObjectName}] CPU usage = {cpu_usage:.1f}%, "
                   f"above {self.cpuUsageThreshold}%. "
                   f"Waited {(retry * self.EachWaitTime) / 60:.2f} mins. Retrying in {self.EachWaitTime} sec.")
            
            MPlogger().logW(
                MES,
                printOnScreen=(not printed_start),
                logFile="freeCPUConformer.log",
                logSubDir=self.logSubDir
            )
            printed_start = True

            draw_progress_bar(retry, self.RetryLimit, msg)
            time.sleep(self.EachWaitTime)

        sys.stdout.write("\n")
        MES = (f"[{self.ObjectName}] Waited {(self.EachWaitTime * self.RetryLimit) / 3600:.2f} hours "
               f"({self.RetryLimit} retries), CPU usage never dropped below {self.cpuUsageThreshold}%.")
        MPlogger().logW(MES, logFile=self.logFile, logSubDir=self.logSubDir)

        if not self.ReachLimitContinueMode:
            raise Exception(MES)
        return False