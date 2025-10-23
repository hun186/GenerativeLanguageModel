# czjLLM/es_mode/runtime/sinks/es_sink.py
from typing import Any, Optional, List, Dict
from elasticsearch import Elasticsearch, helpers
import datetime
from datetime import timezone
import re
import json
import atexit

# 與其他 sink 保持一致的 logging helper（如果找不到模組會 fallback 到 print）
try:
    from ....job_manager.console_ui import tlog, tlog_warn
except Exception:
    def tlog(msg): print(msg)
    def tlog_warn(msg): print(msg)

def _now_iso_utc() -> str:
    # 例：'2025-10-22T13:37:43Z'（無微秒，最穩）
    return datetime.datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")       
        
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
                 flatten_json: bool = False):
        self.ctx = ctx
        self.es: Elasticsearch = es_client
        self.index = index
        # 若沒有顯式提供 output_col，從 ctx 取得；若還沒，預設 'LLM_result'
        self.output_col = output_col or getattr(ctx, "output_col", "LLM_result")
        self.flush_every = int(flush_every or getattr(ctx, "es_flush_every", 1))
        self.flatten_json = bool(flatten_json or getattr(ctx, "flatten_json", False))

        self._buffer: List[Dict[str, Any]] = []
        self._debug = bool(getattr(self.ctx, "debug_es_sink", False))
        # ✅ 內部快取：實際生效的欄位（可能是 output_col 或 output_col+"_json"）
        self._effective_output_col = None
        
        atexit.register(self.flush_all)  # 程式結束時保底 flush
        #print("ctx in ESSink",self.ctx)

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
            s = payload.strip()
            if s and s[0] in "{[":
                try:
                    return json.loads(s)
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
    
    # ---- 取代你舊的 _normalize_event_payload（不覆蓋 time/date）----
    def _normalize_event_payload_v2(self, payload: any):
        """
        只處理我們的多維事件結構（list[dict]），
        - Event.time 產出：Event.time_raw / Event.time_iso / Event.time_precision
        - Event_Timeline[].date 產出：date_raw / date_iso / date_precision
        - date_range.start/end 可選：加上 *_raw / *_precision（start/end 本身仍可留 date 類型）
        """
        try:
            if not isinstance(payload, list):
                return payload
    
            out = []
            for item in payload:
                if not isinstance(item, dict):
                    out.append(item); continue
                obj = dict(item)  # 淺拷貝
    
                # --- Event.time -> 新三欄 ---
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
    
                # --- Event_Timeline[].date -> 新三欄 ---
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
            doc["update_time_ai"] = _now_iso_utc()      # ← 改成合規 ISO UTC
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
    def write_main(self, pk, result_text: Any, update_time: Optional[str] = None):
        if pk is None:
            tlog_warn("⚠️ ESSink.write_main: pk 為 None，略過寫入。")
            return
    
        # 1) 解析
        payload = self._maybe_parse_json(result_text)
    
        # 2) 事件正規化（僅指定欄位）
        if str(self.output_col) in ("multidim_event_json", "llm_result_json"):
            payload = self._normalize_event_payload_v2(payload)  # 或你的 _normalize_event_payload
    
        # 3) 空值歸一
        payload = self._normalize_payload_for_es(payload)
    
        # 🚫 規範化後為 None → 直接略過（避免 exists 誤判）
        if payload is None:
            if self._debug:
                tlog("ℹ️ ESSink.write_main: 規範化後為空，略過寫入。")
            return
    
        doc = self._prepare_update_doc(payload)
        #print("ctx in write_main",self.ctx)
        #if update_time:
            #doc["update_time"] = update_time
        #print("doc",doc)
        #print("doc update_time",doc["update_time"])
        self._buffer.append({"_id": pk, "doc": doc})
        if self._debug:
            tlog(f"[ESSink] buffer size = {len(self._buffer)} (flush_every={self.flush_every})")
        if len(self._buffer) >= self.flush_every:
            self._flush()

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
        self._buffer.append({"_id": pk, "doc": doc})
        if len(self._buffer) >= self.flush_every:
            self._flush()

    def ensure_flatten_schema(self, allowed_fields=None):
        # ES 不需為 nested JSON 做額外 schema 建立；保持與 SqlSink API 相容
        return

    # -------- flush / bulk --------
    def _flush(self):
        if not self._buffer:
            return
        actions = (
            {
                "_op_type": "update",
                "_index": self.index,
                "_id": item["_id"],
                "doc": item["doc"],
                "doc_as_upsert": True,
            }
            for item in self._buffer
        )
        
        try:
            #print("actions in flush",list(actions))
            #raise Exception
            '''
            ok, errors = helpers.bulk(
                self.es,
                actions,
                raise_on_error=False,   # 不丟例外，但我們自己印錯誤
                stats_only=False,
                request_timeout=120,
            )
            '''
            success, errors = helpers.bulk(self.es, actions, raise_on_error=False)
            if getattr(self.ctx, "es_refresh_after_flush", True):  # ← 開發期預設 True
                self.es.indices.refresh(index=self.index)
            if self._debug:
                print(f"💾 ESSink: flush {len(actions)} actions (successes: {success}) to index {self.index}")
            # ✅ 可視化結果
            if errors:
                print(f"❌ bulk 有錯（僅示範前 3 筆）：{errors[:3]}")
            else:
                print(f"💾 bulk 成功筆數：{success}")
                #print("actions in flush",list(actions))
    
            # ✅ 讓後續立刻查得到（避免你以為沒寫）
            try:
                self.es.indices.refresh(index=self.index)
            except Exception as _:
                pass
        except Exception as ex:
            print(f"⚠️ ESSink._flush 例外：{ex}")
        finally:
            self._buffer.clear()

    def flush_all(self):
        self._flush()
