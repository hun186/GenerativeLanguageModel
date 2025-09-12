from openai import OpenAI
import requests
import random

from utils.utilities import is_connected

from prompt_pipeline.prompt_generator import should_disable_think

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
    

def CallLLMAPI(content,
               model_spec=dict(),
               #api_key=api_key,
               api_key="",
               base_url="https://api.deepseek.com",
               model="deepseek-chat",
               max_tokens=4096,
               temperature=1,
               On_Premises=False,
               NoThinkProcess=True
               ):
    #print("model_spec",model_spec)
    if max_tokens > 4096 and model in ["deepseek-chat","deepseek-coder"]:
        base_url="https://api.deepseek.com/beta"
    
    if On_Premises == True:
        base_url="http://192.168.0.134:11434/v1" if is_connected() else "http://199.9.208.12:11434/v1"
        root_url = base_url.rsplit("/v1", 1)[0]# 拿掉 /v1，保留根網址
        #tags_url = f"{root_url}/api/tags"
        #name:上下文長度
        #4k:4400,8k:8700,13k:14400,16k:17600
        modelList = requests.get(f"{root_url}/api/tags").json().get("models", [])
        # 取出模型名稱
        model_names = {m["name"] for m in modelList}
        
        # 預設候選清單（依優先順序）
        candidates = ["qwen3:32b-ctx-32k-premises-q4", "gpt-oss:latest-ctx-32k-premises-MXFP4", "qwen3:30b-a3b-32k", "qwen2.5-32k"]
        
        # 找到第一個存在於模型清單中的模型
        model = next((m for m in candidates if m in model_names), None)
        api_key = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpZCI6IjIyYzIzYWVkLWM4YzktNGZhYS1hNGRkLTg1NGNlZDg0YTE3ZCJ9.zP5xKqCemX2J3GFra03jMYPngipCbCUfFfIUyO96JOQ"
        
    if model_spec != dict():
        
        model = model_spec["model_name"]
        if isinstance(model_spec["base_url"],str):
            base_url = model_spec["base_url"]
        elif isinstance(model_spec["base_url"],list):
            base_url = random.choice(model_spec["base_url"])
        api_key = model_spec["api_key"]
    
    # 根據模型與 NoThinkProcess 判斷是否附加 /no_think
    model_lower = model.lower() if isinstance(model, str) else ""
    if NoThinkProcess and should_disable_think(model_lower):
        if not content.strip().endswith("/no_think"):
            content = content.rstrip() + "\n/no_think"
            
    client = OpenAI(api_key=api_key, base_url=base_url)
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
    #print("response @ Call",response)
    n_prompt_tks = response.usage.prompt_tokens
    n_completion_tks = response.usage.completion_tokens
    if model in ["deepseek-chat","deepseek-coder"]:
        n_prompt_cache_hit_tks = response.usage.prompt_cache_hit_tokens
        n_prompt_cache_miss_tks = response.usage.prompt_cache_miss_tokens    
        unit_price_prompt = 0.14*33/10**6
        unit_price_prompt_cache_hit = unit_price_prompt/10
        unit_price_prompt_cache_miss = unit_price_prompt
        unit_price_completion = 0.28*33/10**6
        cost = n_prompt_cache_hit_tks*unit_price_prompt_cache_hit+n_prompt_cache_miss_tks*unit_price_prompt_cache_miss+n_completion_tks*unit_price_completion
    else:
        n_prompt_cache_hit_tks = 0
        cost = 0
    #print("response",response)
    print("~"*50)
    print(f"使用模型為{model}，端口：{base_url}")
    print((f"輸入token數:{n_prompt_tks}，\n"
           f"內含緩存命中輸入token數:{n_prompt_cache_hit_tks}，\n"
          f"輸出token數:{n_completion_tks}，\n"
          f"耗用費用為新臺幣{cost:.3f}元。"))
    
    return response,cost