# czjLLM/es_mode/runtime/sinks/es_sink.py
from typing import Any, Optional, List, Dict
from elasticsearch import Elasticsearch, helpers
import datetime
import json

# 與其他 sink 保持一致的 logging helper（如果找不到模組會 fallback 到 print）
try:
    from ....job_manager.console_ui import tlog, tlog_warn
except Exception:
    def tlog(msg): print(msg)
    def tlog_warn(msg): print(msg)

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
        self.flush_every = int(flush_every or getattr(ctx, "es_flush_every", 100))
        self.flatten_json = bool(flatten_json or getattr(ctx, "flatten_json", False))

        self._buffer: List[Dict[str, Any]] = []
        self._debug = bool(getattr(self.ctx, "debug_es_sink", False))

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

    def _prepare_update_doc(self, payload: Any, save_raw_input: bool = False, input_col: Optional[str] = None, input_value: Any = None):
        """
        準備要放入 ES doc 的內容（永遠放在 self.output_col）
        payload 可以是字串(LLM 結果) 或 list(dict) (flatten 結果)
        """
        doc = {self.output_col: payload}
        if getattr(self.ctx, "record_update_time", False):
            # 若 caller 傳了 update_time 字串則不覆蓋；否則加上現在時間
            now = datetime.datetime.utcnow().isoformat()
            doc.setdefault("update_time", now)
        if save_raw_input and input_col:
            # 將原始輸入也一起存入（使用 input_col 的路徑字串）
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

    def write_main(self, pk, result_text: Any, update_time: Optional[str] = None):
        """
        寫回 single result：只更新 output_col（不覆蓋其它欄位）
        pk -> ES document _id
        """
        if pk is None:
            tlog_warn("⚠️ ESSink.write_main: pk 為 None，略過寫入。")
            return

        # 儲存要送到 ES 的 payload（字串或物件）
        payload = result_text
        if update_time:
            # 如果外部傳了 update_time，使用之（並由 _prepare_update_doc 設定在 doc）
            doc = self._prepare_update_doc(payload)
            doc["update_time"] = update_time
        else:
            doc = self._prepare_update_doc(payload)

        # push to buffer
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
        actions = []
        for item in self._buffer:
            _id = item.get("_id")
            doc = item.get("doc", {})
            action = {
                "_op_type": "update",
                "_index": self.index,
                "_id": _id,
                "doc": doc,
                "doc_as_upsert": True,
            }
            actions.append(action)
        try:
            success, _ = helpers.bulk(self.es, actions, raise_on_error=False)
            if self._debug:
                tlog(f"💾 ESSink: flush {len(actions)} actions (successes: {success}) to index {self.index}")
        except Exception as ex:
            tlog_warn(f"⚠️ ESSink._flush 發生例外：{ex}")
            # 若需要更細緻的錯誤處理，可在此展開
        finally:
            self._buffer.clear()

    def flush_all(self):
        self._flush()
