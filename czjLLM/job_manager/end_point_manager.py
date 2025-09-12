import json
import os
import requests
from urllib.parse import urlparse

# 設定檔的預設路徑
DEFAULT_END_POINT_CONFIG_FILE = "GenerativeLanguageModel/czjLLM/infrastructure/end_point_config.json"

def is_end_point_available(url, verbose=False):
    """
    檢查給定的 Ollama 端點是否可以連接。
    先檢查根網域端點是否可用，然後確認 Ollama 是否運行。
    
    :param url: 要檢查的完整端點 URL
    :param verbose: 是否顯示詳細訊息，預設為 False
    :return: 如果連接成功並且 Ollama 正在運行，返回 True；否則返回 False
    """
    try:
        # 解析 URL，獲取主網域部分
        parsed_url = urlparse(url)
        root_url = f"{parsed_url.scheme}://{parsed_url.hostname}:{parsed_url.port}" if parsed_url.port else f"{parsed_url.scheme}://{parsed_url.hostname}"

        if verbose:
            print(f"檢查根網域: {root_url}")
        
        # 嘗試連接到根網域端點
        response = requests.get(root_url, timeout=5)  # 設定 5 秒超時
        if response.status_code == 200:
            # 檢查回應內容是否包含 "Ollama is running"
            if "Ollama is running" in response.text:
                if verbose:
                    print(f"Ollama 在 {root_url} 運行中！")
                return True
            else:
                if verbose:
                    print(f"{root_url} 可連接，但沒有收到預期的回應：'Ollama is running'")
                return False
        else:
            if verbose:
                print(f"主網域 {root_url} 連接失敗，HTTP 狀態碼: {response.status_code}")
            return False
    except requests.exceptions.RequestException as e:
        if verbose:
            print(f"無法連接到 {root_url}，錯誤: {e}")
        return False


def get_available_end_points(config_file=DEFAULT_END_POINT_CONFIG_FILE):
    """
    從設定檔中讀取可用的端點清單，並檢查每個端點是否可連接。
    """
    if os.path.exists(config_file):
        with open(config_file, 'r') as f:
            config_data = json.load(f)

        # 讀取設定檔中的端點清單
        end_points = config_data.get("on_premises_end_points", [])
        #print("end_points",end_points)
        #import time
        #time.sleep(10)
        # 篩選出可用的端點
        available_end_points = [end_point for end_point in end_points if is_end_point_available(end_point)]
        #print("available_end_points",available_end_points)
        # 如果沒有可用端點，回報錯誤並返回默認端點
        if not available_end_points:
            print("所有設定端點無法連接，將使用默認端點。")
            available_end_points = ["http://192.168.0.134:11434/v1"]  # 默認端點
        
        return available_end_points
    else:
        print("設定檔不存在，使用預設端點。")
        return ["http://192.168.0.134:11434/v1"]  # 默認端點
    
    
def get_available_models(base_url, candidates):
    """
    偵測可用的模型，從本地端點獲取模型清單，並根據候選模型清單選擇可用的模型。
    如果 `On_Premises` 為 `True`，則會檢查本地端點的模型清單，並選擇可用的模型。
    """
    try:
        # 嘗試獲取本地端點的模型清單
        root_url = base_url.rsplit("/v1", 1)[0]  # 拿掉 /v1，保留根網址
        model_list_response = requests.get(f"{root_url}/api/tags", timeout=5)
        model_list_response.raise_for_status()  # 檢查請求是否成功
        
        model_list = model_list_response.json().get("models", [])
        model_names = {model["name"] for model in model_list}

        # 根據優先順序選擇第一個存在於模型清單中的模型
        available_model = next((model for model in candidates if model in model_names), None)
        
        if available_model:
            print(f"已選擇模型: {available_model} 在本地端點 {base_url}")
        else:
            print(f"未找到合適的模型，使用候選模型中的預設模型: {candidates[0]}")
            available_model = candidates[0]  # 如果沒有合適的模型，使用預設模型

        return available_model
    except requests.exceptions.RequestException as e:
        print(f"無法獲取本地端點的模型清單，錯誤: {e}")
        # 如果發生錯誤，返回候選模型中的預設模型
        return candidates[0]

# 範例：從設定中讀取候選模型並選擇可用模型
def select_model(model_spec, config_file=DEFAULT_END_POINT_CONFIG_FILE):
    """
    根據 model_spec 和設定檔選擇模型，並確保選擇的 base_url 是可用的。
    如果 model_spec 中沒有 base_url，則使用 get_available_end_points 自動選擇端點。
    """
    candidates = ["qwen3:32b-ctx-32k-premises-q4", "gpt-oss:latest-ctx-32k-premises-MXFP4", "qwen3:30b-a3b-32k", "qwen2.5-32k"]
    
    # 如果 model_spec 中沒有 base_url，則使用 get_available_end_points 函數選擇可用端點
    if "base_url" not in model_spec or not model_spec["base_url"]:
        available_end_points = get_available_end_points(config_file)  # 呼叫 get_available_end_points
        #print("available_end_points",available_end_points)
        model_spec["base_url"] = available_end_points[0]  # 選擇第一個可用的端點
    
    # 使用 get_available_models 函數來選擇合適的模型
    model = get_available_models(model_spec["base_url"], candidates)  # 調用 get_available_models 函數選擇模型
    
    # 更新 model_spec 中的 model_name
    model_spec["model_name"] = model
    return model_spec