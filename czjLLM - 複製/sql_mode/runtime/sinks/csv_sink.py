# sql_mode/runtime/sinks/csv_sink.py
from typing import List, Optional
import os, json
import pandas as pd
from pandas.api.types import is_string_dtype, is_object_dtype
from ....job_manager.console_ui import tlog, tlog_warn

def _ensure_text_col(df: pd.DataFrame, col: str):
    if col not in df.columns:
        try:
            df[col] = pd.Series([pd.NA]*len(df), dtype="string")
        except Exception:
            df[col] = pd.Series([""]*len(df), dtype="object")
    elif not (is_string_dtype(df[col]) or is_object_dtype(df[col])):
        try: df[col] = df[col].astype("string")
        except Exception: df[col] = df[col].astype("object")

def _norm(v):
    if v is None: return ""
    try:
        import math
        if isinstance(v, float) and math.isnan(v): return ""
    except Exception:
        pass
    return str(v).strip()

def _jsonify(val):
    # CSV 不支援 list/dict，統一轉成 JSON 字串
    if isinstance(val, (list, dict)):
        return json.dumps(val, ensure_ascii=False)
    return val

class CsvSink:
    """
    CSV 版 Sink（子表用獨立 CSV 檔）。
    - 主表：output_path（若不存在則用 input_path 初始化）
    - 子表：output_path 同目錄下 <stem>__<output_col>_flattened.csv
    - 主鍵：支援自訂欄位；若為 'row_id' 就建固定序號欄位
    - 緩寫：主表/子表各有 flush_every
    """
    def __init__(self, ctx, input_path: str, output_path: str,
                 flush_main_every: int = 10, flush_sub_every: int = 10):
        self.ctx = ctx
        self.input_path  = os.path.abspath(input_path or "")
        self.output_path = os.path.abspath(output_path or "")
        self.df: Optional[pd.DataFrame] = None
        self.sub_df: Optional[pd.DataFrame] = None
        self.flush_main_every = max(int(flush_main_every or 1), 1)
        self.flush_sub_every  = max(int(flush_sub_every  or 1), 1)
        self._dirty_main = False
        self._dirty_sub  = False
        self._main_since = 0
        self._sub_since  = 0
        self._dup_warned_keys = set()
        self.subtable_csv_path = None   # 於 open() 決定
        self._info_emitted = False
        self._debug = bool(getattr(self.ctx, "debug_csv_sink", False))

    # ---- lifecycle ----
    def open(self):
        if not self.input_path or not self.output_path:
            raise ValueError("CsvSink input/output 路徑未設定")
        os.makedirs(os.path.dirname(self.output_path), exist_ok=True)

        # 續跑優先 output，否則讀 input
        src = self.output_path if os.path.isfile(self.output_path) else self.input_path
        self.df = pd.read_csv(src)
        self.df = self.df.reset_index(drop=True)

        # 主鍵欄就位
        pk = getattr(self.ctx, "primary_key", None) or "row_id"
        self.ctx.primary_key = pk
        if pk == "row_id":
            if "row_id" not in self.df.columns:
                self.df["row_id"] = range(len(self.df))
        else:
            if pk not in self.df.columns:
                # 嘗試從 input 補回
                try:
                    src_df = pd.read_csv(self.input_path)
                    if pk in src_df.columns:
                        self.df[pk] = src_df[pk].reset_index(drop=True)
                    else:
                        tlog_warn(f"⚠️ 找不到主鍵欄位 {pk}，改用 row_id")
                        self.ctx.primary_key = "row_id"
                        if "row_id" not in self.df.columns:
                            self.df["row_id"] = range(len(self.df))
                except Exception as ex:
                    tlog_warn(f"⚠️ 回補主鍵欄位失敗：{ex}，改用 row_id")
                    self.ctx.primary_key = "row_id"
                    if "row_id" not in self.df.columns:
                        self.df["row_id"] = range(len(self.df))

        # 輸出欄
        _ensure_text_col(self.df, self.ctx.output_col)

        # update_time（CSV 我們就寫 isoformat 字串）
        if getattr(self.ctx, "record_update_time", False) and "update_time" not in self.df.columns:
            _ensure_text_col(self.df, "update_time")

        # 如果是從 input 開的，先初始化一份到 output
        if os.path.abspath(src) != os.path.abspath(self.output_path):
            self.df.to_csv(self.output_path, index=False)

        # 子表 CSV 路徑（同資料夾）
        stem = os.path.splitext(os.path.basename(self.output_path))[0]
        self.subtable_csv_path = os.path.join(
            os.path.dirname(self.output_path),
            f"{stem}__{self.ctx.output_col}_flattened.csv"
        )

        # 一次性提示
        if not self._info_emitted:
            self._info_emitted = True
            tlog(f"ℹ️ CsvSink 緩寫：主表每 {self.flush_main_every} 筆、子表每 {self.flush_sub_every} 筆自動落盤。")

    def close(self):
        self._flush_main(True)
        self._flush_sub(True)

    # ---- 查找多筆 row（支援重複主鍵 → 扇出寫入）----
    def _find_row_indices(self, pk_val):
        pk_col = getattr(self.ctx, "primary_key", None)
        if not pk_col or pk_col not in self.df.columns:
            tlog_warn(f"⚠️ CsvSink 找不到主鍵欄位：{pk_col}（pk={pk_val}）")
            return []
        s = self.df[pk_col].apply(_norm)
        key = _norm(pk_val)
        idxs = self.df.index[s == key].tolist()
        if not idxs:
            tlog_warn(f"⚠️ 找不到主鍵 {pk_col}='{key or '(空)'}' 對應列，略過。")
            return []
        if len(idxs) > 1 and key not in self._dup_warned_keys:
            self._dup_warned_keys.add(key)
            tlog_warn(f"⚠️ 主鍵 {pk_col}='{key}' 出現 {len(idxs)} 列，將同步寫入所有列。")
        return idxs

    # ---- main table ----
    def write_main(self, pk, result_text: str, update_time: Optional[str] = None):
        try:
            idxs = self._find_row_indices(pk)
            if not idxs:
                return
            _ensure_text_col(self.df, self.ctx.output_col)
            if getattr(self.ctx, "record_update_time", False):
                _ensure_text_col(self.df, "update_time")

            for i in idxs:
                self.df.at[i, self.ctx.output_col] = result_text
                if getattr(self.ctx, "record_update_time", False) and update_time:
                    if isinstance(update_time, str) and update_time.startswith("'"):
                        update_time = update_time.lstrip("'")
                    self.df.at[i, "update_time"] = str(update_time)

            self._dirty_main = True
            self._main_since += len(idxs)
            if self._main_since >= self.flush_main_every:
                self._flush_main()
        except Exception as ex:
            tlog_warn(f"⚠️ CsvSink.write_main 失敗（pk={pk}）：{ex}")

    def fetch_input(self, pk):
        try:
            idxs = self._find_row_indices(pk)
            if not idxs: return None
            return self.df.at[idxs[0], self.ctx.input_col]
        except Exception:
            return None

    # ---- flatten (subtable) ----
    def ensure_flatten_schema(self, allowed_fields: Optional[List[str]] = None):
        # 決定是否要「額外」寫 raw input 欄（若 pk==input_col，就不重複寫）
        save_raw = bool(getattr(self.ctx, "save_raw_input_when_flatten", False))
        in_col    = getattr(self.ctx, "input_col", None)
        if getattr(self.ctx, "primary_key", None) == in_col:
            save_raw = False
        fields = list(allowed_fields or (self.ctx.allowed_output_fields or []))
        # 初始化/補欄位
        if self.sub_df is None:
            cols = [self.ctx.primary_key, "seq"]
            if save_raw and in_col:
                cols.append(in_col)
            cols.extend(fields)
            self.sub_df = pd.DataFrame(columns=cols)
        else:
            for c in [self.ctx.primary_key, "seq"] + fields:
                if c not in self.sub_df.columns:
                    self.sub_df[c] = None
            if save_raw and in_col and in_col not in self.sub_df.columns:
                self.sub_df[in_col] = None

    def write_flatten(self, pk, json_array, save_raw_input: bool, input_col: Optional[str], input_value):
        # CSV 子表：每次覆蓋整檔（但有緩寫）
        if self.sub_df is None:
            self.ensure_flatten_schema(getattr(self.ctx, "allowed_output_fields", None))

        # 刪舊
        if self.ctx.primary_key in self.sub_df.columns:
            self.sub_df = self.sub_df[self.sub_df[self.ctx.primary_key] != pk]

        # append
        rows = []
        for i, rec in enumerate(json_array, 1):
            row = {self.ctx.primary_key: pk, "seq": i}
            if save_raw_input and input_col:
                row[input_col] = input_value
            # 將 list/dict 轉字串
            for k, v in (rec or {}).items():
                row[k] = _jsonify(v)
            rows.append(row)

        if rows:
            self.sub_df = pd.concat([self.sub_df, pd.DataFrame(rows)], ignore_index=True)

        self._dirty_sub = True
        self._sub_since += 1
        if self._sub_since >= self.flush_sub_every:
            self._flush_sub()

    # ---- flush ----
    def _flush_main(self, force: bool=False):
        if not self._dirty_main and not force:
            return
        self.df.to_csv(self.output_path, index=False)
        self._dirty_main = False
        self._main_since = 0

    def _flush_sub(self, force: bool=False):
        if not self._dirty_sub and not force:
            return
        if self.sub_df is not None:
            self.sub_df.to_csv(self.subtable_csv_path, index=False)
        self._dirty_sub = False
        self._sub_since = 0
