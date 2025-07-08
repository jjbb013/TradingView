import requests
import time
import itertools
from datetime import datetime, timedelta, timezone
import os
import csv
import glob
import concurrent.futures

# ========== 采集K线相关函数 ==========
RETRY_LIMIT = 5
REQUEST_DELAY = 0.6
API_URL = "https://www.okx.com/api/v5/market/history-candles"

# 创建带重试的session
def create_retry_session():
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
    retry_strategy = Retry(
        total=RETRY_LIMIT,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
        backoff_factor=1.5,
        respect_retry_after_header=True,
        raise_on_status=False
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session = requests.Session()
    session.mount("https://", adapter)
    return session

def calculate_time_boundaries(days=30):
    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(days=days)
    return int(start_time.timestamp() * 1000), int(end_time.timestamp() * 1000)

API_WAIT_CODES = ["50008", "50111", "50112"]
class RateLimitExceeded(Exception):
    pass

def fetch_swap_candles(session, instId, bar, before=None, after=None):
    params = {
        "instId": instId,
        "bar": bar,
        "limit": "100"
    }
    if before:
        params["before"] = str(before)
    if after:
        params["after"] = str(after)
    headers = {"Content-Type": "application/json"}
    try:
        time.sleep(REQUEST_DELAY)
        response = session.get(API_URL, params=params, headers=headers, timeout=30)
        if response.status_code != 200:
            print(f"HTTP {response.status_code} 错误: {response.text[:100]}")
            return []
        data = response.json()
        if "code" in data and data["code"] != "0":
            if data["code"] in API_WAIT_CODES:
                print(f"触发API限速: {data['msg']}")
                time.sleep(10)
                return fetch_swap_candles(session, instId, bar, before, after)
            elif data["code"] in ["51001", "51005"]:
                print(f"标的不存在或不可用: {instId}")
                return "instrument_not_found"
            else:
                print(f"API错误: {data.get('code')} - {data.get('msg')}")
                return []
        if not data.get("data"):
            print(f"未获取到数据: {instId}-{bar}")
            return []
        return data["data"]
    except Exception as e:
        print(f"请求异常: {str(e)}")
        return []

def fetch_okx_history_klines(instId, bar, days=30):
    session = create_retry_session()
    start_time_ms, end_time_ms = calculate_time_boundaries(days)
    all_candles = []
    after = None
    before = None
    has_more = True
    last_timestamp = end_time_ms
    while has_more:
        candles = fetch_swap_candles(session, instId, bar, before=before, after=after)
        if candles == "instrument_not_found":
            break
        if not candles:
            break
        first_ts = int(candles[0][0])
        last_ts = int(candles[-1][0])
        all_candles.extend(candles)
        if last_ts <= start_time_ms:
            all_candles = [c for c in all_candles if int(c[0]) >= start_time_ms]
            break
        after = last_ts
        time.sleep(REQUEST_DELAY)
    session.close()
    return list(reversed(all_candles))

# ========== 工具函数 ==========
def frange(start, stop, step):
    while start <= stop:
        yield start
        start += step

# ========== 配置 ==========
SYMBOL = "TRUMP-USDT-SWAP"
BAR = "5m"
MAX_LIMIT = 100
DAYS = 30
TP_RANGE = [round(x, 3) for x in frange(0.01, 0.06, 0.002)]
SL_RANGE = [round(x, 3) for x in frange(0.01, 0.06, 0.002)]
AMP_RANGE = [round(x, 3) for x in frange(0.01, 0.08, 0.002)]

def parse_kline(k):
    return {
        "ts": int(k[0]) // 1000,
        "open": float(k[1]),
        "high": float(k[2]),
        "low": float(k[3]),
        "close": float(k[4])
    }

def backtest_segmented(klines):
    LEVERAGE = 10
    MARGIN = 10
    # 参数定义
    take_profit_1, stop_loss_1, amp_1_min, amp_1_max = 0.05, 0.044, 0.012, 0.022
    take_profit_2, stop_loss_2, amp_2_min, amp_2_max = 0.046, 0.046, 0.022, 0.05
    take_profit_3, stop_loss_3, amp_3_min = 0.02, 0.03, 0.05
    balance = 0
    win = 0
    total = 0
    position = None
    entry = 0
    entry_idx = 0
    trades = []
    seg_count = [0.0, 0.0, 0.0]
    seg_profit = [0.0, 0.0, 0.0]
    for i in range(1, len(klines)):
        k0 = klines[i-1]
        k1 = klines[i]
        amp = abs(k0["close"] - k0["open"]) / k0["open"]
        is_green = k0["close"] > k0["open"]
        is_red = k0["close"] < k0["open"]
        seg = None
        tp = sl = None
        # 分段参数选择，优先级3>2>1
        if amp >= amp_3_min:
            tp, sl, seg = take_profit_3, stop_loss_3, 2
        elif amp >= amp_2_min and amp < amp_2_max:
            tp, sl, seg = take_profit_2, stop_loss_2, 1
        elif amp >= amp_1_min and amp < amp_1_max:
            tp, sl, seg = take_profit_1, stop_loss_1, 0
        if position is None and seg is not None:
            assert tp is not None and sl is not None
            entry = k0["close"]
            entry_idx = i-1
            seg_count[seg] += 1.0
            if is_green:
                position = ("SHORT", seg, tp, sl)
            elif is_red:
                position = ("LONG", seg, tp, sl)
        elif position is not None:
            closed = False
            pos_dir, pos_seg, pos_tp, pos_sl = position
            assert pos_tp is not None and pos_sl is not None
            profit_per_trade = MARGIN * LEVERAGE * pos_tp
            loss_per_trade = MARGIN * LEVERAGE * pos_sl
            if pos_dir == "LONG":
                tp_price = entry * (1 + pos_tp)
                sl_price = entry * (1 - pos_sl)
                if k1["low"] <= sl_price and k1["high"] >= tp_price:
                    balance -= loss_per_trade
                    seg_profit[pos_seg] -= loss_per_trade
                    trades.append({"seg": pos_seg+1, "dir": "LONG", "entry": entry, "exit": sl_price, "result": -loss_per_trade, "entry_idx": entry_idx, "exit_idx": i})
                    total += 1
                    position = None
                    closed = True
                elif k1["high"] >= tp_price:
                    balance += profit_per_trade
                    seg_profit[pos_seg] += profit_per_trade
                    win += 1
                    trades.append({"seg": pos_seg+1, "dir": "LONG", "entry": entry, "exit": tp_price, "result": profit_per_trade, "entry_idx": entry_idx, "exit_idx": i})
                    total += 1
                    position = None
                    closed = True
                elif k1["low"] <= sl_price:
                    balance -= loss_per_trade
                    seg_profit[pos_seg] -= loss_per_trade
                    trades.append({"seg": pos_seg+1, "dir": "LONG", "entry": entry, "exit": sl_price, "result": -loss_per_trade, "entry_idx": entry_idx, "exit_idx": i})
                    total += 1
                    position = None
                    closed = True
            elif pos_dir == "SHORT":
                tp_price = entry * (1 - pos_tp)
                sl_price = entry * (1 + pos_sl)
                if k1["high"] >= sl_price and k1["low"] <= tp_price:
                    balance -= loss_per_trade
                    seg_profit[pos_seg] -= loss_per_trade
                    trades.append({"seg": pos_seg+1, "dir": "SHORT", "entry": entry, "exit": sl_price, "result": -loss_per_trade, "entry_idx": entry_idx, "exit_idx": i})
                    total += 1
                    position = None
                    closed = True
                elif k1["low"] <= tp_price:
                    balance += profit_per_trade
                    seg_profit[pos_seg] += profit_per_trade
                    win += 1
                    trades.append({"seg": pos_seg+1, "dir": "SHORT", "entry": entry, "exit": tp_price, "result": profit_per_trade, "entry_idx": entry_idx, "exit_idx": i})
                    total += 1
                    position = None
                    closed = True
                elif k1["high"] >= sl_price:
                    balance -= loss_per_trade
                    seg_profit[pos_seg] -= loss_per_trade
                    trades.append({"seg": pos_seg+1, "dir": "SHORT", "entry": entry, "exit": sl_price, "result": -loss_per_trade, "entry_idx": entry_idx, "exit_idx": i})
                    total += 1
                    position = None
                    closed = True
    winrate = win / total if total > 0 else 0
    return balance, winrate, total, trades, seg_count, seg_profit

SAVE_DIR = "trump_kline_data"

def save_klines_to_csv(klines, symbol, bar):
    if not klines:
        return None
    if not os.path.exists(SAVE_DIR):
        os.makedirs(SAVE_DIR)
    start_ts = klines[0][0]
    end_ts = klines[-1][0]
    file_name = f"{symbol}_{bar}_{start_ts}_{end_ts}.csv"
    file_path = os.path.join(SAVE_DIR, file_name)
    with open(file_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["timestamp", "open", "high", "low", "close"])
        for k in klines:
            writer.writerow([k[0], k[1], k[2], k[3], k[4]])
    print(f"K线数据已保存到: {file_path}")
    return file_path

def load_klines_from_csv(symbol, bar):
    import csv
    import os
    pattern = os.path.join(SAVE_DIR, f"{symbol}_{bar}_*.csv")
    files = sorted(glob.glob(pattern))
    if not files:
        return None
    latest_file = files[-1]
    klines = []
    with open(latest_file, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        next(reader)  # 跳过表头
        for row in reader:
            # [timestamp, open, high, low, close]
            klines.append([int(row[0]), float(row[1]), float(row[2]), float(row[3]), float(row[4])])
    print(f"已从本地文件加载K线: {latest_file}，共{len(klines)}根")
    return klines

# ========== 并行参数优化 ==========
def parallel_grid_search(klines, amp_grid, tp_grid, sl_grid, topN=20):
    tasks = []
    for amp1_min in amp_grid:
        for amp2_min in amp_grid:
            if amp2_min <= amp1_min: continue
            for amp3_min in amp_grid:
                if amp3_min <= amp2_min: continue
                tasks.append((amp1_min, amp2_min, amp3_min))
    print(f"共需遍历分段区间组合: {len(tasks)}")
    results = []
    with concurrent.futures.ProcessPoolExecutor() as executor:
        future_to_amp = {executor.submit(search_best_tp_sl, klines, amp1_min, amp2_min, amp3_min, tp_grid, sl_grid): (amp1_min, amp2_min, amp3_min) for (amp1_min, amp2_min, amp3_min) in tasks}
        for i, future in enumerate(concurrent.futures.as_completed(future_to_amp)):
            res = future.result()
            results.append(res)
            if (i+1) % 50 == 0:
                print(f"已完成{i+1}/{len(tasks)}组分段区间")
    results = sorted(results, key=lambda x: x['profit'], reverse=True)[:topN]
    return results

def search_best_tp_sl(klines, amp1_min, amp2_min, amp3_min, tp_grid, sl_grid):
    best = None
    for tp1 in tp_grid:
        for sl1 in sl_grid:
            for tp2 in tp_grid:
                for sl2 in sl_grid:
                    for tp3 in tp_grid:
                        for sl3 in sl_grid:
                            profit = backtest_segmented_custom(klines, amp1_min, amp2_min, amp3_min, tp1, sl1, tp2, sl2, tp3, sl3)
                            if best is None or profit > best['profit']:
                                best = {'amp1_min': amp1_min, 'amp2_min': amp2_min, 'amp3_min': amp3_min,
                                        'tp1': tp1, 'sl1': sl1, 'tp2': tp2, 'sl2': sl2, 'tp3': tp3, 'sl3': sl3,
                                        'profit': profit}
    return best

def backtest_segmented_custom(klines, amp1_min, amp2_min, amp3_min, tp1, sl1, tp2, sl2, tp3, sl3):
    LEVERAGE = 10
    MARGIN = 10
    balance = 0
    win = 0
    total = 0
    position = None
    entry = 0
    entry_idx = 0
    for i in range(1, len(klines)):
        k0 = klines[i-1]
        k1 = klines[i]
        amp = abs(k0["close"] - k0["open"]) / k0["open"]
        is_green = k0["close"] > k0["open"]
        is_red = k0["close"] < k0["open"]
        seg = None
        tp = sl = None
        if amp >= amp3_min:
            tp, sl, seg = tp3, sl3, 2
        elif amp >= amp2_min and amp < amp3_min:
            tp, sl, seg = tp2, sl2, 1
        elif amp >= amp1_min and amp < amp2_min:
            tp, sl, seg = tp1, sl1, 0
        if tp is None or sl is None:
            continue
        if position is None and seg is not None:
            entry = k0["close"]
            entry_idx = i-1
            if is_green:
                position = ("SHORT", seg, tp, sl)
            elif is_red:
                position = ("LONG", seg, tp, sl)
        elif position is not None:
            pos_dir, pos_seg, pos_tp, pos_sl = position
            profit_per_trade = MARGIN * LEVERAGE * pos_tp
            loss_per_trade = MARGIN * LEVERAGE * pos_sl
            if pos_dir == "LONG":
                tp_price = entry * (1 + pos_tp)
                sl_price = entry * (1 - pos_sl)
                if k1["low"] <= sl_price and k1["high"] >= tp_price:
                    balance -= loss_per_trade
                    total += 1
                    position = None
                elif k1["high"] >= tp_price:
                    balance += profit_per_trade
                    win += 1
                    total += 1
                    position = None
                elif k1["low"] <= sl_price:
                    balance -= loss_per_trade
                    total += 1
                    position = None
            elif pos_dir == "SHORT":
                tp_price = entry * (1 - pos_tp)
                sl_price = entry * (1 + pos_sl)
                if k1["high"] >= sl_price and k1["low"] <= tp_price:
                    balance -= loss_per_trade
                    total += 1
                    position = None
                elif k1["low"] <= tp_price:
                    balance += profit_per_trade
                    win += 1
                    total += 1
                    position = None
                elif k1["high"] >= sl_price:
                    balance -= loss_per_trade
                    total += 1
                    position = None
    return balance

def local_fine_tune(klines, base_params, topN=5):
    amp1_c, amp2_c, amp3_c = base_params['amp1_min'], base_params['amp2_min'], base_params['amp3_min']
    tp1_c, sl1_c = base_params['tp1'], base_params['sl1']
    tp2_c, sl2_c = base_params['tp2'], base_params['sl2']
    tp3_c, sl3_c = base_params['tp3'], base_params['sl3']
    # 微调区间
    amp1_grid = [round(x, 3) for x in frange(amp1_c-0.01, amp1_c+0.01, 0.002) if 0.01 <= x < 0.08]
    amp2_grid = [round(x, 3) for x in frange(amp2_c-0.01, amp2_c+0.01, 0.002) if 0.01 <= x < 0.08]
    amp3_grid = [round(x, 3) for x in frange(amp3_c-0.01, amp3_c+0.01, 0.002) if 0.01 <= x < 0.08]
    tp1_grid = [round(x, 3) for x in frange(tp1_c-0.01, tp1_c+0.01, 0.002) if 0.01 <= x <= 0.06]
    sl1_grid = [round(x, 3) for x in frange(sl1_c-0.01, sl1_c+0.01, 0.002) if 0.01 <= x <= 0.06]
    tp2_grid = [round(x, 3) for x in frange(tp2_c-0.01, tp2_c+0.01, 0.002) if 0.01 <= x <= 0.06]
    sl2_grid = [round(x, 3) for x in frange(sl2_c-0.01, sl2_c+0.01, 0.002) if 0.01 <= x <= 0.06]
    tp3_grid = [round(x, 3) for x in frange(tp3_c-0.01, tp3_c+0.01, 0.002) if 0.01 <= x <= 0.06]
    sl3_grid = [round(x, 3) for x in frange(sl3_c-0.01, sl3_c+0.01, 0.002) if 0.01 <= x <= 0.06]
    # 组合任务
    tasks = []
    for amp1_min in amp1_grid:
        for amp2_min in amp2_grid:
            if amp2_min <= amp1_min: continue
            for amp3_min in amp3_grid:
                if amp3_min <= amp2_min: continue
                tasks.append((amp1_min, amp2_min, amp3_min))
    print(f"微调分段区间组合: {len(tasks)}")
    results = []
    with concurrent.futures.ProcessPoolExecutor() as executor:
        future_to_amp = {executor.submit(search_best_tp_sl_fine, klines, amp1_min, amp2_min, amp3_min, tp1_grid, sl1_grid, tp2_grid, sl2_grid, tp3_grid, sl3_grid): (amp1_min, amp2_min, amp3_min) for (amp1_min, amp2_min, amp3_min) in tasks}
        for i, future in enumerate(concurrent.futures.as_completed(future_to_amp)):
            res = future.result()
            results.append(res)
            if (i+1) % 20 == 0:
                print(f"微调已完成{i+1}/{len(tasks)}组分段区间")
    results = sorted(results, key=lambda x: x['profit'], reverse=True)[:topN]
    return results

def search_best_tp_sl_fine(klines, amp1_min, amp2_min, amp3_min, tp1_grid, sl1_grid, tp2_grid, sl2_grid, tp3_grid, sl3_grid):
    best = None
    for tp1 in tp1_grid:
        for sl1 in sl1_grid:
            for tp2 in tp2_grid:
                for sl2 in sl2_grid:
                    for tp3 in tp3_grid:
                        for sl3 in sl3_grid:
                            profit = backtest_segmented_custom(klines, amp1_min, amp2_min, amp3_min, tp1, sl1, tp2, sl2, tp3, sl3)
                            if best is None or profit > best['profit']:
                                best = {'amp1_min': amp1_min, 'amp2_min': amp2_min, 'amp3_min': amp3_min,
                                        'tp1': tp1, 'sl1': sl1, 'tp2': tp2, 'sl2': sl2, 'tp3': tp3, 'sl3': sl3,
                                        'profit': profit}
    return best

# ========== 主流程 ==========
if __name__ == "__main__":
    print("正在加载本地K线数据...")
    raw_klines = load_klines_from_csv(SYMBOL, "15m")
    if raw_klines is None:
        print("本地无K线数据，开始采集...")
        raw_klines = fetch_okx_history_klines(SYMBOL, "15m", DAYS)
        save_klines_to_csv(raw_klines, SYMBOL, "15m")
    klines = [parse_kline(k) for k in raw_klines]
    print(f"共获取{len(klines)}根K线")
    # 并行参数优化
    amp_grid = [round(x, 3) for x in frange(0.012, 0.08, 0.01)]
    tp_grid = [round(x, 3) for x in frange(0.01, 0.06, 0.01)]
    sl_grid = [round(x, 3) for x in frange(0.01, 0.06, 0.01)]
    topN = 20
    top_results = parallel_grid_search(klines, amp_grid, tp_grid, sl_grid, topN=topN)
    print("\n【分段振幅多参数策略Top参数】")
    for i, res in enumerate(top_results):
        print(f"Top{i+1}: 分段1[{res['amp1_min']},{res['amp2_min']}), 止盈={res['tp1']}, 止损={res['sl1']} | "
              f"分段2[{res['amp2_min']},{res['amp3_min']}), 止盈={res['tp2']}, 止损={res['sl2']} | "
              f"分段3[{res['amp3_min']},+∞), 止盈={res['tp3']}, 止损={res['sl3']} | 收益={res['profit']:.2f}")
    # 自动微调Top1
    print("\n【Top1参数微调优化】")
    fine_results = local_fine_tune(klines, top_results[0], topN=5)
    for i, res in enumerate(fine_results):
        print(f"微调Top{i+1}: 分段1[{res['amp1_min']},{res['amp2_min']}), 止盈={res['tp1']}, 止损={res['sl1']} | "
              f"分段2[{res['amp2_min']},{res['amp3_min']}), 止盈={res['tp2']}, 止损={res['sl2']} | "
              f"分段3[{res['amp3_min']},+∞), 止盈={res['tp3']}, 止损={res['sl3']} | 收益={res['profit']:.2f}")

 