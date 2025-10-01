# czjLLM/es_mode/entry/steps_es.py
from typing import Any, Dict, List, Tuple
from pathlib import Path
import importlib.util

from elasticsearch import Elasticsearch

from utils.selector import OptionSelector

from czjLLM.es_mode.config.config_loader_es import load_es_cfg, InteractivePolicy, NonInteractivePolicy
from czjLLM.es_mode.runtime.sinks.es_sink import ESSink

from czjLLM.es_mode.adapters.elasticsearch_adapter import ElasticsearchAdapter

from utils.ES_utils import get_es_client, apply_es_mapping

# ---------- Resolve 連線 ----------
def resolve_es_connection_old(ctx, get_param, args):
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


def resolve_es_connection(ctx, get_param, args):
    """
    讀取 ES 連線設定，保留互動式詢問，
    最後回傳 (adapter, es_cfg)
    """
    # 1. 選擇互動策略
    policy = NonInteractivePolicy(args) if args.config else InteractivePolicy()
    es_cfg = load_es_cfg(ctx, get_param, args, policy)
    #print("es_cfg in resolve_es_connection",es_cfg)
    # 2. 取得連線參數（若設定檔沒有，就互動詢問）
    es_host = (es_cfg.get("es_host")
               or input("🔹 請輸入 ES host（預設 http://localhost:9200）：").strip()
               or "http://localhost:9200")
    es_user = es_cfg.get("es_user") if "es_user" in es_cfg else \
              (input("🔹 請輸入 ES user（留空表示無帳號）：").strip() or None)
    es_pass = es_cfg.get("es_pass") if "es_pass" in es_cfg else \
              (input("🔹 請輸入 ES password（留空表示無密碼）：").strip() or None)
    es_index = es_cfg.get("es_index") or input("🔹 請輸入 ES index：").strip()

    # 若沒有設定 tgt_index，預設與 src_index 相同（單一 index 模式）
    src_index = es_cfg.get("es_src_index", es_index)
    tgt_index = es_cfg.get("es_tgt_index", src_index)

    # 3. 建立 ElasticsearchAdapter（內部會自己建 client）
    adapter_cfg = {
        "es_host": es_host,
        "http_auth": (es_user, es_pass) if es_user else None,
        "timeout": es_cfg.get("timeout", 60),
        "src_index": src_index,
        "tgt_index": tgt_index,
        #"id_col": es_cfg.get("id_col", getattr(ctx, "primary_key", "_id")),
        "id_col": es_cfg.get("id_col", getattr(ctx, "primary_key", "_id")),
        "input_col": es_cfg.get("input_col"),
        "output_col": es_cfg.get("output_col"),
        "reset_output": es_cfg.get("reset_output", None),
        "reset_confirm_code": es_cfg.get("reset_confirm_code", None)
    }
    
    # 直接用 dict comprehension 過濾掉 None，保持乾淨
    adapter_cfg = {k: v for k, v in adapter_cfg.items() if v is not None}
    #print("adapter_cfg in ",adapter_cfg)
    adapter = ElasticsearchAdapter(adapter_cfg).connect()

    # 4. 回傳
    return adapter, es_cfg



# ---------- 選擇欄位 (相當於 choose_columns_and_io_cols) ----------
def choose_columns_es(ctx, env, get_param, args):
    """
    在 ES 裡對應 SQL 的「欄位選擇」：
    - primary_key 對應 _id 或 config 裡的 id_col
    - input_col 對應 JSON key path
    - output_col 對應 JSON key path (可以不存在，執行時新增)
    與新結構對齊：env 內含 adapter（ElasticsearchAdapter），不再直接放 index。
    最後回傳 List[Tuple[col, type]] 供 ensure_schemas_es 用（同 SQL 流程）。
    """
    adapter = env["adapter"]
    es_cfg = getattr(adapter, "cfg", {})

    # ---------- primary_key ----------
    primary_key = (
        getattr(args, "id_col", None)
        or get_param("id_col", es_cfg.get("id_col"))
        or "_id"
    )
    #print("es_cfg",es_cfg)
    # ---------- input_col ----------
    #input_col = (
    #    getattr(args, "input_col", None)
    #    or get_param("input_col", es_cfg.get("input_col", ""))
    #)
    #if not input_col:
    #    input_col = input("📝 請輸入輸入欄位 (預設 rawInfo.content)：").strip() or "rawInfo.content"
    if "input_col" in es_cfg:
        input_col = es_cfg["input_col"]
    else:
        input_col = input("📝 請輸入輸入欄位 (預設 rawInfo.content)：").strip() or "rawInfo.content"
    #print("input_col",input_col)
    # ---------- output_col ----------
    #output_col = (
    #    getattr(args, "output_col", None)
    #    or get_param("output_col", (es_cfg.get("output_col") or [None])[0] or "")
    #)
    #if not output_col:
    #    default_out = f"{input_col}_LLM_result"
    #    output_col = input(f"💾 請輸入輸出欄位名稱（預設為 {default_out}）：").strip() or default_out
    if "output_col" in es_cfg:
        output_col = es_cfg["output_col"]
    else:
        default_out = f"{input_col}_LLM_result"
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

    # ---------- 回灌到 ctx ----------
    # 若你仍有 ctx.es_index，可在 resolve 時塞；此處不直接使用 index，改由 adapter.cfg 管理
    ctx.primary_key = primary_key
    ctx.input_col = input_col
    ctx.output_col = output_col

    # ---------- 同步到 adapter.cfg（讓後續 build_pending_iter_es 直接使用） ----------
    es_cfg["id_col"]   = primary_key
    es_cfg["input_col"]  = input_col
    es_cfg["output_col"] = output_col
    # 若你需要此時才決定 index 名稱，也可在這裡放：
    # es_cfg["src_index"] = es_cfg.get("src_index") or input("請輸入來源 index：").strip()
    # es_cfg["tgt_index"] = es_cfg.get("tgt_index") or es_cfg["src_index"]

    # ---------- 回傳給 ensure_schemas_es 的 columns（建議只補目標 index 的 output 欄位） ----------
    # 型別字串用簡單語義；ElasticsearchAdapter.ensure_columns 會把 "TEXT" 轉成 text+keyword
    return [(output_col, "TEXT")]

def choose_columns_es_old(ctx, env, get_param, args) -> Dict[str, str]:
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
        default_out = f"{input_col}_LLM_result"
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


# ---------- flatten 設定 ----------
def configure_flatten_es(ctx, get_param, args):
    """
    ES 文件通常是 JSON，是否要扁平化交給參數
    """
    ctx.flatten_json = getattr(args, "flatten_json", None) or False


# ---- 確保 schema（mapping）對齊 SQL ensure_schemas ----
def ensure_schemas_es(ctx, adapter: ElasticsearchAdapter, columns, index_name_hint=None):
    """
    先確保 src/tgt index 存在；再依設定：
      - 若有 es_apply_mapping + mapping_file：整包 put_mapping（新增欄位）
      - 否則最小化保障：只確保 output_col 存在且型別正確（NESTED/OBJECT 擇一）
    """
    # 1) 確保 index 存在
    adapter.ensure_table(adapter.cfg["src_index"])
    adapter.ensure_table(adapter.cfg["tgt_index"])

    tgt_index = adapter.cfg["tgt_index"]
    # 你想要的欄位名（只看 ctx.output_col）
    out_field = getattr(ctx, "output_col", "llm_result")
    # 建議預設為 NESTED（你的 LLM 輸出是陣列）
    desired_type = getattr(ctx, "es_output_type", "NESTED").upper()  # "NESTED" or "OBJECT"

    # 2) 若設定檔要求整包 mapping，就先走這條
    es_apply_mapping = adapter.cfg.get("es_apply_mapping", False)
    mapping_file = adapter.cfg.get("mapping_file")
    if es_apply_mapping and mapping_file:
        try:
            adapter.apply_mapping_file(tgt_index, mapping_file)
            print(f"✅ 已套用 mapping 檔到 index='{tgt_index}'：{mapping_file}")
        except Exception as ex:
            print(f"⚠️ 套用 mapping 檔失敗（將退回最小化策略）：{ex}")

    # 3) 最小化保障：只管 output_col 的型別
    #    - 若欄位不存在：put_mapping 建立
    #    - 若已存在但型別不符：僅告警，不強改
    try:
        exists_node = adapter.get_field_mapping(tgt_index, out_field)
        if exists_node is None:
            # 欄位不存在 → 依 desired_type 建出最小 mapping
            if desired_type == "NESTED":
                body = {"properties": {out_field: {"type": "nested"}}}
            else:
                # OBJECT 適合單一物件（或你想寬鬆一些）
                body = {"properties": {out_field: {"type": "object"}}}
            adapter.es.indices.put_mapping(index=tgt_index, body=body)  # type: ignore
            print(f"✅ 已在 index='{tgt_index}' 新增欄位 '{out_field}'（type={desired_type}）")
        else:
            # 欄位已存在 → 檢查型別
            cur_type = exists_node.get("type", "object")  # object/nested/text/…；無 type 視為 object
            ok = (desired_type == "NESTED" and cur_type == "nested") or \
                 (desired_type == "OBJECT" and cur_type in ["object", None])
            if not ok:
                print(f"⚠️ 欄位 '{out_field}' 已存在但型別為 {cur_type}，與期望 {desired_type} 不符。"
                      f"ES 不允許變更型別，請改用另一個 output_col（如 '{out_field}_json'）或清空重建 index。")
    except Exception as ex:
        print(f"⚠️ 確認/建立 output_col 映射時發生例外：{ex}")
        
# ---- 確保 schema（mapping）對齊 SQL ensure_schemas ----
def ensure_schemas_es_old(ctx, adapter: ElasticsearchAdapter, columns: List[Tuple[str, str]], index_name_hint=None):
    adapter.ensure_table(adapter.cfg["src_index"])
    adapter.ensure_table(adapter.cfg["tgt_index"])

    # 🔁 改這裡：用 NESTED（陣列）或 OBJECT（二擇一）
    out_field = getattr(ctx, "output_col", "llm_result")
    desired_type = "NESTED"  # 如果你的 llm_result 是陣列（建議）
    # desired_type = "OBJECT"  # 如果你確定只是一個物件

    adapter.ensure_columns(adapter.cfg["tgt_index"], [(out_field, desired_type)])


    

# ---------- reset output ----------
def maybe_reset_output_es_old(ctx, es_client, index, columns, args):
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


# ---- 可能重設輸出欄位（對齊 SQL maybe_reset_output_col） ----
def maybe_reset_output_es(ctx, adapter: ElasticsearchAdapter, columns, args):
    """
    若 args.reset_output 為 True，或 adapter.cfg['reset_output'] 為 True，
    會把目標 index 中的輸出欄位清掉。
    另外支援清除「歷史欄位」：例如 rawInfo.content_LLM_result、rawInfo.LLM_result。
    """
    if adapter.es is None:
        raise RuntimeError("Elasticsearch client 尚未連線")

    # 1) 判斷是否要重設（args 優先，否則看 adapter.cfg）
    reset_flag = getattr(args, "reset_output", None)
    if reset_flag is None:
        reset_flag = adapter.cfg.get("reset_output", False)
    if not reset_flag:
        return

    # 2) 確認碼（有提供就跳過互動）
    confirm_code = getattr(args, "reset_confirm_code", None)
    if confirm_code is None:
        confirm_code = adapter.cfg.get("reset_confirm_code", None)
    if confirm_code is None:
        # 沒有提供就做最簡單的互動確認（避免誤刪）
        code = "12345"
        entered = input(f"⚠️ 將清空輸出欄位，請輸入確認碼 {code} 繼續（或直接 Enter 取消）：").strip()
        if entered != code:
            print("↩️ 已取消重設。")
            return

    tgt_index = adapter.cfg.get("tgt_index") or adapter.cfg.get("src_index")
    if not tgt_index:
        raise ValueError("未設定 target/source index（tgt_index/src_index）")

    # 3) 構建要清的欄位清單
    out_col = ctx.output_col  # 例如 'llm_result'
    # 常見歷史欄位（依你的資料範例）
    legacy_fields = [
        f"{ctx.input_col}_LLM_result",   # e.g. 'rawInfo.content_LLM_result'
        "rawInfo.LLM_result",
    ]
    fields_to_remove = [out_col] + legacy_fields

    # 4) 用 painless 一次移除多個欄位（存在才移除，不存在就略過）
    script_source = """
      for (f in params.fields) {
        if (ctx._source.containsKey(f)) { ctx._source.remove(f); }
      }
    """

    resp = adapter.es.update_by_query(
        index=tgt_index,
        body={
            "script": {"source": script_source, "lang": "painless", "params": {"fields": fields_to_remove}},
            "query": {"match_all": {}}
        },
        refresh=True,
        conflicts="proceed",
        wait_for_completion=True,
    )
    # 給點可見的回饋
    updated = resp.get("updated", 0)
    print(f"🧼 reset_output: index={tgt_index}, removed_fields={fields_to_remove}, updated_docs={updated}")
    
# ---------- 建立 iterator ----------
def build_pending_iter_es(adapter: ElasticsearchAdapter, ctx):
    """
    與 SQL 版一致回傳 Iterable[(pk, input_text)]。
    內部邏輯由 adapter.select_pending_rows 負責（單/雙 index 自動處理）。
    """
    return adapter.select_pending_rows(
        src_table=adapter.cfg["src_index"],
        tgt_table=adapter.cfg["tgt_index"],
        pk=adapter.cfg["id_col"],
        input_col=adapter.cfg["input_col"],
        output_col=adapter.cfg["output_col"],
        record_update_time=getattr(ctx, "record_update_time", False),
        fetch_size=getattr(ctx, "fetch_size", 500),
    )

def build_pending_iter_es_old(es_client, ctx):
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

