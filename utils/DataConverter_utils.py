try:
    import utils
except:
    from PackageImport import PackageImporter
    PackageImporter.proc()

import os
import re
import pandas as pd
import slugify

from utils.utilities import CapWords
from utils.utilities import OSWALK
from utils.utilities import MKDIR
#from utils.utilities import pathSeqFromFN
from utils.utilities import pathSpliter
from utils.utilities import removeStrPrefix
from utils.utilities import ConvertTimeStrFMT
from utils.utilities import getMFNFromFN
from utils.utilities import getFNExtFromFullPath
from utils.utilities import FileNamePicker

from utils.utilities import RemoveIlleagalCharForFileName
#from utils.utilities import DictSaver
from utils.MP_utils import MPlogger
from utils.df_utils import XLSTodf
from utils.df_utils import CSVtodf
from utils.df_utils import dfFromSQLite3
from utils.df_utils import dfOutputer
from utils.df_utils import dfAppendToXLS
from utils.df_utils import dfListToXLS
from utils.TCF_utils import datasetDirOutputDirPickers

from DatasetConverter.EXTConverter.ExtractionRule import ExtractionRuleDict
from BertScript.ClassTable import ClassTable

from ClassesTree.ClassesTree_utils import GetSubNodes
from ClassesTree.ClassesTree_utils import LoadTree
from ClassesTree.ClassesTree_utils import BuildInfoScoreTable
from ClassesTree.Label_utils import getLabelsFromFileName
from ClassesTree.Label_utils import GetCTOfLabel

def GetFixedTestPATH(args):
    #FixedTestPATHList = [
                        #"Using",
                         #]
    FixedTestPATHList = []
    for FTPathCand in ["../FixedTest","FixedTest"]:
        FixedTestSubDir = os.path.join(
           FTPathCand,"FixedTest_"+str(args.TRVPort),"Using")
        if os.path.isdir(FixedTestSubDir):
            FixedTestPATHList.append(FixedTestSubDir)
            
    #FTSCand = os.path.join(TopicTextCrawlerROOT,FixedTestSubDir)
    #if os.path.isdir(FTSCand) != True:
        #FixedTestSubDir = "../FixedTest"
        #FTSCand = os.path.join(TopicTextCrawlerROOT,FixedTestSubDir)
            #FixedTestPATHList = [os.path.join(FixedTestSubDir,x)
                                 #for x in FixedTestPATHList]
    #FixedTestPATHList = [os.path.join(TopicTextCrawlerROOT,"FixedTest",x)
                         #for x in FixedTestPATHList]
    return FixedTestPATHList





      
def getSrcFromFileName(FileName, LabelList):
    #x = ../Books/中文文章/scrap/中文古文
    #print("path is ", x)
    FolderList = [CapWords(fold) for fold in pathSpliter.proc(FileName)]
    #print("FolderList",FolderList)
    #raise Exception
    SrcType, Src = None, None
    #print("="*50)
    #print("FileName", FileName)
    #print("getLabelsFromFileName(FileName)", getLabelsFromFileName(FileName))
    for label in LabelList:
        #print("label", label)
        if label in getLabelsFromFileName(FileName):
            #Ind = FolderList.index(label)
            for i,fold in enumerate(FolderList):
                if fold.startswith("#T#") and label in getLabelsFromFileName(fold):
                    Ind = i
                    break
            #if "Books" in pathSeqFromFN(FileName):
            if "Books" in pathSpliter.proc(FileName):
                 SrcType = FolderList[Ind-1]
                 Src = FolderList[Ind+1]
            else:
                #print("FolderList",FolderList)
                SrcType = FolderList[Ind-2]
                Src = FolderList[Ind-1]
            break
    #print("SrcType, Src",SrcType, Src)
    return SrcType, Src

'''
class NewestModelMainFileNamePickers:
    def proc(OldOutputDir=None):
        r = re.compile("^model\.ckpt-\d+.*$")
        ModelMFN = sorted(set([
            ".".join(x.split(".")[0:2]) for x in list(filter(r.match, A))]))[-1]
        MES = f"Using the model {ModelMFN} in {OldOutputDir} to transferring training."
        MPlogger.logW(MES)
        return ModelMFN
'''

class KaggleDatasetExtractor:
    def __init__(self, filename, FileType=None, 
                 Columns=[],ctxCols =[],SaveFNCols=[],
                 sep = ',', header = 'infer', nrows = None):
        self.filename = filename
        #self.OMFN = OMFN
        self.FileType = FileType if FileType is not None else self.DetectFileType()
        self.Columns = Columns
        self.ctxCols = ctxCols
        self.SaveFNCols = SaveFNCols if SaveFNCols != [] else ctxCols[0]
        self.sep = sep
        self.header = header
        self.nrows = nrows
    def show(self):
        print("OMFN is {}".format(self.OMFN))
    def DetectFileType(self):
        Ext = getFNExtFromFullPath(self.filename).lower()
        if Ext in ["csv","tsv"]:
            return "csv"
        elif Ext in ["json"]:
            return "json"
        elif Ext in ["xls","xlsx"]:
            return "xls"
    def SaveText(self,SavePath,row,slugifyFN = False):
        text = '\n'.join([str(row[col]) for col in self.ctxCols])
        if slugifyFN == False:
            SaveFN = '_'.join([str(row[col])[:20] for col in self.SaveFNCols])+".txt"
        else:
            SaveFN = '_'.join([slugify(str(row[col]))[:20] for col in self.SaveFNCols])+".txt"
        #f"{str(row['_id'])[:20]}_{row['bylines'][:20]}_{text[:20]}.txt"
        SaveFN = RemoveIlleagalCharForFileName(SaveFN)
        #print("SavePath",SavePath)
        #print("SaveFN",SaveFN)
        #避免因檔名相同覆蓋，如果檔案已存在，在主檔名加計數器
        FullSaveFN = os.path.join(SavePath,SaveFN)
        if(os.path.isfile(FullSaveFN)):
            count = 1
            tempFullSaveFN = FullSaveFN.rpartition(".")[0]+f"_{count}.txt"
            while(os.path.isfile(tempFullSaveFN)):
                tempFullSaveFN = FullSaveFN.rpartition(".")[0]+f"_{count}.txt"
                count += 1
            FullSaveFN = tempFullSaveFN
                
        f = open(FullSaveFN, 'wt', encoding='utf-8')
        f.write(text)
        f.close()
        
    def proc(self):
        print(f"Start to load the file: {self.filename}")
        print(f"FileType is {self.FileType}")
        if self.Columns == []:
            print("The param Columns to load is Empty! Abort.")
        if self.ctxCols == []:
            print("The param ctxCols (columns for text) to load is Empty! Abort.")
        if self.SaveFNCols == []:
            print("The param SaveFNCols (columns for output filename) is Empty! Abort.")
            
        if self.FileType == "csv":
            df = CSVtodf(InputCSV = self.filename,
                         sep = self.sep, names = Columns,
                         #header = self.header,
                         error_bad_lines = True)
                         #nrows = self.nrows)
        elif self.FileType == "json":
            if self.nrows is not None:
                df = pd.read_json(self.filename,nrows=self.nrows, lines=True)
            else:
                df = pd.read_json(self.filename)#,orient="records", lines=True, chunksize=5)
        elif self.FileType == "xls":
            df = XLSTodf(self.filename,index_col=None,header=self.header,skiprows=None)
        print(f"Finished loading, the Columns are {df.columns.tolist()}")
        #if self.Columns != []:
            #df = df[self.Columns]
        #print("df",df)
        nSaveRows = len(df)
        #nSaveRows = 100
        i=0
        #SavePath = os.path.join(
            #getPathFromFN(self.filename),getMFNFromFN(self.filename))
        SavePath = getMFNFromFN(self.filename)
        MKDIR(SavePath)
        for index, row in df.iterrows():
            #print("row",row)
            #if i > len(df):
            if i % 10000 == 1:
                print(f"{i} rows have been processed.")
            if i > nSaveRows:
                break
            else:
                #print(row["ad_creative_bodies"])
                #print(type(row["ad_creative_bodies"]))
                #text = row["ad_creative_bodies"]
                for col in self.ctxCols:
                    if type(row[col]) == list:
                        row[col] = ''.join(row[col])
                try:
                    self.SaveText(SavePath,row,slugifyFN = False)
                except:
                    self.SaveText(SavePath,row,slugifyFN = True)
                i+=1

        return
 
class RANDLoader:
    def __init__(
        self,
        RAND_Dir = r'H:\bought pdf\=DeepLearningText=\外國智庫\C_RAND_DUMP'
        ):
        self.RAND_Dir = RAND_Dir
        self.RANDtpcTreeFile = os.path.join(
            self.RAND_Dir, "TopicTree.txt")
        self.RANDMetadataFile = os.path.join(
            self.RAND_Dir, "RAND_Metadata.sql3")        
    def show(self):
        print("RAND Dir is {}".format(self.RAND_Dir))
    def GetTopicTree(self,):
        return LoadTree(self.RANDtpcTreeFile)
        #傳回所有下級主題，包含出發主題。
    def GetSubtopics(self, sourceList):
        tpcTree = self.GetTopicTree()
        #print(tpcTree)
        print("="*50)
        #sourceList = ["Oceania"]
        #sourceList = ["East Asia"]
        #sourceList = ["Law and Business"]
        FullSubTree = sourceList.copy()
        StrictSubNodes = GetSubNodes(tpcTree, sourceList)
        while (StrictSubNodes!=[]):
            FullSubTree += StrictSubNodes
            StrictSubNodes = GetSubNodes(tpcTree, StrictSubNodes)
            print(GetSubNodes(tpcTree, FullSubTree))
            #FullSubTree += GetSubNodes(tpcTree, FullSubTree)
            

        print("{}\nFor topics {}, there are {} subtopics found"
              " for FullSubTree, precisely, {}".format(
            "="*50, sourceList, len(FullSubTree),FullSubTree
            ))
        return FullSubTree
    
    def GetMetadata(self,):
        #return dfFromSQLite3(self.RANDMetadataFile, tableList = "press")
        columnList = ["title", "topics", "FilePath"]
        return dfFromSQLite3(self.RANDMetadataFile, columnList = columnList)
    def run(self):

        df = self.GetMetadata()
        print(df.columns)
        print(df.shape)
        print(df.head())
        return df

def CheckDatasetFiles(BertDatasetSubDir="./"):
    res = {}
    for setType in ["train","test","dev"]:
        FullPath = os.path.join(BertDatasetSubDir,f"{setType}.tsv")
        res[FullPath] = os.path.isfile(FullPath)
    return res
    
class RawAndPredictionMerger:
    def __init__(
        self,
        AnnotRawDir = "./",
        AnnotRawFNrePatList = [],
        args = None,
        ):
        
        if args.task in ["SDSMS","SDSMS_Prediction"]:
            #AnnotRawDir = args.BertDatasetSubDir
            BertDatasetSubDir,outputDir = datasetDirOutputDirPickers(
                args=args,rdy_for_stage="Spike").proc()
            AnnotRawDir = BertDatasetSubDir
            #AnnotRawDir = os.path.join(args.WeiTechWorkPoolPATH,args.WeiTechworkID)
            AnnotRawFNrePatList = ExtractionRuleDict[args.ExtractionConverterTask]["fileNames"]
            assert AnnotRawFNrePatList != [], "For SDSMS or SDSMS_Prediction mission, AnnotRawFNrePatList is [] while we need nonempyt AnnotRawFNrePatList for RawAndPredictionMerger, Abort!"
        self.AnnotRawDir = AnnotRawDir
        self.AnnotRawFNrePatList = AnnotRawFNrePatList
        #self.OUTPUTMAIN = getMFNFromFN(self.AnnotRawFN)+"_Combined"
        self.args = args
        self.testResSQL = os.path.join(self.AnnotRawDir,"test_results_verification.sql3")
        self.DFPSQL = os.path.join(self.AnnotRawDir,"DFPreambleCols_df_ALL.sql3")
        self.CZJCorpusSQL = os.path.join(self.AnnotRawDir,f"CZJ_CorpusFile_{args.task}_FixedTest.sql3")
        self.InfoScoreTable = self.GetInfoScoreTable()
    def show(self):
        print("self.AnnotRawDir is {}".format(self.AnnotRawDir))
        print("self.AnnotRawFNrePatList is {}".format(self.AnnotRawFNrePatList))
        print("self.args is {}".format(self.args))
        
    def GetInfoScoreTable(self,):
        TreeBaseFNList = ["TopicTree.csv","TopicTree_AK4.csv"]
        tpcTree = LoadTree(TreeBaseFNList)
        InfoScoreTable = BuildInfoScoreTable(tpcTree = tpcTree)
        return InfoScoreTable
    '''
    def AppendAIResultWithTestRes(self,df,testResDict):
        InputFMT = "%Y-%m-%d %H:%M:%S"
        OutputFMT = "%Y-%m-%d"
        if "Type" not in df.columns:
            df["Type"] = ""
        #依testResDict字典獲得文本片段推論類別。
        df["pred_Type"] = df.apply(lambda x:testResDict.get(x.SmsContent,""),axis=1)
        df["date"] = df.apply(lambda x:ConvertTimeStrFMT(
            x.ItcDate,srcFMTCands=[InputFMT],desFMT=OutputFMT,debug = True,
            ),axis=1)
        df["correct_pred"] = df["pred_Type"] == df["Type"]
        #依InfoScoreTable字典獲得文本片段分數。
        df["InfoScore"] = df.apply(lambda x:self.InfoScoreTable.get(x.pred_Type,0),axis=1)
        #for col in ["SmsContentNo","Type"]:
        for col in ["Type"]:
            df[col] = df[col].fillna(value="")
        for col in ["Type","pred_Type"]:
            df[col+"_CT"] = df.apply(lambda x:GetCTOfLabel(
                ClassTable=ClassTable,Label=x[col]),axis=1)
        return df
    '''
    def AppendAIResultWithDFP(self,df,DFPDict,textTitleDict):
        InputFMT = "%Y-%m-%d %H:%M:%S"
        OutputFMT = "%Y-%m-%d"
        if "Type" not in df.columns:
            df["Type"] = ""
        #依testResDict字典獲得文本片段推論類別。
        df["pred_Type"] = df.apply(lambda x:DFPDict.get(
            textTitleDict.get(x.SmsContent,""),dict()).get("Class Of Most Pieces",None),axis=1)
        df["date"] = df.apply(lambda x:ConvertTimeStrFMT(
            x.ItcDate,srcFMTCands=[InputFMT],desFMT=OutputFMT,debug = True,
            ),axis=1)
        df["correct_pred"] = df["pred_Type"] == df["Type"]
        #依InfoScoreTable字典獲得文本片段分數。
        df["InfoScore"] = df.apply(lambda x:DFPDict.get(
            textTitleDict.get(x.SmsContent,""),dict()).get("InfoScoreSum",None),axis=1)
        for col in ["Type","pred_Type"]:
            df[col] = df[col].fillna(value="")
            df[col] = df[col].apply(lambda x:re.sub("#T#","",x))
        for col in ["Type","pred_Type"]:
            df[col+"_CT"] = df.apply(lambda x:GetCTOfLabel(
                ClassTable=ClassTable,Label=x[col]),axis=1)
        return df
    def proc(self,):
        #self.show()
        ApplyingFNList = FileNamePicker(dirList=[self.AnnotRawDir], FNrePatList=self.AnnotRawFNrePatList).proc()
        print(f"ApplyingFNList[:3] for RawAndPredictionMerger are {ApplyingFNList[:3]}")
        #testResdf = dfFromSQLite3(self.testResSQL)
        #testResDict = dict(zip(testResdf.text,testResdf.pred_Type))
        textTitledf = dfFromSQLite3(self.CZJCorpusSQL)
        textTitleDict = dict(zip(textTitledf.text,textTitledf.title)) 
        DFPdf = dfFromSQLite3(self.DFPSQL)
        DFPdf.set_index("File",inplace=True)
        DFPDict = DFPdf.to_dict('index')
        for file in ApplyingFNList:
            OUTPUTMAIN = os.path.join(self.AnnotRawDir,getMFNFromFN(file)+"_Combined")            
            #del testResdf
            #AnnotRawFN = "MERGED-20231024-20240306All.csv"
            #OUTPUTMAIN = getMFNFromFN(AnnotRawFN)+"_Combined"

            '''
            if self.args.task in ["SDSMS","SDSMS_Prediction"]:
                quoting = csv.QUOTE_ALL
                quotechar = '"'
                
            else:
                quoting = csv.QUOTE_NONE
                quotechar = ''
                
            '''
            df = CSVtodf(InputCSV = file,sep=",",header=True,
                         error_bad_lines=True,
                         #quoting=quoting,quotechar=quotechar,
                         )
            #df = self.AppendAIResultWithTestRes(df,testResDict)
            df = self.AppendAIResultWithDFP(df,DFPDict,textTitleDict)
            #df = df.sort_values(["ItcDate","Address1","Address2"])
            #print("OUTPUTMAIN",OUTPUTMAIN)
            df.sort_values(
                by=["InfoScore","pred_Type","SmsContent","ItcDate","Address1","Address2"],
                ascending=[False,True,True,True,True,True],
                inplace=True)
            dfOutputer(df,OUTPUTMAIN,TSVTextAdapter=True,
                       OutputFormat = ["tsv","sql"],
                       ).run()
        df_CLT = pd.DataFrame.from_dict(ClassTable, orient='index')
        #將df_CLT index名稱由index改成Type
        df_CLT.rename_axis("Type",inplace=True)
        #dfAppendToXLS(df_CLT,OutputFN=f"{OUTPUTMAIN}.xlsx")
        #'''
        dfListToXLS(dfList=[df,df_CLT],OutputFN=f"{OUTPUTMAIN}.xlsx",
                    sheetNameList=["PredictResult","ClassTable"],
                    AutoAdjustColWidth=True,
                    )
        #'''

        
if __name__=='__main__':
    FN = r"D:\shared\TopicClassification\Kaggle\Facebook Ad Library\us\ads.json"
    #FN = r"D:\shared\TopicClassification\Kaggle\Facebook Ad Library\us\todo.json"
    FN = r"D:\shared\TopicClassification\Kaggle\Facebook Ad Library\de\ads.json"
    FN = "KaggleExtraction/us/ads.json"
    
    '''    
    Columns = []
    Columns = ["_id","bylines","ad_creative_bodies"]
    ctxCols = ["ad_creative_bodies"]
    SaveFNCols = ["_id","bylines","ad_creative_bodies"]
    
    FN = "KaggleExtraction/human_trafficking.xlsx"
    Columns = ["Unnamed: 0","title","text"]
    ctxCols = ["title","text"]
    SaveFNCols = ["Unnamed: 0","title"]
    KDE = KaggleDatasetExtractor(
        filename=FN,Columns=Columns,ctxCols=ctxCols,SaveFNCols=SaveFNCols)#,nrows=5)
    df = KDE.proc()
    '''
    
    Columns = ["Time","Sen","Rec","Rec2","text","unknown"]
    ctxCols = ["text"]
    SaveFNCols = ["Sen","Rec","Rec2","text"]
    FN = r"D:\shared\TopicClassification\PythonModule\utils\KaggleExtraction\csvSample.txt"
    ROOTPATH = r"D:\shared\TopicClassification\PythonModule\utils\KaggleExtraction"
    for file in OSWALK(ROOTPATH):
        KDE = KaggleDatasetExtractor(
            filename=FN,Columns=Columns,ctxCols=ctxCols,SaveFNCols=SaveFNCols,
            FileType="csv")#,nrows=5)
        df = KDE.proc()