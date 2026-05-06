from PackageImport import PackageImporter
PackageImporter.proc()

import os
import sys
import time
#import multiprocessing as mp
import re
import hashlib
import shutil
import psutil

try:
    import humanize
except Exception as e:
    print(e)
    pass

import random
import pathlib
from pathlib import Path
import platform
import collections
import json
import string
#import ast
#import psutil,GPUtil
import math
#import statistics
import GPUtil
import argparse
import numpy as np
#from numpy.linalg import norm
from collections import Counter
from collections.abc import Hashable
from opencc import OpenCC
try:
    from langconv.converter import LanguageConverter
    from langconv.language.zh import zh_cn, zh_tw, zh_hk
except:
    pass
import pandas as pd
#import types
#import numpy as np
from scipy.stats import entropy
from math import log, e
import timeit
import datetime as dte
from dateutil.relativedelta import relativedelta
import operator
import setproctitle
from platform import python_version
from version_parser.version import Version
from urllib.parse import unquote
#from colorama import Fore, Back, Style
#import curses
import socket
#try:
#    import jellyfish
#except:
#    pass

try:
    from utils.MP_utils import MPlogger
except:
    from .MP_utils import MPlogger

import zipfile 
#import py7zr
#import rarfile
import subprocess

from colorama import Fore, Style
from tqdm import tqdm

'''
try:
    import utils.Edited_zipfile as zf
except:
    import Edited_zipfile as zf
'''
#from PyQt5 import QtWidgets
#from PyQt5.QtWidgets import QWidget
'''
import random
import difflib

try:
    from cdifflib import CSequenceMatcher
    difflib.SequenceMatcher = CSequenceMatcher
except:
    pass
'''
#from diff_match_patch import diff_match_patch

from utils.utilities_path import OSWALK
from utils.utilities_path import MKDIR
from utils.utilities_path import MKDIRandCopy
from utils.utilities_path import remove_empty_dirs
from utils.utilities_path import RESETDIR
from utils.utilities_path import fileNameNormalizer
from utils.utilities_path import PathSEP
from utils.utilities_path import pathSpliter
from utils.utilities_path import fileNameReplacer
from utils.utilities_path import ShortenFN
from utils.utilities_path import getMFNFromFN,getFNFromFullPath,getFNExtFromFullPath
from utils.utilities_path import getPathFromFN,getFileDirFromFN
from utils.utilities_path import getSubdirectory
from utils.utilities_path import FileNamePicker
from utils.utilities_path import InsertDirnameToFN
from utils.utilities_path import AppendedMFN
from utils.utilities_path import RemoveIlleagalCharForFileName
from utils.utilities_path import RemoveIlleagalCharForFileNameForLatex
#from utils.utilities_path import find_similar_directory
from utils.utilities_path import getFastAPIStaticDir
from utils.utilities_path import BackupAndDelFile
from utils.utilities_path import DirReplace
from utils.utilities_path import RenameDir
#from utils.utilities_json import JsonHandler
#from utils.utilities_json import JsonFilesProcessor
#from utils.json_utils import Serializer
from utils.progress_utils import draw_progress_bar

# 檢查當前系統是否為 Windows
def IsWindows():
    #return (platform.system().lower() == 'windows')
    return ("windows" in platform.system().lower())

if IsWindows():
    import msvcrt
else:
    import select

def is_connected(host="8.8.8.8", port=53, timeout=3):
    """
    嘗試連線至 Google DNS，判斷是否有對外網路。
    """
    try:
        socket.setdefaulttimeout(timeout)
        socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect((host, port))
        return True
    except Exception:
        return False
    
#熵計算=========================================================

def exit_program():
    print("Exiting the program...")
    sys.exit(0)
    #quit()
    
def entropy1(labels, base=None):
  value,counts = np.unique(labels, return_counts=True)
  return entropy(counts, base=base)

def entropy2(labels, base=None):
  """ Computes entropy of label distribution. """

  n_labels = len(labels)

  if n_labels <= 1:
    return 0

  value,counts = np.unique(labels, return_counts=True)
  probs = counts / n_labels
  n_classes = np.count_nonzero(probs)

  if n_classes <= 1:
    return 0

  ent = 0.

  # Compute entropy
  base = e if base is None else base
  for i in probs:
    ent -= i * log(i, base)

  return ent

def entropy3(labels, base=None):
  vc = pd.Series(labels).value_counts(normalize=True, sort=False)
  base = e if base is None else base
  return -(vc * np.log(vc)/np.log(base)).sum()

def entropy4(labels, base=None):
  value,counts = np.unique(labels, return_counts=True)
  norm_counts = counts / counts.sum()
  base = e if base is None else base
  return -(norm_counts * np.log(norm_counts)/np.log(base)).sum()

def EntropyTest():
    repeat_number = 1000000
    
    a = timeit.repeat(stmt='''entropy1(labels)''',
                      setup='''labels=[1,3,5,2,3,5,3,2,1,3,4,5];from __main__ import entropy1''',
                      repeat=3, number=repeat_number)
    
    b = timeit.repeat(stmt='''entropy2(labels)''',
                      setup='''labels=[1,3,5,2,3,5,3,2,1,3,4,5];from __main__ import entropy2''',
                      repeat=3, number=repeat_number)
    
    c = timeit.repeat(stmt='''entropy3(labels)''',
                      setup='''labels=[1,3,5,2,3,5,3,2,1,3,4,5];from __main__ import entropy3''',
                      repeat=3, number=repeat_number)
    
    d = timeit.repeat(stmt='''entropy4(labels)''',
                      setup='''labels=[1,3,5,2,3,5,3,2,1,3,4,5];from __main__ import entropy4''',
                      repeat=3, number=repeat_number)
    print(a,b,c,d)

#========================================================

class VariableChangeDetector:
    """ A simple class, set to watch its variable. """
    def __init__(self, name, value):
        self.name = name
        self.variable = value   
    def proc(self, new_value):
        if new_value != self.variable:
            self.variable = new_value
            return True
        else:
            return False

def TSVTextAdapter(text):
    for removeChar in ['\0','\u3000','\t', '\ufeff']:
        text = str(text).replace(removeChar,'')
    text = text.replace('"','“')
    text = text.replace("'","’")
    #去除斷行。
    text = text.replace("\n", " ")
    return text


class RENormalizer:
    def proc(rexp):
        #如果輸入為一堆正規表示式清單，將其以or形式串接回傳。
        if type(rexp) is list:
            return '|'.join([f"({x})" for x in rexp])
        elif type(rexp) is str:
            return rexp



class Prefixer:
    def __init__(self, inputObj="", prefix="",):
        self.inputObj = inputObj
        self.prefix = prefix
    def proc(self, inputObj):
        return self.prefix + inputObj
    def run(self):
        return self.inputObj+self.prefix

class Replacer:
    def __init__(self, Map={}):
        self.Map = Map
    def proc(self, inputObj):
        result = inputObj
        for key in self.Map.keys():
            result = result.replace(key, self.Map[key])
        return result

class TextNormalizer:
    def __init__(self, Map={}):
        if Map == {}:
            for removeChar in ['\0','\u3000','\t', '\ufeff']:
                Map[removeChar] = ""
            Map.update({'"':'“',"'":"’"})
        self.Map = Map
    def proc(self, inputObj):
        #result = inputObj
        return Replacer(Map = self.Map).proc(inputObj)
    
class LineBreaker:
    def __init__(self, BreakPattern=[]):
        self.BreakPattern = BreakPattern
    def proc(self, inputObj):
        result = inputObj #string
        for pat in self.BreakPattern:
            result = result.replace(
                pat, pat+"\n").replace("\n\n","\n").replace("\n ","\n")
        return result

class NewlineNormalizer:
    def __init__(self, max_newlines=20):
        self.max_newlines = max_newlines

    def proc(self, input_string):
        # 將字串分割成以\n為分隔符的列表
        lines = input_string.rstrip('\n').split('\n')
        # 如果\n的數量超過設定的上限，將多餘的\n替換為空白
        if len(lines) > self.max_newlines:
            # 將超過的部分替換為空白
            processed_string = '\n'.join(lines[:self.max_newlines])+' '+' '.join(lines[self.max_newlines:])
            return processed_string
        else:
            # 如果\n的數量沒有超過上限，直接返回原字串
            return input_string
    
class OptionLineBreaker:
    def __init__(self, OptionPattern=[]):
        self.OptionPattern = OptionPattern
    def proc(self, inputObj):
        result = inputObj #string
        for pat in self.OptionPattern:
            if inputObj.startswith(pat) and inputObj.strip() != pat:
                result = inputObj.replace(
                    pat+" ", pat).replace(pat, pat+"\n")
                break
        return result

def IsVersionValid(
        ModName="Python",
        UBD = "9999999999999.9999999999999.9999999999999",
        LBD = "0.0.0"):
    #IsVersionValid(ModName="Python",UBD="3.10.0")
    #IsVersionValid(ModName=pandas,UBD="1.4.0")
    if ModName in ["python","Python"]:
        CKVer = python_version()
    else:
        CKVer = getattr(ModName,"__version__")

    return Version(str(LBD))<=Version(CKVer)<=Version(str(UBD))

r'''
class VersionPicker:
    def __init__(self, Option="Verno"):
        self.Option = Option
    def proc(self, inputObj):#inputObj:List of string
        result = inputObj
        VerDict = {}
        if Option == "Verno":
            for x in inputObj:
                VerCand = re.findall("\d+",x)
                if VerCand == []:
                    VerCand = [0]
                    
                
                NewestItem = sorted(A.items(),key = lambda x:x[1])[-1]
                NewestEle = NewestItem[0]
                return NewestEle
'''

class reExtractor:
    def __init__(self, pat): #pat="YouShouldInputAPattern"):
        self.pattern = pat
    def proc(self, inputObj):#inputObj:A string
        return re.findall(self.pat,inputObj)[0]
                
class reCombiner:
    def __init__(self, reList = [], method = "or"):
        self.reList = reList
        self.method = method
    def proc(self):
        res = ""
        if self.method == "or":
            for rege in self.reList:
                if rege == "":
                    continue
                #第一個表示式前面不加 |
                if res != "":
                    res += "|"
                res += f"({rege})"
        elif self.method == "and":
            for rege in self.reList:
                if rege == "":
                    continue
                res += f"(?={rege})"
            res += ".*"
            
            #(?=.*COVID|.*APO)(?=.*Story|.*BDK).*
        #print(res)
        #raise Exception
        return res

class DomainNameExtractor:
    def __init__(self, link):
        self.link = link
    def proc(self, ):#inputObj:A string
        return removeStrPrefix(removeStrPrefix(
            self.link,"http://"),"https://").split("/")[0]

class ListDivider:
    def proc(List, ratioList = [0.5,0.5]):
        if sum(ratioList) != 1:
            SUMR = sum(ratioList)
            ratioList = [x/SUMR for x in ratioList]
        result = []
        LenL = len(List)
        #cutIdxList
        CIL = [int(sum(ratioList[:i+1])*LenL)
            for i,ratio in enumerate(ratioList)]
        CIL.insert(0,0)
        print("CIL",CIL)
        if CIL[-1] != LenL:
            CIL[-1] == LenL
        for i in range(len(CIL)-1):
            print(CIL[i],CIL[i+1])
            result.append(List[CIL[i]:CIL[i+1]])
        return result
    
class ListCutPicker:
    def proc(sourceList = [], triggerList = []):
        '''
        A = ["a","b","c","d","e","f"]
        triggerList = [{"triggerRe":"^b$","cutPieces":[(1,9999),(3,4)]}]
        ListCutter(A,triggerList) = ['c', 'd', 'e', 'f', 'e']
        '''
        res = []
        for trig in triggerList:
            for i,x in enumerate(sourceList):
                if re.match(trig["triggerRe"],x):
                    partSrc = sourceList[i:]
                    print(trig["cutPieces"])
                    for start,end in trig["cutPieces"]:                  
                        #print("start,end",start,end)
                        res.extend(partSrc[start:end])
        return res
    
def CapWords(s, ignorePreposition = True):
    #print("CapWords", s)
    if all([ignorePreposition,
            s in ["and","of","to","on","above","below","under",
                  "at","a","an","the"],
            ]):
        return s
    else:
        lst = [word[0].upper() + word[1:] for word in s.split()]
        return " ".join(lst)
        




def timeNow(FMT = "%Y%m%d%H%M%S"):
    return time.strftime(FMT, time.localtime())
    #return datetime.datetime.now().strftime(format=FMT)
def timeRelative(
        start=timeNow(),
        inputFMT = "%Y%m%d%H%M%S",
        outputFMT = "%Y%m%d%H%M%S",
        args={"months":-1}
        ):
    res = dte.datetime.strptime(start, inputFMT) + relativedelta(**args)
    res = dte.datetime.strftime(res,outputFMT)
    return res

def DateList(startday="", periods=100,freq="D",FMT = "%Y%m%d"):
    if startday == "":
        startday = time.strftime(FMT, time.localtime())
    start = dte.datetime.strptime(startday, FMT)
    datelist = pd.date_range(start, periods=periods,freq=freq).tolist()
    datelist = [dte.datetime.strftime(date,FMT) for date in datelist]
    return datelist
'''
Alias Description
B business day frequency
C custom business day frequency
D calendar day frequency
W weekly frequency
M month end frequency
SM semi-month end frequency (15th and end of month)
BM business month end frequency
CBM custom business month end frequency
MS month start frequency
SMS semi-month start frequency (1st and 15th)
BMS business month start frequency
CBMS custom business month start frequency
Q quarter end frequency
BQ business quarter end frequency
QS quarter start frequency
BQS business quarter start frequency
A,Y year end frequency
BA,BY business year end frequency
AS,YS year start frequency
BAS,BY Sbusiness year start frequency
BH business hour frequency
H hourly frequency
T,min minutely frequency
S secondly frequency
L,ms milliseconds
U,us microseconds
N nanoseconds
'''

def getFileModTime(file):
    fname = pathlib.Path(file)
    try:
        result = dte.datetime.fromtimestamp(int(fname.stat().st_mtime))
    except:
        result = None
    return result

def MemUsage(Object, ObjName):
    print("Memory usage of", type(Object), ObjName, "is", sys.getsizeof(object), "bytes.,")

def MemUsageOfCurrentProcess(humanizedMessage=True):
    memUsage = psutil.Process(os.getpid()).memory_info().rss
    if humanizedMessage == True:
        try:
            shownMemUsage = humanize.naturalsize(memUsage)
        except Exception as e:
            print(e)
            shownMemUsage = memUsage
    else:
        shownMemUsage = memUsage
    print(f"The memory usage of current process is {shownMemUsage}")
    return shownMemUsage
    

def ShowElapsedTime(start_time=None):
    if start_time is not None:
        elapsed_time = time.time() - start_time
        print("It has been passed for {:.4f} seconds".format(elapsed_time))
        return elapsed_time
    else:
        print("While running ShowElapsedTime, the start_time is not input!")
        return None
    
    
def ShowStepCostTime(start_time, JobName = ""):
    elapsed_time = time.time() - start_time
    print("It cost {:.4f} seconds for this job {}".format(elapsed_time, JobName)) 


def countdown_pause(seconds):
    if seconds <= 0:
        return
    for i in range(seconds, 0, -1):
        print(f"\r倒數 {i} 秒... (按 Enter 鍵略過)", end="")
        sys.stdout.flush()  # 確保馬上顯示輸出

        if IsWindows():
            # Windows 系統使用 msvcrt 模組
            if msvcrt.kbhit() and msvcrt.getch() == b'\r':
                print("\r倒數被略過")
                return
        else:
            # 非 Windows 系統使用 select 模組
            if select.select([sys.stdin], [], [], 1)[0]:
                input()  # 等待 Enter 鍵被按下
                print("\r倒數被略過")
                return
        time.sleep(1)
    print("\r倒數結束")

def DictIndentPrint(Dict,indent=4):
    #for key in Dict.keys():
        #if isinstance(Dict[key],set):
            #Dict[key] = list(Dict[key])
    print(json.dumps(Dict,indent=4,ensure_ascii=False))
    
def ShowPartDict(Dict, nShow = 15, DictMeaning = None):
    print("-"*50)
    print("Show the first and last", nShow/2, "items of", DictMeaning)
    KEYSList = list(Dict.keys())
    print("key", "Dict[key]")
    for key in KEYSList[0:int(nShow/2)]+KEYSList[-int(nShow/2):]:
        try:
            print(key, str(Dict[key])[0:1000])
        except Exception as e:
            print(f"When Runngin ShowPartDict, the following error occurs:\n{e}\n")
        if len(str(Dict[key])[0:1000]) > 1000:
            print("-"*10)
    MemUsage(Dict, DictMeaning)
    print("-"*50)

def ShowLenOfValuesOfDict(mydict,Name=None):
    print(f"{'-'*10} Len of Values of The Dict {Name} {'-'*10}")
    for key in mydict.keys():
        print(f"{key}: {len(mydict[key])}")
    print('-'*50)
    
def UniqueList(InputList):
    result = []
    for x in InputList:
        if x not in result:
            result.append(x)
        else:
            continue
    return result
def ListDiff(List1,List2):#Output:List1-List2
    s = set(List2)
    print("List1[0:15], List2[0:15]",list(List1)[0:15], list(List1)[0:15])
    return [x for x in List1 if x not in s]

def ListCap(List1,List2):#Output:List1 intersect List2
    return list(set(List1) & set(List2))

def ListFill(Number, ChoiceList): #range(n) (0,1,2,3,...,n-1)
    n = Number
    k = len(ChoiceList)
    s = (n- n%k)/k #number for repeated use
    if n % k == 0:
        s += 1
    result = []
    choice = 0
    for x in range(k):
        if choice < n % k :
            result = result +[ChoiceList[choice]]*int(s+1)
        else:
            result = result +[ChoiceList[choice]]*int(s)
        choice += 1
    return result

#import timeit
def flattenListOld(t):
    return [item for sublist in t for item in sublist]
def flattenList(t):
    tempList = []
    for sublist in t:
        tempList.extend(sublist)
    return tempList
def flattenTest():
    repeat_number = 100000
    
    a = timeit.repeat(stmt='''flattenListOld(t)''',
                      setup='''t=[list(range(1000)),list(range(1000))];from __main__ import flattenListOld''',
                      repeat=3, number=repeat_number)

    b = timeit.repeat(stmt='''flattenList(t)''',
                      setup='''t=[list(range(1000)),list(range(1000))];from __main__ import flattenList''',
                      repeat=3, number=repeat_number)
    print(f"flattenListOld cost {a}")
    print(f"flattenList cost {b}")
    t=[list(range(10)),list(range(10))]
    print(f"Are the two answers the same? {flattenListOld(t)==flattenList(t)}")
#flattenTest()
    
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
    return [
        data[x:x+nElemInSubList] 
        for x in range(0, len(data), nElemInSubList)]

def safe_set(x):
    """
    從輸入的資料 x 中，篩選出所有可 hash 的元素並轉換成集合。
    若 x 為 None 或空值，則回傳空集合。
    
    參數:
        x (iterable 或 None): 可能包含不可 hash 元素的集合或列表
    
    回傳:
        set: 僅包含可 hash 元素的集合
    """
    return set(item for item in (x or []) if isinstance(item, Hashable))

def safe_sorted_str_list(term, key, unique=True):
    try:
        val = term.get(key, [])
        if isinstance(val, str):
            # 嘗試還原成 list，如果是合法 JSON 字串
            try:
                val = json.loads(val)
            except Exception:
                return []  # 不是合法 JSON，就放棄
        if isinstance(val, list):
            cleaned = [str(v).strip() for v in val if v and isinstance(v, (str, int, float))]
            if unique:
                return sorted(set(cleaned))  # ✅ 去重並排序
            else:
                return sorted(cleaned)       # ✅ 保留重複項目並排序
    except:
        pass
    return []

def safe_sorted_str_list_old(term, key):
    try:
        val = term.get(key, [])
        if isinstance(val, str):
            # 嘗試還原成 list，如果是合法 JSON 字串
            try:
                val = json.loads(val)
            except Exception:
                return []  # 不是合法 JSON，就放棄
        if isinstance(val, list):
            return sorted([str(v).strip() for v in val if v and isinstance(v, (str, int, float))])
    except:
        pass
    return []

def convert_lang_variant(data, targetVariant='zh_cn'):
    """
    遞迴處理資料，將所有字串轉換成指定的中文語言版本。

    參數:
      data: 任意型態的資料（可能是字串、列表或字典）
      targetVariant: 目標語言版本，可用值有 'zh_cn', 'zh_tw', 'zh_hk'，
                     預設為 'zh_cn'
                     
    回傳:
      處理後的資料，其中所有字串均已轉換為指定的語言版本
    """
    variant_map = {
        "zh_cn": zh_cn,
        "zh_tw": zh_tw,
        "zh_hk": zh_hk,
    }
    cc = LanguageConverter.from_language(variant_map.get(targetVariant, zh_cn))
    
    def convert_data(d):
        if isinstance(d, str):
            return cc.convert(d)
        elif isinstance(d, list):
            return [convert_data(item) for item in d]
        elif isinstance(d, dict):
            return {key: convert_data(value) for key, value in d.items()}
        else:
            return d

    return convert_data(data)

def SortedDictWithValue(dic, dsc = True):
    sortedList = sorted(dic.items(), key=lambda x:x[1],reverse = dsc)
    return dict(sortedList)

def SortedDictWithValLen(dic, dsc = True):
    #print("dic input",dic)
    dic = {k: v for k, v in sorted(
        dic.items(), key=lambda item: len(item[1]),reverse = dsc)}
    #print("dic sorted",dic)
    temp = {}
    for i,ke in list(enumerate(dic)):
        temp[i] = dic.pop(ke)
    dic = temp
    #print("temp",temp)
    #raise Exception
    return dic

class DictQueryer:
    def __init__(self, mydict=dict(), queryVector=[]):
        self.mydict = mydict
        self.queryVector = queryVector
    def show(self,):
        print("="*50)
        print("for DictQueryer, queryVector", self.queryVector)
    def proc(self,):
        if self.queryVector == []:
            print("for DictQueryer, ")
            return
        res = None
        return res
        
def frequency_sort(lst):
    counts = collections.Counter(lst)
    return sorted(lst, key=lambda x: (counts[x], x), reverse=True)
    
    



        
def LinkFiller(Link, CtrlPath, SpecLinkFiller=None):
    if SpecLinkFiller != None:
        if Link.startswith("http"):
            return Link
        #{"re":"http://www.ccpit.org/.*/","method":"concatenate"},
        
        method = SpecLinkFiller["method"]

        pre_expr = SpecLinkFiller.get("prefix_re","")
        suf_expr = SpecLinkFiller.get("suffix_re","")
        print("pre_expr, CtrlPath", pre_expr, CtrlPath)
        #prefix = re.findall(pre_expr,CtrlPath)[0]
        prefix = re.search(pre_expr,CtrlPath).group()
        
        #print("prefix", prefix)
        if method == "concatenate":
            finLink = prefix+Link
        elif method == "ExtractAndConcatenate":
            ext_expr = SpecLinkFiller["extract_re"]
            #finLink = prefix+re.findall(ext_expr,Link)[0]+suf_expr
            finLink = prefix+re.search(ext_expr,Link).group()+suf_expr
        elif method == "replace":
            replace_re = SpecLinkFiller["replace_re"]
            #finLink = prefix+re.findall(ext_expr,Link)[0]+suf_expr
            finLink = re.sub(replace_re["src"],replace_re["tar"],Link)
        if SpecLinkFiller.get("UrlDecode",False) in [True,"True","yes","YES","Yes"]:
            finLink = unquote(finLink)
        print("after concatenate, the link is", finLink)
        return finLink
    else:
        CtrlDir = "/".join(CtrlPath.split("/")[:-1])
        HomeLink = "/".join(CtrlPath.split("/")[0:3])
        if Link.startswith("//"):
            Link = "https:"+Link
        elif Link.startswith("/"):
            Link = HomeLink+Link
        elif Link.startswith("#"):
            Link = CtrlPath.split("#")[0]+"#"+Link.split("#")[1]
        elif Link.startswith("."): #../* or ./*
            print("CtrlPath", CtrlPath)
            '''
            SubPath = Link.split("/")
            RemoveCtrlPathLevel = (
                SubPath[0]==".")*1+(SubPath[0]=="..")*2+sum(
                [(x=="..")*1 for x in SubPath[1:]])
            print("RemoveCtrlPathLevel", RemoveCtrlPathLevel)
            print("Link", Link)
            Link = "/".join(CtrlPath.split("/")[:min(-RemoveCtrlPathLevel+1,-1)]+[
                x for x in SubPath if x not in [".",".."]])
            print("Link af", Link)
            '''
            print("CtrlDir", CtrlDir)
            Link = CtrlDir + "/"+Link
            #Link = CtrlDir+'.'.join(Link.split(".")[1:])
        #elif (not Link.startswith("http")) and ("aspx" in Link):
        elif (not Link.startswith("http")) and (not Link.startswith("/")):
            Link = HomeLink+"/"+Link
    return Link

def LinkFillerOld(Link, CtrlPath):
    CtrlDir = "/".join(CtrlPath.split("/")[:-1])
    HomeLink = "/".join(CtrlPath.split("/")[0:3])
    if Link.startswith("."):
        Link = CtrlDir+'.'.join(Link.split(".")[1:])
    elif Link.startswith("/"):
        Link = HomeLink+Link
    elif Link.startswith("#"):
        Link = CtrlPath.split("#")[0]+"#"+Link.split("#")[1]
    #elif (not Link.startswith("http")) and ("aspx" in Link):
    elif (not Link.startswith("http")) and (not Link.startswith("/")):
        Link = HomeLink+"/"+Link
    return Link

def BackUp(FileName):
    if "." in FileName:
        ext = FileName.split(".")[-1]
        dst = FileName.replace(ext,"_{}.{}".format(timeNow(),ext))
    else:
        dst = FileName + ext,timeNow()
    MES = "Backuping file {} as {}".format(FileName, dst)
    MPlogger().logW(MES)
    shutil.copyfile(FileName, dst)
                    

'''
#移到TextProcessor_utils.py
class strQ2BConverter:
    """ 全型字母、數字、括弧、空白轉半型 """
    def __init__(self):
        src = "１２３４５６７８９０ＡＢＣＤＥＦＧＨＩＪＫＬＭＮＯＰＱＲＳＴＵＶＷＸＹＺａｂｃｄｅｆｇｈｉｊｋｌｍｎｏｐｑｒｓｔｕｖｗｘｙｚ（）［］　"
        des = "1234567890ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz()[] "
        self.convertDict = dict(zip(src,des))
        for x in ["ꎬ ","ꎮ ","ꎮ ","ꎻ "]:
        #for x in ["ꎬ "]:
            self.convertDict[x] ="，"
    def proc(self, text):
        result = text
        for x in self.convertDict.keys():
            result = result.replace(x, self.convertDict[x])
        return result
'''
        
def hasher(data, method="sha512"):
    m = getattr(hashlib, method)()
    if data == None:
        return None
    try:
        m.update(data)
    except:
        data = data.encode('utf-8')
        m.update(data)
    return m.hexdigest()


class FileHashDictBuilder:
    def __init__(self, fileList, hashalg = "md5", nBytes = None):
        self.fileList = fileList
        self.nBytes = nBytes
        self.hashalg = hashalg
    def show(self,):
        print("="*50)
        print("for FileHashDictBuilder, fileList[0:3]:", self.fileList[0:3])
    def run(self):
        hashDict = {}
        ndup = 0
        for file in self.fileList:
            hashval = hasher(
                open(file,'rb').read(self.nBytes), self.hashalg)
            if hashval in hashDict.keys():
                ndup += 1
            hashDict[file] = hashval
        return hashDict

def removeStrPrefix(inpStr, prefix):
    if inpStr.startswith(prefix):
        return inpStr[len(prefix):]
    else:
        return inpStr

def removeStrSuffix(inpStr, suffix):
    if inpStr.endswith(suffix):
        return inpStr[:-len(suffix)]
    else:
        return inpStr
    
def wrap(s, w, pieceUBD = math.inf):
    return [s[i:i + w] for i in range(0, min(len(s),pieceUBD*w), w)]

def OffsetWrap(s, StartOffset, ChunkUnit):
    return [s[i:i + ChunkUnit] for i in range(0, len(s), StartOffset)]

def split_text_by_line_and_length(text, max_length):
    """
    依斷行切割文本為多片，並確保每片最大長度小於max_length
    :param text: 要切割的文本
    :param max_length: 每片的最大長度
    :return: 切割後的文本清單
    """
    lines = text.split('\n')
    chunks = []
    current_chunk = ""

    for line in lines:
        if len(current_chunk) + len(line) + 1 <= max_length:
            if current_chunk:
                current_chunk += "\n"
            current_chunk += line
        else:
            # 如果納入該行後會超過max_length，則將該行分成前後兩段
            remaining_length = max_length - len(current_chunk) - 1
            if remaining_length > 0:
                current_chunk += "\n" + line[:remaining_length]
                chunks.append(current_chunk)
                current_chunk = line[remaining_length:]
            else:
                chunks.append(current_chunk)
                current_chunk = line

            # 如果剩下的後段超過max_length，則繼續將其分割成多個小於或等於max_length的片段
            if len(current_chunk) > max_length:
                sub_chunks = [current_chunk[i:i+max_length] for i in range(0, len(current_chunk), max_length)]
                chunks.extend(sub_chunks[:-1])
                current_chunk = sub_chunks[-1]

    if current_chunk:
        chunks.append(current_chunk)

    return chunks

def atoi(text):
    return int(text) if text.isdigit() else text

def getLineOfMaxLen(strX):
    #NumberTypes = (types.IntType, types.LongType, types.FloatType, types.ComplexType)
    #if isinstance(strX, NumberTypes) == True:
    if isinstance(strX, (int, float, complex)) == True:
        #strX = str(strX)
        return [strX]
    elif strX is None:
        return [""]
    strX = str(strX)
    Lines = strX.split("\n")
    Lens = [len(x) for x in Lines]
    MaxLen = max(Lens)
    return [x for x in Lines if len(x) == MaxLen]

def natural_keys(text):
    '''
    alist.sort(key=natural_keys) sorts in human order
    http://nedbatchelder.com/blog/200712/human_sorting.html
    (See Toothy's implementation in the comments)
    '''
    return [ atoi(c) for c in re.split(r'(\d+)', text) ]

def removekey(d, key):
    r = dict(d)
    del r[key]
    return r

def GetFileSize(FilePath):
    return Path(FilePath).stat().st_size

def WaitUntilFileIsStable(WatchedFN, 
                          WatchClockTime=3,
                          WatchedTimeBound=300, 
                          logFile = "Watching_File_Log.txt"):
    def GetFileSizeAndWait(WatchedTime,WatchClockTime):
        FileSize = Path(WatchedFN).stat().st_size
        time.sleep(WatchClockTime)
        WatchedTime += WatchClockTime
        return FileSize, WatchedTime
    #監控檔案是否出現。
    WatchedTime = 0
    while not os.path.isfile(WatchedFN):
        time.sleep(WatchClockTime)
        WatchedTime += WatchClockTime
        MES = "Watching File {} for {} Secs.".format(WatchedFN,WatchedTime)
        MPlogger().logW(MES,logFile=logFile)
        if WatchedTime > WatchedTimeBound:
            MES = "File {} has not been present for {} secs. Abort watching.".format(
                WatchedFN,WatchedTime)
            MPlogger().logW(MES,logFile=logFile)
            return
    #監控檔案大小是否有變更。
    WatchedTime = 0
    FileSize, WatchedTime = GetFileSizeAndWait(WatchedTime,WatchClockTime)
    while(Path(WatchedFN).stat().st_size > FileSize):
        FileSize, WatchedTime = GetFileSizeAndWait(WatchedTime,WatchClockTime)
        MES = "Watching File {} for {} Secs. Filesize is {} Bytes.".format(
            WatchedFN,WatchedTime,Path(WatchedFN).stat().st_size)
        MPlogger().logW(MES,logFile=logFile)
        if WatchedTime > 2*WatchedTimeBound:
            MES = "File {} has kept changing for {} secs. Abort watching.\n".format(
                WatchedFN,WatchedTime)
            MES += f"FileSize is {FileSize}"
            MPlogger().logW(MES,logFile=logFile)
            return

def ExtractRar(InputFN, output_dir="."):
    # 檢查是否安裝了解壓工具
    if not rarfile.is_rarfile(InputFN):
        print(f"解壓失敗: {InputFN} 不是合法的 RAR 檔案")
        return

    # 生成解壓目錄
    SubDir = os.path.join(output_dir, os.path.splitext(os.path.basename(InputFN))[0])
    os.makedirs(SubDir, exist_ok=True)

    try:
        # 使用 rarfile 解壓
        with rarfile.RarFile(InputFN, 'r') as archive:
            archive.extractall(path=SubDir)
        print(f"Finished ExtractRAR {InputFN} to {SubDir}")
    except rarfile.BadRarFile:
        print(f"解壓失敗: {InputFN} 不是合法的 RAR 檔案")
    except Exception as e:
        print(f"解壓失敗: {e}")

'''
def Extract7z(InputFN, output_dir="."):
    SubDir = os.path.join(output_dir, os.path.splitext(os.path.basename(InputFN))[0])
    os.makedirs(SubDir, exist_ok=True)
    try:
        with py7zr.SevenZipFile(InputFN, mode='r') as archive:
            archive.extractall(path=SubDir)
    except Exception as e:
        print(f"解壓失敗: {e}")
    print(f"Finished ExtractZIP {InputFN} to {SubDir}")
'''

def ExtractWith7Z(InputFN, output_dir="."):
    SubDir = os.path.join(output_dir, os.path.splitext(os.path.basename(InputFN))[0])
    os.makedirs(SubDir, exist_ok=True)

    success = False

    print("🔧 嘗試使用 7z 解壓縮...")
    try:
        result = subprocess.run(
            ['7z', 'x', InputFN, f'-o{SubDir}', '-y'],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )

        if result.returncode == 0:
            print(f"✅ 使用 7z 解壓成功！位置：{SubDir}")
            success = True
        else:
            print("⚠️ 7z 解壓失敗，嘗試使用 Python zipfile 模組")
            print(result.stderr)

    except FileNotFoundError:
        print("❌ 系統找不到 7z 指令，將改用 Python zipfile 模組解壓縮")

    if success:
        print(f"\n🎉 全部解壓完成！位置：{SubDir}")
    else:
        print("🚫 解壓縮完全失敗。請確認 zip 檔格式是否正確。")
        
def ExtractZip(InputFN, output_dir=".", prefer_7z=True):
    SubDir = os.path.join(output_dir, os.path.splitext(os.path.basename(InputFN))[0])
    os.makedirs(SubDir, exist_ok=True)

    success = False

    # 嘗試使用 7z 解壓縮
    if prefer_7z:
        print("🔧 嘗試使用 7z 解壓縮...")
        try:
            result = subprocess.run(
                ['7z', 'x', InputFN, f'-o{SubDir}', '-y'],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )

            if result.returncode == 0:
                print(f"✅ 使用 7z 解壓成功！位置：{SubDir}")
                success = True
            else:
                print("⚠️ 7z 解壓失敗，嘗試使用 Python zipfile 模組")
                print(result.stderr)

        except FileNotFoundError:
            print("❌ 系統找不到 7z 指令，將改用 Python zipfile 模組解壓縮")

    # 如果 7z 沒成功，改用 zipfile 處理
    if not success:
        encodings = ['utf-8', 'big5', 'gbk']
        try:
            with zipfile.ZipFile(InputFN, 'r') as z:
                for file_info in z.infolist():
                    print(f"📦 處理原始名稱: {file_info.filename}")
                    decoded = False
                    for enc in encodings:
                        try:
                            filename = file_info.filename.encode('cp437').decode(enc)
                            decoded = True
                            break
                        except Exception:
                            continue
                    
                    if not decoded:
                        print(f"❌ 無法解碼檔名：{file_info.filename}（使用 {encodings}）")
                        continue

                    target_path = os.path.join(SubDir, filename)
                    os.makedirs(os.path.dirname(target_path), exist_ok=True)

                    with open(target_path, 'wb') as f_out, z.open(file_info) as f_in:
                        shutil.copyfileobj(f_in, f_out)
                    print(f"✅ 解壓完成：{target_path}")
            success = True
        except Exception as e:
            print(f"❌ Python zipfile 解壓失敗：{e}")

    if success:
        print(f"\n🎉 全部解壓完成！位置：{SubDir}")
    else:
        print("🚫 解壓縮完全失敗。請確認 zip 檔格式是否正確。")
        
def ExtractZip_old3(InputFN, output_dir="."):
    SubDir = os.path.join(output_dir, os.path.splitext(os.path.basename(InputFN))[0])
    os.makedirs(SubDir, exist_ok=True)

    encodings = ['utf-8', 'big5', 'gbk']  # 嘗試解碼的編碼順序

    with zipfile.ZipFile(InputFN, 'r') as z:
        for file_info in z.infolist():
            print(f"📦 處理原始名稱: {file_info.filename}")
            decoded = False
            for enc in encodings:
                try:
                    filename = file_info.filename.encode('cp437').decode(enc)
                    decoded = True
                    break
                except Exception:
                    continue
            
            if not decoded:
                print(f"❌ 無法解碼檔名：{file_info.filename}（使用 {encodings}）")
                continue

            target_path = os.path.join(SubDir, filename)
            target_folder = os.path.dirname(target_path)
            os.makedirs(target_folder, exist_ok=True)

            with open(target_path, 'wb') as f_out, z.open(file_info) as f_in:
                f_out.write(f_in.read())
            print(f"✅ 解壓完成：{target_path}")

    print(f"\n🎉 全部解壓完成！位置：{SubDir}")


def ExtractZip_Old2(InputFN, output_dir="."):
    os.system("set PYTHONUTF8=1")
    os.system("set PYTHONIOENCODING=utf8")
    
    with zipfile.ZipFile(InputFN, 'r') as files:
        SubDir = os.path.join(output_dir, ".".join(InputFN.split(".")[:-1]))
        os.makedirs(SubDir, exist_ok=True)  # 確保目錄存在
        
        encodings = ['utf-8', 'big5', 'gbk']  # 定義嘗試的編碼順序
        for file_info in files.infolist():
            print(f"extracting {file_info.filename}")
            decoded = False
            for encoding in encodings:
                try:
                    # 嘗試使用不同編碼解碼
                    file_info.filename = file_info.filename.encode('cp437').decode(encoding)
                    decoded = True
                    break  # 解碼成功，退出編碼嘗試
                #except UnicodeDecodeError:
                except:
                    continue  # 解碼失敗，嘗試下一個編碼
            
            if not decoded:
                # 所有編碼皆失敗，顯示錯誤訊息
                print(f"用{encodings}，無法解碼檔案名稱: {file_info.filename}")
                continue  # 跳過該檔案
            
            files.extract(file_info, SubDir)
    
    print(f"Finished ExtractZIP {InputFN} to {SubDir}")

def ExtractZip_Old(InputFN):
    files = zipfile.ZipFile(InputFN, 'r')
    SubDir = ".".join(InputFN.split(".")[:-1])
    MKDIR(SubDir)
    files.extractall(SubDir)
    '''
    for fn in files.namelist():
        print("fn",fn)
        extracted_path = Path(files.extract(
            fn,path = SubDir))
        src = os.path.join(SubDir, fn)
        des = os.path.join(SubDir, fn.encode('cp437').decode('gbk'))
        shutil.move(src, des)
        #extracted_path.rename(fn.encode('cp437').decode('gbk'))
    files.close()
    '''

def GetDigitElementsOfaList(InputList):
    r = re.compile("^[0-9]+$")
    return list(filter(r.match, list(InputList)))

def GetnDigitElementsOfaList(InputList):
    r = re.compile("^[0-9]+$")
    return len(list(filter(r.match, list(InputList))))

def countnDigits(string):
    total_digits = 0
    for s in string:
        if s.isnumeric():
            total_digits += 1
    return total_digits

def GetRatioOfDigits(InString, SpaceExcluded = True):
    LenIn = len(InString)
    if SpaceExcluded == True:
        Len = LenIn-InString.count(' ')
    else:
        Len = LenIn
    nDigits = GetnDigitElementsOfaList(list(InString))
    return nDigits/Len

def KeyWordsListToRegx(KeyWordsList):
    regxLists = []
    for kw in KeyWordsList:
        if ".*" not in kw:
            regxLists.append(".*"+kw)
        else:
            regxLists.append(kw)
    result = ""
    for i,regx in enumerate(regxLists):
        if i == 0:
            result += f"({regx})"
            continue
        result += f"|({regx})"
    return result

def CopyOrMoveWithFNList(
    SrcRoot="", DesRoot="",
    FNMatchingMode="Part",FNPatList=[]):
    for file in OSWALK(SrcRoot):
        SrcFN = getFNFromFullPath(file)
        for FNPat in FNPatList:
            if FNPat in SrcFN:
                des = os.path.join(DesRoot,SrcFN)
                shutil.copyfile(file,des)
                continue

class DateExtractor:
    def proc(InputStr=""):
        r'''
        MatchResult = re.findall('20\d{6}',InputStr)
        if len(MatchResult) > 0:
            return MatchResult[0]
        #else:
            #return False
        '''
        MatchResult = re.search(r'20\d{6}',InputStr)
        if MatchResult is not None:
            return MatchResult.group()


def RandomSample(InList, nSample):
    return random.sample(InList, min(len(InList),nSample))

def id_generator(size=6, chars=string.ascii_uppercase + string.digits):
    return ''.join(random.choice(chars) for _ in range(size))

def randomReplace(text,nReplacedChar=1):
    textSP = list(text)
    textSP[random.randint(0,len(textSP)-1)] = id_generator(size=1)
    return ''.join(textSP)
    
def IdentifyFMT(TimeList):
    if type(TimeList) is not list: #如果輸入僅為一個單一時間，而非list，將其自動轉為list。
        TimeList = [TimeList]
    TimeList = [str(x) for x in TimeList]
    #Time = str(Time)
    #if int(str(Time)[0:4])>2100 or int(str(Time)[0:4])<1990:
        #print("WARNING! The time period format identification for ", Time, " fails. ABORT!")
        #raise Exception
    FMTCandicates = [
        '%Y%m%d',
        '%m%d%H%M',
        '%m%d %H:%M',
        '%Y%m%d%H',
        '%m%d %H',
        '%Y%m%d%H%M',
        '%H:%M',
        '%Y%m%d%H%M%S',
        '%Y-%m-%d %H:%M',
        '%m%d',
        '%H%M'
        ]
    for FMT in FMTCandicates:
        try:
            for Time in TimeList:
                _ = dte.datetime.strptime(Time, FMT)
            #print("For time {}, its FMT is identified as {}.".format(TimeList, FMT))
            return FMT
        except ValueError:
            pass
    print("WARNING! WARNING! The time period format identification for", TimeList, " fails, ABORT!")
    return None


def ConvertTimeStrFMT(
        TimeStr,srcFMTCands=["%Y-%m-%dT%H:%M:%S"],
        desFMT="%Y%m%d",
        debug = False):
    for srcFMT in srcFMTCands:
        #timeObj = dte.datetime.strptime(TimeStr, srcFMT)
        try:
            timeObj = dte.datetime.strptime(TimeStr, srcFMT)
            return dte.datetime.strftime(timeObj, desFMT)
        except Exception as e:
            if debug == True:
                print(e)
            pass

def ReadTimeStr(TimeStr,FMTCands=["%Y%m%d","%Y-%m-%dT%H:%M:%S"]):
    TimeStr = TimeStr.lstrip("🌎")
    for FMT in FMTCands:
        try:
            timeObj = dte.datetime.strptime(TimeStr, FMT)
            return timeObj
        except:
            pass
    

def remove_duplicates(ROOTPATH,delImmediately = False):
    unique = []
    for file in OSWALK(ROOTPATH):
        #print(f"Dealing file {file}")
        #src = os.path.join(dir,file)
        if os.path.isfile(file):
            #filehash = md5.md5(file(src).read()).hexdigest()
            filehash = hasher(
                open(file,encoding = 'utf-8').read())
            #print("filehash", filehash)
            if filehash not in unique: 
                unique.append(filehash)
            else:
                if delImmediately == True:
                    os.remove(file)
                    MES = f"The file {file} is a duplicate and deleted"
                else:
                    desSubDir = os.path.join(ROOTPATH,"duplicates")
                    des = os.path.join(desSubDir,getFNFromFullPath(file))
                    MKDIR(desSubDir)
                    shutil.move(file, des)
                    MES = f"The file {file} is a duplicate and moved {desSubDir}"
                MPlogger().logW(MES,logFile="FileProcessingLog.txt")

def rindex(lst, value):
    return len(lst)-operator.indexOf(reversed(lst), value)-1


def RandomColor(seed = None):
    random.seed(seed)
    hexadecimal = "#"+''.join([random.choice('ABCDEF0123456789') for i in range(6)])
    #print("A Random color is :",hexadecimal)
    return hexadecimal

class DictSaver:
    def proc(dic, OMFN = "DictSaver", filefmt = 'json'):
        MKDIR(getPathFromFN(OMFN))
        if filefmt == "json":
            ext = "json"
        OPTFN = f"{OMFN}.{ext}"
        f = open(OPTFN, "wt",encoding='utf-8')
        json.dump(dic, f, indent=4)
        f.close()
        
class DictTransposer:
    def proc(dic):
        '''
        Parameters
        ----------
        dic : dict
            DESCRIPTION. A dictionary of dictionaries

        Returns
        -------
        res : dict
            DESCRIPTION. Transpose of the input dictionary of dictionaries

        '''
        
        res = dict()
        for outerKey in dic:
            for innerKey in dic[outerKey]:
                if innerKey not in res.keys():
                    res[innerKey] = dict()
                res[innerKey][outerKey] = dic[outerKey][innerKey]
        return res



def IsProcessRunning(procName):
    #print("psutil.process_iter()",[p.name() for p in psutil.process_iter()])
    return procName in (p.name() for p in psutil.process_iter())
def nProcessRunningWithName(procName):
    #print("psutil.process_iter()",[p.name() for p in psutil.process_iter()])
    return [p.name() for p in psutil.process_iter()].count(procName)


def str2bool(v):
    if isinstance(v, bool):
        return v

    v = str(v).strip().lower()

    true_set = {
        'yes', 'true', 't', 'y', '1',
        'on', 'ok', 'sure', 'enabled',
        '開', '啟用', '是', '好', '好啊', '可以'
    }

    false_set = {
        'no', 'false', 'f', 'n', '0',
        'off', 'cancel', 'none', 'disabled',
        '關', '停用', '否', '不要', '不行', '不可以'
    }

    if v in true_set:
        return True
    elif v in false_set:
        return False
    else:
        raise argparse.ArgumentTypeError(
            f"Boolean value expected. 接受值如: {', '.join(sorted(true_set | false_set))}"
        )


def strip_end(text, suffix):
    if suffix and text.endswith(suffix):
        return text[:-len(suffix)]
    return text


'''
def clearPort(process):
    #if "windows" not in platform.system().lower():
    if IsWindows() == False:
        pkillsh = "/mntCZJ/dockerpkill.sh"
        with open(pkillsh,'wt') as f:
            f.write(f"pkill {process}\n")
        os.system(f"chmod 700 {pkillsh};{pkillsh}")
        time.sleep(2)
'''
def clear_port(process_name):
    if not process_name or not process_name.strip():
        raise ValueError("process_name 不可為空")
            
    if "windows" in platform.system().lower():
        # 強制結束同名行程
        subprocess.run(["taskkill", "/F", "/IM", process_name], check=False)
        # 若需依指令列內容比對可改用 PowerShell Stop-Process -Id 或 -Name
    else:
        # -f 以完整指令列比對；避免 shell 注入，使用 list 參數
        subprocess.run(["pkill", "-f", process_name], check=False)
    time.sleep(5)

clearPort = clear_port
    
def save_dicts_to_txt(input_dir):
    '''
    預期格式為：[字典1,字典2,字典3,...]
    '''
    # 生成输出目录名称
    output_dir = input_dir + "_sessions"

    # 确保输出目录存在
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    # 遍历输入目录及其子目录下的所有txt文件
    for root, dirs, files in os.walk(input_dir):
        for filename in files:
            if filename.endswith('.txt'):
                print(f"{filename} is running save_dicts_to_txt.")
                file_path = os.path.join(root, filename)
                with open(file_path, 'r', encoding='utf-8') as file:
                    # 读取JSON格式的字典列表
                    dict_list = json.load(file)
                
                # 生成子目录名称
                relative_path = os.path.relpath(root, input_dir)
                sub_dir = os.path.join(output_dir, relative_path, filename.replace('.txt', ''))
                if not os.path.exists(sub_dir):
                    os.makedirs(sub_dir)

                # 資料處理格式，可能會產生不合格式：[[字典1,字典2],[字典3,字典4]]
                tmp_dict_list = []
                for subterm in dict_list:
                    if isinstance(subterm,dict):
                        tmp_dict_list.append(subterm)
                    elif isinstance(subterm,list):
                        tmp_dict_list.extend([x for x in subterm if isinstance(x,dict)])
                    elif isinstance(subterm,str):
                        continue
                    else:
                        print("subterm",subterm)
                        print("type(subterm)",type(subterm))
                        print(f"When making dict_list for {filename}, error occurs.")
                        raise Exception
                dict_list=tmp_dict_list
                #print("dict_list",dict_list)
                # 保存每个字典到单独的txt文件
                for idx, item in enumerate(dict_list):
                    # 获取title值并去除特殊字符
                    try:
                        title = item.get('title', '').replace('/', '_').replace('\\', '_').replace(':', '_')
                        # 生成文件名
                        file_name = f"{title}_{idx + 1}.txt"
                        file_path = os.path.join(sub_dir, file_name)
    
                        # 写入文件
                        with open(file_path, 'w', encoding='utf-8') as file:
                            for key in item.keys():
                                if key == 'title':
                                    # 处理title中的特殊字符
                                    value = item[key].replace('/', '_').replace('\\', '_').replace(':', '_')
                                else:
                                    value = item[key]
                                file.write(f"{key.capitalize()}: {value}\n")
                    except Exception as ex:
                        print("When handling the followint item, the error occurs.")
                        print("Item:",item)
                        print("filename",filename)
                        print("Error:",ex)
                        raise Exception

                    print(f"Saved {file_name} in {sub_dir}")


                


def MemDictTest(varPre = "NO"):
    setproctitle.setproctitle("TestMemUsage")
    A = {varPre+str(i):i for i in range(1000000)}
    print(len(A))
    print("Mem Usage:",sys.getsizeof(A))
    #print("A",A)
    '''
    start_time = time.time()
    print("Start to load A.")
    ShowElapsedTime(start_time)
    Serializer(obj=A,BaseFileName="TestMemUsageSerializer").load()
    print("Finished load A.")
    ShowElapsedTime(start_time)
    Serializer(obj=A,BaseFileName="TestMemUsageSerializer").save()
    '''
    print("finish to wait closing")
    #time.sleep(30)

def chownPath(path):
    try:
        CMD = f"chown 64001:64001 {path}"
        os.system(CMD)
    except Exception as e:
        print(e)

def getIP():
    if IsWindows():
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(("8.8.8.8", 80))
                return s.getsockname()[0]
        except Exception as e:
            print(f"Error getting IP: {e}")
            return None
    else:
        hostname = socket.gethostname()
        ip_lists = socket.gethostbyname_ex(hostname)[2]
        ip_lists_192 = [ip for ip in ip_lists if ip.startswith('192.168.0')]
        return ip_lists_192[0] if ip_lists_192 else ip_lists[0]

def colored_print(text, color="lightyellow_ex"):
    color_map = {
        'black': Fore.BLACK,
        'red': Fore.RED,
        'green': Fore.GREEN,
        'yellow': Fore.YELLOW,
        'blue': Fore.BLUE,
        'magenta': Fore.MAGENTA,
        'cyan': Fore.CYAN,
        'white': Fore.WHITE,
        'lightblack_ex': Fore.LIGHTBLACK_EX,
        'lightred_ex': Fore.LIGHTRED_EX,
        'lightgreen_ex': Fore.LIGHTGREEN_EX,
        'lightyellow_ex': Fore.LIGHTYELLOW_EX,
        'lightblue_ex': Fore.LIGHTBLUE_EX,
        'lightmagenta_ex': Fore.LIGHTMAGENTA_EX,
        'lightcyan_ex': Fore.LIGHTCYAN_EX,
        'lightwhite_ex': Fore.LIGHTWHITE_EX,
    }
    
    color_code = color_map.get(color.lower(), Fore.RESET)
    print(f"{color_code}{text}{Style.RESET_ALL}")
def tlog(s):
    #tlog = lambda s: tqdm.write(Fore.CYAN + s + Style.RESET_ALL)
    return tqdm.write(Fore.CYAN + s + Style.RESET_ALL)
    
if __name__ == '__main__':
    '''
    A = {"Suan Ming-TW Affairs": 1}
    B = {"Showbiz": 2, "Constellation": 1, "Exempt-Showbiz": 1}
    A = {'TW Showbiz': 2, 'Exempt-Showbiz': 2, 'Suan Ming-TW Affairs': 2, 'Showbiz': 1, 'Scrap': 2, 'Suan Ming': 1}
    B = {'Showbiz': 3, 'Constellation': 2, 'Exempt-Showbiz': 2, 'Scrap': 2}
    '''
    
    #print(DateList(freq='SM',FMT = "%Y-%m%d %H:%M:%S"))
    #print(DateList(freq='D'))
    #print(timeRelative(args={"months":-6},outputFMT = "%Y%m%d"))
    varRepeat = 1
    #MemDictTest(varPre = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"*varRepeat)
    #InnerCrossSimilarityForTextListTest()
    #RAGChunks = JsonHandler(file="RAGTest.json").load()
    #OptionSelector(options={"Chinese":"中文","English":"英文","NoExp":""}).proc()
    #InteractiveOptionSelector(options={"Chinese1":"3333333333中文","English":"英文","NoExp":""}).proc()
    #print(getIP())
    ExtractZip(InputFN="C:/Users/AI/Downloads/自傳測試集.zip", output_dir="C:/Users/AI/Downloads/TestExtractZip")