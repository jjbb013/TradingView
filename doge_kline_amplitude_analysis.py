import csv
from datetime import datetime
from utils.kline_data_toolkit import fetch_candles

def ts_to_str(ts):
    return datetime.fromtimestamp(int(ts)//1000).strftime("%Y-%m-%d %H:%M")

def fetch_doge_5m_klines(limit=2000):
    instId = "DOGE-USDT-SWAP"
    bar = "5m"
    all_klines = []
    after = None
    while len(all_klines) < limit:
        candles = fetch_candles(instId, bar, after=after)
        if not candles:
            break
        all_klines.extend(candles)
        after = int(candles[-1][0])
        if len(candles) < 100:
            break
    all_klines = sorted(all_klines, key=lambda x: int(x[0]))
    return all_klines[-limit:]

def analyze_amplitude(klines):
    result = []
    for i, k in enumerate(klines):
        ts, open_, high, low, close = k[0], float(k[1]), float(k[2]), float(k[3]), float(k[4])
        amplitude = (high - low) / open_ if open_ != 0 else 0
        body = abs(close - open_) / open_ if open_ != 0 else 0
        result.append({
            "idx": i,
            "ts": ts,
            "amplitude": amplitude,
            "body": body,
            "close": close,
            "next_close": float(klines[i+1][4]) if i+1 < len(klines) else None
        })
    return result

def analyze_wicks(klines):
    upper_wicks = []
    lower_wicks = []
    for i, k in enumerate(klines):
        open_, high, low, close = float(k[1]), float(k[2]), float(k[3]), float(k[4])
        upper = high - max(open_, close)
        lower = min(open_, close) - low
        upper_wicks.append({
            "idx": i,
            "ts": k[0],
            "wick": upper,
            "open": open_,
            "close": close,
            "high": high,
            "low": low,
            "next_close": float(klines[i+1][4]) if i+1 < len(klines) else None
        })
        lower_wicks.append({
            "idx": i,
            "ts": k[0],
            "wick": lower,
            "open": open_,
            "close": close,
            "high": high,
            "low": low,
            "next_close": float(klines[i+1][4]) if i+1 < len(klines) else None
        })
    return upper_wicks, lower_wicks

def write_top_to_csv(amplitude_data, klines, out_csv_ampl="doge_5m_amplitude_top20.csv", out_csv_body="doge_5m_body_top20.csv", raw_csv="doge_5m_raw.csv"):
    # 振幅前20
    top20_ampl = sorted(amplitude_data, key=lambda x: x["amplitude"], reverse=True)[:20]
    with open(out_csv_ampl, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["排名", "时间", "振幅", "收盘价", "下一根收盘价"])
        for rank, item in enumerate(top20_ampl, 1):
            writer.writerow([
                rank,
                ts_to_str(item["ts"]),
                f"{item['amplitude']:.4%}",
                item["close"],
                item["next_close"] if item["next_close"] is not None else ""
            ])
    # 实体振幅前20
    top20_body = sorted(amplitude_data, key=lambda x: x["body"], reverse=True)[:20]
    with open(out_csv_body, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["排名", "时间", "实体振幅", "收盘价", "下一根收盘价"])
        for rank, item in enumerate(top20_body, 1):
            writer.writerow([
                rank,
                ts_to_str(item["ts"]),
                f"{item['body']:.4%}",
                item["close"],
                item["next_close"] if item["next_close"] is not None else ""
            ])
    # 保存原始K线
    with open(raw_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["timestamp", "open", "high", "low", "close", "volume", "volCcy", "volCcyQuote", "confirm"])
        for row in klines:
            writer.writerow(row)

def write_top_wicks_to_csv(upper_wicks, lower_wicks, ts_to_str, out_csv_upper="doge_5m_upper_wick_top10.csv", out_csv_lower="doge_5m_lower_wick_top10.csv"):
    top10_upper = sorted(upper_wicks, key=lambda x: abs(x["wick"]), reverse=True)[:10]
    top10_lower = sorted(lower_wicks, key=lambda x: abs(x["wick"]), reverse=True)[:10]
    with open(out_csv_upper, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["排名", "时间", "上影线绝对值", "开盘", "收盘", "最高", "最低", "下一根收盘"])
        for rank, item in enumerate(top10_upper, 1):
            writer.writerow([
                rank,
                ts_to_str(item["ts"]),
                f"{item['wick']:.6f}",
                item["open"],
                item["close"],
                item["high"],
                item["low"],
                item["next_close"] if item["next_close"] is not None else ""
            ])
    with open(out_csv_lower, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["排名", "时间", "下影线绝对值", "开盘", "收盘", "最高", "最低", "下一根收盘"])
        for rank, item in enumerate(top10_lower, 1):
            writer.writerow([
                rank,
                ts_to_str(item["ts"]),
                f"{item['wick']:.6f}",
                item["open"],
                item["close"],
                item["high"],
                item["low"],
                item["next_close"] if item["next_close"] is not None else ""
            ])

if __name__ == "__main__":
    klines = fetch_doge_5m_klines(limit=2000)
    amplitude_data = analyze_amplitude(klines)
    write_top_to_csv(amplitude_data, klines)
    upper_wicks, lower_wicks = analyze_wicks(klines)
    write_top_wicks_to_csv(upper_wicks, lower_wicks, ts_to_str)
    print("分析完成，已输出振幅、实体振幅、上影线和下影线统计csv文件") 