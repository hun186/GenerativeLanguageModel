# pip3 install transformers
# python3 deepseek_v2_tokenizer.py
import transformers

chat_tokenizer_dir = "./"

tokenizer = transformers.AutoTokenizer.from_pretrained( 
        chat_tokenizer_dir, trust_remote_code=True
        )

MES = """
擬針對LLM RAG應用進行文本chunk切割，用於組建語意向量庫。為了優化檢索效果，切割時儘量保持段落的語意連結整體性，不要切在不適當的地方，避免切出段落太破碎。並且在每一個切割出來的chunk前加上該段文字的出處標題及段落標題，以json輸出chunk的清單，不要有其他LLM的說明提詞。在語意主題聚合的前提下，單一chunk以400字為目標，儘量長。
chunk格式範例：
{"type":"RAG chunk",
"title":"1月PMI数据点评：我国经济继续保持平稳恢复态势",
"source":消息出處,
"background_date":"2021-1-1 00:00:00",
"event_date":"(2020-12-21 00:00:00,2021-1-1 00:00:00)",
"section":"拉闸限电制约企业生产",
"content": "1月生产指数为53.5%，环比回落0.7个百分点。采购量下降1.2%至52.0%，但产成品库存指数为49.0%，较上月回升2.8个百分点，原材料库存指数为49.0%，比上月回升0.4个百分点。库存分项均位于临界点下方，表明未来企业生产仍有一定空间。12月中下旬起，湖南、浙江、江西等省份由于气温偏低、年底赶工等导致生活、生产用电需求旺盛，部分地区开启“拉闸限电”。2021年春节较晚，部分地区也提倡就地过年，赶工可能还将持续一段时间，对生产数据造成一定扰动。",
"keywords":["企业生产","拉闸限电","库存指数"]}
請定出全部段落合適的共用標題放在title，section是各段的副標題。background_date為段落發布背景時間，event_date則為該切割段落內提及重要事件的時間，各chunk可不同，使用之格式字串表示法為%Y-%m-%d %H:%M:%S，如果時間是一個區間，則使用2維tuple表示該區間。另外提供3個重要關鍵字，由重要度高排到低存放於keywords。source為消息來源單位。各欄位如無合適值可填入，填入空字串或空清單。
主檔名為「123」，
☆輸入文本：
"""
result = tokenizer.encode(MES)
print(result)
print(len(result))
