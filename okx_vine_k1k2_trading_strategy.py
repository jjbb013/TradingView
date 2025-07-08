"""
任务名称
name: OKX VINE K1K2自动交易 PROD
定时规则
cron: 3 */5 * * * *
"""
import os
import json
import random
import string
import time
from datetime import datetime, timezone, timedelta
import okx.MarketData as MarketData
import okx.Trade as Trade
from notification_service import notification_service

# ============== 可配置参数区域 ==============
INST_ID = "VINE-USDT-SWAP"
BAR = "5m"
LIMIT = 7  # 获取7根K线
LEVERAGE = 10
MARGIN = 5  # 保证金(USDT)
CONTRACT_FACE_VALUE = 50  # 合约面值
SizePoint = 0
TAKE_PROFIT_PERCENT = 0.016  # 止盈1.6%
STOP_LOSS_PERCENT = 0.02     # 止损2%
MIN_BODY1 = 0.01  # K2最小实体振幅(1%)
MAX_BODY1 = 0.04  # K2最大实体振幅(4%)
MAX_TOTAL_RANGE = 0.02  # K3~K6总单向振幅上限(2%)
ACCOUNT_SUFFIXES = ["", "1"]
MAX_RETRIES = 3
RETRY_DELAY = 2

def get_beijing_time():
    beijing_tz = timezone(timedelta(hours=8))
    return datetime.now(beijing_tz).strftime("%Y-%m-%d %H:%M:%S")

def get_env_var(var_name, suffix="", default=None):
    return os.getenv(f"{var_name}{suffix}", default)

def get_orders_pending(trade_api, account_prefix=""):
    for attempt in range(MAX_RETRIES + 1):
        try:
            result = trade_api.get_order_list(instId=INST_ID, state="live")
            if result and 'code' in result and result['code'] == '0' and 'data' in result:
                return result['data']
        except Exception as e:
            print(f"[{get_beijing_time()}] {account_prefix} [ORDERS] 获取未成交订单异常: {str(e)}")
        if attempt < MAX_RETRIES:
            time.sleep(RETRY_DELAY)
    return []

def cancel_pending_open_orders(trade_api, account_prefix=""):
    all_pending_orders = get_orders_pending(trade_api, account_prefix)
    cancel_orders = []
    for order in all_pending_orders:
        if order.get('ordType', '') == 'limit' and order.get('state', '') == 'live':
            cancel_orders.append({"instId": INST_ID, "ordId": order['ordId']})
    if not cancel_orders:
        return False
    for attempt in range(MAX_RETRIES + 1):
        try:
            cancel_data = {"cancels": cancel_orders}
            result = trade_api._request('POST', '/api/v5/trade/cancel-batch-orders', body=cancel_data)
            if result and 'code' in result and result['code'] == '0':
                time.sleep(2)
                return True
        except Exception as e:
            print(f"[{get_beijing_time()}] [CANCEL] 撤销订单异常: {str(e)}")
        if attempt < MAX_RETRIES:
            time.sleep(RETRY_DELAY)
    return False

def analyze_kline(kline_list):
    # kline_list: 最新在前，K1=0, K2=1, ..., K7=6
    if len(kline_list) < 7:
        return None, None, None
    # K2为最新K线
    o2 = float(kline_list[1][1])
    c2 = float(kline_list[1][4])
    body2 = abs(c2 - o2) / o2
    # K3为方向判断
    o3 = float(kline_list[2][1])
    c3 = float(kline_list[2][4])
    is_long = c3 > o3
    is_short = c3 < o3
    # K3~K6总单向振幅
    total_range = 0.0
    for i in range(2, 6):
        oi = float(kline_list[i][1])
        ci = float(kline_list[i][4])
        total_range += abs(ci - oi) / oi
    # 满足条件
    can_entry = (body2 > MIN_BODY1) and (body2 < MAX_BODY1) and (total_range < MAX_TOTAL_RANGE)
    entry_price = c2
    signal = None
    if can_entry:
        if is_long:
            signal = "LONG"
        elif is_short:
            signal = "SHORT"
    return signal, entry_price, {
        "body2": body2,
        "total_range": total_range,
        "is_long": is_long,
        "is_short": is_short,
        "can_entry": can_entry
    }

def generate_clord_id():
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    random_str = ''.join(random.choices(string.ascii_letters + string.digits, k=6))
    return f"VINE{timestamp}{random_str}"[:32]

def process_account_trading(account_suffix, signal, entry_price):
    suffix = account_suffix if account_suffix else ""
    account_prefix = f"[ACCOUNT-{suffix}]" if suffix else "[ACCOUNT]"
    api_key = get_env_var("OKX_API_KEY", suffix)
    secret_key = get_env_var("OKX_SECRET_KEY", suffix)
    passphrase = get_env_var("OKX_PASSPHRASE", suffix)
    flag = get_env_var("OKX_FLAG", suffix, "0")
    if not all([api_key, secret_key, passphrase]):
        print(f"[{get_beijing_time()}] {account_prefix} [ERROR] 账户信息不完整或未配置")
        return
    try:
        trade_api = Trade.TradeAPI(api_key, secret_key, passphrase, False, flag)
        print(f"[{get_beijing_time()}] {account_prefix} API初始化成功")
    except Exception as e:
        print(f"[{get_beijing_time()}] {account_prefix} [ERROR] API初始化失败: {str(e)}")
        return
    print(f"[{get_beijing_time()}] {account_prefix} [ORDER] 检测到信号，先撤销现有开仓订单")
    cancel_pending_open_orders(trade_api, account_prefix)
    # 动态计算下单数量
    trade_value = MARGIN * LEVERAGE
    raw_qty = trade_value / entry_price
    qty = int((raw_qty + 9) // 10 * 10)
    if qty == 0:
        print(f"[{get_beijing_time()}] {account_prefix} [ERROR] 计算数量为0，放弃交易")
        notification_service.send_bark_notification(
            f"{account_prefix} 交易失败",
            f"计算数量为0，放弃交易\n入场价格: {entry_price:.4f}\n保证金: {MARGIN} USDT\n杠杆: {LEVERAGE}倍",
            group="OKX自动交易通知"
        )
        return
    # 止盈止损
    if signal == "LONG":
        take_profit_price = round(entry_price * (1 + TAKE_PROFIT_PERCENT), 5)
        stop_loss_price = round(entry_price * (1 - STOP_LOSS_PERCENT), 5)
    else:
        take_profit_price = round(entry_price * (1 - TAKE_PROFIT_PERCENT), 5)
        stop_loss_price = round(entry_price * (1 + STOP_LOSS_PERCENT), 5)
    cl_ord_id = generate_clord_id()
    attach_algo_ord = {
        "attachAlgoClOrdId": generate_clord_id(),
        "tpTriggerPx": str(take_profit_price),
        "tpOrdPx": "-1",
        "tpOrdKind": "condition",
        "slTriggerPx": str(stop_loss_price),
        "slOrdPx": "-1",
        "tpTriggerPxType": "last",
        "slTriggerPxType": "last"
    }
    order_params = {
        "instId": INST_ID,
        "tdMode": "cross",
        "side": "buy" if signal == "LONG" else "sell",
        "ordType": "limit",
        "px": str(entry_price),
        "sz": str(qty),
        "clOrdId": cl_ord_id,
        "posSide": "long" if signal == "LONG" else "short",
        "attachAlgoOrds": [attach_algo_ord]
    }
    print(f"[{get_beijing_time()}] {account_prefix} [ORDER] 准备下单参数: {json.dumps(order_params, indent=2)}")
    for attempt in range(MAX_RETRIES + 1):
        try:
            order_result = trade_api.place_order(**order_params)
            print(f"[{get_beijing_time()}] {account_prefix} [ORDER] 订单提交结果: {json.dumps(order_result)}")
            break
        except Exception as e:
            print(f"[{get_beijing_time()}] {account_prefix} [ORDER] 下单异常 (尝试 {attempt+1}/{MAX_RETRIES+1}): {str(e)}")
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY)
    notification_service.send_trading_notification(
        account_name=account_prefix,
        inst_id=INST_ID,
        signal_type=signal,
        entry_price=entry_price,
        size=qty,
        margin=MARGIN,
        take_profit_price=take_profit_price,
        stop_loss_price=stop_loss_price,
        success=True,
        error_msg=""
    )

def get_kline_data():
    suffix = ACCOUNT_SUFFIXES[0] if ACCOUNT_SUFFIXES else ""
    api_key = get_env_var("OKX_API_KEY", suffix)
    secret_key = get_env_var("OKX_SECRET_KEY", suffix)
    passphrase = get_env_var("OKX_PASSPHRASE", suffix)
    flag = get_env_var("OKX_FLAG", suffix, "0")
    if not all([api_key, secret_key, passphrase]):
        print(f"[{get_beijing_time()}] [ERROR] 账户信息不完整，无法获取K线数据")
        return None, None, None
    try:
        market_api = MarketData.MarketAPI(api_key, secret_key, passphrase, False, flag)
    except Exception as e:
        print(f"[{get_beijing_time()}] [ERROR] K线API初始化失败: {str(e)}")
        return None, None, None
    for attempt in range(MAX_RETRIES + 1):
        try:
            result = market_api.get_candlesticks(instId=INST_ID, bar=BAR, limit=str(LIMIT))
            break
        except Exception as e:
            print(f"[{get_beijing_time()}] [MARKET] 获取K线数据异常 (尝试 {attempt+1}/{MAX_RETRIES+1}): {str(e)}")
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY)
            else:
                return None, None, None
    if not result or 'data' not in result or len(result['data']) < 7:
        print(f"[{get_beijing_time()}] [ERROR] 获取K线数据失败或数据不足")
        return None, None, None
    kline_list = result['data']
    signal, entry_price, amp_info = analyze_kline(kline_list)
    print(f"[{get_beijing_time()}] [KLINE] 分析结果: {amp_info}")
    return signal, entry_price, amp_info

if __name__ == "__main__":
    print(f"[{get_beijing_time()}] [INFO] 开始VINE自动交易策略")
    signal, entry_price, amp_info = get_kline_data()
    if not signal:
        print(f"[{get_beijing_time()}] [INFO] 未检测到交易信号")
        if amp_info:
            print(f"[{get_beijing_time()}] [AMP_DETAIL] "
                  f"K2实体振幅: {amp_info['body2']:.4f} "
                  f"K3~K6总振幅: {amp_info['total_range']:.4f}")
        else:
            print(f"[{get_beijing_time()}] [ERROR] 无K线数据")
        exit(0)
    print(f"[{get_beijing_time()}] [INFO] 开始处理所有账户交易")
    for suffix in ACCOUNT_SUFFIXES:
        process_account_trading(suffix, signal, entry_price)
    print(f"[{get_beijing_time()}] [INFO] 所有账户交易处理完成") 