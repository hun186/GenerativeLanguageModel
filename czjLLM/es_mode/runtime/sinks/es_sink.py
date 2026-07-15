# czjLLM/es_mode/runtime/sinks/es_sink.py
from typing import Any, Optional, List, Dict
from elasticsearch import Elasticsearch, helpers
import datetime
from datetime import timezone
import json
import atexit
import time

# 與其他 sink 保持一致的 logging helper（如果找不到模組會 fallback 到 print）
try:
    from ....job_manager.console_ui import tlog, tlog_warn
except Exception:
    def tlog(msg): print(msg)
    def tlog_warn(msg): print(msg)

from ...output_profiles import get_default_registry, load_output_profile_plugins
from ...output_profiles.multidim_event import normalize_multidim_event_payload
from ...output_profiles.multidim_event import normalize_date_value

def _now_iso_utc() -> str:
    # 例：'2025-10-22T13:37:43Z'（無微秒，最穩）
    return datetime.datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")       

def _meta_field_from_cfg(cfg: dict, output_col: str) -> str:
    rr = (cfg.get("rerun") or {})
    return rr.get("meta_field") or f"{output_col}_meta"


def _normalize_output_profile(value: Any) -> str:
    """Normalize YAML/ctx output profile names via the profile registry."""
    return get_default_registry().normalize_name(value)


def _infer_output_profile(output_col: Optional[str], legacy_event_cols: Optional[List[str]] = None) -> str:
    """Backward-compatible inference for legacy ES event configs.

    Only the clearly event-specific multidim_event_json is inferred by default.
    Generic names such as llm_result_json should set output_profile explicitly
    when they need multidim_event normalization.
    """
    event_cols = set(legacy_event_cols or ["multidim_event_json"])
    return "multidim_event" if str(output_col) in event_cols else "none"
    
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
        self._resolved_doc_id_cache: Dict[str, Optional[str]] = {}
        self._debug = bool(getattr(self.ctx, "debug_es_sink", False))
        self.write_output = bool(getattr(ctx, "write_output", getattr(ctx, "es_write_output", True)))
        load_output_profile_plugins(getattr(self.ctx, "output_profile_plugins", None))
        load_output_profile_plugins(getattr(self.ctx, "output_profiles", None))
        profile_from_ctx = getattr(self.ctx, "output_profile", None)
        self.output_profile = self._resolve_output_profile(profile_from_ctx, self.output_col)
        # ✅ 內部快取：實際生效的欄位（可能是 output_col 或 output_col+"_json"）
        #self._effective_output_col = None
        
        # ✅ meta_field 預設為 f"{output_col}_meta"
        self.meta_field: Optional[str] = meta_field or f"{self.output_col}_meta"
        self.meta_base: Dict[str, Any] = dict(meta_base or {})
        
        atexit.register(self.flush_all)  # 程式結束時保底 flush
        #print("ctx in ESSink",self.ctx)

    # -------- lifecycle --------
    def open(self):
        # 可在此檢查 index 是否存在（非必要，steps.ensure 已處理）
        try:
            exists = self.es.indices.exists(index=self.index)
            if not exists:
                tlog_warn(f"[ESSink] index '{self.index}' 不存在，後續 update 會做 upsert（視需求可先建立 index）。")
            tlog(f"[ESSink] open: index={self.index}, output_col={self.output_col}, output_profile={self.output_profile}, write_output={self.write_output}, flush_every={self.flush_every}")
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

    def _es_id_col(self) -> str:
        adapter = getattr(self.ctx, "_es_adapter", None)
        cfg = getattr(adapter, "cfg", None) or getattr(self.ctx, "cfg", None) or {}
        return str(cfg.get("id_col") or getattr(self.ctx, "primary_key", "_id") or "_id")

    def _pk_term_field(self, id_col: str, index: str) -> str:
        adapter = getattr(self.ctx, "_es_adapter", None)
        cfg = getattr(adapter, "cfg", None) or {}
        suffix = cfg.get("pk_keyword_suffix", ".keyword")
        try:
            mapping = adapter.get_field_mapping(index, id_col) if adapter is not None else None
            has_keyword = isinstance(mapping, dict) and "fields" in mapping and "keyword" in mapping["fields"]
        except Exception:
            has_keyword = False
        return f"{id_col}{suffix}" if has_keyword else id_col

    def _resolve_doc_id_for_update(self, logical_id: Any, index: str) -> str:
        """Return the concrete Elasticsearch ``_id`` for an update action.

        ES mode may configure ``id_col`` to a business key stored in ``_source``.
        The row scheduler then passes that business key as ``pk``.  A bulk
        ``update`` action, however, always targets Elasticsearch ``_id``.  If we
        send the business key as ``_id``, ES reports a successful upsert while
        the original document remains unchanged.  Resolve the real ``_id`` first
        so same-index writeback mutates the source document.
        """
        doc_id = str(logical_id)
        id_col = self._es_id_col()
        if id_col == "_id":
            return doc_id

        cache_key = f"{index}\0{id_col}\0{doc_id}"
        if cache_key in self._resolved_doc_id_cache:
            cached = self._resolved_doc_id_cache[cache_key]
            return cached or doc_id

        term_field = self._pk_term_field(id_col, index)
        try:
            res = self.es.search(
                index=index,
                body={
                    "query": {"term": {term_field: doc_id}},
                    "_source": False,
                    "size": 2,
                },
                request_timeout=int(getattr(self.ctx, "es_request_timeout", 60)),
            )
            hits = res.get("hits", {}).get("hits", [])
            if hits:
                resolved = str(hits[0].get("_id"))
                if len(hits) > 1:
                    tlog_warn(
                        f"⚠️ ESSink: id_col={id_col!r} value={doc_id!r} 命中多筆文件，"
                        f"將更新第一筆 _id={resolved!r}。"
                    )
                self._resolved_doc_id_cache[cache_key] = resolved
                return resolved
        except Exception as ex:
            tlog_warn(f"⚠️ ESSink: 無法以 {id_col}={doc_id!r} 解析 ES _id，改用原值更新：{ex}")

        self._resolved_doc_id_cache[cache_key] = None
        return doc_id

    def _build_update_action(self, item: Dict[str, Any]) -> Dict[str, Any]:
        index = item.get("_index", self.index)
        logical_id = item["_id"]
        action = {
            "_op_type": "update",
            "_index": index,
            "_id": self._resolve_doc_id_for_update(logical_id, index),
            "doc": item["doc"],
            "doc_as_upsert": True,
        }
        id_col = self._es_id_col()
        if id_col != "_id" and isinstance(action["doc"], dict):
            action["doc"].setdefault(id_col, str(logical_id))
        return action

    def _maybe_parse_json(self, payload):
        if isinstance(payload, str):
            s = payload.strip()
            if s and s[0] in "{[":
                try:
                    return json.loads(s)
                except Exception:
                    pass
        return payload
    

    def _legacy_event_output_cols(self) -> List[str]:
        cols = getattr(self.ctx, "legacy_event_output_cols", None)
        if cols is None:
            cols = ["multidim_event_json"]
        return list(cols or [])

    def _resolve_output_profile(self, profile: Any, output_col: Optional[str]) -> str:
        profile_name = _normalize_output_profile(profile)
        if profile_name == "auto":
            profile_name = _infer_output_profile(output_col, self._legacy_event_output_cols())
        return _normalize_output_profile(profile_name)

    def _normalize_payload_by_profile(self, payload):
        """Apply the configured payload normalizer before writing to ES.

        output_profile intentionally decouples ES field names from task-specific
        payload handling. Profile behavior is resolved through the output profile
        registry so domain-specific transformers can live outside ESSink.
        """
        return self._normalize_payload_with_profile(payload, getattr(self, "output_profile", "auto"), self.output_col)

    def _normalize_payload_for_es(self, payload):
        # 空字串 → None；空陣列/空物件 → None（避免 exists 為真卻是「空結果」）
        if payload is None:
            return None
        if isinstance(payload, str):
            return payload if payload.strip() != "" else None
        if isinstance(payload, (list, dict)):
            return payload if len(payload) > 0 else None
        return payload
    
    
    def _normalize_event_payload(self, payload: any):
        """只處理我們的 multidim_event_json 結構：補 date_raw / time_raw、正規化日期與粒度。"""
        try:
            if not isinstance(payload, list):
                return payload
            out = []
            for item in payload:
                if not isinstance(item, dict):
                    out.append(item); continue
    
                item = dict(item)  # 淺複製
    
                # Event.time
                ev = item.get("Event")
                if isinstance(ev, dict):
                    t = ev.get("time")
                    if isinstance(t, str):
                        ev.setdefault("time_raw", t)
                        norm, prec = self._normalize_date_value(t)
                        if prec:
                            ev["time"] = norm
                            ev["time_precision"] = prec
                        else:
                            # 解析失敗則保留 raw，讓 mapping 的 ignore_malformed 接住
                            pass
    
                # date_range.start/end
                dr = item.get("date_range")
                if isinstance(dr, dict):
                    for k in ("start", "end"):
                        v = dr.get(k)
                        if isinstance(v, str):
                            dr.setdefault(f"{k}_raw", v)
                            norm, prec = self._normalize_date_value(v)
                            if prec:
                                dr[k] = norm
                                dr[f"{k}_precision"] = prec
    
                # Event_Timeline[].date
                tl = item.get("Event_Timeline")
                if isinstance(tl, list):
                    new_tl = []
                    for step in tl:
                        if isinstance(step, dict):
                            step = dict(step)
                            dv = step.get("date")
                            if isinstance(dv, str):
                                step.setdefault("date_raw", dv)
                                norm, prec = self._normalize_date_value(dv)
                                if prec:
                                    step["date"] = norm
                                    step["date_precision"] = prec
                        new_tl.append(step)
                    item["Event_Timeline"] = new_tl
    
                out.append(item)
            return out
        except Exception:
            return payload
    
    # ---- 新增：解析日期字串，回傳 (iso_str, precision) ----
    def _normalize_date_value(self, s: str):
        """Backward-compatible wrapper for the multidim_event profile date helper."""
        return normalize_date_value(s)
    
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
    
    # ---- 取代你舊的 _normalize_event_payload（不覆蓋 time/date）----
    
    def _build_meta(self) -> Optional[dict]:
        if not self.meta_field:
            return None
    
        rr = (getattr(self.ctx, "_es_adapter", None).cfg.get("rerun", {}) 
              if getattr(self.ctx, "_es_adapter", None) else {})
    
        meta = dict(self.meta_base or {})
        # 固定欄位
        meta["processed_at"]  = _now_iso_utc()
        meta["output_field"]  = self.output_col
        if getattr(self, "output_profile", None):
            meta["output_profile"] = self.output_profile
        stage_cfg = getattr(self.ctx, "stage_cfg", None) or {}
        if getattr(self.ctx, "pipeline_name", None):
            meta.setdefault("pipeline_name", self.ctx.pipeline_name)
        if isinstance(stage_cfg, dict) and stage_cfg:
            if stage_cfg.get("version"):
                meta.setdefault("pipeline_version", stage_cfg.get("version"))
            meta.setdefault("pipeline_enabled", bool(stage_cfg.get("enabled", False)))
    
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
        
    def _normalize_event_payload_v2(self, payload: any):
        """Backward-compatible wrapper for the multidim_event profile transformer."""
        return normalize_multidim_event_payload(payload)
        
 
    def _prepare_update_doc(self, payload: Any, save_raw_input: bool = False,
                            input_col: Optional[str] = None, input_value: Any = None):
        doc = {self.output_col: payload}
    
        if getattr(self.ctx, "record_update_time", False):
            ts = _now_iso_utc()
            doc["update_time_ai"] = ts  # 根層
    
            # ✅（可選）也寫到 output_col 內層
            # 記得對應的 mapping 若要查 nested 內的時間，需在 multidim_event_json.properties.update_time_ai 定義成 date。
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
            
    def _profile_for_output_col(self, output_col: str, rule: Optional[dict] = None) -> str:
        """Resolve the output profile for a single ES writeback field."""
        if isinstance(rule, dict) and rule.get("output_profile") is not None:
            return self._resolve_output_profile(rule.get("output_profile"), output_col)
        if output_col == self.output_col:
            return self._resolve_output_profile(getattr(self, "output_profile", "auto"), output_col)
        return self._resolve_output_profile("auto", output_col)

    def _normalize_payload_with_profile(self, payload: Any, profile: str, output_col: str) -> Any:
        profile = self._resolve_output_profile(profile, output_col)
        registry = get_default_registry()
        if registry.has(profile):
            return registry.normalize_payload(
                profile,
                payload,
                ctx=self.ctx,
                output_col=output_col,
                sink=self,
            )
        if self._debug:
            tlog_warn(f"⚠️ ESSink: 未知 output_profile={profile!r}，略過任務特定正規化。")
        return payload

    def _build_meta_for_field(self, output_col: str, profile: str, meta_base: Optional[dict] = None) -> Optional[dict]:
        old_output_col = self.output_col
        old_profile = self.output_profile
        old_meta_base = self.meta_base
        try:
            self.output_col = output_col
            self.output_profile = profile
            self.meta_base = dict(meta_base or {})
            return self._build_meta()
        finally:
            self.output_col = old_output_col
            self.output_profile = old_profile
            self.meta_base = old_meta_base

    def _prepare_update_doc_for_field(
        self,
        output_col: str,
        payload: Any,
        *,
        profile: str,
        meta_field: Optional[str],
        meta_base: Optional[dict] = None,
        write_meta: bool = True,
    ) -> dict:
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

        if write_meta and meta_field:
            meta = self._build_meta_for_field(output_col, profile, meta_base=meta_base)
            if meta:
                doc[meta_field] = meta
        return doc

    def _iter_multifield_write_docs(self, result_map: dict) -> list[dict]:
        rules = getattr(self.ctx, "es_writeback_rules", None) or []
        if not isinstance(rules, list) or not rules:
            return []

        docs: list[dict] = []
        for rule in rules:
            if not isinstance(rule, dict):
                continue
            output_col = str(rule.get("output_col", "") or "").strip()
            if not output_col or output_col not in result_map:
                continue
            raw_payload = self._maybe_parse_json(result_map.get(output_col))
            profile = self._profile_for_output_col(output_col, rule)
            payload = self._normalize_payload_with_profile(raw_payload, profile, output_col)
            payload = self._normalize_payload_for_es(payload)
            if payload is None:
                if self._debug:
                    tlog(f"ℹ️ ESSink.write_main: 欄位 {output_col} 規範化後為空，略過寫入。")
                continue
            meta_field = rule.get("meta_field")
            if meta_field is None:
                meta_field = f"{output_col}_meta"
            meta_field = str(meta_field or "").strip() or None
            doc = self._prepare_update_doc_for_field(
                output_col,
                payload,
                profile=profile,
                meta_field=meta_field,
                meta_base=rule.get("meta_base") if isinstance(rule.get("meta_base"), dict) else None,
                write_meta=bool(rule.get("write_meta", True)),
            )
            docs.append({"_id": None, "_index": str(rule.get("index") or self.index), "doc": doc})
        # Backward-compatible fallback: if callers pass a dict without a matching
        # es_writeback_rules entry, write the primary output column as before.
        if not docs and self.output_col in result_map:
            raw_payload = self._maybe_parse_json(result_map.get(self.output_col))
            profile = self._profile_for_output_col(self.output_col, None)
            payload = self._normalize_payload_with_profile(raw_payload, profile, self.output_col)
            payload = self._normalize_payload_for_es(payload)
            if payload is not None:
                doc = self._prepare_update_doc_for_field(
                    self.output_col,
                    payload,
                    profile=profile,
                    meta_field=self.meta_field,
                    meta_base=self.meta_base,
                    write_meta=bool(self.meta_field),
                )
                docs.append({"_id": None, "_index": self.index, "doc": doc})
        return docs

    def write_main(self, pk, result_text: Any, update_time: Optional[str] = None):
        if pk is None:
            tlog_warn("⚠️ ESSink.write_main: pk 為 None，略過寫入。")
            return
    
        if not self.write_output:
            if self._debug:
                tlog(f"ℹ️ ESSink.write_main: write_output=False，略過 ES 文件寫入（pk={pk}）。")
            return

        if isinstance(result_text, dict):
            docs = self._iter_multifield_write_docs(result_text)
            if docs:
                for item in docs:
                    item["_id"] = pk
                    self._buffer.append(item)
                    self._buffer_bytes += self._estimate_size(item)
                if self._debug:
                    tlog(f"[ESSink] multifield buffer size={len(self._buffer)}, bytes~={self._buffer_bytes}")
                self._maybe_flush()
                return

        # 1) 解析
        payload = self._maybe_parse_json(result_text)
    
        # 2) 依 YAML/ctx output_profile 執行任務特定正規化；預設不改任意 JSON/text。
        payload = self._normalize_payload_by_profile(payload)
    
        # 3) 空值歸一
        payload = self._normalize_payload_for_es(payload)
    
        # 🚫 規範化後為 None → 直接略過（避免 exists 誤判）
        if payload is None:
            if self._debug:
                tlog("ℹ️ ESSink.write_main: 規範化後為空，略過寫入。")
            return
    
        doc = self._prepare_update_doc(payload)
        item = {"_id": pk, "_index": self.index, "doc": doc}
        self._buffer.append(item)
        self._buffer_bytes += self._estimate_size(item)

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
    
        actions_gen = (self._build_update_action(item) for item in self._buffer)
    
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
                raise RuntimeError(f"ESSink bulk update failed: {errors[:3]}")

            print(f"💾 bulk 成功筆數：{success}")
            self._buffer.clear()
            self._buffer_bytes = 0
            self._last_flush_ts = time.time()
    
            # 二擇一即可，不必再呼叫一次 refresh
            # try: self.es.indices.refresh(index=self.index)
            # except Exception: pass
    
        except Exception as ex:
            print(f"⚠️ ESSink._flush 例外：{ex}")
            raise

    def flush_all(self):
        self._flush()
