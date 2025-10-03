# GenerativeLanguageModel/czjLLM/modelConfig.py
from importlib import import_module, util

# 聚合所有任務設定的總表
modelSetting = {}

# 想載入的 {模組檔名: 變數名} 對應表（依你的既有命名）
CONFIG_TARGETS = {
    "modelConfig_pri": "modelSetting_pri",
    "modelConfig_ANKInt": "modelSetting_ANKInt",
    "modelConfig_DRN_64": "modelSetting_DRN_64",
    "modelConfig_ANKIso_Fake": "modelSetting_ANKIso_Fake",
    "modelConfig_ANKIso": "modelSetting_ANKIso",
}

# 取得 czjLLM 當前套件名稱（相對匯入時會是 'czjLLM'）
# 若此檔被當作 'czjLLM.modelConfig' 匯入，__package__ == 'czjLLM'
PKG = __package__ or "czjLLM"
BASE_PKG = f"{PKG}.model_configs"  # 一律從套件路徑載入

for module_name, setting_name in CONFIG_TARGETS.items():
    full_name = f"{BASE_PKG}.{module_name}"
    from importlib import import_module, util
    if util.find_spec(full_name) is None:
        continue
    mod = import_module(full_name)
    if not hasattr(mod, setting_name):
        continue

    new_dict = getattr(mod, setting_name)
    for key, new_cfg in new_dict.items():
        if key in modelSetting:
            old_cfg = modelSetting[key]
            merged = dict(old_cfg)  # 先以舊的為基底
            merged.update(new_cfg)  # 後者的欄位覆蓋舊的

            # base_url 特別處理：合併去重
            old_urls = old_cfg.get("base_url", [])
            new_urls = new_cfg.get("base_url", [])
            if isinstance(old_urls, str):
                old_urls = [old_urls]
            if isinstance(new_urls, str):
                new_urls = [new_urls]
            merged["base_url"] = list(dict.fromkeys([*old_urls, *new_urls]))

            modelSetting[key] = merged
            print(f"[ModelConfig] 合併設定：{key}")
        else:
            modelSetting[key] = new_cfg


# 如果沒設環境變數，就做連線檢測
#if os.environ.get("CZJLLM_SKIP_MODEL_PROBE", "").lower() not in ("1", "true", "yes"):
if True:
    #print("start to filter_available_models")
    from .model_configs.model_probe_utils import filter_available_models
    modelSetting = filter_available_models(modelSetting)
#print("modelSetting",modelSetting)