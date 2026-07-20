# -*- coding: utf-8 -*-
"""
llm_caller.py
集中管理 LLM 呼叫（含 Qwen/Qwen3 的 /no_think 判斷），
並提供函式式 API（CallLLMAPI）與物件式封裝（LLMCaller）。

依賴：
- openai>=1.x
- httpx
- czjLLM.prompt_pipeline.prompt_generator.should_disable_think
- czjLLM.prompt_pipeline.prompt_generator.append_no_think_if_applicable
- utils.utilities.tlog（若缺則 fallback 到 print）
"""

from __future__ import annotations

import time
from typing import Any, Dict, Optional, Tuple

import httpx
import inspect

from openai import OpenAI
from openai import APIConnectionError, APITimeoutError, RateLimitError, APIError

try:
    # 專案既有的輕量日誌工具
    from utils.utilities import tlog  # type: ignore
except Exception:
    def tlog(msg: str) -> None:  # 極簡 fallback
        print(msg)


# ===== Qwen /no_think 能力整合 =====
# 經由 prompt_generator 暴露的統一介面，不再硬寫 "qwen"
from czjLLM.prompt_pipeline.prompt_generator import (
    should_disable_think,
    append_no_think_if_applicable,
)
from czjLLM.utilities.llm_call_audit import resolve_context_limit


# ===== httpx 客戶端工廠 =====
def _create_http_client() -> httpx.Client:
    """
    建立共用 httpx.Client（多版相容）：
    - 控制連線上限
    - 合理 timeout
    - 關閉系統 Proxy 與環境變數干擾（避免 192.168.* 被誤導）
    - httpx 0.27 有 proxies=；0.28+ 移除，改用 mounts=
    """
    limits = httpx.Limits(
        max_connections=64,
        max_keepalive_connections=32,
    )

    # 部分舊版 httpx.Timeout 沒有 pool 參數，做個備援
    try:
        timeout = httpx.Timeout(connect=10.0, read=240.0, write=240.0, pool=120.0)
    except TypeError:
        timeout = httpx.Timeout(connect=10.0, read=240.0, write=240.0)

    client_kwargs = dict(
        timeout=timeout,
        limits=limits,
        trust_env=False,  # 不讀取 HTTP(S)_PROXY / NO_PROXY 等環境變數
    )

    # 0.27 及更早：支援 proxies 參數 → 明確給空 dict 代表不使用代理
    # 0.28+：已移除 proxies → 不要帶這個鍵
    try:
        params = inspect.signature(httpx.Client.__init__).parameters
        if "proxies" in params:
            client_kwargs["proxies"] = {}  # 或 None；給 {} 更明確
    except Exception:
        # 安全失敗：若檢查失敗，保持不帶 proxies（相容 0.28+）
        pass

    return httpx.Client(**client_kwargs)


# ===== DeepSeek 成本估算（TWD） =====
def _estimate_cost_twd(response: Any, model: str) -> float:
    """
    以你現有邏輯估算新臺幣成本（DeepSeek）
    - 單位價格（TWD/token）：
        prompt:      4 * 33 / 1e6
        completion: 12 * 33 / 1e6
        prompt cache hit: 上述 prompt 單價 / 8
    """
    model_lower = (model or "").lower()
    if model_lower not in {"deepseek-chat", "deepseek-coder"}:
        return 0.0

    # 安全地取 usage 欄位
    usage = getattr(response, "usage", None)
    if usage is None:
        return 0.0

    prompt_tks = getattr(usage, "prompt_tokens", 0) or 0
    completion_tks = getattr(usage, "completion_tokens", 0) or 0
    prompt_cache_hit_tks = getattr(usage, "prompt_cache_hit_tokens", 0) or 0
    prompt_cache_miss_tks = getattr(usage, "prompt_cache_miss_tokens", 0) or 0

    unit_price_prompt = 4 * 33 / 10**6
    unit_price_completion = 12 * 33 / 10**6
    unit_price_prompt_cache_hit = unit_price_prompt / 8.0

    cost = (
        prompt_cache_hit_tks * unit_price_prompt_cache_hit
        + prompt_cache_miss_tks * unit_price_prompt
        + completion_tks * unit_price_completion
    )
    return float(cost)


def _calc_token_stats(response: Any) -> Tuple[int, int, int]:
    """
    回傳 (prompt_tokens, completion_tokens, total_tokens)，缺省給 0。
    """
    usage = getattr(response, "usage", None)
    if not usage:
        return 0, 0, 0
    p = getattr(usage, "prompt_tokens", 0) or 0
    c = getattr(usage, "completion_tokens", 0) or 0
    total = p + c
    return int(p), int(c), int(total)


# ===== 對外函式：CallLLMAPI =====
def CallLLMAPI(
    content: str,
    model_spec: Optional[Dict[str, Any]] = None,
    api_key: str = "",
    base_url: str = "https://api.deepseek.com",
    model: str = "deepseek-chat",
    max_tokens: int = 8192,
    temperature: float = 1.0,
    NoThinkProcess: bool = True,  # 是否啟用 /no_think 自動附加
    http_client: Optional[httpx.Client] = None,
) -> Tuple[Any, float]:
    """
    呼叫 OpenAI 相容端點的簡化函式。

    參數優先序：model_spec > 顯式參數（api_key/base_url/model）
      - model_spec 可帶：
        - "api_key": str
        - "base_url": str
        - "model_name": str
        - "no_think_suffix": Optional[str]  # 覆寫 /no_think（None=強制不加、"/no_think"=強制加）

    回傳： (response, cost_twd)
    - response：openai.ChatCompletion 物件
    - cost_twd：估算新臺幣成本（僅 DeepSeek chat/coder 會計價，其他為 0）
    """
    model_spec = model_spec or {}

    # 以 model_spec 覆蓋顯式參數
    model = model_spec.get("model_name", model) or model
    base_url = model_spec.get("base_url", base_url) or base_url
    api_key = model_spec.get("api_key", api_key) or api_key

    # /no_think 覆寫（若非 None，會強制採用）
    no_think_override = model_spec.get("no_think_suffix", None)

    # 依能力表決定是否附加 /no_think（已支援 Qwen3 / Qwen2.5 / Qwen2 / 泛 qwen）
    content = append_no_think_if_applicable(
        content=content,
        model_name=(model or "").lower(),
        enabled=NoThinkProcess,
        override_suffix=no_think_override,
    )

    # 建立（或重用）http_client 與 OpenAI 客戶端
    http_client = http_client or _create_http_client()
    client = OpenAI(
        api_key=api_key or "EMPTY",
        base_url=(base_url or "").rstrip("/"),
        http_client=http_client,
    )

    start_ts = time.time()

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "You are a helpful assistant"},
                {"role": "user", "content": content},
            ],
            max_tokens=max_tokens,
            temperature=temperature,
        )
    except (APITimeoutError, APIConnectionError) as e:
        # 讓上游重試機制處理；保留明確錯誤訊息
        raise RuntimeError(f"LLM_CALL_TIMEOUT_OR_CONN: {e}") from e
    except (RateLimitError, APIError):
        # 速率或服務端錯誤交給外層策略重試
        raise

    elapsed = max(time.time() - start_ts, 0.0)
    p_tks, c_tks, total_tks = _calc_token_stats(response)
    tps = (total_tks / elapsed) if elapsed > 0 else float(total_tks)

    cost_twd = _estimate_cost_twd(response, model=model)
    context_limit, context_source = resolve_context_limit(model_spec, response=response)
    if context_limit > 0:
        context_pct = (float(total_tks) / float(context_limit)) * 100.0
        token_line = (
            f"Tokens  In/Out: {p_tks}/{c_tks}  |  Total: {total_tks}"
            f"  |  Context: {context_pct:.2f}% ({total_tks}/{context_limit}, {context_source})"
        )
    else:
        token_line = (
            f"Tokens  In/Out: {p_tks}/{c_tks}  |  Total: {total_tks}"
            "  |  Context: unknown"
        )

    # 簡潔日誌
    tlog(
        "\n".join(
            [
                "~" * 50,
                f"模型：{model}  |  端點：{base_url}",
                token_line,
                f"耗時：{elapsed:.2f}s  |  處理速率：{tps:.2f} tok/s",
                f"新臺幣成本（估）：{cost_twd:.3f} 元",
            ]
        )
    )

    return response, cost_twd


# ===== 物件式封裝：LLMCaller =====
class LLMCaller:
    """
    輕量級包裝器，重用 httpx.Client 與模型設定。
    使用方式：
        caller = LLMCaller(model_spec={"api_key": "...", "base_url": "...", "model_name": "qwen3-..."})
        resp, cost = caller.call("你的提示詞")
    """

    def __init__(
        self,
        model_spec: Optional[Dict[str, Any]] = None,
        *,
        max_tokens: int = 8192,
        temperature: float = 1.0,
        no_think: bool = True,
        http_client: Optional[httpx.Client] = None,
    ) -> None:
        self.model_spec = dict(model_spec or {})
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.no_think = no_think
        self.http_client = http_client or _create_http_client()

        # 預先建 client（若 api_key/base_url 隨時會變，可改為延遲建立）
        api_key = self.model_spec.get("api_key", "") or "EMPTY"
        base_url = (self.model_spec.get("base_url", "") or "").rstrip("/")
        self.client = OpenAI(api_key=api_key, base_url=base_url, http_client=self.http_client)

    def call(self, content: str) -> Tuple[Any, float]:
        """
        執行一次 LLM 呼叫；回傳 (response, cost_twd)。
        內部沿用 CallLLMAPI 的邏輯以保持一致。
        """
        # 為了最大相容、少重複，直接轉呼 CallLLMAPI，但重用既有 http_client
        # （此舉也確保 /no_think、成本估算、日誌等行為完全一致）
        # 註：若你偏好完全使用 self.client，可在此改為 self.client.chat.completions.create 的流程。
        return CallLLMAPI(
            content=content,
            model_spec=self.model_spec,
            api_key=self.model_spec.get("api_key", ""),
            base_url=self.model_spec.get("base_url", ""),
            model=self.model_spec.get("model_name", ""),
            max_tokens=self.max_tokens,
            temperature=self.temperature,
            NoThinkProcess=self.no_think,
            http_client=self.http_client,
        )
