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

    # --- 連線生命週期 ------------------------------------------------------
    def connect(self):
        if Elasticsearch is None:
            raise ImportError("elasticsearch 客戶端未安裝，請先 pip install 'elasticsearch<8'（對 ES 7.x）")
        self.es = Elasticsearch(
            hosts=self.cfg.get("hosts", ["http://localhost:9200"]),
            http_auth=self.cfg.get("http_auth"),
            timeout=self.cfg.get("timeout", 60),
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
        import os, json
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
        
    def ensure_columns_old(self, index: str, columns: List[Tuple[str, str]]):
        """
        將 SQL 的 columns（name, type）對應到 ES 的 mapping。
        這裡僅提供最小實作：若欄位未存在，新增為 keyword/text（依型別字串簡單判別）。
        若需要精確 mapping，建議在專案中集中管理 schema，由 ETL 建表時一次性建立。
        """
        assert self.es is not None
        if not columns:
            return
        # 讀現有 mapping
        index_map = self.es.indices.get_mapping(index=index)
        props = index_map.get(index, {}).get("mappings", {}).get("properties", {})

        to_add: Dict[str, Dict[str, Any]] = {}
        for name, ctype in columns:
            if name in props:
                continue
            ctype_lower = (ctype or "").lower()
            if any(t in ctype_lower for t in ["int", "bigint", "smallint", "tinyint"]):
                to_add[name] = {"type": "long"}
            elif any(t in ctype_lower for t in ["float", "double", "real", "decimal", "numeric"]):
                to_add[name] = {"type": "double"}
            elif any(t in ctype_lower for t in ["date", "time", "datetime", "timestamp"]):
                to_add[name] = {"type": "date"}
            else:
                # 文字欄位：預設 text + keyword 便於精確比對與聚合
                to_add[name] = {"type": "text", "fields": {"keyword": {"type": "keyword"}}}

        if to_add:
            self.es.indices.put_mapping(index=index, body={"properties": to_add})

    # --- ES 版本的 pending 擷取 --------------------------------------------
    def select_pending_rows(
        self,
        *,
        src_table: str,  # 對應 ES 的 index
        tgt_table: str,  # 對應 ES 的 index（可與 src_table 相同）
        pk: str,
        input_col: str,
        output_col: str,
        record_update_time: bool,  # 與 SQL 介面一致，此處不使用
        fetch_size: int = 500,
    ) -> Iterable[Tuple[Any, str]]:
        """
        產生 (pk_value, input_text)。
        - 單一 Index：src_table == tgt_table → 用 exists/must_not/term("") 篩選。
        - 雙 Index：先 scan 來源，再 mget 檢查結果 index 有無非空輸出。
        """
        assert self.es is not None
        #output_col = output_col[0]

        if src_table == tgt_table:
            # 單一 Index 模式
            for doc in self._scan_single_index_pending(src_table, pk, input_col, output_col, fetch_size):
                yield doc
        else:
            # 來源/結果分離
            for doc in self._scan_dual_index_pending(src_table, tgt_table, pk, input_col, output_col, fetch_size):
                yield doc

    # ------------------------ 內部：單一 Index ------------------------------
    
    def _scan_single_index_pending(self, index: str, pk: str, input_col: str, output_col: str, fetch_size: int):
        assert self.es is not None
        
        def _run_scan(query_body):
            return helpers.scan(self.es, index=index, query=query_body, size=fetch_size, preserve_order=False)
        
        # ✅ 只有兩個條件：
        # 1) 有輸入(input_col)
        # 2) 沒有輸出(output_col)
        body = {
            "query": {
                "bool": {
                    "must":     [{"exists": {"field": input_col}}],
                    "must_not": [{"exists": {"field": output_col}}],
                }
            },
            "_source": [input_col, pk] if pk != "_id" else [input_col],
        }
        print("DEBUG single-index pending query:", json.dumps(body, ensure_ascii=False))
        
        for hit in _run_scan(body):
            print("hit",hit)
            src = hit.get("_source", {}) or {}
            pk_val = hit.get("_id") if pk == "_id" else _dot_get(src, pk)
            if pk_val is None:
                continue
                
            # ✅ 二次確認：若文件此時已經有 output_col，就跳過（處理 NRT 或先前批次剛寫入的狀況）
            try:
                full = self.es.get(index=index, id=pk_val)
                if _dot_get(full.get("_source", {}) or {}, output_col) is not None:
                    # 可視需要加個 debug log
                    # print(f"[skip-NRT] {pk_val} 已具備 {output_col}，略過")
                    continue
            except Exception:
                pass                
                        
            text = _dot_get(src, input_col)
            if text is None or str(text).strip() == "":
                continue
            yield (pk_val, str(text))
    
    # ------------------------ 內部：雙 Index -------------------------------
    def _scan_dual_index_pending(self, src_index, tgt_index, pk, input_col, output_col, fetch_size):
        assert self.es is not None
        src_query = {"query": {"exists": {"field": input_col}}, "_source": [input_col]}
    
        batch_ids, batch_docs = [], {}
    
        def _is_non_empty(v) -> bool:
            if v is None: return False
            if isinstance(v, str): return v.strip() != ""
            if isinstance(v, (list, dict)): return len(v) > 0
            return True  # 其他型別一律當成有值
    
        def flush_batch():
            if not batch_ids:
                return []
            docs = self.es.mget(index=tgt_index, body={"ids": batch_ids})
            present = set()
            for d in docs.get("docs", []):
                if not d.get("found"): 
                    continue
                src = d.get("_source", {}) or {}
                val = _dot_get(src, output_col)         # ✅ 只看一個欄位
                if _is_non_empty(val):
                    present.add(d.get("_id"))
            for _id in batch_ids:
                if _id not in present:
                    yield (_id, batch_docs[_id])
    
        for hit in helpers.scan(self.es, index=src_index, query=src_query, size=fetch_size):
            src = hit.get("_source", {}) or {}
            _id = hit.get("_id") if pk == "_id" else _dot_get(src, pk)
            if _id is None: 
                continue
            text = _dot_get(src, input_col)
            if text is None or str(text).strip() == "":
                continue
            batch_ids.append(_id)
            batch_docs[_id] = str(text)
            if len(batch_ids) >= fetch_size:
                for item in flush_batch():
                    yield item
                batch_ids.clear(); batch_docs.clear()
    
        for item in flush_batch():
            yield item


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
