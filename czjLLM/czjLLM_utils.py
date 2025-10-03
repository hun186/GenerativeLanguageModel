from pathlib import Path
import os
import sys

try:
    from utilities.path_utils import init_project_root
except:
    from GenerativeLanguageModel.czjLLM.utilities.path_utils import init_project_root
project_root = init_project_root()
from PackageImport import set_working_dir_to, PackageImporter
PackageImporter.proc()
PGMSubDir = Path(set_working_dir_to("TopicClassification"))


import json
import re
import random
import inspect




import shutil
import argparse


try:
    from czjLLM_utils_key import api_key
    import czjLLM.taskConfig
    from czjLLM.taskConfig import taskSetting
    from czjLLM.taskConfig import *
except:
    from GenerativeLanguageModel.czjLLM.czjLLM_utils_key import api_key
    from GenerativeLanguageModel.czjLLM import taskConfig
    from GenerativeLanguageModel.czjLLM.taskConfig import taskSetting
    from GenerativeLanguageModel.czjLLM.taskConfig import *
#print("taskConfig in L32",taskSetting)
#from utils.utilities import MKDIR

from czjLLM.sql_utils.common import quote_column


from utils.utilities import countdown_pause
from utils.utilities import save_dicts_to_txt

#from job_config import DEFAULT_MODEL
'''
def sanitize_path(path):
    """
    清理路徑中的非法字元，將非法字元替換為下劃線
    """
    # 替換非法字元和不可用的特殊符號
    cleaned_path = re.sub(r'[<>:"/\\|?*]', '_', path)
    # 去掉尾端不必要的斜線或空格
    cleaned_path = cleaned_path.rstrip(' .')
    return cleaned_path

def MKDIR(DirName):
    """
    建立資料夾，若包含非法字元或路徑過長則自動處理
    """
    try:
        # 清理資料夾名稱中的非法字元
        cleaned_dir = sanitize_path(DirName)
        # 若路徑過長，進行裁剪
        if len(cleaned_dir) > 255:
            cleaned_dir = cleaned_dir[:255]
        os.makedirs(cleaned_dir, exist_ok=True)
        print(f"✅ 成功建立資料夾：{cleaned_dir}")
    except Exception as e:
        print(f"❌ 建立資料夾失敗：{cleaned_dir}，錯誤：{e}")
''' 


    

def json_repair_test():
    jsonFN = r'D:/shared/TopicClassification/GenerativeLanguageModel/czjLLM/WorkPool_czjLLM/Prompt/災害應變作業手冊/臺中市北屯區災害應變中心作業手冊_tika/Success/49.txt'
    json_content = open(jsonFN,'rt',encoding='utf-8').read()
    CombCTX,error_mes = combine_json_return(json_content)
    print("CombCTX",CombCTX)
    os.system("pause")

def combine_RAG_chunk_text(source_directory):
    target_directory = f"{source_directory}_combine_text"
    cnt = 0
    for root, _, files in os.walk(source_directory):
        for file in files:
            #省略處理的輸出檔案，避免二次處理，導致報錯。
            if "_combine_text" in root:
                continue
            file_path = os.path.join(root, file)
            if "RAG Chunk" not in file_path:
                #print("continue")
                continue
            relative_path = os.path.relpath(file_path, source_directory)
            target_path = os.path.join(target_directory, relative_path)
            print("handling",file_path)
            with open(file_path,'rt',encoding='utf-8') as f:
                #print("f",f)
                mydic = json.load(f)
            CombCTX = ""
            section_temp = ""
            for term in mydic:
                section = term.get("section","")
                if "content" not in term:
                    print("WARNING! for the following term, there is no content key. Abort this term.")
                    print(term)
                    continue
                content = term["content"]
                if  section != section_temp and not content.startswith(section):
                    CombCTX += (section+"\n")
                    section_temp = section
                CombCTX += (content+"\n\n")
            #CombCTX = '\n'.join([f'{term["section"]}\n{term["content"]}\n' for term in mydic])
            #print("CombCTX",CombCTX)
            #print("os.path.dirname(target_path)",os.path.dirname(target_path))
            os.makedirs(os.path.dirname(target_path),exist_ok=True)
            with open(target_path,'wt',encoding='utf-8') as f:
                f.write(CombCTX)
            cnt += 1
    print(f'{"="*50}\n{Fore.LIGHTGREEN_EX}There are {cnt} files handled for {source_directory}.{Fore.WHITE}\n{"="*50}')

def combine_RAG_chunk_text_subDir(source_directory):
    subdirectories = [os.path.join(source_directory,d) 
                   for d in os.listdir(source_directory) 
                   if os.path.isdir(os.path.join(source_directory, d))]
    for SubDir in subdirectories:
        combine_RAG_chunk_text(SubDir)




def CallLLMAPI_test():
    content = """
    1+1等於幾？
    """
    print("start to run test for CallLLMAPI.")
    On_Premises=False
    response,cost = CallLLMAPI(content)#,On_Premises=On_Premises)
    print(response)
    print("="*50)
    print(response.choices[0].message.content)
    countdown_pause(300)
    
def main():
    #CallLLMAPI_test()
    source_directory = r"D:\shared\TopicClassification\TopicTextCrawler\Books\特定主題\說明指導文件\指導文件\災害應變作業手冊\original\UnTagged\Combine"
    source_directory = r"D:\shared\TopicClassification\GenerativeLanguageModel\czjLLM\RAG_chunks"
    #combine_RAG_chunk_text_subDir(source_directory)
    #把RAG chunks字典分切到多個文字檔。
    #source_directory = r"D:\shared\TopicClassification\GenerativeLanguageModel\czjLLM\RAG_chunks"
    source_directory = r"D:\shared\TopicClassification\GenerativeLanguageModel\czjLLM\LLMSourcePool_Finished\Laws_New"
    save_dicts_to_txt(source_directory)
    #json_repair_test()
    
if __name__ == '__main__':
    main()

    
    