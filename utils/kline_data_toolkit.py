import os
import csv
import time
import requests
import logging
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
from statistics import mean, stdev

# ========== 参数区 ==========
INSTRUMENTS = ["BTC-USDT-SWAP", "ETH-USDT-SWAP"]
TIMEFRAMES = ["5m", "15m"]
DAYS_TO_FETCH = 30
DATA_DIR = "swap_kline_data"
MAX_WORKERS = 4
BOLL_PERIOD = 20  # 布林带周期

API_URL = "https://www.okx.com/api/v5/market/history-candles"
REQUEST_DELAY = 0.6
RETRY_LIMIT = 5

# ========== 日志配置 ==========
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger()

# ========== 工具函数 ==========
def get_utc_time():
    return datetime.now(timezone.utc)

def get_beijing_time():
    return datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")

def create_data_directory():
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR)
    for inst in INSTRUMENTS:
        inst_dir = os.path.join(DATA_DIR, inst)
        if not os.path.exists(inst_dir):
            os.makedirs(inst_dir)

def calculate_time_boundaries():
    end_time = get_utc_time()
    start_time = end_time - timedelta(days=DAYS_TO_FETCH)
    return int(start_time.timestamp() * 1000), int(end_time.timestamp() * 1000)

def fetch_candles(instId, bar, before=None, after=None):
    params = {"instId": instId, "bar": bar, "limit": "100"}
    if before:
        params["before"] = str(before)
    if after:
        params["after"] = str(after)
    for attempt in range(RETRY_LIMIT):
        try:
            time.sleep(REQUEST_DELAY)
            resp = requests.get(API_URL, params=params, timeout=30)
            if resp.status_code != 200:
                logger.warning(f"HTTP {resp.status_code} 错误: {resp.text[:100]}")
                continue
            data = resp.json()
            if data.get("code") != "0":
                logger.warning(f"API错误: {data.get('code')} - {data.get('msg')}")
                continue
            return data["data"]
        except Exception as e:
            logger.error(f"请求异常: {e}")
            time.sleep(2)
    return []

def save_candles_to_csv(candles, instId, bar, start_ts, end_ts):
    if not candles:
        return False
    file_name = f"{instId}_{bar}_{start_ts}_{end_ts}.csv"
    file_path = os.path.join(DATA_DIR, instId, file_name)
    with open(file_path, "w", newline="", encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow([
            "timestamp", "open", "high", "low", "close", "volume", "volCcy", "volCcyQuote", "confirm",
            "ma5", "ma10", "ma20", "amplitude", "is_high", "is_low", "boll_mid", "boll_up", "boll_low"
        ])
        for row in candles:
            writer.writerow(row)
    logger.info(f"保存 {len(candles)} 条 {instId}-{bar} 数据到 {file_path}")
    return True

# ========== 分析函数 ==========
def analyze_candles(candles):
    # 输入: 原始K线二维数组，输出: 增加分析字段的二维数组
    closes = [float(c[4]) for c in candles]
    highs = [float(c[2]) for c in candles]
    lows = [float(c[3]) for c in candles]
    result = []
    for i, c in enumerate(candles):
        close = float(c[4])
        open_ = float(c[1])
        high = float(c[2])
        low = float(c[3])
        # 均线
        ma5 = mean(closes[max(0, i-4):i+1]) if i >= 4 else ''
        ma10 = mean(closes[max(0, i-9):i+1]) if i >= 9 else ''
        ma20 = mean(closes[max(0, i-19):i+1]) if i >= 19 else ''
        # 振幅
        amplitude = (high - low) / open_ if open_ != 0 else ''
        # 极值点
        is_high = 1 if i > 0 and i < len(highs)-1 and high > highs[i-1] and high > highs[i+1] else 0
        is_low = 1 if i > 0 and i < len(lows)-1 and low < lows[i-1] and low < lows[i+1] else 0
        # 布林带
        if i >= BOLL_PERIOD-1:
            mid = mean(closes[i-BOLL_PERIOD+1:i+1])
            std = stdev(closes[i-BOLL_PERIOD+1:i+1])
            boll_up = mid + 2*std
            boll_low = mid - 2*std
        else:
            mid = boll_up = boll_low = ''
        result.append(
            list(c) + [ma5, ma10, ma20, amplitude, is_high, is_low, mid, boll_up, boll_low]
        )
    return result

# ========== 采集+分析主流程 ==========
def fetch_and_analyze(instId, bar):
    logger.info(f"采集 {instId}-{bar} ...")
    start_time_ms, end_time_ms = calculate_time_boundaries()
    all_candles = []
    after = None
    has_more = True
    while has_more:
        candles = fetch_candles(instId, bar, after=after)
        if not candles:
            break
        all_candles.extend(candles)
        last_ts = int(candles[-1][0])
        if last_ts <= start_time_ms:
            all_candles = [c for c in all_candles if int(c[0]) >= start_time_ms]
            break
        after = last_ts
    # 时间正序
    all_candles = sorted(all_candles, key=lambda x: int(x[0]))
    analyzed = analyze_candles(all_candles)
    if analyzed:
        save_candles_to_csv(analyzed, instId, bar, int(analyzed[0][0]), int(analyzed[-1][0]))
    return instId, bar, len(analyzed)

# ========== 多线程主控 ==========
def multi_thread_fetch_and_analyze():
    create_data_directory()
    tasks = [(inst, bar) for inst in INSTRUMENTS for bar in TIMEFRAMES]
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = [executor.submit(fetch_and_analyze, inst, bar) for inst, bar in tasks]
        for future in as_completed(futures):
            instId, bar, count = future.result()
            logger.info(f"完成: {instId}-{bar} 共{count}条")

if __name__ == "__main__":
    multi_thread_fetch_and_analyze() 