import asyncio
import json
import websockets
from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
import threading
import os
from dotenv import load_dotenv

# 加载.env
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '.env'))

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 读取多账户API信息
OKX_ACCOUNTS = []
idx = 1
while True:
    api_key = os.getenv(f"OKX_API_KEY_{idx}")
    api_secret = os.getenv(f"OKX_API_SECRET_{idx}")
    passphrase = os.getenv(f"OKX_API_PASSPHRASE_{idx}")
    if not api_key:
        break
    OKX_ACCOUNTS.append({
        "apiKey": api_key,
        "apiSecret": api_secret,
        "passphrase": passphrase
    })
    idx += 1

# 读取账户备注名
ACCOUNT_NAMES = []
idx = 1
while True:
    name = os.getenv(f"OKX_ACCOUNT_NAME_{idx}")
    if not name:
        break
    ACCOUNT_NAMES.append(name)
    idx += 1

@app.get("/api/account_names")
def get_account_names():
    return {"account_names": ACCOUNT_NAMES}

latest_data = {}  # {account_idx: [data]}
ws_clients = set()
latest_prices = {}  # {instId: markPx}

# 合约面值（可根据实际合约调整，DOGE-USDT-SWAP为1，ETH-USDT-SWAP为0.01等）
CONTRACT_FACE_VALUE = {
    'DOGE-USDT-SWAP': 1,
    'ETH-USDT-SWAP': 0.01,
    'BTC-USDT-SWAP': 0.01,
    # 可继续补充
}

def get_contract_face_value(instId):
    return CONTRACT_FACE_VALUE.get(instId, 1)

async def okx_login(ws, apiKey, apiSecret, passphrase):
    import time, hmac, base64
    ts = str(int(time.time()))
    sign = base64.b64encode(
        hmac.new(
            apiSecret.encode(),
            f"{ts}GET/users/self/verify".encode(),
            digestmod="sha256"
        ).digest()
    ).decode()
    login_req = {
        "op": "login",
        "args": [{
            "apiKey": apiKey,
            "passphrase": passphrase,
            "timestamp": ts,
            "sign": sign
        }]
    }
    await ws.send(json.dumps(login_req))

async def okx_account_ws(account_idx, account):
    url = "wss://ws.okx.com:8443/ws/v5/private"
    async with websockets.connect(url) as ws:
        await okx_login(ws, account["apiKey"], account["apiSecret"], account["passphrase"])
        # 等待登录成功
        while True:
            msg = await ws.recv()
            data = json.loads(msg)
            if data.get("event") == "login" and data.get("code") == "0":
                break
        # 订阅持仓和余额
        sub_req = {
            "id": f"acc{account_idx}",
            "op": "subscribe",
            "args": [{"channel": "balance_and_position"}]
        }
        await ws.send(json.dumps(sub_req))
        # 持续接收推送
        while True:
            msg = await ws.recv()
            data = json.loads(msg)
            # 只处理包含data字段的推送
            if data.get("arg", {}).get("channel") == "balance_and_position" and "data" in data:
                # 计算未实现盈亏（用标记价格）
                for d in data["data"]:
                    for pos in d.get("posData", []):
                        instId = pos.get("instId")
                        avgPx = float(pos.get("avgPx", 0))
                        posQty = float(pos.get("pos", 0))
                        posSide = pos.get("posSide", "net")
                        markPx = float(latest_prices.get(instId, 0))
                        face_value = get_contract_face_value(instId)
                        # 多头：未实现盈亏 = (markPx-均价)*数量*面值，空头反之
                        if avgPx > 0 and posQty != 0 and markPx > 0:
                            if posSide == 'long':
                                unrealized = (markPx - avgPx) * posQty * face_value
                            elif posSide == 'short':
                                unrealized = (avgPx - markPx) * posQty * face_value
                            else:
                                unrealized = (markPx - avgPx) * posQty * face_value
                        else:
                            unrealized = 0
                        pos["unrealizedPnl"] = unrealized
                        pos["lastPrice"] = markPx
                latest_data[account_idx] = data["data"]
                # 推送给所有前端
                for client in ws_clients:
                    await client.send_json({"account": account_idx, "data": data["data"]})

async def okx_mark_price_ws():
    url = "wss://ws.okx.com:8443/ws/v5/public"
    while True:
        # 动态收集所有持仓合约
        instIds = set()
        for acc_data in latest_data.values():
            for d in acc_data:
                for pos in d.get("posData", []):
                    instIds.add(pos.get("instId"))
        # 也可手动补充常用合约
        instIds.update(["DOGE-USDT-SWAP", "ETH-USDT-SWAP", "BTC-USDT-SWAP"])
        args = [{"channel": "mark-price", "instId": instId} for instId in instIds]
        async with websockets.connect(url) as ws:
            sub_req = {"op": "subscribe", "args": args}
            await ws.send(json.dumps(sub_req))
            while True:
                msg = await ws.recv()
                data = json.loads(msg)
                if data.get("arg", {}).get("channel") == "mark-price" and "data" in data:
                    mark = data["data"][0]
                    instId = mark.get("instId")
                    markPx = float(mark.get("markPx", 0))
                    latest_prices[instId] = markPx

# 启动所有账户的ws监听和行情监听
def start_okx_ws():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    tasks = [okx_account_ws(idx, acc) for idx, acc in enumerate(OKX_ACCOUNTS)]
    tasks.append(okx_mark_price_ws())
    loop.run_until_complete(asyncio.gather(*tasks))

@app.on_event("startup")
def start_ws_thread():
    threading.Thread(target=start_okx_ws, daemon=True).start()

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    ws_clients.add(websocket)
    # 首次推送所有账户最新数据
    for idx, data in latest_data.items():
        await websocket.send_json({"account": idx, "data": data})
    try:
        while True:
            await websocket.receive_text()
    except:
        ws_clients.remove(websocket) 