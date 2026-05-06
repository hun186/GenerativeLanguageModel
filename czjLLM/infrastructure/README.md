# Infrastructure runtime settings

## Base URL load stale timeout (`CZJ_BASE_URL_LOAD_STALE_SECS`)

`czjLLM/infrastructure/ollama_lb.py` 的 `base_url_load.json` 會記錄每個 base_url 的派工租約與最後更新時間。
若整份負載檔裡所有 base_url 的 `last_update` 都超過此 timeout 沒有刷新，系統會判定派工負載資訊可能整體卡住，並在下一次選擇 base_url 前清空未完成租約，讓新的 job 可以繼續派發。只要仍有切片任務持續派工或完成，`select_idle_ollama_url` / `release_url_load` 會刷新至少一個 base_url 的 `last_update`，因此不會觸發此重設。

- 預設值是 `1200` 秒（20 分鐘）
- 可用環境變數 `CZJ_BASE_URL_LOAD_STALE_SECS` 覆蓋

範例：

```bash
export CZJ_BASE_URL_LOAD_STALE_SECS=1200
python your_entry.py
```

## Lock stale timeout (`CZJ_LOCK_STALE_SECS`)

`czjLLM/infrastructure/ollama_lb.py` 的檔案鎖會使用：

- `LOCK_STALE_SECS = float(os.getenv("CZJ_LOCK_STALE_SECS", "600"))`

也就是：

- 預設值是 `600` 秒
- 可用環境變數 `CZJ_LOCK_STALE_SECS` 覆蓋

### 要在哪裡設定？

這不是 YAML 設定檔欄位，而是**啟動程式的執行環境變數**。常見做法：

#### 1) Linux shell（單次執行）

```bash
export CZJ_LOCK_STALE_SECS=900
python your_entry.py
```

#### 2) systemd 服務

在 service 檔加入：

```ini
Environment=CZJ_LOCK_STALE_SECS=900
```

然後：

```bash
sudo systemctl daemon-reload
sudo systemctl restart <your-service>
```

#### 3) Docker / Compose

`docker run`：

```bash
docker run -e CZJ_LOCK_STALE_SECS=900 ...
```

`docker-compose.yml`：

```yaml
environment:
  - CZJ_LOCK_STALE_SECS=900
```

### 建議值

- 一般情境：`600`
- 任務很重、鎖競爭偏高：`900` 或 `1200`
- 先觀察 timeout log，再微調為你環境的穩定值
