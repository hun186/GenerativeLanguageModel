try:
    import utils
except:
    from PackageImport import PackageImporter
    PackageImporter.proc()

import numpy as np
import multiprocessing as mp
import pandas as pd
from pandas.api.types import is_string_dtype
import csv
import sqlite3 as lite
import json

import time
import os
from collections import Counter
#import pyodbc
#import pymysql
#import charts
import random

from utils.MP_utils import MPlogger
from utils.MP_utils import multicoreJob
from utils.utilities import MKDIR
#from utils.utilities import hasher
from utils.utilities import ShowElapsedTime
from utils.utilities import flattenList
from utils.utilities import RemoveIlleagalCharForFileName
from utils.utilities import getFNExtFromFullPath
from utils.utilities import getMFNFromFN
from utils.utilities import getPathFromFN
from utils.utilities import TSVTextAdapter
from utils.utilities import IsVersionValid
from utils.utilities import getLineOfMaxLen
from utils.DB_utils import  createIndex

try:
    import xlsxwriter
except Exception as e:
    MES = f"When loading the module xlsxwriter, the following error occurs:\n{e}"
    MPlogger().logW(MES,logFile="ModuleNotFoundError.log")

'''
def parallelize_dataframe(df, func, n_cores=4):
    df_split = np.array_split(df, n_cores)
    pool = mp.Pool(n_cores)
    df = pd.concat(pool.map(func, df_split))
    pool.close()
    pool.join()
    return df
'''

def DFTSVTextAdapter(df,NormalizedCols = []):
    if NormalizedCols == []:
        NormalizedCols = [col for col in df.columns if is_string_dtype(df[col]) == True]
    print("Apply TSVTextAdapter to Columns:", NormalizedCols)
    for col in NormalizedCols:
        df[col] = df[col].apply(TSVTextAdapter)
            #lambda x:
                #x.replace('\"',"\'") if isinstance(x, str) else x)
            
        #for removeChar in ['\0','\u3000','\t', '\ufeff']:
            #df.text = df.text.str.replace(removeChar,'')
        #df.text = df.text.replace('"','“')
        #df.text = df.text.replace("'","’")
        #去除斷行。
        #df.text = df.text.replace("\n", " ")
        #df.text = df.text.replace("\\n", " ")
        #將全形字母、數字換成半型，以利tokenize。
        #df.text = strQ2BConverter().proc(df.text)
        #若遇連續空白，只留下一個空白。
        #df.text = ' '.join(df.text.split())
        #for x in ["\n","  ","\n "," \n"]:
            #df.text = re.sub("[{}]{{2,}}".format(x), x*2, df.text)
    return df

def dfToXLS(df, OutputFN, excelindex=True,
            #encoding = 'utf-8'
            sheet_name='Sheet1',
            mode='w',
            ):
    if df.shape[0] <= 1048576:
        try:
            with pd.ExcelWriter(
                    OutputFN,
                    engine = 'xlsxwriter',
                    engine_kwargs = {'options':{'strings_to_urls':False}},
                    #engine = 'openpyxl',
                    #options = {'strings_to_urls':False},
                    mode = mode,
                    ) as writer:
                df.to_excel(writer,index = excelindex,
                            #encoding = encoding,
                            sheet_name = sheet_name,
                            )
        except Exception as e:
            print(f"When apply disabling strings_to_urls, the following error occurs, maybe you should upgrade pands:{e}")
            df.to_excel(OutputFN,  
                        index = excelindex,
                        #encoding = 'utf-8',
                        sheet_name = sheet_name,
                        )
    else:
        print(f"Excel檔案最大列數限制 1048576，但df含有{df.shape[0]}列，無法存為Excel檔。")

def dfAppendToXLS(df, OutputFN, excelindex=True,
            sheet_name='SheetAppend1',
            ):
    if df.shape[0] <= 1048576:
        with pd.ExcelWriter(OutputFN,engine = 'openpyxl',mode = 'a',
                ) as writer:
            df.to_excel(writer,index = excelindex,
                        sheet_name = sheet_name,
                        )
    else:
        print(f"Excel檔案最大列數限制 1048576，但df含有{df.shape[0]}列，無法存為Excel檔。")


def smart_reset_index(df, new_col_name='OriginalIndex'):
    """
    如果 df 的索引只是預設的 RangeIndex (0, 1, 2, ...)，
    則不保留索引到新的欄位，直接 reset 後丟掉。
    否則，保留原索引到新的欄位 (new_col_name)。
    """
    # 判斷是否為 RangeIndex(預設流水號索引)，且從 0 開始、step=1
    if (isinstance(df.index, pd.RangeIndex) 
        and df.index.start == 0 
        and df.index.step == 1):
        # 如果是預設索引，直接丟掉
        df.reset_index(drop=True, inplace=True)
    else:
        # 若有意義的索引，則保留
        df.reset_index(inplace=True)
        df.rename(columns={'index': new_col_name}, inplace=True)
        
def dfListToXLS(dfList, OutputFN="dfListToXLSOutput.xlsx", excelindex=False,
            #encoding = 'utf-8'
            sheetNameList=[],
            AutoAdjustColWidth = False,
            AutoAdjustRowWidth = False,
            MaxColWidth = 75,
            CellMaxNRow = 4,
            ):
    writer = pd.ExcelWriter(
        OutputFN,
        engine = 'xlsxwriter',
        engine_kwargs = {'options':{'strings_to_urls':False}},
        )
    sheetNameList.reverse()
    cnt = 1
    for df in dfList:
        if df.shape[0] <= 1048576:
            if len(sheetNameList) > 0:
                sheet_name = sheetNameList.pop()
            else:
                sheet_name = f"AutoSheetName{cnt}"
                cnt+=1
            #df['index'] = df.index
            #df.reset_index(inplace = True) #會跑出一欄流水號index
            df.to_excel(writer,
                        index = excelindex,
                        #index = False,
                        #encoding = encoding,
                        sheet_name = sheet_name,
                        )
            #將所有columns設定垂直置中。
            workbook  = writer.book
            my_format = workbook.add_format()
            my_format.set_align('vcenter')
            #print("dir(my_format)",dir(my_format))
            worksheet = writer.sheets[sheet_name]  # pull worksheet object
            #worksheet.set_column('A:XFD', None, my_format)
            if AutoAdjustColWidth == True:
                print(f"設定{sheet_name}最佳欄寬，最大寬度為{MaxColWidth}")
                #worksheet = writer.sheets[sheet_name]  # pull worksheet object
                for idx, col in enumerate(df):  # loop through all columns
                    #series = df[col]
                    series = df[col].apply(lambda x:getLineOfMaxLen(x)[0])# if x is not None else 0)
                    #print("="*50)
                    #print("series",series)
                    max_len = max((
                        series.astype(str).map(len).max(),  # len of largest item
                        len(str(series.name))  # len of column name/header
                        )) + 1  # adding a little extra space
                    #print("idx,max_len b4",idx,max_len)
                    max_len = min(max_len,MaxColWidth) #控制最大寬度
                    #print("max_len af",max_len)
                    worksheet.set_column(idx, idx, max_len,my_format)  # set column width
            if AutoAdjustRowWidth == True:
                factor_of_font_size_to_width = {
                    # TODO: other sizes
                    11: {
                        "factor": 0.8,  # width / count of symbols at row
                        "height": 12,
                    },
                    12: {
                        "factor": 0.8,  # width / count of symbols at row
                        "height": 16,
                    },
                }
                #df.reset_index(inplace = True) #會跑出一欄流水號index
                smart_reset_index(df, new_col_name='MyIndex')
                for idx, dfrow in df.iterrows():  # loop through all columns
                    #print("="*50)
                    #print("idx,dfrow",idx,dfrow)
                    series = dfrow.apply(lambda x:str(x).count("\n")+1)
                    
                    #print("series",series)
                    max_nrow = max((
                        series.max(),  # len of largest item
                        len(str(series.name))  # len of column name/header
                        ))  # adding a little extra space
                    #print("idx,max_nrow b4",idx,max_nrow)
                    max_nrow = min(max_nrow,CellMaxNRow) #控制最大寬度
                    #print("max_nrow af",max_nrow)
                    #set row height
                    #首列為header，idx=0，df列對應的試算表實際列數需加1
                    worksheet.set_row(
                        idx+1, max_nrow*factor_of_font_size_to_width[11]["height"])
        else:
            print(f"Excel檔案最大列數限制 1048576，但df含有{df.shape[0]}列，無法存為Excel檔。")
    #writer.save()
    writer.close()

        
def dfToTSV(df, OutputFN, tsvIndex=False,header=False, TSVTextAdapter=False):
    #df.dropna(how="all", inplace=True, axis=1)
    #df.dropna(how="any", inplace=True, axis=1)
    nProcess = multicoreJob().ComputeNProcess()
    if TSVTextAdapter == True:
        df = multicoreJob(
            nProcess=nProcess).parallelize_dataframe(
                df, DFTSVTextAdapter)
    #print("="*50)
    #print("dfTOTSV, df",df)
    #print("="*50)
    df.to_csv(
        OutputFN, sep = '\t', index = tsvIndex,
        quoting=csv.QUOTE_NONE, quotechar="", escapechar="\\",
        header = header, encoding="utf-8")

def dfToSQL(SQLname,df,SavingDfColumns=[],
            IndexCols=[],UniqueIndexCols=[],dtype=None,
            table='sampleSrc',MPLOGGER=None,if_exists='replace',
            index_label=None):
    #print("In dts SQLName,UniqueIndexCols",SQLname,UniqueIndexCols)
    '''
    def createIndex(col,connection=None,uniqueIndex=False,MPLOGGER=None):
        if connection is None:
            print("There is no sql connection given! ABORT!")
            return
        getIndex = f'SELECT name FROM sqlite_master WHERE type = "index";'
        sqlIndexCols = [term[0] for term in list(cnx.execute(getIndex))]
        if col+"_Index" in sqlIndexCols:
            print(f"The index {col} exists! Abort creating index for {col}")
            return
        if uniqueIndex == False:
            indexType = "INDEX"
        elif uniqueIndex == True:
            indexType = "UNIQUE INDEX"
        createIndex = f'CREATE {indexType} "{col}_Index" ON "{table}"("{col}");'
        if MPLOGGER is not None:
            MES = "Creating index on column {} for table {}".format(col, table)
            MPLOGGER.logW(MES)
        cnx.execute(createIndex)
    '''
    if MPLOGGER == None:
        MPLOGGER = MPlogger()
    #SavingDfColumns = ['Column Name A','Column Name B','Column Name C']
    if len(SavingDfColumns) == 0:
        SavingDfColumns = df.columns.values
    #連結sqlite資料庫
    cnx = lite.connect(SQLname)
    
    #選取dataframe 要寫入的欄位名稱
    #欄位名稱需與資料庫的欄位名稱一樣 才有辦法對照寫入
    sql_df=df.loc[:,SavingDfColumns]
    #將字典型別的column轉換成 json字串，以存到SQLLite，為了避免取第0列時報錯，先進行列數檢驗。
    if len(sql_df) > 0:
        #print("sql_df",sql_df)
        for col in sql_df.columns:
            #print(col,type(sql_df[col][0]))
            #print("sql_df[col]",sql_df[col])
            #if isinstance(sql_df[col][0],dict):
                #sql_df[col]=sql_df[col].apply(json.dumps)
            sql_df[col]=sql_df[col].apply(
                lambda x:json.dumps(x,ensure_ascii=False) if 
                any([isinstance(x,dict),isinstance(x,list),isinstance(x,tuple)])
                else x)
    #if_exists 若是選擇 replace，如果sampleSrc 這個 table 已存在資料庫，則會將其取代。
    #if_exists 若是選擇 append，如果sampleSrc 這個 table 已存在資料庫，則會將其附加。
    #print("SQLname,UniqueIndexCols",SQLname,UniqueIndexCols)
    if len(UniqueIndexCols)>0:
        index_label = UniqueIndexCols
    else:
        index_label = None
    sql_df.to_sql(name=table, con=cnx, 
                  if_exists=if_exists,
                  dtype=dtype,
                  index_label=index_label
                  )
    
    #創造index，以提升讀取速度。
    #getIndex = f'SELECT name FROM sqlite_master WHERE type = "index";'
    #sqlIndexCols = [term[0] for term in list(cnx.execute(getIndex))]
    #print("sqlIndexCols",sqlIndexCols)
    for col in IndexCols:
        print(f"in dfToSQL of df_utils, col (in IndexCols) is {col}")
        createIndex(SQLname,table=table,IndexCol=col,connection=cnx,MPLOGGER=MPLOGGER)
    #for col in UniqueIndexCols:
        #createIndex(col,connection=cnx,uniqueIndex=True,MPLOGGER=MPLOGGER)
    cnx.close()


class SeriesToWeiTechFormatOutputer:
    '''
    如果輸入的RefWTFInpFN存在，則利用輸入的RefWTFInpFN進行加工轉存。
    '''
    def __init__(self, seri,OutputCols=[],
                 OutputFN = "test.AI2",
                 RefWTFInpFN = "",
                 WTFRefMode = False
                 ):
        self.seri = seri
        self.OutputCols = OutputCols
        self.OutputFN = OutputFN
        self.RefWTFInpFN = RefWTFInpFN
        self.WTFRefMode = WTFRefMode

    def proc(self):
        if self.WTFRefMode == True:
            if os.path.isfile(self.RefWTFInpFN):
        #if self.OutputCols == []:
            #如果輸出Cols未設定，且WTFAIMode=True，使用客製化方式轉換格式。
                with open(self.RefWTFInpFN) as jsonfile:
                    newSeriDict = json.load(jsonfile)
                PreambleCols = ["Rating",
                                "InfoScoreSum", 
                                "InfoScoreMean",
                                "NumberOfMatchingBlock",
                                "NumberOfMatchingBlockWithKW",
                                "Compositions",
                                "Class Of Most Pieces",
                                "Class Of Highest Score",
                                "NumberOfExemptPieces",
                                #"Date",
                                "Selected",
                                "Target",
                                "Twins",
                                #"File",
                                ]
                
                #newSeriDict["_id"] = seri["File"]
                #newSeriDict["indexDB"] = "ap4"
                #newSeriDict["importDT"] = seri["Date"]
                #print("self.seri",self.seri)
                newSeriDict["AI"] = dict()
                for col in PreambleCols:
                    newSeriDict["AI"][col] = self.seri[col]
                newSeriDict["AI"]["classLabels"] = dict()
                for label in [
                    "General","20Da","APEC","CrossStraitTree","RUWar","CN Military"]:
                    newSeriDict["AI"]["classLabels"][label] = True if len(self.seri[label]) > 0 else False

                self.seri = newSeriDict
                self.OutputCols = self.seri.keys()
            else:
                MES = f"When apply WeiTechFormatOutputer to {self.RefWTFInpFN}, the file does NOT exist. ABORT!"
                MPlogger().logW(MES=MES,logFile="WeiTechFormatOutputer.txt")
                return
        if self.OutputCols == []:
            self.OutputCols = self.seri.keys()
        res = dict()
        for col in self.OutputCols:
            res[col] = self.seri[col]
        #print("res",res)
        DirName = os.path.dirname(self.OutputFN)
        if len(DirName) >0:
            MKDIR(DirName)
        with open(self.OutputFN, 'w') as f:
            json.dump(res, f)
        

'''
class WeiTechFormatCombiner:
    #輸入一個WeiTechFormat字典，查詢dataframe進行加工，補上AI分析資料。
    def __init__(self, WTFdict, df):
        self.WTFdict = WTFdict
        self.df = df
        self.OutputFN = OutputFN

    def proc(self):
'''

class dfOutputer:
    def __init__(self, df, OMFN, 
                 IndexCols=[], #For SQL, make index columns to speed up the query time
                 UniqueIndexCols=[],
                 dtype = None,
                 tsvIndex=False,header=False,
                 TSVTextAdapter=False,
                 SQL_table="sampleSrc",
                 WeiTechFormatJob = dict(),
                 nProcess = 1,
                 MPLOGGER = None,
                 OutputFormat = ["tsv","sql","xls"],
                 if_exists = "replace", #{‘fail’, ‘replace’, ‘append’}
                 index_label = None, #the index key of SQL
                 sheet_name='Sheet1',
                 xlsMode = 'w',
                 excelindex = True,
                 AutoAdjustColWidth = True,
                 AutoAdjustRowWidth = True,
                 MaxColWidth = 75,
                 CellMaxNRow = 4,
                 ):
        self.df = df
        self.OMFN = OMFN
        self.IndexCols = IndexCols
        self.UniqueIndexCols = UniqueIndexCols
        #print("-"*50)
        #print("OMFN,self.UniqueIndexCols",OMFN,self.UniqueIndexCols)
        self.dtype = dtype
        self.tsvIndex = tsvIndex
        self.header = header
        self.TSVTextAdapter = TSVTextAdapter
        self.SQL_table = SQL_table
        self.WeiTechFormatJob = WeiTechFormatJob
        self.nProcess = nProcess
        #self.WeiTechFormatInputPATH = WeiTechFormatInputPATH
        #self.WeiTechFormatOutputPATH = WeiTechFormatOutputPATH
        self.MPLOGGER = MPLOGGER if MPLOGGER != None else MPlogger()
        self.OutputFormat = [x.lower() for x in OutputFormat]
        self.if_exists = if_exists
        self.index_label = index_label
        self.sheet_name = sheet_name
        self.xlsMode = xlsMode
        self.excelindex = excelindex
        self.AutoAdjustColWidth = AutoAdjustColWidth
        self.AutoAdjustRowWidth = AutoAdjustRowWidth
        self.MaxColWidth = MaxColWidth
        self.CellMaxNRow = CellMaxNRow
    def show(self):
        print("OMFN is {}".format(self.OMFN))
    
    def run(self):
        print("="*50)
        print(f"Start to run dfOutper with OMFN {self.OMFN} for \n {self.df}")
        DirName = os.path.dirname(self.OMFN)
        if DirName != "":
            MKDIR(DirName)
        #print("In df_outputer, DirName", DirName)
        #print(os.path.dirname(self.OMFN))
        #raise Exception
        if "tsv" in self.OutputFormat:
            try:
                dfToTSV(self.df, self.OMFN+'.tsv',
                        tsvIndex=self.tsvIndex,header=self.header,
                        TSVTextAdapter=self.TSVTextAdapter)
            except Exception as ex:
                print(ex)
                self.MPLOGGER.logW(ex)
        #將轉換成完成之資料集df存入SQL資料庫，以加速存取。
        if "sql" in self.OutputFormat:
            dfToSQL(self.OMFN+".sql3",
                    self.df,
                    self.df.columns.values,
                    IndexCols=self.IndexCols,
                    UniqueIndexCols=self.UniqueIndexCols,
                    dtype=self.dtype,
                    table=self.SQL_table,
                    if_exists=self.if_exists,
                    index_label=self.index_label)
        #Excel檔案最大列數限制 1048576
        if any(fmt in self.OutputFormat for fmt in ["xls", "xlsx"]):
            #dfToXLS(self.df, self.OMFN+'.xlsx', sheet_name=self.sheet_name, mode = self.xlsMode)
            
            dfListToXLS([self.df], OutputFN=self.OMFN+'.xlsx',
                        sheetNameList=[self.sheet_name],
                        excelindex=self.excelindex,
                        #encoding = 'utf-8',
                        AutoAdjustColWidth = self.AutoAdjustColWidth,
                        AutoAdjustRowWidth = self.AutoAdjustRowWidth,
                        MaxColWidth = self.MaxColWidth,
                        CellMaxNRow = self.CellMaxNRow,
                        )
            
        #WTFAIMode=True將會於dfOutputer內使用客製方式微調輸出格式。
        #以RefPATH做為索引參照資料夾，搭配df的資料，
        #將RefPATH內的WTF加工組裝，輸出新檔至WeiTechFormatJob["OutputPATH"]。
        #如果有設定WeiTechFormatOutputPATH，則每列輸出為WTF格式。
        #if self.WeiTechFormatJob != dict():
        if all([len(self.WeiTechFormatJob.get("RefPATH","")) >0,
                len(self.WeiTechFormatJob.get("OutputPATH","")) >0,
                ]):
            
            '''
            #sample of row:
            row (3, Rating
            InfoScoreSum                            -510
            InfoScoreMean                           -510
            NumberOfMatchingBlock
            NumberOfMatchingBlockWithKW
            Class Of Most Pieces           #T#Showbiz#T#
            Class Of Highest Score         #T#Showbiz#T#
            NumberOfExemptPieces
            Date                               🌎20221209
            Selected
            Target
            Twins
            File                               data2.AI2
            20Da
            APEC
            ...
            Name: 3, dtype: object)
            '''
            DTBJobs = [
                SeriesToWeiTechFormatOutputer(
                    seri = row[1],
                    RefWTFInpFN = os.path.join(
                        self.WeiTechFormatJob["RefPATH"],row[1]['File']),
                    OutputFN = os.path.join(
                        self.WeiTechFormatJob["OutputPATH"],row[1]['File']+"Predict"),
                    WTFRefMode=True)
                for row in self.df.iterrows()]
            multicoreJob(DTBJobs, method = "proc", nProcess=self.nProcess).run()


def CSVtodf(InputCSV, sep = ',', header = 'infer', 
            error_bad_lines = True, dtype={},
            nrows = None, names = None,
            quoting = csv.QUOTE_NONE, quotechar=''):
    # Import CSV
    kwargs = {
        "sep":sep,
        "quoting":csv.QUOTE_NONE, 
        "quotechar":quotechar,
        "escapechar":"\\",
        "encoding":"utf-8",
        #"header":header,
        "error_bad_lines":error_bad_lines,
        "dtype":dtype,
        "nrows":nrows
        }
    #print("*"*50)
    #print("kwargs",kwargs)
    #print("*"*50)
    FirstLineEles = open(InputCSV,'rt',encoding='utf-8'
                         ).readlines(1)[0].rstrip().split(sep)
    #raise Exception
    if names is not None:
        kwargs["names"] = names
    else:
        #假如第一列分解出來的欄位含有大於30個字元的值，則假定此為不具標題列的檔案。
        if not all([len(x) < 30 for x in FirstLineEles]):
            kwargs["names"] = ["Col"+str(x) for x in range(len(FirstLineEles))]
        else:
            #colnames = FirstLineEles
            #header = 'infer'
            kwargs["header"] = 'infer'
    
    if not IsVersionValid(ModName=pd,UBD = "1.4.0"):
        if kwargs["error_bad_lines"] == False:
            kwargs["on_bad_lines"] = "warn"
        elif kwargs["error_bad_lines"] == True:
            kwargs["on_bad_lines"] = "error"
        kwargs.pop("error_bad_lines")
    
    df = pd.read_csv(
        InputCSV,
        **kwargs)
    print("="*50)
    print("In CSVtodf, header:",header)
    print("In CSVtodf, df.columns:",df.columns)

    return df


def XLSTodf(InputXLS, index_col=None,header=0,skiprows=None,usecols=None):
    df = pd.read_excel(
        InputXLS, index_col=index_col,header=header,
        skiprows=skiprows,
        usecols=usecols,
        engine='openpyxl')
    return df
    print(df)

def DictRowsListToDF(
        rows_list,
        start_time=None,
        RemoveDumpSamples=True,
        RemoveDumpBasedOnCols=[],
        RemoveOrderIndex=True,
        Cols=[],
        ):
    '''
    將字典組成之清單轉換為DataFrame，每一個字典轉換成一個橫列。
    '''
    if start_time is None:
        start_time = time.time()
    #去除空列
    rows_list = list(filter((None).__ne__, rows_list))
    print("="*50)
    print("finished remove empty list of Row_List")
    ShowElapsedTime(start_time)
    random.shuffle(rows_list)
    print("="*50)
    print("Finished shuffling Row_List.")
    ShowElapsedTime(start_time)    
    print("="*50)
    print("The first 3 of rows_list:")
    for x in rows_list[0:3]:
        print(str(x)+"\n")
    df = pd.DataFrame(rows_list)
    if len(Cols) > 0:
        df.columns = Cols
    #RemoveDumpSamples = False
    if RemoveDumpSamples == True:
        oriLen = len(df)
        #如果未設定重複移除的參照行時，則所有行相等才移除重覆列。
        if RemoveDumpBasedOnCols == []:
            RemoveDumpBasedOnCols = df.columns
        #去除重複樣本，當(Out)Label與text都相同時，則去除。    
        #df = df[~df.duplicated(['OutLabel','text'])]
        df = df[~df.duplicated(RemoveDumpBasedOnCols)]
        print(f"Finished remove duplicated according to {RemoveDumpBasedOnCols}")
        print(f"There are {len(df)-oriLen} removed.")
        ShowElapsedTime(start_time)
        print("df af remov dup", df)
        print("df.columns af remov dup", df.columns)
    
    if df.shape[0] == 0:
        print("WARNING!! Dataframe df is empy!! ABORT!")
        #raise Exception
    #移除數值流水號Index
    if RemoveOrderIndex == True:
        df = df.reset_index(drop=True)
    #if len(df)>0:
        #print("rows_list[0:2]",rows_list[0:2])
        #raise Exception
    return df
    
def dftoMySQL(df, db_settings=None, TableName = 'Samples'):
    db_settings = {
        "host": "127.0.0.1",
        "port": 3306,
        "user": "root",
        "password": "abc123",
        "db": "test",
        "charset": "utf8mb4"
    }
    Cols = ['InLabel', 'OutLabel', 'texts','fileSrc', 'DataSrcType', 'DataSrc']
    df.columns = Cols
    for col in Cols:
        df[col] = getattr(df,col).astype(str)
    for col in df.columns:
        df[col] = df[col].apply(
            lambda x:
                x.replace('\"',"\'") if isinstance(x, str) else x)
    
    #如果text結尾為 \，補上空白，以免\與字分隔符"結合，
    #造成SQL將 \"誤判為"，而視為text字串的一部份，
    #因而導致SQL語法錯誤。
    df['texts'] = df['texts'].apply(
        lambda x: x+x.endswith('\\')*' ')
    df['SampleID'] = df['texts'].apply(
        lambda x: hash(x.encode('utf-8'), 'sha1'))
    Cols = ['SampleID', 'InLabel', 'OutLabel',
            'texts','fileSrc', 'DataSrcType', 'DataSrc']
    df = df[Cols]
    ColumnsString = ",".join(Cols)
    #print("ColumnsString",ColumnsString)
    ColumnsTypeString ='''
        SampleID CHAR(40) NOT NULL,
        InLabel VARCHAR(50) NOT NULL,
        OutLabel VARCHAR(50) NOT NULL,
        texts VARCHAR(2048) NOT NULL,
        fileSrc VARCHAR(400) NOT NULL,
        DataSrcType VARCHAR(200) NOT NULL,
        DataSrc VARCHAR(200) NOT NULL,
        PRIMARY KEY (SampleID)
        '''
    # 建立Connection物件
    conn = pymysql.connect(**db_settings)
    cursor = conn.cursor()
    try:
        # Create Table
        create_table = "CREATE TABLE IF NOT EXISTS {} ({})".format(
            TableName, ColumnsTypeString)
        cursor.execute(create_table)
        createIndex = 'CREATE INDEX {} ON {}({});'.format(
            "SampleID_Index",TableName,"SampleID")
        cursor.execute(createIndex)
        createIndex = 'CREATE INDEX {} ON {}({});'.format(
            "texts_Index",TableName,"texts")
        cursor.execute(createIndex)
        
    except Exception as ex:
        print(ex)
    
    #def dfInserter(df):
    i = 0
    for row in df.itertuples():
        if i % 1000 == 0:
            MES = "{} samples have been imported.".format(i)
            print(MES)
            MPlogger().logW(MES)
            conn.commit()
        Attrs = list(row[1:]) #捨去index number
        ValuesString = ",".join(
            ["{}{}{}".format('"',x,'"') for x in Attrs])
        insert_dict = 'INSERT INTO {} ({}) VALUES ({})'.format(
                TableName, ColumnsString, ValuesString)
        try:
            cursor.execute(insert_dict)
        except Exception as ex:
            MPlogger().logW("="*50)
            MPlogger().logW(row)
            MPlogger().logW(ex)
            MPlogger().logW(insert_dict)
            pass
        i += 1
    MES = "{} samples have been imported.".format(i)
    print(MES)
    MPlogger().logW(MES)
    conn.commit()
    return pd.DataFrame()

    
def dfFromSQLite3(sql3File,
                  tableList = None,
                  columnList = None,
                  orderList = None,
                  clause = ""):
    # Read sqlite query results into a pandas DataFrame
    conn = lite.connect(sql3File)
    if type(tableList) == str:
        tableList = [tableList]
    if tableList == None:
        tableList = list(conn.execute("SELECT name FROM sqlite_master WHERE type='table';"))
        tableList = [x[0] for x in tableList]
    if columnList == None:
        ColumnStrings = "*"
    else:
        ColumnStrings = ','.join(columnList)
    if orderList == None:
        orderStrings = ""
    else:
        orderStrings = "ORDER BY "+','.join(orderList)
        
    print("tableList",tableList)
    df = pd.DataFrame()
    print("Start to load the sql3 file {}.".format(sql3File))
    for name in tableList:
        print("Loading the table {}".format(name))
        #df = pd.read_sql_query("SELECT * FROM {}".format(table), conn)
        
        query = "SELECT {} FROM {} {}".format(
            ColumnStrings, name, orderStrings)
        if clause != "":
            query += clause
        #print(f"Start to load from sql3 with query: {query}")
        df = pd.concat(
            [df,pd.read_sql_query(query, conn)])
    
    # Verify that result of SQL query is stored in the dataframe
    #print(df.head())
    conn.close()
    print("Finished Loading the tables {}".format(tableList))
    return df


def concat_df_str1(df):
    """ run time: 1.3416s """
    return pd.Series([''.join(row.astype(str)) for row in df.values], index=df.index)

def compare_dfs(df1,df2):
    boolList = (df1.sort_index().sort_index(axis=1) == 
                df2.sort_index().sort_index(axis=1)).values.tolist()
    boolList = flattenList(boolList)
    return Counter(boolList)





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
    def proc(self):
        if not os.path.isfile(self.filename):
            print(f"{self.filename} does not exist, Abort!")
            return
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
                         sep = self.sep, header = self.header,
                         error_bad_lines = True,
                         nrows = self.nrows)
        elif self.FileType == "json":
            if self.nrows is not None:
                df = pd.read_json(self.filename,nrows=self.nrows, lines=True)
            else:
                df = pd.read_json(self.filename)#,orient="records", lines=True, chunksize=5)
        print(f"Finished loading, the Columns are {df.columns.tolist()}")
        #if self.Columns != []:
            #df = df[self.Columns]
        print("df",df)
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
            if i % 10000 == 0:
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
                text = ''.join([str(row[col]) for col in self.ctxCols])

                SaveFN = '_'.join([str(row[col])[:20] for col in self.SaveFNCols])+".txt"
                #f"{str(row['_id'])[:20]}_{row['bylines'][:20]}_{text[:20]}.txt"
                SaveFN = RemoveIlleagalCharForFileName(SaveFN)
                #print("SavePath",SavePath)
                #print("SaveFN",SaveFN)
                FullSaveFN = os.path.join(SavePath,SaveFN)
                f = open(FullSaveFN, 'wt', encoding='utf-8')
                f.write(text)
                f.close()
                i+=1
        return
        for index, row in df.iterrows():
            #if str(row['content']) != "nan":
            if True:
                Label = row['genre_name'].split("|")[0].strip()
                MKDIR(Label)
                title = RemoveIlleagalCharForFileName(row['title'])
                OutputFN = os.path.join(Label,title+".txt")
                open(OutputFN,mode='wt',encoding='utf-8').write(row['content'])
                #print(row['title'], row['content'], row['genre_name'])
            
            #print("="*50)
        #print(df)
                
if __name__=='__main__':
    FN = r"D:\shared\TopicClassification\Kaggle\Facebook Ad Library\us\ads.json"
    #FN = r"D:\shared\TopicClassification\Kaggle\Facebook Ad Library\us\todo.json"
    FN = r"D:\shared\TopicClassification\Kaggle\Facebook Ad Library\de\ads.json"
    FN = "KaggleExtraction/us/ads.json"
    Columns = []
    Columns = ["_id","bylines","ad_creative_bodies"]
    ctxCols = ["ad_creative_bodies"]
    SaveFNCols = ["_id","bylines","ad_creative_bodies"]
    KDE = KaggleDatasetExtractor(
        filename=FN,Columns=Columns,ctxCols=ctxCols,SaveFNCols=SaveFNCols)#,nrows=5)
    df = KDE.proc()