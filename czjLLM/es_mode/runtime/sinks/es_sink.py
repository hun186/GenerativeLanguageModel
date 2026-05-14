# czjLLM/es_mode/runtime/sinks/es_sink.py
from typing import Any, Optional, List, Dict
from elasticsearch import Elasticsearch, helpers
import datetime
from datetime import timezone
import re
import json
import atexit
import time
from czjLLM.utilities.json_text_utils import loads_json_flexible_deep

# 與其他 sink 保持一致的 logging helper（如果找不到模組會 fallback 到 print）
try:
    from ....job_manager.console_ui import tlog, tlog_warn
except Exception:
    def tlog(msg): print(msg)
    def tlog_warn(msg): print(msg)

def _now_iso_utc() -> str:
    # 例：'2025-10-22T13:37:43Z'（無微秒，最穩）
    return datetime.datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")       

def _meta_field_from_cfg(cfg: dict, output_col: str) -> str:
    rr = (cfg.get("rerun") or {})
    return rr.get("meta_field") or f"{output_col}_meta"
    
class ESSink:
    """
    Elasticsearch Sink —— 與 SqlSink/ExcelSink 介面相容
    主要特點：
      - 永遠只更新/新增 output_col (不覆蓋原文件)
      - 支援緩衝與 bulk 提交 (helpers.bulk)
      - 提供 fetch_input(pk) 來讀取既有文件某個 input_path（支援 dot.path）
      - write_flatten 將 json_array 寫回 output_col（作為陣列）
    """
    def __init__(self, ctx, es_client: Elasticsearch, index: str,
                 output_col: Optional[str] = None,
                 flush_every: Optional[int] = None,
                 flatten_json: bool = False,
                 *,
                 meta_field: Optional[str] = None,
                 meta_base: Optional[dict] = None):
        self.ctx = ctx
        self.es: Elasticsearch = es_client
        self.index = index
        # 若沒有顯式提供 output_col，從 ctx 取得；若還沒，預設 'LLM_result'
        self.output_col = output_col or getattr(ctx, "output_col", "LLM_result")
        # ✅ 建議：把預設筆數拉到 1000（你現在設 5 太頻繁）
        self.flush_every = int(flush_every or getattr(ctx, "es_flush_every", 1000))
        self.flatten_json = bool(flatten_json or getattr(ctx, "flatten_json", False))

        # ✅ 新增：容量 & 時間門檻（可被 ctx 覆寫）
        self.flush_bytes = int(getattr(ctx, "es_flush_bytes", 8_000_000))  # ≈ 8MB
        self.flush_secs  = float(getattr(ctx, "es_flush_secs",  2.0))      # 至多等 2 秒

        self._buffer: List[Dict[str, Any]] = []
        self._buffer_bytes = 0                    # ✅ 累積近似大小
        self._last_flush_ts = datetime.datetime.now().timestamp()
        self._debug = bool(getattr(self.ctx, "debug_es_sink", False))
        # ✅ 內部快取：實際生效的欄位（可能是 output_col 或 output_col+"_json"）
        #self._effective_output_col = None
        
        # ✅ meta_field 預設為 f"{output_col}_meta"
        self.meta_field: Optional[str] = meta_field or f"{self.output_col}_meta"
        self.meta_base: Dict[str, Any] = dict(meta_base or {})
        self.writeback_rules = self._load_writeback_rules()
        
        atexit.register(self.flush_all)  # 程式結束時保底 flush
        #print("ctx in ESSink",self.ctx)


    def _load_writeback_rules(self) -> Dict[str, Dict[str, Any]]:
        """從 ctx.es_writeback_rules/sql_writeback_rules 建立 output_col -> rule 查表。"""
        raw = getattr(self.ctx, "es_writeback_rules", None) or getattr(self.ctx, "sql_writeback_rules", None) or []
        out: Dict[str, Dict[str, Any]] = {}
        if isinstance(raw, list):
            for item in raw:
                if not isinstance(item, dict):
                    continue
                col = str(item.get("output_col", "")).strip()
                if col:
                    out[col] = dict(item)
        return out

    def _rule_for_output(self, output_col: str) -> Dict[str, Any]:
        return self.writeback_rules.get(str(output_col), {})

    def _index_for_output(self, output_col: str) -> str:
        rule = self._rule_for_output(output_col)
        return str(rule.get("index", rule.get("tgt_index", self.index)) or self.index)

    def _meta_field_for_output(self, output_col: str) -> Optional[str]:
        rule = self._rule_for_output(output_col)
        if rule.get("write_meta", True) is False:
            return None
        if "meta_field" in rule:
            mf = rule.get("meta_field")
            return str(mf).strip() if mf else None
        if output_col == self.output_col:
            return self.meta_field
        return f"{output_col}_meta"

    def _should_apply_payload_date_normalization_for(self, output_col: str) -> bool:
        """
        Optional legacy payload date normalization.

        This is off by default for arbitrary ES tasks. Enable it only for output
        fields that use the legacy multidimensional date schema via either:
        - rule.normalize_payload_dates: true
        - ctx.es_payload_date_normalize_fields: ["output_field"]

        """
        rule = self._rule_for_output(output_col)
        if "normalize_payload_dates" in rule:
            return bool(rule.get("normalize_payload_dates"))
        fields = getattr(self.ctx, "es_payload_date_normalize_fields", None)
        if fields is None:
            adapter = getattr(self.ctx, "_es_adapter", None)
            cfg = (getattr(adapter, "cfg", {}) or {}) if adapter else {}
            fields = cfg.get("es_payload_date_normalize_fields")

        if isinstance(fields, (list, tuple, set)):
            return output_col in {str(x) for x in fields}
        if isinstance(fields, str) and fields.strip():
            return output_col in {x.strip() for x in fields.split(",") if x.strip()}

        return False

    def _prepare_payload_for_output(self, output_col: str, result_text: Any):
        payload = self._maybe_parse_json(result_text)
        payload = self._unwrap_self_wrapped_output_for(output_col, payload)
        if self._should_apply_payload_date_normalization_for(output_col):
            payload = self._normalize_multidim_date_payload(payload)
        return self._normalize_payload_for_es(payload)

    def _unwrap_self_wrapped_output_for(self, output_col: str, payload):
        old = self.output_col
        try:
            self.output_col = output_col
            return self._unwrap_self_wrapped_output(payload)
        finally:
            self.output_col = old

    def _build_meta_for_output(self, output_col: str) -> Optional[dict]:
        old_output = self.output_col
        old_meta = self.meta_field
        try:
            self.output_col = output_col
            self.meta_field = self._meta_field_for_output(output_col)
            return self._build_meta()
        finally:
            self.output_col = old_output
            self.meta_field = old_meta

    def _prepare_update_doc_for_output(self, output_col: str, payload: Any):
        doc = {output_col: payload}
        if getattr(self.ctx, "record_update_time", False):
            ts = _now_iso_utc()
            doc["update_time_ai"] = ts
            if getattr(self.ctx, "update_time_inside_output", False):
                if isinstance(payload, dict):
                    payload.setdefault("update_time_ai", ts)
                elif isinstance(payload, list):
                    for it in payload:
                        if isinstance(it, dict):
                            it.setdefault("update_time_ai", ts)
        meta_field = self._meta_field_for_output(output_col)
        if meta_field:
            meta = self._build_meta_for_output(output_col)
            if meta:
                doc[meta_field] = meta
        return doc

    def _enqueue_update(self, pk, index: str, doc: Dict[str, Any]) -> None:
        item = {"_id": pk, "_index": index, "doc": doc}
        self._buffer.append(item)
        self._buffer_bytes += self._estimate_size(item)

    # -------- lifecycle --------
    def open(self):
        # 可在此檢查 index 是否存在（非必要，steps.ensure 已處理）
        try:
            exists = self.es.indices.exists(index=self.index)
            if not exists:
                tlog_warn(f"[ESSink] index '{self.index}' 不存在，後續 update 會做 upsert（視需求可先建立 index）。")
            tlog(f"[ESSink] open: index={self.index}, output_col={self.output_col}, flush_every={self.flush_every}")
        except Exception as ex:
            tlog_warn(f"[ESSink] open 時發生例外：{ex}")

    def close(self):
        self.flush_all()

    # -------- helpers --------
    def _extract_by_path(self, source: Dict[str, Any], path: Optional[str]):
        """從 dict 依 dot.path 取值；path None 或 '' 回傳整個 source"""
        if not path:
            return source
        keys = path.split(".")
        v = source
        try:
            for k in keys:
                if v is None:
                    return None
                v = v.get(k)
            return v
        except Exception:
            return None

    def _maybe_parse_json(self, payload):
        if isinstance(payload, str):
            try:
                return loads_json_flexible_deep(payload)
            except Exception:
                pass
        return payload
    

    def _normalize_payload_for_es(self, payload):
        # 空字串 → None；空陣列/空物件 → None（避免 exists 為真卻是「空結果」）
        if payload is None:
            return None
        if isinstance(payload, str):
            return payload if payload.strip() != "" else None
        if isinstance(payload, (list, dict)):
            return payload if len(payload) > 0 else None
        return payload

    def _unwrap_self_wrapped_output(self, payload):
        """
        修復模型偶發回傳的「自包裝」結構：
        - {"<output_col>": "<json_string>"}
        - {"<output_col>": [...]}
        - [ {"<output_col>": "..."} ] (單元素包裝)
        """
        out_key = str(self.output_col or "").strip()
        if not out_key:
            return payload

        cur = payload
        for _ in range(3):
            changed = False
            if isinstance(cur, dict) and out_key in cur:
                # 只在「單鍵」或明顯自包裝時解包，避免誤傷正常欄位
                if len(cur) == 1:
                    cur = self._maybe_parse_json(cur.get(out_key))
                    changed = True
            elif isinstance(cur, list) and len(cur) == 1 and isinstance(cur[0], dict):
                first = cur[0]
                if out_key in first and len(first) == 1:
                    cur = self._maybe_parse_json(first.get(out_key))
                    changed = True
            if not changed:
                break
        return cur
    
    
    # ---- 新增：解析日期字串，回傳 (iso_str, precision) ----
    def _normalize_date_value(self, s: str):
        """支援 YYYY-MM-DD / YYYY-MM / YYYY；其餘回傳 (None, None)。"""
        if not isinstance(s, str):
            return (None, None)
        t = s.strip()
        # YYYY-MM-DD
        if re.match(r"^\d{4}-\d{2}-\d{2}$", t):
            return (t, "day")
        # YYYY-MM -> YYYY-MM-01
        if re.match(r"^\d{4}-\d{2}$", t):
            return (t + "-01", "month")
        # YYYY -> YYYY-01-01
        if re.match(r"^\d{4}$", t):
            return (t + "-01-01", "year")
        return (None, None)
    
    # ---- 取值工具：支援 dict.get 深層賦值 ----
    def _getd(self, d, path, default=None):
        cur = d
        for k in path:
            if not isinstance(cur, dict) or k not in cur:
                return default
            cur = cur[k]
        return cur
    
    def _setd(self, d, path, value):
        cur = d
        for k in path[:-1]:
            if k not in cur or not isinstance(cur[k], dict):
                cur[k] = {}
            cur = cur[k]
        cur[path[-1]] = value
    
    def _build_meta(self) -> Optional[dict]:
        if not self.meta_field:
            return None
    
        rr = (getattr(self.ctx, "_es_adapter", None).cfg.get("rerun", {}) 
              if getattr(self.ctx, "_es_adapter", None) else {})
    
        meta = dict(self.meta_base or {})
        # 固定欄位
        meta["processed_at"]  = _now_iso_utc()
        meta["output_field"]  = self.output_col
    
        # 來自任務/環境
        if getattr(self.ctx, "task", None):
            meta.setdefault("task", self.ctx.task)
        #if getattr(self.ctx, "model_spec", None):
        #    meta.setdefault("model_spec", self.ctx.model_spec)
        if getattr(self.ctx, "channel", None):
            meta.setdefault("channel", self.ctx.channel)
        if getattr(self.ctx, "source", None):
            meta.setdefault("source", self.ctx.source)
    
        # 來自 rerun 設定
        if rr.get("model_tag"):
            meta.setdefault("model_tag", rr.get("model_tag"))
        if rr.get("pipeline_hash"):
            meta.setdefault("pipeline_hash", rr.get("pipeline_hash"))
    
        # 自動推導 force_reason（若有強制條件）
        if "force_reason" not in meta:
            reason = []
            if rr.get("force_since"):       reason.append("force_since")
            if rr.get("stale_after_days"):  reason.append("stale_after_days")
            if rr.get("force_if_missing_meta"): reason.append("missing_meta")
            if rr.get("model_tag"):         reason.append("model_tag_mismatch")
            if rr.get("pipeline_hash"):     reason.append("pipeline_hash_mismatch")
            if reason:
                meta["force_reason"] = ",".join(reason)
        return {k: v for k, v in meta.items() if v is not None}
        #return meta
        
    def _normalize_multidim_date_payload(self, payload: any):
        """
        處理舊版多維日期結構（list[dict]），不是通用 JSON transformer。
        僅在 normalize_payload_dates / es_payload_date_normalize_fields 明確啟用時執行：
        - payload["Event"].time 產出：time_raw / time_iso / time_precision
        - payload["Event_Timeline"][].date 產出：date_raw / date_iso / date_precision
        - date_range.start/end 產出 *_raw / *_precision，並把可解析值轉成 ISO 日期
        目前僅解析 YYYY-MM-DD / YYYY-MM / YYYY。
        """
        try:
            if not isinstance(payload, list):
                return payload
    
            out = []
            for item in payload:
                if not isinstance(item, dict):
                    out.append(item); continue
                obj = dict(item)  # 淺拷貝
    
                # --- legacy payload["Event"].time -> 新三欄 ---
                ev = obj.get("Event")
                if isinstance(ev, dict):
                    t = ev.get("time")
                    if isinstance(t, str):
                        # 保留原字面
                        ev.setdefault("time_raw", t)
                        iso, prec = self._normalize_date_value(t)
                        if iso:
                            ev["time_iso"] = iso
                            ev["time_precision"] = prec
                        # 不覆蓋原本的 ev["time"]，你也可以選擇刪掉 ev["time"]：
                        # ev.pop("time", None)
    
                # --- date_range.start / end -> 可加 raw/precision（可選）---
                dr = obj.get("date_range")
                if isinstance(dr, dict):
                    for k in ("start", "end"):
                        v = dr.get(k)
                        if isinstance(v, str):
                            dr.setdefault(f"{k}_raw", v)
                            iso, prec = self._normalize_date_value(v)
                            if iso:
                                # 如果你想保留 start/end 是 date 類型，直接覆蓋為 iso
                                dr[k] = iso
                                dr[f"{k}_precision"] = prec
                            # 若不想覆蓋，也可以另外寫入 k+"_iso"：
                            # self._setd(dr, [f"{k}_iso"], iso)
    
                # --- legacy payload["Event_Timeline"][].date -> 新三欄 ---
                tl = obj.get("Event_Timeline")
                if isinstance(tl, list):
                    new_tl = []
                    for step in tl:
                        if isinstance(step, dict):
                            step = dict(step)
                            dv = step.get("date")
                            if isinstance(dv, str):
                                step.setdefault("date_raw", dv)
                                iso, prec = self._normalize_date_value(dv)
                                if iso:
                                    step["date_iso"] = iso
                                    step["date_precision"] = prec
                                # 同理你也可以刪掉原本的 step["date"]
                                # step.pop("date", None)
                        new_tl.append(step)
                    obj["Event_Timeline"] = new_tl
    
                out.append(obj)
            return out
        except Exception:
            # 出錯就原樣返回，避免中斷
            return payload
        
 
    def _prepare_update_doc(self, payload: Any, save_raw_input: bool = False,
                            input_col: Optional[str] = None, input_value: Any = None):
        doc = {self.output_col: payload}
    
        if getattr(self.ctx, "record_update_time", False):
            ts = _now_iso_utc()
            doc["update_time_ai"] = ts  # 根層
    
            # ✅（可選）也寫到 output_col 內層
            # 若要查 nested 內的時間，需在對應 output 欄位的 properties.update_time_ai 定義成 date。
            if getattr(self.ctx, "update_time_inside_output", False):
                if isinstance(payload, dict):
                    payload.setdefault("update_time_ai", ts)
                elif isinstance(payload, list):
                    for it in payload:
                        if isinstance(it, dict):
                            it.setdefault("update_time_ai", ts)
        # ⬇️ 新增：同步寫入 meta
        if self.meta_field:
            meta = self._build_meta()
            if meta:
                doc[self.meta_field] = meta

        if save_raw_input and input_col:
            doc[input_col] = input_value
        return doc



    # -------- 主介面（與 SqlSink/ExcelSink 相同的方法） --------
    def fetch_input(self, pk):
        """依 pk (ES _id) 回傳 ctx.input_col 指定的輸入內容（支援 dot.path）"""
        if pk is None:
            return None
        try:
            r = self.es.get(index=self.index, id=pk)
            src = r.get("_source", {}) or {}
            return self._extract_by_path(src, getattr(self.ctx, "input_col", None))
        except Exception:
            return None

    '''
    def _prepare_update_doc(self, payload: Any, save_raw_input: bool = False,
                            input_col: Optional[str] = None, input_value: Any = None):
        # ✅ 在這裡（或 write_main）統一先嘗試轉成 JSON 物件
        payload = self._maybe_parse_json(payload)
        doc = {self.output_col: payload}
        if getattr(self.ctx, "record_update_time", False):
            now = datetime.datetime.utcnow().isoformat()
            doc.setdefault("update_time", now)
        if save_raw_input and input_col:
            doc[input_col] = input_value
        return doc
    '''
    
    
    def _estimate_size(self, item: Dict[str, Any]) -> int:
        """粗估單筆 action 的 JSON 大小（bytes）。"""
        try:
            return len(json.dumps(item, ensure_ascii=False))
        except Exception:
            return 0
    
    def _maybe_flush(self):
        now = time.time()
        if (len(self._buffer) >= self.flush_every or
            self._buffer_bytes >= self.flush_bytes or
            (now - self._last_flush_ts) >= self.flush_secs):
            self._flush()
            self._last_flush_ts = now
            self._buffer_bytes = 0
            
    def write_main(self, pk, result_text: Any, update_time: Optional[str] = None):
        if pk is None:
            tlog_warn("⚠️ ESSink.write_main: pk 為 None，略過寫入。")
            return

        # 多階段 row_merger 會傳入 {output_col: payload_text, ...}；
        # ES 在這裡把每個 output_col 依規則寫到同一或不同 index。
        if isinstance(result_text, dict):
            docs_by_index: Dict[str, Dict[str, Any]] = {}
            for output_col, raw_payload in result_text.items():
                output_col = str(output_col).strip()
                if not output_col:
                    continue
                payload = self._prepare_payload_for_output(output_col, raw_payload)
                if payload is None:
                    if self._debug:
                        tlog(f"ℹ️ ESSink.write_main: output_col={output_col} 規範化後為空，略過。")
                    continue
                idx = self._index_for_output(output_col)
                docs_by_index.setdefault(idx, {}).update(self._prepare_update_doc_for_output(output_col, payload))

            for idx, doc in docs_by_index.items():
                self._enqueue_update(pk, idx, doc)
            if docs_by_index:
                self._maybe_flush()
            return

        payload = self._prepare_payload_for_output(self.output_col, result_text)

        # 🚫 規範化後為 None → 直接略過（避免 exists 誤判）
        if payload is None:
            if self._debug:
                tlog("ℹ️ ESSink.write_main: 規範化後為空，略過寫入。")
            return

        doc = self._prepare_update_doc_for_output(self.output_col, payload)
        self._enqueue_update(pk, self._index_for_output(self.output_col), doc)

        if self._debug:
            tlog(f"[ESSink] buffer size={len(self._buffer)}, bytes~={self._buffer_bytes} (limits: {self.flush_every} / {self.flush_bytes}B)")
        self._maybe_flush()

    def write_flatten(self, pk, json_array: List[Dict], save_raw_input: bool, input_col: Optional[str], input_value):
        """
        將 flatten（或子表）結果寫回 output_col（作為陣列）。
        - save_raw_input: 若 True，會把 input_col/input_value 一起放入該 doc
        """
        if pk is None:
            tlog_warn("⚠️ ESSink.write_flatten: pk 為 None，略過寫入。")
            return
        payload = json_array or []
        doc = self._prepare_update_doc(payload, save_raw_input=save_raw_input, input_col=input_col, input_value=input_value)
        item = {"_id": pk, "doc": doc}
        self._buffer.append(item)
        self._buffer_bytes += self._estimate_size(item)
        self._maybe_flush()

    def ensure_flatten_schema(self, allowed_fields=None):
        # ES 不需為 nested JSON 做額外 schema 建立；保持與 SqlSink API 相容
        return

    # -------- flush / bulk --------
    def _flush(self):
        if not self._buffer:
            return
    
        actions_gen = (
            {
                "_op_type": "update",
                "_index": item.get("_index", self.index),
                "_id": item["_id"],
                "doc": item["doc"],
                "doc_as_upsert": True,
            }
            for item in self._buffer
        )
    
        try:
            # ✅ 只有在 debug 下才轉 list（避免平時多一份記憶體拷貝）
            actions = list(actions_gen) if self._debug else actions_gen
            if self._debug:
                tlog(f"[ESSink] flushing {len(actions)} actions to index {self.index}")
    
            success, errors = helpers.bulk(self.es, actions, raise_on_error=False, request_timeout=120)
    
            # ✅ 建議：正式環境關閉這個 refresh（把 ctx.es_refresh_after_flush 設 False）
            if getattr(self.ctx, "es_refresh_after_flush", False):
                self.es.indices.refresh(index=self.index)
    
            if errors:
                print(f"❌ bulk 有錯（僅示範前 3 筆）：{errors[:3]}")
            else:
                print(f"💾 bulk 成功筆數：{success}")
    
            # 二擇一即可，不必再呼叫一次 refresh
            # try: self.es.indices.refresh(index=self.index)
            # except Exception: pass
    
        except Exception as ex:
            print(f"⚠️ ESSink._flush 例外：{ex}")
        finally:
            self._buffer.clear()

    def flush_all(self):
        self._flush()
