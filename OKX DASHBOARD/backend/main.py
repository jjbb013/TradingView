import asyncio
import json
import websockets
from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
import threading
import os
from dotenv import load_dotenv
import random
import string
import time
from datetime import datetime, timezone, timedelta
import okx.Trade as Trade
from pydantic import BaseModel

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
        "passphrase": passphrase,
        "flag": os.getenv(f"OKX_FLAG_{idx}", "0"),
        "name": os.getenv(f"OKX_ACCOUNT_NAME_{idx}", f"账户{idx}")
    })
    idx += 1

# 读取账户备注名
ACCOUNT_NAMES = [acc['name'] for acc in OKX_ACCOUNTS]

@app.get("/api/account_names")
def get_account_names():
    return {"account_names": ACCOUNT_NAMES}

latest_data = {}  # {account_idx: [data]}
ws_clients = set()
latest_prices = {}  # {instId: markPx}

# 合约面值
CONTRACT_FACE_VALUE = {
    'DOGE-USDT-SWAP': 1,
    'ETH-USDT-SWAP': 0.01,
    'BTC-USDT-SWAP': 0.01,
}

def get_contract_face_value(instId):
    return CONTRACT_FACE_VALUE.get(instId, 1)

def get_beijing_time():
    beijing_tz = timezone(timedelta(hours=8))
    return datetime.now(beijing_tz).strftime("%Y-%m-%d %H:%M:%S")

def generate_clord_id():
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    random_str = ''.join(random.choices(string.ascii_letters + string.digits, k=6))
    return f"GEMINI{timestamp}{random_str}"[:32]

class OrderRequest(BaseModel):
    account_index: int
    inst_id: str
    order_size: str
    order_side: str

class ClosePositionRequest(BaseModel):
    account_index: int
    pos_data: dict

@app.post("/api/place_order")
async def place_order(req: OrderRequest):
    account = OKX_ACCOUNTS[req.account_index]
    trade_api = Trade.TradeAPI(account["apiKey"], account["apiSecret"], account["passphrase"], False, account["flag"])
    
    order_params = {
        "instId": req.inst_id,
        "tdMode": "cross",
        "side": req.order_side,
        "ordType": "market",
        "sz": req.order_size,
        "clOrdId": generate_clord_id(),
        "posSide": "long" if req.order_side == "buy" else "short"
    }
    
    print(f"[{get_beijing_time()}] [ORDER] Placing order for {account['name']}: {json.dumps(order_params)}")
    result = trade_api.place_order(**order_params)
    print(f"[{get_beijing_time()}] [ORDER] Result for {account['name']}: {json.dumps(result)}")
    
    return result

@app.post("/api/close_position")
async def close_position(req: ClosePositionRequest):
    account = OKX_ACCOUNTS[req.account_index]
    trade_api = Trade.TradeAPI(account["apiKey"], account["apiSecret"], account["passphrase"], False, account["flag"])
    
    pos = req.pos_data
    close_side = "sell" if pos['posSide'] == 'long' else 'buy'
    
    order_params = {
        "instId": pos['instId'],
        "tdMode": "cross",
        "side": close_side,
        "ordType": "market",
        "sz": pos['pos'],
        "clOrdId": generate_clord_id(),
        "posSide": pos['posSide']
    }
    
    print(f"[{get_beijing_time()}] [CLOSE] Closing position for {account['name']}: {json.dumps(order_params)}")
    result = trade_api.place_order(**order_params)
    print(f"[{get_beijing_time()}] [CLOSE] Result for {account['name']}: {json.dumps(result)}")
    
    return result

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
    while True:
        try:
            async with websockets.connect(url) as ws:
                await okx_login(ws, account["apiKey"], account["apiSecret"], account["passphrase"])
                
                # Wait for login success
                login_success = False
                while not login_success:
                    msg = await asyncio.wait_for(ws.recv(), timeout=10)
                    data = json.loads(msg)
                    if data.get("event") == "login" and data.get("code") == "0":
                        login_success = True
                
                # Subscribe to balance and position
                sub_req = {
                    "id": f"acc{account_idx}",
                    "op": "subscribe",
                    "args": [{"channel": "balance_and_position"}]
                }
                await ws.send(json.dumps(sub_req))
                
                # Receive pushes
                while True:
                    msg = await asyncio.wait_for(ws.recv(), timeout=60) # Add timeout to detect dead connections
                    data = json.loads(msg)
                    if data.get("arg", {}).get("channel") == "balance_and_position" and "data" in data:
                        for d in data["data"]:
                            for pos in d.get("posData", []):
                                instId = pos.get("instId")
                                avgPx = float(pos.get("avgPx", 0))
                                posQty = float(pos.get("pos", 0))
                                posSide = pos.get("posSide", "net")
                                markPx = float(latest_prices.get(instId, 0))
                                face_value = get_contract_face_value(instId)
                                
                                if avgPx > 0 and posQty != 0 and markPx > 0:
                                    pnl_multiplier = 1 if posSide == 'long' else -1
                                    unrealized = (markPx - avgPx) * posQty * face_value * pnl_multiplier
                                    unrealized_pct = (unrealized / (avgPx * posQty * face_value)) * 100 if (avgPx * posQty * face_value) != 0 else 0
                                else:
                                    unrealized = 0
                                    unrealized_pct = 0
                                    
                                pos["unrealizedPnl"] = unrealized
                                pos["unrealizedPnlPct"] = unrealized_pct
                                pos["lastPrice"] = markPx
                                
                        latest_data[account_idx] = data["data"]
                        for client in ws_clients:
                            await client.send_json({"account": account_idx, "data": data["data"]})
        except (websockets.exceptions.ConnectionClosed, asyncio.TimeoutError) as e:
            print(f"[{get_beijing_time()}] [WS-{account['name']}] Connection lost ({e}), reconnecting in 5s...")
            await asyncio.sleep(5)
        except Exception as e:
            print(f"[{get_beijing_time()}] [WS-{account['name']}] Error: {e}")
            await asyncio.sleep(5)


async def okx_mark_price_ws():
    url = "wss://ws.okx.com:8443/ws/v5/public"
    while True:
        try:
            instIds = set(["DOGE-USDT-SWAP", "ETH-USDT-SWAP", "BTC-USDT-SWAP"])
            for acc_data in latest_data.values():
                for d in acc_data:
                    for pos in d.get("posData", []):
                        if pos.get("instId"):
                            instIds.add(pos.get("instId"))
            
            args = [{"channel": "mark-price", "instId": instId} for instId in instIds if instId]
            
            if not args:
                await asyncio.sleep(5)
                continue

            async with websockets.connect(url) as ws:
                sub_req = {"op": "subscribe", "args": args}
                await ws.send(json.dumps(sub_req))
                
                while True:
                    msg = await asyncio.wait_for(ws.recv(), timeout=60)
                    data = json.loads(msg)
                    if data.get("arg", {}).get("channel") == "mark-price" and "data" in data:
                        mark = data["data"][0]
                        instId = mark.get("instId")
                        markPx = float(mark.get("markPx", 0))
                        if instId:
                            latest_prices[instId] = markPx
        except (websockets.exceptions.ConnectionClosed, asyncio.TimeoutError) as e:
            print(f"[{get_beijing_time()}] [MARK-PRICE-WS] Connection lost ({e}), reconnecting in 5s...")
            await asyncio.sleep(5)
        except Exception as e:
            print(f"[{get_beijing_time()}] [MARK-PRICE-WS] Error: {e}")
            await asyncio.sleep(5)


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
    # Send latest data for all accounts on first connect
    for idx, data in latest_data.items():
        await websocket.send_json({"account": idx, "data": data})
    try:
        while True:
            # Keep connection alive
            await websocket.receive_text()
    except websockets.exceptions.ConnectionClosed:
        ws_clients.remove(websocket)
    finally:
        if websocket in ws_clients:
            ws_clients.remove(websocket)