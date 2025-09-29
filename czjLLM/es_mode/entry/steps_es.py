# czjLLM/es_mode/entry/steps_es.py
from typing import Any, Dict, List
from pathlib import Path
import importlib.util

from elasticsearch import Elasticsearch

from utils.selector import OptionSelector

from czjLLM.es_mode.config.config_loader_es import load_es_cfg, InteractivePolicy, NonInteractivePolicy
from czjLLM.es_mode.runtime.sinks.es_sink import ESSink

# ---------- Resolve 連線 ----------
def resolve_es_connection(ctx, get_param, args):
    """
    讀取 ES 連線設定，回傳 Elasticsearch client 與 index
    支援 config + 智慧互動（比照 SQL pipeline）
    """
    # ---------------- 1. 選擇互動策略 ----------------
    policy = NonInteractivePolicy(args) if args.config else InteractivePolicy()
    es_cfg = load_es_cfg(ctx, get_param, args, policy)
    print("es_cfg in resolve_es_connection", es_cfg)
    # ---------------- 2. 取得連線參數 ----------------
    es_host = (es_cfg.get("es_host") or
               input("🔹 請輸入 ES host（預設 http://localhost:9200）：").strip() or
               "http://localhost:9200")
    if "es_user" in es_cfg:
        es_user = es_cfg["es_user"]
    else:
        es_user = input("🔹 請輸入 ES user（留空表示無帳號）：").strip() or None
    if "es_pass" in es_cfg:
        es_pass = es_cfg["es_pass"]
    else:
        es_pass = input("🔹 請輸入 ES password（留空表示無密碼）：").strip() or None
    #es_user = es_cfg.get("es_user") if "es_user" in es_cfg else input("🔹 請輸入 ES user（留空表示無帳號）：").strip() or None
    #es_user = es_cfg.get("es_user") or input("🔹 請輸入 ES user（留空表示無帳號）：").strip() or None
    #es_pass = es_cfg.get("es_pass") or input("🔹 請輸入 ES password（留空表示無密碼）：").strip() or None
    es_index = es_cfg.get("es_index") or input("🔹 請輸入 ES index：").strip()

    # ---------------- 3. 建立 Elasticsearch client ----------------
    es_client_kwargs = {"hosts": [es_host]}
    if es_user:
        es_client_kwargs["http_auth"] = (es_user, es_pass)

    es = Elasticsearch(**es_client_kwargs)

    # ---------------- 4. 回傳 ----------------
    return es, es_index, es_cfg

def resolve_es_connection_old(ctx, get_param, args):
    """
    讀取 ES 連線設定，回傳 Elasticsearch client 與 index
    """
    # ---------------- 1. 載入 config ----------------
    cfg = {}
    config_path = getattr(args, "config", None)  # 先取 args.config
    if config_path and Path(config_path).exists():
        spec = importlib.util.spec_from_file_location("es_config", config_path)
        cfg_mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cfg_mod)
        cfg = {k: getattr(cfg_mod, k) for k in dir(cfg_mod) if not k.startswith("__")}

    # ---------------- 2. 取得連線參數 ----------------
    es_host = cfg.get("es_host") or getattr(args, "es_host", None) or input("🔹 請輸入 ES host（預設 http://localhost:9200）：").strip() or "http://localhost:9200"
    es_user = cfg.get("es_user") or getattr(args, "es_user", None) or input("🔹 請輸入 ES user（留空表示無帳號）：").strip() or None
    es_pass = cfg.get("es_pass") or getattr(args, "es_pass", None) or input("🔹 請輸入 ES password（留空表示無密碼）：").strip() or None
    es_index = cfg.get("es_index") or getattr(args, "es_index", None) or input("🔹 請輸入 ES index：").strip()

    # ---------------- 3. 建立 Elasticsearch client ----------------
    es_client_kwargs = {"hosts": [es_host]}
    if es_user:
        es_client_kwargs["http_auth"] = (es_user, es_pass)
    es = Elasticsearch(**es_client_kwargs)

    return es, es_index


# ---------- 選擇欄位 (相當於 choose_columns_and_io_cols) ----------
def choose_columns_es(ctx, env, get_param, args) -> Dict[str, str]:
    """
    在 ES 裡對應 SQL 的「欄位選擇」：
    - primary_key 對應 _id 或 config 裡的 id_col
    - input_col 對應 JSON key path
    - output_col 對應 JSON key path (可以不存在，執行時新增)
    """

    # ---------- primary_key ----------
    primary_key = (
        getattr(args, "id_col", None)
        or get_param("id_col", env.get("id_col"))
        or "_id"
    )

    # ---------- input_col ----------
    input_col = (
        getattr(args, "input_col", None)
        or get_param("input_col", env.get("input_col", ""))
    )
    if not input_col:
        input_col = input("📝 請輸入輸入欄位 (預設 rawInfo.content)：").strip() or "rawInfo.content"

    # ---------- output_col ----------
    output_col = (
        getattr(args, "output_col", None)
        or get_param("output_col", env.get("output_col", ""))
    )
    if not output_col:
        default_out = f"{input_col}_result"
        output_col = input(f"💾 請輸入輸出欄位名稱（預設為 {default_out}）：").strip() or default_out

    # ---------- 檢查 input/output 是否相同 ----------
    if input_col == output_col:
        ok = OptionSelector(
            options={"no": "否，重選", "yes": "是，我確定要覆蓋"},
            question="❗輸入/輸出欄位相同，確定覆蓋？",
            default="no"
        ).proc()
        if ok != "yes":
            output_col = input("🔁 請重新輸入輸出欄位名稱：").strip() or f"{input_col}_result"

    # ---------- 存到 ctx ----------
    ctx.es_index = env["index"]
    ctx.primary_key = primary_key
    ctx.input_col = input_col
    ctx.output_col = output_col

    return {
        "primary_key": primary_key,
        "input_col": input_col,
        "output_col": output_col,
    }

def choose_columns_es_old2(ctx, get_param, es_client, index, es_cfg, args) -> Dict[str, str]:
#def choose_columns_es(ctx, env, get_param, args):
    """
    在 ES 裡對應 SQL 的「欄位選擇」：
    - primary_key 固定為 _id
    - input_col / output_col 可由 config 指定或互動輸入
    """
    # -------- 1. primary_key 固定為 _id --------
    primary_key = "_id"

    # -------- 2. input_col --------
    input_col = get_param("input_col", es_cfg.get("input_col", ""))
    if not input_col:
        input_col = input("📝 請輸入輸入欄位 JSON path（預設 rawInfo.content）：").strip() or "rawInfo.content"

    # -------- 3. output_col --------
    output_col = get_param("output_col", es_cfg.get("output_col", ""))
    if not output_col:
        default_out = "LLM_result"
        output_col = input(f"💾 請輸入輸出欄位 JSON path（預設 {default_out}）：").strip() or default_out

    # -------- 4. 避免輸入輸出相同 --------
    if input_col == output_col:
        ok = OptionSelector(
            options={"no": "否，重選", "yes": "是，我確定要覆蓋"},
            question="❗輸入/輸出欄位相同，確定覆蓋？",
            default="no"
        ).proc()
        if ok != "yes":
            # 請使用者重新指定 output_col
            output_col = input(f"🔁 請重新輸入輸出欄位 JSON path（預設 {input_col}_result）：").strip() or f"{input_col}_result"

    # -------- 5. 是否記錄 update_time --------
    ctx.record_update_time = get_param("record_update_time", es_cfg.get("record_update_time"))
    if ctx.record_update_time is None:
        record_update_time = input("⏱️ 是否記錄 update_time？(Y/n)：").strip().lower()
        ctx.record_update_time = (record_update_time != "n")

    # -------- 6. 存進 ctx --------
    ctx.es_index = index
    ctx.input_col = input_col
    ctx.output_col = output_col
    ctx.primary_key = primary_key

    return {
        "primary_key": primary_key,
        "input_col": input_col,
        "output_col": output_col,
    }

def choose_columns_es_old(ctx, get_param, es_client, index, args) -> Dict[str, str]:
    """
    在 ES 裡對應 SQL 的「欄位選擇」：
    - primary_key 對應 _id
    - input_col 對應 JSON key path
    - output_col 對應 JSON key path (可以不存在，執行時新增)
    """
    primary_key = "_id"
    input_col = getattr(args, "input_col", None) or "rawInfo.content"
    output_col = getattr(args, "output_col", None) or "LLM_result"

    ctx.es_index = index
    ctx.input_col = input_col
    ctx.output_col = output_col
    ctx.primary_key = primary_key

    return {
        "primary_key": primary_key,
        "input_col": input_col,
        "output_col": output_col,
    }


# ---------- flatten 設定 ----------
def configure_flatten_es(ctx, get_param, args):
    """
    ES 文件通常是 JSON，是否要扁平化交給參數
    """
    ctx.flatten_json = getattr(args, "flatten_json", None) or False


# ---------- schema 檢查 ----------
def ensure_schemas_es(ctx, es_client, columns, index):
    """
    在 ES 模式中 schema 概念比較弱，
    這裡可以確認 index 是否存在，若不存在可報錯或建立
    """
    if not es_client.indices.exists(index=index):
        raise ValueError(f"Index {index} 不存在")


# ---------- reset output ----------
def maybe_reset_output_es(ctx, es_client, index, columns, args):
    """
    是否要重設 output 欄位 (清空 LLM_result 等)
    """
    reset = getattr(args, "reset_output", False)
    if reset:
        es_client.update_by_query(
            index=index,
            body={
                "script": {"source": f"ctx._source.remove('{columns['output_col']}')"},
                "query": {"exists": {"field": columns["output_col"]}},
            },
            refresh=True,
        )


# ---------- 建立 iterator ----------
def build_pending_iter_es(es_client, ctx):
    """
    建立一個 iterator，逐筆拉出 ES 文件，取 input_col 送進 pipeline
    產出 (pk, input) tuple，兼容 SQL pipeline
    """
    index = ctx.es_index
    input_col = ctx.input_col

    def extract_value(doc: dict, path: str):
        keys = path.split(".")
        val = doc["_source"]
        for k in keys:
            val = val.get(k, None)
            if val is None:
                break
        return val

    resp = es_client.search(index=index, scroll="2m", size=1000, body={"query": {"match_all": {}}})
    sid = resp["_scroll_id"]
    hits = resp["hits"]["hits"]

    while hits:
        for h in hits:
            pk = h["_id"]
            input_value = extract_value(h, input_col)
            yield pk, input_value  # 產出 tuple，兼容 pipeline
        resp = es_client.scroll(scroll_id=sid, scroll="2m")
        sid = resp["_scroll_id"]
        hits = resp["hits"]["hits"]

