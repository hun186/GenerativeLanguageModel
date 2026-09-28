# czjLLM/es_mode/entry/steps_es.py
from typing import Any, Dict, List, Tuple
from pathlib import Path
import importlib.util
import time
import queue, threading
from elasticsearch import Elasticsearch

from utils.selector import OptionSelector

from czjLLM.es_mode.config.config_loader_es import load_es_cfg, InteractivePolicy, NonInteractivePolicy
from czjLLM.es_mode.config.rerun_logging import log_rerun_config, resolve_rerun_config
from czjLLM.es_mode.config.stage_cfg import build_es_stage_cfg, stage_name_from_cfg
#from czjLLM.es_mode.runtime.sinks.es_sink import ESSink

from czjLLM.es_mode.adapters.elasticsearch_adapter import ElasticsearchAdapter

_SENTINEL = object()


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
    # 主 YAML 可覆寫 es_config_file 內的 rerun 設定，方便用 pipeline_hash
    # 做測試重跑；其餘未覆寫欄位仍沿用 ES config。
    rerun_cfg, rerun_diagnostics = resolve_rerun_config(es_cfg, get_param)
    log_rerun_config(rerun_cfg, rerun_diagnostics)

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
        "output_profile": es_cfg.get("output_profile", None),
        "output_profile_plugins": es_cfg.get("output_profile_plugins", None),
        "output_profiles": es_cfg.get("output_profiles", None),
        "pipeline_name": es_cfg.get("pipeline_name", None),
        "pipeline": es_cfg.get("pipeline", None),
        "stages": es_cfg.get("stages", None),
        "routes": es_cfg.get("routes", None),
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
        "es_prefetch_buffer": es_cfg.get("es_prefetch_buffer", 0),
        "es_prefetch_first_timeout": es_cfg.get("es_prefetch_first_timeout", 20),
        "es_writeback_rules": es_cfg.get("es_writeback_rules", None),
        "es_output_mappings": es_cfg.get("es_output_mappings", None),
        "es_payload_date_normalize_fields": es_cfg.get("es_payload_date_normalize_fields", None),
        "es_flatten_writeback_rules": es_cfg.get("es_flatten_writeback_rules", None),
        "flatten_json_output": es_cfg.get("flatten_json_output", None),
        # －－－－ 新增這三項：讓 Adapter 知道怎麼判斷需重跑 －－－－
        "rerun": rerun_cfg,                                      # ★ 必傳
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
    input_col = (
        getattr(args, "input_col", None)
        or get_param("input_col", None)
        or es_cfg.get("input_col")
    )
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
    output_col = (
        getattr(args, "output_col", None)
        or get_param("output_col", None)
        or es_cfg.get("output_col")
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

    ctx.record_update_time = get_param("record_update_time")
    if ctx.record_update_time is None:
        ctx.record_update_time = (input("⏱️ 要不要寫 update_time？(Y/n)：").strip().lower() != "n")
        
    # ---------- 回灌到 ctx ----------
    # 若你仍有 ctx.es_index，可在 resolve 時塞；此處不直接使用 index，改由 adapter.cfg 管理
    ctx.primary_key = primary_key
    ctx.input_col = input_col
    ctx.output_col = output_col
    ctx.output_profile = (
        getattr(args, "output_profile", None)
        or get_param("output_profile", es_cfg.get("output_profile", None))
        or "auto"
    )
    ctx.output_profile_plugins = get_param("output_profile_plugins", es_cfg.get("output_profile_plugins", None))
    ctx.output_profiles = get_param("output_profiles", es_cfg.get("output_profiles", None))
    ctx.legacy_event_output_cols = get_param("legacy_event_output_cols", es_cfg.get("legacy_event_output_cols", None))
    ctx.stage_cfg = build_es_stage_cfg(get_param, es_cfg)
    ctx.pipeline_name = (
        getattr(args, "pipeline_name", None)
        or stage_name_from_cfg(ctx.stage_cfg)
        or get_param("pipeline_name", es_cfg.get("pipeline_name", None))
        or None
    )
    if isinstance(ctx.stage_cfg, dict) and ctx.stage_cfg.get("stages"):
        ctx.stages = ctx.stage_cfg.get("stages")

    # ES 多階段寫回規則沿用既有 row_merger 的 sql_writeback_rules 解析。
    es_writeback_rules = get_param("es_writeback_rules", es_cfg.get("es_writeback_rules", [])) or []
    if es_writeback_rules and not isinstance(es_writeback_rules, list):
        es_writeback_rules = []
    ctx.es_writeback_rules = es_writeback_rules
    ctx.sql_writeback_rules = es_writeback_rules
    ctx.es_payload_date_normalize_fields = get_param(
        "es_payload_date_normalize_fields",
        es_cfg.get("es_payload_date_normalize_fields", []),
    ) or []
    # ES 原生可保存 object/nested；避免 SQL/Table flatten 規則誤套到 ES。
    ctx.flatten_json_output = False
    ctx.sql_flatten_writeback_rules = []
    ctx.es_flatten_writeback_rules = []

    output_cols = []
    for col in [output_col, *[r.get("output_col") for r in es_writeback_rules if isinstance(r, dict)]]:
        if col and col not in output_cols:
            output_cols.append(col)
    ctx.output_cols = output_cols or [output_col]

    # ---------- 同步到 adapter.cfg（讓後續 build_pending_iter_es 直接使用） ----------
    es_cfg["id_col"]   = primary_key
    es_cfg["input_col"]  = input_col
    es_cfg["output_col"] = output_col
    es_cfg["output_profile"] = ctx.output_profile
    es_cfg["output_profile_plugins"] = ctx.output_profile_plugins
    es_cfg["output_profiles"] = ctx.output_profiles
    es_cfg["legacy_event_output_cols"] = ctx.legacy_event_output_cols
    es_cfg["output_cols"] = ctx.output_cols
    es_cfg["es_writeback_rules"] = ctx.es_writeback_rules
    es_cfg["es_payload_date_normalize_fields"] = ctx.es_payload_date_normalize_fields
    if ctx.pipeline_name:
        es_cfg["pipeline_name"] = ctx.pipeline_name
    es_cfg["stage_cfg"] = ctx.stage_cfg
    # 若你需要此時才決定 index 名稱，也可在這裡放：
    # es_cfg["src_index"] = es_cfg.get("src_index") or input("請輸入來源 index：").strip()
    # es_cfg["tgt_index"] = es_cfg.get("tgt_index") or es_cfg["src_index"]

    # ---------- 回傳給 ensure_schemas_es 的 columns（建議只補目標 index 的 output 欄位） ----------
    # 型別字串用簡單語義；ElasticsearchAdapter.ensure_columns 會把 "TEXT" 轉成 text+keyword
    type_map = {
        "keyword": "keyword",
        "text": "TEXT",
        "nested": "NESTED",
        "object": "OBJECT",
        "date": "date",
        "long": "long",
        "double": "double",
    }
    columns = [(output_col, "TEXT")]
    for rule in es_writeback_rules:
        if not isinstance(rule, dict):
            continue
        col = rule.get("output_col")
        if not col:
            continue
        typ = type_map.get(str(rule.get("output_type", "TEXT")).strip().lower(), "TEXT")
        if (col, typ) not in columns:
            columns.append((col, typ))
    return columns

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
    # 1) 確保 index 存在
    adapter.ensure_table(adapter.cfg["src_index"])
    adapter.ensure_table(adapter.cfg["tgt_index"])

    tgt_index  = adapter.cfg["tgt_index"]
    out_field  = getattr(ctx, "output_col", "llm_result")                 # 主要輸出欄位
    out_type   = getattr(ctx, "es_output_type", "NESTED").upper()         # "NESTED"/"OBJECT"

    # 2) 若指定 mapping 檔，先交由 YAML 套用（只新增，不變更既有型別）
    es_apply_mapping = adapter.cfg.get("es_apply_mapping", False)
    mapping_file     = adapter.cfg.get("mapping_file")
    if es_apply_mapping and mapping_file:
        try:
            adapter.apply_mapping_file(tgt_index, mapping_file)
        except Exception as ex:
            print(f"⚠️ 套用 mapping 檔失敗（將退回最小化策略）：{ex}")

    # 多欄位 ES writeback 可在各 rule 指定 mapping_file。這裡逐一套用，
    # 讓 extract/audit/fallback 等不同輸出欄位都能在寫入前取得正確 mapping。
    if es_apply_mapping:
        applied_rule_mappings = {str(mapping_file or "").strip()} if mapping_file else set()
        for rule in (getattr(ctx, "es_writeback_rules", None) or []):
            if not isinstance(rule, dict):
                continue
            rule_mapping = str(rule.get("mapping_file", "") or "").strip()
            if not rule_mapping or rule_mapping in applied_rule_mappings:
                continue
            rule_index = str(rule.get("index", "") or tgt_index).strip() or tgt_index
            try:
                adapter.apply_mapping_file(rule_index, rule_mapping)
                applied_rule_mappings.add(rule_mapping)
            except Exception as ex:
                print(f"⚠️ 套用 writeback rule mapping 檔失敗（{rule_mapping}）：{ex}")

    # 3) output 欄位（最小化備援）：不存在才建 type
    try:
        node = adapter.get_field_mapping(tgt_index, out_field)
        if node is None:
            body = {"properties": {out_field: {"type": "nested"}}} \
                   if out_type == "NESTED" else \
                   {"properties": {out_field: {"type": "object"}}}
            adapter.es.indices.put_mapping(index=tgt_index, body=body)  # type: ignore
            print(f"✅ 已在 index='{tgt_index}' 新增欄位 '{out_field}'（type={out_type}）")
        else:
            cur = node.get("type", "object")
            ok  = (out_type == "NESTED" and cur == "nested") or (out_type == "OBJECT" and cur in ["object", None])
            if not ok:
                print(f"⚠️ 欄位 '{out_field}' 型別為 {cur}，與期望 {out_type} 不符；請改用另一 output_col 或重建索引。")
    except Exception as ex:
        print(f"⚠️ 確認/建立 output 欄位映射時發生例外：{ex}")
    # 4) meta 欄位（最小化備援）：不存在才建；存在則僅檢查型別，不改動
    try:
        rr = (adapter.cfg or {}).get("rerun") or {}
        out_field  = getattr(ctx, "output_col", "llm_result")
        meta_field = rr.get("meta_field") or getattr(ctx, "meta_field", None) or f"{out_field}_meta"
        meta_type  = getattr(ctx, "es_meta_type", "OBJECT").upper()  # "OBJECT" / "NESTED"
    
        meta_node = adapter.get_field_mapping(tgt_index, meta_field)
        if meta_node is None:
            node = {"type": "nested"} if meta_type == "NESTED" else {"type": "object"}
            # 🔽 一次放進常用子欄位（僅在「不存在」時建立）
            node["properties"] = {
                "processed_at":  {"type": "date"},    # ISO8601 (e.g. 2025-11-10T08:00:00Z)
                "model_tag":     {"type": "keyword"},
                "model_name":    {"type": "keyword"},
                "base_url_alias":{"type": "keyword"},
                "num_ctx":       {"type": "integer"},
                "temperature":   {"type": "float"},
                "model_version": {"type": "keyword"},
                "pipeline_hash": {"type": "keyword"},
                #"model_spec":    {"type": "keyword"},
                "source":        {"type": "keyword"}, # 自定：資料來源/任務來源
                "channel":       {"type": "keyword"}, # 自定：任務 channel
                "task":          {"type": "keyword"}, # 自定：任務名稱
                "force_reason":  {"type": "keyword"}, # 自定：為何強制重跑
                "output_profile": {"type": "keyword"}, # 自定：輸出/正規化 profile
                "pipeline_name":  {"type": "keyword"}, # 自定：資料處理流路名稱
                "pipeline_version": {"type": "keyword"}, # 自定：資料處理流路版本
                "pipeline_enabled": {"type": "boolean"}, # 自定：是否啟用多階段流路
            }
            body = {"properties": {meta_field: node}}
            adapter.es.indices.put_mapping(index=tgt_index, body=body)  # type: ignore
            print(f"✅ 已在 index='{tgt_index}' 新增欄位 '{meta_field}'（type={node['type']}，含預設子欄位）")
        else:
            cur = meta_node.get("type", "object")
            want_nested = (meta_type == "NESTED")
            ok = (want_nested and cur == "nested") or (not want_nested and cur in ["object", None])
            if not ok:
                print(f"⚠️ meta 欄位 '{meta_field}' 型別為 {cur}，與期望 {meta_type} 不符；建議調整 YAML 或重建索引。")
    except Exception as ex:
        print(f"⚠️ 確認/建立 meta 欄位映射時發生例外：{ex}")
    
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
    ctx._pending_adapter = adapter
    ctx._pending_tgt_table = adapter.cfg["tgt_index"]
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
    buf      = int(cfg.get("es_prefetch_buffer",        getattr(ctx, "es_prefetch_buffer", 0)))
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
