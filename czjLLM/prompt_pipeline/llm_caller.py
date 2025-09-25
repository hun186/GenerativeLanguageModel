from openai import OpenAI
import requests
import random
import time

#from utils.utilities import is_connected
from utils.utilities import tlog

from czjLLM.prompt_pipeline.prompt_generator import should_disable_think
from czjLLM.prompt_pipeline.clients import build_openai_like_client

'''
class LLMCaller:
    def __init__(self, model_spec: dict, on_premises=False, max_tokens=4096):
        self.model_spec = model_spec
        self.on_premises = on_premises
        self.max_tokens = max_tokens
        self.client = None
        self.api_key = model_spec.get("api_key")
        self.base_url = model_spec.get("base_url")
        self.model = model_spec.get("model_name")

        if self.on_premises:
            self.base_url = "http://192.168.0.134:11434/v1" if is_connected() else "http://199.9.208.12:11434/v1"

        self.client = OpenAI(api_key=self.api_key, base_url=self.base_url)

    def call(self, prompt: str):
        if should_disable_think(self.model.lower()) and not prompt.strip().endswith("/no_think"):
            prompt += "\n/no_think"

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": "You are a helpful assistant"},
                {"role": "user", "content": prompt},
            ],
            max_tokens=self.max_tokens,
            temperature=1,
            stream=False
        )
        return response
'''

def CallLLMAPI(content,
               model_spec=dict(),
               #api_key=api_key,
               api_key="",
               base_url="https://api.deepseek.com",
               model="deepseek-chat",
               max_tokens=4096,
               temperature=1,
               #On_Premises=False,
               NoThinkProcess=True
               ):
    #print("model_spec",model_spec)
    #if max_tokens > 4096 and model in ["deepseek-chat","deepseek-coder"]:
        #base_url="https://api.deepseek.com/beta"

    # 根據 `model_spec` 提供的參數設置 `base_url` 和 `api_key`
    model = model_spec.get("model_name", model)
    base_url = model_spec.get("base_url", base_url)
    api_key = model_spec.get("api_key", api_key)

    # 記錄開始時間
    start_time = time.time()
    #print("model_spec in CallLLMAPI",model_spec)
    
    # 根據模型與 NoThinkProcess 判斷是否附加 /no_think
    model_lower = model.lower() if isinstance(model, str) else ""
    if NoThinkProcess and should_disable_think(model_lower):
        if not content.strip().endswith("/no_think"):
            content = content.rstrip() + "\n/no_think"
    
    # ★ 關鍵：用工廠建立 client（不會把 proxies 丟進不接受的 ctor）
    print("Start to build client in CallLLMAPI wtih build_openai_like_client")
    print("base_url", base_url)
    #client = OpenAI(api_key=api_key, base_url=base_url)
    client = build_openai_like_client({
        "base_url": base_url,
        "api_key": api_key,
        # "proxies": model_spec.get("proxies")  # 如需代理再開，否則先省略
        "timeout": model_spec.get("timeout", 60),
    })
    print("Success to build client")
    
    print("Success to build client")
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": "You are a helpful assistant"},
            {"role": "user", "content": content},
        ],
        max_tokens=max_tokens,
        stream=False,
        temperature=temperature
    )
    print("Success to get response")
    # 計算請求處理時間
    end_time = time.time()
    elapsed_time = end_time - start_time  # 經過的時間（秒）
    
    n_prompt_tks = response.usage.prompt_tokens
    n_completion_tks = response.usage.completion_tokens
    total_tokens = n_prompt_tks + n_completion_tks
    
    
    # 計算每秒處理的 token 數
    if elapsed_time > 0:
        tokens_per_second = total_tokens / elapsed_time
    else:
        tokens_per_second = total_tokens  # 當時間為 0 時，假設處理非常快
        
    if model in ["deepseek-chat","deepseek-coder"]:
        n_prompt_cache_hit_tks = response.usage.prompt_cache_hit_tokens
        n_prompt_cache_miss_tks = response.usage.prompt_cache_miss_tokens    
        unit_price_prompt = 4*33/10**6
        unit_price_prompt_cache_hit = unit_price_prompt/8
        unit_price_prompt_cache_miss = unit_price_prompt
        unit_price_completion = 12*33/10**6
        cost = n_prompt_cache_hit_tks*unit_price_prompt_cache_hit+n_prompt_cache_miss_tks*unit_price_prompt_cache_miss+n_completion_tks*unit_price_completion
    else:
        n_prompt_cache_hit_tks = 0
        cost = 0
        
    # 打印資訊
    MES =  (
        f"{'~' * 50}\n"
        f"使用模型為 {model}，端口：{base_url}\n"
        f"輸入 token 數: {n_prompt_tks}，輸出 token 數: {n_completion_tks}\n"
        f"總共處理的 token 數: {total_tokens}\n"
        f"耗時: {elapsed_time:.2f} 秒\n"
        f"每秒處理 token 數: {tokens_per_second:.2f} tokens/sec\n"
        f"消耗費用為新臺幣: {cost:.3f} 元\n"
        )
    print(MES)
    return response, cost