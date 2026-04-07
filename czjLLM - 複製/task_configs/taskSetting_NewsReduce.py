
taskSetting_NewsReduce = {
    "News-FacetTop10-Map-to json format": {
        "CT_name": "新聞聚合(Map)：候選事件抽取",
        "InputCutLen": 3500,  # 視你的 chunk 大小與模型限制作微調
        "template": lambda content: (
            "任務：從下列新聞文本中萃取「候選新聞事件」，去除重複或高度雷同的段落，"
            "並以純 JSON 回傳候選清單，供後續全域聚合使用。\n"
            "要求：\n"
            "1) 引用片段使用原文，以利檢索反查，其餘使用臺灣習慣用語，輸出必須是合法 JSON，勿加入多餘說明。\n"
            "2) 每則候選要能跨 chunk 去重，請產生穩定的 unique_key（如：主題關鍵詞+核心實體+日期範圍的規範化雜湊）。\n"
            "3) 請粗分面向（facet），如：政治、經濟、農業、社會、科技、國際、環境、能源、交通、文化教育。"
            "   若難以判斷，先放入最接近的單一面向。\n"
            "4) 請計算重要度（importance_score，0~100），以便後續排序；並同時提供子分數：impact, novelty, coverage, credibility（各 0~100）。\n"
            "5) 摘要時刪除贅詞，語句簡潔、明確，修正明顯錯別字與語法。\n"
            "6) 請輸出最多 30 則候選（去重後），避免重複。\n\n"
            "評分準則（簡述）：\n"
            "- impact：涉眾/政策/市場影響範圍與強度\n"
            "- novelty：相對於既有動向的新穎程度與轉折性\n"
            "- coverage：文本中被多處提及或多消息源佐證程度\n"
            "- credibility：消息來源可信度（官方/主流媒體/研究機構 > 未知管道）\n"
            "importance_score = round(0.35*impact + 0.25*novelty + 0.25*coverage + 0.15*credibility)\n\n"
            "輸出 JSON 結構：\n"
            '[\n'
            "    {\n"
            '      "unique_key": "string(穩定鍵，例：sha1(標題規範化+核心實體+首日yyyy-mm-dd))",\n'
            '      "facet": "政治|經濟|農業|社會|科技|國際|環境|能源|交通|文化教育",\n'
            '      "title_tw": "15~60字，精煉主標",\n'
            '      "summary_tw": "80~200字，列出關鍵事實與結論，避免贅語",\n'
            '      "core_entities": ["人名/機構/地名/關鍵產品"...],\n'
            '      "date_range": {"start": "yyyy-mm-dd", "end": "yyyy-mm-dd"},\n'
            '      "locations": ["地點1","地點2"],\n'
            '      "evidence_snippets": [{"text":"引用片段(<=200字)","source_id":"可用檔名/URL/內部ID"}],\n'
            '      "importance": {\n'
            '         "impact": 0, "novelty": 0, "coverage": 0, "credibility": 0,\n'
            '         "importance_score": 0\n'
            "      }\n"
            "    }\n"
            "]\n"
            "☆下列為輸入任務文本：\n"
            f"{content}"
        )
    },
    
    "News-FacetTop10-Reduce-to json format": {
      "CT_name": "新聞聚合(Reduce)：SQL平面化列輸出",
      "InputCutLen": 2000,
      "template": lambda content: (
        "任務：輸入為多個 Map 結果合併後的候選事件陣列（頂層為 array）。"
        "請在全域層級進行去重、聚合與排序，最後輸出「頂層為陣列」的**純平面列**，每列代表一個聚合後事件。"
        "回應必須是**合法 JSON，且只有資料**，不可含任何多餘文字或 Markdown。\n"
        "規則：\n"
        "1) 去重：先以 unique_key；如鍵不同但內容相近，依『標題語義近似度 + 核心實體交集 + 日期重疊』合併；來源去重。\n"
        "2) 排序：以 importance_score 為主；同分時依序比較 impact > coverage > credibility > novelty。\n"
        "3) 名單：每面向最多10則（不足可少於10）；另計算跨面向的 global 前10，於列中標記。\n"
        "4) 文案：刪除不必要詞語、改善用詞、過渡自然；修正明顯錯別字與語法；摘要具體可驗（僅據輸入可支持之事實/數據）。\n"
        "5) 型別與格式：分數/名次整數；日期 yyyy-mm-dd；欄位 snake_case；多值欄位使用『|』分隔；若原文含『|』請以『／』替代。\n\n"
    
        "【輸入格式】頂層為陣列，如：[ {候選1}, {候選2}, ... ]。\n\n"
    
        "【輸出 JSON 結構（頂層為陣列，單列＝單事件）】\n"
        "[\n"
        "  {\n"
        '    "version": "v1.2-sqlflat",\n'
        '    "generated_at": "yyyy-mm-ddTHH:MM:SSZ",\n'
        '    "group_key": "聚合後穩定鍵（沿用代表項 unique_key 或新哈希）",\n'
        '    "facet_code": "POL|ECO|AGR|SOC|TEC|INT|ENV|ENE|TRA|CUL",\n'
        '    "facet_name": "政治|經濟|農業|社會|科技|國際|環境|能源|交通|文化教育",\n'
        '    "rank_in_facet": 1,               \n'
        '    "is_in_global_top10": 1,          \n'
        '    "rank_global": 1,                 \n'
        '    "title_tw": "精煉主標（15~60字）",\n'
        '    "summary_tw": "150~260字，列重點、影響、利害關係人與後續觀察；避免贅語",\n'
        '    "date_start": "yyyy-mm-dd",\n'
        '    "date_end": "yyyy-mm-dd",\n'
        '    "importance_score": 0,\n'
        '    "impact": 0,\n'
        '    "novelty": 0,\n'
        '    "coverage": 0,\n'
        '    "credibility": 0,\n'
        '    "core_entities_csv": "實體1|實體2|實體3",\n'
        '    "locations_csv": "地點1|地點2",\n'
        '    "sources_csv": "source_id1|source_id2|source_id3",\n'
        '    "snippets_json": "[{\\"text\\":\\"片段一\\",\\"source_id\\":\\"source_id1\\"},{\\"text\\":\\"片段二\\",\\"source_id\\":\\"source_id2\\"}]",\n'
        '    "sources_count": 0,\n'
        '    "snippets_count": 0\n'
        "  }\n"
        "]\n\n"
    
        "【合併與欄位生成細則】\n"
        "- title_tw/summary_tw：合併後選最具代表性版本，必要時微調語句，避免冗語並修正錯別字。\n"
        "- date_start/date_end：取所有來源的最早與最晚日期作為區間。\n"
        "- *_csv 欄位：以『|』連接；若原字串含『|』以『／』替代。\n"
        "- snippets_json：為 JSON 字串（而非陣列）；每項含 text 與 source_id，文字長度宜≤200字；保留最多5則代表片段。\n"
        "- is_in_global_top10/rank_global：若未入選則 is_in_global_top10=0、rank_global=null。\n\n"
    
        "☆下列為輸入任務文本（由多個 Map 陣列合併而成）：\n"
        f"{content}"
      )
    }
}
