import os, time, json, random, tempfile
from datetime import datetime, timezone
from czjLLM.utilities.atomic_io import atomic_write_json

# ==== 參數可按需調整 ====
LEASE_SECS = 300           # 單次派工的租約秒數，超時會自動釋放（防 crash 不釋放）
STALE_RESET_SECS = float(os.getenv("CZJ_BASE_URL_LOAD_STALE_SECS", "1200"))  # 負載資訊 20 分鐘未更新就視為卡住並釋放未完成租約
EPSILON_EXPLORE = 0.1      # ε-greedy：有 10% 機率嘗試任意節點，避免永久飢餓
JITTER = 0.05              # 破平手用的微小抖動，避免所有人都選到同一台
LOCK_TIMEOUT = 5.0         # 取得檔案鎖的等候上限秒數
LOCK_SLEEP = 0.05          # 等鎖時的 sleep 間隔
LOCK_STALE_SECS = float(os.getenv("CZJ_LOCK_STALE_SECS", "600"))  # 預設 600 秒，長任務較不易誤判 stale


def _lock_path(json_path: str) -> str:
    return json_path + ".lock"

def _acquire_file_lock(lock_path: str, timeout: float = LOCK_TIMEOUT, stale: float = LOCK_STALE_SECS):
    """最簡單的跨程序鎖法：用『獨佔建立 lock 檔』。

    強化：若 lock 檔明顯過舊（例如前次程序被強制中斷）就自動回收，
    避免整個排程因僵死 lock 永久卡住。
    """
    start = time.time()
    lock_dir = os.path.dirname(lock_path) or "."
    os.makedirs(lock_dir, exist_ok=True)
    while True:
        try:
            # 'x' 模式：若已存在會丟 FileExistsError
            f = open(lock_path, "x")
            return f  # 用 caller 的 finally 去 close+unlink
        except FileExistsError:
            # lock 檔存在：若過舊視為殭屍鎖，嘗試回收
            try:
                age = time.time() - os.path.getmtime(lock_path)
                if age > stale:
                    os.remove(lock_path)
                    continue
            except FileNotFoundError:
                # 競態：別人剛好刪掉，直接重試
                continue
            except OSError:
                # 可能被另一程序占用，走一般等待流程
                pass
            if time.time() - start > timeout:
                # 若鎖非 stale 但長時間拿不到，回報明確錯誤，避免無鎖寫入破壞負載統計
                try:
                    age = time.time() - os.path.getmtime(lock_path)
                except OSError:
                    age = None
                age_text = f"{age:.2f}s" if isinstance(age, (int, float)) else "unknown"
                raise TimeoutError(
                    f"Timeout acquiring lock: {lock_path} (age={age_text}, stale_after={stale}s)"
                )
            time.sleep(LOCK_SLEEP)

def _release_file_lock(lock_fp, lock_path: str):
    if lock_fp is None:
        return
    try:
        lock_fp.close()
    except Exception:
        pass
    try:
        os.remove(lock_path)
    except Exception:
        pass

def _now() -> float:
    return time.time()

def _load_state(path: str, base_urls):
    """讀檔（若毀損就重建），並確保每個 url 都有基本結構。"""
    state = {}
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                state = json.load(f) or {}
        except Exception:
            state = {}
    # 規範化結構：每個 url => {"leases":[ts,...], "last_update": ts}
    now = _now()
    for url in base_urls:
        rec = state.get(url)
        if not isinstance(rec, dict):
            rec = {}
        if not isinstance(rec.get("leases"), list):
            rec["leases"] = []
        if not isinstance(rec.get("last_update"), (int, float)):
            rec["last_update"] = 0.0
        state[url] = rec
    return state

def _cleanup_and_count(state: dict, url: str, now_ts: float) -> int:
    """清掉過期租約，回傳目前有效租約數（= 負載）。"""
    rec = state[url]
    leases = rec.get("leases", [])
    # 僅保留未過期的 lease
    leases = [exp for exp in leases if exp > now_ts]
    rec["leases"] = leases
    return len(leases)

def _latest_state_update(state: dict, base_urls) -> float:
    """回傳整份 base_url_load 狀態最近一次更新時間。"""
    latest = 0.0
    for url in base_urls:
        rec = state.get(url)
        if not isinstance(rec, dict):
            continue
        last_update = rec.get("last_update", 0.0)
        if isinstance(last_update, (int, float)):
            latest = max(latest, float(last_update))
    return latest

def _reset_state_if_stale(state: dict, base_urls, now_ts: float) -> bool:
    """整份負載資訊長時間沒更新時，釋放所有未完成租約。

    base_url_load.json 是平衡派工的共享狀態；只要切片任務仍持續派工或完成，
    select_idle_ollama_url / release_url_load 會刷新至少一個 base_url 的 last_update，
    因此整份狀態的 latest last_update 仍會保持新鮮，不會觸發此重設。

    只有當所有 base_url 的 last_update 都超過 STALE_RESET_SECS 未刷新，才視為
    派工狀態可能整體卡住或程序已中斷，並清空未完成 leases，讓後續可以繼續派新 job。
    """
    latest_update = _latest_state_update(state, base_urls)
    if latest_update <= 0 or now_ts - latest_update <= STALE_RESET_SECS:
        return False

    for url in base_urls:
        state[url]["leases"] = []
        state[url]["last_update"] = now_ts
    return True

def select_idle_ollama_url(base_urls, PGMSubDir: str = ""):
    """
    選擇目前負載最輕的 base_url。
    強化點：
    - 使用「租約」(TTL) 計數，crash 不釋放也會到期自動釋放。
    - 每次選擇前會清理過期租約；長時間未更新者直接重置。
    - ε-greedy + jitter，避免節點被永久飢餓或長期平手偏壓。
    - 檔案鎖 + 原子寫，避免多程序同時寫壞檔或 PermissionError。
    """
    if isinstance(base_urls, str):
        base_urls = [base_urls]
    load_file = os.path.join(PGMSubDir, "logs", "base_url_load.json")
    lock_fp = None
    try:
        lock_fp = _acquire_file_lock(_lock_path(load_file))
    except TimeoutError as ex:
        # 降級策略：避免因負載統計鎖競爭導致整個 LLM 呼叫失敗
        chosen = random.choice(base_urls)
        print(f"⚠️ base_url 負載鎖逾時，改用降級隨機選擇: {chosen} ({ex})")
        return chosen
    try:
        state = _load_state(load_file, base_urls)
        now_ts = _now()

        # 先做整體 stale 檢查，再清理各節點過期租約
        if _reset_state_if_stale(state, base_urls, now_ts):
            print(
                f"⚠️ base_url 負載資訊整體超過 {int(STALE_RESET_SECS)} 秒未更新，"
                "已釋放未完成租約以解除可能卡死"
            )

        loads = {}
        for url in base_urls:
            loads[url] = _cleanup_and_count(state, url, now_ts)

        # ε-greedy：一定機率隨機探索，避免某節點永遠得不到新任務
        if random.random() < EPSILON_EXPLORE:
            chosen = random.choice(base_urls)
        else:
            # metric = 負載 + 微抖動，避免大量 tie 全撞同一台
            metrics = {u: (loads[u] + random.random() * JITTER) for u in base_urls}
            min_metric = min(metrics.values())
            candidates = [u for u, v in metrics.items() if abs(v - min_metric) < 1e-9 or v == min_metric]
            chosen = random.choice(candidates)

        # 指派租約：加入一個到期時間
        lease_exp = now_ts + LEASE_SECS
        state[chosen]["leases"].append(lease_exp)
        state[chosen]["last_update"] = now_ts

        # 寫回
        atomic_write_json(load_file, state)
        
        print(f"選擇負載最輕的 base_url: {chosen}，當前負載: {loads.get(chosen, 0)}")
        
        #time.sleep(10)
        # 追加：輸出人性化快照（JSON 或 TXT 版擇一或都要）
        try:
            write_human_load_snapshot(load_file, tz='local')  # base_url_load.human.json
        except Exception as ex:
            print(f"In select_idle_ollama_url, the following error occurs: {ex}")
            # 不影響主流程
            pass
        return chosen
    finally:
        _release_file_lock(lock_fp, _lock_path(load_file))


def release_url_load(base_url: str, PGMSubDir: str = ""):
    """
    釋放該 base_url 的一個租約（若不存在就忽略）。
    即使忘了呼叫，租約也會在 LEASE_SECS 後自動失效，避免計數漂移。
    """
    load_file = os.path.join(PGMSubDir, "logs", "base_url_load.json")
    lock_fp = None
    try:
        lock_fp = _acquire_file_lock(_lock_path(load_file))
    except TimeoutError as ex:
        # 釋放鎖失敗不阻斷主流程；租約也會靠 TTL 自動過期。
        print(f"⚠️ release_url_load 略過（鎖逾時）: {ex}")
        return
    try:
        if not os.path.exists(load_file):
            return
        try:
            with open(load_file, "r", encoding="utf-8") as f:
                state = json.load(f) or {}
        except Exception:
            state = {}

        rec = state.get(base_url)
        if not isinstance(rec, dict):
            # 沒紀錄就當作已釋放
            return

        now_ts = _now()
        # 先清除所有過期租約
        leases = [exp for exp in rec.get("leases", []) if exp > now_ts]
        # 再移除一個最早到期的租約（有就移）
        if leases:
            leases.sort()
            leases.pop(0)

        rec["leases"] = leases
        rec["last_update"] = now_ts
        state[base_url] = rec

        atomic_write_json(load_file, state)
        print(f"釋放 base_url: {base_url} 的負載，當前負載: {len(leases)}")
        try:
            write_human_load_snapshot(load_file, tz='local')            
        except Exception as ex:
            print(f"In release_url_load, the following error occurs: {ex}")
            pass
    finally:
        _release_file_lock(lock_fp, _lock_path(load_file))




        
def _fmt_ts(ts, tz='local', timespec='seconds'):
    if ts is None:
        return "-"
    ts = float(ts)
    if tz in (None, 'local'):
        tzinfo = datetime.now().astimezone().tzinfo
    elif tz == 'utc':
        tzinfo = timezone.utc
    else:
        tzinfo = tz
    return datetime.fromtimestamp(ts, tzinfo).isoformat(timespec=timespec)

def _human_delta(seconds):
    if seconds is None:
        return "-"
    s = int(round(seconds))
    neg = s < 0
    s = abs(s)
    units = [('天', 86400), ('小時', 3600), ('分', 60), ('秒', 1)]
    parts = []
    for name, unit in units:
        if s >= unit:
            q, s = divmod(s, unit)
            parts.append(f"{q}{name}")
    out = " ".join(parts) if parts else "0秒"
    return f"-{out}" if neg else out

def _pretty_view_from_data(data, tz='local'):
    now = time.time()
    view = {}
    for url, v in (data or {}).items():
        leases = v.get('leases', []) or []
        last_update = v.get('last_update')
        view[url] = {
            'concurrency': len(leases),
            'last_update': _fmt_ts(last_update, tz),
            'last_update_ago': _human_delta(now - float(last_update)) if last_update else "-",
            'leases': [
                {'at': _fmt_ts(ts, tz), 'ago': _human_delta(now - float(ts))}
                for ts in leases
            ],
        }
    return view

def write_human_load_snapshot(load_json_path, out_path=None, tz='local'):
    load_json_path = os.path.abspath(load_json_path)
    if out_path is None:
        out_path = os.path.join(os.path.dirname(load_json_path), "base_url_load.human.json")

    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    try:
        with open(load_json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        data = {}

    view = _pretty_view_from_data(data, tz=tz)  # ← dict
    atomic_write_json(out_path, view)           # ← 直接丟 dict，不要 encode 成 bytes
    return out_path
