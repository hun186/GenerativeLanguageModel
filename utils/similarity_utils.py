from PackageImport import PackageImporter
PackageImporter.proc()
import os
parentSubDir = os.getcwd().split(os.path.sep)[-1]
if parentSubDir in [
    "DatasetConverter","BertScript","GenerativeLanguageModel","ArticleClustering"
    ]:
    os.chdir("../")
    print(f"Change working directory to {os.getcwd()}")
elif parentSubDir in [
    "utils",
    ]:
    os.chdir("../../../")
    print(f"Change working directory to {os.getcwd()}")

import re
import numpy as np
from numpy.linalg import norm
from collections import Counter
import pandas as pd

from utils.utilities import frequency_sort
from utils.utilities import wrap
from utils.MP_utils import MPlogger
from utils.utilities import SortedDictWithValue

try:
    import diff_match_patch
except Exception as e:
    MES = f"When loading the module diff_match_patch, the following error occurs:\n{e}"
    MPlogger().logW(MES, logFile="ModuleNotFoundError.log")

import difflib

try:
    from cdifflib import CSequenceMatcher
    difflib.SequenceMatcher = CSequenceMatcher
except:
    pass



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
    if isinstance(seq1,dict):
        c1 = seq1
        c2 = seq2
    else:
        c1 = Counter(seq1)
        c2 = Counter(seq2)
    U = set(c1).union(set(c2))
    if sortKey == "increasing":
        U = sorted(U)
    elif sortKey == "decreasing":
        U = sorted(U,reverse=True)

    v1 = []
    v2 = []
    for x in U:
        v1.append(c1.get(x,0))
        v2.append(c2.get(x,0))

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
    if type(seq1) == type(seq2) == list and method == "dmp":
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

    if method == "difflib":
        return difflib.SequenceMatcher(None,seq1,seq2,autojunk=autojunk).ratio()
    elif method == "jaro_similarity":
        import jellyfish
        return jellyfish.jaro_similarity(seq1,seq2)
    elif method == "theFuzz":
        from thefuzz import fuzz
        return fuzz.ratio(seq1,seq2)/100
        
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
        saveFN = "InnerCrossSimilarityForTextList.xlsx",
        saveResult = True,
        sortSimDictMethod = None):
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
            txtseg2 = textList2[j]
            txtseg2 = txtseg2.replace("\n"," ")#.replace(" ","")
            SimilarityDict[txtseg1][txtseg2] = SequenceSimilarity(
                seq1=textList1[i],seq2=textList2[j],
                method=method,
                )
    if saveResult == True:
        df = pd.DataFrame.from_dict(SimilarityDict,orient='index')
        #print("SimilarityDict",SimilarityDict)
        print("In InnerCrossSimilarityForTextList, df.shape",df.shape)
        print(f"save the result of InnerCrossSimilarityForTextList to {saveFN}")
        df.to_excel(saveFN)
    if sortSimDictMethod in ["dsc"]:
        for key in SimilarityDict:
            SimilarityDict[key] = SortedDictWithValue(SimilarityDict[key],dsc=True)
    elif sortSimDictMethod in ["asc"]:
        for key in SimilarityDict:
            SimilarityDict[key] = SortedDictWithValue(SimilarityDict[key],dsc=False)
            
    return SimilarityDict
            
def InnerCrossSimilarityForTextListTest():
    testFNList = [
        #"期末指数投资按公允价值占基金资产净值比例大小排序的所有权益投资.txt",
        #"中国科学院科技战略咨询研究院（筹）与民进中央举行合作交流座谈会.txt",
        #"冀航警43_24 航标动态.txt",
        #"澜沧江—湄公河合作第三次领导人会议万象宣言.txt",
        #"InnerCrossSimilarityTest.txt",
        #"Social-ecological drivers of metropolitan residents’ comfort living with wildlife_tika.txt",
        #"肖锋：对中美航行自由之争的思考之附件：原文阅读.txt",
        #"缅甸：300 万人急需救生援助和保护.txt",
        #"Two Weeks of Chaos_ Inside Elon Musk’s Takeover of Twitter.txt",
        #"Why is Elon Musk’s Twitter takeover increasing hate speech.txt",
        #"Iran_Military_Power_LR.txt",
        #"China's Tailored Coercion and Its Rivals' Actions and Responses_tika.txt",
        #"Asad Under Fire_ Five Scenarios for the Future of Syria_tika.txt",
        #"An Intensified Approach to Combatting the Islamic State_tika.txt",
        #"China’s Blue Water Navy Strategy and its Implications_tika.txt",
        "陈德铭呼吁美方为中国赴美企业提供公平公正商业环境.txt",
        "陈德铭呼吁美方为中国赴美企业提供公平公正商业环境_space.txt",
        ]
    #testFN= "InnerCrossSimilarityForTextList.txt"
    for FN in testFNList:
        inputArt = open(FN,mode='rt',encoding='utf-8').read()
        textList1 = textList2 = wrap(inputArt, 256)
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

'''
def findMostSimilarityStr(source="",targetPool = [],method="theFuzz"):
    similarityDict = {}
    for target in targetPool:
        similarityDict[target] = 
'''
  
if __name__ == '__main__':
    #Sim = SequenceSimilarity(A,B,method="CountVectorCosine")
    #print(Sim)
    #InnerCrossSimilarityForTextListTest()
    #print(InnerCrossSimilarityForTextList(textList1=["CN Military"],textList2 = ["CC","CN Military Power","CN Military Diplomacy"],saveResult=False,sortSimDict=True))
    
    seq1 = "美國在巴黎的大使館"
    seq2 = "美國駐英國大使館"
    #seq1 = str(["外交聯絡", "領事服務", "文化交流", "國家安全"])
    #seq2 = str(["人道主義援助", "經濟發展支援", "國際合作"])
    method = "theFuzz"
    print(SequenceSimilarity(seq1=seq1,seq2=seq2,method=method))