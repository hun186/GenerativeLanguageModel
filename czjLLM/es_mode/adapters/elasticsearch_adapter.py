#es_mode/adapters/elasticsearch_adapter.py

from typing import Any, Dict, List, Tuple, Optional
import json

try:
    # 官方 7.x 客戶端
    from elasticsearch import Elasticsearch, helpers  # type: ignore
except Exception:  # pragma: no cover
    Elasticsearch = None  # type: ignore
    helpers = None  # type: ignore

from .pending_policy import ElasticsearchPendingPolicyMixin
from .value_helpers import (
    extract_by_path as _extract_by_path,
    normalize_scalar as _norm_scalar,
)


class ElasticsearchAdapter(ElasticsearchPendingPolicyMixin):
    """
    目標：在既有 LLM 分析框架中，提供與 SQL 模式相近的掛接點，
    以便後續流程（批次擷取待處理資料 → 呼叫任務 → 回寫結果）不需重寫。

    設計重點：
    1) 兼容「單一 Index」與「雙 Index（來源/結果分離）」兩種部署。
       - 單一 Index：同文件同時包含 input 與 output 欄位 → 直接用查詢條件篩出「尚未產生輸出」的文件。
       - 雙 Index：來源 index 只有 input；結果 index 以同一主鍵（通常對應 ES 的 _id）寫入結果。
         → 以 scan 從來源拉一批 id，再用 mget 檢查結果 index 有沒有對應輸出；沒有就視為待處理。

    2) 與 SQL 版本介面對齊：
       - ensure_table / ensure_columns 在 ES 中對應為 ensure_index / ensure_fields（放在此類中實作為 no-op 或簡易 mapping 升級）。
       - select_pending_rows 回傳 Iterable[(pk_value, input_string)]，供上層流水線直接消費。

    3) 效能：
       - 使用 helpers.scan 走游標（scroll）避免一次性大量取回。
       - 雙 Index 模式下，先批次收集一組 src _id，再用 mget 一次檢查，減少往返。

    4) 欄位空白判定：
       - 預設視 output 欄位「不存在/為空字串」都算待處理。
       - 若 output 為 text+keyword，會優先嘗試以 term 查 keyword 子欄位的空字串（依實際 mapping 決定）。

    cfg（設定）範例：
    cfg = {
        "hosts": ["http://localhost:9200"],
        "http_auth": ("elastic", "changeme"),  # 或 None
        "timeout": 60,
        "src_index": "my_source",
        "tgt_index": "my_results",  # 若與 src_index 相同 → 視為單一 Index 模式
        "pk_field": "_id",          # 主鍵欄位；若使用 ES 的 _id，填 "_id"
        "input_col": "text_raw",
        "output_col": ["llm_output"],
    }
    """

    def __init__(self, cfg: Dict[str, Any]):
        self.cfg = cfg
        self.es: Optional[Elasticsearch] = None
    #'''
    # ✅ 支援 with 語法
    def __enter__(self):
        if self.es is None:
            self.connect()
        return self

    def __exit__(self, exc_type, exc, tb):
        try:
            self.close()
        finally:
            return False  # 不吞掉例外
    #'''  
    # --- 連線生命週期 ------------------------------------------------------
    def connect(self):
        if Elasticsearch is None:
            raise ImportError("elasticsearch 客戶端未安裝，請先 pip install 'elasticsearch<8'（對 ES 7.x）")
    
        # ---- 1) 相容兩種設定命名：hosts/http_auth 或 es_host/es_user/es_pass ----
        hosts = self.cfg.get("hosts")
        if not hosts:
            es_host = self.cfg.get("es_host") or "http://localhost:9200"
            hosts = [es_host] if isinstance(es_host, str) else es_host
    
        http_auth = self.cfg.get("http_auth")
        if http_auth is None:
            u = self.cfg.get("es_user")
            p = self.cfg.get("es_pass")
            if u is not None and p is not None:
                http_auth = (u, p)
    
        timeout = self.cfg.get("timeout", self.cfg.get("es_timeout", 60))
    
        # ---- 2) TLS/HTTPS 相關參數 ----
        # ✅ 只要 hosts 裡是 https:// 就會走 TLS；但自簽憑證需要 ca_certs 或關閉驗證
        ca_certs = self.cfg.get("es_ca_certs") or self.cfg.get("ca_certs")
        verify_certs = self.cfg.get("es_verify_certs", True)
        ssl_assert_hostname = self.cfg.get("es_ssl_assert_hostname", False)
    
        # elasticsearch 7.x client 參數名：verify_certs / ca_certs / ssl_assert_hostname
        # 但不同小版本可能略有差異，所以做保守處理：只有在需要時才傳
        es_kwargs = dict(
            hosts=hosts,
            http_auth=http_auth,
            timeout=timeout,
            max_retries=self.cfg.get("es_max_retries", 3),
            retry_on_timeout=self.cfg.get("es_retry_on_timeout", True),
        )
    
        # 只有 https 才塞 TLS 參數（避免 http 也帶參數造成困擾）
        any_https = any(str(h).lower().startswith("https://") for h in (hosts or []))
        if any_https:
            # 1) 驗證開啟：建議一定給 CA
            if verify_certs:
                if not ca_certs:
                    raise ValueError(
                        "目前是 https 連線且 verify_certs=True，但未提供 es_ca_certs。"
                        "請在 cfg 加 es_ca_certs 指向 http_ca.crt，或暫時設 es_verify_certs=False。"
                    )
                es_kwargs["ca_certs"] = ca_certs
                es_kwargs["verify_certs"] = True
                es_kwargs["ssl_assert_hostname"] = ssl_assert_hostname
            else:
                # 2) 救急：關閉驗證（不推薦長期使用）
                es_kwargs["verify_certs"] = False
                es_kwargs["ssl_show_warn"] = self.cfg.get("es_ssl_show_warn", False)
    
        self.es = Elasticsearch(**es_kwargs)
    
        # 簡單健康檢查
        self.es.info()
        return self

    def connect_1219(self):
        if Elasticsearch is None:
            raise ImportError("elasticsearch 客戶端未安裝，請先 pip install 'elasticsearch<8'（對 ES 7.x）")
        self.es = Elasticsearch(
            hosts=self.cfg.get("hosts", ["http://localhost:9200"]),
            http_auth=self.cfg.get("http_auth"),
            timeout=self.cfg.get("timeout", 60),
            max_retries=self.cfg.get("es_max_retries", 3),     # ✅
            retry_on_timeout=self.cfg.get("es_retry_on_timeout", True),  # ✅
        )
        # 簡單健康檢查
        self.es.info()
        return self

    def close(self):
        if self.es is not None:
            try:
                self.es.transport.close()
            finally:
                self.es = None

    # 取得 index 的 mapping（快取可自行加）
    def get_index_mapping(self, index: str) -> dict:
        assert self.es is not None
        return self.es.indices.get_mapping(index=index).get(index, {}).get("mappings", {})

    # 依 dot.path 取得欄位定義（回傳該層 properties 的節點）
    def get_field_mapping(self, index: str, field_path: str):
        """
        回傳欄位節點（可含 type/properties/fields），若不存在回 None。
        支援 a.b.c 逐層深入；頂層從 properties 直接取，不再誤用 node['properties']。
        """
        m = self.get_index_mapping(index)
        props = m.get("properties", {}) or {}
        node = props
        parts = field_path.split(".")
    
        for i, part in enumerate(parts):
            # 先在目前這層的 properties 直接找欄位
            if part not in node:
                return None
            node = node[part]  # 走到該欄位節點
    
            # 若還有更下一層，則切到該節點的 properties 繼續往下找
            if i < len(parts) - 1:
                node = node.get("properties", {})
                if not isinstance(node, dict):
                    return None
    
        return node  # 最終節點（可能含 type / properties / fields）


    def get_field_mapping_old(self, index: str, field_path: str):
        m = self.get_index_mapping(index)
        props = m.get("properties", {})
        node = props
        for part in field_path.split("."):
            if "properties" in node and part in node["properties"]:
                node = node["properties"][part]
            else:
                return None
        return node

    # 讀 YAML/JSON 檔並套用 put_mapping（只會新增，不會改已存在型別）
    def apply_mapping_file(self, index: str, path: str):
        from pathlib import Path
        ext = Path(path).suffix.lower()
    
        with open(path, "r", encoding="utf-8") as f:
            if ext in [".yml", ".yaml"]:
                import yaml
                body = yaml.safe_load(f)
            else:
                import json
                body = json.load(f)
    
        assert self.es is not None
    
        # ---- A. 抓套用前的欄位扁平路徑 ----
        def _flatten_props(props: dict, prefix: str = "") -> dict:
            """
            回傳 { 'a.b.c': {'type': 'text', ...}, ... }；
            object/nested 也會記錄節點自己（若有 type），並遞迴其 properties。
            會同時展開 keyword 等子欄位（fields）。
            """
            out = {}
            for k, node in (props or {}).items():
                path = f"{prefix}.{k}" if prefix else k
                ntype = node.get("type")
    
                # 記錄目前節點（只要有 type 就列；object 無 type 也可跳過顯示）
                if ntype:
                    out[path] = node
    
                # 1) 進一步展開 properties（object/nested 的子欄位）
                if "properties" in node and isinstance(node["properties"], dict):
                    out.update(_flatten_props(node["properties"], path))
    
                # 2) 展開 multi-fields（例如 text -> keyword 子欄位）
                if "fields" in node and isinstance(node["fields"], dict):
                    for fk, fnode in node["fields"].items():
                        fpath = f"{path}.{fk}"
                        out[fpath] = fnode
            return out
    
        def _mapping_props_of_index(idx: str) -> dict:
            m = self.es.indices.get_mapping(index=idx)
            return m.get(idx, {}).get("mappings", {}).get("properties", {}) or {}
    
        before_props = _mapping_props_of_index(index)
        before_flat  = _flatten_props(before_props)
    
        # ---- B. 套用 mapping ----
        self.es.indices.put_mapping(index=index, body=body)
    
        # ---- C. 抓套用後的欄位並做差集 ----
        after_props = _mapping_props_of_index(index)
        after_flat  = _flatten_props(after_props)
    
        before_keys = set(before_flat.keys())
        after_keys  = set(after_flat.keys())
        added_keys  = sorted(list(after_keys - before_keys))
    
        if added_keys:
            print(f"✅ 已套用 mapping 檔到 index='{index}'：{path}")
            print("📌 本次新增欄位（含型別）如下：")
            for k in added_keys:
                t = after_flat.get(k, {}).get("type", "(unknown)")
                print(f"  - {k}  (type={t})")
        else:
            print(f"ℹ️ 套用 mapping 檔到 index='{index}' 完成（此次未新增新欄位）：{path}")
            print("   ※ 若你使用的是 dynamic_templates，實際欄位會在首次寫入對應資料後才出現。")

    # 讀 YAML/JSON 檔並套用 put_mapping（只會新增，不會改已存在型別）
    def apply_mapping_file_OLD(self, index: str, path: str):
        #import os, json
        from pathlib import Path
        ext = Path(path).suffix.lower()
        with open(path, "r", encoding="utf-8") as f:
            if ext in [".yml", ".yaml"]:
                import yaml
                body = yaml.safe_load(f)
            else:
                body = json.load(f)
        assert self.es is not None
        self.es.indices.put_mapping(index=index, body=body)
        
    # --- 與 SQL 介面對齊的「保留」方法（ES 版本） ---------------------------
    def list_columns(self, index: str) -> List[str]:
        """回傳 index 的 mapping 欄位名（僅作對齊用途）。"""
        assert self.es is not None
        mapping = self.es.indices.get_mapping(index=index)
        props = mapping.get(index, {}).get("mappings", {}).get("properties", {})
        return sorted(list(props.keys()))

    def ensure_table(self, index: str, *_args, **_kwargs):
        """確保 index 存在。對齊 SQL ensure_table；若不存在則以最簡 mapping 建立。"""
        assert self.es is not None
        if not self.es.indices.exists(index=index):
            body = {"mappings": {"properties": {}}}
            self.es.indices.create(index=index, body=body)
    def ensure_columns(self, index: str, columns: List[Tuple[str, str]]):
        assert self.es is not None
        if not columns:
            return
    
        index_map = self.es.indices.get_mapping(index=index)
        props = index_map.get(index, {}).get("mappings", {}).get("properties", {})
    
        to_add: Dict[str, Dict[str, Any]] = {}
        for name, ctype in columns:
            if name in props:
                continue
            ctype_lower = (ctype or "").lower()
    
            if ctype_lower in ("object", "json", "map"):
                to_add[name] = {"type": "object"}                # 一般物件
            elif ctype_lower in ("nested",):
                to_add[name] = {"type": "nested"}                # 陣列物件要用這個，利於精準查詢
            elif any(t in ctype_lower for t in ["int", "bigint", "smallint", "tinyint"]):
                to_add[name] = {"type": "long"}
            elif any(t in ctype_lower for t in ["float", "double", "real", "decimal", "numeric"]):
                to_add[name] = {"type": "double"}
            elif any(t in ctype_lower for t in ["date", "time", "datetime", "timestamp"]):
                to_add[name] = {"type": "date"}
            else:
                to_add[name] = {"type": "text", "fields": {"keyword": {"type": "keyword"}}}
    
        if to_add:
            self.es.indices.put_mapping(index=index, body={"properties": to_add})
            
    # --- ES 版本的 pending 擷取 --------------------------------------------

    def is_row_pending(self, *, tgt_table: str, pk: str, pk_value: Any, output_cols: List[str]) -> bool:
        return self.check_row_pending(tgt_table=tgt_table, pk=pk, pk_value=pk_value, output_cols=output_cols).pending

    def check_row_pending(self, *, tgt_table: str, pk: str, pk_value: Any, output_cols: List[str]):
        if self.es is None:
            raise RuntimeError("Elasticsearch client 尚未連線")
        from czjLLM.common.pending_decision import PendingDecision
        output_cols_resolved = self._resolve_output_cols(output_cols=output_cols)
        if not output_cols_resolved:
            return PendingDecision(True, "missing_output")
        key_val = _norm_scalar(pk_value)
        if key_val is None:
            return PendingDecision(False, "fresh_completed")
        timeout = int(self.cfg.get("es_request_timeout", 60))
        if pk == "_id":
            response = self.es.mget(index=tgt_table, body={"ids": [key_val]}, request_timeout=timeout)
            docs = response.get("docs", [])
            if not docs or not docs[0].get("found"):
                return PendingDecision(True, "row_missing")
            return self.check_source_pending(docs[0].get("_source", {}) or {}, output_cols_resolved)
        suffix = self.cfg.get("pk_keyword_suffix", ".keyword")
        result = self.es.search(index=tgt_table, body={"query": {"term": {pk + suffix: key_val}}, "size": 1}, request_timeout=timeout)
        hits = result.get("hits", {}).get("hits", [])
        if not hits:
            return PendingDecision(True, "row_missing")
        return self.check_source_pending(hits[0].get("_source", {}) or {}, output_cols_resolved)

    def select_pending_rows(
        self,
        *,
        src_table: str,
        tgt_table: str,
        pk: str,
        input_col: str,
        output_col: Any = None,
        output_cols: Any = None,
        record_update_time: bool = False,
        fetch_size: int = 500,
    ):
        """
        以 helpers.scan 串流完整待處理集合（有 input、無有效 output）。

        input_col 是本列排程/切片的主文字來源。若多階段 YAML 的某些 stage
        宣告不同 input_col，呼叫端會先把那些 dot-path 放到 cfg["stage_source_input_cols"]；
        adapter 只負責把它們一併從 _source 取回並隨列回傳為 source_inputs，
        讓後續 stage 可用不同來源文字組 prompt。
        """
        output_cols_resolved = self._resolve_output_cols(output_col=output_col, output_cols=output_cols)
        stage_source_input_cols = self.cfg.get("stage_source_input_cols", []) or []
        assert self.es is not None
    
        if src_table == tgt_table:
            # 單一 index：同文件包含 input/output
            for item in self._scan_single_index_pending(src_table, pk, input_col, output_cols_resolved, fetch_size, stage_input_cols=stage_source_input_cols):
                yield item
        else:
            # 來源/結果分離：src 提 id + input，tgt 用 mget 檢是否已有 output
            for item in self._scan_dual_index_pending(src_table, tgt_table, pk, input_col, output_cols_resolved, fetch_size, stage_input_cols=stage_source_input_cols):
                yield item
    def _yield_pending_from_batch(
        self,
        *,
        tgt_index: str,
        pk: str,
        batch_ids: List[str],
        batch_docs: Dict[str, Any],
        output_cols: Any,
        request_timeout: int,
    ):
        """
        檢查 batch_ids 在 tgt_index 是否已有『新鮮 output』，
        沒有的就 yield 出來。函式內不重新建立 batch，直接清空傳入容器。
        """
        if not batch_ids:
            return
    
        present = self._bulk_check_present_nonempty(
            tgt_index=tgt_index,
            pk=pk,
            ids=batch_ids,
            output_cols=output_cols,
            request_timeout=request_timeout,
        )
    
        for _id in batch_ids:
            if _id not in present:
                doc_entry = batch_docs[_id]
                if isinstance(doc_entry, tuple) and len(doc_entry) == 2:
                    yield (_id, doc_entry[0], doc_entry[1])
                else:
                    yield (_id, doc_entry)
    
        batch_ids.clear()
        batch_docs.clear()
        
    def _scan_single_index_pending(self, index, pk, input_col, output_cols, fetch_size, stage_input_cols: List[str] | None = None):
        assert self.es is not None
        output_cols_resolved = self._resolve_output_cols(output_cols=output_cols)
        filters = self._build_pending_filters()
        rt = int(self.cfg.get("es_request_timeout", 60))
        keepalive = self.cfg.get("es_scroll_keepalive", "2m")
        
        needs_rerun_clauses = [c for c in (self._needs_rerun_clause(index, col) for col in output_cols_resolved) if c]
        python_freshness_scan = self._requires_python_freshness_scan(output_cols_resolved)
        
        # ★ 取得備援日期欄位（你在 cfg 或 rerun 內放的）
        rr = (self.cfg or {}).get("rerun") or {}
        fallback_date = rr.get("fallback_date_field") \
                         or self.cfg.get("fallback_date_field") \
                         or "update_time_ai"
        # 組 _source 欄位清單：必帶 input/output；有 meta 再加；pk 不是 _id 也要加
        stage_input_cols = [c for c in (stage_input_cols or []) if c and c != input_col]
        src_fields = ([input_col] + output_cols_resolved
                      + self._required_output_source_fields(output_cols_resolved)
                      + self._output_meta_fields(output_cols_resolved) + stage_input_cols)
        if pk != "_id":
            src_fields.append(pk)
        # 可選：也讓 _source 直接帶上日期欄位（保險起見）
        if fallback_date and fallback_date not in src_fields:
            src_fields.append(fallback_date)
        src_fields = list(dict.fromkeys(src_fields))
        query_bool = {
            "must": [{"exists": {"field": input_col}}],
            "filter": filters,
        }
        if not python_freshness_scan:
            query_bool.update({
                "should": [
                    *[{"bool": {"must_not": [{"exists": {"field": col}}]}} for col in output_cols_resolved],
                    *needs_rerun_clauses,
                ],
                "minimum_should_match": 1,
            })
        body = {
            "query": {"bool": query_bool},
            "_source": src_fields,
            # ★ 關鍵：用 docvalue_fields 拿到標準化的日期值（會出現在 hit['fields']）
            "docvalue_fields": [fallback_date] if fallback_date else [],
            "track_total_hits": True
        }

        print("[DEBUG] pending query:", json.dumps(body["query"], ensure_ascii=False)[:3000])
        
        # 先用 search 取樣驗證：理論上 hits > 0
        try:
            probe = self.es.search(
                index=index,
                body={
                    "query": body["query"],
                    "_source": [input_col],
                    "docvalue_fields": [fallback_date] if fallback_date else [],
                    "size": 3
                }
            )
            print("[DEBUG] probe hits:", len(probe.get("hits", {}).get("hits", [])))
        except Exception as e:
            print("[DEBUG] probe error:", repr(e))

            
        scan_iter = helpers.scan(
            client=self.es, index=index, query=body,
            size=int(fetch_size or 500), preserve_order=False,
            scroll=keepalive, request_timeout=rt, clear_scroll=True
        )
        printed = False
        for hit in scan_iter:
            src = hit.get("_source", {}) or {}
        
            # ★ 合併 docvalue_fields：把 hit['fields'] 的單值拉平進 src
            flds = hit.get("fields", {}) or {}
            for k, v in flds.items():
                if k not in src:  # 不覆蓋 _source 既有值
                    src[k] = (v[0] if isinstance(v, list) and len(v) == 1 else v)
        
            if not printed:
                print("[DEBUG] sample _id:", hit.get("_id"))
                first_output_col = output_cols_resolved[0] if output_cols_resolved else ""
                print("[DEBUG] has output?", first_output_col.split(".")[0] in (src or {}))
                print("[DEBUG] update_time_ai:", src.get("update_time_ai"))  # ← 現在會有值
                printed = True
                
            pk_val = hit.get("_id") if pk == "_id" else _extract_by_path(src, pk)
            if isinstance(pk_val, list): pk_val = pk_val[0] if pk_val else None
            if pk_val is None: continue
    
            # 先在客戶端過濾「已完成」
            #outv = _extract_by_path(src, output_col)
            #if _is_non_empty_deep(outv):
            #    continue
            # 先在客戶端過濾「已完成且新鮮」——改成檢查新鮮度，而不是僅檢查非空
            if not self._is_pending_by_outputs(src, output_cols_resolved):
                continue
    
            text = _extract_by_path(src, input_col)
            if isinstance(text, list): text = text[0] if text else None
            if text is None or str(text).strip() == "": 
                continue
    
            source_inputs = {c: _extract_by_path(src, c) for c in stage_input_cols}
            yield (str(pk_val), str(text), source_inputs)

    def _scan_dual_index_pending(self, src_index: str, tgt_index: str, pk: str, input_col: str, output_cols: Any, fetch_size: int, stage_input_cols: List[str] | None = None):
        """
        src 用 scan 串流所有有 input 的文件；每批用 mget/search 檢查 tgt 是否已有「非空」output。
        對齊 pk == "_id" 與 pk != "_id" 兩種情況。
        """
        assert self.es is not None
        output_cols_resolved = self._resolve_output_cols(output_cols=output_cols)
        filters = self._build_pending_filters()
        rt = int(self.cfg.get("es_request_timeout", 60))
        keepalive = self.cfg.get("es_scroll_keepalive", "2m")
        batch_limit = int(fetch_size or 500)
    
        stage_input_cols = [c for c in (stage_input_cols or []) if c and c != input_col]
        src_fields = [input_col] + stage_input_cols + ([pk] if pk != "_id" else [])
        src_fields = list(dict.fromkeys(src_fields))
        src_query = {
            "query": {"bool": {"must": [{"exists": {"field": input_col}}], "filter": filters}},
            "_source": src_fields,
            "track_total_hits": True
        }
    
        scan_iter = helpers.scan(
            client=self.es,
            index=src_index,
            query=src_query,
            size=int(fetch_size or 500),
            preserve_order=False,
            scroll=keepalive,
            request_timeout=rt,
            clear_scroll=True
        )
    
        batch_ids: List[str] = []
        batch_docs: Dict[str, Any] = {}

        for hit in scan_iter:
            src = hit.get("_source", {}) or {}
        
            key_val = hit.get("_id") if pk == "_id" else _extract_by_path(src, pk)
            key_val = _norm_scalar(key_val)         # ✅ 先標準化
            if key_val is None:
                continue
        
            text = _extract_by_path(src, input_col)
            if isinstance(text, list):              # ✅ text 若是 list 取第一個
                text = text[0] if text else None
            if text is None or str(text).strip() == "":
                continue
        
            batch_ids.append(key_val)               # ✅ 已是標準化後的字串
            batch_docs[key_val] = (str(text), {c: _extract_by_path(src, c) for c in stage_input_cols})
        
            if len(batch_ids) >= batch_limit:
                yield from self._yield_pending_from_batch(
                    tgt_index=tgt_index,
                    pk=pk,
                    batch_ids=batch_ids,
                    batch_docs=batch_docs,
                    output_cols=output_cols_resolved,
                    request_timeout=rt,
                )
                
        # 最後殘批也用同一個函式
        yield from self._yield_pending_from_batch(
            tgt_index=tgt_index,
            pk=pk,
            batch_ids=batch_ids,
            batch_docs=batch_docs,
            output_cols=output_cols_resolved,
            request_timeout=rt,
        )

    def _build_pending_filters(self) -> list:
        """
        從 cfg 組 pending 過濾條件：
        - cfg["pending_filters"] 可是 list（原生 ES 子句）或 dict（會轉成 term）
        - cfg["only_selected"] 為 True 時，自動加 {"term":{"selectedMessage": True}}
        """
        #print("****************self.cfg for es adapter",self.cfg)
        filters = []
        pf = self.cfg.get("pending_filters")
        if isinstance(pf, dict):
            for k, v in pf.items():
                filters.append({"term": {k: v}})
        elif isinstance(pf, (list, tuple)):
            filters.extend(pf)

        if self.cfg.get("only_selected", False):
            filters.append({"term": {"selectedMessage": True}})
        return filters

    # ✅ 新增：支援 with 语法
    #def __enter__(self):
    #    # 已 connect() 的情況直接回傳 self；若尚未 connect，也可在這裡防呆
    #    if self.es is None:
    #        self.connect()
    #    return self

    #def __exit__(self, exc_type, exc, tb):
    #    self.close()

# ----------------------------- 小工具 ---------------------------------------

def _get_non_empty(src: Dict[str, Any], field: str) -> Optional[Any]:
    """回傳欄位值（若存在且非空字串），否則回傳 None。支援 a 或 a.keyword 的容錯。"""
    if field in src:
        v = src.get(field)
        if v is not None and str(v).strip() != "":
            return v
    # 假如上游寫入時是以 keyword 欄位保存
    parts = field.split(".")
    if len(parts) == 1 and f"{field}.keyword" in src:
        v = src.get(f"{field}.keyword")
        if v is not None and str(v).strip() != "":
            return v
    return None


# ----------------------------- 使用示例 -------------------------------------
if __name__ == "__main__":
    cfg = {
        "hosts": ["http://localhost:9200"],
        "http_auth": None,
        "timeout": 60,
        # 單一 Index：將 src_index 與 tgt_index 設為相同
        "src_index": "my_source",
        "tgt_index": "my_source",
        "id_col": "_id",
        "input_col": "text_raw",
        "output_col": "llm_output",
    }

    adapter = ElasticsearchAdapter(cfg).connect()
    try:
        # 對齊既有 SQL 介面的呼叫方式
        for pk_val, text in adapter.select_pending_rows(
            src_table=cfg["src_index"],
            tgt_table=cfg["tgt_index"],
            pk=cfg["id_col"],
            input_col=cfg["input_col"],
            output_col=cfg["output_col"],
            record_update_time=False,
            fetch_size=500,
        ):
            print(pk_val, text[:60].replace("\n", " ") + ("..." if len(text) > 60 else ""))
    finally:
        adapter.close()
