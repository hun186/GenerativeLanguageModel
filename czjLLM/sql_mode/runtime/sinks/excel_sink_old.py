# sql_mode/runtime/sinks/excel_sink.py
from typing import Any, Optional, List, Dict
from datetime import datetime
import threading
from utilities.excel_utils import write_dataframe

class ExcelSink:
    def __init__(self, df, output_file, output_col, record_update_time=False, flush_every=20):
        self.df = df
        self.output_file = output_file
        self.output_col = output_col
        self.record_update_time = record_update_time
        self.flush_every = max(1, int(flush_every))
        self._lock = threading.Lock()
        self._dirty = 0
        if self.record_update_time and ("update_time" not in self.df.columns):
            self.df["update_time"] = ""

    def open(self):  # 與 SQL 介面對齊
        pass

    def close(self):
        self.finalize()

    def _flush_if_needed(self):
        self._dirty += 1
        if self._dirty >= self.flush_every:
            write_dataframe(self.df, self.output_file, index=False)
            self._dirty = 0

    def write_main(self, pk: Any, result_text: str, update_time: Optional[str]) -> None:
        with self._lock:
            self.df.at[pk, self.output_col] = result_text
            if self.record_update_time:
                self.df.at[pk, "update_time"] = update_time or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self._flush_if_needed()

    def ensure_flatten_schema(self, fields: Optional[List[str]]) -> None:
        if not fields: return
        with self._lock:
            for col in fields:
                if col not in self.df.columns:
                    self.df[col] = ""

    def write_flatten(
        self,
        pk: Any,
        json_array: List[Dict[str, Any]],
        *,
        save_raw_input: bool,
        input_col: Optional[str],
        input_value: Optional[str],
    ) -> None:
        # Excel：把每個 dict 的鍵寫回同一列（遇到多項可取第一項或合併，這裡取第一項）
        if not json_array: return
        row = json_array[0]
        with self._lock:
            for k, v in row.items():
                if k not in self.df.columns:
                    self.df[k] = ""
                self.df.at[pk, k] = v
            if save_raw_input and input_col:
                if input_col not in self.df.columns:
                    self.df[input_col] = ""
                self.df.at[pk, input_col] = input_value or ""
            self._flush_if_needed()

    def fetch_input(self, pk: Any) -> Optional[str]:
        # 直接從 df 取
        try:
            return str(self.df.at[pk, self.output_col])  # 或 ctx.input_col；依你的需求決定
        except Exception:
            return None

    def finalize(self):
        with self._lock:
            write_dataframe(self.df, self.output_file, index=False)
            self._dirty = 0
