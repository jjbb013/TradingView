import asyncio
import websockets
import json
import time
import os
from datetime import datetime

symbols = [
    "VINE-USDT-SWAP",
    "ETH-USDT-SWAP",
    "PERP-USDT-SWAP",
    "PRCL-USDT-SWAP",
    "MERL-USDT-SWAP"
]

latest_prices = {symbol: None for symbol in symbols}
sampled_prices = {symbol: [] for symbol in symbols}  # 每个标的：[(timestamp, price), ...]
log_buffers = {symbol: [] for symbol in symbols}     # 每个标的：日志字符串列表

# 创建标的文件夹
for symbol in symbols:
    folder = symbol
    if not os.path.exists(folder):
        os.makedirs(folder)

def get_now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def get_file_time_str():
    return datetime.now().strftime("%Y%m%d_%H%M")

async def amplitude_sampler():
    while True:
        try:
            now_ts = int(time.time())
            now_str = get_now_str()
            for symbol in symbols:
                price = latest_prices[symbol]
                if price is not None:
                    sampled_prices[symbol].append((now_ts, float(price)))
                    # 只保留最近7个采样点（0,10,20,30,40,50,60秒前）
                    if len(sampled_prices[symbol]) > 7:
                        sampled_prices[symbol].pop(0)
            await asyncio.sleep(10)
        except Exception as e:
            print(f"{get_now_str()} 采样器错误: {e}")
            await asyncio.sleep(10)

async def amplitude_logger():
    while True:
        try:
            now_str = get_now_str()
            for symbol in symbols:
                history = sampled_prices[symbol]
                if len(history) >= 7:
                    now_time, now_price = history[-1]
                    log_lines = []
                    for i, sec in enumerate([10, 20, 30, 40, 50, 60], start=1):
                        past_time, past_price = history[-1 - i]
                        amplitude = (now_price - past_price) / past_price * 100
                        line = (f"{now_str} {symbol} 当前价: {now_price}，{sec}秒前: {past_price}，振幅: {amplitude:.4f}%")
                        print(line)
                        log_lines.append(line)
                    # 记录本次采样的所有振幅信息
                    log_buffers[symbol].extend(log_lines)
                else:
                    print(f"{now_str} {symbol} 采样数据不足，无法计算多周期振幅。")
            await asyncio.sleep(10)
        except Exception as e:
            print(f"{get_now_str()} 振幅计算器错误: {e}")
            await asyncio.sleep(10)

async def file_writer():
    while True:
        try:
            await asyncio.sleep(600)  # 10分钟
            file_time = get_file_time_str()
            for symbol in symbols:
                if log_buffers[symbol]:
                    folder = symbol
                    filename = os.path.join(folder, f"{symbol}_{file_time}.log")
                    with open(filename, "a", encoding="utf-8") as f:
                        for line in log_buffers[symbol]:
                            f.write(line + "\n")
                    log_buffers[symbol].clear()
                    print(f"{get_now_str()} {symbol} 已写入日志文件：{filename}")
        except Exception as e:
            print(f"{get_now_str()} 文件写入器错误: {e}")
            await asyncio.sleep(600)

async def websocket_handler():
    while True:
        try:
            url = "wss://ws.okx.com:8443/ws/v5/public"
            async with websockets.connect(url, ping_interval=30, ping_timeout=10) as ws:
                sub_param = {
                    "op": "subscribe",
                    "args": [
                        {"channel": "tickers", "instId": symbol}
                        for symbol in symbols
                    ]
                }
                await ws.send(json.dumps(sub_param))
                print(f"{get_now_str()} 已订阅 5个标的 实时价格")
                
                while True:
                    try:
                        msg = await ws.recv()
                        data = json.loads(msg)
                        if isinstance(data, dict) and data.get("arg", {}).get("channel") == "tickers":
                            ticker = data.get("data", [{}])[0]
                            symbol = ticker.get("instId")
                            last_price = ticker.get("last")
                            if symbol in latest_prices:
                                latest_prices[symbol] = last_price
                                print(f"{get_now_str()} {symbol} 最新价格: {last_price}")
                    except websockets.exceptions.ConnectionClosedError:
                        print(f"{get_now_str()} WebSocket连接断开，准备重连...")
                        break
                    except Exception as e:
                        print(f"{get_now_str()} 消息处理错误: {e}")
                        continue
        except Exception as e:
            print(f"{get_now_str()} WebSocket连接错误: {e}")
            print(f"{get_now_str()} 5秒后尝试重连...")
            await asyncio.sleep(5)

async def main():
    # 启动所有异步任务
    tasks = [
        asyncio.create_task(amplitude_sampler()),
        asyncio.create_task(amplitude_logger()),
        asyncio.create_task(file_writer()),
        asyncio.create_task(websocket_handler())
    ]
    
    try:
        # 等待所有任务完成（实际上会一直运行）
        await asyncio.gather(*tasks)
    except KeyboardInterrupt:
        print(f"\n{get_now_str()} 程序被用户中断")
    except Exception as e:
        print(f"{get_now_str()} 主程序错误: {e}")

if __name__ == "__main__":
    asyncio.run(main()) 