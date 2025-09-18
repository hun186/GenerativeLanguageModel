from PackageImport import PackageImporter
PackageImporter.proc()

import os
import sys
import time
import multiprocessing as mp
import re
import hashlib
import shutil
import psutil
try:
    import humanize
except Exception as e:
    print(e)
    pass

import pathlib
from pathlib import Path
import platform
import collections
import json
import string
import ast
#import psutil,GPUtil
import math
import statistics 
import GPUtil
import argparse
import numpy as np
from numpy.linalg import norm
from collections import Counter
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
#try:
#    import jellyfish
#except:
#    pass

try:
    from utils.MP_utils import MPlogger
except:
    from .MP_utils import MPlogger

import zipfile as zf
'''
try:
    import utils.Edited_zipfile as zf
except:
    import Edited_zipfile as zf
'''
#from PyQt5 import QtWidgets
#from PyQt5.QtWidgets import QWidget
import random
import difflib

try:
    from cdifflib import CSequenceMatcher
    difflib.SequenceMatcher = CSequenceMatcher
except:
    pass

#from diff_match_patch import diff_match_patch
try:
    import diff_match_patch
except Exception as e:
    MES = f"When loading the module diff_match_patch, the following error occurs:\n{e}"
    MPlogger().logW(MES, logFile="ModuleNotFoundError.log")

import _pickle as pickle


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

class fileNameNormalizer:
    def proc(fileName):
        return fileName.replace("\\","/")

def PathSEP(filePath):
    if "/" in filePath:
        SEP = "/"
    elif "\\" in filePath:
        SEP = "\\"
    else:
        SEP = os.path.sep
    return SEP

class pathSpliter:
    def proc(filePath):
        #filePath = fileNameNormalizer.proc(filePath)
        #for pathSep in ["/","\\"]:
            #filePath = filePath.split(pathSep)
        #return filePath.split(PathSEP(filePath))
        return re.split("/|\\\\",filePath)


class fileNameReplacer:
    def proc(ROOTPATHList,ReplaceDict = {},
             ReplaceDirNameOnly=False,RemoveEmptyFolder = False):
        counter = 0
        for ROOTPATH in ROOTPATHList:
            for file in OSWALK(ROOTPATH):
                #print("dealing {}".format(file))
                src = fileNameNormalizer.proc(file)
                des = src
                for key in ReplaceDict.keys():
                    desSubDir = des.rpartition("/")[0]
                    if ReplaceDirNameOnly == False:
                        des = des.replace(key, ReplaceDict[key])
                    elif ReplaceDirNameOnly == True:
                        desSubDir = desSubDir.replace(key, ReplaceDict[key])
                        des = os.path.join(desSubDir,getFNFromFullPath(des))
                des = fileNameNormalizer.proc(des)
                
                if src != des:
                    srcSubDir = src.rpartition("/")[0]#'/'.join(pathSpliter.proc(src)[:-1])
                    desSubDir = des.rpartition("/")[0]#'/'.join(pathSpliter.proc(des)[:-1])
                    MKDIR(desSubDir)
                    shutil.move(src, des)
                    MES = "Move {} to {}".format(src,des)
                    MPlogger().logW(MES,logFile="FileProcessingLog.txt")
                    if RemoveEmptyFolder == True and len(os.listdir(srcSubDir)) == 0:
                        shutil.rmtree(srcSubDir)
                    counter += 1
        MES = "="*50+"\nThere are totally {} files renamed.".format(counter)
        MPlogger().logW(MES,logFile="FileProcessingLog.txt")

'''
def pathSeqFromFN(file):
    file = fileNameNormalizer.proc(file)
    return file.split("/")
'''

class RENormalizer:
    def proc(rexp):
        #如果輸入為一堆正規表示式清單，將其以or形式串接回傳。
        if type(rexp) is list:
            return '|'.join([f"({x})" for x in rexp])
        elif type(rexp) is str:
            return rexp


def OSWALK(ROOTPATH, Extension = [], 
           FNrePat = None, FullPathFNrePat = None):
    if type(Extension) == str:
        Extension = [Extension]
    Extension = [x.lower() for x in Extension]
    result = []
    for dirPath, dirNames, fileNames in os.walk(ROOTPATH):
        for i,f in enumerate(fileNames):
            FullPathFN = os.path.join(dirPath, f)
            if FNrePat is not None:
                if not re.search(FNrePat,f):
                    continue
            if FullPathFNrePat is not None:
                if not re.search(FullPathFNrePat,FullPathFN):
                    continue
            if Extension == [] or any(f.lower().endswith(x) for x in Extension):
                result.append(FullPathFN)
    result = [fileNameNormalizer.proc(x) for x in result]
    return result

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
        result = inputObj
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

import timeit
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
    def proc():
        if self.queryVector == []:
            print("for DictQueryer, ")
            return
        res = None
        return res
        
def frequency_sort(lst):
    counts = collections.Counter(lst)
    return sorted(lst, key=lambda x: (counts[x], x), reverse=True)
    
    
def ShortenFN(FN):
    LeftFNLen = min(100,len(getPathFromFN(FN)))
    print("getMFNFromFN(FN)",getMFNFromFN(FN))
    LeftFN = ('{}.{}').format(
        getMFNFromFN(FN)[:100],
        pathSpliter.proc(FN)[-1].rpartition(".")[-1])
    return getPathFromFN(FN)+PathSEP(FN)+LeftFN
    
def getPathFromFN(FN, removeDrive = True):
    pathList = pathSpliter.proc(FN)[:-1]
    #Drive = ""
    if removeDrive == True:
        if re.match("^[A-Z,a-z]:$",pathList[0]):
            #Drive = pathList[0]
            pathList = pathList[1:]
    res = PathSEP(FN).join(pathList)
    #res = re.sub("^[A-Z,a-z]:$","",res)
    return res

def InsertDirnameToFN(FN, insPos = 0, insDirname = ""):
    pathList = pathSpliter.proc(FN)
    pathList.insert(insPos,insDirname)
    res = PathSEP(FN).join(pathList)
    #res = re.sub("^[A-Z,a-z]:$","",res)
    return res

def getMFNFromFN(FN):
    '''
    e.g: known_pictures\Hong Kong\artist\Aaron Kwok[3].jpg => Aaron Kwok[3]
    '''
    FN = getFNFromFullPath(FN)
    if "." in FN:
        return FN.rpartition(".")[0]
    else:
        return FN
    '''
    return pathSpliter.proc(FN)[-1].rpartition(".")[0]
    result = FN.split(PathSEP(FN))[-1].rpartition(".")[0]
    if result == "":
        result = "MFN_Detection_Failure"
    return result
    '''
       
def getFNFromFullPath(FN):
    '''
    e.g: known_pictures\Hong Kong\artist\Aaron Kwok[3].jpg => Aaron Kwok[3].jpg
    '''
    try:
        return os.path.basename(FN)
    except Exception as e:
        MES = f"When applying getFNFromFullPath to {FN}, the following error occurs:\n{e}"
        MPlogger().logW(MES, logFile="getFNFromFullPathError.log")
        return None

    
def getFNExtFromFullPath(FN,lower = False):
    '''
    e.g: known_pictures\Hong Kong\artist\Aaron Kwok[3].jpg => jpg
    '''
    #os.path.splitext(x)[1][1:] #".txt" -> "", which is not as expected!
    Ext = getFNFromFullPath(FN).rpartition(".")[2]
    if lower is True:
        return Ext.lower()
    else:
        return Ext

def AppendedMFN(FN,appendStr = "", includeOriDir= True):
    MFN = getMFNFromFN(FN)+appendStr

    #result = MFN+"."+FN.split(PathSEP(FN))[-1].rpartition(".")[2]
    result = MFN+"."+pathSpliter.proc(FN)[-1].rpartition(".")[2]
    if includeOriDir == True:
        #result = PathSEP(FN).join(FN.split(PathSEP(FN))[:-1]+[result])
        result = PathSEP(FN).join(pathSpliter.proc(FN)[:-1]+[result])

    return result

def getFileDirFromFN(FN):
    '''
    e.g: known_pictures\Hong Kong\artist\Aaron Kwok[3].jpg => known_pictures\Hong Kong\artist
    '''
    FN = fileNameNormalizer.proc(fileName = FN)
    FileDir = FN.rpartition("/")[0]
    if FileDir == "":
        FileDir = "./"
    return FileDir

class FileNamePicker:
    def __init__(self, dirList, FNrePatList, method="OR"):
        self.dirList = dirList
        self.FNrePatList = FNrePatList
        self.method = method
    def show(self,):
        print("="*50)
        print("for FileNamePicker, dirList[0:3]:", self.dirList[0:3])
        print("for FileNamePicker, FNrePatList[0:3]:", self.FNrePatList[0:3])
    def proc(self):
        self.show()
        res = []
        for dirName in self.dirList:
            for file in OSWALK(dirName):
                if self.method == "OR":
                    if any([re.search(FNrePat,getFNFromFullPath(file)) 
                        is not None for FNrePat in self.FNrePatList]):
                        res.append(file)
                elif self.method == "AND":           
                    if all([re.search(FNrePat,getFNFromFullPath(file)) 
                        is not None for FNrePat in self.FNrePatList]):
                        res.append(file)
        return res

        
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
                    
def MKDIR(DirName):
    if DirName == "":
        #print("DirName is empty string, skipping MKDIR(DirName).")
        return
    fileNameNormalizer.proc(DirName)
    os.makedirs(DirName, exist_ok=True)

def MKDIRandCopy(src,des):
    MKDIR(getPathFromFN(des))
    shutil.copy(src, des)

def RESETDIR(DirName):
    if os.path.isdir(DirName):
        shutil.rmtree(DirName, ignore_errors=False, onerror=None)
    MKDIR(DirName)

def RemoveIlleagalCharForFileName(title, Mode = "FileName"):
    result = title
    IlleagalMapDict = {}
    IlleagalMapDict["'"] = "’"
    if Mode == "FileName":
        IlleagalSet = ['/','\\',':','?','\"','<','>','|','\n','\xa0','\t','*']
        for x in IlleagalSet:
            IlleagalMapDict[x] = "_"
    if Mode == "Latex":
        IlleagalMapDict["_"] = " "
        IlleagalMapDict["&"] = "\&"
        IlleagalMapDict["%"] = "\%"
        IlleagalMapDict["#"] = "＃"
    for x in IlleagalMapDict.keys():
        result = result.replace(x,IlleagalMapDict[x])
    return result

def RemoveIlleagalCharForFileNameForLatex(text):
    result = text
    IlleagalSet = ['/','\\',':','?','\"','<','>','|','\n','\xa0','\t','*']
    for x in IlleagalSet:
        result = result.replace(x,"_")
    return result

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

def atoi(text):
    return int(text) if text.isdigit() else text

def getLineOfMaxLen(strX):
    #NumberTypes = (types.IntType, types.LongType, types.FloatType, types.ComplexType)
    #if isinstance(strX, NumberTypes) == True:
    if isinstance(strX, (int, float, complex)) == True:
        #strX = str(strX)
        return [strX]
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

def ExtractZip(InputFN):
    files = zf.ZipFile(InputFN, 'r')
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
        '''
        MatchResult = re.findall('20\d{6}',InputStr)
        if len(MatchResult) > 0:
            return MatchResult[0]
        #else:
            #return False
        '''
        MatchResult = re.search('20\d{6}',InputStr)
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
                validtime = dte.datetime.strptime(Time, FMT)
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

def cosineSimilarity(A,B,mode = "1to1"):
    '''
    # define two lists or array
    "1to1":
    A = np.array([2,1,2,3,2,9])
    B = np.array([3,4,2,4,5,5])
    ------------------------------------------------
    "Nto1":
    A = np.array([[2,1,2],[3,2,9], [-1,2,-3]])
    B = np.array([3,4,2])
    ------------------------------------------------
    "NtoN":
    A = np.array([[1,2,2],
                   [3,2,2],
                   [-2,1,-3]])
    B = np.array([[4,2,4],
                   [2,-2,5],
                   [3,4,-4]])
    '''
    # compute cosine similarity
    if mode == "1to1":
        cosine = np.dot(A,B)/(norm(A)*norm(B))
    elif mode == "Nto1":
        cosine = np.dot(A,B)/(norm(A, axis=1)*norm(B))
    elif mode == "NtoN":
        cosine = np.sum(A*B, axis=1)/(norm(A, axis=1)*norm(B, axis=1))
    else:
        print("The mode {mode} is unknown mode for cosineSimilarity. Abort!")
    return cosine

def SequenceToCountVector(seq1,seq2,sortKey = None):
    '''
    print("-"*50)
    print("seq1 b4",seq1)
    print("type(seq1) b4)",type(seq1))
    for seq in [seq1,seq2]:
        try:
            seq = json.loads(seq)
            seq = ast.literal_eval(seq)
        except Exception as e:
            print(e)
            pass
    '''
    #print("-"*50)
    #print("seq1 af",seq1)
    #print("type(seq1) af",type(seq1))
    if isinstance(seq1,dict):
        #print("Input seq is a dict")
        c1 = seq1
        c2 = seq2
    else:
        #print("Start to counter seq")
        c1 = Counter(seq1)
        c2 = Counter(seq2)
    U = set(c1).union(set(c2))
    if sortKey == "increasing":
        U = sorted(U)
    elif sortKey == "decreasing":
        U = sorted(U,reverse=True)
    #print("c1,c2,U",c1,c2,U)
    v1 = []
    v2 = []
    for x in U:
        v1.append(c1.get(x,0))
        v2.append(c2.get(x,0))
    #print(U)
    #print(v1,v2)
    return v1,v2
    
    
    
def SequenceSimilarity(
        seq1,seq2,method="difflib",sort_first = False,
        autojunk=False,
        digits_assimilation = False):
    '''
    回傳一個介於0到1之間的數值，越相似的話，數值越高。
    '''
    '''
    if method == "FullCombination":
        return statistics.mean(
            [SequenceSimilarity(seq1,seq2,method=method,sort_first = False)
             for method in ["difflib","dmp","CountVectorCosine"]
            ])
    '''
    #if type(seq1) == type(seq2) == list and method != "difflib":
    if type(seq1) == type(seq2) == list and method == "dmp":
        #MES = "For lists similarity, now only difflib is available,"
        #MES += "thus the function will use method difflib."
        #MPlogger().logW(MES)
        method = "difflib"
    if sort_first == True:
        if type(seq1) == type(seq2) == list:
            seq1 = frequency_sort(seq1)
            seq2 = frequency_sort(seq2)
        elif type(seq1) == type(seq2) == str:
            seq1 = ''.join(frequency_sort(seq1))
            seq2 = ''.join(frequency_sort(seq2))
    if digits_assimilation == True:
        if type(seq1) == type(seq2) == list:
            seq1 = [re.sub("\d","Ｄ",x) for x in seq1]
            seq2 = [re.sub("\d","Ｄ",x) for x in seq2]
        elif type(seq1) == type(seq2) == str:
            seq1 = ''.join([re.sub("\d","Ｄ",x) for x in seq1])
            seq2 = ''.join([re.sub("\d","Ｄ",x) for x in seq2])
    #print("="*50)
    #print("seq1",seq1)
    #print("seq2",seq2)
    #MES = f"Using method {method} to compute SequenceSimilarity."
    #MPlogger().logW(MES, printOnScreen = False)
    if method == "difflib":
        #print(difflib.SequenceMatcher(None,seq1,seq2).ratio())
        #print(difflib.SequenceMatcher(None,seq2,seq1).ratio())
        #if "公 司" in seq1 or "公 司" in seq2:
        #print("seq1",seq1)
        #print("seq2",seq2)
        #print(difflib.SequenceMatcher(None,seq1,seq2,autojunk=autojunk).ratio())
        #print(difflib.SequenceMatcher(None,seq2,seq1,autojunk=autojunk).ratio())
        return difflib.SequenceMatcher(None,seq1,seq2,autojunk=autojunk).ratio()
    elif method == "jaro_similarity":
        import jellyfish
        return jellyfish.jaro_similarity(seq1,seq2)
    elif method == "theFuzz":
        from thefuzz import fuzz
        return fuzz.ratio(seq1,seq2)/100
        #return fuzz.token_sort_ratio(seq1,seq2)/100
        
    elif method == "dmp":
        sim, diff = dmp_compute_similarity_and_diff(seq1, seq2)
        return sim
    elif method == "CountVectorCosine":
        v1,v2 = SequenceToCountVector(seq1,seq2)
        sim = cosineSimilarity(v1,v2)
        return sim

def InnerCrossSimilarityForTextList(
        textList1,textList2,
        #method="difflib",
        method="theFuzz",
        #method="dmp",
        #method ='jaro_similarity',
        sort_first = False,
        saveFN = "InnerCrossSimilarityForTextList.xlsx"):
    SimilarityDict = dict()
    #print("textList1==textList2",textList1==textList2)
    for i,x in enumerate(textList1):
        #SimilarityDict[i] = dict()
        txtseg1 = textList1[i]
        #print("txtseg1",txtseg1)
        #txtseg1 = textList1[i][:30]
        txtseg1 = txtseg1.replace("\n"," ")#.replace(" ","")
        SimilarityDict[txtseg1] = dict()
        for j,y in enumerate(textList2):
            #SimilarityDict[i][j] = SequenceSimilarity(seq1=textList1[i],seq2=textList2[j])
            #print("-"*50)
            #print("i,j",i,j)
            #print("i,j,x,y",i,j,x,y)
            txtseg2 = textList2[j]
            #txtseg2 = textList2[j][:30]
            txtseg2 = txtseg2.replace("\n"," ")#.replace(" ","")
            SimilarityDict[txtseg1][txtseg2] = SequenceSimilarity(
                seq1=textList1[i],seq2=textList2[j],
                method=method,
                #digits_assimilation=False,
                )
            #print("SimilarityDict",SimilarityDict)
            #print(SimilarityDict[txtseg1][txtseg2])
    #df = pd.DataFrame.from_dict({(i,j): SimilarityDict[i][j] 
                       #for i in SimilarityDict.keys() 
                       #for j in SimilarityDict[i].keys()},
                   #orient='index')
    df = pd.DataFrame.from_dict(SimilarityDict,orient='index')
    #print("SimilarityDict",SimilarityDict)
    print("df.shape",df.shape)
    #print(saveFN)
    df.to_excel(saveFN)
    #print("="*50)
    #print("df==df.transpose()",df==df.transpose())
    #print("="*50)
    #print("df.all()",df.all())
    #print("df==df.transpose().type",(df==df.transpose()).dtypes)
    #print("df",df)
            
def InnerCrossSimilarityForTextListTest():
    testFNList = [
        "期末指数投资按公允价值占基金资产净值比例大小排序的所有权益投资.txt",
        "中国科学院科技战略咨询研究院（筹）与民进中央举行合作交流座谈会.txt",
        "冀航警43_24 航标动态.txt",
        "澜沧江—湄公河合作第三次领导人会议万象宣言.txt",
        #"InnerCrossSimilarityTest.txt",
        "Social-ecological drivers of metropolitan residents’ comfort living with wildlife_tika.txt",
        "肖锋：对中美航行自由之争的思考之附件：原文阅读.txt",
        "缅甸：300 万人急需救生援助和保护.txt",
        "Two Weeks of Chaos_ Inside Elon Musk’s Takeover of Twitter.txt",
        "Why is Elon Musk’s Twitter takeover increasing hate speech.txt",
        "Iran_Military_Power_LR.txt",
        "China's Tailored Coercion and Its Rivals' Actions and Responses_tika.txt",
        "Asad Under Fire_ Five Scenarios for the Future of Syria_tika.txt",
        "An Intensified Approach to Combatting the Islamic State_tika.txt",
        "China’s Blue Water Navy Strategy and its Implications_tika.txt",
        ]
    #testFN= "InnerCrossSimilarityForTextList.txt"
    for FN in testFNList:
        inputArt = open(FN,mode='rt',encoding='utf-8').read()
        textList1 = textList2 = wrap(inputArt, 768)
        #textList1 = textList2 = wrap(inputArt, 4)
        #print("")
        InnerCrossSimilarityForTextList(textList1,textList2,saveFN=FN.rpartition(".")[0]+".xlsx")
    
def dmp_compute_similarity_and_diff(text1, text2):
    dmp = diff_match_patch()
    dmp.Diff_Timeout = 0.0
    diff = dmp.diff_main(text1, text2, False)

    # similarity
    common_text = sum([len(txt) for op, txt in diff if op == 0])
    text_length = max(len(text1), len(text2))
    sim = common_text / text_length

    return sim, diff
    #return sim

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


def DirReplace(FilePath,SrcDir,DesDir):
    FilePath = fileNameNormalizer.proc(FilePath)
    SrcDir = fileNameNormalizer.proc(SrcDir)
    DesDir = fileNameNormalizer.proc(DesDir)
    return FilePath.replace(SrcDir,DesDir)
    
def BackupAndDelFile(
        SrcDir,DesDir,
        #BackFNrePat = ".*",
        BackFNrePatList = [".*"],
        delete=True):
    MKDIR(DesDir)
    #FNMatchList = list(map(getFNFromFullPath,OSWALK(SrcDir,
        #FNrePat=BackFNrePat)))
    #for file in FNMatchList:
        #src = os.path.join(SrcDir,file)
        #des = os.path.join(DesDir,file)
        #shutil.move(src, des)
    for BackFNrePat in BackFNrePatList:
        FNPathMatchList = OSWALK(SrcDir,FNrePat=BackFNrePat)
        for file in FNPathMatchList:
            #des = file.replace(SrcDir,DesDir)
            des = DirReplace(FilePath=file,SrcDir=SrcDir,DesDir=DesDir)
            MKDIR(getPathFromFN(des))
            shutil.move(file, des)
    shutil.rmtree(SrcDir)
        
def RenameDir(SrcDir,DesDir):
    #for i in range(3):
    try:
        os.rename(SrcDir,DesDir)
    except Exception as e:
        print(f"When try to apply RenameDir in utilities with os.rename, the following error occurs:\n{e}\n Try to use shutil.copytree and rmtree")
        try:
            shutil.copytree(SrcDir,DesDir)
            shutil.rmtree(SrcDir)
        except Exception as e:
            print(f"When try to apply RenameDir in utilities with shutil.copytree and rmtree, the following error occurs:\n{e}\n")    

def mem_report():
    memReport = psutil.virtual_memory()
    mem_report = {
        "total":memReport.total,
        "available":memReport.available,
        "used":memReport.used,
        }
    return mem_report

def GPU_mem_report():
    #print("CPU RAM Free: " + humanize.naturalsize( psutil.virtual_memory().available ))
    GPUs = GPUtil.getGPUs()
    GPU_mem_report = []
    for i, gpu in enumerate(GPUs):
        mem_Free,mem_Tot,mem_Util_pct = gpu.memoryFree, gpu.memoryTotal, gpu.memoryUtil*100
        GPU_mem_report.append((i,mem_Free,mem_Tot,mem_Util_pct))
        print('GPU {:d} ... Mem Free: {:.0f}MB / {:.0f}MB | Utilization {:3.0f}%'.format(
            i,mem_Free,mem_Tot,mem_Util_pct))
    return GPU_mem_report

class freeGPUConformer:
    def __init__(self, ObjectName = "",
                 freeGPUmemReq = 3000, #MB
                 EachWaitTime = 10, #second
                 RetryLimit = 360,
                 #達到嘗試次數限制後，是否繼續後續程式，如果不繼續，則直接Raise Exception
                 ReachLimitContinueMode = False,
                 logFile="Exception.log",logSubDir="../"):
        self.ObjectName = ObjectName
        self.freeGPUmemReq = freeGPUmemReq
        self.EachWaitTime = EachWaitTime
        self.RetryLimit = RetryLimit
        self.logFile = logFile
        self.logSubDir = logSubDir
        self.ReachLimitContinueMode = ReachLimitContinueMode
    def proc(self,):
        #檢查是否有GPU，有的話要求必需存在GPU具有3GB以上的未使用VRam，否則再等10秒鐘。
        #最多等10小時
        GPU_mem = GPU_mem_report()
        retry = 0
        while(len(GPU_mem)>0 and retry < self.RetryLimit):
            #GPU_mem: [(i,mem_Free,mem_Tot,mem_Util_pct)]
            if not all([gpu[1]<self.freeGPUmemReq for gpu in GPU_mem]):
                break
            else:
                retry += 1
                MES = f"Mem of All GPU are < {self.freeGPUmemReq}MB! It has been waiting for {retry*self.EachWaitTime/60:.2f} mins. Wait more {self.EachWaitTime} secs."
                MPlogger().logW(MES,logFile="freeGPUConformer.log",logSubDir="logs")
                time.sleep(self.EachWaitTime)
                GPU_mem = GPU_mem_report()
        if retry >= self.RetryLimit:
            if self.ReachLimitContinueMode == False:
                MES = f"For {self.ObjectName}, It has been waiting for {self.EachWaitTime*self.RetryLimit/3600:.2f} hour ({self.RetryLimit} times) and there is no enough Mem of GPU to run. Abort!"
                MPlogger().logW(MES,logFile="Exception.log",logSubDir="logs")
                raise Exception
            elif self.ReachLimitContinueMode == True:
                MES = f"For {self.ObjectName}, It has been waiting for {self.EachWaitTime*self.RetryLimit/3600:.2f} hour ({self.RetryLimit} times) and there is no enough Mem of GPU. Continue with CPU!"
                MPlogger().logW(MES,logFile="Exception.log",logSubDir="logs")

def IsProcessRunning(procName):
    #print("psutil.process_iter()",[p.name() for p in psutil.process_iter()])
    return procName in (p.name() for p in psutil.process_iter())
def nProcessRunningWithName(procName):
    #print("psutil.process_iter()",[p.name() for p in psutil.process_iter()])
    return [p.name() for p in psutil.process_iter()].count(procName)


def str2bool(v):
    if isinstance(v, bool):
        return v
    if v.lower() in ('yes', 'True','true', 't', 'y', '1'):
        return True
    elif v.lower() in ('no', 'False','false', 'f', 'n', '0'):
        return False
    else:
        raise argparse.ArgumentTypeError('Boolean value expected.')

def strip_end(text, suffix):
    if suffix and text.endswith(suffix):
        return text[:-len(suffix)]
    return text


def clearPort(process):
    if "windows" not in platform.system().lower():
        pkillsh = "/mntCZJ/dockerpkill.sh"
        with open(pkillsh,'wt') as f:
            f.write(f"pkill {process}\n")
        os.system(f"chmod 700 {pkillsh};{pkillsh}")


class PickleHandler:
    def __init__(self, file = "",obj = None, BaseFileName="",indent=None,variableName=""):
        self.file = file
        self.obj = obj
        self.BaseFileName = BaseFileName
        if self.file == "" and self.BaseFileName != "":
            self.file = self.BaseFileName+".pickle"
        self.variableName = variableName
    def save(self,):
        print("*"*50)
        print(f"Saving {self.variableName} to {self.file} with PickleHandler.")
        print("*"*50)
        with open(self.file, 'wb') as f: # pickle 是二進位格式
            pickle.dump(self.obj, f)
    def load(self,):
        print("*"*50)
        print(f"Loading {self.variableName} from {self.file} with PickleHandler.")
        print("*"*50)
        with open(self.file, 'rb') as f: # pickle 是二進位格式
            obj = pickle.load(f)
        print("first 200 chars of loaded obj:", str(obj)[:200])
        return obj

class JsonHandler:
    def __init__(self,file="",obj=None,BaseFileName="",indent=None,variableName=""):
        self.file = file
        self.obj = obj
        self.BaseFileName = BaseFileName
        if self.file == "" and self.BaseFileName != "":
            self.file = self.BaseFileName+".json"
        self.indent  = indent 
        self.variableName = variableName
    def save(self,):
        print("*"*50)
        print(f"Saving {self.variableName} to {self.file} with JsonHandler.")
        print("*"*50)
        with open(self.file,'wt',encoding='utf-8') as f:
            json.dump(self.obj, f, indent=self.indent)
    def load(self,):
        print("*"*50)
        print(f"Loading {self.variableName} from {self.file} with JsonHandler.")
        print("*"*50)
        with open(self.file,'rt',encoding='utf-8') as f:
            obj = json.load(f)
        print("first 200 chars of loaded obj:", str(obj)[:200])
        return obj
    
class Serializer:
    def __init__(self,file="",obj=None,BaseFileName="",indent = None,
                 serializerList = ["pickle","json"],
                 variableName = ""):
        self.file = file
        self.obj = obj
        self.BaseFileName = BaseFileName
        self.indent = indent
        self.serializerList = serializerList
        self.NameMapping = {
            "pickle":PickleHandler,
            "json":JsonHandler
            }
        self.variableName = variableName
    def save(self,):
        #print("self.file",self.file)
        #print("self.BaseFileName",self.BaseFileName)
        for ser in self.serializerList:
            self.NameMapping[ser](
                file=self.file,obj=self.obj,
                BaseFileName=self.BaseFileName,indent=self.indent,
                variableName=self.variableName,
                ).save()
    def load(self,):
        #如果"PickleHandler"有在選項內，優先嘗試使用PickleHandler載入。
        self.serializerList = sorted(
            self.serializerList,key=lambda x:x=="PickleHandler",reverse=True)
        for ser in self.serializerList:
            try:
                obj = self.NameMapping[ser](
                    file=self.file,
                    obj=self.obj,
                    BaseFileName=self.BaseFileName,
                    indent=self.indent,
                    variableName=self.variableName,
                    ).load()
                #print(f"Obj in Serializer.load, {obj}")
                if obj is not None:
                    return obj
            except Exception as e:
                print(f"When use Serializer with serializer {ser} to load obj, the following error occurs:\n{e}\n")
                

def getFastAPIStaticDir():
    return "fastAPI/static"

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

if __name__ == '__main__':
    '''
    A = {"Suan Ming-TW Affairs": 1}
    B = {"Showbiz": 2, "Constellation": 1, "Exempt-Showbiz": 1}
    A = {'TW Showbiz': 2, 'Exempt-Showbiz': 2, 'Suan Ming-TW Affairs': 2, 'Showbiz': 1, 'Scrap': 2, 'Suan Ming': 1}
    B = {'Showbiz': 3, 'Constellation': 2, 'Exempt-Showbiz': 2, 'Scrap': 2}
    Sim = SequenceSimilarity(A,B,method="CountVectorCosine")
    print(Sim)
    '''
    
    #print(DateList(freq='SM',FMT = "%Y-%m%d %H:%M:%S"))
    #print(DateList(freq='D'))
    #print(timeRelative(args={"months":-6},outputFMT = "%Y%m%d"))
    varRepeat = 1
    #MemDictTest(varPre = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"*varRepeat)
    InnerCrossSimilarityForTextListTest()