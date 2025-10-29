from __future__ import annotations
from pathlib import Path

import os
import json
from opencc import OpenCC
import shutil
import re
from typing import List, Dict, Any
from utils.utilities_path import OSWALK
from utils.utilities_path import MKDIR
from utils.utilities_path import getPathFromFN
from utils.utilities_path import DirReplace
from utils.utilities import flattenList
from utils.MP_utils import MPlogger

from json_repair import repair_json

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
    raw = raw.replace("```json", "").replace("```", "").strip()

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
    json_content_res = json_content.replace("```json\n", "").replace("```\n", "").strip()
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


def combine_api_finished_item(item: str, ctx) -> str:
    print(f"{item} is finished calling API, start to combine returned result.")
    item_p = Path(item)
    suc_dir = item_p / "Success"

    chunks: list[str] = []
    for fp in sorted(OSWALK(str(suc_dir))):
        #print("fp adding in combine_utils",fp)
        p = Path(fp)
        text = p.read_text(encoding="utf-8")
        #print("text",text)
        if OpenCC("s2twp").convert(text.lstrip()).startswith("無主題相關內容"):
            continue

        try:
            obj = json.loads(text)
            if isinstance(obj, dict):
                obj = [obj]
            elif not isinstance(obj, list):
                raise ValueError("不支援的 JSON 結構")
            chunks.append(json.dumps(obj, ensure_ascii=False, indent=2) + "\n")
        except Exception as e:
            if "to json format" in str(getattr(ctx, "task", "")).lower():
                print(f"❌ 解析 JSON 失敗（跳過格式補正）：{p}，錯誤：{e}")
            chunks.append(text if text.endswith("\n") else text + "\n")
    #print("chunks",chunks)
    combined_text = "".join(chunks)
    #print("combined_text",combined_text)
    # === 安全地決定輸出目錄（不要出現前導斜線） ===
    # 優先 llm_source_finished_dir，其次 llm_source_dir；都沒有就用 item 的上層
    #'''
    base_out = (
        Path(getattr(ctx, "temp_txt_finished_dir", "")) or
        Path(getattr(ctx, "llm_source_finished_dir", "")) or
        Path(getattr(ctx, "llm_source_dir", "")) or
        item_p.parent
    )
    #'''
    
    '''
    def _p(s):
        # 僅在 s 是非空字串時回傳 Path，否則回傳 None 讓 or 繼續 fallback
        return Path(s) if isinstance(s, str) and s.strip() else None
    
    # 優先：每列覆寫用的 temp_txt_finished_dir
    base_out = (
        _p(getattr(ctx, "temp_txt_finished_dir", None))
        or (_p(getattr(ctx, "llm_source_finished_dir", None)) / "cache"
            if _p(getattr(ctx, "llm_source_finished_dir", None)) else None)
        or (_p(getattr(ctx, "llm_source_dir", None)) / "cache"
            if _p(getattr(ctx, "llm_source_dir", None)) else None)
        or item_p.parent
    )
    '''
    base_out.mkdir(parents=True, exist_ok=True)
    #print("ctx.main_file_name",getattr(ctx, "main_file_name",""))
    #print("item_p.name",item_p.name)
    #main_name = getattr(ctx, "main_file_name", item_p.name)
    main_name = item_p.name
    #print("main_name",main_name)
    task_name = str(getattr(ctx, "task", "result")).replace(os.sep, "_")
    out_path = base_out / f"{main_name}_{task_name}.txt"

    # JSON 合併修補（如有指定 to json format）
    if "to json format" in str(getattr(ctx, "task", "")).lower():
        fixed, err = combine_json_return(combined_text, dictListForced=True)
        combined_text = fixed
        if err:
            logs_dir = Path(getattr(ctx, "PGMSubDir", "")) / "logs"
            logs_dir.mkdir(parents=True, exist_ok=True)
            MPlogger(str(logs_dir), logFile="FailToCombineJsonResult.log").logW(
                MES=f"When combining {out_path} json format, the following error occurs:\n{err}\n"
            )

    out_path.write_text(combined_text, encoding="utf-8")

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
    
def merge_dict_slices(dict_list: List[Dict[str, Any]]) -> Dict[str, Any]:
    """將多個切片（list[dict]）深度合併成單一 dict。
    規則：
      - list + list：串接（如需去重，自行改成 dict.fromkeys）
      - dict + dict：遞迴合併
      - 標量衝突：保留左側（第一個非空），若要改為以右側覆蓋可自行調整
    """
def merge_dict_slices(dict_list: List[dict]) -> dict:
    """維持你原本的合併規則（左側優先、list 串接、dict 遞迴）。"""
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
    logger: Optional[callable] = None,           # 例如 tlog_warn
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

    return (agg, report) if audit else (agg, {})