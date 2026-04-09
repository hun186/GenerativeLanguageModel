#sql_mode/runtime/sinks/excel_sink.py
from typing import List, Optional
import os
import pandas as pd
import numpy as np
import json
import math
from pandas.api.types import is_string_dtype, is_object_dtype
from ....utilities.excel_utils import read_dataframe, write_dataframe
from ....utilities.excel_utils import write_dataframe_sheet
from ....job_manager.console_ui import tlog, tlog_warn
from ....excel_mode.schema.subtable_ops import ensure_excel_subtable_config
from ....job_manager.console_ui import tlog, tlog_warn

class ExcelSink:
    """
    給 row_merger_watchdog_generic 使用的 Excel 寫回器。
    - pk 預設對應 DataFrame 的 index（pending_iter 用 df.reset_index(drop=True)）
    - 若 output_path 已存在，優先續跑；否則從 input_path 讀，並立即初始化輸出檔
    - 每寫入 flush_every 筆落盤；close() 再保險寫一次
    - 展平子表寫在同一個 .xlsx 的另一個 sheet（ctx.subtable_name）
    """
    def __init__(self, ctx, input_path: str, output_path: str,
                 main_sheet: Optional[str] = None,
                 flush_main_every: int = 10,
                 flush_sub_every: int = 10):
        self.ctx = ctx
        self.input_path  = os.path.abspath(input_path or "")
        self.output_path = os.path.abspath(output_path or "")
        self.main_sheet = main_sheet

        self.df: Optional[pd.DataFrame] = None
        self.sub_df: Optional[pd.DataFrame] = None

        self._flatten_ready_sig = None
        self.flush_main_every = max(int(flush_main_every or 1), 1)
        self.flush_sub_every  = max(int(flush_sub_every  or 1), 1)

        self._dirty_main = False
        self._dirty_sub  = False
        self._main_since = 0
        self._sub_since  = 0
        self._first_write_done = os.path.isfile(self.output_path)
        
        self._dup_warned_keys = set()
        self._info_emitted = False    # ← 一次性提示旗標
        self._debug = bool(getattr(self.ctx, "debug_excel_sink", False))

    # 小工具：帶等寬前綴，避免與 tqdm 亂版
    def _log(self, msg: str):
        try:
            tlog(msg)
        except Exception:
            print(msg)

    def _emit_buffering_info_once(self):
        """只提示一次：主表/子表的緩寫入策略與如何立即落盤。"""
        if self._info_emitted:
            return
        self._info_emitted = True
        self._log(
            f"ℹ️ ExcelSink 啟用緩寫入：主表每 {self.flush_main_every} 筆落盤，"
            f"子表每 {self.flush_sub_every} 筆落盤（或 close 時統一寫入）。"
        )
        self._log(
            "   若需要即時落盤，可設 flush_main_every=1 / flush_sub_every=1，"
            "或在程式適當時機呼叫 sink.flush_all()。"
        )
        
    def _ensure_text_col(self, df, col):
        if col not in df.columns:
            # 欄位不存在：建立新欄位（優先 string dtype，失敗則 object）
            try:
                df[col] = pd.Series([pd.NA] * len(df), dtype="string")
            except Exception:
                df[col] = pd.Series([""] * len(df), dtype="object")
        elif not (is_string_dtype(df[col]) or is_object_dtype(df[col])):
            # 欄位存在但不是文字型：轉成 string/object
            try:
                df[col] = df[col].astype("string")
            except Exception:
                df[col] = df[col].astype("object")
    
    def _ensure_dt_col(self, df, col="update_time"):
        if col not in df.columns:
            df[col] = pd.NaT
        # 轉真正的 datetime dtype（coerce 可吞掉亂字串）
        try:
            df[col] = pd.to_datetime(df[col], errors="coerce")
        except Exception:
            pass
        
    # ---- lifecycle ----
    def open(self):
        if not self.input_path:
            raise ValueError("ExcelSink.input_path 未設定")
        if not self.output_path:
            raise ValueError("ExcelSink.output_path 未設定")
        
        self.input_path  = os.path.abspath(self.input_path)
        self.output_path = os.path.abspath(self.output_path)
    
        # 這兩行是關鍵：看清楚現在到底拿到什麼
        print(f"[ExcelSink] input_path = {self.input_path}")
        print(f"[ExcelSink] output_path = {self.output_path}")
    
        if os.path.isdir(self.input_path):
            raise FileNotFoundError(f"❌ 給的是資料夾不是檔案：{self.input_path}")
        # output_path 不一定存在，但不能是資料夾
        if os.path.isdir(self.output_path):
            raise FileNotFoundError(f"❌ 給的是資料夾不是檔案：{self.output_path}")

        os.makedirs(os.path.dirname(self.output_path), exist_ok=True)
        
        self._emit_buffering_info_once()   # ← 新增：開檔後提示一次
        
        # 續跑：有輸出檔就讀輸出，否則讀輸入
        src = self.output_path if os.path.isfile(self.output_path) else self.input_path
        print(f"[ExcelSink] src = {src}")  # 再印一次最終讀誰
        self.df = read_dataframe(src).reset_index(drop=True)

        # 確保輸出欄位 / update_time 欄位存在
        out_col = self.ctx.output_col
        if out_col not in self.df.columns:
            self.df[out_col] = ""
            
        # --- 關鍵：確保輸出欄位是文字 dtype ---
        out_col = self.ctx.output_col
        self._ensure_text_col(self.df, out_col)
        
        
        #if getattr(self.ctx, "record_update_time", False) and "update_time" not in self.df.columns:
        #    self.df["update_time"] = ""
        # ← 關鍵：確保 df 裡的欄位就是 datetime dtype
        if getattr(self.ctx, "record_update_time", False):
            if "update_time" not in self.df.columns:
                self.df["update_time"] = pd.NaT
            try:
                self.df["update_time"] = pd.to_datetime(self.df["update_time"], errors="coerce")
            except Exception as ex:
                print(f"The following error occurs in ExcelSink.open(): {ex}")
                pass

        # 如果是從 input 開的，先初始化一份到 output，避免之後 flush/子表寫入找不到檔
        if os.path.abspath(src) != os.path.abspath(self.output_path):
            print("由原始輸入excel檔開始首次執行，先初始化一份到輸入檔案")
            write_dataframe(self.df, self.output_path, index=False)

        # 子表（同檔不同 sheet）先嘗試載入
        self._maybe_load_subtable()


    # --- close：雙方都強制 flush 一次 ---
    def close(self):
        # 結束前，如果還有緩存，顯示提示
        if self._dirty_main or self._dirty_sub:
            try:

                tlog("📦 Pipeline 結束，開始將緩存資料全部落盤…")
            except Exception:
                print("📦 Pipeline 結束，開始將緩存資料全部落盤…")
    
        # ⚠️ 只做 sheet-level 的 flush，不要整檔重寫
        # 先 main 後 sub（或反之皆可；兩者都只會 replace 各自的 sheet）
        self._flush_main(force=True)
        self._flush_sub(force=True)
            
    def fetch_input(self, pk):
        try:
            row_idxs = self._find_row_indices(pk)
            if not row_idxs:
                return None
            return self.df.at[row_idxs[0], self.ctx.input_col]  # 取第一筆當代表
        except Exception:
            return None

    def _maybe_load_subtable(self):
        if not self._is_xlsx(self.output_path):
            self.sub_df = None
            return
        if not getattr(self.ctx, "flatten_json_output", False):
            self.sub_df = None
            return
        sub_sheet = getattr(self.ctx, "subtable_name", "subtable")  # ★ 防呆
        try:
            self.sub_df = pd.read_excel(self.output_path, sheet_name=sub_sheet)
        except Exception:
            self.sub_df = None
            
    # 取得同鍵的所有 row index（以字串等值比對，忽略前後空白）
    def _find_row_indices(self, pk):
        """
        回傳符合主鍵值的所有 DataFrame 索引（list[int]）。
        - 若找不到主鍵欄位：警告並回空清單
        - 若找不到任何列：警告並回空清單
        - 若找到多列：僅第一次遇到該鍵時警告，並說明會寫入所有同鍵列
        - 若找到一列：在 debug 模式下印出命中索引
        """

    
        pk_col = getattr(self.ctx, "primary_key", None)
        if not pk_col or pk_col not in self.df.columns:
            tlog_warn(f"⚠️ ExcelSink 找不到主鍵欄位：{pk_col}，無法定位（pk={pk}）。")
            return []
    
        def _norm(v):
            if v is None:
                return ""
            try:
                if isinstance(v, float) and math.isnan(v):
                    return ""
            except Exception:
                pass
            return str(v).strip()
    
        pk_norm = _norm(pk)
        s = self.df[pk_col].apply(_norm)
        idxs = self.df.index[s == pk_norm].tolist()
    
        if not idxs:
            tlog_warn(f"⚠️ 找不到主鍵 {pk_col}='{pk_norm or '(空)'}' 對應的列，略過寫回。")
            return []
    
        if len(idxs) > 1:
            # 只對同一鍵警告一次，避免洗版
            if pk_norm not in self._dup_warned_keys:
                tlog_warn(
                    f"⚠️ 主鍵 {pk_col}='{pk_norm or '(空)'}' 在主表出現 {len(idxs)} 列。"
                    "本次會把同一結果寫入所有這些列；建議後續清理由相同鍵造成的重複，以提升可追溯性。"
                )
                self._dup_warned_keys.add(pk_norm)
        else:
            if getattr(self, "_debug", False):
                tlog(f"🔎 主鍵 {pk_col}='{pk_norm or '(空)'}' 命中單一列 index={idxs[0]}。")
    
        return idxs

    # ---- main table ----
    def write_main(self, pk, result_text: str, update_time: Optional[str] = None):
        try:
            row_idxs = self._find_row_indices(pk)
            if not row_idxs:
                print("在write_main，找不到定位列 → 不寫入")
                return  # 找不到就略過

            value_map = result_text if isinstance(result_text, dict) else {self.ctx.output_col: result_text}
            for col in value_map.keys():
                self._ensure_text_col(self.df, col)
            if getattr(self.ctx, "record_update_time", False):
                self._ensure_dt_col(self.df, "update_time")

            # 寫所有同鍵列（扇出）
            for row_idx in row_idxs:
                for col, val in value_map.items():
                    self.df.at[row_idx, col] = val
                if getattr(self.ctx, "record_update_time", False) and update_time:
                    if isinstance(update_time, str) and update_time.startswith("'"):
                        update_time = update_time.lstrip("'")
                    try:
                        ts = pd.to_datetime(update_time)
                    except Exception:
                        ts = pd.Timestamp.now()
                    self.df.at[row_idx, "update_time"] = ts
    
            self._dirty_main = True
            self._main_since += len(row_idxs)
            
            # 若未達落盤門檻，debug 模式下提示一次目前已緩存幾筆
            if self._debug and (self._main_since < self.flush_main_every):
                self._log(
                    f"🗂️ 主表已緩存 {self._main_since}/{self.flush_main_every} 筆（尚未寫入檔案）。"
                )
                
            if self._main_since >= self.flush_main_every:
                self._flush_main()
        except Exception as ex:
            tlog_warn(f"⚠️ ExcelSink.write_main 失敗（pk={pk}）：{ex}")

    # ---- flatten (subtable) ----
    def ensure_flatten_schema(self, allowed_fields: Optional[List[str]] = None):
        # 確保 ctx.subtable_name / subtable_input_col 依規則就緒
        ensure_excel_subtable_config(self.ctx, self.output_path)
    
        pk_col  = getattr(self.ctx, "primary_key", "row_id")
        sub_in  = getattr(self.ctx, "subtable_input_col", None)  # 可能為 None
        fields  = list(allowed_fields or (self.ctx.allowed_output_fields or []))
    
        sig = (self.ctx.subtable_name, tuple(fields), pk_col, sub_in)
        if self._flatten_ready_sig == sig:
            return
    
        self._maybe_load_subtable()
        if self.sub_df is None:
            cols = [pk_col, "seq"]
            if sub_in:
                cols.append(sub_in)
            cols.extend(fields)
            self.sub_df = pd.DataFrame(columns=cols)
        else:
            for c in [pk_col, "seq"] + fields:
                if c not in self.sub_df.columns:
                    self.sub_df[c] = None
            if sub_in and sub_in not in self.sub_df.columns:
                self.sub_df[sub_in] = None
    
        self._flatten_ready_sig = sig
    
    def write_flatten(self, pk, json_array, save_raw_input: bool, input_col: Optional[str], input_value):
        if not self._is_xlsx(self.output_path):
            tlog_warn("⚠️ 輸出不是 .xlsx，略過子表寫入。")
            return
    
        pk_col = getattr(self.ctx, "primary_key", "row_id")
        if self.sub_df is None:
            self.ensure_flatten_schema(getattr(self.ctx, "allowed_output_fields", None))
    
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
    
        # 落盤（只覆蓋子表 sheet）
        
        try:
            self._dirty_sub = True
            self._sub_since += 1
            if self._debug and (self._sub_since < self.flush_sub_every):
                self._log(
                    f"🧩 子表已緩存 {self._sub_since}/{self.flush_sub_every} 筆（尚未寫入子 sheet）。"
                )
            if self._sub_since >= self.flush_sub_every:
                self._flush_sub()

        except Exception as ex:
            tlog_warn(f"⚠️ 子表寫回失敗：{ex}")
    
    def _to_excel_scalar(self, v):
        # 1) 先處理容器型別：list / dict / numpy.ndarray
        if isinstance(v, (list, dict, np.ndarray)):
            try:
                return json.dumps(v, ensure_ascii=False, default=str)
            except Exception:
                return str(v)
    
        # 2) None 直接回傳 None
        if v is None:
            return None
    
        # 3) pandas Timestamp -> 原生 datetime（openpyxl 需要）
        if isinstance(v, pd.Timestamp):
            try:
                return v.to_pydatetime()
            except Exception:
                pass
    
        # 4) numpy scalar -> Python scalar
        if isinstance(v, np.generic):
            try:
                return v.item()
            except Exception:
                pass
    
        # 5) 其餘純量再判斷是否為缺失值
        try:
            if pd.isna(v):
                return None
        except Exception:
            # 某些型別（少見）isna 會報錯，直接當作純量處理
            pass
    
        return v
    
    def _prepare_df_for_excel(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        回傳一份可安全寫入 Excel 的 DataFrame：
        - 將 <NA>/NaN/NaT → None
        - 將 list/dict → JSON 字串
        - 處理 Timestamp / numpy scalar
        """
        # 先確保文字欄/時間欄 dtype 合理（你原本已有 _ensure_text_col/_ensure_dt_col）
        safe = df.copy()
        # 逐格轉換為 Excel 可接受的純量
        return safe.map(self._to_excel_scalar)

    def _flush_main(self, force: bool=False):
        if not self._dirty_main and not force:
            return
        self._log("💾 正在將主表緩存資料落盤（僅覆蓋主表工作表）…")
        #main_sheet = self.sheet or "Sheet1"
        #self._replace_sheet(main_sheet, self.df)
        #print("self.main_sheet in flush main",self.main_sheet)
        write_dataframe_sheet(self.df, self.output_path, sheet_name=(self.main_sheet or "Sheet1"), index=False)
        self._dirty_main = False
        self._main_since = 0
        self._first_write_done = True
        if self._debug: self._log("✅ 主表落盤完成。")
    
    def _flush_sub(self, force: bool=False):
        if not self._dirty_sub and not force:
            return
        if self.sub_df is None or not self._is_xlsx(self.output_path) or not getattr(self.ctx, "flatten_json_output", False):
            self._dirty_sub = False
            self._sub_since = 0
            return
    
        # 若活頁簿尚未建立，先把主表寫一份，避免只剩子表
        if not os.path.isfile(self.output_path) and self.df is not None:
            self._replace_sheet(self.main_sheet or "Sheet1", self.df)
    
        self._log("💾 正在將子表緩存資料落盤（僅覆蓋子表工作表）…")
        write_dataframe_sheet(self.sub_df, self.output_path, sheet_name=self.ctx.subtable_name, index=False)
        self._dirty_sub = False
        self._sub_since = 0
        
    def flush_all(self):
        """提供給外部在關鍵節點手動落盤（例如 pipeline 迭代段落結束）。"""
        self._flush_sub()
        self._flush_main()
        
    @staticmethod
    def _is_xlsx(p: str) -> bool:
        return str(p).lower().endswith(".xlsx")
