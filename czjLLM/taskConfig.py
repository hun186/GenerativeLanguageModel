# GenerativeLanguageModel/czjLLM/taskConfig.py
from importlib import import_module, util

# 聚合所有任務設定的總表
taskSetting = {}

# 想載入的 {模組檔名: 變數名} 對應表（依你的既有命名）
CONFIG_TARGETS = {
    "taskConfig_ANKInt": "taskSetting_ANKInt",
    "taskConfig_pri": "taskSetting_pri",
    "taskConfig_ANKIso": "taskSetting_ANKIso",
    "taskSetting_Enrichment": "taskSetting_Enrichment",
    "taskSetting_NewsReduce": "taskSetting_NewsReduce",
    "taskSetting_MenuAnalysis": "taskSetting_MenuAnalysis",
}

# 取得 czjLLM 當前套件名稱（相對匯入時會是 'czjLLM'）
# 若此檔被當作 'czjLLM.taskConfig' 匯入，__package__ == 'czjLLM'
PKG = __package__ or "czjLLM"
BASE_PKG = f"{PKG}.task_configs"  # 一律從套件路徑載入

for module_name, setting_name in CONFIG_TARGETS.items():
    full_name = f"{BASE_PKG}.{module_name}"
    # 只用 importlib 的模組探測，不碰檔案系統與 CWD
    if util.find_spec(full_name) is None:
        continue
    mod = import_module(full_name)
    if hasattr(mod, setting_name):
        taskSetting.update(getattr(mod, setting_name))
