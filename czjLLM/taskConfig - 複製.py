#GenerativeLanguageModel/czjLLM/taskConfig.py
import os
import importlib
#from utils.utilities import removeStrSuffix
#from utils.utilities import countdown_pause
#if os.path.isfile("GenerativeLanguageModel/czjLLM/pre_trans_ak.py"):
#    from GenerativeLanguageModel.czjLLM.pre_trans_ak import pre_trans

'''
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]  # TopicClassification
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
'''
taskSetting = {}

config_files = [
    ("taskConfig_ANKInt", "taskSetting_ANKInt"),
    ("taskConfig_pri", "taskSetting_pri"),
    ("taskConfig_ANKIso", "taskSetting_ANKIso"),
    ("taskSetting_Enrichment","taskSetting_Enrichment"),
    ("taskSetting_NewsReduce", "taskSetting_NewsReduce"),
]

for module_name, setting_name in config_files:
    #file_path = f"GenerativeLanguageModel/czjLLM/{module_name}.py"
    file_path = f"czjLLM/task_configs/{module_name}.py"
    if os.path.isfile(file_path):
        #full_module_name = f"GenerativeLanguageModel.czjLLM.{module_name}"
        full_module_name = f"czjLLM.task_configs.{module_name}"
        module = importlib.import_module(full_module_name)
        taskSetting.update(getattr(module, setting_name))
