import asyncio
import websockets
import json

latest_price = None
sampled_prices = []  # 每10秒采样一次的价格

async def sampler():
    global latest_price, sampled_prices
    while True:
        if latest_price is not None:
            sampled_prices.append(latest_price)
            # 只保留最近6个采样点（即50秒前到现在）
            if len(sampled_prices) > 6:
                sampled_prices.pop(0)
        await asyncio.sleep(10)

async def amplitude_checker():
    while True:
        if len(sampled_prices) >= 6:
            now = float(sampled_prices[-1])
            for i, sec in enumerate([10, 20, 30, 40, 50], start=1):
                past = float(sampled_prices[-1 - i])
                amplitude = (now - past) / past * 100
                print(f"【{sec}秒振幅】当前价: {now}，{sec}秒前: {past}，振幅: {amplitude:.4f}%")
        else:
            print("采样数据不足，无法计算多周期振幅。")
        await asyncio.sleep(10)

async def main():
    global latest_price
    url = "wss://ws.okx.com:8443/ws/v5/public"
    async with websockets.connect(url) as ws:
        # 订阅ETH-USDT-SWAP的tickers频道
        sub_param = {
            "op": "subscribe",
            "args": [
                {
                    "channel": "tickers",
                    "instId": "ETH-USDT-SWAP"
                }
            ]
        }
        await ws.send(json.dumps(sub_param))
        print("已订阅 ETH-USDT-SWAP 实时价格")
        # 启动采样协程
        asyncio.create_task(sampler())
        # 启动振幅监控协程
        asyncio.create_task(amplitude_checker())
        while True:
            msg = await ws.recv()
            data = json.loads(msg)
            # 只处理行情推送
            if isinstance(data, dict) and data.get("arg", {}).get("channel") == "tickers":
                ticker = data.get("data", [{}])[0]
                last_price = ticker.get("last")
                latest_price = last_price
                print(f"最新价格: {last_price}")

if __name__ == "__main__":
    asyncio.run(main()) 