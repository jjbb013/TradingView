"""
任务名称
name: OKX TRUMP 自动交易 PROD
定时规则
cron: 1 */15 * * * *
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
# 交易标的参数
INST_ID = "TRUMP-USDT-SWAP"  # 交易标的
BAR = "1m"  # K线规格
LIMIT = 2  # 获取K线数量
LEVERAGE = 10  # 杠杆倍数
SizePoint = 0  # 下单数量的小数点保留位数
CONTRACT_FACE_VALUE = 10  # TRUMP-USDT-SWAP合约面值为10美元

# 策略参数
MARGIN = 10  # 保证金(USDT)
TAKE_PROFIT_PERCENT = 0.02  # 止盈2%
STOP_LOSS_PERCENT = 0.03    # 止损3%
AMPLITUDE_PERCENT = 0.05    # 振幅5%

# 环境变量账户后缀，支持多账号
ACCOUNT_SUFFIXES = ["", "1", "2", "3"]

# 网络请求重试配置
MAX_RETRIES = 3
RETRY_DELAY = 2

# 价格比较容差（避免因微小价格波动导致的误判）
PRICE_TOLERANCE = 0.0001  # 0.01%的容差

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
                print(f"[{get_beijing_time()}] {account_prefix} [ORDERS] 成功获取{len(result['data'])}个未成交订单")
                return result['data']
            error_msg = result.get('msg', '') if result else '无响应'
            print(f"[{get_beijing_time()}] {account_prefix} [ORDERS] 获取未成交订单失败: {error_msg}")
        except Exception as e:
            print(f"[{get_beijing_time()}] {account_prefix} [ORDERS] 获取未成交订单异常 (尝试 {attempt+1}/{MAX_RETRIES+1}): {str(e)}")
        if attempt < MAX_RETRIES:
            print(f"[{get_beijing_time()}] {account_prefix} [ORDERS] 重试中... ({attempt+1}/{MAX_RETRIES})")
            time.sleep(RETRY_DELAY)
    print(f"[{get_beijing_time()}] {account_prefix} [ORDERS] 所有尝试失败")
    return []

def cancel_pending_open_orders(trade_api, account_prefix=""):
    all_pending_orders = get_orders_pending(trade_api, account_prefix)
    cancel_orders = []
    for order in all_pending_orders:
        if order.get('ordType', '') == 'limit' and order.get('state', '') == 'live':
            cancel_orders.append({"instId": INST_ID, "ordId": order['ordId']})
    if not cancel_orders:
        print(f"[{get_beijing_time()}] {account_prefix} [CANCEL] 无需要撤销的开仓订单")
        return False
    for attempt in range(MAX_RETRIES + 1):
        try:
            cancel_data = {"cancels": cancel_orders}
            print(f"[{get_beijing_time()}] {account_prefix} [CANCEL] 正在批量撤销{len(cancel_orders)}个开仓订单 (尝试 {attempt+1}/{MAX_RETRIES+1})")
            result = trade_api._request('POST', '/api/v5/trade/cancel-batch-orders', body=cancel_data)
            if result and 'code' in result and result['code'] == '0':
                print(f"[{get_beijing_time()}] {account_prefix} [CANCEL] 所有{len(cancel_orders)}个订单撤销成功")
                time.sleep(2)
                return True
            error_msg = result.get('msg', '') if result else '无响应'
            print(f"[{get_beijing_time()}] {account_prefix} [CANCEL] 批量撤销失败: {error_msg}")
        except Exception as e:
            print(f"[{get_beijing_time()}] {account_prefix} [CANCEL] 撤销订单异常 (尝试 {attempt+1}/{MAX_RETRIES+1}): {str(e)}")
        if attempt < MAX_RETRIES:
            print(f"[{get_beijing_time()}] {account_prefix} [CANCEL] 重试中... ({attempt+1}/{MAX_RETRIES})")
            time.sleep(RETRY_DELAY)
    print(f"[{get_beijing_time()}] {account_prefix} [CANCEL] 所有尝试失败")
    return False

def analyze_kline(kline):
    open_price = float(kline[1])
    high_price = float(kline[2])
    low_price = float(kline[3])
    close_price = float(kline[4])
    amplitude = (high_price - low_price) / low_price
    is_green = close_price > open_price
    is_red = close_price < open_price
    signal = None
    entry_price = None
    if amplitude >= AMPLITUDE_PERCENT:
        entry_price = close_price
        signal = 'SHORT' if is_green else 'LONG'
    return signal, entry_price, {
        'open': open_price,
        'high': high_price,
        'low': low_price,
        'close': close_price,
        'amplitude': amplitude,
        'is_green': is_green,
        'is_red': is_red,
        'signal': signal,
        'entry_price': entry_price
    }

def generate_clord_id():
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    random_str = ''.join(random.choices(string.ascii_letters + string.digits, k=6))
    return f"TRUMP{timestamp}{random_str}"[:32]

def get_current_price(market_api, inst_id, account_prefix=""):
    for attempt in range(MAX_RETRIES + 1):
        try:
            result = market_api.get_ticker(instId=inst_id)
            if result and 'code' in result and result['code'] == '0' and 'data' in result:
                current_price = float(result['data'][0]['last'])
                print(f"[{get_beijing_time()}] {account_prefix} [PRICE] {inst_id} 当前价格: {current_price}")
                return current_price
            else:
                error_msg = result.get('msg', '') if result else '无响应'
                print(f"[{get_beijing_time()}] {account_prefix} [PRICE] 获取{inst_id}价格失败: {error_msg}")
        except Exception as e:
            print(f"[{get_beijing_time()}] {account_prefix} [PRICE] 获取{inst_id}价格异常 (尝试 {attempt+1}/{MAX_RETRIES+1}): {str(e)}")
        if attempt < MAX_RETRIES:
            print(f"[{get_beijing_time()}] {account_prefix} [PRICE] 重试中... ({attempt+1}/{MAX_RETRIES})")
            time.sleep(RETRY_DELAY)
    print(f"[{get_beijing_time()}] {account_prefix} [PRICE] 获取{inst_id}价格失败")
    return None

def get_pending_orders(trade_api, inst_id, account_prefix=""):
    for attempt in range(MAX_RETRIES + 1):
        try:
            result = trade_api.get_order_list(instId=inst_id, state="live")
            if result and 'code' in result and result['code'] == '0' and 'data' in result:
                orders = result['data']
                print(f"[{get_beijing_time()}] {account_prefix} [ORDERS] {inst_id} 获取到{len(orders)}个未成交订单")
                return orders
            else:
                error_msg = result.get('msg', '') if result else '无响应'
                print(f"[{get_beijing_time()}] {account_prefix} [ORDERS] 获取{inst_id}未成交订单失败: {error_msg}")
        except Exception as e:
            print(f"[{get_beijing_time()}] {account_prefix} [ORDERS] 获取{inst_id}未成交订单异常 (尝试 {attempt+1}/{MAX_RETRIES+1}): {str(e)}")
        if attempt < MAX_RETRIES:
            print(f"[{get_beijing_time()}] {account_prefix} [ORDERS] 重试中... ({attempt+1}/{MAX_RETRIES})")
            time.sleep(RETRY_DELAY)
    print(f"[{get_beijing_time()}] {account_prefix} [ORDERS] 获取{inst_id}未成交订单失败")
    return []

def should_cancel_order(order, current_price, account_prefix=""):
    try:
        ord_id = order['ordId']
        side = order['side']
        pos_side = order.get('posSide', '')
        order_price = float(order['px'])
        is_long = (side == 'buy' and pos_side == 'long') or (side == 'buy' and pos_side == '')
        is_short = (side == 'sell' and pos_side == 'short') or (side == 'sell' and pos_side == '')
        if not (is_long or is_short):
            print(f"[{get_beijing_time()}] {account_prefix} [CHECK] 订单{ord_id} 方向不明确: side={side}, posSide={pos_side}")
            return False, "方向不明确", None
        take_profit_price = None
        attach_algo_ords = order.get('attachAlgoOrds', [])
        if attach_algo_ords and isinstance(attach_algo_ords, list) and len(attach_algo_ords) > 0 and 'tpTriggerPx' in attach_algo_ords[0]:
            take_profit_price = float(attach_algo_ords[0]['tpTriggerPx'])
        else:
            linked_algo = order.get('linkedAlgoOrd', {})
            if linked_algo and 'tpTriggerPx' in linked_algo:
                take_profit_price = float(linked_algo['tpTriggerPx'])
            else:
                return False, "无止盈价格信息", None
        should_cancel = False
        reason = ""
        if is_long:
            if current_price > take_profit_price * (1 + PRICE_TOLERANCE):
                should_cancel = True
                reason = f"做多订单，当前价格({current_price:.4f})已超过止盈价格({take_profit_price:.4f})"
        elif is_short:
            if current_price < take_profit_price * (1 - PRICE_TOLERANCE):
                should_cancel = True
                reason = f"做空订单，当前价格({current_price:.4f})已低于止盈价格({take_profit_price:.4f})"
        return should_cancel, reason, take_profit_price
    except Exception as e:
        print(f"[{get_beijing_time()}] {account_prefix} [CHECK] 判断订单{order.get('ordId', 'unknown')}时异常: {str(e)}")
        return False, f"判断异常: {str(e)}", None

def cancel_order(trade_api, inst_id, ord_id, account_prefix=""):
    for attempt in range(MAX_RETRIES + 1):
        try:
            result = trade_api.cancel_order(instId=inst_id, ordId=ord_id)
            if result and 'code' in result and result['code'] == '0':
                print(f"[{get_beijing_time()}] {account_prefix} [CANCEL] 订单{ord_id}撤销成功")
                return True, "撤销成功"
            else:
                error_msg = result.get('msg', '') if result else '无响应'
                print(f"[{get_beijing_time()}] {account_prefix} [CANCEL] 订单{ord_id}撤销失败: {error_msg}")
        except Exception as e:
            print(f"[{get_beijing_time()}] {account_prefix} [CANCEL] 订单{ord_id}撤销异常 (尝试 {attempt+1}/{MAX_RETRIES+1}): {str(e)}")
        if attempt < MAX_RETRIES:
            print(f"[{get_beijing_time()}] {account_prefix} [CANCEL] 重试中... ({attempt+1}/{MAX_RETRIES})")
            time.sleep(RETRY_DELAY)
    print(f"[{get_beijing_time()}] {account_prefix} [CANCEL] 订单{ord_id}撤销失败")
    return False, "撤销失败"

def process_account_trading(account_suffix, signal, entry_price, amp_info):
    suffix = account_suffix if account_suffix else ""
    account_prefix = f"[ACCOUNT-{suffix}]" if suffix else "[ACCOUNT]"
    api_key = get_env_var("OKX_API_KEY", suffix)
    secret_key = get_env_var("OKX_SECRET_KEY", suffix)
    passphrase = get_env_var("OKX_PASSPHRASE", suffix)
    flag = get_env_var("OKX_FLAG", suffix, "0")
    account_name = get_env_var("OKX_ACCOUNT_NAME", suffix) or f"账户{suffix}" if suffix else "默认账户"
    if not all([api_key, secret_key, passphrase]):
        print(f"[{get_beijing_time()}] {account_prefix} [ERROR] 账户信息不完整或未配置")
        return
    try:
        trade_api = Trade.TradeAPI(api_key, secret_key, passphrase, False, flag)
        market_api = MarketData.MarketAPI(api_key, secret_key, passphrase, False, flag)
        print(f"[{get_beijing_time()}] {account_prefix} API初始化成功 - {account_name}")
    except Exception as e:
        print(f"[{get_beijing_time()}] {account_prefix} [ERROR] API初始化失败: {str(e)}")
        return
    # 新增：下单前检查未成交委托单，若当前价格已超过止盈价则撤单
    current_price = get_current_price(market_api, INST_ID, account_prefix)
    if current_price is not None:
        pending_orders = get_pending_orders(trade_api, INST_ID, account_prefix)
        for order in pending_orders:
            should_cancel, reason, take_profit_price = should_cancel_order(order, current_price, account_prefix)
            if should_cancel:
                cancel_order(trade_api, INST_ID, order['ordId'], account_prefix)
    print(f"[{get_beijing_time()}] {account_prefix} [ORDER] 检测到信号，先撤销现有开仓订单")
    cancel_pending_open_orders(trade_api, account_prefix)
    # 计算下单数量（保证金10USDT，10倍杠杆，价值约100USDT，向上取整为10的倍数）
    trade_value = MARGIN * LEVERAGE
    raw_qty = trade_value / entry_price
    qty = int((raw_qty + 9) // 10 * 10)  # 向上取整为10的倍数
    if qty == 0:
        print(f"[{get_beijing_time()}] {account_prefix} [ERROR] 计算数量为0，放弃交易")
        notification_service.send_bark_notification(
            f"{account_prefix} 交易失败",
            f"计算数量为0，放弃交易\n入场价格: {entry_price:.4f}\n保证金: {MARGIN} USDT\n杠杆: {LEVERAGE}倍",
            group="OKX自动交易通知"
        )
        return
    print(f"[{get_beijing_time()}] {account_prefix} [SIZE_CALC] 下单数量: {qty} (10的倍数)")
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
            if order_result and 'code' in order_result and order_result['code'] == '0':
                success = True
                error_msg = ""
            else:
                success = False
                error_msg = order_result.get('msg', '') if order_result else '下单失败，无响应'
            break
        except Exception as e:
            print(f"[{get_beijing_time()}] {account_prefix} [ORDER] 下单异常 (尝试 {attempt+1}/{MAX_RETRIES+1}): {str(e)}")
            success = False
            error_msg = str(e)
            if attempt < MAX_RETRIES:
                print(f"[{get_beijing_time()}] {account_prefix} [ORDER] 重试中... ({attempt+1}/{MAX_RETRIES})")
                time.sleep(RETRY_DELAY)
            else:
                print(f"[{get_beijing_time()}] {account_prefix} [ORDER] 所有尝试失败")
    notification_service.send_trading_notification(
        account_name=account_name,
        inst_id=INST_ID,
        signal_type=signal,
        entry_price=entry_price,
        size=qty,
        margin=MARGIN,
        take_profit_price=take_profit_price,
        stop_loss_price=stop_loss_price,
        success=success,
        error_msg=error_msg
    )
    print(f"[{get_beijing_time()}] {account_prefix} [SIGNAL] {signal}@{entry_price:.4f}")
    print(f"[{get_beijing_time()}] {account_prefix} [ORDER] {json.dumps(order_params)}")
    print(f"[{get_beijing_time()}] {account_prefix} [RESULT] {json.dumps(order_result)}")

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
        print(f"[{get_beijing_time()}] [MARKET] K线API初始化成功")
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
                print(f"[{get_beijing_time()}] [MARKET] 重试中... ({attempt+1}/{MAX_RETRIES})")
                time.sleep(RETRY_DELAY)
            else:
                print(f"[{get_beijing_time()}] [MARKET] 所有尝试失败")
                return None, None, None
    if not result or 'data' not in result or len(result['data']) < 2:
        print(f"[{get_beijing_time()}] [ERROR] 获取K线数据失败或数据不足")
        return None, None, None
    prev_kline = result['data'][1]
    print(f"[{get_beijing_time()}] [DEBUG] 正在分析前一根K线: {prev_kline}")
    signal, entry_price, amp_info = analyze_kline(prev_kline)
    print(f"[{get_beijing_time()}] [KLINE] 分析结果:")
    print(f"  标的: {INST_ID} | K线规格: {BAR}")
    print(f"  开盘价: {amp_info['open']:.4f}")
    print(f"  最高价: {amp_info['high']:.4f}")
    print(f"  最低价: {amp_info['low']:.4f}")
    print(f"  收盘价: {amp_info['close']:.4f}")
    print(f"  振幅: {amp_info['amplitude']*100:.2f}%")
    print(f"  是否为阳线: {amp_info['is_green']}")
    print(f"  是否为阴线: {amp_info['is_red']}")
    print(f"  信号: {signal if signal else '无信号'}")
    print(f"  入场价: {entry_price if entry_price else 'N/A'}")
    if amp_info['amplitude'] >= AMPLITUDE_PERCENT:
        notification_service.send_amplitude_alert(
            symbol=INST_ID,
            amplitude=amp_info['amplitude']*100,
            threshold=AMPLITUDE_PERCENT*100,
            open_price=amp_info['open'],
            latest_price=amp_info['close']
        )
        print(f"[{get_beijing_time()}] [AMPLITUDE] 发送振幅预警通知")
    return signal, entry_price, amp_info

if __name__ == "__main__":
    print(f"[{get_beijing_time()}] [INFO] 开始TRUMP自动交易策略")
    signal, entry_price, amp_info = get_kline_data()
    if not signal:
        print(f"[{get_beijing_time()}] [INFO] 未检测到交易信号")
        exit(0)
    print(f"[{get_beijing_time()}] [INFO] 开始处理所有账户交易")
    for suffix in ACCOUNT_SUFFIXES:
        process_account_trading(suffix, signal, entry_price, amp_info)
    print(f"[{get_beijing_time()}] [INFO] 所有账户交易处理完成") 