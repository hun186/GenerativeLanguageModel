#model_configs/modelConfig_ANKInt.py
import os

common_base_urls = [
    "http://192.168.0.134:11435/v1",  #為了控出一個給ollma持續使用，可mark，以便代理人開發期間運用。
    "http://192.168.0.134:11436/v1"
]
common_api_key = os.getenv("CZJLLM_ANKINT_API_KEY", "EMPTY")

modelSetting_ANKInt = {}

models = [
    #("qwen3:32b", [4, 8, 16, 32, 64, 128], {
    #    16: {"recommend_task": ["CLASS EXT"], "nProcess": 4},
    #    32: {"recommend_task": ["CLASS EXT"], "nProcess": 4},
    #}),
    #("qwen3:30b-a3b", [4, 8, 16, 32, 64, 128], {
    #    16: {"nProcess": 4},
    #    32: {"nProcess": 4},
    #}),
    ("qwen3.8:latest", [4, 8, 16, 32, 64, 128], {
        16: {"recommend_task": ["CLASS EXT"], "nProcess": 4},
        32: {"recommend_task": ["CLASS EXT"], "nProcess": 4},
    }),
    ("gpt-oss:latest", [4, 8, 16, 32, 64, 128], {
        32: {"nProcess": 4},
    }),
    ("gpt-oss:120b", [4, 8, 16, 32, 64, 128], {
        32: {"nProcess": 4},
    }),   
    ("nemotron-3-super:latest", [4, 16, 32, 64, 128], {
        32: {"nProcess": 2},
    }), 
    ("nemotron-3-nano:30b", [4, 16, 32, 64, 128], {
        32: {"nProcess": 2},
    }),
]

for model_prefix, context_lengths_k, extras in models:
    for context_k in context_lengths_k:
        if model_prefix in ["gpt-oss:latest","gpt-oss:120b"]:
            quan_method = "MXFP4"
        else:
            quan_method = "q4"
        key = f"{model_prefix}-ctx-{context_k}k-premises-{quan_method}"
        base_urls = common_base_urls.copy()

        # 確保包含兩個 IP
        #if "http://192.168.0.134:11435/v1" in base_urls and \
        #   "http://192.168.0.134:11436/v1" not in base_urls:
        #    base_urls.append("http://192.168.0.134:11436/v1")

        setting = {
            "model_name": f"{model_prefix}-{context_k}k",
            "base_url": base_urls,
            "api_key": common_api_key,
            "num_ctx": context_k * 1024,
            "on_premises": True,
            **extras.get(context_k, {})  # 合併額外設定（若有）
        }

        modelSetting_ANKInt[key] = setting
#print("modelSetting_ANKInt.keys()",modelSetting_ANKInt.keys())
