from utils.utilities import removeStrSuffix

MULTIDIM_EXTRACTION_Rule = """
輸出結構：
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

【日期回填與禁止規則】
- 只有年 → date_iso = YYYY-01-01 / time_iso = YYYY-01-01；precision = "year"
- 年+月 → date_iso = YYYY-MM-01 / time_iso = YYYY-MM-01；precision = "month"
- 年月日 → precision = "day"
- 無法判斷 → iso 欄位填 null；precision = "unknown"
- 禁止輸出含 XX、00、— 的日期字串；一律改用上述回填或 null。

【證據片段規則】
- 必須從輸入原文中**逐字擷取**（verbatim），不得改寫。
- 每個事件最多 3 段，單段**最多 280 字**，避免過長。
- 如能定位，請回傳 `char_start`/`char_end`；若不易定位可填 null。
- 避免重覆片段；若多段重覆，保留信心最高的單一段。
"""

USE_MAINFILE_HINT = False  # True 就會加那一行，False 就隱藏
taskSetting_Enrichment = {
    "InfoExtraction-MultiDim-SQLFriendly-to json format": {
        "CT_name": "多維度新聞事件分析與 SQL-friendly JSON 輸出",
        "InputCutLen": 600,
        "template": lambda content, MainFileName=None: (
            "請針對下列輸入任務文本進行完整多維度事件分析與資訊萃取，"
            "並輸出 SQL-friendly JSON 結構，不要有額外說明或前置詞。\n\n"
            f"{MULTIDIM_EXTRACTION_Rule}"
            + (f"主檔名為「{removeStrSuffix(MainFileName,'_tika')}」，可用於輔助分析article_title。\n"
               if USE_MAINFILE_HINT and MainFileName else "")
            + "☆下列為輸入任務文本：\n"
            + f"{content}"
        )
    }
}