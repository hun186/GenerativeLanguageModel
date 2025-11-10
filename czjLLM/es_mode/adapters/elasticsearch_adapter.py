#es_mode/adapters/es_adapter.py

from typing import Any, Dict, Iterable, List, Tuple, Optional
import json

try:
    # 官方 7.x 客戶端
    from elasticsearch import Elasticsearch, helpers  # type: ignore
except Exception as e:  # pragma: no cover
    Elasticsearch = None  # type: ignore
    helpers = None  # type: ignore

def _dot_get(d, path):
    cur = d
    for p in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(p)
        if cur is None:
            return None
    return cur

def _extract_by_path(src: dict, path: str):
    """a.b.c 取值，缺任一層回 None。"""
    try:
        cur = src
        for k in path.split("."):
            if cur is None:
                return None
            cur = cur.get(k)
        return cur
    except Exception:
        return None
    
def _is_non_empty_deep(v) -> bool:
    if v is None: return False
    if isinstance(v, str): return v.strip() != ""
    if isinstance(v, (list, tuple)): 
        return any(_is_non_empty_deep(x) for x in v)
    if isinstance(v, dict):
        return any(_is_non_empty_deep(x) for x in v.values())
    return True  # 其他型別視為有值

def _norm_scalar(v):
    """將 list/tuple 取第一個，再轉成字串；None 維持 None。"""
    if isinstance(v, (list, tuple)):
        v = v[0] if v else None
    return None if v is None else str(v)


class ElasticsearchAdapter:
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
    def _bulk_check_present_nonempty(
        self, *, tgt_index: str, pk: str, ids: List[str],
        output_col: str, request_timeout: int,
    ) -> set:
        assert self.es is not None
        present = set()
        if not ids:
            return present
        
        # ✅ 先把查詢用的 ids 統一標準化，過濾掉 None
        ids_norm = []
        for v in ids:
            nv = _norm_scalar(v)
            if nv is not None:
                ids_norm.append(nv)
        if not ids_norm:
            return present
    
        if pk == "_id":
            # 直接用 mget
            docs = self.es.mget(index=tgt_index, body={"ids": ids_norm},
                                request_timeout=request_timeout)
            for d in docs.get("docs", []):
                if not d.get("found"):
                    continue
                src = d.get("_source", {}) or {}
                val = _extract_by_path(src, output_col)
                #if _is_non_empty_deep(val):
                if self._is_fresh_output(src, output_col):
                    # ✅ 放入 present 前也標準化，避免 _id 型態不一
                    present.add(_norm_scalar(d.get("_id")))
            return present
    
        # pk 不是 _id：用 search terms 查詢
        pk_keyword = pk + self.cfg.get("pk_keyword_suffix", ".keyword")
        try:
            m = self.get_field_mapping(tgt_index, pk)
            has_keyword = isinstance(m, dict) and "fields" in m and "keyword" in m["fields"]
        except Exception:
            has_keyword = False
    
        term_field = pk_keyword if has_keyword else pk
    
        batch = 1000
        for i in range(0, len(ids_norm), batch):
            chunk = ids_norm[i:i+batch]          # ✅ 已是標準化後的字串
            q = {
                "query": {"terms": {term_field: chunk}},
                "_source": [pk, output_col],
                "size": len(chunk)
            }
            res = self.es.search(index=tgt_index, body=q, request_timeout=request_timeout)
            for hit in res.get("hits", {}).get("hits", []):
                src = hit.get("_source", {}) or {}
                val = _extract_by_path(src, output_col)
                if _is_non_empty_deep(val):
                    key_val = _extract_by_path(src, pk)
                    key_val = _norm_scalar(key_val)     # ✅ 放入前標準化
                    if key_val is not None:
                        present.add(key_val)
        return present
    def _bulk_check_present_nonempty_old(
        self,
        *,
        tgt_index: str,
        pk: str,
        ids: List[str],
        output_col: str,
        request_timeout: int,
    ) -> set:
        """
        回傳：在 tgt_index 中，主鍵 pk 落在 ids 範圍，且 output_col『為非空』的那批 pk 值集合。
        """
        assert self.es is not None
        present = set()
        if not ids:
            return present
    
        def _is_non_empty(v) -> bool:
            if v is None: return False
            if isinstance(v, str): return v.strip() != ""
            if isinstance(v, (list, dict)): return len(v) > 0
            return True
    
        if pk == "_id":
            # 直接用 mget
            docs = self.es.mget(index=tgt_index, body={"ids": ids}, request_timeout=request_timeout)
            for d in docs.get("docs", []):
                if not d.get("found"):
                    continue
                src = d.get("_source", {}) or {}
                val = _extract_by_path(src, output_col)
                if _is_non_empty(val):
                    present.add(d.get("_id"))
            return present
    
        # pk 不是 _id：用 search terms 查詢
        # 優先用 pk.keyword；若沒有，就用 pk 本身
        pk_keyword = pk + self.cfg.get("pk_keyword_suffix", ".keyword")
        # 試一次 mapping 決定用哪個欄位
        try:
            m = self.get_field_mapping(tgt_index, pk)
            has_keyword = isinstance(m, dict) and "fields" in m and "keyword" in m["fields"]
        except Exception:
            has_keyword = False
    
        term_field = pk_keyword if has_keyword else pk
    
        # 大批 terms 可能過長，做分批
        batch = 1000
        for i in range(0, len(ids), batch):
            chunk = ids[i:i+batch]
            q = {
                "query": {"terms": {term_field: chunk}},
                "_source": [pk, output_col],
                "size": len(chunk)
            }
            res = self.es.search(index=tgt_index, body=q, request_timeout=request_timeout)
            for hit in res.get("hits", {}).get("hits", []):
                src = hit.get("_source", {}) or {}
                val = _extract_by_path(src, output_col)
                if _is_non_empty(val):
                    # 取出 pk 值（注意是 pk 欄位，不是 _id）
                    key_val = _extract_by_path(src, pk)
                    if key_val is not None:
                        present.add(str(key_val))
        return present

    
    def _needs_rerun_clause(self, index: str, output_col: str) -> Optional[dict]:
        rr = (self.cfg or {}).get("rerun") or {}
        if not rr.get("enable"):
            return None
        #print("rr in _needs_rerun_clause",rr)
        #print("-"*50)
        meta      = rr.get("meta_field") or f"{output_col}_meta"  # e.g. "multidim_event_json_meta"
        #print("meta",meta)
        tag       = rr.get("model_tag")
        pipe      = rr.get("pipeline_hash")
        since     = rr.get("force_since")
        stale_days= rr.get("stale_after_days")
        force_if_missing_meta = rr.get("force_if_missing_meta", False)
    
        # 這行改成同時支援 rerun 與全域（你檔案就是放全域）
        #print("self.cfg in needs_rerun",self.cfg)
        fallback_date = (
            rr.get("fallback_date_field")
            or self.cfg.get("fallback_date_field")
            or "update_time_ai"
        )

    
        should = []
    
        # A) 版本/管線比對（有 meta 才比）
        if tag and meta:
            should.append({"bool":{"must":[{"exists":{"field":output_col}}],
                                   "must_not":[{"term":{f"{meta}.model_tag.keyword":tag}}]}})
        if pipe and meta:
            should.append({"bool":{"must":[{"exists":{"field":output_col}}],
                                   "must_not":[{"term":{f"{meta}.pipeline_hash.keyword":pipe}}]}})
    
        # B) 逾期（stale_days）
        if stale_days:
            if meta:
                should.append({"range": {f"{meta}.processed_at": {"lt": f"now-{int(stale_days)}d"}}})
            if fallback_date:
                # 若 fallback_date 是 date mapping，這條會生效
                should.append({"range": {fallback_date: {"lt": f"now-{int(stale_days)}d"}}})
    
        # C) 強制時間窗（since）
        if since:
            if meta:
                should.append({"range": {f"{meta}.processed_at": {"lt": since}}})
            if fallback_date:
                # 1) date-mapped 的正常 range
                should.append({"range": {fallback_date: {"lt": since}}})
                # 2) 非 date-mapped 的字串比較備援（有 output 才需要重跑）
                should.append({
                    "bool": {
                        "must": [
                            {"exists": {"field": output_col}},
                            {"script": {
                                "script": {
                                    "lang": "painless",
                                    "source": """
                                        def v = params._source.get(params.fd);
                                        if (v == null) return false;
                                        def s = v instanceof List ? (v.size() > 0 ? v.get(0) : null) : v;
                                        if (s == null) return false;
                                        return s.compareTo(params.since) < 0;
                                    """,
                                    "params": {"fd": fallback_date, "since": since}
                                }
                            }}
                        ]
                    }
                })
    
        # D) 有 output 但缺 meta → 也當需重跑
        #print("force_if_missing_meta",force_if_missing_meta)
        #print("meta",meta)
        if force_if_missing_meta and meta:
            #print("GOGOGO")
            should.append({
                "bool": {
                    "must":     [{"exists": {"field": output_col}}],
                    "must_not": [{"exists": {"field": meta}}]
                }
            })
    
        if not should:
            return None
        return {"bool": {"should": should, "minimum_should_match": 1}}
    
    def _is_fresh_output(self, src: dict, output_col: str) -> bool:
        """單一處定義：輸出存在且“新鮮”。"""
        val = _extract_by_path(src, output_col)
        if not _is_non_empty_deep(val):
            return False
    
        rr = (self.cfg or {}).get("rerun") or {}
        if not rr.get("enable"):
            return True  # 只要有值就當新鮮
    
        meta_field = rr.get("meta_field")           # e.g., "multidim_event_json_meta"
        tag        = rr.get("model_tag")
        pipe       = rr.get("pipeline_hash")
        since      = rr.get("force_since")
        stale_days = rr.get("stale_after_days")
        force_if_missing_meta = rr.get("force_if_missing_meta", False)
    
        meta = _extract_by_path(src, meta_field) if meta_field else None
    
        if force_if_missing_meta and meta_field and meta is None:
            return False
    
        # model_tag / pipeline_hash 比對
        if tag and meta and _extract_by_path(meta, "model_tag") != tag:
            return False
        if pipe and meta and _extract_by_path(meta, "pipeline_hash") != pipe:
            return False
    
        # 日期新鮮度（若有）
        def _older_than(cfg_days) -> bool:
            # 以 processed_at 優先，再退回 update_time_ai
            from datetime import datetime, timezone, timedelta
            dt = _extract_by_path(meta, "processed_at") if meta else None
            if dt is None:
                dt = _extract_by_path(src, "update_time_ai")
            try:
                # 允許 ISO 8601；你的資料若是 epoch_ms，這裡可再加分支
                dt = datetime.fromisoformat(str(dt).replace("Z","+00:00"))
            except Exception:
                return False
            return dt < (datetime.now(timezone.utc) - timedelta(days=int(cfg_days)))
    
        if stale_days and _older_than(stale_days):
            return False
    
        # force_since：結果若早於此時間 → 視為不新鮮（需重跑）
        if since:
            try:
                from datetime import datetime
                since_dt = datetime.fromisoformat(since.replace("Z","+00:00"))
                dt = _extract_by_path(meta, "processed_at") if meta else _extract_by_path(src, "update_time_ai")
                dt = datetime.fromisoformat(str(dt).replace("Z","+00:00"))
                if dt < since_dt:
                    return False
            except Exception:
                pass
    
        return True

    # --- ES 版本的 pending 擷取 --------------------------------------------

    def select_pending_rows(
        self,
        *,
        src_table: str,
        tgt_table: str,
        pk: str,
        input_col: str,
        output_col: str,
        record_update_time: bool,
        fetch_size: int = 500,
    ):
        """以 helpers.scan 串流完整待處理集合（有 input、無有效 output）。"""
        assert self.es is not None
    
        if src_table == tgt_table:
            # 單一 index：同文件包含 input/output
            for item in self._scan_single_index_pending(src_table, pk, input_col, output_col, fetch_size):
                yield item
        else:
            # 來源/結果分離：src 提 id + input，tgt 用 mget 檢是否已有 output
            for item in self._scan_dual_index_pending(src_table, tgt_table, pk, input_col, output_col, fetch_size):
                yield item

    def _scan_single_index_pending(self, index, pk, input_col, output_col, fetch_size):
        assert self.es is not None
        filters = self._build_pending_filters()
        rt = int(self.cfg.get("es_request_timeout", 60))
        keepalive = self.cfg.get("es_scroll_keepalive", "2m")
        
        needs_rerun = self._needs_rerun_clause(index, output_col)
        '''
        body = {
            "query": {"bool": {
                "must":   [{"exists": {"field": input_col}}],
                "filter": filters
            }},
            "_source": [input_col, output_col] + ([pk] if pk != "_id" else []),
            "track_total_hits": True
        }
        '''
        '''
        body = {
            "query": {"bool": {
                "must":   [{"exists": {"field": input_col}}],
                "filter": filters,
                "should": [
                    {"bool": {"must_not": [{"exists": {"field": output_col}}]}},  # 沒輸出
                    *([needs_rerun] if needs_rerun else [])
                ],
                "minimum_should_match": 1
            }},
            "_source": [input_col, output_col, self.cfg.get("rerun", {}).get("meta_field", "")] 
                       + ([pk] if pk != "_id" else []),
            "track_total_hits": True
        }
        '''
        
        # ★ 取得備援日期欄位（你在 cfg 或 rerun 內放的）
        rr = (self.cfg or {}).get("rerun") or {}
        fallback_date = rr.get("fallback_date_field") \
                         or self.cfg.get("fallback_date_field") \
                         or "update_time_ai"
        # 先安全取得 meta_field（可能為 None）
        mf = (self.cfg.get("rerun") or {}).get("meta_field")
        
        # 組 _source 欄位清單：必帶 input/output；有 mf 再加；pk 不是 _id 也要加
        src_fields = [input_col, output_col]
        if mf:
            src_fields.append(mf)
        if pk != "_id":
            src_fields.append(pk)
        # 可選：也讓 _source 直接帶上日期欄位（保險起見）
        if fallback_date and fallback_date not in src_fields:
            src_fields.append(fallback_date)
        body = {
            "query": {
                "bool": {
                    "must":   [{"exists": {"field": input_col}}],
                    "filter": filters,
                    "should": [
                        {"bool": {"must_not": [{"exists": {"field": output_col}}]}},  # 沒輸出
                        *([needs_rerun] if needs_rerun else [])
                    ],
                    "minimum_should_match": 1
                }
            },
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
                print("[DEBUG] has output?", output_col.split(".")[0] in (src or {}))
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
            if self._is_fresh_output(src, output_col):
                continue
    
            text = _extract_by_path(src, input_col)
            if isinstance(text, list): text = text[0] if text else None
            if text is None or str(text).strip() == "": 
                continue
    
            yield (str(pk_val), str(text))
    '''
    def _scan_single_index_pending_1110_2(self, index: str, pk: str, input_col: str, output_col: str, fetch_size: int):
        assert self.es is not None
        filters = self._build_pending_filters()
    
        rt = int(self.cfg.get("es_request_timeout", 60))
        keepalive = self.cfg.get("es_scroll_keepalive", "2m")

        body = {
            "query": {
                "bool": {
                    "must": [
                        {"exists": {"field": input_col}}
                    ],
                    "must_not": [
                        {
                            "nested": {
                                "path": output_col,          # "multidim_event_json"
                                "query": {"match_all": {}}
                            }
                        }
                    ],
                    "filter": filters
                }
            },
            "_source": [input_col, pk] if pk != "_id" else [input_col],
            "track_total_hits": True
        }
        print("DEBUG single-index pending query:", json.dumps(body, ensure_ascii=False))
    
        scan_iter = helpers.scan(
            client=self.es,
            index=index,
            query=body,
            size=int(fetch_size or 500),
            preserve_order=False,
            scroll=keepalive,
            request_timeout=rt,
            clear_scroll=True
        )
    
        for hit in scan_iter:
            src = hit.get("_source", {}) or {}
            pk_val = hit.get("_id") if pk == "_id" else _extract_by_path(src, pk)
            # ✅ 若欄位是 list，取第一個
            if isinstance(pk_val, list):
                pk_val = pk_val[0] if pk_val else None
            if pk_val is None:
                continue
    
            text = _extract_by_path(src, input_col)
            if isinstance(text, list):
                text = text[0] if text else None
            if text is None or str(text).strip() == "":
                continue
    
            yield (str(pk_val), str(text))
    '''
    def _scan_dual_index_pending(self, src_index: str, tgt_index: str, pk: str, input_col: str, output_col: str, fetch_size: int):
        """
        src 用 scan 串流所有有 input 的文件；每批用 mget/search 檢查 tgt 是否已有「非空」output。
        對齊 pk == "_id" 與 pk != "_id" 兩種情況。
        """
        assert self.es is not None
        filters = self._build_pending_filters()
        rt = int(self.cfg.get("es_request_timeout", 60))
        keepalive = self.cfg.get("es_scroll_keepalive", "2m")
    
        src_query = {
            "query": {"bool": {"must": [{"exists": {"field": input_col}}], "filter": filters}},
            "_source": [input_col, pk] if pk != "_id" else [input_col],
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
        batch_docs: Dict[str, str] = {}
        '''
        for hit in scan_iter:
            src = hit.get("_source", {}) or {}
            key_val = hit.get("_id") if pk == "_id" else _extract_by_path(src, pk)
            if key_val is None:
                continue
            text = _extract_by_path(src, input_col)
            if text is None or str(text).strip() == "":
                continue
    
            key_val = str(key_val)
            batch_ids.append(key_val)
            batch_docs[key_val] = str(text)
    
            if len(batch_ids) >= int(fetch_size or 500):
                present = self._bulk_check_present_nonempty(
                    tgt_index=tgt_index,
                    pk=pk,
                    ids=batch_ids,
                    output_col=output_col,
                    request_timeout=rt,
                )
                for _id in batch_ids:
                    if _id not in present:
                        yield (_id, batch_docs[_id])
                batch_ids.clear()
                batch_docs.clear()
    
        if batch_ids:
            present = self._bulk_check_present_nonempty(
                tgt_index=tgt_index,
                pk=pk,
                ids=batch_ids,
                output_col=output_col,
                request_timeout=rt,
            )
            for _id in batch_ids:
                if _id not in present:
                    yield (_id, batch_docs[_id])
        '''
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
            batch_docs[key_val] = str(text)
        
            if len(batch_ids) >= int(fetch_size or 500):
                present = self._bulk_check_present_nonempty(
                    tgt_index=tgt_index, pk=pk, ids=batch_ids,
                    output_col=output_col, request_timeout=rt,
                )
                for _id in batch_ids:
                    if _id not in present:
                        yield (_id, batch_docs[_id])
                batch_ids.clear()
                batch_docs.clear()
    '''
    def _scan_dual_index_pending_1110(self, src_index: str, tgt_index: str, pk: str, input_col: str, output_col: str, fetch_size: int):
        """
        src 用 scan 串流所有有 input 的文件；每批用 mget 檢查 tgt 是否已有「非空」output。
        """
        assert self.es is not None
        filters = self._build_pending_filters()
        rt = int(self.cfg.get("es_request_timeout", 60))
        keepalive = self.cfg.get("es_scroll_keepalive", "2m")
    
        def _is_non_empty(v) -> bool:
            if v is None: return False
            if isinstance(v, str): return v.strip() != ""
            if isinstance(v, (list, dict)): return len(v) > 0
            return True
    
        src_query = {
            "query": {"bool": {"must": [{"exists": {"field": input_col}}], "filter": filters}},
            "_source": [input_col, pk] if pk != "_id" else [input_col],
            "track_total_hits": True
        }
    
        batch_ids, batch_docs = [], {}
    
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
    
        for hit in scan_iter:
            src = hit.get("_source", {}) or {}
            _id = hit.get("_id") if pk == "_id" else _extract_by_path(src, pk)
            if _id is None:
                continue
            text = _extract_by_path(src, input_col)
            if text is None or str(text).strip() == "":
                continue
            batch_ids.append(_id)
            batch_docs[_id] = str(text)
            if len(batch_ids) >= int(fetch_size or 500):
                # 批次檢查 tgt 是否已有非空 output
                docs = self.es.mget(index=tgt_index, body={"ids": batch_ids}, request_timeout=rt)
                present = set()
                for d in docs.get("docs", []):
                    if not d.get("found"): 
                        continue
                    val = _extract_by_path(d.get("_source", {}) or {}, output_col)
                    if _is_non_empty(val):
                        present.add(d.get("_id"))
                for _id in batch_ids:
                    if _id not in present:
                        yield (_id, batch_docs[_id])
                batch_ids.clear(); batch_docs.clear()
    
        if batch_ids:
            docs = self.es.mget(index=tgt_index, body={"ids": batch_ids}, request_timeout=rt)
            present = set()
            for d in docs.get("docs", []):
                if not d.get("found"):
                    continue
                val = _extract_by_path(d.get("_source", {}) or {}, output_col)
                if _is_non_empty(val):
                    present.add(d.get("_id"))
            for _id in batch_ids:
                if _id not in present:
                    yield (_id, batch_docs[_id])
    '''
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
    def __enter__(self):
        # 已 connect() 的情況直接回傳 self；若尚未 connect，也可在這裡防呆
        if self.es is None:
            self.connect()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()

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
