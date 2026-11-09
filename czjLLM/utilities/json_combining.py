"""JSON text parsing and combination helpers.

Kept separate from filesystem result orchestration so callers can reuse the JSON
normalisation logic without loading the much larger combine workflow.
"""

import json
import re

from json_repair import repair_json
from czjLLM.utilities.json_text_utils import strip_markdown_code_fence


def _flatten_list(items):
    """Flatten one list level without importing the broad legacy utilities module."""
    return [item for sublist in items for item in sublist]


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

def split_json_arrays_safe(
    raw: str, *, reject_incomplete: bool = False,
) -> list[str]:
    """
    將 raw 字串中的多個 JSON 陣列（支援跨行、巢狀物件）正確分割成獨立區塊。

    避免使用正則處理嵌套結構，改用 quote/escape-aware 括號平衡方式切分。
    Opt-in fail-closed mode prevents silently dropping an unfinished array.
    The default preserves this public helper's historical tolerant behavior.
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

    if started and reject_incomplete:
        # An unfinished array (including a quoted string without a closing
        # quote) cannot be safely combined: do not emit [] or a partial
        # prefix as if the entire LLM output was successfully processed.
        raise ValueError("JSON_ARRAY_SEGMENT_INCOMPLETE")
    return arrays

def robust_merge_json_lists(raw: str, *, require_complete: bool = False) -> str:
    """
    清理並合併多個 JSON 陣列字串，並在解析失敗時自動嘗試修復格式錯誤的段落。

    處理流程：
    1. 移除程式碼區塊的 Markdown 格式標記（```json ... ```）。
    2. 使用已存在的 quote/escape-aware 括號掃描器分段抓取完整 JSON 陣列（如 [ {...}, {...} ]）。
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
    # The legacy splitter counts brackets inside quoted JSON strings and can
    # truncate valid output (e.g. {"text": "]"}). Reuse the existing
    # quote/escape-aware scanner; preserve the downstream repair fallback.
    parts = split_json_arrays_safe(raw, reject_incomplete=True)
    if require_complete and not parts:
        # A non-JSON response must not become a successful empty JSON array.
        raise ValueError("JSON_ARRAY_SEGMENT_MISSING")
    all_items = []
    skipped_segment = False

    for p in parts:
        try:
            # 嘗試將每段轉換為 Python list
            arr = json.loads(p)
            if isinstance(arr, list):
                all_items.extend(arr)
            else:
                skipped_segment = True
        except json.JSONDecodeError:
            # The input and exception text may contain source material.
            # Use fixed codes only; do not log raw LLM output.
            print("[JSON-COMBINE] decode_failed; attempting_local_repair")

            try:
                # 嘗試修復格式錯誤並重新解析
                repaired = repair_json(p)
                arr = json.loads(repaired)

                if isinstance(arr, list):
                    all_items.extend(arr)
                    print("[JSON-COMBINE] repaired_segment_accepted")
                else:
                    skipped_segment = True

            except Exception:
                # Preserve legacy result behavior while avoiding raw source,
                # exception messages and credentials in console output.
                print("[JSON-COMBINE] repair_failed_segment_skipped")
                skipped_segment = True

    if require_complete and skipped_segment:
        # Opt-in validation callers must never accept a partial successful
        # prefix after an invalid or unrepaired list segment.
        raise ValueError("JSON_ARRAY_SEGMENT_SKIPPED")

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



def combine_json_return(json_content,NoNestedList=True,dictListForced=True, *, require_complete=False):
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
    # Preserve the legacy one-argument call contract for tolerant callers,
    # including integrations that wrap this helper with a single-arg function.
    if require_complete:
        json_content_res = robust_merge_json_lists(
            json_content_res, require_complete=True,
        )
    else:
        json_content_res = robust_merge_json_lists(json_content_res)
    #print("json_content_res af",json_content_res)

    error_mes = ""
    try:
        json.loads(json_content_res)
    except Exception as ex:
        error_mes = ex
        try:
            print("[JSON-COMBINE] combined_decode_failed; attempting_local_repair")
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
                    decoded_object = _flatten_list(decoded_object)
            # 資料處理格式，可能會產生不合格式：[[字典1,字典2],[字典3,字典4]]
            if dictListForced == True:
                tmp_dict_list = []
                for subterm in decoded_object:
                    if isinstance(subterm,dict):
                        tmp_dict_list.append(subterm)
                    elif isinstance(subterm,list):
                        tmp_dict_list.extend([x for x in subterm])
                    else:
                        print("[JSON-COMBINE] repaired_item_shape_invalid")
                        raise Exception
                decoded_object = tmp_dict_list
            json_content_res = json.dumps(
                decoded_object,ensure_ascii=False,indent=4)

            print("[JSON-COMBINE] combined_repair_succeeded")
            error_mes = str(error_mes)+"\nBut it is repaired with repair_json."
        except Exception:
            print("[JSON-COMBINE] combined_postprocess_failed")
            pass
    return json_content_res,error_mes
