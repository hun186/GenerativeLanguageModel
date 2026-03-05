from utils.utilities import removeStrSuffix

MENU_ANALYSIS_Rule = """
【輸出硬限制】
- 只能輸出 JSON（不得輸出任何額外文字、Markdown、註解或前後綴）。
- JSON 根節點必須是陣列 []，且陣列長度必須 = 1（用於我的平行切片框架合併）。
- 陣列內物件必須包含頂層鍵值（不可缺欄位）：
  meta、unit_conversions、ingredients、dishes、inventory、prices、example_constraints、errors
- 必須成功產出：
  dishes 長度 >= 1、ingredients 長度 >= 1、且每一筆 dish.ingredients 長度 >= 1（qty 允許為 null，但 ingredient_id 不可缺）。
- 禁止出現「省略/略/omitted/for brevity/...」等字樣。

────────────────────────────────────────
一、核心目標（重要）：把「單日總量」轉成「每人份量」
你輸入的「數量/訂貨數量」是單天需求總量。建立菜單資料庫時，dish.ingredients.qty 必須是「每人份量」。

- 先取得當天預估用餐人數 people_est：
  1) 優先抓「今日用餐人數」附近或獨立一行的「xxx人」（如 280人、270-280人）
     - 若是區間（270-280人）取平均 275
  2) 若找不到，再用「計數器 xxx」作為 people_est
  3) 若仍找不到：people_est = 230（預設值）
     - 並在 errors 記錄 type="people_est_defaulted"，message="No people count found; default to 230"
     - 同時在 meta.parse_profile.people_estimation.default_value 填 230，並在 source_note 註記已套用預設人數

- 對每一筆食材列先算「單日總量（換算到 base unit）」total_base，再算每人份量：
  per_person_qty = total_base / people_est
  - 建議四捨五入到小數點 4 位
  - 若 people_est=null，per_person_qty=null，但仍要把 ingredient_id 掛進 dish.ingredients（避免成份為空）

────────────────────────────────────────
二、base unit 與換算（固定規格）
【base_units 固定】
- ["g","ml","piece"]

【unit_conversions（固定輸出 5 筆，務必含斤）】
- kg→g(1000), L→ml(1000), tbsp→ml(15), tsp→ml(5), 斤→g(600)
- 格式範例：{ "from_unit": "kg", "to_unit": "g", "factor": 1000 }

【piece 類單位（視為 piece）】
- 個/粒/顆/包/桶/罐/箱/瓶/板/盒/件/條/根

【total_base 如何取得（用於 per_person_qty）】
- 優先用「訂貨數量 + 訂貨單位」
- 若缺「訂貨數量」，才退回用「數量」
- 斤：total_base = qty_source * 600，unit_base="g"
- piece 類：total_base = qty_source，unit_base="piece"
- 若單位缺失或無法辨識：unit_base="piece"，total_base=null，errors(type="unknown_unit")

────────────────────────────────────────
三、日期/價格日期（price_date）推斷
- 從日標題抓 ROC 日期，例如「115年 1月 06日」=> ISO 2026-01-06（西元=ROC+1911）
- 若抓不到日期，price_date=null 並 errors(type="missing_price_date")

────────────────────────────────────────
四、食材對齊（alias + 既有 id + deterministic id）
【alias_map（先套別名再找 id）】
- 蛋 / 洗選蛋 → 雞蛋
- 去皮洋蔥 → 洋蔥
- 牛番茄 → 番茄
- 冷凍玉米粒 → 玉米粒
- 生香菇 → 香菇
- 雪白菇 → 鴻喜菇
- 4.3豆腐 / 豆腐 → 板豆腐
- 芥花油 / 沙拉油 → 食用油
- 棒腿 / 去骨雞腿丁3*3 → 雞腿肉

【常用 ingredients id（對到就沿用）】
- 洋蔥 ing_onion；蒜頭 ing_garlic；薑 ing_ginger；青蔥 ing_scallion
- 醬油 ing_soy_sauce；蠔油 ing_oyster_sauce；香油 ing_sesame_oil；食用油 ing_cooking_oil；鹽 ing_salt；糖 ing_sugar；味噌 ing_miso；高湯 ing_chicken_stock
- 高麗菜 ing_cabbage；青江菜 ing_bokchoy；菠菜 ing_spinach；花椰菜 ing_broccoli；茄子 ing_eggplant；番茄 ing_tomato；玉米粒 ing_corn；香菇 ing_shiitake；鴻喜菇 ing_mushroom
- 雞蛋 ing_egg；板豆腐 ing_tofu
- 雞腿肉 ing_chicken_thigh；雞胸肉 ing_chicken_breast；豬梅花 ing_pork_shoulder；五花肉 ing_pork_belly；牛肉片 ing_beef_slice；吳郭魚片 ing_fish_tilapia；鮭魚 ing_fish_salmon；蝦仁 ing_shrimp
- 蘋果 ing_apple；香蕉 ing_banana；柳丁 ing_orange
- 若遇到未列出者（如 油菜、豆芽菜、臭豆腐、鴨血、紅蘿蔔 等）：視為新食材，用 deterministic id 生成

【deterministic id（避免平行切片撞號）】
- normalize_zh：去空白；全半形統一；（）()【】[]/+-*改成底線；連續底線壓成一個
- 未知食材：id = "ing_" + normalize_zh(食材名)
- 未知菜色：id = "dish_" + role + "_" + normalize_zh(菜名)

────────────────────────────────────────
五、ingredients.category / protein_group / default_unit 推斷（貼近舊資料集）
- category 只允許：grain / vegetable / seasoning / soy / egg / meat / seafood / fruit / other
- protein_group 只在 category=meat 或 seafood 時填：chicken / pork / beef / fish / seafood；其他一律 null
- default_unit 建議填 base unit（g/ml/piece）；推不出則 null

推斷順序（命中即停）：
(1) 若已對到既有 id（上方清單），直接套用該 id 的 category/protein_group/default_unit
(2) 否則用名稱關鍵字：
- fruit：香蕉/柳丁/蘋果/奇異果/葡萄/鳳梨/西瓜/木瓜/哈密瓜/芭樂/火龍果/芒果/草莓/藍莓/檸檬/柚子/梨/桃/李/櫻桃…
- egg：雞蛋/蛋/鴨蛋/鹹蛋/皮蛋/蛋液/蛋白/蛋黃…
- soy：豆腐/豆干/豆皮/豆包/素肚/素雞/豆漿/黃豆/毛豆…
- seafood（fish）：魚/魚片/吳郭魚/鯛魚/鮭魚/鱈魚/鯖魚/秋刀魚/虱目魚…
- seafood（seafood）：蝦/蝦仁/花枝/透抽/魷魚/章魚/貝/蛤/蚵/牡蠣/蟹/魚板/蟹棒…
- meat（chicken）：雞腿/雞胸/雞翅/雞排/雞塊/雞卷/雞肉…
- meat（pork）：豬/里肌/梅花/五花/排骨/絞肉/肉絲/肉片…
- meat（beef）：牛/牛肉/牛腱/牛腩/牛排/牛肉片/牛絞肉…
- grain：米/白米/五穀米/糙米/燕麥/麥/麵/麵條/烏龍麵/麵線/螺旋麵/吐司/厚片/麵粉/地瓜粉/太白粉/玉米粉…
- seasoning：醬油/蠔油/沙茶/豆瓣/番茄醬/番茄糊/辣椒醬/醋/糖/鹽/胡椒/胡椒鹽/味素/味噌/咖哩粉/紅椒粉/滷包/高湯/米酒/香油/麻油/芥花油/沙拉油/橄欖油…
- vegetable：其餘多數生鮮蔬菜；並沿用舊資料集：菇類（香菇/鴻喜菇/杏鮑菇…）歸 vegetable
- other：加工成品或無法可靠分類（大烹堡、小籠包、鍋貼、飲料…）

default_unit 推斷：
- 若 unit_base 能推得：g => "g"；ml => "ml"；piece => "piece"
- 推不出：null

────────────────────────────────────────
六、區塊辨識（role 對齊你的 schema）
- 菜名(主) => role="main"
- 菜名(配1)、菜名(配2)、青菜 => role="side"
- 湯品 => role="soup"
- 水果 => role="fruit"
- 雜貨、週三麵食 => 不產生 dishes（避免 role 不相容），但可產生 ingredients/prices，並在 errors 註記來源區塊。

────────────────────────────────────────
七、最重要：菜名/成份判斷（解決合併儲存格被吃掉）
在「菜名(主/配1/配2)/湯品」區塊內，以『列』為單位解析並維持 current_dish_name：

【規則A：新菜名列（同列有菜名+食材）】
- 若該列在遇到第一個數字之前出現「至少 2 段文字」：
  第1段=dish_name（設定 current_dish_name），第2段=ingredient_name（此 dish 第一個成份）

【規則B：延續成份列（禁止誤判成新菜名）】
- 若該列在遇到第一個數字之前只有「1 段文字」：
  此文字必定是 ingredient_name（沿用 current_dish_name），禁止當新 dish_name

【規則C：重置時機】
- 只有遇到『下一個區塊標題』或『合 計/總 計』才重置 current_dish_name。

【規則D：孤兒成份列】
- 若符合規則B但 current_dish_name 不存在：寫入 errors(type="orphan_ingredient_row")，但仍繼續解析。

【雜訊列】
- 合 計 / 總 計 / 0 / 單獨數字不得當食材，寫入 errors(type="unparsed_row")。

【青菜 水果 區塊特殊規則（本區塊通常不會出現菜名欄）】
- 觸發條件：遇到區塊標題包含「青菜 水果」（或類似：青菜水果、青菜/水果）。
- 在此區塊內，每一列都視為一個獨立菜色，不使用 current_dish_name，也不套用規則A/B。
- item_name 同時也是 dish_name；該 dish 只有 1 個成份：ingredient_name=item_name
- role：常見水果 => fruit；其他 => side
- 本區塊內資料列不得產生 orphan_ingredient_row；解析不到才用 unparsed_row。

────────────────────────────────────────
八、dishes 欄位（除舊欄位外，允許補強；舊欄位不可少）
每一筆 dish 必須包含（必填）：
- id, name, role, cuisine, meat_type, tags, ingredients

其中：
- cuisine：能推就填（例：味噌/日式 => japanese；其餘可用 home_style），推不出可填 null
- meat_type：
  - role="main" 時盡量填：chicken/pork/beef/fish/seafood/vegetarian/unknown
  - role="soup"/"side"/"fruit" 時可填 null（不要硬猜）
- tags：字串陣列，能推就填；推不出用 []

【湯品（role="soup"）特別提醒】
- 湯品區塊會出現「湯的菜名」，例如「番茄蛋花湯」「味噌豆腐湯」「香菇蔬菜湯」等；它們就是 dish.name（不要把湯名當食材）。
- tags 建議規則（能推就推，推不出就 []）：
  - 若菜名含「清湯/蛋花湯/蔬菜湯/味噌湯/薏仁湯/湯」且不像濃湯 => tags 包含 "light"
  - 若菜名含「濃湯」=> tags 可包含 "creamy"
- cuisine 建議規則：
  - 含「味噌」=> japanese
  - 其餘 => home_style（除非明顯是西式/泰式等，否則不要亂猜）

允許你額外補強的 dish 鍵值（建議輸出，能解析就填；解析不到就 null/空）：
- source_day_key（例 "0106+"）、source_date（ISO）、source_org、source_section、people_est
- remarks（彙整備註）、total_amount（同菜金額加總）、cost_per_person（total_amount/people_est）、source_rows（原始列陣列）

【dish.ingredients（必填且不得為空）】
- 每筆至少包含：ingredient_id、qty、unit
- qty=每人份量（per_person_qty），unit=base unit（"g"/"piece"/"ml"）
- 允許補強：qty_total、unit_total、unit_price、amount、remark

────────────────────────────────────────
九、prices 產生（要能估算成本；單位需對齊 base unit）
【prices（欄位固定）】
- ingredient_id、price_date、price_per_unit、unit
- 若 unit_price 與 unit_source 存在：
  - unit_source=斤：price_per_unit=unit_price/600，unit="g"
  - unit_source 為 piece 類：price_per_unit=unit_price，unit="piece"
- price_date：能推得就填 ISO；推不出填 null 並 errors(type="missing_price_date")

────────────────────────────────────────
十、meta（dataset_name 不要寫死；需可推導 + 需 parse_profile）
【meta.dataset_name 推導規則】
- 先嘗試從內文推導：
  1) 若抓到機關/營區（例如「電訊科技中心(安康營區)」）=> dataset_name = "menu_" + normalize_zh(機關/營區)
  2) 若抓到可用日期（ISO）=> dataset_name 可在末尾加 "_" + YYYYMM（只加到月份，避免每天不同）
  3) 若都抓不到 => dataset_name = "menu_dataset"
- dataset_name 必須是穩定可重複的字串（同一來源切片後合併時不應亂跳）。

meta 必須包含 parse_profile 物件（必填），欄位必須包含：
- source_type、source_note、portion_policy、people_estimation、dish_line_rules、special_sections、unit_conversions_used、id_policy、limits

parse_profile 範例（格式示意，內容依本次輸入可調整）：
"parse_profile":{
  "source_type":"excel_extracted_text",
  "source_note":"來源：<機關/營區> ROC115-01-06 午餐明細表；people_est=280；counter=265",
  "portion_policy":"per_person",
  "people_estimation":{"priority":["今日用餐人數","計數器"],"range_policy":"avg","missing_policy":"set_qty_null_and_log_error"},
  "dish_line_rules":{"A_two_text_fields_before_number":"new_dish","B_one_text_field_before_number":"continue_ingredient","reset_on":["section_header","合計","總計"]},
  "special_sections":{"青菜 水果":"each_row_is_dish_self_ingredient","雜貨":"no_dishes_only_ingredients_prices","週三麵食":"no_dishes_only_ingredients_prices"},
  "unit_conversions_used":["kg->g:1000","L->ml:1000","tbsp->ml:15","tsp->ml:5","斤->g:600"],
  "id_policy":{"ingredient_unknown":"ing_{normalize_zh(name)}","dish_unknown":"dish_{role}_{normalize_zh(name)}"},
  "limits":["qty 以每人份量輸出；若缺 people_est 或單位不明則 qty 可能為 null","prices 依單價與單位推得；若缺日期則 price_date=null"]
}

────────────────────────────────────────
十一、除 dishes 以外的其他鍵值：輸出格式要求（請嚴格照結構）
【meta（固定欄位 + parse_profile 必填）】
- meta.dataset_name 依推導規則填入（不可寫死）
- meta.currency="TWD"
- meta.base_units=["g","ml","piece"]
- meta.notes 可追加來源與人數資訊
- meta.parse_profile 必填

【unit_conversions（固定 5 筆）】
（必須包含斤→g）

【ingredients（本片段用到的食材即可）】
- 必須至少包含：id、name、category、default_unit
- protein_group：只有 meat/seafood 才填，其他 null

【inventory】
- 若輸入沒有庫存/效期資料，一律輸出空陣列 []

【prices（本片段解析到的價格即可）】
- 欄位固定：ingredient_id、price_date、price_per_unit、unit

【example_constraints（至少要有 menu_plan；其餘可省略）】
- 最少輸出：
  { "menu_plan": { "days": 30, "per_day": { "main": 1, "side": 3, "fruit": 1, "soup": 1 } } }

【errors（一定保留 row_text，截斷到 200 字）】
- 允許的 type 建議：
  unparsed_row / orphan_ingredient_row / unknown_unit / missing_price_date / missing_people_est / stock_row
- row_text 必填；message 簡短

────────────────────────────────────────
十二、整體輸出 JSON 形狀（固定）
你的最終輸出必須是：
[
  {
    "meta": {...},
    "unit_conversions": [...],
    "ingredients": [...],
    "dishes": [...],
    "inventory": [],
    "prices": [...],
    "example_constraints": {...},
    "errors": [...]
  }
]
────────────────────────────────────────
"""

USE_MAINFILE_HINT = True  # True 就會加那一行，False 就隱藏
taskSetting_MenuAnalysis = {
    "Menu Analysis-to json format": {
        "CT_name": "菜單自動結構化分析",
        "InputCutLen": 600,
        "template": lambda content, MainFileName=None: (
            "你是一個「Excel 菜單文字 → 結構化 JSON」的資料整理器。"
            "你會收到一段由 Excel 抽取出的午餐明細表文字（原 Excel 含合併儲存格；抽取後常把『菜名欄空白』吃掉）"
            "，請把內容解析並轉成單一 JSON，以利匯入排菜單資料庫並估算成本。\n"
            f"{MENU_ANALYSIS_Rule}"
            + (f"主檔名為「{removeStrSuffix(MainFileName,'_tika')}」，可用於輔助分析dataset_name。\n"
               if USE_MAINFILE_HINT and MainFileName else "")
            + "☆下列為輸入任務文本：\n"
            + f"{content}"
        )
    }
}