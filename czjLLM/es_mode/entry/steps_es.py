# czjLLM/es_mode/entry/steps_es.py
from typing import Any, Dict, List, Tuple
from pathlib import Path
import importlib.util
import time
import queue, threading
from elasticsearch import Elasticsearch

from utils.selector import OptionSelector

from czjLLM.es_mode.config.config_loader_es import load_es_cfg, InteractivePolicy, NonInteractivePolicy
#from czjLLM.es_mode.runtime.sinks.es_sink import ESSink

from czjLLM.es_mode.adapters.elasticsearch_adapter import ElasticsearchAdapter

from utils.ES_utils import get_es_client, apply_es_mapping

_SENTINEL = object()


def _normalize_es_writeback_rules(get_param):
    """
    正規化 ES 多階段寫回規則。
    優先讀 es_writeback_rules；若未設定，沿用 sql_writeback_rules 以便共用現有 row_merger。
    每條規則可含 output_col/source/stage/index/output_type/mapping_file/meta_field/normalize_payload_dates。
    """
    rules = get_param("es_writeback_rules", None)
    if not isinstance(rules, list):
        rules = get_param("sql_writeback_rules", None)
    out = []
    if not isinstance(rules, list):
        return out
    for item in rules:
        if not isinstance(item, dict):
            continue
        col = str(item.get("output_col", "")).strip()
        if not col:
            continue
        src = str(item.get("source", "combined") or "combined").strip().lower()
        if src not in {"combined", "stage"}:
            src = "combined"
        rule = dict(item)
        rule.update({"output_col": col, "source": src, "stage": item.get("stage", None)})
        out.append(rule)
    return out



def _warn_ignored_es_flatten_config(get_param):
    """
    ES 原生支援 object/nested JSON，不需要 SQL/Table 的 flatten-to-subtable 寫回機制。
    若設定檔仍帶入相關 key，明確忽略，避免 row_merger 誤呼叫 ESSink.write_flatten。
    """
    flatten_keys = (
        "es_flatten_writeback_rules",
        "sql_flatten_writeback_rules",
        "es_flatten_json_output",
        "flatten_json_output",
        "es_flatten_writeback_rule",
        "sql_flatten_writeback_rule",
    )
    present = [key for key in flatten_keys if get_param(key, None) is not None]
    if present:
        print(
            "ℹ️ ES 模式已忽略 flatten 設定："
            f"{present}。ES 可直接寫入 object/nested JSON；"
            "請改用 es_writeback_rules + output_type/mapping_file 控制輸出。"
        )


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
    #es_host = (es_cfg.get("es_host")
    #           or input("🔹 請輸入 ES host（預設 http://localhost:9200）：").strip()
    #           or "http://localhost:9200")
    hosts = es_cfg.get("hosts")
    ca = es_cfg.get("es_ca_certs", "")
    
    if not hosts:
        es_host = (es_cfg.get("es_host")
                   or input("ES host（預設 http://localhost:9200）：").strip()
                   or "http://localhost:9200")
        hosts = [es_host]
        
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
        #"es_host": hosts,
        "hosts": hosts,
        "http_auth": (es_user, es_pass) if es_user else None,
        # ✅ TLS 相關：把 es_cfg 的值「帶進 adapter」
        "es_ca_certs": ca,  # ★關鍵：不帶這個就會噴你看到的錯
        "es_verify_certs": es_cfg.get("es_verify_certs", True),
        "es_ssl_assert_hostname": es_cfg.get("es_ssl_assert_hostname", False),
        
        "timeout": es_cfg.get("timeout", 60),
        "src_index": src_index,
        "tgt_index": tgt_index,
        #"id_col": es_cfg.get("id_col", getattr(ctx, "primary_key", "_id")),
        "id_col": es_cfg.get("id_col", getattr(ctx, "primary_key", "_id")),
        "input_col": es_cfg.get("input_col"),
        "output_col": es_cfg.get("output_col"),
        "reset_output": es_cfg.get("reset_output", None),
        "reset_confirm_code": es_cfg.get("reset_confirm_code", None),
        "es_apply_mapping": es_cfg.get("es_apply_mapping", None),
        "mapping_file": es_cfg.get("mapping_file", None),
        "only_selected": es_cfg.get("only_selected", None),
        "pending_filters": es_cfg.get("pending_filters", None),
        "es_request_timeout": es_cfg.get("es_request_timeout", 60),
        "es_scroll_keepalive": es_cfg.get("es_scroll_keepalive", "2m"),
        "es_max_retries": es_cfg.get("es_max_retries", 3),
        "es_retry_on_timeout": es_cfg.get("es_retry_on_timeout", True),
        "es_prefetch_buffer": es_cfg.get("es_prefetch_buffer", 1000),
        "es_prefetch_first_timeout": es_cfg.get("es_prefetch_first_timeout", 20),
        # －－－－ 新增這三項：讓 Adapter 知道怎麼判斷需重跑 －－－－
        "rerun": es_cfg.get("rerun", {}),                         # ★ 必傳
        "fallback_date_field": es_cfg.get("fallback_date_field", "update_time_ai"),  # ★ 必傳
        "pk_keyword_suffix": es_cfg.get("pk_keyword_suffix", ".keyword"),            # 建議傳
    }
    
    # 直接用 dict comprehension 過濾掉 None，保持乾淨
    adapter_cfg = {k: v for k, v in adapter_cfg.items() if v is not None}
    #print("adapter_cfg in resolve_es_connection",adapter_cfg)
    # 預設只挑 selectedMessage==true；可改用 config/CLI 覆寫
    #adapter_cfg["only_selected"] = True
    # 也可直接提供進階 filters（list 形式），此行可先不開：
    # adapter_cfg["pending_filters"] = [{"term": {"selectedMessage": True}}]
    # adapter_cfg["pending_filters"] = [
    #     {"term": {"selectedMessage": True}},
    #     {"term": {"ai.classLabels.highValue": True}},   # boolean → 直接 term
    #     {"term": {"rawInfo.langCode.keyword": "zh-TW"}},
    #     {"range": {"importDT": {"gte": "2025-10-01T00:00:00Z"}}}
    # ]
    # （建議）同步 ctx.primary_key，避免後續 select_pending_rows 用到舊值
    setattr(ctx, "primary_key", adapter_cfg["id_col"])
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
    input_col = get_param("input_col", es_cfg.get("input_col"))
    if not input_col:
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
    output_col = get_param("output_col", es_cfg.get("output_col"))
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

    # ---------- 多階段/多欄位寫回設定 ----------
    # ES 使用自己的 es_writeback_rules 名稱；同時鏡射到 sql_writeback_rules，
    # 以重用既有 row_merger 的多階段 stage selector。
    ctx.es_writeback_rules = _normalize_es_writeback_rules(get_param)
    ctx.sql_writeback_rules = ctx.es_writeback_rules
    # ES 原生支援 JSON object/nested；不要啟用 SQL/Table 的 flatten-to-subtable 流程。
    _warn_ignored_es_flatten_config(get_param)
    ctx.sql_flatten_writeback_rules = []
    ctx.sql_flatten_writeback_rule = 0

    ctx.output_cols = [str(output_col).strip()] if str(output_col).strip() else []
    for r in ctx.es_writeback_rules:
        c = str(r.get("output_col", "")).strip()
        if c and c not in ctx.output_cols:
            ctx.output_cols.append(c)

    ctx.es_output_mappings = get_param("es_output_mappings", es_cfg.get("es_output_mappings", None)) or []
    ctx.es_payload_date_normalize_fields = get_param(
        "es_payload_date_normalize_fields",
        es_cfg.get("es_payload_date_normalize_fields", None),
    )
    ctx.flatten_json_output = False
    ctx.allowed_output_fields = []
    ctx.save_raw_input_when_flatten = False

    ctx.record_update_time = get_param("record_update_time")
    if ctx.record_update_time is None:
        ctx.record_update_time = (input("⏱️ 要不要寫 update_time？(Y/n)：").strip().lower() != "n")
        
    # ---------- 回灌到 ctx ----------
    # 若你仍有 ctx.es_index，可在 resolve 時塞；此處不直接使用 index，改由 adapter.cfg 管理
    ctx.primary_key = primary_key
    ctx.input_col = input_col
    ctx.output_col = output_col

    # ---------- 同步到 adapter.cfg（讓後續 build_pending_iter_es 直接使用） ----------
    es_cfg["id_col"]   = primary_key
    es_cfg["input_col"]  = input_col
    es_cfg["output_col"] = output_col
    es_cfg["output_cols"] = ctx.output_cols
    es_cfg["es_writeback_rules"] = ctx.es_writeback_rules
    es_cfg["es_output_mappings"] = ctx.es_output_mappings
    es_cfg["es_payload_date_normalize_fields"] = ctx.es_payload_date_normalize_fields
    # 若你需要此時才決定 index 名稱，也可在這裡放：
    # es_cfg["src_index"] = es_cfg.get("src_index") or input("請輸入來源 index：").strip()
    # es_cfg["tgt_index"] = es_cfg.get("tgt_index") or es_cfg["src_index"]

    # ---------- 回傳給 ensure_schemas_es 的 columns（建議只補目標 index 的 output 欄位） ----------
    # 型別字串用簡單語義；ElasticsearchAdapter.ensure_columns 會把 "TEXT" 轉成 text+keyword
    def _rule_type(col: str) -> str:
        for r in ctx.es_writeback_rules:
            if r.get("output_col") == col:
                return str(r.get("output_type", r.get("type", "TEXT")) or "TEXT")
        return str(get_param("es_output_type", "TEXT") or "TEXT")

    return [(col, _rule_type(col)) for col in ctx.output_cols]

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
    確保 ES index/mapping 可承接本次任務輸出。

    支援三層設定：
    1. 全域 mapping_file/es_apply_mapping：套用到預設 target index。
    2. es_output_mappings：可宣告多個 index + mapping_file。
    3. es_writeback_rules/sql_writeback_rules：逐輸出欄位指定 index/output_type/mapping_file/meta_field。
    """
    # 1) 確保 index 存在
    adapter.ensure_table(adapter.cfg["src_index"])
    adapter.ensure_table(adapter.cfg["tgt_index"])

    default_tgt = adapter.cfg["tgt_index"]
    es_apply_mapping = adapter.cfg.get("es_apply_mapping", False)
    mapping_file = adapter.cfg.get("mapping_file")

    def _apply_mapping(idx: str, path: str | None, enabled: bool = True):
        if not enabled or not path:
            return
        try:
            adapter.apply_mapping_file(idx, path)
        except Exception as ex:
            print(f"⚠️ 套用 mapping 檔失敗 index={idx}, file={path}（將退回最小化策略）：{ex}")

    # 2) 全域 mapping 檔
    _apply_mapping(default_tgt, mapping_file, bool(es_apply_mapping and mapping_file))

    # 3) 多 index mapping 檔
    output_mappings = getattr(ctx, "es_output_mappings", None) or adapter.cfg.get("es_output_mappings") or []
    if isinstance(output_mappings, dict):
        output_mappings = [output_mappings]
    for item in output_mappings:
        if not isinstance(item, dict):
            continue
        idx = str(item.get("index", item.get("tgt_index", default_tgt)) or default_tgt)
        adapter.ensure_table(idx)
        _apply_mapping(idx, item.get("mapping_file"), bool(item.get("apply", True)))

    rules = getattr(ctx, "es_writeback_rules", None) or getattr(ctx, "sql_writeback_rules", None) or []
    if not isinstance(rules, list):
        rules = []
    rule_by_col = {str(r.get("output_col", "")).strip(): r for r in rules if isinstance(r, dict)}

    output_cols = getattr(ctx, "output_cols", None) or [getattr(ctx, "output_col", "llm_result")]
    if columns:
        for col, _typ in columns:
            if col not in output_cols:
                output_cols.append(col)

    def _node_for_type(output_type: str) -> dict:
        t = str(output_type or "TEXT").strip().upper()
        if t == "NESTED":
            return {"type": "nested"}
        if t in {"OBJECT", "JSON", "MAP"}:
            return {"type": "object"}
        if t in {"KEYWORD"}:
            return {"type": "keyword"}
        if t in {"DATE", "DATETIME", "TIMESTAMP"}:
            return {"type": "date"}
        if t in {"LONG", "INTEGER", "INT", "BIGINT"}:
            return {"type": "long"}
        if t in {"DOUBLE", "FLOAT", "NUMERIC", "DECIMAL"}:
            return {"type": "double"}
        return {"type": "text", "fields": {"keyword": {"type": "keyword"}}}

    def _ensure_field(idx: str, field: str, node: dict):
        try:
            existing = adapter.get_field_mapping(idx, field)
            if existing is None:
                adapter.es.indices.put_mapping(index=idx, body={"properties": {field: node}})  # type: ignore
                print(f"✅ 已在 index='{idx}' 新增欄位 '{field}'（type={node.get('type', 'object')}）")
            else:
                cur = existing.get("type", "object") if isinstance(existing, dict) else "object"
                want = node.get("type", "object")
                if cur != want and not (want == "object" and cur is None):
                    print(f"⚠️ 欄位 '{field}' 目前 type={cur}，設定期望 type={want}；ES 無法直接改既有型別，請改欄位或重建索引。")
        except Exception as ex:
            print(f"⚠️ 確認/建立欄位映射失敗 index={idx}, field={field}: {ex}")

    def _ensure_meta(idx: str, meta_field: str, meta_type: str = "OBJECT"):
        if not meta_field:
            return
        node = {"type": "nested"} if str(meta_type).upper() == "NESTED" else {"type": "object"}
        node["properties"] = {
            "processed_at": {"type": "date"},
            "model_tag": {"type": "keyword"},
            "pipeline_hash": {"type": "keyword"},
            "source": {"type": "keyword"},
            "channel": {"type": "keyword"},
            "task": {"type": "keyword"},
            "output_field": {"type": "keyword"},
            "force_reason": {"type": "keyword"},
        }
        _ensure_field(idx, meta_field, node)

    # 4) 逐欄位最小 mapping 備援
    for out_field in output_cols:
        if not out_field:
            continue
        rule = rule_by_col.get(str(out_field), {})
        idx = str(rule.get("index", rule.get("tgt_index", default_tgt)) or default_tgt)
        adapter.ensure_table(idx)
        _apply_mapping(idx, rule.get("mapping_file"), bool(rule.get("apply_mapping", bool(rule.get("mapping_file")))))
        output_type = rule.get("output_type", rule.get("type", getattr(ctx, "es_output_type", "TEXT")))
        _ensure_field(idx, str(out_field), _node_for_type(output_type))
        meta_field = rule.get("meta_field")
        if meta_field is None:
            rr = (adapter.cfg or {}).get("rerun") or {}
            meta_field = rr.get("meta_field") if str(out_field) == getattr(ctx, "output_col", "") else f"{out_field}_meta"
        if rule.get("write_meta", True):
            _ensure_meta(idx, str(meta_field), str(rule.get("meta_type", getattr(ctx, "es_meta_type", "OBJECT"))))
    
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
    configured_outputs = [c for c in (getattr(ctx, "output_cols", None) or [out_col]) if c]
    fields_to_remove = list(dict.fromkeys(configured_outputs + legacy_fields))

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

def prefetch_iter(
    src_iter,
    maxsize=1000,
    first_batch_timeout=20,
    heartbeat=30,
    sentinel=None,
    on_error=None,
    # ✅ 一律關閉回退直通，避免雙重消費
    fallback_on_timeout=False,
    name="ES-prefetch",
    verbose=False
):
    if sentinel is None:
        sentinel = object()

    q = queue.Queue(maxsize=maxsize)
    stats = {"produced": 0, "consumed": 0}
    cancelled = threading.Event()

    def _producer():
        try:
            for item in src_iter:
                if cancelled.is_set():
                    break
                q.put(item)
                stats["produced"] += 1
        except Exception as e:
            if on_error:
                on_error(e)
        finally:
            try:
                q.put(sentinel)
            except Exception:
                pass

    t = threading.Thread(target=_producer, daemon=True, name=name)
    t.start()

    # --- 首批等待 ---
    try:
        if first_batch_timeout and first_batch_timeout > 0:
            while True:
                try:
                    item = q.get(timeout=first_batch_timeout)
                    break
                except queue.Empty:
                    # ✅ 不回退直通，只印心跳、繼續等
                    print(f"[prefetch] 首批 > {first_batch_timeout}s 未到… thread_alive={t.is_alive()}", flush=True)
        else:
            item = q.get()
    except KeyboardInterrupt:
        cancelled.set()
        return

    # --- 消費迴圈 ---
    while True:
        if item is sentinel:
            if verbose:
                print(f"[prefetch] 結束 produced={stats['produced']} consumed={stats['consumed']}", flush=True)
            break

        stats["consumed"] += 1
        yield item

        if heartbeat and heartbeat > 0:
            try:
                item = q.get(timeout=heartbeat)
            except queue.Empty:
                print(f"[prefetch] 等下一批… qsize={q.qsize()} prod={stats['produced']} "
                      f"cons={stats['consumed']} thread_alive={t.is_alive()}", flush=True)
                continue
        else:
            item = q.get()


        
def prefetch_iter_old(
    src_iter,
    maxsize=1000,
    first_batch_timeout=20,      # 首批等待上限(秒)，>0 才會啟用
    heartbeat=30,                # 後續每隔 N 秒沒拿到資料就吐心跳
    sentinel=None,               # 終止記號；None 表示內部自建
    on_error=None,               # 背景取件出錯時的回呼
    fallback_on_timeout=True,    # 首批逾時是否回退直通
    name="ES-prefetch",          # 執行緒命名，方便 dump 追
    verbose=False                # 結束時印統計
):
    if sentinel is None:
        sentinel = object()

    q = queue.Queue(maxsize=maxsize)
    stats = {"produced": 0, "consumed": 0}
    cancelled = threading.Event()  # 用來在回退時通知 producer 停止

    def _producer():
        try:
            for item in src_iter:
                if cancelled.is_set():
                    break
                q.put(item)  # 允許背壓
                stats["produced"] += 1
        except Exception as e:
            if on_error:
                on_error(e)
        finally:
            try:
                q.put(sentinel)
            except Exception:
                pass

    t = threading.Thread(target=_producer, daemon=True, name=name)
    t.start()

    # --- 首批等待 ---
    try:
        if first_batch_timeout and first_batch_timeout > 0:
            try:
                item = q.get(timeout=first_batch_timeout)
            except queue.Empty:
                print(f"[prefetch] 首批 > {first_batch_timeout}s 未到", flush=True)
                if fallback_on_timeout:
                    print("[prefetch] 回退為直通 iterator（不預取）", flush=True)
                    cancelled.set()  # 通知背景 producer 停下
                    for x in src_iter:     # 直通：直接把原始 iterator 交回
                        yield x
                    return
                else:
                    # 不回退就持續等，期間印心跳
                    while True:
                        try:
                            item = q.get(timeout=heartbeat or 30)
                            break
                        except queue.Empty:
                            print(f"[prefetch] 仍在等首批… thread_alive={t.is_alive()}", flush=True)
        else:
            item = q.get()
    except KeyboardInterrupt:
        cancelled.set()
        return

    # --- 消費迴圈（帶心跳）---
    while True:
        if item is sentinel:
            if verbose:
                print(f"[prefetch] 結束 produced={stats['produced']} "
                      f"consumed={stats['consumed']}", flush=True)
            break

        stats["consumed"] += 1
        yield item

        if heartbeat and heartbeat > 0:
            try:
                item = q.get(timeout=heartbeat)
            except queue.Empty:
                print(f"[prefetch] 等下一批… qsize={q.qsize()} "
                      f"prod={stats['produced']} cons={stats['consumed']} "
                      f"thread_alive={t.is_alive()}", flush=True)
                continue
        else:
            item = q.get()
def _tap_progress(it, ctx):
    for x in it:
        try:
            ctx.last_progress_ts = time.time()
        except Exception:
            pass
        yield x
# ---------- 建立 iterator ----------
def build_pending_iter_es(adapter, ctx):
    stage_extra_cols = []
    for stage in (getattr(ctx, "stages", None) or []):
        if isinstance(stage, dict):
            col = str(stage.get("input_col", "")).strip()
            if col and col != adapter.cfg.get("input_col"):
                stage_extra_cols.append(col)
            route_map = stage.get("route_map")
            if isinstance(route_map, dict):
                for route_item in route_map.values():
                    if isinstance(route_item, dict):
                        col = str(route_item.get("input_col", route_item.get("from_col", ""))).strip()
                        if col and col != adapter.cfg.get("input_col"):
                            stage_extra_cols.append(col)
    # 這不是另一個 runtime input_col，而是把各 stage YAML 宣告的 input_col
    # 預先掛到 adapter cfg，讓 adapter 單次 scan 時一併取回供 stage_source_inputs 使用。
    adapter.cfg["stage_source_input_cols"] = sorted(set(stage_extra_cols))

    base = adapter.select_pending_rows(
        src_table=adapter.cfg["src_index"],
        tgt_table=adapter.cfg["tgt_index"],
        pk=adapter.cfg["id_col"],
        input_col=adapter.cfg["input_col"],
        output_col=adapter.cfg["output_col"],
        record_update_time=getattr(ctx, "record_update_time", False),
        fetch_size=getattr(ctx, "fetch_size", 500),
    )

    cfg = getattr(adapter, "cfg", {})
    buf      = int(cfg.get("es_prefetch_buffer",        getattr(ctx, "es_prefetch_buffer", 1000)))
    first_to = int(cfg.get("es_prefetch_first_timeout", 20))
    hb       = int(cfg.get("es_prefetch_heartbeat",     30))
    fallback = bool(cfg.get("es_prefetch_fallback",     True))
    verbose  = bool(cfg.get("es_prefetch_verbose",      False))

    if buf <= 0:
        print("[prefetch] 關閉（es_prefetch_buffer<=0）→ 直通模式", flush=True)
        # ✅ 直通模式也要 bump 進度
        return _tap_progress(base, ctx)

    return _tap_progress(
        prefetch_iter(
            base,
            maxsize=buf,
            first_batch_timeout=first_to,
            heartbeat=hb,
            fallback_on_timeout=fallback,
            on_error=lambda e: print(f"[prefetch] ES 取件錯誤：{e}", flush=True),
            verbose=verbose
        ),
        ctx
    )


