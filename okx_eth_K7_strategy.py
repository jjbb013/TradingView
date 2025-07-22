"""
任务名称
name: OKX ETH K6趋势策略
定时规则
cron: 3 */5 * * * *
基于Pine脚本的ETH 5分钟K1振幅+K2方向顺势策略
策略说明：
- K1为当前K线，K2~K5为前4根K线
- K1实体振幅在[min_body1, max_body1]之间，且K2~K5总单向振幅小于max_total_range时，顺K2方向开仓
- 多空均可重复开仓（pyramiding>1）
- 止盈止损按参数自动计算
- 采用限价单，滑点1%
- 每单保证金10USDT，杠杆10倍
"""

import os
from utils.okx_utils import (
    get_kline_data, get_orders_pending, cancel_pending_open_orders,
    build_order_params, generate_clord_id, send_bark_notification,
    init_trade_api, get_env_var, get_shanghai_time
)
from utils.notification_service import notification_service

# ========== 策略参数 ==========
INST_ID = "ETH-USDT-SWAP"
BAR = "5m"
LIMIT = 6
LEVERAGE = 10  #杠杆倍数
QTY_USDT = 10  # 保证金10USDT
CONTRACT_FACE_VALUE = 0.01  # ETH合约面值合约最小值
MIN_BODY1 = 0.012
MAX_BODY1 = 0.025
MAX_TOTAL_RANGE = 0.05
TAKE_PROFIT_PERC = 0.015
STOP_LOSS_PERC = 0.01
MAX_RETRIES = 3
RETRY_DELAY = 2

# ========== 测试用假K线数据（可触发空单） ==========
TEST_MODE = False  # 测试时为True，实盘请设为False
FAKE_KLINES_SHORT = [
    ["1710000000000", "2665", "2670", "2655", "2667", "100", "100", "100", "1"],  # 最新K线（无用）
    ["1709999990000", "2665", "2670", "2655", "2640", "100", "100", "100", "1"],  # K1: open=2665, close=2640, body1≈0.0094
    ["1709999980000", "2680", "2685", "2675", "2660", "100", "100", "100", "1"],  # K2: open=2680, close=2660, is_short=True
    ["1709999970000", "2695", "2700", "2690", "2690", "100", "100", "100", "1"],
    ["1709999960000", "2710", "2715", "2705", "2705", "100", "100", "100", "1"],
    ["1709999950000", "2725", "2730", "2720", "2720", "100", "100", "100", "1"],
]

# ========== 信号分析 ==========
def analyze_signal(klines):
    if len(klines) < 6:
        return {"can_entry": False}
    k1_open = float(klines[1][1])
    k1_close = float(klines[1][4])
    body1 = abs(k1_close - k1_open) / k1_open
    k2_open = float(klines[2][1])
    k2_close = float(klines[2][4])
    # 只以K2方向为准
    k2_is_long = k2_close > k2_open
    k2_is_short = k2_close < k2_open
    total_range = 0.0
    for i in range(2, 6):
        o = float(klines[i][1])
        c = float(klines[i][4])
        total_range += abs(c - o) / o
    can_entry = (body1 > MIN_BODY1) and (body1 < MAX_BODY1) and (total_range < MAX_TOTAL_RANGE)
    entry_price = k1_close
    if k2_is_long:
        take_profit = entry_price * (1 + TAKE_PROFIT_PERC)
        stop_loss = entry_price * (1 - STOP_LOSS_PERC)
        order_side = "buy"
        pos_side = "long"
    elif k2_is_short:
        take_profit = entry_price * (1 - TAKE_PROFIT_PERC)
        stop_loss = entry_price * (1 + STOP_LOSS_PERC)
        order_side = "sell"
        pos_side = "short"
    else:
        return {"can_entry": False}
    return {
        'can_entry': can_entry,
        'entry_price': entry_price,
        'take_profit': take_profit,
        'stop_loss': stop_loss,
        'order_side': order_side,
        'pos_side': pos_side,
        'body1': body1,
        'total_range': total_range
    }

# ========== 主流程 ==========
def main():
    api_key = get_env_var("OKX_API_KEY")
    secret_key = get_env_var("OKX_SECRET_KEY")
    passphrase = get_env_var("OKX_PASSPHRASE")
    flag = get_env_var("OKX_FLAG", "0")
    trade_api = init_trade_api(api_key, secret_key, passphrase, flag)
    if TEST_MODE:
        klines = FAKE_KLINES_SHORT
        print(f"[{get_shanghai_time()}] [INFO] 已启用假K线数据进行测试")
    else:
        klines = get_kline_data(api_key, secret_key, passphrase, INST_ID, BAR, limit=LIMIT)
    if not klines or len(klines) < 6:
        print(f"[{get_shanghai_time()}] [ERROR] K线数据不足，终止执行")
        return
    latest_close = float(klines[1][4])
    orders = get_orders_pending(trade_api, INST_ID)
    cancel_flag = False
    for order in orders:
        ord_type = order.get('ordType', '')
        side = order.get('side', '')
        pos_side = order.get('posSide', '')
        attach_algo = order.get('attachAlgoOrds', [])
        tp_px = None
        for algo in attach_algo:
            if 'tpTriggerPx' in algo:
                tp_px = float(algo['tpTriggerPx'])
        if ord_type == 'limit' and side == 'buy' and pos_side == 'long' and tp_px:
            if latest_close >= tp_px:
                print(f"[{get_shanghai_time()}] [INFO] 多单委托止盈已到，撤销委托: {order['ordId']}")
                cancel_pending_open_orders(trade_api, INST_ID)
                cancel_flag = True
        if ord_type == 'limit' and side == 'sell' and pos_side == 'short' and tp_px:
            if latest_close <= tp_px:
                print(f"[{get_shanghai_time()}] [INFO] 空单委托止盈已到，撤销委托: {order['ordId']}")
                cancel_pending_open_orders(trade_api, INST_ID)
                cancel_flag = True
    if cancel_flag:
        print(f"[{get_shanghai_time()}] [INFO] 已撤销委托，重新获取K线与信号，继续尝试开仓")
        if TEST_MODE:
            klines = FAKE_KLINES_SHORT
        else:
            klines = get_kline_data(api_key, secret_key, passphrase, INST_ID, BAR, limit=LIMIT)
        if not klines or len(klines) < 6:
            print(f"[{get_shanghai_time()}] [ERROR] K线数据不足，终止执行")
            return
        latest_close = float(klines[1][4])
        # 重新获取未成交委托
        orders = get_orders_pending(trade_api, INST_ID)
        if orders:
            print(f"[{get_shanghai_time()}] [INFO] 撤单后仍有未成交委托，跳过本次开仓")
            return
    if orders:
        print(f"[{get_shanghai_time()}] [INFO] 存在未成交委托，跳过本次开仓")
        return
    print(f"[{get_shanghai_time()}] [INFO] 无未成交委托，进入信号判断")
    signal = analyze_signal(klines)
    qty = round(QTY_USDT / signal.get('entry_price', latest_close) / CONTRACT_FACE_VALUE, 2)
    print(f"[{get_shanghai_time()}] [INFO] 本次计算下单数量: {qty:.2f}")
    if not signal['can_entry']:
        print(f"[{get_shanghai_time()}] [INFO] 未满足开仓条件")
        return
    if qty < 0.01:
        print(f"[{get_shanghai_time()}] [INFO] 下单数量过小(<0.01)，跳过")
        return
    order_params = build_order_params(
        inst_id=INST_ID,
        side=signal['order_side'],
        entry_price=round(signal['entry_price'], 2),
        size=qty,
        pos_side=signal['pos_side'],
        take_profit=round(signal['take_profit'], 2),
        stop_loss=round(signal['stop_loss'], 2),
        prefix="ETH"
    )
    print(f"[{get_shanghai_time()}] [INFO] 下单参数: {order_params}")
    order_result = trade_api.place_order(**order_params)
    print(f"[{get_shanghai_time()}] [INFO] 下单结果: {order_result}")
    pos_side = signal.get('pos_side')
    signal_type = str(pos_side) if isinstance(pos_side, str) and pos_side in ('long', 'short') else "无信号"
    notification_service.send_trading_notification(
        account_name="ETH-K6 策略",
        inst_id=INST_ID,
        signal_type=signal_type,
        entry_price=signal['entry_price'],
        size=qty,
        margin=QTY_USDT,
        take_profit_price=signal['take_profit'],
        stop_loss_price=signal['stop_loss'],
        success=(order_result and order_result.get('code') == '0'),
        error_msg=order_result.get('msg', '') if order_result else '',
        order_params=order_params,
        order_result=order_result
    )

if __name__ == "__main__":
    main() 