import os
import importlib
#from PackageImport import set_working_dir_to
# 執行時自動設定工作目錄至 TopicClassification 目錄
#PGMSubDir = set_working_dir_to("TopicClassification")
#from PackageImport import PackageImporter
#PackageImporter.proc()
modelSetting = {}

config_files = [
    ("modelConfig_ANKInt", "modelSetting_ANKInt"),
    ("modelConfig_pri", "modelSetting_pri"),
    ("modelConfig_DRN_64", "modelSetting_DRN_64"),
]

for module_name, setting_name in config_files:
    #file_path = f"GenerativeLanguageModel/czjLLM/{module_name}.py"
    file_path = f"czjLLM/{module_name}.py"
    #print("os.getcwd()",os.getcwd())
    #print("file_path",file_path)
    if os.path.isfile(file_path):
        #full_module_name = f"GenerativeLanguageModel.czjLLM.{module_name}"
        full_module_name = f"czjLLM.{module_name}"
        module = importlib.import_module(full_module_name)
        modelSetting.update(getattr(module, setting_name))
        #print("modelSetting",modelSetting)