from multiprocessing import Pool
from functools import partial
import pandas as pd

# 假设 TextInfoSearcher 已经定义
class TextInfoSearcher:
    def __init__(self, src_log_file_list, keys):
        self.src_log_file_list = src_log_file_list
        self.keys = keys
    
    def proc(self, text):
        # 这里应该是处理文字的逻辑，返回一个包含 "file" 和 "PartNO" 的字典
        return {"file": "dummy_file", "PartNO": "dummy_partno"}

# 定义 compute 函数
def compute(row, SrcLogFileList):
    result = dict()
    print("="*50)
    print("locals()", locals())
    print("-"*50)
    print("row in L167", row)
    print("SrcLogFileList", SrcLogFileList)
    result["file"], result["PartNO"] = TextInfoSearcher(SrcLogFileList, ["file", "PartNO"]).proc(row['text'])
    return result

# 定义一个应用于每一行的辅助函数
def apply_compute(row, **kwargs):
    SrcLogFileList = kwargs["SrcLogFileList"]
    result = compute(row, SrcLogFileList)
    for key, value in result.items():
        row[key] = value
    return row

# 使用多重处理进行并行化运算
def parallel_apply(df, func, num_of_processes=8, **kwargs):
    with Pool(num_of_processes) as pool:
        func = partial(func, **kwargs)
        result = pool.map(func, [row for _, row in df.iterrows()])
    return pd.DataFrame(result)

if __name__=='__main__':
    # 假设 df 是你的 DataFrame 并且 SrcLogFileList 已经定义
    df = pd.DataFrame({
        'text': ['example text 1', 'example text 2', 'example text 3']
    })
    SrcLogFileList = ['log1.txt', 'log2.txt']
    
    result_df = parallel_apply(df, apply_compute, num_of_processes=8, SrcLogFileList=SrcLogFileList)
    print(result_df)
    import os
    os.system("pause")
