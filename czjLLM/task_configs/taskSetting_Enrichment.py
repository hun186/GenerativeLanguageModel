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
    "time": "事件發生時間或報導時間（格式：YYYY-MM-DD）",
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
    {"date": "YYYY-MM-DD", "description": "事件內容"}
  ]
}]
"""


taskSetting_Enrichment = {
    "InfoExtraction-MultiDim-SQLFriendly-to json format": {
        "CT_name": "多維度新聞事件分析與 SQL-friendly JSON 輸出",
        "InputCutLen": 100,
        "template": lambda MainFileName, content: (
            f"請針對下列輸入任務文本進行完整多維度事件分析與資訊萃取，"
            "並輸出 SQL-friendly JSON 結構，不要有額外說明或前置詞。\n\n"
            f"{MULTIDIM_EXTRACTION_Rule}"
    		f"主檔名為「{removeStrSuffix(MainFileName,'_tika')}」，可用於輔助分析article_title。\n"
            "☆下列為輸入任務文本：\n"
            f"{content}"
        )
    }
}