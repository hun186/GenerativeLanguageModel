import os
import sys
import re 
import shutil
from pathlib import PureWindowsPath, PurePosixPath
try:
    from utils.MP_utils import MPlogger
except:
    from .MP_utils import MPlogger

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



class fileNameNormalizer:
    def proc(fileName):
        return str(fileName).replace("\\","/")

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

def clean_path_end_dots(path):
    # 以正確的路徑分隔符拆分路徑
    parts = path.replace("\\", "/").split("/")
    # 去除每個部分結尾的多餘點
    cleaned_parts = [part.rstrip(".") for part in parts]
    # 使用作業系統適合的分隔符重新組合路徑
    cleaned_path = os.path.join(*cleaned_parts)
    return cleaned_path

'''
def clean_path_end_chars_OLD(path):
    # 以正確的路徑分隔符拆分路徑，處理混合分隔符的情況
    parts = path.replace("\\", "/").split("/")
    # 去除每個部分結尾的多餘點、空白及斜線
    cleaned_parts = [part.rstrip(". /\\") for part in parts if part]
    # 使用作業系統適合的分隔符重新組合路徑
    cleaned_path = os.path.join(*cleaned_parts)
    return cleaned_path
'''

'''
def clean_path_end_chars_OLD_2(path: str) -> str:
    """
    安全清理路徑：
    - 保留磁碟根 (例如 D:\) 或 UNC 前綴 (\\server\share\)
    - 僅修剪中間段落尾端的空白與點（Windows 不允許尾點/空白）
    - 不會把 'D:\...' 變成 'D:...'
    - 回傳 OS 正規化後的字串
    """
    if sys.platform.startswith("win"):
        P = PureWindowsPath
    else:
        P = PurePosixPath

    p = P(path)
    drive = p.drive    # 例: 'D:' 或 '\\\\server\\share'
    root  = p.root     # 例: '\\' 或 '/' 或 對 UNC 也是 '\\'

    # 只處理中間段落，不動 drive/root
    mid_parts = [seg.rstrip(' .\\/') for seg in p.parts
                 if seg not in (drive, root) and seg not in ('', '.')]

    tail = os.path.join(*mid_parts) if mid_parts else ''
    prefix = (drive + root) if (drive or root) else ''

    cleaned = os.path.join(prefix, tail) if prefix else tail
    return os.path.normpath(cleaned)
'''

def clean_path_end_chars(path: str) -> str:
    """
    安全清理路徑（跨平台）：
    - Windows：修剪每個段落尾端的空白與點（符合 WinFS 規則），保留磁碟/UNC 前綴。
    - POSIX：保留根（/ 或 //），不改動各段內容（避免誤剪有效的尾端字元）。
    - 最後回傳對應平臺的正規化路徑。
    """
    if not isinstance(path, str) or path == "":
        return path  # 原樣返回

    # 統一分隔符，讓 mixed separator（/、\）可跨平台處理
    unified = path.replace("\\", "/")

    # 保留 Windows drive prefix（例如 C:）
    m = re.match(r"^[A-Za-z]:", unified)
    drive = m.group(0) if m else ""
    rest = unified[len(drive):]

    has_root = rest.startswith("/")
    rest = rest.lstrip("/")

    parts = []
    for seg in rest.split("/"):
        if seg in ("", "."):
            continue
        cleaned_seg = seg.rstrip(" .")
        if cleaned_seg in ("", "."):
            continue
        parts.append(cleaned_seg)

    tail = "/".join(parts)

    if drive and has_root:
        cleaned = f"{drive}/{tail}" if tail else f"{drive}/"
    elif drive:
        cleaned = f"{drive}/{tail}" if tail else drive
    elif has_root:
        cleaned = f"/{tail}" if tail else "/"
    else:
        cleaned = tail

    cleaned = cleaned.replace("/", os.path.sep)
    return os.path.normpath(cleaned)

def ShortenFN(FN):
    #LeftFNLen = min(100,len(getPathFromFN(FN)))
    print("getMFNFromFN(FN)",getMFNFromFN(FN))
    LeftFN = ('{}.{}').format(
        getMFNFromFN(FN)[:100],
        pathSpliter.proc(FN)[-1].rpartition(".")[-1])
    return getPathFromFN(FN)+PathSEP(FN)+LeftFN
    
def getPathFromFN(FN, removeDrive = False):
    pathList = pathSpliter.proc(FN)[:-1]
    #Drive = ""
    if removeDrive == True:
        if re.match("^[A-Z,a-z]:$",pathList[0]):
            #Drive = pathList[0]
            pathList = pathList[1:]
    res = PathSEP(FN).join(pathList)
    #res = re.sub("^[A-Z,a-z]:$","",res)
    return res

def getFileDirFromFN(FN):
    r'''
    e.g: known_pictures\Hong Kong\artist\Aaron Kwok[3].jpg => known_pictures\Hong Kong\artist
    '''
    FN = fileNameNormalizer.proc(fileName = FN)
    FileDir = FN.rpartition("/")[0]
    if FileDir == "":
        FileDir = "./"
    return FileDir


def getMFNFromFN(FN):
    r'''
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
    r'''
    e.g: known_pictures\Hong Kong\artist\Aaron Kwok[3].jpg => Aaron Kwok[3].jpg
    '''
    try:
        return os.path.basename(FN)
    except Exception as e:
        MES = f"When applying getFNFromFullPath to {FN}, the following error occurs:\n{e}"
        MPlogger().logW(MES, logFile="getFNFromFullPathError.log")
        return None

    
def getFNExtFromFullPath(FN,lower = False):
    r'''
    e.g: known_pictures\Hong Kong\artist\Aaron Kwok[3].jpg => jpg
    '''
    #os.path.splitext(x)[1][1:] #".txt" -> "", which is not as expected!
    Ext = getFNFromFullPath(FN).rpartition(".")[2]
    if lower is True:
        return Ext.lower()
    else:
        return Ext

def getSubdirectory(ROOTPATH = "./"):
    #print("ROOTPATH",ROOTPATH)
    #print("In get Subdir,os.listdir(ROOTPATH)",os.listdir(ROOTPATH))
    subdirectories = [
        d for d in os.listdir(ROOTPATH) 
        if os.path.isdir(os.path.join(ROOTPATH, d))]
    return subdirectories
    
def InsertDirnameToFN(FN, insPos = 0, insDirname = ""):
    pathList = pathSpliter.proc(FN)
    pathList.insert(insPos,insDirname)
    res = PathSEP(FN).join(pathList)
    #res = re.sub("^[A-Z,a-z]:$","",res)
    return res

def AppendedMFN(FN,appendStr = "", includeOriDir= True):
    MFN = getMFNFromFN(FN)+appendStr

    #result = MFN+"."+FN.split(PathSEP(FN))[-1].rpartition(".")[2]
    result = MFN+"."+pathSpliter.proc(FN)[-1].rpartition(".")[2]
    if includeOriDir == True:
        #result = PathSEP(FN).join(FN.split(PathSEP(FN))[:-1]+[result])
        result = PathSEP(FN).join(pathSpliter.proc(FN)[:-1]+[result])

    return result


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
        IlleagalMapDict["&"] = r"\&"
        IlleagalMapDict["%"] = r"\%"
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

def find_similar_directory(directory):
    """
    檢測某個目錄是否存在，如果不存在，則檢測上一層目錄下是否有其他以該目錄開頭的子目錄。

    :param directory: 要檢測的目錄
    :return: 如果找到相似的目錄，則返回該目錄；否則返回 None
    """
    if os.path.exists(directory):
        return directory

    # 獲取目錄名稱和上一層目錄
    dir_name = os.path.basename(directory)
    parent_dir = os.path.dirname(directory)

    # 檢測上一層目錄下是否有其他以該目錄開頭的子目錄
    if os.path.exists(parent_dir):
        for item in os.listdir(parent_dir):
            item_path = os.path.join(parent_dir, item)
            if os.path.isdir(item_path) and item.startswith(dir_name):
                return item_path

    return None

def getFastAPIStaticDir():
    return "fastAPI/static"

def DirReplace(FilePath,SrcDir,DesDir):
    FilePath = fileNameNormalizer.proc(FilePath)
    SrcDir = fileNameNormalizer.proc(SrcDir)
    DesDir = fileNameNormalizer.proc(DesDir)
    return FilePath.replace(SrcDir,DesDir)



def BackupAndDelFile(
        SrcDir,DesDir,
        #BackFNrePat = ".*",
        BackFNrePatList = [".*"],
        #delete=True,
        ):
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
            #print("~"*50)
            #print("src,",file)
            des = DirReplace(FilePath=file,SrcDir=SrcDir,DesDir=DesDir)
            #print("getPathFromFN(des)",getPathFromFN(des))
            MKDIR(getPathFromFN(des))
            #print("os.path.isdir(getPathFromFN(des))",os.path.isdir(getPathFromFN(des)))
            #print("os.path.isdir",os.path.isdir(r"D:shared/TopicClassification/WTWorkPool/WT1/datasetDB"))
            #print("os.path.isdir(getPathFromFN(des).replace('datasetDB','datasetDB123')",os.path.isdir(getPathFromFN(des).replace('datasetDB','datasetDB123')))
            shutil.move(file, des)
    shutil.rmtree(SrcDir)
      
def remove_empty_dirs(root_dir):
    for dirpath, dirnames, filenames in os.walk(root_dir, topdown=False):
        if not dirnames and not filenames:  # 檢查是否為空目錄
            os.rmdir(dirpath)  # 移除空目錄
            print(f"Removed empty directory: {dirpath}")
            # 遞迴向上檢查父目錄是否也變成空目錄
            parent_dir = os.path.dirname(dirpath)
            while parent_dir != root_dir and not os.listdir(parent_dir):
                os.rmdir(parent_dir)
                print(f"Removed empty parent directory: {parent_dir}")
                parent_dir = os.path.dirname(parent_dir)

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

def safe_move(src, dst, retries=5, delay=0.05):
    MKDIR(getPathFromFN(dst))
    for i in range(retries):
        try:
            shutil.move(src, dst)
            return
        except Exception as e:
            if i == retries - 1:
                raise
            time.sleep(delay)


def smart_detect_path(PGMSubDir, path):
    """嘗試判斷路徑是相對還是絕對路徑，找出真實存在的路徑"""
    if not path:
        return None
    path = os.path.expanduser(path)
    if os.path.isfile(path):
        return path
    alt_path = os.path.join(PGMSubDir, path)
    if os.path.isfile(alt_path):
        return alt_path
    # 若 path 已含專案根目錄名稱（例如在專案根下又寫了 "GenerativeLanguageModel/..."），
    # 會造成重複拼接：<PGMSubDir>/GenerativeLanguageModel/...，此處自動去重再嘗試一次。
    project_name = os.path.basename(os.path.normpath(PGMSubDir or ""))
    normalized_path = path.replace("\\", "/")
    if project_name and normalized_path.startswith(project_name + "/"):
        trimmed_rel = normalized_path[len(project_name) + 1:]
        trimmed_path = os.path.join(PGMSubDir, trimmed_rel)
        if os.path.isfile(trimmed_path):
            return trimmed_path
    return None


def is_sqlite_path(server_value):
    if not isinstance(server_value, str):
        return False

    # 若是加了 r"" 或含引號的輸入，要去除引號
    server_value = server_value.strip().strip('"').strip("'")

    # 合理副檔名（可依需求擴充）
    sqlite_extensions = (".db", ".sqlite", ".sqlite3", ".sql3", ".s3db")

    # 是現存的檔案 + 副檔名正確
    if os.path.isfile(server_value) and server_value.lower().endswith(sqlite_extensions):
        return True

    # 即使檔案不存在，只要副檔名合理，也可能是 SQLite
    if not os.path.exists(server_value) and server_value.lower().endswith(sqlite_extensions):
        return True

    return False
