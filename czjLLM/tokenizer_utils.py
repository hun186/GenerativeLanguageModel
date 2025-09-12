import os
from czjLLM.taskConfig import taskSetting
from DatasetConverter.sampleHandler import tokenization_wrap
from utils.utilities import tlog

class TokenizerWrapper:
    def __init__(self, model_name: str, task: str,
                 base_path="GenerativeLanguageModel/czjLLM/tokenizers",
                 max_tokens: int = None):
        self.model_name = model_name.lower()
        self.task = task
        self.base_path = base_path
        self.model_dir = self._resolve_model_dir()
        self.max_input_tokens = taskSetting.get(task, {}).get("InputCutLen", 3000)
        self.max_tokens = max_tokens or 8192  # 預設 output token 上限

    def _resolve_model_dir(self) -> str:
        model_tokenizer_map = {
            "qwen2.5": "qwen2.5_tokenizer",
            "qwen3": "qwen3_tokenizer",
            "deepseek-v3": "deepseek_v3_tokenizer",
            "deepseek": "deepseek_v3_tokenizer",  # fallback 指定
        }
        for key, folder in model_tokenizer_map.items():
            if key in self.model_name:
                return os.path.join(self.base_path, folder)
        return os.path.join(self.base_path, "deepseek_v3_tokenizer")


    def tokenize(self, text: str, adjust: bool = True, max_tokens: int = None, debug: bool = False) -> dict:
        max_tokens = max_tokens or self.max_tokens
        nTokensToWrap = int(self.max_input_tokens * (max_tokens / 4096)) if adjust else self.max_input_tokens
    
        print(f"📦 tokenizer path: {self.model_dir}")
        print(f"🧠 task: {self.task}")
        print(f"🔢 max tokens to wrap: {nTokensToWrap}")
    
        tokensWrap = tokenization_wrap(
            context=text,
            modelDir=self.model_dir,
            ReTks=True,
            debug=debug,
            nTokensToWrap=nTokensToWrap
        )
    
        print(f"✅ ctxCut token lens: {[len(x) for x in tokensWrap['ctxCut']]}")
        print(f"✅ ReTks token lens: {[len(x) for x in tokensWrap['ReTks']]}")
        return tokensWrap
