import shutil
import os
from tqdm import tqdm
import pandas as pd
from colorama import Fore, Style#, Back
from datetime import datetime
from utils.utilities_path import OSWALK
from utils.utilities_path import smart_detect_path
from utils.selector import OptionSelector

from utilities.excel_utils import backup_table_file

from utilities.excel_utils import read_dataframe,write_dataframe

from prompt_pipeline.prompt_generator import process_file_to_prompt
from prompt_pipeline.pipeline_controller import process_prompt_and_merge
from row_processors.row_runner import process_row_and_get_result
from cli_tools.cli_utils import print_cli_usage_hint

from job_manager.job_config import showTemplate

from utils.utilities import countdown_pause
from utils.utilities_path import MKDIR
from utils.utilities_path import getPathFromFN
from utils.utilities_path import DirReplace


def handle_excel_mode(ctx, get_param, args):
    ctx.input_excel_file = get_param("input_excel_file")

    if not ctx.input_excel_file:
        # 自動搜尋固定資料夾內 Excel 檔
        excel_dir = os.path.join(ctx.llm_source_dir)
        MKDIR(excel_dir)
        excel_files = [f for f in OSWALK(excel_dir)
           if (f.endswith(".xlsx") or f.endswith(".csv")) and "_backup_excel" not in f]
    
    
        if not excel_files:
            print(f"❌ 找不到任何 Excel 檔於：{excel_dir}")
            exit(0)
    
        # 建立選單用的 dict（名稱為檔名，不含路徑）
        excel_file_options = {os.path.basename(f): f for f in excel_files}
        selected_excel = OptionSelector(
            options=excel_file_options,
            question="📄 請選擇欲處理的 Excel 檔案："
        ).proc()
        ctx.input_excel_file = excel_file_options[selected_excel]
    excel_path = smart_detect_path(ctx.PGMSubDir, ctx.input_excel_file)
    if not excel_path:
        print("❌ 找不到指定的 Excel 檔案")
        exit(1)
    
    ctx.input_col = get_param("input_col")
    if not ctx.input_col:
        df = read_dataframe(excel_path, nrows=2)
        print("📌 偵測到以下欄位：")
        columns = list(df.columns)
        col_options = {col: "" for col in columns}
        ctx.input_col = OptionSelector(col_options, question="🔍 請選擇要處理的輸入欄位：").proc()
        if not ctx.input_col or ctx.input_col not in df.columns:
            print(f"❌ Excel 檔案中未找到欄位：{ctx.input_col}")
            exit(1)
    
    ctx.output_col = get_param("output_col")
    if not ctx.output_col:
        ctx.output_col = input(f"💾 請輸入輸出欄位名稱（預設為 {ctx.input_col}_result）：").strip()
        if not ctx.output_col:
            ctx.output_col = ctx.input_col + "_result"
            
    ctx.record_update_time = get_param("record_update_time")
    if ctx.record_update_time is None:
        record_update_time = input("⏱️ 是否在每筆更新時記錄 update_time？(Y/n)：").strip().lower()
        ctx.record_update_time = (record_update_time != "n")
        
    ctx.output_excel_file = get_param("output_excel_file")
    if not ctx.output_excel_file:
        base, ext = os.path.splitext(excel_path)
        default_output_excel_file = base + "_with_result" + ext
        ctx.output_excel_file = input(f"💾 請輸入輸出檔名（預設為 {default_output_excel_file}）：").strip()
        ctx.output_excel_file = ctx.output_excel_file or default_output_excel_file
    '''
        if args.config:
            ctx.output_excel_file = ctx.input_excel_file.replace(".xlsx", "_with_result.xlsx")
        else:
            base, ext = os.path.splitext(excel_path)
            default_output_excel_file = base + "_with_result" + ext
            ctx.output_excel_file = ctx.output_excel_file or default_output_excel_file
    '''
    #print("ctx.output_excel_file af",ctx.output_excel_file)
    # CLI 教學提示（如果來自互動模式）
    if not args.config:
        print_cli_usage_hint(ctx)
    handle_excel_with_cache_txt_like_txt(
        file_path=excel_path,
        ctx=ctx,
        input_col=ctx.input_col,
        output_col=ctx.output_col,
        output_file_path=ctx.output_excel_file
    )
    print("✅ 分析完成！")
    
def handle_excel_with_cache_txt_like_txt(file_path: str, ctx, input_col: str, output_col: str = "result", output_file_path: str = None):
    # 設定輸出檔案
    output_file = output_file_path or file_path.replace(".xlsx", "_with_result.xlsx")
    # 每處理一列即時儲存，支援中斷續跑
    if os.path.isfile(output_file):
        print(f"📄 偵測到已有結果檔，將以此作為續跑來源：{output_file}")
        df = read_dataframe(output_file)
    else:
        df = read_dataframe(file_path)
        if output_col not in df.columns:
            df[output_col] = ""
            df[output_col] = df[output_col].astype(object)
        # 自動備份原始 Excel（加時間戳）
        backup_table_file(file_path)
    if ctx.record_update_time and "update_time" not in df.columns:
        df["update_time"] = ""
        df["update_time"] = df["update_time"].astype(object)
        
    # 建立暫存輸入資料夾
    #excel_input_dir = os.path.join(ctx.llm_source_dir, "cache_from_excel")
    excel_input_dir = os.path.join(ctx.llm_source_dir)
    MKDIR(excel_input_dir)

    
    base_name, _ = os.path.splitext(file_path)
    ctx.error_log_path = base_name + "_error_log.txt"
    first_line = True  # 加入旗標
    for idx, row in tqdm(df.iterrows(), total=len(df), 
                         desc=Fore.LIGHTGREEN_EX + "Excel列處理進度" + Style.RESET_ALL, ncols=80):
        if first_line:
            print()  # 🔧 這一行確保與進度條斷開
            first_line = False
        # 若該列已有處理結果，則跳過
        if pd.notna(row.get(output_col)) and str(row[output_col]).strip():
            print(f"⏩ 第 {idx+1} 列已存在結果，跳過處理")
            continue
        if idx == 0:
            pause_seconds = 10
        else:
            pause_seconds = 0
        result = process_row_and_get_result(str(row[input_col]), idx, ctx, pause_seconds)
        if result is not None:
            df.at[idx, output_col] = result
            if ctx.record_update_time:
                df.at[idx, "update_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            write_dataframe(df, output_file, index=False)
    print(f"✅ 完成分析並儲存至：{output_file}")
    print(f"📄 錯誤紀錄（若有）可見：{ctx.error_log_path}")