import ast
import os
import re
import shutil
from df_utils import dfFromSQLite3
from df_utils import dfOutputer
from utilities import ListCap
from utilities import OSWALK
from utilities import MKDIR

def LoadTree(file):
    result = []
    with open(file,'rt',encoding='utf-8') as f:
        for line in f:
            terms = line.strip().split(",")
            if len(terms)<3:
                continue
            result.append(terms[0:2])
    return result

#回傳下一級節點，不包含出發節點。
def GetSubNodes(TopicTree, sourceList):
    result = []
    for src in sourceList:
        for edge in TopicTree:
            if edge[0] == src:
                result.append(edge[1])
    return result
    
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
 
    
if __name__ == '__main__':
    RAND_Dir = r'H:\bought pdf\=DeepLearningText=\外國智庫\C_RAND_DUMP'
    RANDLoader().show()
    df = RANDLoader().GetMetadata()
    
    #GetSubLevel()
    TreeBinaryTarget = "Oceania"
    TreeBinaryTarget = "Artificial Intelligence"
    MaxRatio = 1000
    Subtcps = RANDLoader().GetSubtopics(sourceList=[TreeBinaryTarget])
    #print(ast.literal_eval(x))
    #
    print("="*50)
    df["label"] = df["topics"].apply(
        lambda x:
            "Positive" 
            if ListCap(
                    [tpc[2:].rstrip("']") for tpc in x.split("',")],Subtcps)!=[] 
            else "Negative")

    OUTPUTMAIN = "ArticleLabels"
    dfOutputer(df, OUTPUTMAIN).run()
    PosDf = df[df["label"]=="Positive"]
    NegDf = df[df["label"]=="Negative"]
    #print("NegDf",NegDf)
    #raise Exception
    RANDSampleTempDir = os.path.join("RAND_Temp", TreeBinaryTarget)
    max_chosenNo = MaxRatio*df["label"].value_counts().min()
    for label in ["Positive", "Negative"]:
        def CopyFiles():
            Nchoosen_file = 0
            group_df = df[df["label"]==label]
            group_df = group_df.sample(frac=1)
            group_df = group_df.head(max_chosenNo)
            for index, row in group_df.iterrows():
                PATH = row["FilePath"]
                PATH = PATH.lstrip("C_RAND_DUMP\\")
                PATH = os.path.join(RAND_Dir, PATH)
                desSubDir = os.path.join(
                    RANDSampleTempDir,"#T#[{}]".format(label))
                MKDIR(desSubDir)
                for file in OSWALK(PATH, Extension = "txt"):
                    FN = file.split("\\")[-1]
                    if len(re.findall("\d\d\d\d, \w\w\w$", PATH)) > 0:
                        if FN[0:40] != row["topics"][0:40]:
                            continue
                    des = os.path.join(desSubDir,FN)
                    shutil.copy2(file, des)
                    Nchoosen_file += 1                   
                    if Nchoosen_file > max_chosenNo:
                        return
        CopyFiles()
    raise Exception