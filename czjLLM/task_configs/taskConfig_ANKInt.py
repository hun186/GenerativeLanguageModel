import os
from utils.utilities import removeStrSuffix
#from utils.utilities import countdown_pause
if os.path.isfile("GenerativeLanguageModel/czjLLM/pre_trans_ak.py"):
    from GenerativeLanguageModel.czjLLM.pre_trans_ak import pre_trans
    
PDF_OPT_Rule = (
    "1.請將冗餘空格或同一段落內的不必要的斷行去除。但如果判定為段落標題斷行或分段斷行，則保留該斷行。尤其像下述這種圖表產生之多餘斷行：2\n0\n0\n6\nQ\n1\n，應合併成2006Q1\n"
    "2.若有掃瞄OCR錯誤導致亂碼或錯字，將其修正。\n"
    "3.只留下文本切片含有的討論主題正文，去除非關主題的雜訊，如：版權宣告、免責宣告、資格聲明、聯絡方式、分析師介紹、評級標準。\n"
    "4.除了前述清整雜訊的情況外，留下之正文儘量不要改寫原有文字，也不要進行摘整或擴增說明。\n"
    "5.如果開頭出現與主題相似的標題，請把標題也留下。\n"
    "6.回應不要有LLM回答的前置提示詞，也不要有額外說明。\n"
    "7.保持原有簡繁體設定。\n"
    "8.針對全文做前述完整分析，不要只做一半。\n"
    "9.如果清整後沒有留下主題內容，請回應：無主題相關內容。\n"
    )

CLASS_EXT_Rule = (
    "1.留下之正文儘量不要改寫原有文字，也不要進行摘整或擴增說明。\n"
    "2.如果開頭出現與目標類別相關的標題，請把標題也留下。\n"
    "3.目標類別不考慮語種或簡繁差異，只要是該類別文本就留下，但是討論的內容主題類別關聯性要以較嚴謹的標準來認定。\n"
    "4.回應不要有LLM回答的前置提示詞，也不要有額外說明。\n"
    "5.輸出時保持原有簡繁體設定。\n"
    "6.儘可能去針對全文做前述完整分析，不要中途結束。\n"
    "7.如果清整後沒有留下目標類別內容，請回應：無主題相關內容。\n"
    )

DETAIL_EXT_TRANS_Rule = """
1.去除格式雜訊。
2.捨去附錄內容。
3.回應不要有LLM回答的前置提示詞，也不要有答案以外的擴增說明。
"""

MDT_EXTRACTION_Rule = """
請萃取下列任務文本中有關軍事、外交、科技、政治、經濟、社會、機關單位領域的詞彙，如果該詞彙的某個片段也是有意義的子詞彙，則一併提取，提取原則為越多越好。輸出格式為 json 格式，以繁體中文取代簡體中文輸出。

對於每個領域的詞彙，請注意以下要求：
1. **semantic_components子詞彙抽取：可以針對main_term進行拆解，但拆解的結果應該是有意義的子詞彙。例如，「北大西洋公約組織」可以拆解為「北大西洋」和「公約組織」，但不應拆解為「北」、「大」、「西」、「洋」等無意義的單個字符。
2. **語義提取**：只提取具有語義並能構成有意義語句的片段，拆解後的子詞應該有語法或語義上的意圖。

輸出格式要求：
每個詞彙的資訊以 JSON 物件表示，包含以下欄位：
main_term：文本中出現的詞彙用字，如果中英文翻譯共同出現，優先採用中文。
formal_name_china：詞彙的中國大陸用語正式全稱，。
formal_name_taiwan：詞彙的臺灣用語正式全稱。
formal_name_en：詞彙的英文正式全稱。
field：詞彙所屬領域（例如軍事、外交、科技）。
semantic_components：main_term、formal_name_zh_cn、formal_name_zh_tw這三個屬性中有意義片段構成的子詞彙。
abbreviations_zh：main_term的中文縮寫清單。
definition：詞彙的定義或解釋。
context：詞彙在輸入任務文本中的上下文。
article_title：輸入任務文本的有意義標題。
article_code：輸入任務文本的文件編號或期數編號。
article_proceeding：輸入任務文本的出處刊名。
如果某個欄位沒有合適的值，請留空。
參考輸出範例：
[
{
"main_term": "武器裝備體系",
"formal_name_china": "武器裝備體系",
"formal_name_taiwan": "武器裝備體系",
"formal_name_en": "Weapon Equipment System",
"field": ["軍事"],
"semantic_components": ["武器", "裝備體系", "裝備", "體系"],
"abbreviations_zh": ["武裝體系","軍備體系","裝備體系"],
"definition": "指用於軍事目的的各種武器和相關裝備的組合。",
"context": "在現代戰爭中，武器裝備體系的完善與否直接影響戰鬥力。",
},
{
"main_term": "北約",
"formal_name_china": "北大西洋公約組織",
"formal_name_taiwan": "北大西洋公約組織",
"formal_name_en": "North Atlantic Treaty Organization",
"field": ["外交"],
"semantic_components": ["北大西洋", "公約組織"],
"abbreviations_zh": ["北約"],
"definition": "由北美和歐洲國家組成的軍事同盟。",
"context": "北約近期舉行了年度軍事演習。",
},
{
"main_term": "太空人",
"formal_name_china": "航天員",
"formal_name_taiwan": "太空人",
"formal_name_en": "Astronaut",
"field": ["科技"],
"semantic_components": ["太空", "航天"],
"abbreviations_zh": ["太空人"],
"definition": "太空人是指接受航太訓練後，指揮、操縱或搭乘太空載具的人員。",
"context": "自1961年人類首次飛天以來，共有來自64個國家的太空人先後飛天。",
},
]

注意事項：
-範例僅供格式參考，如果範例中的詞彙未出現在輸入任務文本中，請勿將其加入輸出。
確保輸出格式嚴格符合 JSON 規範。
-main_term 原則上是一個詞彙，避免中文及該詞的英文翻譯並列，如果都有出現，選擇中文詞彙。
-main_term 是文本中出現的詞彙（可能是簡稱或上下文用詞），而 formal_name_zh_cn及formal_name_zh_tw 是該詞彙的中文正式全稱，三者不一定相同。
-semantic_components的部份，要對main_term、formal_name_zh_cn、formal_name_zh_tw三個屬性都做分析。
-只要輸出JSON格式就好，不要有其他說明。
"""

NESTED_SYMBOL_FIX_Rule = (
        "目前有一份結構化文本因使用者操作錯誤、掃描瑕疵或轉檔問題，"
        "導致項目層級混亂、OCR 誤字與格式不正確，無法通過文本分析程式的解析。\n\n"
        "請你根據語意，在不改變原文內容的前提下，修正層級結構與排版錯誤，"
        "清除明顯的 OCR 雜訊、錯字與異常符號，並注意「項目符號格式」的正確性，"
        "尤其包含括號的全半形，否則會導致後續其他程式分析失敗。\n\n"
        "層級格式請嚴格依照下列順序：\n"
        "第一層：「一、」「二、」…\n"
        "第二層：「（一）」「（二）」…\n"
        "第三層：「1、」「2、」…\n\n"
        "僅輸出修正後的純文本，不需任何說明或補充。輸出時不要改變原來中文的簡繁體設定。"
        "注意不要改變原文項目號次後面的項目名稱。"
)
#qwen3加範例有時候會有問題，先不用範例。
NESTED_SYMBOL_FIX_Rule_Example = (
        "如下面範例中的科技新聞、手機方面。\n\n"
        "預期輸出範例風格："
        "一、科技新聞\n"
        "（一）手機方面：\n"
        "1、傳iPhone 17 Pro相機採橫條設計 保護殼開始生產： "
        "（中央社記者吳家豪台北21日電）蘋果公司預計今年下半年發表"
        "iPhone 17系列手機，隨著美國暫緩實施高額對等關稅、iPhone"
        "漲價疑慮減緩，最新消息傳出，高階機型iPhone 17 Pro將調整"
        "相機排列方式，改採橫條設計，配件商已開始生產保護殼，也讓新"
        "機設計細節曝光。\n"
        "2、知名大廠宣布退出手機市場！曾是全球前3品牌 經營31年走入歷史：\n"
        "過去曾在全球手機市場排名前3的韓國科技品牌「LG」，"
        "在2021年因為手機業務的持續虧損和激烈的市場競爭，"
        "宣布放棄智慧型手機業務，但依然為使用其手機的用戶提"
        "供軟體更新等服務。不過這段過渡期也將宣告結束，LG最近在官網公告，從今年6月30日起，將終止電子手機軟體升級及更新等服務。\n"
        "（二）筆電方面：\n"
        "1、關稅發威！Razer 在美暫停新機銷售，新創 Framework 嘆"
        "低階筆電虧本賣：\n"
        "Razer（雷蛇）發表全新電競筆電 Razer Blade 16，經"
        "過重新設計並搭載最新 NVIDIA GeForce RTX 50 系列"
        "顯示卡和最高 AMD Ryzen AI 9 HX 370 處理器，"
        "成為品牌成立以來最纖薄的 Blade 電競筆電。"
        "但現在 Razer Blade 16 及其他機型在美國官網"
        "暫時不提供預購或選購，又如正在宣傳的筆電支架"
        "新品 Razer Adjustable Laptop Stand，想在美"
        "國官網購買被迫等待通知，但在其他國家則能正常選購。\n"
        "-注意前面是範例而已，不要當成你的輸出。"
)

NESTED_STRUCTURE_Rule = (
        "目前有一份結構化文本因使用者操作錯誤、掃描瑕疵或轉檔問題，"
        "導致項目層級混亂、OCR 誤字與格式不正確，無法通過文本分析程式的解析。\n\n"
        "請你根據語意，在不改變原文內容的前提下，進行文本重要資訊結構化的動作，輸出巢狀結構如下：\n\n"
        '{"大範疇名稱A":{"子方面名稱a":["條目a-1","條目a-2","條目a-3"],'
        '"子方面名稱b":["條目b-1","條目b-2"]},'
        '"大範疇名稱B":{"子方面名稱c":["條目c-1"],...}'
        '}\n\n'
        "清除明顯的 OCR 雜訊、錯字與異常符號，並注意輸出巢狀JSON格式的正確性，"
        '嚴格遵守子方面名稱格式為"ＯＯ方面"，以及三層的巢狀結構，否則會導致後續其他程式分析失敗。\n\n'
        "僅輸出修正後的純文本，不需任何說明或補充。輸出時不要改變原來中文的簡繁體設定。"
)

ORGANIZATION_PROFILE_ANALYZER_Rule = """
請針對以下的組織名稱清單，逐筆產出對應的多欄位屬性資訊，格式為 **JSON 字典清單陣列**，每筆對應一個組織，請嚴格遵守以下格式與欄位規則：

- **語言要求**：所有內容請使用臺灣常用繁體中文。不得輸出簡體或英文說明。
- **格式要求**：最終輸出為 JSON 陣列（即以 `[` 開頭的多筆字典），不得附加任何說明或文字。
- **欄位說明如下（key : 說明與範例）**：

1. `"inputName"` : 原始輸入名稱，如 `"北市秘書處"`
2. `"formalName"` : 正式單位全名，例如 `"臺北市政府秘書處"`、`"美國駐西班牙大使館"`
3. `"functionalDomain"` : 功能領域，例如 `"行政管理與綜合協調"`
4. `"administrativeLevel"` : 行政層級與隸屬關係，例如 `"臺北市政府一級機關"`
5. `"parentUnit"` : 直屬上層單位名稱，如無合適值請填 `""`（空字串），直屬上層單位名稱欄位使用正式單位全名
6. `"administrativeDivision"` : 所屬行政區，例如 `"臺北市"`
7. `"address"` : 詳細地址，如不明請填 `""`
8. `"organizationType"` : 組織型態，請從下列選項中選一：
    - `中央政府`
    - `地方政府`
    - `國際組織`
    - `國營企業`
    - `民營企業`
    - `NGO`
    - `高端智庫`
    - `普通智庫`
    - `學術機構`
9. `"keyFunctions"` : 關鍵職能，使用字串陣列格式，例如：`["文書處理", "行政支援"]`
10. `"affiliatedNationOrRegion"` : 所屬國或地區（如涉國際），例如 `"中華民國（臺灣）"`
11. `"locatedCountryOrRegion"` : 實際所在國，例如 `"中華民國（臺灣）"`
12. `"affNationLangs"` : 所屬國官方語言，用字串陣列表示，如：`["中文"]` 或 `["中文", "英文"]`
13. `"description"` : 單位簡述，例如：`"臺北市政府秘書處負責市府文書、公文核稿及跨局處協調。"`

- **注意事項**：
    - 請勿輸出除 JSON 結構以外的任何說明文字。
    - 若無明確資料可填，請使用空字串 `""` 或空陣列 `[]`。
    - 若屬外交機構，請特別留意「中」字涵義（例如「中駐以使館」為「中華人民共和國」）。
"""

RAG_CHUNK_Rule = """\
擬針對LLM RAG(Retrieval-Augmented Generation)應用進行文本chunk切割，用於組建語意向量庫。為了優化檢索效果，切割時儘量保持段落的語意連結整體性，不要切在不適當的地方，避免切出太破碎過短的段落。並且在每一個切割出來的chunk前加上該段文字的出處標題及段落標題，以json輸出chunk的清單，不要有其他LLM的說明提詞。在語意主題聚合的前提下，單一chunk以400字左右為目標，儘量長。去除較不具特殊意涵的制式宣告或制式說明，如：版權宣告、免責宣告、資格聲明、評級標準、特别声明、投资评级。
chunk格式範例：{
"type":"RAG chunk",
"title":"1月PMI数据点评：我国经济继续保持平稳恢复态势",
"source":$消息出處$,
"background_date":"2021-1-1 00:00:00",
"event_date":"(2020-12-21 00:00:00,2021-1-1 00:00:00)",
"section":"拉闸限电制约企业生产",
"content": "1月生产指数为53.5%，环比回落0.7个百分点。采购量下降1.2%至52.0%，但产成品库存指数为49.0%，较上月回升2.8个百分点，原材料库存指数为49.0%，比上月回升0.4个百分点。库存分项均位于临界点下方，表明未来企业生产仍有一定空间。12月中下旬起，湖南、浙江、江西等省份由于气温偏低、年底赶工等导致生活、生产用电需求旺盛，部分地区开启“拉闸限电”。2021年春节较晚，部分地区也提倡就地过年，赶工可能还将持续一段时间，对生产数据造成一定扰动。",
"keywords":["企业生产","拉闸限电","库存指数"]}
定出全部段落合適的共用標題放在title，另外section則是各段的副標題。background_date為段落消息發布背景時間，event_date則為該切割段落內提及重要事件的時間，各chunk輸出時間可不同，使用之格式字串表示法為%Y-%m-%d %H:%M:%S，如果時間是一個範圍區間，則使用2維tuple表示該時間區間。另外提供3個重要關鍵字，由重要度高排到低存放於keywords。source則填入消息來源單位。各欄位如無合適值可填入，請填入空字串或空清單。
"""

RAG_CHUNK_LONG_EXAMPLE_Rule_UNUSED = """\
擬針對LLM RAG(Retrieval-Augmented Generation)應用進行文本chunk切割，用於組建語意向量庫。為了優化檢索效果，切割時儘量保持段落的語意連結整體性，不要切在不適當的地方，避免切出段落太破碎，條列式小點項目放在同一個chunk內。並且在每一個切割出來的chunk前加上該段文字的出處標題及段落標題，以json輸出chunk的清單，不要有其他LLM的說明提詞。在語意主題聚合的前提下，單一chunk以800字左右為目標，區塊長度儘量長，儘量不要漏掉有意義的段落，保持原有標號結構。另去除較不具特殊意涵的制式宣告或制式說明，如：版權宣告、免責宣告、資格聲明、評級標準、特别声明、投资评级；並去除廣告、娛樂新聞、運動新聞、星座文。
chunk格式範例：
[{
"type":"RAG chunk",
"title":"資訊安全管理系統政策文件",
"article_code":"ISMS-01000000",
"source":"內政部國土測繪中心",
"background_date":"2022-04-14 00:00:00",
"event_date":"",
"section":"版本資訊及機密等級",
"content": "內政部國土測繪中心\\n資訊安全管理系統政策文件\\n文件編號：ISMS-01000000\\n版 次：V2.95\\n文件日期：111年4月14日\\n機密等級：普通",
"keywords":["資訊安全管理系統政策文件","內政部國土測繪中心","機密等級"]},
{
"type":"RAG chunk",
"title":"資訊安全管理系統政策文件",
"article_code":"ISMS-01000000",
"source":"ISMS工作小組",
"background_date":"2010-04-16 00:00:00",
"event_date":"(2007-11-16 00:00:00,2009-12-19 00:00:00)",
"section":"文件制/修訂紀錄",
"content": "文件編號：ISMS-01000000 版次：V2.95\\n文件制/修訂紀錄\\n版次 日期 說明 作者備註\\nV1.0 961116 初版發行 ISMS工作小組\\nV2.0 971014 增列「角色及責任」、「人員審查」、「考核獎懲」及「資通安全教育訓練」等事項對應程序文件之說明並配合ISO17799及CNS17799之廢止與ISO27002及CNS27002 之訂頒，修正依據標準。 ISMS工作小組\\nV2.1 980213 依據程序文件名稱變更修訂。 ISMS工作小組\\nV2.2 1001013 修正ISMS目標及電腦機房名稱。 ISMS工作小組\\nV2.3 1031024 1.前言，增加考量組織全景內容。2.修正二~四階程序文件之核定，依100年11月8日簽奉核可知授權人員核定。 蔡汶諭\\nV2.4 1041014 文字修正：1.ISO27001標準要求事項第4節至第8節修正為第10節。2.一般要求修正內外部議題與關注方(interested  party)，以及法令、法規及義務之要求。3.事故修正為事件 蔡汶諭\\nV2.5 1060213 增加ISMS目標中的機房「電力及空調服務」，核心系統之可用性目標。 陳建男\\nV2.6 1061016 增加核心資訊系統等文字 陳建男",
"keywords":["文件制/修訂紀錄","ISMS"]},
{
"type":"RAG chunk",
"title":"1月PMI数据点评：我国经济继续保持平稳恢复态势",
"article_code":"",
"source":"",
"background_date":"2021-1-1 00:00:00",
"event_date":"(2020-12-21 00:00:00,2021-1-1 00:00:00)",
"section":"拉闸限电制约企业生产",
"content": "1月生产指数为53.5%，环比回落0.7个百分点。采购量下降1.2%至52.0%，但产成品库存指数为49.0%，较上月回升2.8个百分点，原材料库存指数为49.0%，比上月回升0.4个百分点。库存分项均位于临界点下方，表明未来企业生产仍有一定空间。12月中下旬起，湖南、浙江、江西等省份由于气温偏低、年底赶工等导致生活、生产用电需求旺盛，部分地区开启“拉闸限电”。2021年春节较晚，部分地区也提倡就地过年，赶工可能还将持续一段时间，对生产数据造成一定扰动。",
"keywords":["企业生产","拉闸限电","库存指数"]}
]
定出全部段落合適的共用標題放在title，另外section則是各段的副標題。background_date為段落消息發布背景時間，event_date則為該切割段落內提及重要事件的時間，各chunk輸出時間可不同，使用之格式字串表示法為%Y-%m-%d %H:%M:%S，如果時間是一個範圍區間，則使用2維tuple表示該時間區間。另外提供3個重要關鍵字，由重要度高排到低存放於keywords。source則填入消息來源單位。各欄位如無合適值可填入，請填入空字串或空清單。
"""
#For qwen2.5

RAG_CHUNK_LONG_EXAMPLE_Rule_UNUSED = """\
擬針對LLM RAG(Retrieval-Augmented Generation)應用進行文本chunk切割，用於組建語意向量庫。為了優化檢索效果，切割時儘量保持段落的語意連結整體性，不要切在不適當的地方，避免切出段落太破碎，條列式小點項目放在同一個chunk內。並且在每一個切割出來的chunk前加上該段文字的出處標題及段落標題，以json輸出chunk的清單，不要有其他LLM的說明提詞。在語意主題聚合的前提下，單一chunk以800字左右為目標，區塊長度儘量長，儘量不要漏掉有意義的段落，保持原有標號結構。另去除版權宣告、免責宣告、資格聲明、評級標準、特别声明、投资评级、廣告、娛樂新聞、運動新聞、星座文。
chunk格式範例：
[{
"type":"RAG chunk",
"title":"資訊安全管理系統政策文件",
"article_code":"ISMS-01000000",
"source":"內政部國土測繪中心",
"background_date":"2022-04-14 00:00:00",
"event_date":"",
"section":"版本資訊及機密等級",
"content": "內政部國土測繪中心\\n資訊安全管理系統政策文件\\n文件編號：ISMS-01000000\\n版 次：V2.95\\n文件日期：111年4月14日\\n機密等級：普通",
"keywords":["資訊安全管理系統政策文件","內政部國土測繪中心","機密等級"]},
{
"type": "RAG chunk",
"title": "民法第208條至第213條",
"article_code": "Civil_Law",
"source": "",
"background_date": "1999-01-01 00:00:00",
"event_date": "",
"section": "選擇權與債之效力",
"content": "事人以書面約定，利息遲付逾一年後，經催告而不償還時，債權人得將遲付之利息滾入原本者，依其約定。\n前項規定，如商業上另有習慣者，不適用之。\n第 208 條\n於數宗給付中得選定其一者，其選擇權屬於債務人。但法律另有規定或契約另有訂定者，不在此限。\n第 209 條\n債權人或債務人有選擇權者，應向他方當事人以意思表示為之。\n由第三人為選擇者，應向債權人及債務人以意思表示為之。\n第 210 條\n選擇權定有行使期間者，如於該期間內不行使時，其選擇權移屬於他方當事人。\n選擇權未定有行使期間者，債權至清償期時，無選擇權之當事人，得定相當期限催告他方當事人行使其選擇權，如他方當事人不於所定期限內行使選擇權者，其選擇權移屬於為催告之當事人。\n由第三人為選擇者，如第三人不能或不欲選擇時，選擇權屬於債務人。\n第 211 條\n數宗給付中，有自始不能或嗣後不能給付者，債之關係僅存在於餘存之給付。但其不能之事由，應由無選擇權之當事人負責者，不在此限。\n第 212 條\n選擇之效力，溯及於債之發生時。\n第 213 條\n負損害賠償責任者，除法律另有規定或契約另有訂定外，應回復他方損害發生前之原狀。",
"keywords": ["選擇權", "債之效力", "損害賠償"]
},
{
"type":"RAG chunk",
"title":"1月PMI数据点评：我国经济继续保持平稳恢复态势",
"article_code":"ISMS-01000000",
"source":"",
"background_date":"2021-1-1 00:00:00",
"event_date":"(2020-12-21 00:00:00,2021-1-1 00:00:00)",
"section":"拉闸限电制约企业生产",
"content": "1月生产指数为53.5%，环比回落0.7个百分点。采购量下降1.2%至52.0%，但产成品库存指数为49.0%，较上月回升2.8个百分点，原材料库存指数为49.0%，比上月回升0.4个百分点。库存分项均位于临界点下方，表明未来企业生产仍有一定空间。12月中下旬起，湖南、浙江、江西等省份由于气温偏低、年底赶工等导致生活、生产用电需求旺盛，部分地区开启“拉闸限电”。2021年春节较晚，部分地区也提倡就地过年，赶工可能还将持续一段时间，对生产数据造成一定扰动。",
"keywords":["企业生产","拉闸限电","库存指数"]}
]
定出全部段落合適的共用標題放在title，另外section則是各段的副標題。background_date為段落消息發布背景時間，event_date則為該切割段落內提及重要事件的時間，各chunk輸出時間可不同，使用之格式字串表示法為%Y-%m-%d %H:%M:%S，如果時間是一個範圍區間，則使用2維tuple表示該時間區間。另外提供3個重要關鍵字，由重要度高排到低存放於keywords。article_code填入文件編號。source則填入消息來源單位。各欄位如無合適值可填入，請填入空字串或空清單。
"""

RAG_CHUNK_LONG_EXAMPLE_Rule = """\
請針對一份用於 LLM RAG（Retrieval-Augmented Generation）系統的中文長文本進行段落切割與語意聚合處理，用於建立語意向量資料庫。

請依照以下規則進行文本處理：

1. 切割規則：
- 保持段落的語意連貫性，避免將語句切斷在語意尚未結束處。
- 條列式項目（如 1.、2.、(一)、(二)）應視為一組，合併為同一個 chunk。
- 儘量避免產生過小、破碎的段落。
- 在語意主題一致的前提下，單一 chunk 目標長度為約 800 字，允許視情況略長。
- 每個 chunk 請保留原始的標號格式與結構（例如條文、章節編號）。

2. 篩選處理：
- 請移除以下無資訊價值之段落：版權宣告、免責聲明、資格聲明、評級標準、特別聲明、投資建議、廣告、娛樂新聞、運動新聞、星座文。

3. Chunk metadata 組成：
每個 chunk 請以 JSON 格式輸出，包含以下欄位：
- `"type"`：固定為 `"RAG chunk"`。
- `"title"`：本份文件的主標題（如為法律條文或文章統一名稱）。
- `"article_code"`：文件編號（無則填空字串）。
- `"source"`：消息來源單位（無則填空字串）。
- `"background_date"`：該段落的發布或背景時間，格式為 `%Y-%m-%d %H:%M:%S`。
- `"event_date"`：若該段落中提及特定事件，請填入事件發生時間，若為區間，請使用 tuple 格式表示（例：`("2024-05-01 00:00:00", "2024-05-07 00:00:00")`），若無則填空字串。
- `"section"`：該段落的副標題或小標題。
- `"content"`：該 chunk 的完整內文。
- `"keywords"`：根據內容摘要整理出3個最重要的關鍵字，依重要程度由高到低排列。

4. 請僅輸出 JSON 陣列結果，不要額外解釋或說明。

---

📌 JSON 輸出格式範例如下：
[
  {
    "type": "RAG chunk",
    "title": "民法第208條至第213條",
    "article_code": "Civil_Law",
    "source": "",
    "background_date": "1999-01-01 00:00:00",
    "event_date": "",
    "section": "選擇權與債之效力",
    "content": "...",
    "keywords": ["選擇權", "債之效力", "損害賠償"]
  },
  ...
]
"""

UNUSED_EXAMPLE = [
'''
{
"type":"RAG chunk",
"title":"資訊安全管理系統政策文件",
"article_code":"ISMS-01000000",
"source":"ISMS工作小組",
"background_date":"2010-04-16 00:00:00",
"event_date":"(2007-11-16 00:00:00,2009-12-19 00:00:00)",
"section":"文件制/修訂紀錄",
"content": "文件編號：ISMS-01000000 版次：V2.95\\n文件制/修訂紀錄\\n版次 日期 說明 作者備註\\nV1.0 961116 初版發行 ISMS工作小組\\nV2.0 971014 增列「角色及責任」、「人員審查」、「考核獎懲」及「資通安全教育訓練」等事項對應程序文件之說明並配合ISO17799及CNS17799之廢止與ISO27002及CNS27002 之訂頒，修正依據標準。 ISMS工作小組\\nV2.1 980213 依據程序文件名稱變更修訂。 ISMS工作小組\\nV2.2 1001013 修正ISMS目標及電腦機房名稱。 ISMS工作小組\\nV2.3 1031024 1.前言，增加考量組織全景內容。2.修正二~四階程序文件之核定，依100年11月8日簽奉核可知授權人員核定。 蔡汶諭\\nV2.4 1041014 文字修正：1.ISO27001標準要求事項第4節至第8節修正為第10節。2.一般要求修正內外部議題與關注方(interested  party)，以及法令、法規及義務之要求。3.事故修正為事件 蔡汶諭\\nV2.5 1060213 增加ISMS目標中的機房「電力及空調服務」，核心系統之可用性目標。 陳建男\\nV2.6 1061016 增加核心資訊系統等文字 陳建男",
"keywords":["文件制/修訂紀錄","ISMS"]},
''',
]


'''
#如果沒有段落符合的話，回答"無符合風險關注指標的內容"。
RISK_INDICATOR_EXTRACTION_RULE = """\
請抽取輸入任務文本中，符合風險關注指標的內容段落，抽取風格以嚴謹明確符合為準。只要輸出答案文字就好，不要有其他額外說明。以繁體中文回答。如果沒有段落符合的話，回答"無符合風險關注指標的內容"。
"""
'''
#如果沒有段落符合的話，回答空字串。
RISK_INDICATOR_EXTRACTION_RULE = """\
請抽取輸入任務文本中，符合風險關注指標的內容段落，抽取風格以嚴謹明確符合為準。只要輸出答案文字就好，不要有其他額外說明。以繁體中文回答。如果沒有段落符合的話，僅返回：<EMPTY>。
"""

RISK_LEVEL_ASSESSMENT_RULE = (
    "你是一位股市風險趨勢分析專家，專責追蹤並評估各國針對臺灣可能產生的風險變化。\n"
    "面對川普發起的關稅戰，請根據下列規則，研判輸入任務文本所對應的風險等級：\n\n"

    "📌 任務 1：風險等級分析與思考過程\n"
    "請依照提供的「風險等級與說明」，判斷輸入任務文本所屬的風險等級，並以繁體中文清楚詳列你的思考步驟：\n"
    "- 檢視「風險等級與說明」中各級的條件定義\n"
    "- 比對輸入任務文本是否明確符合其中任一條件\n"
    "- 分析過程中不可主觀臆測，僅能根據文字資訊做出判斷\n"
    "- 若符合多個等級，以最高風險等級為主\n"
    "- 符合其中一項條件即可歸為該等級\n\n"

    "📌 任務 2：風險等級判定與簡要說明\n"
    "根據你的分析結果，請回傳以下內容：\n"
    "- 「風險等級評估」：整數（例如 1、2、3），數值越高代表風險越高\n"
    "- 「簡要說明」：摘要說明為何歸類為該等級\n\n"

    "📌 任務 3：僅回傳標準 JSON 結果\n"
    "請根據任務1與任務2的內容以及輸入任務文本極短單句摘要，以 JSON 陣列格式回傳結果。\n"
    "只回傳 JSON，**不得添加其他說明文字**，以確保自動化系統能正確解析。\n"
    "格式範例如下：\n\n"
    "[{\n"
    "  \"思考過程\": \"1. **理解風險等級與說明**：\\n"
    "     - 等級 3：日本產品關稅全面比臺灣低10%。\\n"
    "     - 等級 2：日本電子產品關稅比臺灣低10%。\\n"
    "     - 等級 1：日本產品關稅與臺灣相同。\\n\\n"
    "  2. **分析輸入任務文本**：\\n"
    "     - 文本提到美國總統川普宣布對等關稅，影響台灣機械出口值的增長，並表示與日韓競爭差距將擴大。\\n"
    "     - 具體的關稅數字和比較未在文本中明確說明，無法直接判斷日本產品關稅是否比臺灣低10%或全面低10%。\\n\\n"
    "  3. **判斷風險等級**：\\n"
    "     - 由於文本未提供具體關稅數據，僅提到競爭差距擴大，這表明存在一定的競爭壓力，但不符合等級2和等級3的明確標準。\\n"
    "     - 文本未說明日本產品關稅與臺灣相同的情況，因此也不符合等級1。\\n\\n"
    "  4. **補充說明**：\\n"
    "     - 考慮到文本僅提到競爭差距擴大而無具體數據支持更高風險等級，根據提供的風險等級標準和任務要求，選擇最低的風險等級1。\",\n"
    "  \"風險等級評估\": 1,\n"
    "  \"簡要說明\": \"文本未提供具體關稅數據，僅提到與日韓競爭差距擴大，但不符合任何高風險等級標準，因此判斷為風險等級1。\"\n"
    "  \"輸入任務文本極短單句摘要\": \"對等關稅恐加劇台灣與日韓競爭差距。\"\n"
    "}]\n"
)



CONTACT_INFORMATION_Rule = (
    "聯絡資訊輸出格式範例如下：\n"
    "{\n"
    "\"type\":\"Contact Information\",\n"
    "\"unit\":,\n"
    "\"address\":,\n"
    "\"POST Code\":,\n"
    "\"TEL\":,\n"
    "\"FAX\":\n"
    "}\n"
    )
"""
聯絡資訊輸出格式範例如下：
{
"type":"Contact Information",
"unit":,
"address":,
"POST Code":,
"TEL":,
"FAX":
}
"""

TENDER_INFORMATION_Rule = """\
請針對提供的輸入採購文件進行結構化處理，輸出json格式結果，範例如下：
☆範例之輸入採購文件：
我部对“气象海洋联合保障业务共享平台”国产化采购项目进行了公开招标采购，现就供应商评审结果公示如下：
一、项目名称：“气象海洋联合保障业务共享平台”国产化项目
二、项目编号：2024-ZAXXDD-F1010
三、公示期限：2024年12月25日至2024年12月27日
四、评审结果：
采购包（1）：因因有效投标供应商数量未能满足至少三家的开标条件，本项目此次招标按流标处理，项目废标
供应商对评审结果如有异议，应当自本公示期限内以书面形式向我部提出质疑。对积极参与本次采购活动的供应商深表感谢，希望今后继续保持合作。
五、采购单位联系方式
联 系 人：朱先生
联系电话：18951017527
地 址：江苏省 南京市
六、代理机构联系方式
单位名称：江苏建科工程咨询有限公司
联 系 人：繆工
联系电话：18261451513
邮 箱：1034187038@qq.com
地 址：江苏省 南京市
详细地址：南京市嘉陵江东街18号6栋13、14层
七、纪检监督联系方式
联 系 人：张先生
联系电话：15121002837

☆範例之輸出結果：
[
{
"project_name":"“气象海洋联合保障业务共享平台”国产化项目",
"project_site":[],
"project_no":"2024-ZAXXDD-F1010",
"project_budget":null,
"project_item_type":"气象",
"project_item_details":"",
"public_notice_period":[[2024,12,25],[2024,12,27]],
"evaluation_state":"failed tender",
"winning_bidder":[],
"successful_bid_price":null,
"procurement_unit_name":"某部",
"procurement_unit_contact_person":["朱先生"],
"procurement_unit_contact_tel":["18951017527"],
"procurement_unit_contact_email":null,
"procurement_unit_contact_address":["江苏省南京市"],
"agency_unit_name":"江苏建科工程咨询有限公司",
"agency_unit_contact_person":["繆工"],
"agency_unit_contact_tel":["18261451513"],
"agency_unit_contact_email":["1034187038@qq.com"],
"agency_unit_contact_address":["江苏省南京市嘉陵江东街18号6栋13、14层"],
"disciplinary_inspection_person":["张先生"],
"disciplinary_inspection_tel":["15121002837]"
}
]
進一步說明特定鍵值的意義，
1.project_site表示項目施作地點或交貨地點,
2.public_notice_period表招標期間或投標文件繳交期間,
3.evaluation_result的值為"successful tender"(決標)或"failed tender"(流標)或"intent survey"(意向調查)或"tender initiation"(啓動招標)
4.winning_bidder填入得標者名稱,successful_bid_price填入得標報價,
5.project_budget表示採購項目總預算金額,注意表格內數值所使用的單位,如果單位是萬元,記得轉換為正確數值再填入。
6.project_item_type表示採購項目所屬領域類別,
7.project_item_details表示採購物件子項目，以字串格式條列簡要說明。
8.如果沒有抓到合適的值，則填入null。
9.聯絡資訊的person,tel,email,address等欄位為清單格式，依順序一一配對，如為共用，則進行冗餘條列，以達到各清單間一一對應關係。
"""

taskSetting_ANKInt = {
    "PDF OPT":{
        "CT_name":"PDF抽取文本優化",
        "InputCutLen":3600,
        #這並未進行DeepSeek API快取優化。
        "template":lambda MainFileName,content:(
            f"{content}\n\n"
            f"上文為網路爬蟲或pdf掃瞄得到的文本切片，主檔名為「{MainFileName}」，請進行下列清整：\n"
            f"{PDF_OPT_Rule}"
            )
    },
    "PDF OPT-Instruction First":{
        "CT_name":"PDF抽取文本優化-指令在前",
        "InputCutLen":3600,
        #已進行DeepSeek API快取優化。
        "template":lambda MainFileName,content:(
            f"下方輸入任務文本為網路爬蟲或pdf掃瞄得到的文本切片，請進行下列清整：\n"
            f"{PDF_OPT_Rule}\n"
            "主檔名為「{MainFileName}」，"
            "☆下列為輸入任務文本：\n"
            f"{content}"
            )
    },
    "CLASS EXT":{
        "CT_name":"特定類別文本抽取-指令在前",
        "InputCutLen":3600,
        "template":lambda textClass,content:(
            f"下方輸入任務文本為網路爬蟲或pdf掃瞄得到的文本切片，請依下列原則抽出符合目標類別的文字段落：\n"
            f"{CLASS_EXT_Rule}\n"
            f"要抽出的文字目標類別為「{textClass}」，"
            "☆下列為輸入任務文本：\n"
            f"{content}"
            ),
        "recommend_model":["qwen2.5-16k","qwen2.5-32k"],
    },
    "CLASS Diff EXT":{
        "CT_name":"特定類別差集文本抽取",
        "InputCutLen":3600,
        "template":lambda textClass,exclusiveTextClass,content:(
            f"下方輸入任務文本為網路爬蟲或pdf掃瞄得到的文本切片，要抽出的文字目標類別為「{textClass}」，但是不屬於「{exclusiveTextClass}」，請依下列原則抽出符合前述的類別差集的文字段落："
            f"{CLASS_EXT_Rule}\n"
            "☆下列為輸入任務文本：\n"
            f"{content}"
            )
    },
    "Details EXT and Translation-toTWZH":{
        "CT_name":"抽取主文，並翻譯為繁體中文",
        "InputCutLen":2500, #sample:(Input EN 2703-> TWZH 4101)
        "template":lambda content:(
            "請依下列清整原則，取出下方輸入任務文本的主文區塊，並使用臺灣習慣用語翻譯取出文本為繁體中文。\n"
            f"{DETAIL_EXT_TRANS_Rule}"
            "☆下列為輸入任務文本：\n"
            f"{content}"
            )
    },
    "Email Extraction to json format": {
        "CT_name": "拆解詐騙電郵為獨立 JSON 物件，保留關鍵欄位資訊",
        "InputCutLen": 3000,  # 可依實測調整
        "template": lambda content: (
            "你將接收到一份包含多封電郵的大型純文字檔，請根據每封電郵的標頭與內文，將所有電郵資訊拆解為一筆筆獨立的 JSON 物件，並以陣列形式回傳。每筆電郵只需保留以下欄位：\n"
            "\"From\"：寄件者\n"
            "\"To\"：收件者\n"
            "\"Subject\"：郵件標題\n"
            "\"Content\"：郵件主文（從問候語起至結尾的信件內容）\n"
            "輸出只需提供純 JSON 陣列，不要包含任何說明、格式標註或多餘文字。若欄位缺失，請填入空字串。\n\n"
            "☆下列為輸入任務文本：\n"
            f"{content}"
        )
    },
    "json format Repair": {
        "CT_name": "",
        "InputCutLen": 3600,
        "template": lambda content: (
            "請檢查下列 JSON 格式字串是否為合法 JSON。若無法被成功解析，"
            "請修正語法錯誤並僅回傳**修正後的 JSON 字串本體**，"
            "注意不要變更中文內容的簡繁體，"
            "不需要說明與註解，以便程式自動化串接使用。"
            "☆下列為輸入任務文本：\n"
            f"{content}"
        )
    },
    "MDT Term Extraction to json format":{
        "CT_name":"萃取軍事、外交、科技、政治、經濟、社會、機關單位詞彙並進行深入補充（enrichment），最後輸出為 JSON 格式",
        "InputCutLen":100,
        "template":lambda MainFileName,content:(
            f"{MDT_EXTRACTION_Rule}"
            f"主檔名為「{removeStrSuffix(MainFileName,'_tika')}」，可用於輔助分析article_title。\n"
            "☆下列為輸入任務文本："
            f"{content}"
            )
    },
    "Nested Symbol Fix": {
        "CT_name": "修正不規則項目符號並還原層級結構，輸出為乾淨分層純文字",
        "InputCutLen": 2500,
        "template": lambda content: (
            "請依據下列規則修正文稿，輸出純淨處理結果以供後續自動化程式使用：\n"
            f"{NESTED_SYMBOL_FIX_Rule}"
            "☆下列為輸入任務文本：\n"
            f"{content}"
        )
    },
    "Nested Structure to json format": {
        "CT_name": "分析輸入文本，輸出結構化巢狀結構",
        "InputCutLen": 2500,
        "template": lambda content: (
            "請依據下列規則分析輸入文本，輸出結構化巢狀結構，以供後續自動化程式使用：\n"
            f"{NESTED_STRUCTURE_Rule}"
            "☆下列為輸入任務文本：\n"
            f"{content}"
        )
    },
    "Organization Profile Analyzer to json format":{
        "CT_name":"分析輸入組織名稱，新增多維屬性，輸出為json格式",
        "InputCutLen":1000,
        "template":lambda content:(
            f"{ORGANIZATION_PROFILE_ANALYZER_Rule}"
            "☆組織名稱列表："
            f"{content}"
            )
    },
    "QA":{
        "CT_name":"問題回答",
        "InputCutLen":100*1000,
        "template":lambda content:(
            f"{content}"
            )
    },
    "RAG Chunk to json format":{
        "CT_name":"切割為RAG Chunk，並抽取元數據，輸出為json格式",
        "InputCutLen":2800,
        #已進行DeepSeek API快取優化。
        "template":lambda MainFileName,content:(
            f"{RAG_CHUNK_Rule}"
            f"主檔名為「{removeStrSuffix(MainFileName,'_tika')}」。\n"
            "☆下列為輸入任務文本："
            f"{content}"
            )
    },
    "RAG Chunk with long example to json format":{
        "CT_name":"切割為RAG Chunk，並抽取元數據，輸出為json格式，prompt使用長範例。",
        "InputCutLen":2400,
        #已進行DeepSeek API快取優化。
        "template":lambda MainFileName,content:(
            f"{RAG_CHUNK_LONG_EXAMPLE_Rule}"
            f"主檔名為「{removeStrSuffix(MainFileName,'_tika')}」。\n"
            "☆下列為輸入任務文本："
            f"{content}"
            "\n回答時請以json輸出chunk的清單，chunk數量無限制，不要有其他LLM的說明提詞。"
            )
    },
    "RAG Chunk and Contact Information to json format":{
        "CT_name":"切割為RAG Chunk，並抽取聯絡資訊，輸出為json格式",
        "InputCutLen":2500,
        #已進行DeepSeek API快取優化。
        "template":lambda MainFileName,content:(
            f"{RAG_CHUNK_Rule}"
            "另外一併抽取出現的聯絡資訊，與RAG chunk放在同一個清單，"
            "沒有聯絡資訊的話，就略過此部份。"
            f"{CONTACT_INFORMATION_Rule}"
            f"主檔名為「{removeStrSuffix(MainFileName,'_tika')}」。\n"
            "☆下列為輸入任務文本："
            f"{content}"
            )
    },
    "Risk Indicator Extraction":{
        "CT_name":"萃取輸入任務文本符合風險關注指標的內容",
        "InputCutLen":2500,
        "template":lambda keyConsiderations,content:(
            f"{RISK_INDICATOR_EXTRACTION_RULE}"
            f"風險關注指標為「{keyConsiderations}」。\n"
            "☆下列為輸入任務文本："
            f"{content}"
            )
    },
    "Risk Level Assessment to json format": {
        "CT_name": "評估輸入任務文本所揭示的風險事件嚴重程度等級",
        "InputCutLen": 2500,
        "template": lambda keyConsiderations, content: (
            f"{RISK_LEVEL_ASSESSMENT_RULE}"
            f"「風險等級與說明」為「{keyConsiderations}」。\n"
            "☆下列為輸入任務文本："
            f"{content}"
        )
    },
    "Summary-toTWZH":{
        "CT_name":"以繁體中文摘要",
        "InputCutLen":100*1000, #sample:(Input EN 2703-> TWZH 4101)
        "template":lambda content:(
            "請使用臺灣習慣用語及繁體中文摘要下列輸入任務文本，回應不要有LLM回答的前置提示詞或額外說明。\n\n"
            "☆下列為輸入任務文本：\n"
            f"{content}"
            )
    },
    "Translation-toTWZH":{
        "CT_name":"翻譯為繁體中文",
        "InputCutLen":2500, #sample:(Input EN 2703-> TWZH 4101)
        "template":lambda content:(
            "請使用臺灣習慣用語翻譯下列輸入任務文本為繁體中文，回應不要有LLM回答的前置提示詞或額外說明。\n\n"
            "☆下列為輸入任務文本：\n"
            f"{content}"
            )
    },
    "Translation-toTWZH@Proceeding":{
        "CT_name":"論文集翻譯為繁體中文",
        "InputCutLen":2500, #sample:(Input EN 2703-> TWZH 4101)
        "template":lambda content:(
            "以下文本為論文集Proceeding的分割段落，請使用臺灣習慣用語翻譯下列輸入任務文本為繁體中文，回應不要有LLM回答的前置提示詞或額外說明。另外，以偵測論文主要標題的方法來判斷是否有碰到連續兩篇不同論文的交界處，如果有碰到不同論文交界處，則加入=====論文分隔線=====，以利後續的自動化程式將整本論文集分存為各篇論文。如果沒碰到明確交界處就不要亂加分隔字串，只有論文主文的標題才算，不要把參考文獻的標題誤判為主文標題。\n"
            "☆下列為輸入任務文本：\n"
            f"{content}"
            )
    },
    "Translation-toEN":{
        "CT_name":"翻譯為英文",
        "InputCutLen":2900, #sample:(Input EN 2703-> TWZH 4101)
        "template":lambda content:(
            f"請翻譯下列輸入任務文本為英文，回應不要有LLM回答的前置提示詞或額外說明。\n\n"
            "☆下列為輸入任務文本：\n"
            f"{content}"
            )
    },
    "Tender Information to json format":{
        "CT_name":"結構化招標資訊",
        "InputCutLen":3000,
        #已進行DeepSeek API快取優化。
        "template":lambda MainFileName,content:(
            f"{TENDER_INFORMATION_Rule}"
            f"主檔名為「{removeStrSuffix(MainFileName,'_tika')}」。\n"
            "☆下列為輸入任務文本："
            f"{content}"
            "\n回答時以json輸出chunk的清單，不要有其他LLM的說明提詞。"
            )
    },
}