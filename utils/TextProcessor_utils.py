from PackageImport import PackageImporter
PackageImporter.proc()

import re
import os
import json




try:
    import utils
    #import utilities
    #import MP_utils
    #import df_utils
except:
    utils.utilities = utilities
    utils.MP_utils = MP_utils
    utils.df_utils= df_utils
    
#utilities = utils.utilities
#from utils import utilities
from utils.utilities import OSWALK
from utils.utilities import AppendedMFN
from utils.utilities import hasher
from utils.utilities import RENormalizer
from utils.utilities import getFNExtFromFullPath
from utils.MP_utils import MPlogger
from utils.df_utils import dfOutputer
    
class textReader:
    def __init__(self, file, 
                 encoding = "utf-8",
                 nBytes=None,
                 MPLOGGER = None
                 ):
        self.file = file
        self.encoding = encoding
        self.nBytes = nBytes
        if MPLOGGER is not None:
            self.MPLOGGER = MPLOGGER
        else:
            self.MPLOGGER = MPlogger()
    def run(self,):
        #讀取文本。
        nullReturn = ""
        if getFNExtFromFullPath(self.file).lower() == "AI2".lower():
            with open(self.file) as jsonfile:
                data = json.load(jsonfile)
                rawInfo = data.get("rawInfo",dict())
                if rawInfo != dict():
                    subject = rawInfo.get("subject","")
                    content = rawInfo.get("content","")
                else:
                    subject = data.get("subject","")
                    content = data.get("content","")
                text = f"{subject} {content}"
                #text = data["rawInfo"]["content"] 
        else:
            try:
                text = open(
                    self.file, mode="rt", encoding=self.encoding).read(self.nBytes).replace("\0","")
            except UnicodeDecodeError:
                try:
                    MES = "Fail to use utf-8 to read file {}.\n".format(
                        self.file)
                    self.MPLOGGER.logW(MES)
                    text = open(
                        self.file, mode="rt").read(self.nBytes).replace("\0","")
                except:
                    MES = "Fail to use cp950 to read file {}.\n".format(
                        self.file)
                    self.MPLOGGER.logW(MES)
                    return nullReturn
        return text

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

class BasicDataCleaner:
    def __init__(
            self,strQ2B = True,DummySpace = True,
                 ):
        #self.text = text
        self.strQ2B = strQ2B
        self.DummySpace = DummySpace
        '''
        self.printOnScreen = printOnScreen
        if MPLOGGER is not None:
            self.MPLOGGER = MPLOGGER
        else:
            self.MPLOGGER = MPlogger()
        '''
    def proc(self,text):
        #去除斷行。
        #text = text.replace("\n", " ")
        #將全形字母、數字換成半型，以利tokenize。
        if self.strQ2B == True:
            text = strQ2BConverter().proc(text)
        #若遇連續空白，只留下一個空白。
        if self.DummySpace == True:
            text = re.sub(" \n", "\n", text)
            for x in ["\n"," ","\n "," \n"]:
                #pass
                text = re.sub(f"({x})+", x, text)
            text = re.sub(" \n", "\n", text)
        return text

class DataCleanerWithPattern:
    def __init__(self, text, 
                 RePatternDict = None,
                 MPLOGGER = None,
                 printOnScreen = False
                 ):
        self.text = text
        self.RePatternDict = RePatternDict
        self.printOnScreen = printOnScreen
        if MPLOGGER is not None:
            self.MPLOGGER = MPLOGGER
        else:
            self.MPLOGGER = MPlogger()
    def proc(self,):
        if self.RePatternDict == None:
            print("WARNING! There is NO Pattern Input! Abort!")
            return
        for key in self.RePatternDict:
            RePattern = RENormalizer.proc(
                self.RePatternDict[key]["SrcPat"])
            ReplacedResult = self.RePatternDict[key]["ReplacedResult"]
            
            Matches = re.findall(RePattern,self.text)
            #print("Matches",Matches)

            if len(Matches) == 0:
                MES = f"There is nothing matched for {self.text[:100]}... with pattern {self.RePatternDict}\n"
                self.MPLOGGER.logW(MES, logFile=f"DataCleaner_{key}.txt",
                              printOnScreen=self.printOnScreen)
            #如果有符合字串，則存至log檔備查。
            if len(Matches) > 0:
                #多條件的情況：
                #match sample:('', '', '', '', '', '', 'From:  Subjcet: eg3fd3m3k3lsag;')
                #Mathces sample:[match1,match2,match3,...]
                if isinstance(Matches[0],tuple):
                    Matches = [list(filter(('').__ne__, match)) for match in Matches]
            
                MES = f"Matching {RePattern}:\n"
                for match in Matches:
                    MES += str(match)+"\n"
                self.MPLOGGER.logW(MES, logFile=f"DataCleaner_{key}.txt",
                              printOnScreen=self.printOnScreen)
            
            self.text = re.sub(RePattern,ReplacedResult,self.text)
        return self.text

class TxtFileHashDictBuilder:
    def __init__(self, fileList, hashalg = "md5", nBytes = None):
        self.fileList = fileList
        self.nBytes = nBytes
        self.hashalg = hashalg
    def show(self,):
        print("="*50)
        print("fileList[0:3]:", self.fileList[0:3])
    def run(self):
        hashDict = {}
        ndup = 0
        for file in self.fileList:
            ctx = textReader(file).run()
            #ctx = open(file,'rt',encoding='utf-8').read(1000000)
            #print(ctx)
            hashval = hasher(ctx, self.hashalg)
            if hashval in hashDict.keys():
                ndup += 1
            #hashDict[hashval] = file
            hashDict[file] = hashval
        return hashDict
    
def CheckStringWithPatterns(string, PatternList):
    for pat in PatternList:
        if pat in string:
            return True, pat
    return False, None

def CheckStringWithRePatterns(string, RePatternDict):
    '''
    RePatternDict = {
        "setn.com":["^((?!News.aspx).)*$"],
        "mirrormedia.mg":[".*/category/.*",
                         ".*/section/.*"],
                    ]
    '''
    for key in RePatternDict.keys():
        if key in string:
            for regex in RePatternDict[key]:                
                if re.match(regex,string) != None:
                    return True, regex
    return False, None

def removeLinesWithPattern(inputFileName, outputFileName=None,RePatternDict = None):
    if RePatternDict == None:
        print("WARNING! There is NO Pattern Input! Abort!")
        return
    
    if outputFileName == None:
        
        outputFileName = AppendedMFN(inputFileName,appendStr="_removeLine")
    print("outputFileName is",outputFileName)
    input = open(inputFileName, "rt",encoding='utf-8')
    output = open(outputFileName, "wt",encoding='utf-8')

    #output.write(input.readline())

    for line in input:
        if CheckStringWithRePatterns(line,RePatternDict)[0] == False:
            output.write(line)

    input.close()
    output.close()

#TODO    
def substituteLinesWithPattern(inputFileName, outputFileName=None,InpPatternDict = None):
    if RePatternDict == None:
        print("WARNING! There is NO Pattern Input! Abort!")
        return
    
    if outputFileName == None:
        
        outputFileName = AppendedMFN(inputFileName,appendStr="_removeLine")
    print("outputFileName is",outputFileName)
    input = open(inputFileName, "rt",encoding='utf-8')
    output = open(outputFileName, "wt",encoding='utf-8')

    #output.write(input.readline())

    for line in input:
        if CheckStringWithRePatterns(line,RePatternDict)[0] == False:
            output.write(line)

    input.close()
    output.close()

#0-index
def fixCsvSepProblem(inputFileName, Sep = ',', FixReplacer = '，',
                     fixPos = None, totalLen = None):
    assert fixPos is not None, "fixPos is NOT specified! ABORT!"
    assert totalLen is not None, "totalLen is NOT specified! ABORT!"
    #outFN = inputFileName.replace
    res = []
    with open(inputFileName,"rt",encoding='utf-8') as f:
        for line in f:
            line = line.split(Sep)
            exendpos = -(totalLen-fixPos)+1
            line = line[:fixPos]+[FixReplacer.join(
                line[fixPos:exendpos])]+line[exendpos:]
            line = Sep.join(line)
            res.append(line)
    #print("res",res)
    with open(inputFileName,"wt",encoding='utf-8') as f:
        for line in res:
            f.write(line)
            
            
if __name__=='__main__':
    ROOTPATH = "./"
    ROOTPATH = r"D:\shared\TopicClassification\TopicTextCrawler\Books\聯合國糧農組織\#T#[Food Security]\作物前景與糧食形勢\test\中文版"
    RePatternDict = {
            "作物前景與糧食形勢中文版":{
                "SrcPat":[
"""
第\d{1,2}期 n 20\d{2}年\d{1,2}月
""",
#"""好棒好棒好棒好棒好棒"""
],
                "ReplacedResult":""
                }
        }
    for file in OSWALK(ROOTPATH,Extension = ["txt"]):
        text = textReader(file).run()
        #fixCsvSepProblem(
            #inputFileName =file,fixPos=4,totalLen=6)
        subedText = DataCleanerWithPattern(
                text=text,RePatternDict=RePatternDict,
                printOnScreen=True).proc()
        if text != subedText:
            open(file,'wt',encoding="utf-8").write(subedText)
        #break