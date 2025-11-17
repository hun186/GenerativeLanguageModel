from utils.utilities import removeStrSuffix

MULTIDIM_EXTRACTION_Rule = """
【整體原則】
1. 僅依據輸入文本內容進行判斷，不得憑想像補資訊。  
2. 日期與時間的處理必須遵守本提示中的所有規則；如不確定，寧可填 null 或 "unknown"。  
3. 所有輸出必須符合指定 SQL-friendly JSON 結構，不得任意添加或刪除欄位。  
4. 證據片段必須逐字擷取自原文，不得改寫。  
5. 不可輸出包含 XX、00、— 的日期。

================================================================================
【日期與時間判讀（核心規則）】

一、民國年轉換  
- 若出現「114 年 01 月 01 日」→ 西元 = 民國年 + 1911 → 2025-01-01。  
- 精度 = day。

二、資料來源僅限明確含有日期語氣者  
允許視為「日期」的來源須包含至少一項：  
- 有「年／月／日」  
- 有「-」「/」等明顯年月日分隔符  
- 有「期間、起、至、起迄、某日、前一日、本月、當月」等字樣  
未出現以上語氣者，不得將任何數字當作日期。

三、四位數（如 0504、0724、0842）需依上下文判斷  
四位數同時可能是日期或時間；請依下列優先序判斷：

【1】若四位數附近（前後 10–15 字）出現時間語氣 → 必定為“時間”  
時間語氣包含：  
- 「時」「時許」「時起」「時左右」「約」「約在」  
- 「分」「分鐘後」「今日」「本日」「當日」「凌晨」「清晨」「上午」「下午」「晚間」  
- 與時間常搭配的動作：偵獲、觀測、升空、通報、航跡、速度、雷達等  
→ 此時四位數視為 HHmm，不得推導任何日期。

【2】若附近出現日期語氣 → 才可能視為 MMDD  
但仍須確認文本內是否存在唯一日期（見下一條）。

【3】若全文已有「唯一且明確日期」  
例如文本標題為「114 年 01 月 01 日情勢摘要」。  
→ 文中所有四位數（0504、0724、0842）均為該日的時間，不得另建新日期。

【4】若無時間語氣、無日期語氣、無其他參照 → 無法判定  
→ 需採保守策略：  
- date_iso = null  
- date_precision = "unknown"  
- time_iso = null（除非可推為 HHmm）  

四、HHmm 時間標準化  
若四位數被判斷為時間：  
- time_raw = "0504"  
- time_iso = "05:04"  
- time_precision = "minute"  

五、Event_Timeline 之日期與時間填寫  
- 若文本有明確日期 → 所有時間均繫於同一天 date_iso = YYYY-MM-DD  
- 時間填入 description：例：「05:04 起空偵站掌握對岸活動跡象」  
- 禁止將 0504 轉成 2025-05-04。

六、保守策略（非常重要）  
若有任何可能誤判的情況，  
請優先填入：  
- date_iso = null  
- time_iso = null  
- precision = "unknown"  
不可亂推測年月日。

================================================================================
【日期回填規則】
- 僅有年 → YYYY-01-01（precision=year）  
- 年月 → YYYY-MM-01（precision=month）  
- 年月日 → precision=day  
- 無法判斷 → iso=null；precision="unknown"  

================================================================================
【證據片段規則】
- 必須從輸入原文中**逐字擷取**（verbatim），不得改寫。
- 每個事件最多 3 段，單段**最多 280 字**，避免過長。
- 如能定位，請回傳 `char_start`/`char_end`；若不易定位可填 null。
- 避免重覆片段；若多段重覆，保留信心最高的單一段。

================================================================================
【輸出結構】
[{
  "article_title": "文章標題",
  "Event_Summary": "一句到三句話摘要文章核心。",
  "Event": {
    "subject": "事件主體（自然力量、政府、組織等）",
    "object": "受體（事件的承受者）",
    "aspect": "面向（政治、經濟、社會、災害等）",
    "medium": "涉及物/媒介（石油、建築、媒體、平台等）",
    "action": "動作（撤離、進口、攻擊、援助等）",

    "time_raw": "文本中出現的原始時間字面（如：2025年2月、9月底、去年）",
    "time_iso": "標準化日期（僅允許 YYYY-MM-DD；不能含 XX/00/—。若僅有年/月，見下方回填規則）",
    "time_precision": "時間精度，必為 day | month | year | unknown",

    "location": "地點",
    "consequence": "事件後果/影響",
    "relation": "涉及的其他人物、單位或國家關係",
    "source": "新聞來源或報導者"
  },
  "Person": [
    {
      "name": "人物名稱",
      "role": "身份/職位/關係",
      "action": "該人物的動作或經歷",
      "quote": "直接言論（若有）",
      "stance": "立場或情緒",
      "relation": "與其他人物或群體關係"
    }
  ],
  "Involved_Parties": [
    {"party_name": "名稱", "party_role": "身份/角色"}
  ],
  "Impact": [
    {"impact_description": "事件影響描述"}
  ],
  "Event_Timeline": [
    {
      "date_raw": "原始字面（如：2025年9月、9/29）",
      "date_iso": "標準化為 YYYY-MM-DD；僅有年/月時回填 01 為日",
      "date_precision": "day | month | year | unknown",
      "description": "事件內容"
    }
  ],
  "evidence_snippets": [
    {
      "text": "與本事件強關聯的原文片段（請逐字擷取，禁止改寫，最大 280 字）",
      "char_start": 整數或 null,     // 該片段在輸入全文的字符起始位置（從 0 起算）；若無法定位填 null
      "char_end": 整數或 null,       // 該片段在輸入全文的字符結束位置（不含 end）；若無法定位填 null
      "paragraph_id": "可選：段落或小節識別（若能判斷）",
      "sentence_index": 整數或 null, // 可選：在段落內的句子索引
      "source_id": "資料來源 ID 或 URL（若有）",
      "confidence": 整數 0-100       // 你對此片段作為證據的信心
    }
  ]
}]


"""

USE_MAINFILE_HINT = False  # True 就會加那一行，False 就隱藏
taskSetting_Enrichment = {
    "InfoExtraction-MultiDim-SQLFriendly-to json format": {
        "CT_name": "多維度新聞事件分析與 SQL-friendly JSON 輸出",
        "InputCutLen": 600,
        "template": lambda content, MainFileName=None: (
            "你是一個專責「多維度事件分析」與「SQL-friendly JSON 輸出」的資訊抽取模型。\n"
            "任務是從輸入文本中抽取事件核心、人物、涉入單位、影響、時間序列與證據片段。\n"
            "請依以下規則輸出，禁止加入額外說明、分析、推論、感想或模型自介。"
            f"{MULTIDIM_EXTRACTION_Rule}"
            + (f"主檔名為「{removeStrSuffix(MainFileName,'_tika')}」，可用於輔助分析article_title。\n"
               if USE_MAINFILE_HINT and MainFileName else "")
            + "☆下列為輸入任務文本：\n"
            + f"{content}"
        )
    }
}
taskSetting_Enrichment_1114 = {
    "InfoExtraction-MultiDim-SQLFriendly-to json format": {
        "CT_name": "多維度新聞事件分析與 SQL-friendly JSON 輸出",
        "InputCutLen": 600,
        "template": lambda content, MainFileName=None: (
            "請針對下列輸入任務文本進行完整多維度事件分析與資訊萃取，"
            "並輸出 SQL-friendly JSON 結構，不要有額外說明或前置詞。\n"
            f"{MULTIDIM_EXTRACTION_Rule}"
            + (f"主檔名為「{removeStrSuffix(MainFileName,'_tika')}」，可用於輔助分析article_title。\n"
               if USE_MAINFILE_HINT and MainFileName else "")
            + "☆下列為輸入任務文本：\n"
            + f"{content}"
        )
    }
}