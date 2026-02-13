from utils.utilities import removeStrSuffix

MULTIDIM_EXTRACTION_Rule = """
【整體原則】
1. 僅依據輸入文本內容進行判斷，不得憑想像補資訊。  
2. 日期與時間的處理必須遵守本提示中的所有規則；如不確定，寧可填 null 或 "unknown"。  
3. 所有輸出必須符合下方指定的 SQL-friendly JSON 結構，不得任意添加或刪除欄位。  
4. 證據片段必須逐字擷取自原文，不得改寫。  
5. 不可輸出包含 XX、00、— 的日期。  

================================================================================
【日期與時間判讀（核心規則）】

一、民國年轉換  
- 若出現「114 年 01 月 01 日」→ 西元 = 民國年 + 1911 → 2025-01-01。  
- 精度（precision） = "day"。  

二、可被視為「日期」的來源（必要條件）  
僅當文本中出現下列任一情況時，才允許將內容視為日期：  
- 含有「年／月／日」字樣  
- 含有明顯年月日分隔符號（如「-」「/」）  
- 含有「期間、起、至、起迄、某日、前一日、本月、當月、本年、去年、前年」等日期語氣詞  

若未出現任何上述語氣，不得將任何純數字視為日期。

三、四位數（如 0504、0724、0842）的判讀優先序  
四位數可能同時代表日期或時間，請依下列順序判斷：  

【1】若四位數附近（前後約 10–15 個字）出現「時間語氣」 → 必定為「時間」  
時間語氣包含（但不限於）：  
- 「時」「時許」「時起」「時左右」「約」「約在」  
- 「分」「分鐘後」  
- 「今日」「本日」「當日」「凌晨」「清晨」「上午」「下午」「晚間」  
- 常與時間搭配的動作或場景：偵獲、觀測、升空、通報、航跡、速度、雷達等  
→ 在此情況下，四位數必須視為 HHmm，不得推導任何日期。  

【2】若四位數附近出現「日期語氣」 → 才「可能」視為 MMDD  
- 僅在同一語境中明確指向某月某日時，才可視為日期。  
- 仍須檢查本文是否已存在其他明確日期（見下一條）。  

【3】若全文已有「唯一且明確日期」  
例如標題為「114 年 01 月 01 日情勢摘要」。  
→ 文中所有四位數（0504、0724、0842）一律視為該日內的時間，不得另建新日期。  

【4】若無時間語氣、無日期語氣、無其他參照 → 視為無法判定  
→ 採取保守策略：  
- date_iso = null  
- date_precision = "unknown"  
- time_iso = null（除非可合理視為 HHmm 時間）  

四、HHmm 時間標準化  
當四位數被判斷為時間時：  
- time_raw = 原始字面（例如 "0504"）  
- time_iso = "05:04"  
- time_precision = "minute"  

五、Event_Timeline 中日期與時間的關聯  
- 若本文中有明確的單一日期，則該日期可作為該篇事件時間軸的日期基準：  
  - Event_Timeline 中所有與該日相關的時間，date_iso 皆為同一天。  
- 時間相關內容應寫入 description，如：「05:04 起空偵站掌握對岸活動跡象」。  
- 禁止將「0504」誤判為「2025-05-04」。  

六、保守策略（非常重要）  
若存在任何可能誤判的情況，請優先採取保守作法：  
- date_iso = null  
- time_iso = null  
- date_precision / time_precision = "unknown"  
不得自行猜測或補齊年月日。

================================================================================
【日期回填規則】

在「已確定年份或年月」但缺少完整年月日時，請依下列規則標準化：  
- 僅有「年」：  
  - time_iso = "YYYY-01-01"  
  - time_precision = "year"  
- 僅有「年 + 月」：  
  - time_iso = "YYYY-MM-01"  
  - time_precision = "month"  
- 有「年 + 月 + 日」：  
  - time_iso = "YYYY-MM-DD"  
  - time_precision = "day"  
- 無法判斷：  
  - time_iso = null  
  - time_precision = "unknown"  

Event_Timeline 中的 `date_iso` 與 `date_precision` 亦遵守相同邏輯。

================================================================================
【文章層級日期（article_date_iso）規則】

- 定義：代表「整篇文章」最具代表性的日期，多數情況為報導日期或主要事件發生日。  

取得優先順序如下：  
1. 若標題或開頭段落中出現「唯一且明確」的年月日，且可判定為本報導日期 → 以此作為 article_date_iso。  
2. 否則，若 Event_Timeline 中只有一個 date_precision = "day" 的 date_iso → 以該日作為 article_date_iso。  
3. 若僅有年或年月，依【日期回填規則】轉成 YYYY-01-01 或 YYYY-MM-01 後填入。  
4. 若存在多個不同日期且無法合理判定哪一個代表整篇文章 → article_date_iso = null。  

補充規則：  
- 禁止將四位數時間（如 0504）誤判為日期。  
- 禁止憑空補年份或日期。  
- 無法合理判斷時，寧可將 article_date_iso 填為 null，article_date_precision 填為 "unknown"。  

================================================================================
【主題與核心實體欄位規則】

以下欄位位於最外層結構，用於搜尋與聚合分析：

一、facet（主題面向標籤）

1. 定義  
   - 用來標示本事件主要屬於哪些主題面向，支援多選。  

2. 可用類別（僅能從下列集合中擇一或多個）：  
   - "politics"     ：選舉、外交、政黨、政府決策、對外關係  
   - "economy"      ：關稅、貿易、物價、通膨、就業、實質工資等經濟議題  
   - "security"     ：軍事行動、軍演、軍售、威懾、國防安全  
   - "society"      ：民生、治安、抗議、教育、社會議題  
   - "technology"   ：科技、資訊、AI、網路、資安  
   - "disaster"     ：天災（地震、颱風、洪水）與重大人為事故  
   - "health"       ：疫情、防疫措施、公共衛生、醫療事件  
   - "environment"  ：環境保護、氣候變遷、能源轉型  
   - "other"        ：無法合理歸類到上述任一類別時  

3. 判斷原則  
   - 以整篇文章與 Event_Summary 的核心內容為準，不因短暫提及就加標籤。  
   - 若同時涉及多個面向（如「關稅政策與軍事威懾」），可同時包含 "economy" 與 "security"。  
   - 若仍無法判斷，填入空陣列 [] 或僅填 ["other"]，不得憑想像補類別。

二、core_entities（核心實體）

1. 定義  
   - 在事件中扮演關鍵角色的國家、地區、組織、重要單位或特定系統，用於做實體維度聚合。  

2. 來源範圍  
   - Event.subject、Event.object  
   - Person.name 與其角色  
   - Involved_Parties.party_name  
   - 文章中反覆出現、對事件有關鍵影響的實體名稱  

3. 規則  
   - 儘量使用文本中的原始寫法（例如「美國」、「中華人民共和國」、「052D 驅逐艦」）。  
   - 僅保留與事件因果高度相關的實體，不要把所有人名、地名都塞進來。  
   - 避免過度籠統的詞（如「軍隊」「媒體」「民眾」）；若無明確核心實體，填空陣列 []。  
   - 不得創造原文未出現的新實體名稱。  

三、locations（標準化地點列表）

1. 定義  
   - 本事件中明確提到的主要地點，從文本中抽取後以較規則的形式呈現，用於搜尋與聚合。  

2. 規則  
   - 僅收「有地名」的地點，至少需有地區/城市或明確地理標的，例如：  
     - "Taipei, Taiwan"  
     - "South China Sea"  
     - "Washington D.C., United States"  
   - 若原文僅寫「南海」而未指明國別，可填寫 "South China Sea"；但不得憑空補上國家。  
   - 可從 Event.location、Event_Timeline.description、Person.action 等處抽取。  
   - 若全文沒有任何明確地名，請填空陣列 []。  
   - 不得創造原文未提及的新地點。  

================================================================================
【證據片段規則（evidence_snippets）】

1. 來源與形式  
   - 每一筆 evidence_snippets.text 必須直接從輸入原文中逐字擷取（verbatim），禁止任何形式的改寫或摘要。  
   - 每個事件最多擷取 30 段證據片段。  

2. 長度限制  
   - 單一片段最長不超過 280 個字，以避免內容過長。  

3. 位置資訊（若能判斷）  
   - char_start：該片段在整篇輸入文本中的起始字元位置（從 0 起算），無法精準定位時填 null。  
   - char_end：該片段在整篇輸入文本中的結束字元位置（不含 end），無法精準定位時填 null。  
   - paragraph_id：可選，段落或小節識別，若能合理判斷可填入，否則為空字串或 null。  
   - sentence_index：可選，該片段所在段落內的句子索引（整數），無法判斷時填 null。  

4. 其他欄位  
   - source_id：資料來源 ID 或 URL（若原始輸入有提供，否則可為空字串或 null）。  
   - confidence：0–100 的整數，代表模型對此片段作為證據的信心程度。  

5. 避免冗餘  
   - 若多段片段高度重複，優先保留資訊最完整、信心最高的片段，避免重覆內容。

================================================================================
【重要性評分規則（importance.*）】

此區用於評估文章或事件在整體監測體系中的相對重要性。  

- coverage（整體涵蓋度）  
  - 0–100 的整數。  
  - 評估本文對事件背景、過程與結果的描述是否完整。  
  - 報導資訊越全面、細節越多，coverage 分數越高。  

- novelty（新穎性）  
  - 0–100 的整數。  
  - 衡量事件相較於常見新聞是否具有新穎或罕見特徵。  
  - 完全例行、重複性高的事件分數偏低；罕見或首次出現的事件分數較高。  

- impact（影響程度）  
  - 0–100 的整數。  
  - 評估事件對國內外政治、經濟、安全、社會等層面的潛在或實際影響。  
  - 牽涉國家安全、重大經濟變化或大規模災害者分數應偏高。  

- credibility（可信度）  
  - 0–100 的整數。  
  - 依據消息來源與報導方式評估可信度：  
    - 官方文件、權威媒體：通常較高。  
    - 未具名消息來源、謠言或明顯立場偏頗者：較低。  

- importance_score（綜合重要性）  
  - 0–100 的整數。  
  - 綜合 coverage、novelty、impact、credibility 四項評分後，給出整體重要性指標。  
  - 並非單純平均，可以依情況略為調整，但須保持內在一致性（例如 impact 與 credibility 極低時，importance_score 不應過高）。  

注意：  
- 所有上述評分欄位必須為整數，不得輸出小數。  
- 若資訊不足難以評估某一指標，可給予中低分（如 40–60），但不得填 null 或憑空給極端分數。  

================================================================================
【輸出結構】

最終輸出必須是一個 JSON 陣列，通常只有一個物件，例如：

[{
  "article_title": "文章標題",
  "article_date_iso": "代表整篇文章的日期，格式 YYYY-MM-DD；無法判斷時為 null",
  "article_date_precision": "文章日期精度，必為 \"day\" | \"month\" | \"year\" | \"unknown\"",

  "facet": ["economy", "politics"],          // 主題面向標籤，可為空陣列 []
  "core_entities": ["United States", "China"], // 核心實體清單，可為空陣列 []
  "locations": ["Washington D.C., United States", "Beijing, China"], // 主要地點，可為空陣列 []

  "Event_Summary": "一句到三句話摘要文章核心。",

  "Event": {
    "subject": "事件主體（自然力量、政府、組織等）",
    "object": "受體（事件的承受者）",
    "aspect": "面向（政治、經濟、社會、災害等）",
    "medium": "涉及物/媒介（石油、建築、媒體、平台等）",
    "action": "動作（撤離、進口、攻擊、援助等）",

    "time_raw": "文本中出現的原始時間字面（如：2025年2月、9月底、去年）",
    "time_iso": "標準化日期（僅允許 YYYY-MM-DD；若僅有年/月，須依日期回填規則；無法判斷時為 null）",
    "time_precision": "\"day\" | \"month\" | \"year\" | \"unknown\"",

    "location": "事件發生或主要影響的地點描述（可較口語）",
    "consequence": "事件後果/影響",
    "relation": "涉及的其他人物、單位或國家關係",
    "source": "新聞來源或報導者（若有）"
  },

  "Person": [
    {
      "name": "人物名稱",
      "role": "身份/職位/關係",
      "action": "該人物的主要動作或經歷",
      "quote": "直接言論（若有）",
      "stance": "立場或情緒（如：支持、反對、譴責、關切等）",
      "relation": "與其他人物或群體之關係說明"
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
      "date_raw": "原始字面（如：2025年9月、9/29、去年9月）",
      "date_iso": "標準化為 YYYY-MM-DD；僅有年/月時依規則回填 01 為日；無法判斷時為 null",
      "date_precision": "\"day\" | \"month\" | \"year\" | \"unknown\"",
      "description": "該時間點或期間的事件內容描述"
    }
  ],

  "evidence_snippets": [
    {
      "text": "與本事件高度相關的原文片段（請逐字擷取，最大 280 字）",
      "char_start": 123,            // 整數或 null
      "char_end": 256,              // 整數或 null
      "paragraph_id": "段落或小節識別（若能判斷，否則可為空字串或 null）",
      "sentence_index": 0,          // 整數或 null
      "source_id": "資料來源 ID 或 URL（若有，否則可為空字串或 null）",
      "confidence": 90              // 整數 0–100
    }
  ],

  "importance": {
    "coverage": 80,
    "novelty": 60,
    "impact": 90,
    "credibility": 85,
    "importance_score": 84
  }
}]

-極重要：注意如果輸入文本是羅列了非結構化的查詢綜整結果的文件，那麼每一個條目都屬於檢索綜整式AI代理人可能會用到的項目，應該將所有條目都萃取至evidence_snippets中，避免遺漏任何一條，每一個原文的條目抽成一個證據片段，以利檢索。
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