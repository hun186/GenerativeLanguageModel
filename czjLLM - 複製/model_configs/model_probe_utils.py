# GenerativeLanguageModel/czjLLM/model_configs/model_probe_utils.py
import json
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    import requests
    HAVE_REQUESTS = True
except ImportError:
    HAVE_REQUESTS = False
    import urllib.request, urllib.error


def _headers(api_key: str | None):
    h = {"Content-Type": "application/json"}
    if api_key:
        h["Authorization"] = f"Bearer {api_key}"
    return h


def _http_get(url, headers=None, timeout=2.0):
    if HAVE_REQUESTS:
        try:
            r = requests.get(url, headers=headers or {}, timeout=timeout)
            return r.status_code, r.text
        except Exception as e:
            return None, str(e)
    else:
        req = urllib.request.Request(url, headers=headers or {})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.getcode(), resp.read().decode("utf-8", errors="ignore")
        except urllib.error.URLError as e:
            return None, str(e)


def _http_post(url, headers=None, data=None, timeout=3.0):
    body = json.dumps(data or {}).encode("utf-8")
    if HAVE_REQUESTS:
        try:
            r = requests.post(url, headers=headers or {}, data=body, timeout=timeout)
            return r.status_code, r.text
        except Exception as e:
            return None, str(e)
    else:
        req = urllib.request.Request(url, data=body, headers=headers or {}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.getcode(), resp.read().decode("utf-8", errors="ignore")
        except urllib.error.URLError as e:
            return None, str(e)


def _probe_list_models(base_url: str, api_key: str | None, model_name: str) -> bool:
    url = base_url.rstrip("/") + "/models"
    code, text = _http_get(url, headers=_headers(api_key))
    if not code or code >= 500:
        return False
    try:
        data = json.loads(text)
    except Exception:
        return False
    items = []
    if isinstance(data, dict) and "data" in data and isinstance(data["data"], list):
        items = data["data"]
    elif isinstance(data, list):
        items = data
    for it in items:
        if isinstance(it, str) and it == model_name:
            return True
        if isinstance(it, dict):
            if it.get("id") == model_name or it.get("name") == model_name or it.get("model") == model_name:
                return True
    return False


def _probe_chat_completion(base_url: str, api_key: str | None, model_name: str) -> bool:
    url = base_url.rstrip("/") + "/chat/completions"
    payload = {"model": model_name, "messages": [{"role": "user", "content": "ping"}], "max_tokens": 1}
    code, text = _http_post(url, headers=_headers(api_key), data=payload)
    if not code:
        return False
    if 200 <= code < 300:
        return True
    try:
        data = json.loads(text)
    except Exception:
        return False
    msg = (data.get("error", {}).get("message") or "").lower() if isinstance(data, dict) else ""
    if "unknown model" in msg or "model not found" in msg or "no such model" in msg:
        return False
    return True


def _probe_one(base_urls: list[str] | str, api_key: str | None, model_name: str):
    if isinstance(base_urls, str):
        base_list = [base_urls]
    else:
        base_list = list(dict.fromkeys(base_urls))
    ok_urls = []
    for b in base_list:
        if _probe_list_models(b, api_key, model_name) or _probe_chat_completion(b, api_key, model_name):
            ok_urls.append(b)
    return bool(ok_urls), ok_urls


def filter_available_models(model_setting: dict, max_workers: int = 8, verbose: bool = False) -> dict:
    """
    只保留至少一個 base_url 可通的模型
    :param model_setting: 所有模型設定字典
    :param max_workers:   同時探測的最大執行緒數
    :param verbose:       是否輸出過程訊息
    """
    results = {}
    futures = {}
    total = len(model_setting)
    if verbose:
        print(f"[ModelProbe] 開始檢測 {total} 個模型設定，並行 {max_workers} 執行緒…")

    from concurrent.futures import ThreadPoolExecutor, as_completed
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        for k, cfg in model_setting.items():
            base = cfg.get("base_url")
            api_key = cfg.get("api_key")
            model_name = cfg.get("model_name") or cfg.get("model")
            if not base or not model_name:
                if verbose:
                    print(f"  - 跳過 {k}：缺少 base_url 或 model_name")
                continue
            futures[ex.submit(_probe_one, base, api_key, model_name)] = (k, cfg)

        for fut in as_completed(futures):
            k, cfg = futures[fut]
            try:
                ok, ok_urls = fut.result()
            except Exception as e:
                ok, ok_urls = False, []
                if verbose:
                    print(f"  - {k} 測試時發生錯誤: {e}")
            if ok:
                new_cfg = dict(cfg)
                new_cfg["base_url"] = ok_urls
                results[k] = new_cfg
                if verbose:
                    print(f"  ✔ 可用：{k} → {ok_urls}")
            else:
                if verbose:
                    print(f"  ✘ 不可用：{k}")

    if verbose:
        print(f"[ModelProbe] 完成：成功 {len(results)}/{total} 個模型。")
    return results
