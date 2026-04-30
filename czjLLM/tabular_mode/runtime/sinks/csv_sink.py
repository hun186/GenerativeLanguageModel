# tabular/sinks/csv_sink.py
import os
import pandas as pd
from pathlib import Path
from typing import Optional, List
from pandas.api.types import is_string_dtype, is_object_dtype
from czjLLM.job_manager.console_ui import tlog, tlog_warn
from czjLLM.utilities.excel_utils import read_dataframe, write_dataframe
from czjLLM.excel_mode.schema.subtable_ops import ensure_excel_subtable_config

class CSVSink:
    """
    主表：output_csv（整檔覆寫）
    子表：<output_stem>__{ctx.subtable_name}.csv（sidecar）
    """
    def __init__(self, ctx, main_csv: str, flush_main_every: int = 10, flush_sub_every: int = 10):
        self.ctx = ctx
        self.main_csv = os.path.abspath(main_csv)
        self.df: Optional[pd.DataFrame] = None
        self.sub_df: Optional[pd.DataFrame] = None
        self.flush_main_every = max(int(flush_main_every), 1)
        self.flush_sub_every  = max(int(flush_sub_every), 1)
        self._dirty_main = False; self._dirty_sub = False
        self._main_since = 0; self._sub_since = 0

    def _sub_csv_path(self) -> str:
        stem = Path(self.main_csv).with_suffix("").name
        ensure_excel_subtable_config(self.ctx, self.main_csv)
        name = f"{stem}_{getattr(self.ctx,'subtable_name','subtable')}.csv"
        return os.path.join(os.path.dirname(self.main_csv), name)

    def open(self):
        os.makedirs(os.path.dirname(self.main_csv), exist_ok=True)
        self.df = read_dataframe(self.main_csv)
        # 讓輸出欄與 update_time 都是「文字 dtype」
        self._ensure_text_col(self.df, self.ctx.output_col)
        # 確保欄位存在
        if self.ctx.output_col not in self.df.columns:
            self.df[self.ctx.output_col] = ""
        if getattr(self.ctx, "record_update_time", False) and "update_time" not in self.df.columns:
            self.df["update_time"] = pd.NaT

        # 子表（若有開）
        if getattr(self.ctx, "flatten_json_output", False):
            sub_path = self._sub_csv_path()
            if os.path.isfile(sub_path):
                self.sub_df = read_dataframe(sub_path)
            else:
                self.sub_df = None

    def close(self):
        self._flush_main(force=True)
        self._flush_sub(force=True)

    # ---- helpers ----
    def _ensure_text_col(self, df, col: str):
        if col not in df.columns:
            try:
                df[col] = pd.Series([pd.NA]*len(df), dtype="string")
            except Exception:
                df[col] = df.get(col, "").astype("object")
        elif not (is_string_dtype(df[col]) or is_object_dtype(df[col])):
            # 把 float64 等轉為 string，避免將來指派字串出現 dtype 警告
            try:
                df[col] = df[col].astype("string")
            except Exception:
                df[col] = df[col].astype("object")
                
    # --- main ---
    def _find_row_indices(self, pk):
        pk_col = getattr(self.ctx, "primary_key", "row_id")
        if pk_col == "row_id":
            # row_id：直接靠 index
            if isinstance(pk, int):
                return [pk]
            try: return [int(pk)]
            except Exception: return []
        # 其他主鍵：等值比對（字串化去空白）
        s = self.df[pk_col].astype(str).str.strip()
        pk_norm = "" if pk is None else str(pk).strip()
        return self.df.index[s == pk_norm].tolist()

    # ---- main write ----
    def write_main(self, pk, result_text: str, update_time: str | None = None):
        try:
            idxs = self._find_row_indices(pk)
            if not idxs:
                return

            value_map = result_text if isinstance(result_text, dict) else {self.ctx.output_col: result_text}
            for col in value_map.keys():
                self._ensure_text_col(self.df, col)
            if getattr(self.ctx, "record_update_time", False):
                self._ensure_text_col(self.df, "update_time")

            # 寫入（扇出到所有同鍵列）
            for i in idxs:
                for col, val in value_map.items():
                    self.df.at[i, col] = str(val)

                if getattr(self.ctx, "record_update_time", False) and update_time:
                    # CSV 用「字串」存時間，避免 NaT/float 衝突
                    ts = str(update_time).lstrip("'")  # 清掉可能的前導單引號
                    self.df.at[i, "update_time"] = ts

            self._dirty_main = True
            self._main_since += len(idxs)
            if self._main_since >= self.flush_main_every:
                self._flush_main()
        except Exception as ex:
            tlog_warn(f"⚠️ CSVSink.write_main 失敗（pk={pk}）：{ex}")

    def _flush_main(self, force: bool=False):
        if not self._dirty_main and not force:
            return
        write_dataframe(self.df, self.main_csv, index=False)
        self._dirty_main = False; self._main_since = 0

    # --- flatten ---
    def ensure_flatten_schema(self, allowed_fields: Optional[List[str]] = None):
        pk_col  = getattr(self.ctx, "primary_key", "row_id")
        sub_in  = getattr(self.ctx, "subtable_input_col", None)
        fields  = list(allowed_fields or (self.ctx.allowed_output_fields or []))
        if self.sub_df is None:
            cols = [pk_col, "seq"] + ([sub_in] if sub_in else []) + fields
            self.sub_df = pd.DataFrame(columns=cols)
        else:
            for c in [pk_col, "seq"] + fields:
                if c not in self.sub_df.columns:
                    self.sub_df[c] = None
            if sub_in and sub_in not in self.sub_df.columns:
                self.sub_df[sub_in] = None

    def fetch_input(self, pk):
        idxs = self._find_row_indices(pk)
        if not idxs: return None
        return self.df.at[idxs[0], self.ctx.input_col]

    def write_flatten(self, pk, json_array, save_raw_input: bool, input_col: Optional[str], input_value):
        if self.sub_df is None:
            self.ensure_flatten_schema(getattr(self.ctx, "allowed_output_fields", None))
        pk_col  = getattr(self.ctx, "primary_key", "row_id")

        # 刪舊
        if pk_col in self.sub_df.columns:
            self.sub_df = self.sub_df[self.sub_df[pk_col] != pk]

        rows = []
        for i, rec in enumerate(json_array, 1):
            row = {pk_col: pk, "seq": i}
            if save_raw_input and input_col:
                row[input_col] = input_value
            row.update(rec or {})
            rows.append(row)
        if rows:
            self.sub_df = pd.concat([self.sub_df, pd.DataFrame(rows)], ignore_index=True)

        self._dirty_sub = True
        self._sub_since += 1
        if self._sub_since >= self.flush_sub_every:
            self._flush_sub()

    def _flush_sub(self, force: bool=False):
        if not self._dirty_sub and not force:
            return
        if self.sub_df is not None:
            write_dataframe(self.sub_df, self._sub_csv_path(), index=False)
        self._dirty_sub = False; self._sub_since = 0
