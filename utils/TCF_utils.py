import os
#import glob
import re
import time
import pathlib
import argparse
import datetime
#import wmi
from utils.MP_utils import MPlogger
from utils.utilities import OSWALK
from utils.utilities import BackupAndDelFile
from utils.utilities import timeNow
from utils.utilities import str2bool
from utils.utilities import RenameDir
from utils.utilities import getFNFromFullPath
from utils.utilities_path import find_similar_directory
from utils.df_utils import dfFromSQLite3

class TaskConnector:
    def __init__(self,SrcTask="",DesTask="",WorkingDir="",logFile=""):
        self.SrcTask = SrcTask
        self.DesTask = DesTask
        self.WorkingDir = WorkingDir
        self.logFile = logFile
    def proc(self):
        NewWorkingDir = self.WorkingDir.replace(
            f"_is_running_{self.SrcTask}",f"_rdy_for_{self.DesTask}")
        print("WorkingDir",self.WorkingDir)
        print("NewWorkingDir",NewWorkingDir)
        for i in range(3):
            try:
                #os.rename(self.WorkingDir,NewWorkingDir)
                #import shutil
                #shutil.copytree(self.WorkingDir,NewWorkingDir)
                #shutil.rmtree(self.WorkingDir)
                RenameDir(SrcDir=self.WorkingDir,DesDir=NewWorkingDir)
                if self.logFile != "":
                    MES = "-"*50+"\n"
                    MES += f"{self.SrcTask} is finished. Rename {self.WorkingDir} as {NewWorkingDir}"
                    MPlogger().logW(MES,logFile=self.logFile)
                #BackupAndDelFile(SrcDir=self.WorkingDir,DesDir=NewWorkingDir,BackFNrePat=".*dataset_total.*")
                break
            except Exception as e:
                MES = "-"*50+"\n"
                MES = f"When try to applying os.rename in TCF_utils.TaskConnector,the following occurs:\n{e}."
                MPlogger().logW(MES,logFile=self.logFile)
                #time.sleep(13)


def ClassfierOptionParser():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-debug", "--debugMode", help="Run in debug Mode",
        type=str2bool, default=False)
    parser.add_argument(
        "-p", "--TRVPort", help="Input the port for hosting the web.",
        type=int, default=8050)
    parser.add_argument(
        "-pub", "--public", help="Publish the web.",
        type=str2bool, default=False)
        #action="store_true")
    
    parser.add_argument(
        "-task", "--task", help="Specific Task.",
        type=str, default="")
    
    parser.add_argument(
        "-tr", "--train", help="Train the model.",
        type=str2bool, default=False)
        #action="store_true")
    parser.add_argument(
        "-trMD", "--trainWithMaliciousDomainDataset", help="Add the HUGE Malicious Domain Dataset to train set",
        type=str2bool, default=False)
        #action="store_true")
    parser.add_argument(
        "-trDRNOnly", "--TrainDRNDataOnly", help="Train with only DRNData.",
        type=str2bool, default=False)
    parser.add_argument(
        "-ts", "--test", help="Predict the test set.",
        type=str2bool, default=False)
        #action="store_true")
    parser.add_argument(
        "-exectime", "--ExecutionTime", help="Execution Time",
        type=str, default="")
    parser.add_argument(
        "-WPRoot", "--WorkPoolROOT", help="Use the directory as WorkPool RootDir",
        type=str, default="WorkPool")
    parser.add_argument(
        "-BertDataDir", "--BertDatasetSubDir", help="Use the directory as Bert datasetDir",
        type=str, default="")
    parser.add_argument(
        "-datasetDBDir", "--datasetDataBaseSubDir", help="The subdir of BertDatasetSubDir for saving datasetDBs",
        type=str, default="datasetDB")
    parser.add_argument(
        "-BertDataDirExt", "--BertDatasetSubDirExt", help="Add the extended part to Bert datasetDir",
        type=str, default="")
    parser.add_argument(
        "-RMBertData", "--RemoveBertDataDir", help="Move the DFPreambleCols_df_ALL to backup and Remove BertDatasetDir after all finished.",
        type=str2bool, default=False)
    parser.add_argument(
        "-mdlDir", "--modelDir", help="Use the model in the dir to predict test set.",
        type=str, default="")

    parser.add_argument(
        "-RunTRV", "--Run_Test_result_Vis", help="Run Test_result_Vis.py.",
        type=str2bool, default=True)    
    parser.add_argument(
        "-VisDir", "--VisDatasetDir", help="Use the dataset dir for Test_result_Vis.",
        type=str, default="")
    parser.add_argument(
        "-VisSelf", "--VisSelfService", help="Upload your corpus zip to test and Vis.",
        type=str2bool, default=False)
    parser.add_argument(
        "-CountArtComp", "--CountArticleComposition", help="Count Article's Composition.",
        type=str2bool, default=True)
    parser.add_argument(
        "-ExpDFAllToDB", "--ExportDFAllToDatabase", help="Export DFAll.sql3 to DFBasePATH.",
        type=str2bool, default=False)
    #parser.add_argument(
        #"-ExportDFAll", "--ExportDFAllToDatabasePath", help="Export DFAll.sql3 to DFBasePATH.",
        #type=str2bool, default=False)
    parser.add_argument(
        "-ExpDBPATH", "--ExportDatabasePath", help="The DFBasePATH for exporting DFAll.sql3 Files.",
        type=str, default="DFDatabase")
    
    parser.add_argument(
        "-DFAllExpPath", "--DFAllExportPATH", help="Export DFPreambleCols_df_ALL result to the path.",
        type=str, default="")
    
    parser.add_argument(
        "-FTPath", "--FixedTestPATH", help="Use the files in the dir to predict.",
        type=str, default="")
    
    parser.add_argument(
        "-WTFInpPath", "--WeiTechFormatInputPATH", help="Use the WeiTechFormat files in the dir to predict.",
        type=str, default="")
    parser.add_argument(
        "-WTFOptPath", "--WeiTechFormatOutputPATH", help="Use the dir to output WeiTechFormat files after predicting.",
        type=str, default="")
    parser.add_argument(
        "-WTFSepWorkPool", "--WeiTechFormatSepWorkPool", help="Use seprate work pool for batch WeiTechFormat job.",
        type=str2bool, default=False)
    parser.add_argument(
        "-WTworkIDPath", "--WeiTechworkIDPath", help="The workId Path for WeiTech job.",
        type=str, default="")
    parser.add_argument(
        "-WTworkID", "--WeiTechworkID", help="The exact workId for WeiTech job.",
        type=str, default="")
    parser.add_argument(
        "-WTWorkPoolPath", "--WeiTechWorkPoolPATH", help="The workPool Path for WeiTech job.",
        type=str, default="")
    parser.add_argument(
        "-EXTConvTask", "--ExtractionConverterTask", help="Run Extraction Converter with specified mode first.",
        type=str, default="")

    parser.add_argument(
        "-ESCFFile", "--ESDataConfigFile", help="Load the ElasticsearchJob.",
        type=str, default="")
    
    parser.add_argument(
        "-FB", "--FixedTestFileBound", help="Input the bound for the number of file for Fixed Test Dir.",
        type=int, default=0)
    parser.add_argument(
        "-TRVHost", "--TRVWebHost", help="Host the Vis web.",
        type=str2bool, default=True)
    parser.add_argument(
        "-AutoISB", "--AutoInfoScoreBound", help="Auto compute the proper InfoScoreBound. (top 500)",
        type=str2bool, default=True)
    parser.add_argument(
        "-ISlbd", "--InfoScoreSumLowerBound", help="Input the lower bound for InfoScoreSum.",
        type=int, default=-999999999)
    parser.add_argument(
        "-ISubd", "--InfoScoreSumUpperBound", help="Input the upper bound for InfoScoreSum.",
        type=int, default=99999999999)
    parser.add_argument(
        "-nScoreUPD", "--nScoringSegUPD", help="The upper bound of number of pieces to count InfoScoreSum.",
        type=int, default=100)
    parser.add_argument(
        "-mdlType", "--ModelType", help="The type of using model, TF15Bert, PytorchXLM(default), PytorchRBTL3",
        type=str, default="PytorchXLM")
    parser.add_argument(
        "-ZeroShot", "--ActiveHTCZeroshot", help="Active Zero-Shot Learning with Hierarchical Text Classification",
        type=str2bool, default=False)

    parser.add_argument(
        "-TwinsAS", "--TwinsAfterSort", help="Compute Twins Group after sort, default is False",
        type=str2bool, default=False)
    parser.add_argument(
        "-SimMethod", "--SimilarityMethod", help="Method to computer similarity of sequences,e.g. difflib,dmp,CountVectorCosine",
        type=str, default="CountVectorCosine")
    parser.add_argument(
        "-TwinsHSNoUBD", "--TwinsHighScoreNoUBD", help="Upper Bound of number of files to be important file when computing twns",
        type=int, default=99999999999)
    parser.add_argument(
        "-SumPerf", "--SummarizePerformance", help="Output test_results_verification database for each label seperately, default is False",
        type=str2bool, default=False)
    parser.add_argument(
        "-keep_checkpoint_max", "--keep_checkpoint_max", help="keep_checkpoint_max setting with default 1",
        type=int, default=1)
    parser.add_argument(
        "-TextSum", "--TextSummarization", help="For article with score over 1000, output cutted texts to Generative Summary, default is False",
        type=str2bool, default=False)

    parser.add_argument(
        "-nProc", "--nProcess", help="Number of multi-processing",
        type=int, default=1)
    parser.add_argument(
        "-nProcSPC", "--nProcessSPC", help="Number of special multi-processing",
        type=int, default=1)
    
    
    args = parser.parse_args()

    if args.train == True:
        args.test = False
        print("Start to training model, the test for FixedTest is turned off.")
    if args.train == False and args.test == False:
        args.test = True
    
    return args





#RSTR:Restricted
def GetRSTRLabelList(RSTRLabelMode):
    if RSTRLabelMode == True:
        RSTRDBTreeFile = "C:/Users/*/Documents/TACA/DB/ZMRAND/Imported/TopicTree_PAK.txt"
        if os.path.isfile(RSTRDBTreeFile) == True:
            RSTRTreeFile = RSTRDBTreeFile
        else:
            RSTRTreeFile = "../TACA/DB/ZMRAND/Imported/TopicTree_PAK.txt"
        
        RSTRLabelList = sorted(set(GetNodes(LoadTree(
            RSTRTreeFile,OnlyLettersDigitsLabels= OnlyLettersDigitsLabels))))
    else:
        RSTRLabelList = []
    return RSTRLabelList

def BackupAIPredictResultAndDelTempFile(
        BertDatasetSubDir,WorkPoolROOT="WorkPool",DesDir="",
        BackFNrePatList=["^DFPreambleCols_df_ALL.*"],
        ):
    print("-"*50)
    print("In BackupAIPredictResultAndDelTempFile")
    print("BertDatasetSubDir",BertDatasetSubDir)
    print("BackFNrePatList",BackFNrePatList)
    
    if DesDir == "":
        DesDir = BertDatasetSubDir.replace(WorkPoolROOT,WorkPoolROOT+"_DFBackup")
    print("DesDir",DesDir)
    #BackFNrePat="(^DFPreambleCols_df_ALL.*)|(^dataset_total_.*_labels_count.*)"
    
    BackupAndDelFile(SrcDir=BertDatasetSubDir,DesDir=DesDir,BackFNrePatList=BackFNrePatList)

'''
def ExportDFAllResult(
        BertDatasetSubDir,WorkPoolROOT="WorkPool",DesDir=""):
    SrcDir = BertDatasetSubDir
    if DesDir == "":
        DesDir = BertDatasetSubDir.replace(WorkPoolROOT,WorkPoolROOT+"_DFBackup")
    #BackFNrePat="(^DFPreambleCols_df_ALL.*)|(^dataset_total_.*_labels_count.*)"
    BackFNrePatList=["^DFPreambleCols_df_ALL.*","^dataset_total_.*_labels_count.*"]
    BackupAndDelFile(SrcDir=SrcDir,DesDir=DesDir,BackFNrePatList=BackFNrePatList)
'''
    
def writeUsingMark(FN = "UsingMark.txt",
                   written_text = f"This is a UsingMark."):
    open(FN,'wt',encoding='utf-8').write(written_text)
    
    
def ClearOldTestResFile(BertDatasetSubDir,outputDir,testResFile):
    UsingMarkFN = os.path.join(outputDir,"UsingMark.txt")
    written_text = f"This is a file to mark using model for {BertDatasetSubDir} after clearing old testResFile"
    writeUsingMark(FN = UsingMarkFN, written_text = written_text)
    #如果之前其他推有留下的test_results或predict.tf_record，將其刪除，以免干擾後續程式驗判。
    for filename in testResFile:
        src = os.path.join(outputDir, filename)
        if os.path.isfile(src):
            os.remove(src)

def convert_to_args_str(args):
    vars_args = vars(args)
    args_str = ""

    for key in vars_args:
        val = vars_args[key]
        if val != '':
            args_str += f" --{key} {vars_args[key]}"
    #print("vars_args",vars_args)
    return args_str

class datasetDirOutputDirPickers:
    #testResFile清單中只要有任何一個檔案存在且30秒內修改過，則判定有程序正在使用此output目錄。
    def __init__(self,
                 args = dict(),
                 rdy_for_stage = "",
                 #start_new_DataConverter = False,
                 datasetDirsROOT=None,
                 outputDirsROOT=None,
                 #modelType = "TF15Bert",
                 testResFile=[],
                 MPLOGGER = None
                 ):
        self.args = vars(args) if args != dict() else dict()
        if self.args["ExecutionTime"] == "":
            self.args["ExecutionTime"] = timeNow()
        self.rdy_for_stage = rdy_for_stage
        #print("self.rdy_for_stage",self.rdy_for_stage)
        if datasetDirsROOT is None:
            self.datasetDirsROOT = self.Pick_datasetDirsROOT()
        else:
            self.datasetDirsROOT = datasetDirsROOT
        if outputDirsROOT is None:
            self.outputDirsROOT = self.Pick_outputDirsROOT()
        else:
            self.outputDirsROOT = outputDirsROOT
        self.testResFile = testResFile
        if MPLOGGER == None:
            self.MPLOGGER = MPlogger()
        else:
            self.MPLOGGER = MPLOGGER
        
        
    def VerifyUsing(self,outdir,testResFile):
        #testResFile.append("UsingMark.txt")
        testList = testResFile + ["UsingMark.txt"]
        filepaths = [os.path.join(outdir,x) for x in testList]
        filepaths = [x for x in filepaths if os.path.isfile(x)]
        #time.sleep(15)
        print("="*50)
        print("outdir",outdir)
        print("testResFile",[x for x in testResFile])
        print("filepaths",filepaths)
        #print("st_ctimes",[(x,pathlib.Path(x).stat().st_ctime) for x in filepaths])
        print("fpath,st_ctimes,st_sizes",[(x,pathlib.Path(x).stat().st_ctime,pathlib.Path(x).stat().st_size) for x in filepaths])
        print("modi in 30 secs",[time.time()-pathlib.Path(x).stat().st_ctime<30 for x in filepaths])
        try:
            if any([time.time()-pathlib.Path(x).stat().st_ctime<30 for x in filepaths]):
                return True
            else:
                return False
        except Exception as e:
            MES = f"When VerifyUsing {testList} for {outdir}, the following error occurs:\n{e}\n Immediately return False"

    def Pick_datasetDirsROOT(self,
                        ):
        CheckDict = {"pat":"(^dataset_\d{12,16}_.*|^dataset_\d{12,16}$)",
                        "cands":["./","WorkPool","./WorkPool","../WorkPool",
                                 "WorkPool_VisSelfService","./WorkPool_VisSelfService","../WorkPool_VisSelfService"]}
        #if self.datasetDirsROOT == None:
        if self.args["WeiTechworkIDPath"] != "":
            CheckDict["cands"] = [os.path.join(
                x,re.findall("rawData/(.*?)/",self.args["WeiTechworkIDPath"])[0])
                for x in CheckDict["cands"]]
        if self.args["WeiTechworkID"] != "":
            CheckDict["cands"] = [os.path.join(
                x,self.args["WeiTechworkID"])
                for x in CheckDict["cands"]]
        for x in CheckDict["cands"]:
            if not os.path.isdir(x):
                continue
            r = re.compile(CheckDict["pat"])
            datasetDirs = list(filter(r.match, os.listdir(x)))
            #print("cands",x)
            #print("datasetDirs in Pick b4",datasetDirs)
            #print("rdy_for_stage",self.rdy_for_stage)
            if self.rdy_for_stage != "":
                datasetDirs = [x for x in datasetDirs if "rdy_for_"+self.rdy_for_stage in x]
            #print("datasetDirs in Pick af",datasetDirs)
            if len(datasetDirs) > 0:
                return x
                #self.datasetDirsROOT = x
            #break
        return None
            
    def Pick_datasetDir(self,
                        ):
        #如果未指定將執行工作階段，將假定為起始階段，開始要做DataConverter
        #if start_new_DataConverter == True:
        if self.rdy_for_stage == "" or self.rdy_for_stage == "DataConverter":
        #print("in PDa rdy_for_stage",self.rdy_for_stage)
            #if self.args['WeiTechworkID'] != "":
                #WTworkInfo = f"_{os.path.basename(self.args['WeiTechWorkPoolPATH'])}_{self.args['WeiTechworkID']}"
            #else:
                #WTworkInfo = ""
            #datasetDir = os.path.join(
                #self.args["WorkPoolROOT"],f"dataset_{self.args['ExecutionTime']}{WTworkInfo}_{self.args['ModelType']}_pt{self.args['TRVPort']}")
            datasetDir = self.args["WorkPoolROOT"]
            if self.args["WeiTechworkIDPath"] != "":
                datasetDir = os.path.join(
                    datasetDir,re.findall("rawData/(.*?)/",self.args["WeiTechworkIDPath"])[0])
            if self.args["WeiTechworkID"] != "":
                datasetDir = os.path.join(
                    datasetDir,self.args["WeiTechworkID"])
            datasetDir = os.path.join(
                datasetDir,f"dataset_{self.args['ExecutionTime']}_{self.args['ModelType']}_pt{self.args['TRVPort']}")
            if self.args["train"] == True:
                datasetDir += "_tr"
            #datasetDir += "_is_running_DataConverter"
            return datasetDir
        
        #datasetIDStr = "dataset"
        #outputIDStr = "output"
        r = re.compile("^dataset_\d{12,16}_.*"+self.args["ModelType"]+".*")#"|^dataset_\d{12,16}$)")
        #print(f"^dataset_\d{12,16}_.*{modelType}.*")
        datasetDirs = list(filter(r.search, os.listdir(self.datasetDirsROOT)))
        datasetDirs = [x for x in datasetDirs if "rdy_for_"+self.rdy_for_stage in x]
        datasetDirs = sorted(datasetDirs, reverse=True)
        if len(datasetDirs) == 0:
            return None
        else:
            datasetDir = os.path.join(self.datasetDirsROOT,datasetDirs[0])
            return datasetDir
        
    def Pick_outputDirsROOT(self,
                        ):
        CheckDict = {"pat":"(^output_\d{12,16}_.*|^output_\d{12,16}$)",
                        "cands":["./","BertScript","./BertScript","../BertScript"]}
        for x in CheckDict["cands"]:
            if not os.path.isdir(x):
                continue
            r = re.compile(CheckDict["pat"])
            outputDirs = list(filter(r.match, os.listdir(x)))
            #排除已標記為使用中的outputDir
            outputDirs = [x for x in outputDirs if "using" not in x.lower()]
            if len(outputDirs) > 0:
                return x
                #outputDirsROOT = x
                #break
        
    def Pick_outputDir(self,
                        ):
        #r = re.compile("(^output_\d{12,16}_.*|^output_\d{12,16}$)")
        r = re.compile("(^output_\d{12,16}_.*$)")
        outputDirs = list(filter(r.match, os.listdir(self.outputDirsROOT)))
        #依模型種類留下目錄有標記為該類模型之選項
        outputDirs = [x for x in outputDirs if self.args['ModelType'].lower() in x.lower()]
        #排除已標記為使用中的outputDir
        outputDirs = [x for x in outputDirs if "using" not in x.lower()]
        outputDirs = sorted(outputDirs, reverse=True)
        #outputDir = outputDirs[0]
        print("outputDirs",outputDirs)
        #time.sleep(10)
        outputDir = ""
        #testResFile.append("UsingMark.txt")
        outputDirs = [os.path.join(self.outputDirsROOT,x) for x in outputDirs]
        
        if self.args["ModelType"] == "TF15Bert":
            for outdir in outputDirs:
                #outdir = os.path.join(outputDirsROOT,outdir)
                print("In Line 450, testing", outdir)
                RT = any([x.startswith("model") for x in os.listdir(outdir)
                        if "000" not in x or 
                        time.time()-pathlib.Path(
                            os.path.join(outdir,x)).stat().st_ctime>60*20])
                print("TF15",RT)
                print("Using",self.VerifyUsing(outdir,self.testResFile))
                #time.sleep(10)
                if any([x.startswith("model") for x in os.listdir(outdir)
                        if "000" not in x or 
                        time.time()-pathlib.Path(
                            os.path.join(outdir,x)).stat().st_ctime>60*20]):
                    if self.VerifyUsing(outdir,self.testResFile):
                        continue
                    return outdir
                    #outputDir = outdir
                    #break
        elif self.args["ModelType"] in ["PytorchXLM","PytorchRBTL3"]:
            for outdir in outputDirs:
                #outdir = os.path.join(outputDirsROOT,outdir)
                r = re.compile("^checkpoint-\d{1,}")
                ckptDirs = list(filter(r.match, os.listdir(outdir)))
                ckptDirs = sorted(ckptDirs, reverse=True)
                for ckDir in ckptDirs:
                    subDir = os.path.join(outdir,ckDir)
                    if any([file in os.listdir(subDir) for file in [
                            "pytorch_model.bin",
                            "model.safetensors",
                            #"checkpoint_best_micro.pt"
                            ]]):
                        return outdir
                        #outputDir = outdir
                        #break
                else:
                    continue  # only executed if the inner loop did NOT break
                break  # only executed if the inner loop DID break
            
    def proc(
            self
            ):
        print(f"Run datasetDirOutputDirPickers to search dataset and output in {self.datasetDirsROOT},{self.outputDirsROOT} seperately.")        
        if self.args["BertDatasetSubDir"] != "":
            datasetDir = self.args["BertDatasetSubDir"]
            #print("The args[BertDatasetSubDir] is", args["BertDatasetSubDir"])
            if not os.path.isdir(datasetDir):
                print(f"{datasetDir} does NOT exits.")
                datasetDir = find_similar_directory(datasetDir)
                print(f"Applying find_similar_directory, find {datasetDir}")
        else:
            datasetDir = self.Pick_datasetDir()
        print("final datasetDir",datasetDir)
        #raise Exception
        if self.args["modelDir"] != "":
            outputDir = self.args["modelDir"]
        else:
            outputDir = self.Pick_outputDir()
        
        #print("type(MPLOGGER)",type(self.MPLOGGER))
        #print("MPLOGGER",self.MPLOGGER)
        MES = f"datasetDirOutputDirPickers pick the model dir {outputDir} for {self.args['ModelType']} mode" 
        self.MPLOGGER.logW(MES)
        return datasetDir,outputDir

def get_testResFile_Name(ModelType, BertDatasetSubDir="",outputDir=""):
    #如果是TF15Bert，testResFile輸出於模型目錄，
    #如果是PytorchXLM或PytorchRBTL3，testResFile輸出於BertdatasetSubdir目錄，
    if ModelType == "TF15Bert":
        testResFile = ["predict.tf_record","test_results.tsv"]       
        testResFile = [os.path.join(outputDir,x) for x in testResFile]
    elif ModelType in ["PytorchXLM","PytorchRBTL3"]:
        testResFile = ["test_results.tsv"]
        testResFile = [os.path.join(BertDatasetSubDir,x) for x in testResFile]
    else:
        MES = "The setting ModelType is not available,"
        MES += "only TF15Bert(default) or PytorchXLM or PytorchRBTL3 or PytorchRBTL3 is avaliable"
        print(MES)
        raise Exception
    return testResFile

class freeModelDirConformer:
    def __init__(self, 
                 args = dict(),
                 outputDirsROOT = "",
                 datasetDirsROOT = "",
                 testResFile = [],
                 EachWaitTime = 10, #second
                 RetryLimit = 360,
                 MPLOGGER = None,
                 logFile="Exception.log",
                 #logSubDir="../"
                 ):
        if args == dict():
            print("the Namespace arguments is need for freeModelDirConformer while no input! ABORT!")
        self.args = args
        self.outputDirsROOT = outputDirsROOT
        self.datasetDirsROOT = datasetDirsROOT
        self.testResFile = testResFile
        self.EachWaitTime = EachWaitTime
        self.RetryLimit = RetryLimit
        if MPLOGGER == None:
            self.MPLOGGER = MPlogger()
        else:
            self.MPLOGGER = MPLOGGER
        self.logFile = logFile
        #self.logSubDir = logSubDir
    def proc(self,):
        #檢查是否有空閒的模型目錄可用，否則再等10秒鐘。最多等10小時
        outputDir = ""
        retry = 0
        while(outputDir == "" or outputDir is None):
            #print("os.cwd",os.getcwd())
            datasetDir, outputDir = datasetDirOutputDirPickers(
                args = self.args,
                outputDirsROOT = self.outputDirsROOT,
                datasetDirsROOT = self.datasetDirsROOT,
                testResFile=self.testResFile).proc()

            if outputDir == "" or outputDir is None:
                MES = f"Using datasetDirOutputDirPickers, but there is no available free outputDir found to test {datasetDir}! Wait 10 secs"
                #MPlogger().logW(MES,logFile="TCFMain.log")
                self.MPLOGGER.logW(MES,logFile="TCFMain.log")
                time.sleep(10)
                retry += 1
                
            if retry >= self.RetryLimit:
                MES = f"It has been waiting for {self.EachWaitTime*self.RetryLimit/3600:.2f} hour ({self.RetryLimit} times) and there is no free ModelDir to use. Abort!"
                MPlogger().logW(MES,logFile="Exception.log",logSubDir="logs")
                self.MPLOGGER.logW(MES,logFile="Exception.log")
                raise Exception
        return outputDir

def LoadDatasetCount(outputDir):
    SQL3File = "dataset_total_labels_count.sql3"
    for file in OSWALK(outputDir):
        if getFNFromFullPath(file) == SQL3File:
            df = dfFromSQLite3(file)
            #df.rename(columns = {'index':'Label'}, inplace = True) 
            df = df.set_index('index')
            #print("df",df)
    return df

def get_finished_date_dir_dict(port,datasetDir_VisSelf = "WorkPool_VisSelfService"):
    r = re.compile(f"^dataset_\d{{12,16}}_.*_pt{port}_rdy_for_Spike")#"|^dataset_\d{12,16}$)")
    datasetDirs = list(filter(r.search, os.listdir(datasetDir_VisSelf)))
    # 添加新的篩選條件
    filtered_datasetDirs = []
    for dir_name in datasetDirs:
        dir_path = os.path.join(datasetDir_VisSelf, dir_name)
        if os.path.isdir(dir_path):
            files = os.listdir(dir_path)
            if "test_results_verification.sql3" in files and "DFPreambleCols_df_ALL.sql3" in files:
                filtered_datasetDirs.append(dir_name)
    filtered_datasetDirs = sorted(filtered_datasetDirs, reverse=True)
    
    # 解析日期字串並格式化為字典
    date_dir_dict = {}
    for dir_name in filtered_datasetDirs:
        date_str = dir_name.split('_')[1]
        date_obj = datetime.datetime.strptime(date_str, '%Y%m%d%H%M%S')
        formatted_date = date_obj.strftime('%Y/%m/%d %H:%M')
        date_dir_dict[formatted_date] = dir_name
        
    return date_dir_dict
