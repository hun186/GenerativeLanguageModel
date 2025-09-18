try:
    import utils
except:
    from PackageImport import PackageImporter
    PackageImporter.proc()

import os
import json
import pandas as pd
import _pickle as pickle
from utils.utilities_path import OSWALK
from utils.df_utils import dfOutputer

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


class JsonFilesProcessor:
    def __init__(self, directory, OMFN="",
                 Extension="json",
                 output_formats=["tsv", "sql", "xls"],
                 excelindex = True,
                 IndexCols=[],
                 logger=None
                 ):
        """
        初始化 JsonFilesProcessor。

        Parameters:
            directory (str): 包含 JSON 檔案的目錄路徑。
            OMFN (str): 輸出路徑（不含副檔名），預設為 "json_to_db"。
            output_formats (list): 輸出格式，預設為 ["tsv", "sql", "xls"]。
            logger (object): 日誌記錄器，預設為 None。
        """
        self.directory = directory
        self.OMFN = OMFN if OMFN != "" else os.path.join(
            self.directory,"json_to_db")           
        self.Extension = Extension
        self.output_formats = output_formats
        self.excelindex = excelindex
        self.IndexCols = IndexCols
        self.logger = logger

    def _load_json_files_to_dataframe(self):
        """
        將指定目錄下的所有 JSON 檔案載入為 DataFrame。

        Returns:
            pd.DataFrame: 合併後的 DataFrame。
        """
        # 使用 OSWALK 函式獲取目錄下所有 JSON 檔案的路徑
        json_files = OSWALK(self.directory, Extension=self.Extension)
        
        # 初始化一個空的 DataFrame
        df = pd.DataFrame()

        # 遍歷所有 JSON 檔案並載入到 DataFrame
        for json_file in json_files:
            print(f"loading {json_file}")
            try:
                temp_df = pd.read_json(json_file)
                df = pd.concat([df, temp_df], ignore_index=True)
            except Exception as e:
                if self.logger:
                    self.logger.logW(f"Error reading {json_file}: {e}")
                else:
                    print(f"Error reading {json_file}: {e}")

        return df

    def _save_dataframe_with_dfOutputer(self, df):
        """
        使用 dfOutputer 將 DataFrame 轉存。

        Parameters:
            df (pd.DataFrame): 要轉存的 DataFrame。
        """
        try:
            outputer = dfOutputer(
                df=df,
                OMFN=self.OMFN,
                OutputFormat=self.output_formats,
                excelindex=self.excelindex,
                IndexCols=self.IndexCols,
                if_exists="replace",  # 根據需求調整
                MPLOGGER=self.logger
            )
            outputer.run()
        except Exception as e:
            if self.logger:
                self.logger.logW(f"Error saving DataFrame: {e}")
            else:
                print(f"Error saving DataFrame: {e}")

    def proc(self):
        """
        執行 JSON 檔案載入和轉存流程。
        """
        # 載入 JSON 檔案到 DataFrame
        df = self._load_json_files_to_dataframe()

        # 使用 dfOutputer 轉存 DataFrame
        self._save_dataframe_with_dfOutputer(df)

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

if __name__=='__main__':
    # 使用範例
    directory_path = r'D:\shared\TopicClassification\GenerativeLanguageModel\DeepSeek\LLMSourcePool_Finished\招標通信類'  # 指定目錄路徑
    
    # 建立 JsonFilesProcessor 實例並執行
    processor = JsonFilesProcessor(
        directory_path,Extension="txt",
        #excelindex=False,IndexCols=["project_no"]
        )
    processor.proc()