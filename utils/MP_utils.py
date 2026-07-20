import os
import multiprocessing as mp
'''
try:
    mp.set_start_method("spawn", force=True)
except RuntimeError as ex:
    print(ex)
    pass
'''
import threading
import subprocess
import numpy as np
import pandas as pd
import time
import random
import psutil
from pathlib import Path
import tqdm
from tqdm.contrib.concurrent import process_map
import platform
from platform import python_version
import math


def _truthy_debug_flag(value):
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on", "debug"}


def _mp_debug_enabled(explicit=None):
    env_value = os.environ.get("CZJLLM_MP_DEBUG")
    if env_value is not None:
        return _truthy_debug_flag(env_value)
    return _truthy_debug_flag(explicit)

'''
try:
    import utils.utilities
except:
    import utilities
'''
#copied from utils.utilities
from platform import python_version
import types
from version_parser.version import Version
def IsVersionValid(
        ModName="Python",
        UBD = "9999999999999.9999999999999.9999999999999",
        LBD = "0.0.0"):
    if ModName in ["python","Python"]:
        CKVer = python_version()
    else:
        CKVer = ModName.__version__

    return Version(str(LBD))<=Version(CKVer)<=Version(str(UBD))

if IsVersionValid(LBD="3.8.0"):
    print("python version >= 3.8, using istarmap2.py in MP_utils.py")
    try:
        import istarmap2 as istarmap # import to apply patch
    except:
        import utils.istarmap2 as istarmap # import to apply patch
else:
    print("python version < 3.8, using istarmap.py in MP_utils.py")
    try:
        import istarmap # import to apply patch
    except:
        import utils.istarmap # import to apply patch
'''
pyver = float('.'.join(python_version().split(".")[:2]))

if pyver < 3.8:
    print("python version < 3.8")
    try:
        import istarmap  # import to apply patch
    except:
        import utils.istarmap  # import to apply patch
else:
    print("python version >= 3.8")
    try:
        import istarmap2 as istarmap # import to apply patch
    except:
        import utils.istarmap2 as istarmap # import to apply patch
'''
def timeNow(FMT = "%Y%m%d%H%M%S"):
    return time.strftime(FMT, time.localtime())

class fileNameNormalizer:
    def proc(fileName):
        return fileName.replace("\\","/")

def MKDIR(DirName):
    if DirName == "":
        #print("DirName is empty string, skipping MKDIR(DirName).")
        return
    fileNameNormalizer.proc(DirName)
    os.makedirs(DirName, exist_ok=True)
    
class MPlogger:
    def __init__(self, logSubDir="logs",logFile="mp_processing_log.txt"):
        self.logSubDir = logSubDir
        self.logFile = logFile
    def logW(self,MES=None,
             printOnScreen=True,logMode="at",
             logSubDir=None,
             logFile=None):
        #MKDIR(logSubDir)
        if logFile == None:
            logFile = self.logFile
        if logSubDir == None:
            logSubDir = self.logSubDir
        logFile = os.path.join(logSubDir,logFile)
        MKDIR(logSubDir)
        if os.path.isfile(logFile):
            try:
                if Path(logFile).stat().st_size > 1024*1024*300:
                    os.remove(logFile)
            except Exception as e:
                print(f"When try to remove large log file {logFile}, the following error occurs:\n {e}")
                pass
        MES = "PID {}: {}".format(os.getpid(), MES)
        if printOnScreen == True:
            print(MES)
        try:
            f = open(logFile, logMode, encoding='utf8')
            f.write("{},{}\n".format(timeNow(FMT="%Y-%m-%d %H:%M:%S"),MES))
            f.close()
        except Exception as e:
            print("logSubDir",logSubDir)
            MES = f"When try to write log to file {logFile},\
                the following error occurs:\n {e}"
            print(MES)

'''
####################################################
# istarmap.py for Python <3.8
import multiprocessing.pool as mpp

def istarmap(self, func, iterable, chunksize=1):
    """starmap-version of imap
    """
    if self._state != mpp.RUN:
        raise ValueError("Pool not running")

    if chunksize < 1:
        raise ValueError(
            "Chunksize must be 1+, not {0:n}".format(
                chunksize))

    task_batches = mpp.Pool._get_tasks(func, iterable, chunksize)
    result = mpp.IMapIterator(self._cache)
    self._taskqueue.put(
        (
            self._guarded_task_generation(result._job,
                                          mpp.starmapstar,
                                          task_batches),
            result._set_length
        ))
    return (item for chunk in result for item in chunk)


mpp.Pool.istarmap = istarmap
'''
'''
####################################################
# istarmap.py for Python 3.8+
import multiprocessing.pool as mpp


def istarmap(self, func, iterable, chunksize=1):
    """starmap-version of imap
    """
    self._check_running()
    if chunksize < 1:
        raise ValueError(
            "Chunksize must be 1+, not {0:n}".format(
                chunksize))

    task_batches = mpp.Pool._get_tasks(func, iterable, chunksize)
    result = mpp.IMapIterator(self)
    self._taskqueue.put(
        (
            self._guarded_task_generation(result._job,
                                          mpp.starmapstar,
                                          task_batches),
            result._set_length
        ))
    return (item for chunk in result for item in chunk)


mpp.Pool.istarmap = istarmap
####################################################
'''
#import istarmap  # import to apply patch
#from multiprocessing import Pool

def Launcher(Job, method=""):
    #記錄任務log。
    MES = "Run Job {}".format(Job)
    multicoreJob.logW(MES=MES)
    if method =="":
        if "run" in dir(Job):
            method = "run"
        elif "proc" in dir(Job[0]):
            method = "proc"
        else:
            method = "run"
    return getattr(Job, method)()


def _mp_init_logging(q):
    """
    子程序啟動時呼叫：
    - 關閉 tqdm 的進度列輸出（避免 0%|...| 反覆重畫）
    - 將 stdout/stderr 攔到 Queue，由父程序 listener 用 tqdm.write() 安全印出
    - 將未捕捉例外以完整 traceback 傳回父程序
    """
    if q is None:
        return

    import os, sys, io, re, traceback

    # 1) 關掉子程序內所有 tqdm 條（源頭止血）
    os.environ.setdefault("TQDM_DISABLE", "1")
    # 若你在父程序也有內層 tqdm，可搭配這個一起關
    os.environ.setdefault("DISABLE_INNER_TQDM", "1")

    # 2) 偵測 tqdm 進度列樣式的正則（避免把它們送回父程序）
    _TQDM_BAR_RE = re.compile(r'^\s*\d+%?\|.*\|\s*\d+/\d+\s*\[[^\]]*\]')

    class _QueueWriter(io.TextIOBase):
        """
        將 write() 內容緩衝起來，遇到換行才送出一行；
        將 \\r 視為重畫，轉換成行邊界以避免碎片；並過濾掉 tqdm 進度列樣式。
        """
        def __init__(self, queue):
            self.q = queue
            self._buf = ""

        def write(self, s):
            if not s:
                return 0
            try:
                s = str(s)
            except Exception:
                # 最差情況處理 bytes
                try:
                    s = s.decode("utf-8", "ignore")
                except Exception:
                    s = repr(s)

            # 將 CR 視為重畫 → 直接當作行分隔，避免不停覆蓋
            s = s.replace("\r", "\n")
            self._buf += s

            # 逐行送出
            while "\n" in self._buf:
                line, self._buf = self._buf.split("\n", 1)
                line = line.rstrip()
                if not line:
                    continue
                # 過濾看起來像 tqdm bar 的行
                if _TQDM_BAR_RE.match(line):
                    continue
                try:
                    self.q.put(line)
                except Exception:
                    pass
            return len(s)

        def flush(self):
            # 把殘留緩衝送出一次（若不是進度列）
            if self._buf.strip():
                line = self._buf.strip()
                if not _TQDM_BAR_RE.match(line):
                    try:
                        self.q.put(line)
                    except Exception:
                        pass
            self._buf = ""

    # 3) 取代 stdout/stderr
    qw = _QueueWriter(q)
    sys.stdout = qw
    sys.stderr = qw

    # 4) 把未捕捉例外也送回父程序（含完整 traceback）
    def _excepthook(exc_type, exc, tb):
        try:
            msg = "".join(traceback.format_exception(exc_type, exc, tb))
            q.put(msg)
        except Exception:
            pass
    sys.excepthook = _excepthook

    
class multicoreJob:
    '''
    平行化任務執行管理器，將Job.method任務集送入平行化運算隊列；
    執行完畢後回傳res清單。
    DTBJobs：任務物件清單，任務執行方法為 Job.run()。
    '''
    def __init__(self, DTBJobs=None, method="",
                 #MulticoreMode=False,
                 nProcess=1,
                 ShuffleJobs = True,
                 SafeMode = False,
                 log_queue=None,
                 mp_debug=None):  # ★ 新增：子程序輸出要丟的 Queue
        if DTBJobs is None:
            DTBJobs = []
        if ShuffleJobs == True:
            random.shuffle(DTBJobs)
        #print("In MU DTBJobs", DTBJobs[0:3])
        self.DTBJobs = DTBJobs
        if method =="" and len(DTBJobs)>0:
            if "run" in dir(DTBJobs[0]):
                method = "run"
            elif "proc" in dir(DTBJobs[0]):
                method = "proc"
        self.method = method
        if nProcess > 1:
            self.MulticoreMode = True
        else:
            self.MulticoreMode = False
        #self.MulticoreMode = MulticoreMode
        if DTBJobs != []:
            self.nProcess = min(nProcess,len(DTBJobs))
        else:
            self.nProcess = nProcess
        self.SafeMode = SafeMode
        self.log_queue = log_queue   # ★ 存起來，給 Pool initializer 用
        self.mp_debug = mp_debug
        #print("self.log_queue",self.log_queue)
        
    def logW(MES=None, logFile="mp_processing_log.txt"):
        try:
            f = open(logFile, "at", encoding='utf8')
            MES = "PID {}: {}".format(os.getpid(), MES)
            f.write("{},{}\n".format(timeNow(FMT="%Y-%m-%d %H:%M:%S"),MES))
            f.close()
        except Exception as e:
            print(f"When try to log message {MES}, the following error occurs:\n{e}\n")
        
    '''
    def add_features(df):
        if "The Economist" in df['file'].split("\\"):
            SampleExtractBound = nUpperBoundForSingleEconomist
        else:
            SampleExtractBound = nUpperBoundForSingleFile
        df['text_cut'] = df['file'].apply(
            lambda x:readSamepleForFile(x, width=256, Mode="FullCut")[0:SampleExtractBound])
        return df
    ''' 

    def parallelize_dataframe(self, df, func = None, rowfunc = None):
        if func is None and rowfunc is None:
            print("For multicoreJob.parallelize_dataframe in MP_utils, both of func and rowfunc is None! Abort!")
            raise Exception
        #func: input:df output:another df
        if rowfunc is not None:
            func = lambda df:df.apply(rowfunc, axis=1)
        
        nProcessCand = math.ceil(len(df)/1000)
        if nProcessCand < self.nProcess:
            df_sp_nProcess = nProcessCand
        else:
            df_sp_nProcess = self.nProcess
        print(f"呼叫DataFrame平行化函數套用功能 with {func.__name__}，進程數為 {df_sp_nProcess}")
        if "windows" in platform.system().lower():
            print("windows平台目前使用DataFrame平行化函數功能會有程序異常大量增殖問題，故強制改為單進程執行。")
        if df_sp_nProcess > 1 and "windows" not in platform.system().lower():
            try:
                
                df_split = np.array_split(df, df_sp_nProcess)
                #pool = mp.Pool(df_sp_nProcess)
                pool = mp.Pool(
                    processes=df_sp_nProcess,
                    initializer=_mp_init_logging,
                    initargs=(self.log_queue,)
                )
                df = pd.concat(pool.map(func, df_split))
                pool.close()
                pool.join()
            except Exception as e:
                MES = f"When apply parallelize_dataframe to df (10rows):\n {df[:10]} \n with function {func.__name__} the following error occurs:\n{e}.\n"
                MES += "Instead, run with single process."
                MPlogger().logW(MES,logFile="Exceptions.log")
                df = func(df)
        else:
            df = func(df)
        return df

    def ComputeNProcess(self,):
        nCPU = mp.cpu_count()
        if nCPU > 30:
            #nProcess = int(nCPU*1.3)
            nProcess = int(nCPU*0.5)
        else:
            nProcess = int(nCPU*0.8)
        
        MES = f"The basic number of Process is defined to {nProcess}."
        MPlogger().logW(MES=MES)
        MES = "進程數設定為{}，請依硬體CPU資源數量，妥善設定進程數量，以免程式崩潰！\
            如果沒有把握，請將進程數設為1，以策安全。".format(nProcess)
        MPlogger().logW(MES=MES)
        nProcess = max(nProcess,1)
        return nProcess
    
    def ComputeSPCNProcess(self,):
        AvaMem = psutil.virtual_memory().available
        nProcessSPC = int(AvaMem/(3*1024*1024*1024))
        nProcessSPC = max(nProcessSPC,1)
        nProcessSPC = min(nProcessSPC,self.ComputeNProcess())
        MES = f"The SPC number of Process is defined to {nProcessSPC}."
        MPlogger().logW(MES=MES)
        MES = "經考量剩餘記憶體，進程數設定為{}，請依硬體CPU資源數量，妥善設定進程數量，以免程式崩潰！\
            如果沒有把握，請將進程數設為1，以策安全。".format(nProcessSPC)
        MPlogger().logW(MES=MES)

        return nProcessSPC
            
    def run(self):
    
        DTBJobs = self.DTBJobs
        if _mp_debug_enabled(self.mp_debug):
            import traceback
            print(
                "\n[MP-POOL-CREATE]\n"
                f"pid={os.getpid()}\n"
                f"ppid={os.getppid()}\n"
                f"thread={threading.current_thread().name}\n"
                f"platform={platform.system()}\n"
                f"start_method={mp.get_start_method(allow_none=True)}\n"
                f"nProcess={self.nProcess}\n"
                f"jobs={len(DTBJobs)}\n"
                f"active_children={len(mp.active_children())}\n"
                f"stack:\n{''.join(traceback.format_stack(limit=12))}",
                flush=True,
            )

        method = self.method
        if len(DTBJobs) == 0:
            print("="*50)
            print("There is no jobs for multicorejob to run! Return empty list [] immediately!")
            print("="*50)
            return []
        
        print("="*50)
        print(f"執行multicorejob.run()函式，共有{len(DTBJobs)}個任務，前{min(3,len(DTBJobs))}個任務為")

        for Job in DTBJobs[0:3]:
            if "show" not in dir(Job):
                break
            print('-'*50)
            Job.show()
        res = []
        if len(DTBJobs) == 1 or self.nProcess ==1:
            self.MulticoreMode = False
            print("There is only one job or nProcess=1. Deactive Multiprocessing.")
        
        #將單一任務執行結果新增至res列表，俟所有任務完成，最後再換成DataFrame，
        #進行存檔或資料視覺化顯示。
        if self.MulticoreMode == False:
            print("="*50)
            print(("Multiprocessing is nonactive now and try pretest."
                  "If everything is fine, try active Multiprocessing."
                  ).replace("\n",""))
            print("="*50)
            for Job in DTBJobs:
                #print("now processing", Job)
                #Job.show()
                res.append(Launcher(Job, method))
        else:
            print("="*50)
            print(("Start Multiprocessing. If the system is halted,"
                  "try inactive the Multiprocessing and make the PGM could "
                  "run without Error or Exception. Otherwise the processing "
                  "may call subprocess INFINITLY resulting in stucking "
                  "in the multiprocess procedure!"
                  ).replace("\n",""))
            print("="*50)
            '''
            #pool = mp.Pool(self.nProcess)
            pool = mp.Pool(
                processes=self.nProcess,
                initializer=_mp_init_logging,
                initargs=(self.log_queue,)
            )
            DTBJobs = [(Job,method) for Job in DTBJobs]
            print(f"There are totally {len(DTBJobs)} Jobs.")
            if self.SafeMode == False:
                res = list(
                    tqdm.tqdm(pool.istarmap(Launcher, DTBJobs),
                    total=len(DTBJobs)))
            elif self.SafeMode == True:
                res = pool.starmap(Launcher, DTBJobs)
                #res = pool.starmap(Launcher, tqdm.tqdm(DTBJobs, total=len(DTBJobs)))
            pool.close()
            pool.join()
            '''
            mp_ctx = mp.get_context("spawn") if os.name == "nt" else mp.get_context()
            
            pool = None
            
            try:
                pool = mp_ctx.Pool(
                    processes=self.nProcess,
                    initializer=_mp_init_logging,
                    initargs=(self.log_queue,),
                )
            
                DTBJobsWithMethod = [
                    (job, method)
                    for job in DTBJobs
                ]
            
                print(
                    f"There are totally {len(DTBJobsWithMethod)} Jobs.",
                    flush=True,
                )
            
                if not self.SafeMode:
                    result_iter = pool.istarmap(
                        Launcher,
                        DTBJobsWithMethod,
                        chunksize=1,
                    )
            
                    res = list(
                        tqdm.tqdm(
                            result_iter,
                            total=len(DTBJobsWithMethod),
                        )
                    )
                else:
                    res = pool.starmap(
                        Launcher,
                        DTBJobsWithMethod,
                    )
            
                pool.close()
                pool.join()
                if _mp_debug_enabled(self.mp_debug):
                    print(
                        "\n[MP-POOL-JOINED]\n"
                        f"pid={os.getpid()}\n"
                        f"active_children={len(mp.active_children())}",
                        flush=True,
                    )
                pool = None
            
            except BaseException:
                if pool is not None:
                    try:
                        pool.terminate()
                    except Exception:
                        pass
            
                    try:
                        pool.join()
                    except Exception:
                        pass
            
                raise
    
        return res

class CommandExecutor:
    def __init__(self, command):
        # 更新檢查邏輯
        if not (isinstance(command, str) or callable(command)):
            raise ValueError("Command must be a string or a callable function")
        self.command = command
        self.thread = None

    def run(self):
        """
        啟動一個新的執行緒來執行指令或函數
        """
        self.thread = threading.Thread(target=self._execute)
        self.thread.start()

    def _execute(self):
        """
        執行指令或函數的內部方法，包含錯誤處理
        """
        try:
            if isinstance(self.command, str):
                # 使用 subprocess 來替代 os.system，增強控制性
                subprocess.run(self.command, shell=True, check=True)
            elif callable(self.command):
                # 如果是可調用的對象（函數），則調用該函數
                self.command()
        except Exception as e:
            print(f"Command execution failed: {e}")

    def join(self):
        """
        等待執行緒完成
        """
        if self.thread:
            self.thread.join()
            
class squ():
    def __init__(self, numL):
        self.numL = numL
    def run(self):
        #print("numL",self.numL)
        return [x*x for x in self.numL]

class MPDictTest():
    def __init__(self, InputDict=dict(), num=1):
        self.InputDict = InputDict
        self.num = num
    def run(self):
        #print("numL",self.numL)
        self.InputDict[self.num] = self.num
        global InputDict
        InputDict[self.num] = self.num
        #InputDict[self.num]=self.num
        return self.InputDict

class MPDictTestAnother():
    def __init__(self, num=1):
        #self.InputDict = InputDict
        self.num = num
    def run(InputDict=dict(),num=2):
        #print("numL",self.numL)
        #self.InputDict[self.num] = self.num
        InputDict[num]=num
        #return self.InputDict
    
"""
if __name__=='__main__':
#if False:   
    def flattenList(t):
        tempList = []
        for sublist in t:
            tempList.extend(sublist)
        return tempList
        
    def SplitList(data, nChunks = 2):
        result = []
        nElemInSubList = int(len(data)/nChunks)
        cong = len(data) % nChunks
        #if len(data) % nChunks != 0:
            #nElemInSubList += 1
        for i in range(nChunks):
            if i <= cong-1:
                chunk = data[0:nElemInSubList+1]
                data = data[nElemInSubList+1:]
            else:
                chunk = data[0:nElemInSubList]
                data = data[nElemInSubList:]
            result.append(chunk)
        return result
    cp = []
    for nProcess in range(1,5):
        testSet = list(range(10))
        DTBJobs = [squ(
            numL=testSetCK
            ) for testSetCK in SplitList(testSet, nChunks=nProcess)]
        
        JBSpli = SplitList(testSet, nChunks=nProcess)
        MPresult = multicoreJob(
            DTBJobs, nProcess=nProcess).run()
        #r = process_map(squ(
            #numL=JBSpli[i]
            #).run(), range(0, len(JBSpli)), max_workers=2))
        #MPresult = process_map(_foo, range(0, 30), max_workers=2)
        test_result = flattenList(MPresult)
        print("test_result",test_result)
        #print("test_result",test_result)
        cp.append(set(test_result)==set([0, 1, 4, 9, 16, 25, 36, 49, 64, 81]))
    print("-"*50)
    print(cp)
    print(sum(cp))
    os.system("pause")
"""   
    
    
def _foo(my_number):
   square = my_number * my_number
   time.sleep(1)
   print(square)
   return square 

#if __name__ == '__main__':
if False:
    r = process_map(_foo, range(0, 30), max_workers=3)
    
if __name__=='__main__':
    A = dict()
    DTBJobs = []
    for i in range(100):
        DTBJobs.append(MPDictTest(InputDict=A,num=i))
        #DTBJobs.append(MPDictTestAnother(num=i))
        #MPDictTestAnother.run(InputDict=A,num=i)
    #print("DTBJobs",DTBJobs)
    MPresult = multicoreJob(
        DTBJobs, nProcess=30).run()
        #DTBJobs, nProcess=30).run(InputDict=A)
    print("MPresult",MPresult)
    print("b4 sub update",A)
    for SubDict in MPresult:
        A.update(SubDict)
    print("af sub update",A)
    os.system("pause")
   
    