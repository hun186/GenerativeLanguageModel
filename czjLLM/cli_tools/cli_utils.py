import os
import argparse
from colorama import Fore, Style#, Back
from pathlib import Path
import yaml


def parse_args():
    parser = argparse.ArgumentParser(description="LLM 任務處理工具 CLI")
    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="指定 YAML 設定檔路徑（若未指定，則進入互動模式）"
    )
    return parser.parse_args()

def print_cli_usage_hint(ctx):
    print("ctx in hint begining",ctx)
    cli_config_example = {
        "mode": getattr(ctx, "mode", None),
        "task": getattr(ctx, "task", None),
        "model_spec": getattr(ctx, "model_spec_name", None),
        "channel": getattr(ctx, "channel", None),
        #"input_excel_file": getattr(ctx, "input_excel_file", None),        
        #"output_excel_file": getattr(ctx, "output_excel_file", None),
        #"input_csv_file": getattr(ctx, "input_csv_file", None),
        #"output_csv_file": getattr(ctx, "output_csv_file", None),
        "current_input_path": getattr(ctx, "current_input_path", None),
        "current_output_path": getattr(ctx, "current_output_path", None),
        "input_col": getattr(ctx, "input_col", None),
        "output_col": getattr(ctx, "output_col", None),
        "record_update_time": getattr(ctx, "record_update_time", None),
        "textClass": getattr(ctx, "textClass", None),
        "exclusiveTextClass": getattr(ctx, "exclusiveTextClass", None),
        "keyConsiderations": getattr(ctx, "keyConsiderations", None),
        "sql_config_file": getattr(ctx, "sql_config_file", None),
        "flatten_json_output": getattr(ctx, "flatten_json_output", None),
        "allowed_output_fields": getattr(ctx, "allowed_output_fields", None),
        "save_raw_input_when_flatten": getattr(ctx, "save_raw_input_when_flatten", None),
        #"save_raw_output_when_flatten": getattr(ctx, "save_raw_output_when_flatten", None),
        # 其他可能有用的路徑
        "sqlite_path": getattr(ctx, "sqlite_path", None),
        "llm_source_dir": getattr(ctx, "llm_source_dir", None),
        "llm_source_backup_dir": getattr(ctx, "llm_source_backup_dir", None),
        # 資料表資訊（非路徑，但一起列在 YAML 便於下次直接用）
        "table_name": getattr(ctx, "sql_table", None),
        "target_table": getattr(ctx, "target_table", None),
        "primary_key": getattr(ctx, "primary_key", None),
    }
    cli_config_example = {
        k:v for k,v in cli_config_example.items() if v}
    # 需要正規化的路徑鍵
    PATH_KEYS = [
        "input_excel_file",
        "output_excel_file",
        "input_csv_file",
        "output_csv_file",
        "sql_config_file",
        "sqlite_path",
        "llm_source_dir",
        "llm_source_backup_dir",
    ]

    for p in PATH_KEYS:
        if (val := cli_config_example.get(p)):
            cli_config_example[p] = str(val).replace("\\", "/")

    yaml_lines = ["# ✅ 建議設定檔 YAML 範例："]
    for k, v in cli_config_example.items():
        if v is not None:
            yaml_lines.append(f"{k}: {v}")
    content = "\n".join(yaml_lines)
    print(content)

    print(f"\n🧾 你可以將上述內容儲存成設定檔，下次使用如下指令：\n"
          f"{Fore.LIGHTGREEN_EX}python czjLLM_TextProcessing.py --config your_config.yaml{Fore.RESET}")

    # ➕ 加入是否儲存的提示
    save = input("💡 是否要將此設定儲存成 YAML 檔？(y/N)：").strip().lower()
    if save == "y":
        filename = input("📄 請輸入儲存檔案名稱（預設為 your_config.yaml）：").strip()
        if not filename:
            filename = "your_config.yaml"

        # 補上副檔名（若缺少）
        if not filename.endswith((".yaml", ".yml")):
            filename += ".yaml"
        save_filename = os.path.join(ctx.PGMSubDir,"yaml", filename)
        # 確保資料夾存在
        os.makedirs(os.path.dirname(save_filename), exist_ok=True)

        payload = {k: v for k, v in cli_config_example.items() if v is not None}
        with open(save_filename, "w", encoding="utf-8") as f:
            yaml.dump(payload, f, allow_unicode=True)
        
        print(f"\n✅ 設定檔已儲存至：{save_filename}")
        print(f"{Fore.CYAN}📌 下次使用時請執行：")
        print(f"{Fore.LIGHTGREEN_EX}python czjLLM_TextProcessing.py --config {save_filename}{Style.RESET_ALL}")
