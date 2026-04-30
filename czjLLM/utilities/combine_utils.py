from __future__ import annotations
from pathlib import Path

import os
import json
from opencc import OpenCC
import shutil
import re
import hashlib
from typing import List, Dict, Any, Tuple, Optional
try:
    from utils.utilities_path import OSWALK
    from utils.utilities_path import MKDIR
    from utils.utilities_path import getPathFromFN
    from utils.utilities_path import DirReplace
    from utils.utilities import flattenList
    from utils.MP_utils import MPlogger
except Exception as ex:
    print(ex)

from json_repair import repair_json
from czjLLM.utilities.json_text_utils import strip_markdown_code_fence

import re

def split_json_arrays(raw: str) -> list[str]:
    """
    將 raw 字串中的多個 JSON 陣列（支援跨行、巢狀物件）正確分割成獨立區塊。

    避免使用正則處理嵌套結構，改用括號平衡方式切分。
    """
    arrays = []
    buf = ''
    level = 0
    inside_array = False

    for c in raw:
        if c == '[':
            level += 1
            inside_array = True
        if inside_array:
            buf += c
        if c == ']':
            level -= 1
            if level == 0:
                arrays.append(buf.strip())
                buf = ''
                inside_array = False

    return arrays

def split_json_arrays_safe(raw: str) -> list[str]:
    """
    將 raw 字串中的多個 JSON 陣列（支援跨行、巢狀物件）正確分割成獨立區塊。

    避免使用正則處理嵌套結構，改用括號平衡方式切分。
    """
    arrays = []
    buf = []
    level = 0
    in_str = False
    esc = False
    started = False

    for ch in raw:
        if not started:
            if ch == '[':
                started = True
                level = 1
                buf = ['[']
            continue

        buf.append(ch)

        if esc:
            esc = False
            continue

        if in_str:
            if ch == '\\':
                esc = True
            elif ch == '"':
                in_str = False
            continue

        # not in string
        if ch == '"':
            in_str = True
        elif ch == '[':
            level += 1
        elif ch == ']':
            level -= 1
            if level == 0:
                arrays.append(''.join(buf).strip())
                buf = []
                started = False

    return arrays
    
def robust_merge_json_lists(raw: str) -> str:
    """
    清理並合併多個 JSON 陣列字串，並在解析失敗時自動嘗試修復格式錯誤的段落。

    處理流程：
    1. 移除程式碼區塊的 Markdown 格式標記（```json ... ```）。
    2. 使用正規表達式分段抓取所有中括號包裹的 JSON 陣列（如 [ {...}, {...} ]）。
    3. 依序嘗試解析每一段 JSON 陣列：
       - 若解析成功且為 list，則加入 all_items。
       - 若解析失敗，則使用 repair_json(p) 嘗試修復並再次解析。
    4. 將所有成功解析的陣列元素合併成一個大的 list，並輸出為格式化 JSON 字串。

    參數：
        raw (str): 包含一段或多段 JSON 陣列的原始字串，可能包含格式錯誤。

    回傳：
        str: 合併並格式化後的合法 JSON 陣列字串。
    """

    # 移除 ```json 與 ``` 標記（常見於 LLM 回傳或 Markdown 格式）
    raw = strip_markdown_code_fence(raw)

    # 使用正則擷取所有類似 [ ... ] 的 JSON 陣列（允許跨多行）
    #parts = re.findall(r'\[.*?\]', raw, re.DOTALL) #re.findall(r'\[.*?\]', raw, re.DOTALL) 使用了非貪婪匹配 .*?，但遇到巢狀結構（例如 [ 裡還有 [）時，正則無法處理嵌套配對，因此會提前結束。
    parts = split_json_arrays(raw)
    all_items = []

    for p in parts:
        try:
            # 嘗試將每段轉換為 Python list
            arr = json.loads(p)
            if isinstance(arr, list):
                all_items.extend(arr)
        except json.JSONDecodeError as e:
            print(f"⚠️ JSON decode error: {e}\n❗ 嘗試使用 repair_json 修復...")

            try:
                # 嘗試修復格式錯誤並重新解析
                repaired = repair_json(p)
                arr = json.loads(repaired)

                if isinstance(arr, list):
                    all_items.extend(arr)
                    print("✅ 修復成功，已納入合併")

            except Exception as e2:
                # 若修復後還是無法解析，則略過該段並顯示錯誤
                print(f"❌ 修復失敗：{e2}\n🔸原始段落略過：\n{p[:200]}...")

    # 將所有成功合併的項目輸出成 JSON 字串，中文不轉碼並格式化縮排
    return json.dumps(all_items, ensure_ascii=False, indent=2)


def clean_and_merge_json_lists(raw: str) -> str:
    """
    清理並合併多個 JSON 陣列字串，將其合併為一個合法的 JSON 陣列表示。

    處理步驟如下：
    1. 移除每個 JSON 陣列中尾端多餘的逗號（例如 "[{a:1},]" → "[{a:1}]"）。
    2. 如果整段字串僅由多個空陣列組成（例如 "[]\n[]\n[]"），則回傳單一空陣列 "[]"
    3. 移除所有獨立的空陣列（"[]"）以避免合併後出現非法結構（如 "[,]")。
    4. 將多個中括號包住的 JSON 陣列（如 "[{a:1}]\n[{b:2}]"）合併為一個陣列（"[{a:1},{b:2}]"）。

    參數：
        raw (str): 原始的 JSON 字串，可能由多個獨立 JSON 陣列段構成。

    回傳：
        str: 處理後合併成單一 JSON 陣列字串。
    """
    # 移除每個陣列尾部多餘的逗號
    raw = re.sub(r',\s*\]', ']', raw)
    
    # 如果整段都只是空陣列（例如 []\n[]），那就只回傳一個空陣列
    all_empty = all(part.strip() == "[]" for part in re.split(r'\s*\n\s*', raw) if part.strip())
    if all_empty:
        return "[]"

    # 移除獨立存在（可跨行）的空陣列段（不破壞 key:[] 結構）
    raw = re.sub(r'(^|\n)\s*\[\s*\n*\s*\]\s*(\n|$)', r'\1\2', raw)

    # 合併連續的 JSON 陣列為單一陣列（例如 "[{a:1}]\n[{b:2}]" → "[{a:1},{b:2}]"）
    raw = re.sub(r'\]\s*\[', ',', raw)

    return raw



def combine_json_return(json_content,NoNestedList=True,dictListForced=True):
    # 假設你的 JSON 檔案內容如下
    #json_content = '''
    #[
    #{"a":1,"b":2},
    #{"a":3,"b":4}
    #]
    #[
    #{"a":4,"b":5},
    #{"a":1,"b":4}
    #]
    #'''
    # 將 JSON 內容分割成多個清單
    #json_lists = re.findall(r'\[.*?\]', json_content, re.DOTALL)
    #print("json_lists",json_lists)
    # 合併多個清單成一個清單
    #merged_list = []
    #for json_list in json_lists:
        #merged_list.extend(json.loads(json_list))
    
    # 輸出合併後的清單
    #print(merged_list)
    #print("Enter combine_json_return. json_content is",json_content)
    #json_content_res = json_content.replace(
    #    "```json\n","").replace("```\n","").replace("\n]\n[",",")
    # 移除 markdown 包裝（```json）
    json_content_res = strip_markdown_code_fence(json_content)
    #print("json_content_res b4",json_content_res)
    # 🧹 Step 1: 移除每段陣列中 `,]` 結尾，改為 `]`
    # 🔁 Step 2: 將多段 array 合併：例如 `][`、`] [`, `]\n[` 等轉為 `,`
    #json_content_res = clean_and_merge_json_lists(json_content_res)
    json_content_res = robust_merge_json_lists(json_content_res)
    #print("json_content_res af",json_content_res)
        
    error_mes = ""
    try:
        json.loads(json_content_res)
    except Exception as ex:
        error_mes = ex
        try:
            print("In combine_json_return, json_content_res is",json_content_res)
            print(f"when loading json string, the following error occurs:\n{ex}\n")
            print("Try to repair it with repair_json")
            #good_json_string = repair_json(json_content_res)
            #json_content_res = json.dumps(
                #json.loads(good_json_string),ensure_ascii=False,indent=4)
            json.loads(repair_json(json_content_res))
            decoded_object = repair_json(
                json_content_res, return_objects=True)
            
            # 資料處理格式，可能會產生不合格式：[[term1,term2],[term3,term4]]
            if NoNestedList == True:
                # 若資料不為空，且第一個元素是清單，執行攤平
                if decoded_object and isinstance(decoded_object[0], list):
                    decoded_object = flattenList(decoded_object)
            # 資料處理格式，可能會產生不合格式：[[字典1,字典2],[字典3,字典4]]
            if dictListForced == True:
                tmp_dict_list = []
                for subterm in decoded_object:
                    if isinstance(subterm,dict):
                        tmp_dict_list.append(subterm)
                    elif isinstance(subterm,list):
                        tmp_dict_list.extend([x for x in subterm])
                    else:
                        print(f"When making dict_list for {decoded_object}, error occurs.")
                        raise Exception
                decoded_object = tmp_dict_list
            json_content_res = json.dumps(
                decoded_object,ensure_ascii=False,indent=4)

            print("Successfully repair it with repair_json")
            error_mes = str(error_mes)+"\nBut it is repaired with repair_json."
        except Exception as ex2:
            print("In combine_json_return, the following error occurs:\n", ex2)
            pass
    return json_content_res,error_mes

def _p(s):
    """接受 str / Path / 任何 PathLike。空字串或 None 則回傳 None。"""
    if s is None:
        return None
    try:
        s_str = os.fspath(s)  # 可處理 PathLike
    except TypeError:
        s_str = str(s)
    s_str = str(s_str)
    return Path(s_str) if s_str.strip() else None

def _safe_task_suffix(task: str, max_len: int = 96) -> str:
    """
    產生可安全放入檔名的任務後綴：
    - 移除 Windows/一般檔名非法字元
    - 將空白與換行壓成底線
    - 過長時截斷並加 hash，避免路徑過長
    """
    cleaned = re.sub(r'[\\/:*?"<>|]+', "_", str(task or "")).strip()
    cleaned = re.sub(r"\s+", "_", cleaned).strip("._") or "result"
    if len(cleaned) <= max_len:
        return cleaned
    digest = hashlib.sha1(cleaned.encode("utf-8")).hexdigest()[:10]
    head_len = max(16, max_len - 11)  # 保留 "_" + 10 碼 hash
    return f"{cleaned[:head_len]}_{digest}"


def _resolve_task_suffix_for_filename(ctx) -> str:
    """
    依執行模式決定輸出檔名的任務後綴長度：
    - SQL 模式預設較短（避免 CT_name 過長造成路徑冗長）
    - 其餘模式維持較寬鬆長度
    - 可用 ctx.task_filename_max_len 覆蓋
    """
    mode = str(getattr(ctx, "mode", "") or "").strip().lower()
    default_max_len = 32 if mode == "sql" else 96
    try:
        max_len = int(getattr(ctx, "task_filename_max_len", default_max_len) or default_max_len)
    except Exception:
        max_len = default_max_len
    max_len = max(16, min(max_len, 128))
    return _safe_task_suffix(getattr(ctx, "task", "result"), max_len=max_len)




def _should_parse_as_json_task(task_text: str) -> bool:
    """
    判斷任務是否應視為 JSON 任務。

    避免把「禁止輸出 JSON」這類文字誤判為 JSON 任務。
    """
    normalized = str(task_text or "").strip().lower()
    if not normalized:
        return False

    negative_hints = (
        "禁止輸出 json",
        "不要輸出 json",
        "do not output json",
        "without json",
    )
    if any(h in normalized for h in negative_hints):
        return False

    positive_hints = (
        "to json format",
        "json 回覆",
        "json回复",
        "請回傳：[",
        "请回传：[",
        "請回傳json",
        "請輸出json",
        "output json",
        "return json",
    )
    return any(h in normalized for h in positive_hints)

def combine_api_finished_item(item: str, ctx) -> str:
    print(f"{item} is finished calling API, start to combine returned result.")
    item_p = Path(item)
    suc_dir = item_p / "Success"

    task_text = str(getattr(ctx, "task", ""))
    json_mode = _should_parse_as_json_task(task_text)
    text_chunks: list[str] = []
    json_rows: list[dict] = []

    for fp in sorted(OSWALK(str(suc_dir))):
        p = Path(fp)
        text = p.read_text(encoding="utf-8")
        if not text or not text.strip():
            # 有些 provider/重試流程會留下空白成功檔，避免誤判成 JSON 壞檔
            continue
        if OpenCC("s2twp").convert(text.lstrip()).startswith("無主題相關內容"):
            continue

        if json_mode:
            try:
                obj = json.loads(text)
                if isinstance(obj, dict):
                    json_rows.append(obj)
                    continue
                if isinstance(obj, list):
                    json_rows.extend([x for x in obj if isinstance(x, dict)])
                    continue
                raise ValueError("不支援的 JSON 結構")
            except Exception as e:
                has_multistage = False
                try:
                    stages = getattr(ctx, "stages", None)
                    has_multistage = isinstance(stages, list) and len(stages) > 1
                except Exception:
                    has_multistage = False
                if has_multistage:
                    print(f"⚠️ JSON 解析失敗（multistage 將改由 stage 輸出寫回，可忽略）：{p}，錯誤：{e}")
                else:
                    print(f"❌ 解析 JSON 失敗（將以純文字串接回退）：{p}，錯誤：{e}")
        text_chunks.append(text if text.endswith("\n") else text + "\n")

    if json_mode and json_rows:
        if should_merge_slices(ctx):
            merged_obj, _report = merge_dict_slices_audited(
                json_rows,
                conflict_policy=str(getattr(ctx, "merge_conflict_policy", "prefer_left")),
                dedup_lists=bool(getattr(ctx, "merge_dedup_lists", True)),
                audit=bool(getattr(ctx, "merge_log_changes", True)),
                logger=print if bool(getattr(ctx, "merge_log_changes", True)) else None,
                max_log=int(getattr(ctx, "merge_max_log", 10)),
            )
            combined_text = json.dumps(merged_obj, ensure_ascii=False, indent=2)
        else:
            combined_text = json.dumps(json_rows, ensure_ascii=False, indent=2)
    else:
        combined_text = "".join(text_chunks)
        if json_mode and not combined_text.strip():
            # JSON 任務在全部分片都空白時，輸出合法空陣列，避免後續寫回/flatten 解析失敗
            combined_text = "[]"

    # === 安全地決定輸出目錄（不要出現前導斜線） ===
    # 優先 llm_source_finished_dir，其次 llm_source_dir；都沒有就用 item 的上層
    #'''
    
    #print('getattr(ctx,"temp_txt_finished_dir")',getattr(ctx,"temp_txt_finished_dir",""))
    #print("ctx.llm_source_finished_dir",ctx.llm_source_finished_dir)
    #print("ctx.llm_source_dir",ctx.llm_source_dir)
    #print("types:",
    #      type(getattr(ctx, "llm_source_finished_dir", None)),
    #      type(getattr(ctx, "llm_source_dir", None)),
    #      type(getattr(ctx, "prompt_dir", None)))
    '''
    # 1) 先決定 Finished 根
    base_out = (
        _p(getattr(ctx, "temp_txt_finished_dir", None))
        or _p(getattr(ctx, "llm_source_finished_dir", None))
        or _p(getattr(ctx, "llm_source_dir", None))
        or item_p.parent
    )
    
    # 2) 用 prompt 根去計算 item 的「相對子路徑」
    prompt_root = _p(getattr(ctx, "prompt_dir", None)).resolve()
    rel = item_p.resolve().relative_to(prompt_root)  # e.g. "2/test_merge"
    mirror_parent = rel.parent                       # e.g. "2"
    
    # 3) 最終輸出資料夾：Finished根 / 相對子目錄(parent)
    dest_dir = base_out / mirror_parent              # → .../LLMSourcePool_Finished/test long/2
    dest_dir.mkdir(parents=True, exist_ok=True)
    
    # 4) 檔名仍用 item 名稱 + 任務名
    main_name = item_p.name
    task_name = str(getattr(ctx, "task", "result")).replace(os.sep, "_")
    out_path = dest_dir / f"{main_name}_{task_name}.txt"
    '''
    # 1) 先決定 Finished 根
    base_out = (
        _p(getattr(ctx, "temp_txt_finished_dir", None))
        or _p(getattr(ctx, "llm_source_finished_dir", None))
        or _p(getattr(ctx, "llm_source_dir", None))
        or Path(item).parent
    )
    # 確保是 Path
    base_out = Path(base_out)
    
    # 2) 用 prompt 根去計算 item 的「相對子路徑」
    prompt_root = Path(getattr(ctx, "prompt_dir", "")).resolve()
    try:
        rel = Path(item).resolve().relative_to(prompt_root)  # e.g. "cache/excel_input_45_90233bc9"
        mirror_parent = rel.parent                           # e.g. "cache"
    except Exception:
        mirror_parent = Path("")
    
    # 3) 如果 base_out 的最後一段與 mirror_parent 的第一段相同，就把 mirror_parent 的第一段去掉，避免重複
    mp_parts = list(mirror_parent.parts)
    if mp_parts and base_out.name.lower() == mp_parts[0].lower():
        mp_parts = mp_parts[1:]
    
    dest_dir = base_out / Path(*mp_parts)
    dest_dir.mkdir(parents=True, exist_ok=True)
    
    # 4) 檔名
    main_name = Path(item).name
    task_name = _resolve_task_suffix_for_filename(ctx)
    out_path = dest_dir / f"{main_name}_{task_name}.txt"
    # JSON 合併修補（如有指定 to json format，且目前仍為字串拼接型態）
    if "to json format" in str(getattr(ctx, "task", "")).lower() and not (json_mode and json_rows):
        fixed, err = combine_json_return(combined_text, dictListForced=True)
        combined_text = fixed
        if err:
            logs_dir = Path(getattr(ctx, "PGMSubDir", "")) / "logs"
            logs_dir.mkdir(parents=True, exist_ok=True)
            MPlogger(str(logs_dir), logFile="FailToCombineJsonResult.log").logW(
                MES=f"When combining {out_path} json format, the following error occurs:\n{err}\n"
            )

    out_path.write_text(combined_text, encoding="utf-8")
    #print("item_p",item_p)
    #print("base_out",base_out)
    #print("out_path",out_path)
    if not getattr(ctx, "debug", False) and item_p.is_dir():
        shutil.rmtree(item_p)

    print("CombBackFN", out_path)
    return str(out_path)

def combine_api_finished_item_OLD(item, ctx):
    print(f"{item} is finished calling API, start to combine returned result.")
    SucSubdir = os.path.join(item,"Success")
    combined_text = ""
    for file in sorted(OSWALK(SucSubdir)):
        with open(file,'rt',encoding='utf-8') as fp:
            fpCTX = fp.read()
            #if OpenCC("s2twp").convert(fpCTX.rstrip()) in [
                    #"無主題相關內容","無主題相關內容。"]:
            if OpenCC("s2twp").convert(fpCTX.lstrip()).startswith("無主題相關內容"):
                continue
            
            try:
                json_obj = json.loads(fpCTX)
                # 如果是一筆 dict，就包成 list
                if isinstance(json_obj, dict):
                    json_obj = [json_obj]
                elif isinstance(json_obj, list):
                    pass  # 結構正確，維持原樣
                else:
                    raise ValueError("不支援的 JSON 結構")
            
                # 加進去合併清單
                combined_text += json.dumps(json_obj, ensure_ascii=False, indent=2) + "\n"
            except Exception as e:
                if "to json format" in ctx.task.lower():
                    print(f"❌ 解析 JSON 失敗（跳過格式補正）：{file}，錯誤：{e}")
                # 如果不是 JSON 結構就維持原來的加法
                if fpCTX and not fpCTX.endswith("\n"):
                    fpCTX += "\n"
                combined_text += fpCTX

    CombBackFN = DirReplace(
        FilePath=item + f"_{ctx.task}.txt",
        SrcDir=ctx.prompt_dir,
        DesDir=ctx.llm_source_finished_dir
    )
    print("CombBackFN",CombBackFN)
    if "to json format" in ctx.task.lower():
        #dictListForced = True if "RAG Chunk" in TASK else False
        dictListForced = True
        combined_text,error_mes = combine_json_return(combined_text,dictListForced=dictListForced)
        if error_mes != "":
            MES = f"When combining {CombBackFN} json format, the following error occurs:\n{error_mes}\n"
            MPlogger(logSubDir=os.path.join(ctx.PGMSubDir,"logs"),logFile="FailToCombineJsonResult.log").logW(MES=MES)
    MKDIR(getPathFromFN(CombBackFN))
    with open(CombBackFN,'wt',encoding='utf-8') as fp:
        fp.write(combined_text)
    if ctx.debug == False:
        if os.path.isdir(item):
            shutil.rmtree(item)
    return CombBackFN
    
def run_merge_for(ctx, job_dir: str, registry=None) -> bool:
    finished_root = (
        getattr(ctx, "temp_txt_finished_dir", None)
        or getattr(ctx, "llm_source_finished_dir", None)
        or getattr(ctx, "llm_source_dir", None)
    )
    class _CtxOverlay:
        def __init__(self, base, **kw):
            self.__dict__.update(getattr(base, "__dict__", {}))
            self.__dict__.update(kw)

    overlay = _CtxOverlay(ctx, debug=True, temp_txt_finished_dir=finished_root)
    out_path = combine_api_finished_item(job_dir, overlay)

    ok = bool(out_path and os.path.isfile(out_path))
    if ok and registry:
        # 依你的 registry 介面調整方法名稱：
        for fn in ("update_item_meta", "set_item_meta", "update_item"):
            if hasattr(registry, fn):
                try:
                    getattr(registry, fn)(job_dir, {"CombBackFN": str(out_path)})
                except Exception:
                    pass
                break
    return ok
'''
def run_merge_for(ctx, job_dir: str) -> bool:
    finished_root = (
        getattr(ctx, "temp_txt_finished_dir", None)
        or getattr(ctx, "llm_source_finished_dir", None)
        or getattr(ctx, "llm_source_dir", None)
    )
    class _CtxOverlay:
        def __init__(self, base, **kw):
            self.__dict__.update(getattr(base, "__dict__", {}))
            self.__dict__.update(kw)

    overlay = _CtxOverlay(ctx, debug=True, temp_txt_finished_dir=finished_root)
    out_path = combine_api_finished_item(job_dir, overlay)
    return bool(out_path and os.path.isfile(out_path))
'''
def run_merge_for_OLD(ctx, job_dir: str) -> bool:
    """
    專做「該 job_dir 的切片合併」；不負責寫回 ES/SQL（那是 row_merger_watchdog_generic 的職責）。
    觸發條件：TODO 與 RUNNING 皆空，且 Success 有內容時才進行合併。
    關鍵：以 debug=True 的 overlay ctx 呼叫 combine_api_finished_item，避免先把 item 目錄刪掉，
          讓 row_merger 能在下一輪掃描到合併產物並完成 sink.write_main() 與 registry.remove()。
    回傳：True=有執行且產出合併檔；False=不需要或失敗。
    """
    try:
        todo_cnt    = len(OSWALK(os.path.join(job_dir, "TODO")))
        running_cnt = len(OSWALK(os.path.join(job_dir, "RUNNING")))
        success_cnt = len(OSWALK(os.path.join(job_dir, "Success")))
    except Exception:
        todo_cnt = running_cnt = success_cnt = 0

    # 沒切片可合併，或仍在處理中 → 不動
    if success_cnt <= 0:
        return False
    if (todo_cnt > 0) or (running_cnt > 0):
        return False

    # 建立 overlay ctx：指定輸出根目錄、最重要的是 debug=True（避免 combine 後刪 item 夾）
    class _CtxOverlay:
        def __init__(self, base, **kw):
            self.__dict__.update(getattr(base, "__dict__", {}))
            self.__dict__.update(kw)

    target_finished_root = (
        getattr(ctx, "temp_txt_finished_dir", None)
        or getattr(ctx, "llm_source_finished_dir", None)
        or getattr(ctx, "llm_source_dir", None)
    )

    overlay = _CtxOverlay(
        ctx,
        debug=True,  # <<< 關鍵：讓 combine 不刪 job_dir，保證 row_merger 能接手寫回 sink
        temp_txt_finished_dir=target_finished_root,
    )

    try:
        out_path = combine_api_finished_item(job_dir, overlay)
        if out_path and os.path.isfile(out_path):
            try:
                tlog(f"🧩 run_merge_for：合併完成 → {out_path}")
            except Exception:
                print(f"run_merge_for merged: {out_path}")
            # （可選）若日後想加速 row_merger 取檔，可在 registry meta 記 CombBackFN。
            # 目前 watchdog 的 _resolve_combined_path() 已能藉 get_combined_result_path() 找到成品，故非必要。
            return True
        else:
            try:
                tlog_warn(f"⚠️ run_merge_for：combine 未產出檔案（{job_dir}）")
            except Exception:
                print(f"run_merge_for WARN: no output for {job_dir}")
            return False
    except Exception as e:
        try:
            tlog_warn(f"⚠️ run_merge_for 失敗（{job_dir}）：{e}")
        except Exception:
            print(f"run_merge_for ERROR for {job_dir}: {e}")
        return False
        
def should_merge_slices(ctx) -> bool:
    """
    只有在 ctx.merge_slices=True（或等價設定）時才啟用切片合併。
    """
    # 你也可以支援多種開關名稱，方便相容既有設定：
    return bool(
        getattr(ctx, "merge_slices", False) or
        getattr(ctx, "enable_slice_merge", False) or
        (getattr(ctx, "merge_strategy", "").lower() in {"dict_deep", "slice_merge", "on"})
    )
    
def merge_dict_slices(dict_list: List[Dict[str, Any]]) -> Dict[str, Any]:
    """將多個切片（list[dict]）深度合併成單一 dict。
    規則：
      - list + list：串接（如需去重，自行改成 dict.fromkeys）
      - dict + dict：遞迴合併
      - 標量衝突：保留左側（第一個非空），若要改為以右側覆蓋可自行調整
    """
    def _merge(a, b):
        if a is None: return b
        if b is None: return a
        if isinstance(a, list) and isinstance(b, list):
            return a + b
        if isinstance(a, dict) and isinstance(b, dict):
            out = dict(a)
            for k, v in b.items():
                out[k] = _merge(out.get(k), v)
            return out
        # 標量衝突：保留 a（若 a 為空字串/None，改採 b）
        return a if a not in ("", None) else b

    agg: Dict[str, Any] = {}
    for d in dict_list:
        if isinstance(d, dict):
            agg = _merge(agg, d)
    return agg


def merge_dict_slices_audited(
    dict_list: List[dict],
    *,
    conflict_policy: str = "prefer_left",        # "prefer_left" | "prefer_right" | "longer_str" | "non_empty"
    dedup_lists: bool = False,                   # True 時，list 會去重（以 JSON 字串為 key）
    audit: bool = True,                          # 回傳 report
    #logger: Optional[callable] = None,           # 例如 tlog_warn
    logger: Optional[callable] = print,
    max_log: int = 10,                           # 最多列出幾筆細節
) -> Tuple[dict, Dict[str, Any]]:
    """
    與 merge_dict_slices 規則相同，但產出審計報告：
      - 記錄 list 串接、list 去重、型別不一致、標量衝突 等事件
      - 依 conflict_policy 決定標量衝突時的取捨
    report：
      {
        "changed": bool,
        "counts": {"list_concat": int, "list_dedup_removed": int, "scalar_conflict": int, "type_mismatch": int},
        "samples": [ { "action": str, "path": "a.b.c", "chosen": "left|right|other", "left_short": str, "right_short": str } ... ],
      }
    """

    counts = {"list_concat": 0, "list_dedup_removed": 0, "scalar_conflict": 0, "type_mismatch": 0}
    samples: List[Dict[str, Any]] = []
    def _shorten(x, n=160):
        try:
            s = x if isinstance(x, str) else json.dumps(x, ensure_ascii=False)
        except Exception:
            s = str(x)
        return s if len(s) <= n else s[:n] + f"...(+{len(s)-n} chars)"

    def _choose_scalar(a, b):
        if conflict_policy == "prefer_right": return b
        if conflict_policy == "longer_str":
            sa = len(str(a)) if a is not None else -1
            sb = len(str(b)) if b is not None else -1
            return a if sa >= sb else b
        if conflict_policy == "non_empty":
            if a not in ("", None): return a
            return b
        # default: prefer_left
        return a if a not in ("", None) else b

    def _log_sample(action, path, chosen, left, right):
        if len(samples) < max_log:
            samples.append({
                "action": action,
                "path": path,
                "chosen": chosen,
                "left_short": _shorten(left),
                "right_short": _shorten(right),
            })

    def _merge(a, b, path: List[str]):
        if a is None: return b
        if b is None: return a

        # list + list
        if isinstance(a, list) and isinstance(b, list):
            counts["list_concat"] += 1
            merged = a + b
            if dedup_lists:
                seen = set()
                deduped = []
                removed = 0
                for it in merged:
                    try:
                        key = json.dumps(it, ensure_ascii=False, sort_keys=True)
                    except Exception:
                        key = str(it)
                    if key in seen:
                        removed += 1
                        continue
                    seen.add(key)
                    deduped.append(it)
                if removed:
                    counts["list_dedup_removed"] += removed
                    _log_sample("list_dedup", ".".join(path), "other", f"{len(merged)} items", f"-{removed} dup")
                return deduped
            return merged

        # dict + dict
        if isinstance(a, dict) and isinstance(b, dict):
            out = dict(a)
            for k, v in b.items():
                out[k] = _merge(out.get(k), v, path + [k])
            return out

        # 型別不一致
        if type(a) is not type(b):
            counts["type_mismatch"] += 1
            _log_sample("type_mismatch", ".".join(path), "left", a, b)
            return a  # 與原規則一致（保留左）；如需覆蓋改為 return b

        # 標量衝突
        if a != b:
            counts["scalar_conflict"] += 1
            chosen = _choose_scalar(a, b)
            _log_sample("scalar_conflict", ".".join(path),
                        "left" if chosen is a else ("right" if chosen is b else "other"),
                        a, b)
            return chosen

        return a  # 相等
    
    # --- 自動解析字串 ---
    if isinstance(dict_list, str):
        try:
            dict_list = json.loads(dict_list)
        except Exception:
            if logger:
                logger("[merge] 輸入是字串且非合法 JSON，回傳空合併。")
            return ({}, {"changed": False, "counts": {}, "samples": []})
    # --- 型別檢查 ---
    if not (isinstance(dict_list, list) and all(isinstance(x, dict) for x in dict_list)):
        if logger:
            logger("[merge] 輸入不是 list[dict]，回傳空合併。")
        return ({}, {"changed": False, "counts": {}, "samples": []})
    
    #print("input dict_list in merge_dict_slices_audited",dict_list)
    
    agg: Dict[str, Any] = {}
    for d in dict_list:
        if isinstance(d, dict):
            agg = _merge(agg, d, [])

    changed = any(v > 0 for v in counts.values())
    report = {"changed": changed, "counts": counts, "samples": samples}

    # 可選：總結性 log
    if logger and changed:
        logger(f"[merge] 變更摘要 counts={counts}（samples 顯示至多 {max_log} 筆）")
        for s in samples:
            logger(f"[merge] {s['action']} @{s['path']} → {s['chosen']} | L={s['left_short']} | R={s['right_short']}")
    #print("returned agg in merge_dict_slices_audited",agg)
    #print("report",report)
    return (agg, report) if audit else (agg, {})

if __name__ == '__main__':
    testDoc = """
[
  {
    "article_title": "Report of the WHO-China Joint Mission on Coronavirus Disease 2019 (COVID-19)",
    "Event_Summary": "A nine‑day joint mission by WHO and China (16‑24 Feb 2020) examined the COVID‑19 outbreak, evaluated national response measures and produced recommendations for China and the international community.",
    "Event": {
      "subject": "World Health Organization and the Government of the People’s Republic of China",
      "object": "China’s national and local public‑health authorities",
      "aspect": "public health emergency response",
      "medium": "scientific data, field observations, government reports",
      "action": "assess, report, and recommend measures to enhance containment and preparedness",
      "time_raw": "16-24 February 2020",
      "time_iso": "2020-02-16",
      "time_precision": "day",
      "location": "China (Beijing, Hubei, Guangdong, Sichuan)",
      "consequence": "Rapid production of evidence‑based findings that informed national and international planning for COVID‑19 containment, and a set of actionable recommendations for China and other affected countries",
      "relation": "WHO, Chinese central and provincial health commissions, national and local government agencies",
      "source": "WHO-China Joint Mission Report, 28 Feb 2020"
    },
    "Person": [
      {
        "name": "Dr Bruce Aylward",
        "role": "WHO representative, Joint Mission lead",
        "action": "oversaw mission activities and analysis",
        "quote": null,
        "stance": null,
        "relation": "together with Dr Wannian Liang"
      },
      {
        "name": "Dr Wannian Liang",
        "role": "Chinese Ministry of Health, Joint Mission lead",
        "action": "co‑led mission activities and facilitated access to data",
        "quote": null,
        "stance": null,
        "relation": "together with Dr Bruce Aylward"
      }
    ],
    "Involved_Parties": [
      {
        "party_name": "World Health Organization",
        "party_role": "International coordinating agency"
      },
      {
        "party_name": "People’s Republic of China",
        "party_role": "Host country and national response coordinator"
      },
      {
        "party_name": "National Health Commission of China",
        "party_role": "National health authority"
      },
      {
        "party_name": "China Centers for Disease Control and Prevention",
        "party_role": "National CDC"
      },
      {
        "party_name": "Provincial Health Commissions (Beijing, Hubei, Guangdong, Sichuan)",
        "party_role": "Provincial health authorities"
      }
    ],
    "Impact": [
      {
        "impact_description": "Provided comprehensive assessment of COVID‑19 transmission dynamics, clinical characteristics, and containment measures, informing policy decisions and enhancing global understanding of the pandemic."
      }
    ],
    "Event_Timeline": [
      {
        "date_raw": "16-24 February 2020",
        "date_iso": "2020-02-16",
        "date_precision": "day",
        "description": "WHO-China Joint Mission conducted field visits, data collection, and stakeholder consultations."
      },
      {
        "date_raw": "30 December 2019",
        "date_iso": "2019-12-30",
        "date_precision": "day",
        "description": "First samples of the novel coronavirus were collected in Wuhan Jinyintan Hospital."
      },
      {
        "date_raw": "20 February 2020",
        "date_iso": "2020-02-20",
        "date_precision": "day",
        "description": "Cumulative COVID‑19 cases in China reached 75,465 as reported by the National Reporting System."
      }
    ],
    "evidence_snippets": [
      {
        "text": "The Joint Mission was implemented over a 9‑day period from 16-24 February 2020.",
        "char_start": null,
        "char_end": null,
        "paragraph_id": null,
        "sentence_index": null,
        "source_id": null,
        "confidence": 100
      },
      {
        "text": "On 30 December 2019, three bronchoalveolar lavage samples were collected from a patient with pneumonia of unknown etiology – a surveillance definition established following the SARS outbreak of 2002‑2003 – in Wuhan Jinyintan Hospital.",
        "char_start": null,
        "char_end": null,
        "paragraph_id": null,
        "sentence_index": null,
        "source_id": null,
        "confidence": 100
      },
      {
        "text": "As of 20 February 2020, a cumulative total of 75,465 COVID-19 cases were reported in China.",
        "char_start": null,
        "char_end": null,
        "paragraph_id": null,
        "sentence_index": null,
        "source_id": null,
        "confidence": 100
      }
    ]
  },
  {
    "article_title": "COVID‑19 Epidemiological Observations and Transmission Dynamics",
    "Event_Summary": "The Chinese authorities implemented a cordon sanitaire around Wuhan on 23 January 2020, intensifying laboratory confirmation, contact tracing and testing that dramatically reduced community spread, particularly outside of Hubei.",
    "Event": {
      "subject": "Chinese public‑health authorities",
      "object": "population of Wuhan and surrounding provinces",
      "aspect": "public health, epidemiology",
      "medium": "lockdown, testing",
      "action": "implemented cordon sanitaire; conducted mass testing and contact tracing",
      "time_raw": "23 January 2020",
      "time_iso": "2020-01-23",
      "time_precision": "day",
      "location": "Wuhan, Hubei province, China",
      "consequence": "prevented further exportation of infected individuals to the rest of the country and reduced community transmission outside Wuhan",
      "relation": "Wuhan local government, national CDC, provincial governments",
      "source": "Joint Mission report"
    },
    "Person": [],
    "Involved_Parties": [
      {
        "party_name": "Wuhan Municipal Government",
        "party_role": "Implementer of lockdown"
      },
      {
        "party_name": "China CDC",
        "party_role": "National epidemiology provider"
      }
    ],
    "Impact": [
      {
        "impact_description": "Significant decline in new case counts outside Wuhan after lockdown"
      }
    ],
    "Event_Timeline": [
      {
        "date_raw": "23 January 2020",
        "date_iso": "2020-01-23",
        "date_precision": "day",
        "description": "Cordon sanitaire imposed around Wuhan"
      }
    ],
    "evidence_snippets": [
      {
        "text": "The cordon sanitaire around Wuhan and neighboring municipalities imposed since 23 January 2020 has effectively prevented further exportation of infected individuals to the rest of the country.",
        "char_start": null,
        "char_end": null,
        "paragraph_id": "transmission_in_wuhan",
        "sentence_index": 2,
        "source_id": "Joint Mission report",
        "confidence": 95
      }
    ]
  },
  {
    "article_title": "COVID‑19 Epidemiological Observations and Transmission Dynamics",
    "Event_Summary": "In Shenzhen, contact tracing of 2,842 close contacts by 17 February 2020 identified 88 COVID‑19 cases (3.1 % infection rate) after 79 % of contacts completed medical observation.",
    "Event": {
      "subject": "Shenzhen City Health Bureau",
      "object": "close contacts of confirmed cases",
      "aspect": "contact tracing, public health",
      "medium": "epidemiological investigation",
      "action": "traced, observed, tested contacts",
      "time_raw": "17 February 2020",
      "time_iso": "2020-02-17",
      "time_precision": "day",
      "location": "Shenzhen, Guangdong, China",
      "consequence": "identification of new cases and containment of spread within city",
      "relation": "Shenzhen municipal government, Guangdong provincial authorities",
      "source": "Joint Mission report"
    },
    "Person": [],
    "Involved_Parties": [
      {
        "party_name": "Shenzhen Municipal Health Bureau",
        "party_role": "Contact tracing lead"
      }
    ],
    "Impact": [
      {
        "impact_description": "3.1 % secondary infection rate among traced contacts"
      }
    ],
    "Event_Timeline": [
      {
        "date_raw": "17 February 2020",
        "date_iso": "2020-02-17",
        "date_precision": "day",
        "description": "Shenzhen contact tracing outcome"
      }
    ],
    "evidence_snippets": [
      {
        "text": "As of 17 February, in Shenzhen City, among 2842 identified close contacts, 2842 (100%) were traced and 2240 (79%) have completed medical observation. Among the close contacts, 88 (3.1%) were found to be infected with COVID-19.",
        "char_start": null,
        "char_end": null,
        "paragraph_id": "contact_tracing_shenzhen",
        "sentence_index": 1,
        "source_id": "Joint Mission report",
        "confidence": 97
      }
    ]
  },
  {
    "article_title": "COVID‑19 Epidemiological Observations and Transmission Dynamics",
    "Event_Summary": "In Sichuan, tracing 25,493 close contacts by 17 February 2020 yielded 0.9 % infection among contacts, with 99 % traced and 91 % medically observed.",
    "Event": {
      "subject": "Sichuan Provincial Health Bureau",
      "object": "close contacts of confirmed cases",
      "aspect": "contact tracing, public health",
      "medium": "epidemiological investigation",
      "action": "traced, observed, tested contacts",
      "time_raw": "17 February 2020",
      "time_iso": "2020-02-17",
      "time_precision": "day",
      "location": "Sichuan Province, China",
      "consequence": "identification of new infections, support for containment",
      "relation": "Sichuan provincial authorities, national CDC",
      "source": "Joint Mission report"
    },
    "Person": [],
    "Involved_Parties": [
      {
        "party_name": "Sichuan Provincial Health Bureau",
        "party_role": "Contact tracing lead"
      }
    ],
    "Impact": [
      {
        "impact_description": "0.9 % secondary infection rate among traced contacts"
      }
    ],
    "Event_Timeline": [
      {
        "date_raw": "17 February 2020",
        "date_iso": "2020-02-17",
        "date_precision": "day",
        "description": "Sichuan contact tracing outcome"
      }
    ],
    "evidence_snippets": [
      {
        "text": "As of 17 February, in Sichuan Province, among 25493 identified close contacts, 25347 (99%) were traced and 23178 (91%) have completed medical observation. Among the close contacts, 0.9% were found to be infected with COVID‑19.",
        "char_start": null,
        "char_end": null,
        "paragraph_id": "contact_tracing_sichuan",
        "sentence_index": 1,
        "source_id": "Joint Mission report",
        "confidence": 96
      }
    ]
  },
  {
    "article_title": "COVID‑19 Epidemiological Observations and Transmission Dynamics",
    "Event_Summary": "In Guangdong, tracing 9,939 close contacts by 20 February 2020 produced 4.8 % infection rate, with 100 % traced and 78 % medically observed, illustrating efficient local surveillance.",
    "Event": {
      "subject": "Guangdong Provincial Health Bureau",
      "object": "close contacts of confirmed cases",
      "aspect": "contact tracing, public health",
      "medium": "epidemiological investigation",
      "action": "traced, observed, tested contacts",
      "time_raw": "20 February 2020",
      "time_iso": "2020-02-20",
      "time_precision": "day",
      "location": "Guangdong Province, China",
      "consequence": "identified secondary cases and reinforced containment measures",
      "relation": "Guangdong provincial authorities, national CDC",
      "source": "Joint Mission report"
    },
    "Person": [],
    "Involved_Parties": [
      {
        "party_name": "Guangdong Provincial Health Bureau",
        "party_role": "Contact tracing lead"
      }
    ],
    "Impact": [
      {
        "impact_description": "4.8 % secondary infection rate among traced contacts"
      }
    ],
    "Event_Timeline": [
      {
        "date_raw": "20 February 2020",
        "date_iso": "2020-02-20",
        "date_precision": "day",
        "description": "Guangdong contact tracing outcome"
      }
    ],
    "evidence_snippets": [
      {
        "text": "As of 20 February, in Guangdong Province, among 9939 identified close contacts, 9939 (100%) were traced and 7765 (78%) have completed medical observation. Among the close contacts, 479 (4.8%) were found to be infected with COVID‑19.",
        "char_start": null,
        "char_end": null,
        "paragraph_id": "contact_tracing_guangdong",
        "sentence_index": 1,
        "source_id": "Joint Mission report",
        "confidence": 98
      }
    ]
  },
  {
    "article_title": "COVID‑19 Outbreak and Early Response in China – Joint Mission Report",
    "Event_Summary": "The outbreak of COVID‑19 in Wuhan triggered a rapid national emergency response, leading to disease surveillance, control measures, and a shift in health policy that reduced transmission and casualties.",
    "Event": {
      "subject": "COVID‑19 outbreak in China (WHO‑classified Class B infectious disease)",
      "object": "Chinese population, especially Wuhan residents",
      "aspect": "public health / epidemiology",
      "medium": "virus",
      "action": "transmission, detection, containment, and policy implementation",
      "time_raw": "20 February 2020",
      "time_iso": "2020-02-20",
      "time_precision": "day",
      "location": "Wuhan, Hubei Province, China and nationwide",
      "consequence": "2114 deaths (CFR 3.8%), 18264 recoveries (24%) and a comprehensive shift of health policy to emergency control",
      "relation": "CPC Central Committee, State Council, Xi Jinping, Li Keqiang, Sun Chunlan, WHO",
      "source": "Joint Mission report on COVID‑19 response in China"
    },
    "Person": [
      {
        "name": "Xi Jinping",
        "role": "General Secretary of the Communist Party of China",
        "action": "directed the national emergency response and prioritized COVID‑19 control",
        "quote": null,
        "stance": "proactive leadership",
        "relation": "CPC Central Committee"
      },
      {
        "name": "Li Keqiang",
        "role": "Premier of the State Council",
        "action": "headed the Central Leading Group for Epidemic Response and inspected Wuhan",
        "quote": null,
        "stance": "leading operational response",
        "relation": "State Council"
      },
      {
        "name": "Sun Chunlan",
        "role": "Vice Premier",
        "action": "coordinated frontline prevention and control in Wuhan",
        "quote": null,
        "stance": "frontline management",
        "relation": "State Council"
      }
    ],
    "Involved_Parties": [
      {
        "party_name": "CPC Central Committee",
        "party_role": "Decision‑making body"
      },
      {
        "party_name": "State Council",
        "party_role": "Administrative authority"
      },
      {
        "party_name": "World Health Organization",
        "party_role": "International partner"
      },
      {
        "party_name": "Wuhan Municipal Government",
        "party_role": "Local implementation"
      }
    ],
    "Impact": [
      {
        "impact_description": "Rapid containment measures reduced further spread of the virus in China."
      },
      {
        "impact_description": "Nationwide policy shift to treat COVID‑19 as a Class B infectious disease introduced legal quarantine controls."
      },
      {
        "impact_description": "Economic activities resumed gradually following the 8 Feb notice, balancing public health and economic recovery."
      }
    ],
    "Event_Timeline": [
      {
        "date_raw": "3 January 2020",
        "date_iso": "2020-01-03",
        "date_precision": "day",
        "description": "Information on the epidemic was notified to WHO."
      },
      {
        "date_raw": "10 January 2020",
        "date_iso": "2020-01-10",
        "date_precision": "day",
        "description": "Whole genome sequences of the COVID‑19 virus were shared with WHO."
      },
      {
        "date_raw": "20 January 2020",
        "date_iso": "2020-01-20",
        "date_precision": "day",
        "description": "COVID‑19 was included in the statutory report of Class B infectious diseases."
      },
      {
        "date_raw": "23 January 2020",
        "date_iso": "2020-01-23",
        "date_precision": "day",
        "description": "Wuhan implemented strict traffic restrictions."
      },
      {
        "date_raw": "8 February 2020",
        "date_iso": "2020-02-08",
        "date_precision": "day",
        "description": "State Council issued the Notice on Orderly Resuming Production and Resuming Production in Enterprises."
      },
      {
        "date_raw": "20 February 2020",
        "date_iso": "2020-02-20",
        "date_precision": "day",
        "description": "Updated statistics: 2114 deaths, 18264 recoveries."
      }
    ],
    "evidence_snippets": [
      {
        "text": "Upon the detection of a cluster of pneumonia cases of unknown etiology in Wuhan, the CPC Central Committee and the State Council launched the national emergency response.",
        "char_start": null,
        "char_end": null,
        "paragraph_id": "paragraph_7",
        "sentence_index": 1,
        "source_id": "",
        "confidence": 95
      },
      {
        "text": "On 20 January 2020, COVID-19 was included in the statutory report of Class B infectious diseases and border health quarantine infectious diseases.",
        "char_start": null,
        "char_end": null,
        "paragraph_id": "paragraph_14",
        "sentence_index": 2,
        "source_id": "",
        "confidence": 90
      },
      {
        "text": "As of 20 February 2020, 2114 of the 55,924 laboratory confirmed cases have died (crude fatality ratio [CFR2] 3.8%).",
        "char_start": null,
        "char_end": null,
        "paragraph_id": "paragraph_23",
        "sentence_index": 3,
        "source_id": "",
        "confidence": 92
      }
    ]
  },
  {
    "article_title": "China Response & Next Steps",
    "Event_Summary": "China’s COVID‑19 containment strategy involved nationwide temperature monitoring, mask mandate, hand washing, and later a risk‑based approach with technology integration, resulting in a substantial decline in cases and accelerating economic reopening.",
    "Event": {
      "subject": "Chinese government and public health authorities",
      "object": "COVID‑19 patients and the general public",
      "aspect": "epidemic control, public health, socio‑economic",
      "medium": "public health infrastructure, technology platforms (AI, 5G, online medical services)",
      "action": "containment, testing, treatment, contact tracing, capacity scaling and resource mobilization",
      "time_raw": "first day of the advance team’s work to final day of the mission",
      "time_iso": null,
      "time_precision": "unknown",
      "location": "China (Hubei Province, Wuhan and national)",
      "consequence": "Reduction from 2478 to 409 new daily cases over two weeks, prevention of hundreds of thousands of infections, restoration of social and economic functions",
      "relation": "National coordination and international knowledge sharing via WHO Joint Mission",
      "source": "WHO Joint Mission Report on China"
    },
    "Person": [],
    "Involved_Parties": [
      {
        "party_name": "Chinese Ministry of Health",
        "party_role": "Implementing agency"
      },
      {
        "party_name": "World Health Organization",
        "party_role": "Joint Mission team"
      },
      {
        "party_name": "Governors and Mayors of provinces",
        "party_role": "Local leadership"
      },
      {
        "party_name": "Chinese public",
        "party_role": "Community participants"
      }
    ],
    "Impact": [
      {
        "impact_description": "Significant decrease in new COVID‑19 cases at national level"
      },
      {
        "impact_description": "Accelerated reopening of schools and businesses"
      },
      {
        "impact_description": "Enhanced public health capacity for isolation and care"
      },
      {
        "impact_description": "Improved technology adoption for health monitoring and rural response"
      }
    ],
    "Event_Timeline": [
      {
        "date_raw": "first day of the advance team’s work",
        "date_iso": null,
        "date_precision": "unknown",
        "description": "2478 newly confirmed cases reported nationwide"
      },
      {
        "date_raw": "final day of the mission (two weeks later)",
        "date_iso": null,
        "date_precision": "unknown",
        "description": "409 newly confirmed cases reported nationwide"
      }
    ],
    "evidence_snippets": [
      {
        "text": "On the first day of the advance team’s work there were 2478 newly confirmed cases of COVID-19 reported in China. Two weeks later, on the final day of this Mission, China reported 409 newly confirmed cases.",
        "char_start": null,
        "char_end": null,
        "paragraph_id": null,
        "sentence_index": null,
        "source_id": null,
        "confidence": 95
      },
      {
        "text": "The China Response & Next Steps 1. In the face of a previously unknown virus, China has rolled out perhaps the most ambitious, agile and aggressive disease containment effort in history.",
        "char_start": null,
        "char_end": null,
        "paragraph_id": null,
        "sentence_index": null,
        "source_id": null,
        "confidence": 90
      },
      {
        "text": "The innovative and aggressive use of cutting edge technologies, from shifting to online medical platforms for routine care and schooling, to the use of 5G platforms to support rural response operations.",
        "char_start": null,
        "char_end": null,
        "paragraph_id": null,
        "sentence_index": null,
        "source_id": null,
        "confidence": 90
      }
    ]
  },
  {
    "article_title": "WHO–China Joint Mission on COVID‑19 Final Report",
    "Event_Summary": "China’s comprehensive public‑health response, guided by WHO, successfully reversed the escalating COVID‑19 epidemic in Hubei and provincial clusters through rapid detection, isolation, contact tracing and community‑level containment measures, thereby saving lives and limiting socio‑economic impact.",
    "Event": {
      "subject": "China’s public health system (including CDC and local authorities)",
      "object": "COVID‑19 outbreak cases and affected communities",
      "aspect": "Public health / epidemic response",
      "medium": "Public health measures (surveillance, isolation, quarantine)",
      "action": "Containment and reversal of case escalation",
      "time_raw": "just 7 weeks since the virus was discovered",
      "time_iso": null,
      "time_precision": "unknown",
      "location": "China (Hubei province and other importation provinces)",
      "consequence": "Reversal of escalating cases, reduction of community transmission, minimized socio‑economic disruption",
      "relation": "WHO, China CDC, national and local health authorities, international partners",
      "source": "WHO–China Joint Mission Report"
    },
    "Person": [
      {
        "name": "Bruce Aylward",
        "role": "Team Lead, WHO–China Joint Mission on COVID‑19; Senior Advisor to the Director‑General, WHO",
        "action": "Led the joint mission’s assessment and recommendations",
        "quote": null,
        "stance": "supportive of rigorous containment measures",
        "relation": "WHO"
      }
    ],
    "Involved_Parties": [
      {
        "party_name": "World Health Organization (WHO)",
        "party_role": "International coordinating body"
      },
      {
        "party_name": "China Centers for Disease Control and Prevention (CDC)",
        "party_role": "National public health authority"
      },
      {
        "party_name": "Robert Koch Institute",
        "party_role": "International partner"
      },
      {
        "party_name": "National Health Commission of China",
        "party_role": "Government health regulator"
      },
      {
        "party_name": "International Community",
        "party_role": "Stakeholders in global response"
      }
    ],
    "Impact": [
      {
        "impact_description": "Effective containment slowed epidemic spread and allowed controlled easing of restrictions"
      },
      {
        "impact_description": "High‑quality public health measures provided a model for other countries"
      },
      {
        "impact_description": "Reduced mortality and preserved healthcare capacity during the pandemic"
      }
    ],
    "Event_Timeline": [
      {
        "date_raw": "7 weeks since virus discovery",
        "date_iso": null,
        "date_precision": "unknown",
        "description": "Rapid scientific work in China enabled development of containment measures and surveillance capacity."
      }
    ],
    "evidence_snippets": [
      {
        "text": "public health response in China reversed the escalating cases in both Hubei, where there has been widespread community transmission, and in the importation provinces, where family clusters appear to have driven the outbreak.",
        "char_start": null,
        "char_end": null,
        "paragraph_id": "p1",
        "sentence_index": null,
        "source_id": "report",
        "confidence": 95
      },
      {
        "text": "Such a strategy is essential for ensuring a sustainable approach while minimizing the socio‑economic impact.",
        "char_start": null,
        "char_end": null,
        "paragraph_id": "p2",
        "sentence_index": null,
        "source_id": "report",
        "confidence": 90
      },
      {
        "text": "20 Given the damage that can be caused by uncontrolled, community‑level transmission of this virus, such an approach is warranted to save lives and to gain the weeks and months needed for the testing of therapeutics and vaccine development.",
        "char_start": null,
        "char_end": null,
        "paragraph_id": "p3",
        "sentence_index": null,
        "source_id": "report",
        "confidence": 92
      }
    ]
  },
  {
    "article_title": "WHO-China Joint Mission on COVID-19 – Mission Report (Feb 2020)",
    "Event_Summary": "A WHO-led mission visited China from 10 to 24 February 2020 to investigate the COVID‑19 outbreak, assess response measures, and produce a joint report.",
    "Event": {
      "subject": "World Health Organization and National Health Commission of China",
      "object": "Chinese public‑health institutions and authorities",
      "aspect": "Epidemiological investigation and public health response",
      "medium": "official visits, workshops, site visits, and data collection",
      "action": "survey, analyze, report",
      "time_raw": "10-24 February 2020",
      "time_iso": "2020-02-10",
      "time_precision": "day",
      "location": "China – Beijing, Shenzhen, Guangzhou, Chengdu, Wuhan",
      "consequence": "Provided evidence that informed national control strategies and the WHO‑China joint report, influencing subsequent public‑health measures.",
      "relation": "WHO, National Health Commission, China CDC, various provincial health authorities",
      "source": "World Health Organization"
    },
    "Person": [
      {
        "name": "Natalia PSHENICHNAYA",
        "role": "Head of International Department and Consultant, Center of Infectious Diseases, National Medical Research Center of Phthisiopulmonology and Infectious Diseases, Moscow, Russia",
        "action": "participated in the joint mission",
        "quote": null,
        "stance": null,
        "relation": null
      },
      {
        "name": "Aleksandr SEMENOV",
        "role": "Deputy Director, Saint Petersburg Pasteur Institute, Saint Petersburg, Russia",
        "action": "participated in the joint mission",
        "quote": null,
        "stance": null,
        "relation": null
      },
      {
        "name": "Hitoshi TAKAHASHI",
        "role": "Senior Research Scientist, Influenza Virus Research Center, National Institute of Infectious Diseases, Tokyo, Japan",
        "action": "participated in the joint mission",
        "quote": null,
        "stance": null,
        "relation": null
      },
      {
        "name": "Maria VAN KERKHOVE",
        "role": "Head of Unit, Emerging Diseases & Zoonoses, Global Infectious Hazard Preparedness, World Health Organization, Geneva, Switzerland",
        "action": "participated in the joint mission",
        "quote": null,
        "stance": null,
        "relation": null
      },
      {
        "name": "Bin WANG",
        "role": "Deputy Team Leader, Deputy Director General, Disease Prevention and Control Bureau, National Health Commission",
        "action": "participated in the joint mission",
        "quote": null,
        "stance": null,
        "relation": null
      },
      {
        "name": "Guangfa WANG",
        "role": "Director, Department of Respiratory and Critical Care Medicine, Peking University First Hospital",
        "action": "participated in the joint mission",
        "quote": null,
        "stance": null,
        "relation": null
      },
      {
        "name": "Fan WU",
        "role": "Vice Dean, Shanghai Medical College, Fudan University",
        "action": "participated in the joint mission",
        "quote": null,
        "stance": null,
        "relation": null
      },
      {
        "name": "Zhongze WU",
        "role": "Director, Compliance and Enforcement Division, Department of Wildlife Conservation, National Forestry and Grassland Administration",
        "action": "participated in the joint mission",
        "quote": null,
        "stance": null,
        "relation": null
      },
      {
        "name": "Zunyou WU",
        "role": "Chief Epidemiologist, Chinese Center for Disease Control and Prevention",
        "action": "participated in the joint mission",
        "quote": null,
        "stance": null,
        "relation": null
      },
      {
        "name": "Jun XING",
        "role": "Head of Unit, Country Capacity for International Health Regulations, Health Security Preparedness, World Health Organization, Geneva, Switzerland",
        "action": "participated in the joint mission",
        "quote": null,
        "stance": null,
        "relation": null
      },
      {
        "name": "Kwok-Yung YUEN",
        "role": "Chair Professor and Co-Director of State Key Laboratory of Emerging Infectious Diseases, Department of Microbiology, The University of Hong Kong",
        "action": "participated in the joint mission",
        "quote": null,
        "stance": null,
        "relation": null
      },
      {
        "name": "Weigong ZHOU",
        "role": "Medical Officer, Influenza Division, National Center for Immunization and Respiratory Diseases, US Centers for Disease Control and Prevention, Atlanta, United States",
        "action": "participated in the joint mission",
        "quote": null,
        "stance": null,
        "relation": null
      },
      {
        "name": "Yong ZHANG",
        "role": "Assistant Director and Researcher, National Institute for Viral Disease Control and prevention, Chinese Center for Disease Control and Prevention",
        "action": "participated in the joint mission",
        "quote": null,
        "stance": null,
        "relation": null
      },
      {
        "name": "Lei ZHOU",
        "role": "Chief and Researcher, Branch for Emerging Infectious Disease, Public Health Emergency Center, Chinese Center for Disease Control and Prevention",
        "action": "participated in the joint mission",
        "quote": null,
        "stance": null,
        "relation": null
      }
    ],
    "Involved_Parties": [
      {
        "party_name": "World Health Organization",
        "party_role": "International coordinating body"
      },
      {
        "party_name": "National Health Commission of China",
        "party_role": "National health authority"
      },
      {
        "party_name": "China CDC",
        "party_role": "National disease control agency"
      },
      {
        "party_name": "National Center for Infectious Diseases",
        "party_role": "National research institute"
      },
      {
        "party_name": "International research institutions",
        "party_role": "Scientific partners"
      }
    ],
    "Impact": [
      {
        "impact_description": "The mission’s findings informed China’s national response strategies, including lockdown measures, testing, contact tracing and public communication. The joint report was used by WHO and national authorities to evaluate and adjust outbreak control measures."
      }
    ],
    "Event_Timeline": [
      {
        "date_raw": "10-15 February 2020 (Advance Team)",
        "date_iso": "2020-02-10",
        "date_precision": "day",
        "description": "Advance team in Beijing met WHO country team and national counterparts."
      },
      {
        "date_raw": "16 February 2020",
        "date_iso": "2020-02-16",
        "date_precision": "day",
        "description": "Full international team briefing at WHO country office in Beijing."
      },
      {
        "date_raw": "17 February 2020",
        "date_iso": "2020-02-17",
        "date_precision": "day",
        "description": "Site visits to Ditan Hospital, Anhuali community and a workshop with China CDC in Beijing."
      },
      {
        "date_raw": "18 February 2020",
        "date_iso": "2020-02-18",
        "date_precision": "day",
        "description": "Guangdong team visited Shenzhen customs, No.3 People’s Hospital, Shenzhen CDC and Tencent; Sichuan team travelled to Chengdu and visited airport, governor, hospital and community."
      },
      {
        "date_raw": "19 February 2020",
        "date_iso": "2020-02-19",
        "date_precision": "day",
        "description": "Guangdong team visited Qiaoxiang community, travelled to Guangzhou for a visit to Futian high‑speed train station and wet market; Sichuan team held symposium and visited West China Hospital."
      },
      {
        "date_raw": "20 February 2020",
        "date_iso": "2020-02-20",
        "date_precision": "day",
        "description": "Guangdong team conducted workshops with provincial government; Sichuan team visited women’s and children’s hospital, logistics center and railway station."
      },
      {
        "date_raw": "21-24 February 2020",
        "date_iso": "2020-02-21",
        "date_precision": "day",
        "description": "Joint mission analyzed findings and held meetings to finalize the report."
      },
      {
        "date_raw": "22 February 2020",
        "date_iso": "2020-02-22",
        "date_precision": "day",
        "description": "Wuhan team travelled from Guangzhou to Wuhan to conduct hospital visits."
      },
      {
        "date_raw": "23 February 2020",
        "date_iso": "2020-02-23",
        "date_precision": "day",
        "description": "Wuhan team visited Tongji Hospital, mobile cabin hospital, and held a workshop with Hubei provincial authorities."
      },
      {
        "date_raw": "24 February 2020",
        "date_iso": "2020-02-24",
        "date_precision": "day",
        "description": "Mission returned to Beijing to finalize the report and hold a WHO‑joint press conference."
      }
    ],
    "evidence_snippets": [
      {
        "text": "10-15 February 2020 (Advance Team) Beijing Advance Team and WHO Country team meetings with national counterparts and institutions",
        "char_start": null,
        "char_end": null,
        "paragraph_id": null,
        "sentence_index": null,
        "source_id": null,
        "confidence": 100
      },
      {
        "text": "16 February 2020 Beijing Meeting with the full international team for briefing at the WHO Country office",
        "char_start": null,
        "char_end": null,
        "paragraph_id": null,
        "sentence_index": null,
        "source_id": null,
        "confidence": 100
      },
      {
        "text": "18 February 2020 (Guangdong Team) Shenzhen, Guangdong Shenzhen customs at the airport",
        "char_start": null,
        "char_end": null,
        "paragraph_id": null,
        "sentence_index": null,
        "source_id": null,
        "confidence": 100
      }
    ]
  },
  {
    "article_title": "COVID-19 outbreak response in China",
    "Event_Summary": "China CDC isolated the novel coronavirus on 7 January 2020, promptly shared its genome and released diagnostic protocols, enabling rapid global awareness and testing.",
    "Event": {
      "subject": "China CDC",
      "object": "Global health community",
      "aspect": "Disease outbreak response",
      "medium": "genome sequence",
      "action": "shared",
      "time_raw": "7 January 2020",
      "time_iso": "2020-01-07",
      "time_precision": "day",
      "location": "Wuhan, China",
      "consequence": "Accelerated development of RT‑PCR diagnostics and global alert",
      "relation": "WHO",
      "source": "China CDC announcement"
    },
    "Person": [],
    "Involved_Parties": [
      {
        "party_name": "China CDC",
        "party_role": "National Center for Disease Control"
      },
      {
        "party_name": "World Health Organization",
        "party_role": "Global health authority"
      }
    ],
    "Impact": [
      {
        "impact_description": "Rapid identification and sharing of the genome facilitated worldwide diagnostic kit development and early containment measures."
      }
    ],
    "Event_Timeline": [
      {
        "date_raw": "7 January 2020",
        "date_iso": "2020-01-07",
        "date_precision": "day",
        "description": "Virus isolated from clinical sample; first RT‑PCR assays distributed."
      }
    ],
    "evidence_snippets": [
      {
        "text": "The virus found to cause COVID-19 was initially isolated from a clinical sample on 7 January. It is notable that within weeks following the identification of the virus, a series of reliable and sensitive diagnostic tools were developed and deployed.",
        "char_start": null,
        "char_end": null,
        "paragraph_id": null,
        "sentence_index": null,
        "source_id": null,
        "confidence": 100
      }
    ]
  },
  {
    "article_title": "COVID-19 outbreak response in China",
    "Event_Summary": "The Wuhan Huanan seafood wholesale market was shut down by Chinese authorities to curb the spread of COVID‑19.",
    "Event": {
      "subject": "Chinese government",
      "object": "Huanan seafood wholesale market",
      "aspect": "Public health containment",
      "medium": "market closure",
      "action": "closed",
      "time_raw": "7 January 2020",
      "time_iso": "2020-01-07",
      "time_precision": "day",
      "location": "Huanan seafood wholesale market, Wuhan",
      "consequence": "Reduced person-to-person transmission at the source",
      "relation": null,
      "source": "Chinese authority announcement"
    },
    "Person": [],
    "Involved_Parties": [
      {
        "party_name": "Chinese government",
        "party_role": "National authorities"
      },
      {
        "party_name": "Huanan seafood wholesale market",
        "party_role": "Market facility"
      }
    ],
    "Impact": [
      {
        "impact_description": "Limiting market operations helped contain early community spread."
      }
    ],
    "Event_Timeline": [
      {
        "date_raw": "7 January 2020",
        "date_iso": "2020-01-07",
        "date_precision": "day",
        "description": "Market shutdown announced."
      }
    ],
    "evidence_snippets": [
      {
        "text": "Huanan seafood wholesale market closed",
        "char_start": null,
        "char_end": null,
        "paragraph_id": null,
        "sentence_index": null,
        "source_id": null,
        "confidence": 100
      }
    ]
  },
  {
    "article_title": "COVID-19 outbreak response in China",
    "Event_Summary": "China CDC shared full genome sequences of the novel coronavirus with WHO and the international community on 12 January 2020.",
    "Event": {
      "subject": "China CDC",
      "object": "WHO and international community",
      "aspect": "Scientific collaboration",
      "medium": "genome sequence",
      "action": "shared",
      "time_raw": "12 January 2020",
      "time_iso": "2020-01-12",
      "time_precision": "day",
      "location": "N/A",
      "consequence": "Enabled global researchers to design diagnostics and vaccines",
      "relation": "WHO",
      "source": "China CDC press release"
    },
    "Person": [],
    "Involved_Parties": [
      {
        "party_name": "China CDC",
        "party_role": "National Center for Disease Control"
      },
      {
        "party_name": "WHO",
        "party_role": "Global health authority"
      }
    ],
    "Impact": [
      {
        "impact_description": "Immediate sharing of genetic data accelerated worldwide diagnostic kit approvals."
      }
    ],
    "Event_Timeline": [
      {
        "date_raw": "12 January 2020",
        "date_iso": "2020-01-12",
        "date_precision": "day",
        "description": "Full genome sequence shared."
      }
    ],
    "evidence_snippets": [
      {
        "text": "Information regarding viral sequences and PCR primers and probes was shared with WHO and the international community by China CDC on 12 January 2020.",
        "char_start": null,
        "char_end": null,
        "paragraph_id": null,
        "sentence_index": null,
        "source_id": null,
        "confidence": 100
      }
    ]
  },
  {
    "article_title": "COVID-19 outbreak response in China",
    "Event_Summary": "On 16 January 2020, China CDC distributed the first RT‑PCR assay kits for COVID‑19 to Hubei, followed by nationwide distribution on 19 January.",
    "Event": {
      "subject": "China CDC",
      "object": "Hubei Province and other provinces",
      "aspect": "Diagnostic deployment",
      "medium": "RT‑PCR kits",
      "action": "distributed",
      "time_raw": "16 January 2020",
      "time_iso": "2020-01-16",
      "time_precision": "day",
      "location": "Hubei Province",
      "consequence": "Enabled mass testing across China",
      "relation": null,
      "source": "China CDC announcement"
    },
    "Person": [],
    "Involved_Parties": [
      {
        "party_name": "China CDC",
        "party_role": "National Center for Disease Control"
      }
    ],
    "Impact": [
      {
        "impact_description": "Rapid kit distribution laid groundwork for nationwide testing strategies."
      }
    ],
    "Event_Timeline": [
      {
        "date_raw": "16 January 2020",
        "date_iso": "2020-01-16",
        "date_precision": "day",
        "description": "First RT‑PCR kits distributed to Hubei."
      },
      {
        "date_raw": "19 January 2020",
        "date_iso": "2020-01-19",
        "date_precision": "day",
        "description": "RT‑PCR kits distributed nationwide."
      }
    ],
    "evidence_snippets": [
      {
        "text": "On 16 January, the first RT‑PCR assays for COVID‑19 were distributed to Hubei. Real‑time PCR kits were distributed to all the provinces on 19 January.",
        "char_start": null,
        "char_end": null,
        "paragraph_id": null,
        "sentence_index": null,
        "source_id": null,
        "confidence": 100
      }
    ]
  },
  {
    "article_title": "COVID-19 Detection and Early Research Efforts",
    "Event_Summary": "Early surveillance data revealed SARS‑CoV‑2 detection in respiratory, fecal and blood samples, prompting coordinated research and diagnostic approval in China.",
    "Event": {
      "subject": "Guangzhou CDC",
      "object": "COVID‑19 patients",
      "aspect": "diagnostic",
      "medium": "biological specimens",
      "action": "detection",
      "time_raw": "20 February",
      "time_iso": null,
      "time_precision": "unknown",
      "location": "Guangzhou, China",
      "consequence": "Early identification of infected individuals before symptom onset.",
      "relation": "Guangzhou CDC collaborates with national health agencies",
      "source": "Source unknown"
    },
    "Person": [],
    "Involved_Parties": [
      {
        "party_name": "Guangzhou CDC",
        "party_role": "Regional public health authority"
      }
    ],
    "Impact": [
      {
        "impact_description": "Detection in upper respiratory samples 1‑2 days prior to symptoms allows earlier isolation and treatment."
      }
    ],
    "Event_Timeline": [
      {
        "date_raw": "20 February",
        "date_iso": null,
        "date_precision": "unknown",
        "description": "Preliminary data collected by Guangzhou CDC on COVID‑19 viral RNA detection."
      }
    ],
    "evidence_snippets": [
      {
        "text": "According to preliminary data from Guangzhou CDC as of 20 February, virus can initially be detected in upper respiratory samples 1-2 days prior to symptom onset and persist for 7-12 days in moderate cases and up to 2 weeks in severe cases.",
        "char_start": null,
        "char_end": null,
        "paragraph_id": null,
        "sentence_index": 1,
        "source_id": null,
        "confidence": 90
      }
    ]
  },
  {
    "article_title": "Joint Mission Research Collaboration",
    "Event_Summary": "A Joint Mission team met with Chinese research laboratories to discuss rapid serological test development.",
    "Event": {
      "subject": "Joint Mission members",
      "object": "China CDC, Guangzhou Regenerative Medicine, and Health Guangdong Laboratory",
      "aspect": "research collaboration",
      "medium": null,
      "action": "meet",
      "time_raw": null,
      "time_iso": null,
      "time_precision": "unknown",
      "location": "Guangzhou, China",
      "consequence": "Accelerated development of rapid IgM/IgG tests using chemiluminiscence.",
      "relation": "Integrated national research response",
      "source": "Source unknown"
    },
    "Person": [],
    "Involved_Parties": [
      {
        "party_name": "China CDC",
        "party_role": "National health authority"
      },
      {
        "party_name": "Guangzhou Regenerative Medicine",
        "party_role": "Research institute"
      },
      {
        "party_name": "Health Guangdong Laboratory",
        "party_role": "Regional diagnostic lab"
      }
    ],
    "Impact": [
      {
        "impact_description": "Rapid test platforms enable early case detection and contact tracing."
      }
    ],
    "Event_Timeline": [
      {
        "date_raw": null,
        "date_iso": null,
        "date_precision": "unknown",
        "description": "Meeting between Joint Mission members and local research teams."
      }
    ],
    "evidence_snippets": [
      {
        "text": "Joint Mission members met with local research teams at the China CDC, Guangzhou Regenerative Medicine and Health Guangdong Laboratory.",
        "char_start": null,
        "char_end": null,
        "paragraph_id": null,
        "sentence_index": 1,
        "source_id": null,
        "confidence": 85
      }
    ]
  },
  {
    "article_title": "China’s Emergency COVID‑19 Research Programs",
    "Event_Summary": "The Chinese government launched comprehensive emergency research programs covering genomics, antivirals, vaccines, diagnostics, and animal models.",
    "Event": {
      "subject": "Government of China",
      "object": "Public health and biomedical community",
      "aspect": "research policy",
      "medium": null,
      "action": "initiated",
      "time_raw": null,
      "time_iso": null,
      "time_precision": "unknown",
      "location": "China",
      "consequence": "Rapid development of therapeutic and preventive measures.",
      "relation": "National coordination of science and public health",
      "source": "Source unknown"
    },
    "Person": [],
    "Involved_Parties": [
      {
        "party_name": "Government of China",
        "party_role": "National governing body"
      }
    ],
    "Impact": [
      {
        "impact_description": "Structured research accelerates identification of effective treatments and vaccines."
      }
    ],
    "Event_Timeline": [
      {
        "date_raw": null,
        "date_iso": null,
        "date_precision": "unknown",
        "description": "Launch of major emergency research programs on COVID‑19."
      }
    ],
    "evidence_snippets": [
      {
        "text": "The government of China has initiated a series of major emergency research programs on virus genomics, antivirals, traditional Chinese medicines, clinical trials, vaccines, diagnostics and animal models.",
        "char_start": null,
        "char_end": null,
        "paragraph_id": null,
        "sentence_index": 1,
        "source_id": null,
        "confidence": 88
      }
    ]
  },
  {
    "article_title": "NMPA Approval of COVID‑19 Diagnostic Kits",
    "Event_Summary": "China’s National Medical Products Administration approved multiple nucleic acid-based and antibody detection kits for COVID‑19.",
    "Event": {
      "subject": "NMPA",
      "object": "Diagnostic manufacturers",
      "aspect": "regulatory approval",
      "medium": "diagnostic kits",
      "action": "approved",
      "time_raw": null,
      "time_iso": null,
      "time_precision": "unknown",
      "location": "China",
      "consequence": "Expanded capacity for rapid testing and surveillance.",
      "relation": "Regulatory oversight of clinical diagnostics",
      "source": "Source unknown"
    },
    "Person": [],
    "Involved_Parties": [
      {
        "party_name": "NMPA",
        "party_role": "Regulatory authority"
      }
    ],
    "Impact": [
      {
        "impact_description": "Availability of approved tests enhances early detection and isolation of cases."
      }
    ],
    "Event_Timeline": [
      {
        "date_raw": null,
        "date_iso": null,
        "date_precision": "unknown",
        "description": "Approval of 8 nucleic acid-based methods and 2 colloidal gold antibody kits."
      }
    ],
    "evidence_snippets": [
      {
        "text": "At least 8 nucleic acid-based methods for direct detection of COVID-19 and two colloidal gold antibody detection kits have been approved in China by the NMPA.",
        "char_start": null,
        "char_end": null,
        "paragraph_id": null,
        "sentence_index": 1,
        "source_id": null,
        "confidence": 90
      }
    ]
  },
  {
    "article_title": "COVID-19 Response Plan on PPE, Diagnostics, and Research",
    "Event_Summary": "A comprehensive COVID‑19 preparedness strategy covering PPE use, community engagement, diagnostics, treatment protocols, vaccine uptake, laboratory analysis, and coordinated research initiatives.",
    "Event": {
      "subject": "Chinese health authorities",
      "object": "Healthcare workers and the general public",
      "aspect": "Health and pandemic response",
      "medium": "PPE, diagnostic tests, vaccines, research facilities",
      "action": "implement, monitor, conduct, develop and coordinate",
      "time_raw": null,
      "time_iso": null,
      "time_precision": "unknown",
      "location": "China",
      "consequence": "Strengthened infection control, early detection, improved diagnostics, vaccine uptake, accelerated research, and global collaboration",
      "relation": "Involvement of international partners, coordination with CDC, and global surveillance networks",
      "source": null
    },
    "Person": [],
    "Involved_Parties": [
      {
        "party_name": "Chinese Ministry of Health",
        "party_role": "government agency"
      },
      {
        "party_name": "Centers for Disease Control and Prevention (CDC), China",
        "party_role": "public health authority"
      },
      {
        "party_name": "International partners",
        "party_role": "collaborating organizations"
      }
    ],
    "Impact": [
      {
        "impact_description": "Improved readiness and mitigation of COVID‑19 spread through enhanced PPE use, early detection protocols, vaccine uptake, and research coordination."
      }
    ],
    "Event_Timeline": [],
    "evidence_snippets": [
      {
        "text": "Conduct pathogenesis studies using biopsy/post-mortem specimens of COVID‑19 patients or infected animal models",
        "char_start": null,
        "char_end": null,
        "paragraph_id": "bullet_list",
        "sentence_index": 2,
        "source_id": null,
        "confidence": 90
      }
    ]
  }
]
    """
    from pprint import pprint
    #data = json.loads(testDoc)
    data = testDoc
    merged, report = merge_dict_slices_audited(data)
    
    print("origin data:")
    pprint(data, width=100, compact=False, sort_dicts=False)
    
    print("\nmerged result:")
    pprint(merged, width=100, compact=False, sort_dicts=False)
    
    print("\nmerge report:")
    pprint(report, width=100, compact=False, sort_dicts=False)
