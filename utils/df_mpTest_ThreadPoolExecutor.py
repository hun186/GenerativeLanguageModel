import pandas as pd
import time
import psutil
from concurrent.futures import ThreadPoolExecutor, as_completed

# 创建一个示例DataFrame
data = {
    'A': list(range(1, 1001)),
    'B': [x * 10 for x in range(1, 1001)]
}
df = pd.DataFrame(data)

# 定义一个函数来处理每一行
def process_row(row):
    time.sleep(0.01)
    result1 = row['A'] ** 2
    result2 = row['B'] ** 3
    return result1, result2

# 并行化处理DataFrame
def parallel_process(df, func, num_threads):
    results = []
    with ThreadPoolExecutor(max_workers=num_threads) as executor:
        future_to_row = {executor.submit(func, row): row for index, row in df.iterrows()}
        for future in as_completed(future_to_row):
            results.append(future.result())
    return results

# 测量时间和内存使用情况
def measure_performance(df, func, num_threads):
    start_time = time.time()
    start_memory = psutil.Process().memory_info().rss

    results = parallel_process(df, func, num_threads)

    end_time = time.time()
    end_memory = psutil.Process().memory_info().rss

    elapsed_time = end_time - start_time
    memory_usage = end_memory - start_memory

    return elapsed_time, memory_usage

# 测试不同的并行化数量
thread_counts = [1, 2, 4, 8, 16,30]
performance_results = []

for num_threads in thread_counts:
    elapsed_time, memory_usage = measure_performance(df, process_row, num_threads)
    performance_results.append({
        'num_threads': num_threads,
        'elapsed_time': elapsed_time,
        'memory_usage': memory_usage
    })

# 打印结果
for result in performance_results:
    print(f"Threads: {result['num_threads']}, Elapsed Time: {result['elapsed_time']:.2f}s, Memory Usage: {result['memory_usage'] / 1024 / 1024:.2f}MB")