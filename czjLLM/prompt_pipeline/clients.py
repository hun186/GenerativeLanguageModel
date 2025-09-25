# czjLLM/prompt_pipeline/clients.py
from __future__ import annotations
import inspect
import httpx

def build_openai_like_client(model_spec: dict):
    """
    建立 OpenAI 風格 client 的穩健工廠：
    - OpenAI v1.x: 用 httpx.Client 傳 proxy（若需要）
    - 若環境是其它相容庫（暴露 Client 類），用函式簽名動態過濾不支援的參數
    - 最後退回到 openai 0.x 的全域設定
    """
    base_url = model_spec.get("base_url")
    api_key  = model_spec.get("api_key")
    timeout  = model_spec.get("timeout", 60)
    proxies  = model_spec.get("proxies")  # 可無

    try:
        import openai
    except Exception as e:
        raise RuntimeError("openai 套件未安裝") from e

    # v1.x 走這裡（推薦路徑）
    if hasattr(openai, "OpenAI"):
        http_client = httpx.Client(proxies=proxies, timeout=timeout) if proxies else None
        # 不把 proxies 丟給 OpenAI，改由 http_client 承接
        return openai.OpenAI(base_url=base_url, api_key=api_key, http_client=http_client, timeout=timeout)

    # 某些相容庫暴露的是 Client 類；用簽名濾掉不支援的參數
    if hasattr(openai, "Client"):
        ctor = openai.Client
        params = dict(base_url=base_url, api_key=api_key, timeout=timeout, proxies=proxies)
        sig = inspect.signature(ctor.__init__)
        safe = {k: v for k, v in params.items() if k in sig.parameters and v is not None}
        return ctor(**safe)

    # 最後退路：openai 0.x
    openai.api_base = base_url
    openai.api_key  = api_key
    return openai
