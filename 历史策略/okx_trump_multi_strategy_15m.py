"""
TRUMP-USDT-SWAP 15m多参数自动交易策略
每15分钟执行一次，依次用3组参数分别执行交易
"""
from notification_service import notification_service
import okx.MarketData as MarketData
import okx.Trade as Trade
import os
import json
import random
import string
import time
from datetime import datetime, timezone, timedelta

# 3组参数
STRATEGY_PARAMS = [
    {"TAKE_PROFIT_PERCENT": 0.046, "STOP_LOSS_PERCENT": 0.046, "AMPLITUDE_PERCENT": 0.022},
    {"TAKE_PROFIT_PERCENT": 0.05,  "STOP_LOSS_PERCENT": 0.044, "AMPLITUDE_PERCENT": 0.012},
    {"TAKE_PROFIT_PERCENT": 0.042, "STOP_LOSS_PERCENT": 0.044, "AMPLITUDE_PERCENT": 0.012},
]

INST_ID = "TRUMP-USDT-SWAP"
BAR = "15m"
LEVERAGE = 10
MARGIN = 10
ACCOUNT_SUFFIXES = ["", "1", "2", "3"]
MAX_RETRIES = 3
RETRY_DELAY = 2
LIMIT = 2
PRICE_TOLERANCE = 0.0001
CONTRACT_FACE_VALUE = 10  # TRUMP合约面值
SizePoint = 0  # 下单数量小数点
PREFIX = "TRUMP"  # 订单号前缀

# 省略API密钥获取、撤单、下单等通用函数，直接复用主策略脚本的相关实现
# 只需在主流程中遍历3组参数，分别执行一次完整交易流程即可

def get_beijing_time():
    beijing_tz = timezone(timedelta(hours=8))
    return datetime.now(beijing_tz).strftime("%Y-%m-%d %H:%M:%S")

def get_env_var(var_name, suffix="", default=None):
    return os.getenv(f"{var_name}{suffix}", default)

def analyze_kline(kline, amplitude_percent):
    open_price = float(kline[1])
    high_price = float(kline[2])
    low_price = float(kline[3])
    close_price = float(kline[4])
    amplitude = (high_price - low_price) / low_price
    is_green = close_price > open_price
    is_red = close_price < open_price
    signal = None
    entry_price = None
    if amplitude >= amplitude_percent:
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

def generate_clord_id(prefix):
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    random_str = ''.join(random.choices(string.ascii_letters + string.digits, k=6))
    return f"{PREFIX}{timestamp}{random_str}"[:32]

def process_account_trading(account_suffix, signal, entry_price, amp_info, take_profit_percent, stop_loss_percent):
    suffix = account_suffix if account_suffix else ""
    account_prefix = f"[ACCOUNT-{suffix}]" if suffix else "[ACCOUNT]"
    api_key = get_env_var("OKX_API_KEY", suffix)
    secret_key = get_env_var("OKX_SECRET_KEY", suffix)
    passphrase = get_env_var("OKX_PASSPHRASE", suffix)
    flag = get_env_var("OKX_FLAG", suffix, "0")
    account_name = get_env_var("OKX_ACCOUNT_NAME", suffix) or f"账户{suffix}" if suffix else "默认账户"
    if not all([api_key, secret_key, passphrase]) or api_key is None or secret_key is None or passphrase is None or flag is None:
        print(f"[{get_beijing_time()}] {account_prefix} [ERROR] 账户信息不完整或未配置 (api_key/secret_key/passphrase/flag)")
        return
    try:
        trade_api = Trade.TradeAPI(str(api_key), str(secret_key), str(passphrase), False, str(flag))
        market_api = MarketData.MarketAPI(str(api_key), str(secret_key), str(passphrase), False, str(flag))
        print(f"[{get_beijing_time()}] {account_prefix} API初始化成功 - {account_name}")
    except Exception as e:
        print(f"[{get_beijing_time()}] {account_prefix} [ERROR] API初始化失败: {str(e)}")
        return
    # 计算合约数量（合约面值10美元，向下取整为10的倍数，最小10）
    raw_size = (MARGIN * LEVERAGE) / (CONTRACT_FACE_VALUE * entry_price)
    size_rounded = round(raw_size, SizePoint)
    if raw_size >= 1:
        size = int(size_rounded // 10) * 10
        if size == 0 and size_rounded >= 5:
            size = 10
            print(f"[{get_beijing_time()}] {account_prefix} [SIZE_ADJUST] 数量过小但≥5，调整为最小交易量10")
    else:
        size = 0
        print(f"[{get_beijing_time()}] {account_prefix} [ERROR] 计算数量过小: {size_rounded}，无法交易")
    if size == 0:
        print(f"[{get_beijing_time()}] {account_prefix} [ERROR] 最终数量为0，放弃交易")
        notification_service.send_bark_notification(
            f"{account_prefix} 交易失败",
            f"计算数量为0，放弃交易\n入场价格: {entry_price:.4f}\n保证金: {MARGIN} USDT\n杠杆: {LEVERAGE}倍",
            group="OKX自动交易通知"
        )
        return
    print(f"[{get_beijing_time()}] {account_prefix} [SIZE_CALC] 计算详情:")
    print(f"  原始数量: {raw_size:.4f}")
    print(f"  四舍五入后: {size_rounded}")
    print(f"  调整后数量: {size} (10的倍数)")
    if signal == "LONG":
        take_profit_price = round(entry_price * (1 + take_profit_percent), 5)
        stop_loss_price = round(entry_price * (1 - stop_loss_percent), 5)
    else:
        take_profit_price = round(entry_price * (1 - take_profit_percent), 5)
        stop_loss_price = round(entry_price * (1 + stop_loss_percent), 5)
    cl_ord_id = generate_clord_id(account_prefix)
    attach_algo_ord = {
        "attachAlgoClOrdId": generate_clord_id(account_prefix),
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
        "sz": str(size),
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
        size=size,
        margin=MARGIN,
        take_profit_price=take_profit_price,
        stop_loss_price=stop_loss_price,
        success=success,
        error_msg=error_msg
    )
    print(f"[{get_beijing_time()}] {account_prefix} [SIGNAL] {signal}@{entry_price:.4f}")
    print(f"[{get_beijing_time()}] {account_prefix} [ORDER] {json.dumps(order_params)}")
    print(f"[{get_beijing_time()}] {account_prefix} [RESULT] {json.dumps(order_result)}")

def get_kline_data(bar, amplitude_percent):
    suffix = ACCOUNT_SUFFIXES[0] if ACCOUNT_SUFFIXES else ""
    api_key = get_env_var("OKX_API_KEY", suffix)
    secret_key = get_env_var("OKX_SECRET_KEY", suffix)
    passphrase = get_env_var("OKX_PASSPHRASE", suffix)
    flag = get_env_var("OKX_FLAG", suffix, "0")
    if not all([api_key, secret_key, passphrase]) or api_key is None or secret_key is None or passphrase is None or flag is None:
        print(f"[{get_beijing_time()}] [ERROR] 账户信息不完整，无法获取K线数据 (api_key/secret_key/passphrase/flag)")
        return None, None, None
    try:
        market_api = MarketData.MarketAPI(str(api_key), str(secret_key), str(passphrase), False, str(flag))
        print(f"[{get_beijing_time()}] [MARKET] K线API初始化成功")
    except Exception as e:
        print(f"[{get_beijing_time()}] [ERROR] K线API初始化失败: {str(e)}")
        return None, None, None
    for attempt in range(MAX_RETRIES + 1):
        try:
            result = market_api.get_candlesticks(instId=INST_ID, bar=bar, limit=str(LIMIT))
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
    signal, entry_price, amp_info = analyze_kline(prev_kline, amplitude_percent)
    print(f"[{get_beijing_time()}] [KLINE] 分析结果:")
    print(f"  标的: {INST_ID} | K线规格: {bar}")
    print(f"  开盘价: {amp_info['open']:.4f}")
    print(f"  最高价: {amp_info['high']:.4f}")
    print(f"  最低价: {amp_info['low']:.4f}")
    print(f"  收盘价: {amp_info['close']:.4f}")
    print(f"  振幅: {amp_info['amplitude']*100:.2f}%")
    print(f"  是否为阳线: {amp_info['is_green']}")
    print(f"  是否为阴线: {amp_info['is_red']}")
    print(f"  信号: {signal if signal else '无信号'}")
    print(f"  入场价: {entry_price if entry_price else 'N/A'}")
    if amp_info['amplitude'] >= amplitude_percent:
        notification_service.send_amplitude_alert(
            symbol=INST_ID,
            amplitude=amp_info['amplitude']*100,
            threshold=amplitude_percent*100,
            open_price=amp_info['open'],
            latest_price=amp_info['close']
        )
        print(f"[{get_beijing_time()}] [AMPLITUDE] 发送振幅预警通知")
    return signal, entry_price, amp_info

if __name__ == "__main__":
    print(f"[{get_beijing_time()}] [INFO] 开始TRUMP多参数自动交易策略")
    for idx, params in enumerate(STRATEGY_PARAMS):
        print(f"\n===== 执行第{idx+1}组参数 =====")
        print(f"参数: 止盈={params['TAKE_PROFIT_PERCENT']}, 止损={params['STOP_LOSS_PERCENT']}, 振幅={params['AMPLITUDE_PERCENT']}")
        signal, entry_price, amp_info = get_kline_data(BAR, params['AMPLITUDE_PERCENT'])
        if not signal:
            print(f"[{get_beijing_time()}] [INFO] 未检测到交易信号 (参数组{idx+1})")
            continue
        print(f"[{get_beijing_time()}] [INFO] 开始处理所有账户交易 (参数组{idx+1})")
        for suffix in ACCOUNT_SUFFIXES:
            process_account_trading(suffix, signal, entry_price, amp_info, params['TAKE_PROFIT_PERCENT'], params['STOP_LOSS_PERCENT'])
        print(f"[{get_beijing_time()}] [INFO] 所有账户交易处理完成 (参数组{idx+1})")
    print(f"[{get_beijing_time()}] [INFO] 所有参数组交易处理完成") 