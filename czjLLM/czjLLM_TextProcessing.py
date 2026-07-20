#python -m czjLLM.czjLLM_TextProcessing --config yaml/es_config_satmeta.yaml
from utils_manager.utils_sync import prepare_env
prepare_env(
    root_name="TopicClassification",
    app_name="GenerativeLanguageModel",
    markers=("PackageImport.py",),
    source_subdir="PythonModule",        # = D:\shared\TopicClassification\PythonModule
    target_subdir="lib/PythonModule",
    include_ext={".py"},
    delete_extraneous=True,
    allow_missing=False,
    #prefer_pgm_subdir="app",             # ✅ 讓 PGMSubDir 指向 GenerativeLanguageModel
    prefer_pgm_subdir="caller",
    #config_arg=args.config,              # 會自動嘗試 CWD、App 根、Caller、Project 根
)


##########################################################################
import pprint
#import os
#from utils.selector import OptionSelector

from czjLLM.job_manager.job_config import initialize_config
from czjLLM.job_manager.job_config import load_config_from_file
from czjLLM.cli_tools.cli_utils import parse_args

from czjLLM.handlers.handle_txt_file import handle_txt_mode
#from sql_mode.entry.handle_tabular import handle_tabular_mode
from czjLLM.handlers.handle_data_mode import handle_data_mode
from czjLLM.handlers.handle_sql_to_excel import handle_sql_to_excel_mode
from czjLLM.utilities.llm_call_audit import create_llm_call_audit_run


def load_stage_cfg_preview(get_param, PGMSubDir):
    """
    預讀多階段設定，支援三種 YAML 入口：
    - stage_config_file: 外部多階段設定檔
    - stage_cfg: ES/跨模式建議使用的包裝式設定
    - stages: 舊版直接宣告 stages list/dict
    """
    stage_cfg_file = get_param("stage_config_file")
    if stage_cfg_file:
        return load_config_from_file(PGMSubDir=PGMSubDir, config_path=stage_cfg_file)

    stage_cfg_inline = get_param("stage_cfg")
    if stage_cfg_inline:
        return stage_cfg_inline

    stages_inline = get_param("stages")
    if stages_inline:
        return stages_inline

    return None
    
if __name__ == '__main__':

    #print("PGMSubDir b4",PGMSubDir)
    #if not PGMSubDir.endswith("czjLLM"):
    #    PGMSubDir = os.path.join(PGMSubDir,"czjLLM")
    #print("PGMSubDir af",PGMSubDir)
    #PGMSubDir = PGMSubDir/"czjLLM"
    args = parse_args()
    file_config = {}


    ctx_paths, PGMSubDir, utils_dir, cfg_path = prepare_env(
        root_name="TopicClassification",
        app_name="GenerativeLanguageModel",
        markers=("PackageImport.py",),
        source_subdir="PythonModule",        # = D:\shared\TopicClassification\PythonModule
        target_subdir="lib/PythonModule",
        include_ext={".py"},
        delete_extraneous=True,
        allow_missing=False,
        #prefer_pgm_subdir="app",             # ✅ 讓 PGMSubDir 指向 GenerativeLanguageModel
        prefer_pgm_subdir="caller",
        config_arg=args.config,              # 會自動嘗試 CWD、App 根、Caller、Project 根
    )

    # 有些地方要字串
    PGMSubDir = str(PGMSubDir)
    #from PythonModule import utils
    from utils.selector import OptionSelector
    # 嘗試讀取設定檔
    if args.config:
        file_config = load_config_from_file(PGMSubDir=PGMSubDir, config_path=args.config)
        if file_config:
            #print(f"載入設定檔 :\n{file_config}")
            print("載入設定檔 :")
            pprint.pprint(file_config, indent=4, width=100)

    def get_param(key, default=None):
        return file_config.get(key, default)

    def infer_multistage_task_hint(stage_cfg):
        """
        多階段模式下，若未提供 task，嘗試從第一個 stage 推導一個相容舊流程的 task 名稱，
        避免 initialize_config 進入互動式 set_task。
        """
        stages = None
        if isinstance(stage_cfg, dict):
            stages = stage_cfg.get("stages")
        elif isinstance(stage_cfg, list):
            stages = stage_cfg
        if not stages:
            return None
        first = stages[0]
        if isinstance(first, dict):
            task_key = str(first.get("task_key", "")).strip()
            if task_key:
                return task_key
            task = str(first.get("prompt", first.get("task", ""))).strip()
            if task.startswith("@taskSetting:"):
                return task.split(":", 1)[1].strip()
            return task or None
        if isinstance(first, str):
            return first
        return None

    # 模式選擇
    mode = get_param("mode")
    if not mode:
        mode = OptionSelector(
            options={"txt": "處理 llm_source_dir 下所有 .txt 檔",
                     "table": "讀取 Excel/CSV 並對某欄進行分析",
                     "sql": "逐筆處理遠端 SQL 資料庫並即時更新",
                     "es": "從 Elasticsearch 抓取資料並分析",       # 新增選項
                     "sql_to_excel": "將 SQL 資料表內容匯出為 Excel"},
            question="請選擇處理模式：",
            default="txt"
        ).proc()






    # 先預讀 stage 設定（若有）以便在未提供 task 時推導相容值
    stage_cfg_preview = load_stage_cfg_preview(get_param, PGMSubDir)
    task_hint = infer_multistage_task_hint(stage_cfg_preview)

    merge_slices_cfg = get_param("merge_slices")
    if merge_slices_cfg is None and stage_cfg_preview:
        # 多階段預設不走互動式「切片合併」詢問，避免非 JSON 任務誤導。
        merge_slices_cfg = False

    # 初始化任務參數
    ctx = initialize_config(
        PGMSubDir=PGMSubDir,
        mode=mode,
        channel=get_param("channel"),
        model_spec_name=get_param("model_spec"),
        merge_slices=merge_slices_cfg,
        task_name=get_param("task") or task_hint
    )
    # 多階段設定（可直接放在主 YAML 的 stage_cfg/stages，或獨立 stage_config_file）
    if stage_cfg_preview:
        ctx.stage_cfg = stage_cfg_preview
        if isinstance(stage_cfg_preview, dict):
            ctx.stages = stage_cfg_preview.get("stages", stage_cfg_preview)
        elif isinstance(stage_cfg_preview, list):
            ctx.stages = stage_cfg_preview
    # mock LLM 模式：無模型環境可做 E2E 流程驗證
    ctx.mock_llm_mode = bool(get_param("mock_llm_mode", False))
    ctx.llm_round_debug = get_param("llm_round_debug", None)
    ctx.combine_debug = get_param("combine_debug", False)
    ctx.debug_print_llm_io = bool(get_param("debug_print_llm_io", False))
    ctx.debug_print_max_chars = int(get_param("debug_print_max_chars", 2000) or 2000)
    for _k, _v in create_llm_call_audit_run(PGMSubDir=PGMSubDir).items():
        setattr(ctx, _k, _v)
    #print("ctx in main",ctx)
    # txt 模式：處理所有 .txt
    if mode == "txt":
        handle_txt_mode(ctx, args)

    # 表格模式 / Tabular 模式
    elif mode in ["table","sql","es"]:
        #handle_tabular_mode(ctx=ctx, get_param=get_param, args=args)
        handle_data_mode(ctx=ctx, get_param=get_param, args=args)
        
        
    elif mode == "sql_to_excel":
        handle_sql_to_excel_mode(ctx=ctx, get_param=get_param,table_sector = args.config is None)

    else:
        print(f"不支援的mode:{mode}")
        
        
