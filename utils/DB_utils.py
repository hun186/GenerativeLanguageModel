from PackageImport import PackageImporter
PackageImporter.proc()

import os
from pymongo import MongoClient
import pprint
import datetime as dte
import pytz
import pandas as pd
import sqlite3
import re
import time
import ast
import json
import datetime
import calendar
from colorama import Fore#, Back, Style

from elasticsearch import Elasticsearch

from utils.utilities import MKDIR
from utils.utilities import OSWALK
from utils.utilities import DictIndentPrint
from utils.utilities import ConvertTimeStrFMT
from utils.utilities import DictTransposer
from utils.utilities import TSVTextAdapter
from utils.utilities import DateList
from utils.utilities import timeRelative
try:
    from utils.df_utils import dfFromSQLite3
    from utils.df_utils import dfOutputer
except:
    pass

def regexp(expr, item):
    reg = re.compile(expr)
    return reg.search(item) is not None

def _connect_mongo(host, port, username, password, db):
    """ A util for making a connection to mongo """

    if username and password:
        mongo_uri = 'mongodb://%s:%s@%s:%s/%s' % (username, password, host, port, db)
        conn = MongoClient(mongo_uri)
    else:
        conn = MongoClient(host, port)

    return conn[db]

def Read_Mongo(db='LPNK',
               collection='2013Test', 
               query = None, 
               project = None,
               host = 'localhost', port = 27017, 
               username = None, password = None, 
               no_id = True,):
    """ Read from Mongo and Store into DataFrame """

    # Connect to MongoDB
    db = _connect_mongo(
        host=host, port=port, 
        username=username, password=password, db=db)

    # Make a query to the specific DB and Collection
    cursor = db[collection].find(query, project)

    # Expand the cursor and construct the DataFrame
    df =  pd.DataFrame(list(cursor))

    # Delete the _id
    if no_id and '_id' in df.columns.tolist():
        del df['_id']

    return df

#以字串形式比對時間，印出時段內資料。
def PrintData(collection, TP):
    TimeLen = len(str(TP[0]))
    for x in collection.find():
        if TP[0] <= int(x['Time'][0:TimeLen]) < TP[1]:
            if 'Receiver' not in x.keys():
                x['Receiver'] = ""
            pprint.pprint(','.join([x[key] for key in 
                           ['Sender', 'Receiver', 'Time', 'Length']]))


def AddDatetimeField(collection):
    pacific = pytz.timezone('US/Pacific')
    for x in collection.find():
        if "Datetime" not in x:
            #print(x["Time"])
            #aware_datetime = pacific.localize(
                #dte.datetime.strptime(x["Time"], "%Y%m%d%H%M%S"))
            aware_datetime = dte.datetime.strptime(x["Time"], "%Y%m%d%H%M%S")
            #print("aware_datetime", aware_datetime)
            collection.update_one({
              '_id': x['_id']
            },{
              '$set': {
                'Datetime': aware_datetime
              }
            }, upsert=False)

def ShowDataAttr(collection, attribute):
    for x in collection.find()[:5]:
        print(x[attribute])

def MongoTest():
    #如果無法連線本機server，確認本機server服務有執行，或啓動之：
    #執行 MongoDB path/bin/mongod --dbpath DBPATH
    #client = MongoClient('localhost', 27017)
    client = MongoClient('mongodb://localhost:27017/')
    db = client['LPNK']
    #collection = db['Y2013']
    #將字串型式時間轉為DateTime物件
    AddDatetimeField(db['Y2013'])
    
    #Before Mongo 4.0
    #client.admin.command('copydb',fromdb='LPNK',todb='LPNK2')
    #db['2013'].copyTo("2013_Copy")

    #client.copy_database(from_name='LPNK',to_name='LPNK2')
    
    #mongo shell:
    #db.Y2013.find().forEach(function(d){ db.getSiblingDB('CopyDB')['copyCol'].insert(d); });
    
    query = {'Time':'20130922132400'}
    TP = [201310230000,201310231400]
    
    ShowDataAttr(db['Y2013'], 'Datetime')
    print("="*50)
    #mongo shell query
    #{Datetime:{
    #    $gte: ISODate("2013-09-22T13:00:00.000Z"),
    #    $lt: ISODate("2013-09-22T17:00:00.000Z")}}

    FMT = "%Y-%m-%dT%H:%M:%SZ"
    from_dt = dte.datetime.strptime(
        "2013-10-23T00:00:00Z", FMT)
    to_dt = dte.datetime.strptime(
        "2013-10-23T14:00:00Z", FMT)
    query = {
        "$or":[
        {"Sender": {
            "$in": ["736158"],
            }},
        {"Receiver": {
            "$in": ["736158"],
            }},
        ],
        #"Datetime":{
            #"$gte": from_dt,
            #"$lt": to_dt
            #}
        }
    project = {
        "_id":0,
        "Sender":1, 
        "Receiver":1, 
        "Datetime": 1, 
        "Length":1
        }
    #print("query", query)
    df = Read_Mongo(
                query=query,
                #project=project,
                db='LPNK',
                collection='Y2013',)
    print("The result of Read_Mongo is", df)
    print("="*50)
    for x in df.head(3).itertuples():
        print(x)


def SQLConcat(
        sql3FileList=[],
        OMFN="SQLConcat",
        #OMFN=r"D:\SQLConcat",
        SQL_table="sampleSrc",
        #UniqueIndexCols=["File"],
        IndexCols=["File"]
        ):
    res = pd.DataFrame()
    for sql3File in sql3FileList:
        PartDF = dfFromSQLite3(sql3File)
        #print("PartDF",PartDF)
        res = pd.concat([res.reset_index(drop=True),
                    PartDF.reset_index(drop=True)],axis=0)
    #print("concat res",res)
    res = res.drop("index",axis=1)
    #res = res.reset_index(drop=True)
    #print("res",res)
    #print("="*50)
    #print("res.columns",res.columns)
    #print("len(res.columns)",len(res.columns))
    dfOutputer(
        df=res,
        OMFN=OMFN,
        SQL_table=SQL_table,
        OutputFormat = ["sql"],
        #UniqueIndexCols=UniqueIndexCols,
        IndexCols=IndexCols
        ).run()
    return res
        
    
def CheckTableExistence(SQLname,table="tableTest"):
    conn = sqlite3.connect(SQLname)
    query = f'SELECT name FROM sqlite_master WHERE type="table" AND name ="{table}";'
    c = conn.cursor()
    res = list(c.execute(query))
    conn.close()
    return res

def CheckSqlState(sql3File):
    if not os.path.isfile(sql3File):
        print(f"The file {sql3File} doesn't exist, no src to load.")
        return False 
    if all([
            #not CheckTableExistence(sql3File,table=f"{ExtMethod}CompDict_{SQL_tableSuff}") 
            #for ExtMethod in ExtMethodList]+[
            not CheckTableExistence(sql3File,table="SimDict") 
            ]
            ):
        #print(f"Any of the table for {ExtMethodList}CompDict_{SQL_tableSuff} doesn't exist for in file {sql3File}, you should build one similarity sql3 DB first.")
        print(f"The table SimDict doesn't exist for in file {sql3File}, you should build one similarity sql3 DB first.")
        return False
    return True


def InsertDictToSQL(
        SQLname,table="tableTest",
        #Columns = ["key","value"],
        DictColNames = {"key":"keyName","value":"valueName"},
        DictColTypes = {"keyName":"TEXT","valueName":"TEXT"},
        writtenDict=dict(),
        indentDict = False):
    #ColumnsString = ",".join(Columns)
    ColumnsString = ",".join(DictColNames.values())
    #print("ColumnsString:", ColumnsString)
    MKDIR(os.path.dirname(SQLname))
    conn = sqlite3.connect(SQLname,timeout=60)
    c = conn.cursor()
    
    create_table = "CREATE TABLE IF NOT EXISTS {} ({})".format(
        table, ColumnsString)
    #print("in insertDictToSQL, create_table",create_table)
    for i in range(10):
        try:
            c.execute(create_table)
            break
        except Exception as e:
            MES = f"While run InsertDictToSQL in DB_utils to write sql3, the following error occurs, wait 2 seconds and retry for {i+2}th time:\n{e}"
            print(MES)
            time.sleep(2)
    

    #columns = ','.join("'" + str(x).replace('/', '_') + "'" for x in writtenDict.keys())
    #values = ','.join("'" + str(x).replace('/', '_') + "'" for x in writtenDict.values())
    #query = "INSERT INTO %s ( %s ) VALUES ( %s );" % ('table', columns, values)
    #print("DictColTypes",DictColTypes)
    for ckcol in DictColNames.values():
        print(f"checking whether column {ckcol} exists in {SQLname}")
        checkColQuery = f"SELECT {ckcol} FROM {table};"
        #print("ckcol,DictColTypes.get(ckcol,'TEXT')",ckcol,DictColTypes.get(ckcol,'TEXT'))
        try:
            c.execute(checkColQuery)
        except:
            print(f"The column {ckcol} doesnot exit in {SQLname}. Adding it.")
            addColQuery = f"ALTER TABLE {table} ADD {ckcol} {DictColTypes.get(ckcol,'TEXT')};"
            c.execute(addColQuery)
        finally:
            pass
    #取得sql3檔案中已存在的鍵值，以決定進行INSERT或UPDATE
    query = f'SELECT {DictColNames["key"]} FROM {table}'
    #print("query ExistingKeys", query)
    ExistingKeys = set(sqlite3Query(SQLname,query=query,ListForm = True))
    #print("ExistingKeys in DB_utils",ExistingKeys)
    for key in writtenDict.keys():
        #print("dealing key",key)
        #key = TSVTextAdapter(key)
        #print("key",key,"key in ExistingKeys",key in ExistingKeys)
        #time.sleep(10)
        writtenDictValue = writtenDict[key]
        if indentDict == True and isinstance(writtenDictValue,dict):
            #print("writtenDict[key] b4",writtenDict[key])
            #字典字串外要使用雙引號，key值用單引號，所以先把雙引號取代為單引號
            #例如：SET NoExtCompDict="{'RU-UA Military Confrontation': 6}"
            writtenDictValue = json.dumps(writtenDictValue, indent=4).replace('\"',"\'")
            #print("writtenDict[key] af",writtenDict[key])
        if key not in ExistingKeys:
            if str(key) in ExistingKeys:
                MES = f"WARNING! key {key} not in ExistingKeys but str(key) in ExistingKeys of {SQLname} with query {query}. There might be a type setting mistake in SQL! If something bad happens, check this!"
                print(MES)
                time.sleep(1)
        #try:
            #print(f"{key} not exist in ExistingKeys of sql3, adding.")
            ValuesString = ",".join(
                ["{}{}{}".format('"',insValue,'"') for insValue in [key,writtenDictValue]])#.replace("\\","")    
            insert_dict = 'INSERT INTO {} ({}) VALUES ({})'.format(
                table, ColumnsString, ValuesString)
            for i in range(10):
                try:
                    #print("insert_dict",insert_dict)
                    c.execute(insert_dict)
                    break
                except Exception as e:
                    MES = f"While run InsertDictToSQL in DB_utils with query {insert_dict} to write sql3, the following error occurs, wait 3 seconds and retry for {i+2}th time:\n{e}"
                    print(MES)
                    time.sleep(3)
        else:
        #except Exception as e:
            #print(f"{key} exist in ExistingKeys of sql3, updating.")
            #print(e)
            #insert_dict = f"SET {table}.{Columns[1]}={writtenDictValue} WHERE {Columns[0]}={key}"
            insert_dict = 'UPDATE {} SET {}="{}" WHERE {}="{}"'.format(table,DictColNames["value"],writtenDictValue,DictColNames["key"],key)
            #print("insert_dict",insert_dict)
            #raise Exception
            retry = 0
            while(retry<10):
                try:
                    #print("insert_dict",insert_dict)
                    c.execute(insert_dict)
                    break
                except Exception as e:
                    MES = f"While run InsertDictToSQL in DB_utils with query {insert_dict} to write sql3, the following error occurs, wait 3 seconds and retry for {i+2}th time:\n{e}"
                    print(MES)
                    time.sleep(3)
                    retry += 1
    #conn.commit()
    
    retry = 0
    while(retry<10):
        try:
            conn.commit()
            break
        except Exception as e:
            MES = f"While run InsertDictToSQL in DB_utils to write sql3, the following error occurs, wait 2 seconds and retry:\n{e}"
            print(MES)
            time.sleep(2)
            retry += 1
    conn.close()
            
def SaveDictToSQL(
        Dict=dict(), SQLname="test.sql3",table="tableTest",
        DictKeyLvForColName = None,DictKeyLvForRowName = None, #LV:0-index
        ColNameOfKey = "key",
        DictColTypes = dict(),
        IndexCol = "",
        uniqueIndex = False,
        indentDict = False,
        ):
    #由0開始計算層數，預想用第0層當ColName，第0層（即下去一層）當的橫索引
    #如果是相反的話，則先取transpose
    if DictKeyLvForColName == 1:
        Dict = DictTransposer.proc(Dict)
        Columns = list(Dict.keys())
    '''
    for key in Dict.keys():
        Columns.append(list(Dict[key].keys()))
    else:
        Columns = []
    '''
    Columns = Dict.keys()
    #print("Columns in SaveDictToSQL",Columns)
    for col in Columns:
        #writtenDict = dict()
        #for key in Dict:
            #writtenDict[key] = Dict[key][col]
        writtenDict = Dict[col]
        #print("col,writtenDict",col,writtenDict)
        InsertDictToSQL(
            SQLname,table=table,
            #Columns = ["key","value"],
            DictColNames = {"key":ColNameOfKey,"value":col},
            DictColTypes = DictColTypes,
            writtenDict=writtenDict,
            indentDict = indentDict)
    createIndex(
        SQLname,table,IndexCol=IndexCol,Columns=Columns,
        uniqueIndex=uniqueIndex,MPLOGGER=None)

def LoadDictFromSQL(SQLname,table="tableTest",Columns=[]):
    res = dict()
    query = f"SELECT * FROM {table}"
    for key, value in sqlite3Query(SQLname,query=query,ListForm = True):
        res[key] = ast.literal_eval(value)
    #print(res)
    return res


def createTable(SQLname,table,
                #ColTypeDict = dict(),
                ColDict = dict(),
                UniqueCols = [],
                ):
    MKDIR(os.path.dirname(SQLname))
    #連結sqlite資料庫
    conn = sqlite3.connect(SQLname)
    #if connection is None:
        #print("There is no sql connection given! ABORT!")
        #return
    #Columns = [f"{name} {datatype}{' UNIQUE' if name in UniqueCols else''}" for name,datatype in ColTypeDict.items()]
    Columns = []
    for name in ColDict.keys():
        fieldStr = name
        #Composite Key格式不同，另外處理。
        if re.match("(.*,.*)",name) and [
                x.lower() for x in list(ColDict[name].keys())] == ["property".lower()] and [
                    x.lower() for x in list(ColDict[name].values())] == ["PRIMARY KEY".lower()]:
            fieldStr = f"PRIMARY KEY {name}"
        else:
            if "datatype" in ColDict[name]:
                fieldStr += f" {ColDict[name]['datatype']}"
            if "property" in ColDict[name]:
                #如果ColDict[name]["property"]僅為單一字串，將其轉換為list，以便使用' '.join
                if type(ColDict[name]["property"]) == str:
                    ColDict[name]["property"] = [ColDict[name]["property"]]
                fieldStr += (" "+" ".join(ColDict[name]['property']))
        Columns.append(fieldStr)
    #Columns = [f"{name} {datatype}{' UNIQUE' if name in UniqueCols else''}" for name,datatype in ColDict.items()]
    #CREATE TABLE t1(a INT, b TEXT, c REAL);
    ColumnsString = ",".join(Columns)
    create_table = f"CREATE TABLE IF NOT EXISTS {table} ({ColumnsString})"
    print(f"{Fore.LIGHTYELLOW_EX}create_table query:{create_table}{Fore.RESET}")
    conn.execute(create_table)
    conn.close()
    
def createIndex(SQLname,table,IndexCol,IndexName="",
                Columns=[],connection=None,
                uniqueIndex=False,MPLOGGER=None):
    if IndexName == "":
        IndexName = IndexCol+"_Index"
    if Columns == []:
        Columns = [IndexCol]
    
    MKDIR(os.path.dirname(SQLname))
    #連結sqlite資料庫
    conn = sqlite3.connect(SQLname)
    #if connection is None:
        #print("There is no sql connection given! ABORT!")
        #return
    
    ColumnsString = ",".join(Columns)
    create_table = f"CREATE TABLE IF NOT EXISTS {table} ({ColumnsString})"
    conn.execute(create_table)
    
    
    getIndex = 'SELECT name FROM sqlite_master WHERE type = "index";'
    sqlIndexCols = [term[0] for term in list(conn.execute(getIndex))]
    if IndexName in sqlIndexCols:
        print(f"The index {IndexName} exists! Abort creating index for {IndexCol}")
        return
    if uniqueIndex == False:
        indexType = "INDEX"
    elif uniqueIndex == True:
        indexType = "UNIQUE INDEX"
    createIndex = f'CREATE {indexType} {IndexName} ON "{table}" ("{IndexCol}");'
    print("createIndex in createIndex of DB_utils",createIndex)
    if MPLOGGER is not None:
        MES = "Creating index on column {} for table {}".format(IndexCol, table)
        MPLOGGER.logW(MES)
    '''  
    for i in range(10):
        try:
            conn.execute(createIndex)
            break
        except Exception as e:
            MES = f"While run createIndex in DB_utils to write sql3, the following error occurs, wait 2 seconds and retry for {i+2}th time:\n{e}"
            print(MES)
            time.sleep(2)
    '''
    conn.execute(createIndex)
    conn.close()

def sqlite3Query(SQLname, cols=None, clause=None, table=None,
                 query = None, ListForm = False):
    if all([
            not os.path.isfile(SQLname),
            "UPDATE " not in query,
            "INSERT " not in query,
            "SET " not in query,
            ]):
        print(f"When try to apply sqlite3Query with the query {query} to the file {SQLname}, the file does NOT exist and query does NOT contain UPDATE, INSERT, SET. Return empty list immediately!")
        return []
    rowslist = []
    '''
    print(f"run query {query} with {SQLname}")
    if os.path.isfile(SQLname) == False:
        print("SQLname seems not to exist now, Maybe renaming, wait for 10 secs")
        time.sleep(10)
        if os.path.isfile(SQLname) == False:
            print("SQLname seems not to exist after waiting 10secs. abort")
            raise Exception
    '''
    conn = sqlite3.connect(SQLname)
    conn.create_function("REGEXP", 2, regexp)
    c = conn.cursor()
    
    #TableName = Dict['mission'].split("_")[-1].replace(" ","_")
    #create_table = "CREATE TABLE IF NOT EXISTS {} ({})".format(
        #TableName, ColumnsString)
    if query == None:
        query = "SELECT "+','.join(cols)
        if table != None:
            query += " FROM "+table
        if clause !=None:
            query += " WHERE "+clause
    #print("query",query)

    if ListForm == False:
        if "UPDATE" in query:
            c.execute(query)
            conn.commit()
            conn.close()
        else:
            #暫時關閉非ListForm功能，以觀察database is locked問題是否解決。
            return c.execute(query)
            #result = list(c.execute(query))
            #if len(result) > 0:
                #if len(result[0]) == 1: 
                    #result = [x[0] for x in result]
                #conn.close()
            #return result
        #c.execute(query)
        #return c.fetchall()
    else:
        result = list(c.execute(query))
        #如果原result = [('A',),('B',),('C',)]
        #轉換為result = ['A','B','C']
        if len(result) > 0:
            if len(result[0]) == 1: 
                result = [x[0] for x in result]
        conn.close()
        return result

    #conn.commit()
    #conn.close()
       
def sqlite3QueryTest():
    SQLname = "D:/Emo/test_results_verification_Large.sql3"
    cols = ['PartNO', 'pred_Type', 'text']
    #clause = f"'Src'={file}"
    clause = "abc"
    table = "sampleSrc"
    
    #SELECT PartNO,pred_Type,text from sampleSrc where SRC = "..\FixedTest\#T#[PRC-Think]\科睿唯安\#T#[5G]\5G技術全景報告.txt";
    query = "SELECT DISTINCT Src FROM sampleSrc;"
    FileList = [x[0] for x in list(sqlite3Query(SQLname, query = query))]
    print(f"There are totally {len(FileList)} different files.")
    for file in FileList:
        if file is None:
            continue
        print("file", file)
        query = f'SELECT PartNO,pred_Type,text FROM sampleSrc WHERE SRC = "{file}";'
        rowslist = sqlite3Query(SQLname,  query = query)


def YearMonthsList(startDay,endDay, FMT="%Y%m"):
    #start_date, end_date = "2021-10-10", "2022-02-08"     
    month_list = pd.period_range(start=startDay, end=endDay, freq='M')
    month_list = [month.strftime(FMT) for month in month_list]
    return month_list

def BuildESJobList(
        esJobTemplate,startDay="20230901",endDay="20230901",
        freq="D",FMT = "%Y%m%d",periods=100):
    print(f"Start to build esJob List with template {esJobTemplate}")
    res = []
    #startMon = startDay[4:2]
    #endMon = endDay[4:2]
    #MonthsList = [str(mon) for mon in range(startMon,endMon+1)]
    dteList = DateList(
        startday=timeRelative(args={"months":-7},outputFMT=FMT),
        periods=7,
        freq=freq,
        FMT=FMT)
    #print("DateList",dteList)

    if "langCodeList" not in esJobTemplate:
        esJobTemplate["langCodeList"] = ["C"]
    esFMT = "%Y-%m-%dT%H:%M:%SZ"
    for i,day in enumerate(dteList[:-1]):
        esJob = dict()
        esJob["startDay"] = ConvertTimeStrFMT(
                TimeStr=dteList[i],srcFMTCands = ["%Y%m%d"],desFMT = esFMT)
        esJob["endDay"] = ConvertTimeStrFMT(
            TimeStr=dteList[i+1],srcFMTCands = ["%Y%m%d"],desFMT = esFMT)
        if "es_tokens" in esJobTemplate:
            esJob["es_tokens"] = esJobTemplate["es_tokens"]
        year = dteList[i][0:4]
        mon = dteList[i][4:6]
        if "indexnameTemplate" in esJobTemplate:
            esJob["indexname"] = esJobTemplate["indexnameTemplate"].replace("%m",mon).replace("%Y",year)
        if "Vis_ESFileNameMode" in esJobTemplate:
            esJob["Vis_ESFileNameMode"] = esJobTemplate["Vis_ESFileNameMode"]
        if "langCodeList" in esJobTemplate:
            for langCode in esJobTemplate["langCodeList"]:
                esJob["langCode"] = langCode
                res.append(esJob.copy())
    print("The first two generated esJob are"),
    for esJob in res[:2]:
        DictIndentPrint(esJob)
    return res


def getESData(esJob):
    if "es_tokens" not in esJob.keys() or "indexname" not in esJob.keys():
        return []
    else:
        es_tokens = esJob["es_tokens"]
    if "startDay" not in esJob:
        esJob["startDay"] = "2022-12-01T00:00:00Z"       
    if "endDay" not in esJob:
        esJob["endDay"] = "2022-12-10T20:00:00Z"
    #if "langCode" not in esJob:
        #esJob["langCode"] = "C"
    if "retItem" not in esJob:
        esJob["retItem"] = {"id"}
    if "selectedMessage" not in esJob:
        esJob["selectedMessage"] = None
    #如果欲篩選selectedMessage值為True者，
    #設定esJob["selectedMessage"] = [True]
    #esJob["selectedMessage"] = [True]

    #print("esJob",esJob)
    resdataList = []
    jqbody = {
        "query": {
            "bool": {
                "must": [
                    { "bool": {
                        "must": [                            
                            #{
                            #    "match":{
                            #        "itc.rawTypeCode": "05"
                            #        }
                            #    },
                            {
                                "bool":{
                                    "should": [
                                        {
                                            "term":
                                            {"itc.rawTypeCode": "04"}
                                            },
                                        {
                                            "term":
                                            {"itc.rawTypeCode": "05"}
                                            },
                                        {
                                            "term":
                                            {"itc.rawTypeCode": "12"},
                                            },
                                        {
                                            "term":
                                            {"itc.rawTypeCode": "17"}
                                            },
                                        ]
                                    
                                    }
                                },
                            {
                                "match": {
                                    "rawInfo.langCode": esJob["langCode"]
                                    }
                                }
                            ]
                        }
                    }
                ],
                "filter": [
                    {"range": {
                        #"itcDT":{
                        "importDT":{
                            "gte":esJob["startDay"],
                            "lte":esJob["endDay"],
                        }
                    }
                },
            ]
        }
    }
    }
    '''
    if esJob["selectedMessage"] == True:
        if 'should' not in jqbody['query']['bool']:
            jqbody['query']['bool']['should'] = []
        jqbody['query']['bool']['should'].extend(
            [
                {
                    'bool':{
                        'must':[{
                            "exists": {
                                "field": "select"
                                }
                            }]
                        }
                    },                
            ])
    elif esJob["selectedMessage"] == False:
        if 'must_not' not in jqbody['query']['bool']:
            jqbody['query']['bool']['must_not'] = []
        jqbody['query']['bool']['must_not'].append(
            {"exists": {
              "field": "select"
              }
            })
    '''
    #目前selectedMessage為無作用key
    '''
    if esJob["selectedMessage"] is not None:
        jqbody['query']['bool']['filter'].append(
            {'terms':{
                "selectedMessage":[esJob["selectedMessage"]]}
             })
    '''
    if esJob["selectedMessage"] == True:
        jqbody['query']['bool']['must'].append({
            "exists": {
                "field": "ak6.select"
                }
            })
    #print("jqbody",jqbody)
    #time.sleep(5)
    es = Elasticsearch(
        es_tokens['host'],
        http_auth=(es_tokens['user'], es_tokens['password']),
        verify_certs=False
        )
    res =es.search(index=esJob["indexname"],body=jqbody,scroll="2m")
    #for x in res['hits']['hits']:
        #print("item in res",x)    
    sid=res['_scroll_id']
    scroll_size =len(res['hits']['hits'])
    #logging.error(res['hits']['total'])
    #logging.error(scroll_size)
    resdataList = []
    while scroll_size > 0:
        #resdataList.extend(res['hits']['hits'])
        #print('-'*50)
        #print(res['hits']['hits'])
        '''
        itemDict = dict()
        for x in res['hits']['hits']:
            itemDict["id"] = x['_id']
            if "subject" in retItem:
                itemDict["subject"] = x['_source'].get('subject')
            if "content" in retItem:
                itemDict["content"] = x['_source']['rawInfo'].get('content')
            if "isTarget" in retItem:
                userNames = x['_source'].get('userNames',[])
                if len(userNames) > 0:
                    itemDict["isTarget"] = True
                else:
                    itemDict["isTarget"] = False

            resdataList.append(itemDict)
        '''
        
        if esJob["retItem"] == {"id"}:
            resdataList.extend([
                {'id':x['_id']} for x in res['hits']['hits']])
        elif esJob["retItem"] == {"id","subject"}:
            resdataList.extend([
                {'id':x['_id'],
                 'subject':x['_source']['communication'].get('subject')}
                                for x in res['hits']['hits']])
        elif esJob["retItem"] == {"id","content"}:
            resdataList.extend([
                {'id':x['_id'],
                 'content':x['_source']['rawInfo'].get('content')}
                                for x in res['hits']['hits']])
        elif esJob["retItem"] == {"id","subject","content"}:
            resdataList.extend([
                {'id':x['_id'],
                 'subject':x['_source']['communication'].get('subject'),
                 'content':x['_source']['rawInfo'].get('content')}
                                for x in res['hits']['hits']])
        else:
            return []
        #for x in res:
            #print("item in res",x)
        res = es.scroll(scroll_id=sid,scroll="2m")
        
        sid=res['_scroll_id']
        scroll_size=len(res['hits']['hits'])
    return resdataList
if __name__ == '__main__':
    #MongoTest()
    #sqlite3QueryTest()
    from ArtCluESJobTemplate import esJobTemplate
    esJobs = BuildESJobList(esJobTemplate,startDay="20230903",endDay="20240218")
    for esJob in esJobs[:2]:
        DictIndentPrint(esJob)
        
    SQLConcat(sql3FileList=OSWALK("SQLConcatenate"))
