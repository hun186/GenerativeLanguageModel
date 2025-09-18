import pandas as pd
from multiprocessing import Pool
import psutil
import time

# 擴增示範資料到100000個元素
data = {
    'A': list(range(1, 100001)),
    'B': [x * 10 for x in range(1, 100001)]
}
df = pd.DataFrame(data)

# 定義一個計算函數
def compute(row):
    # 執行運算，這裡假設將 column 'A' 的值平方並存到兩個新 column 'C' 和 'D'
    result = {
        'C': row['A'] ** 2,
        'D': row['A'] ** 3
    }
    return result

# 定義一個應用於每一行的輔助函數
def apply_compute(row):
    result = compute(row)
    for key, value in result.items():
        row[key] = value
    return row

# 使用多重處理進行平行化運算
def parallel_apply(df, func, num_processes):
    with Pool(num_processes) as pool:
        result = pool.map(func, [row for _, row in df.iterrows()])
    return pd.DataFrame(result)

# 顯示內存用量
def show_memory_usage():
    process = psutil.Process()
    memory_info = process.memory_info()
    print(f"Memory Usage: {memory_info.rss / 1024 ** 2:.2f} MB")

if __name__ == "__main__":
    num_processes_list = [1, 2, 4, 8]  # 不同的進程數量

    for num_processes in num_processes_list:
        print(f"\nUsing {num_processes} process(es):")

        # 顯示內存用量
        print("Before processing:")
        show_memory_usage()

        # 計算時間
        start_time = time.time()
        
        # 執行平行化運算
        df_result = parallel_apply(df, apply_compute, num_processes)

        end_time = time.time()
        
        # 顯示計算時間
        print(f"Processing time: {end_time - start_time:.2f} seconds")

        # 顯示內存用量
        print("After processing:")
        show_memory_usage()
