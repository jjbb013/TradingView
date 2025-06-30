"""
任务名称
name: OKX Vine 自动交易 PROD
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

# 尝试导入本地配置，如果不存在则使用环境变量
try:
    from config_local import *
    print("[INFO] 使用本地配置文件")
    IS_DEVELOPMENT = True
except ImportError:
    print("[INFO] 使用环境变量配置")
    IS_DEVELOPMENT = False

# ============== 可配置参数区域 ==============
# 交易标的参数
INST_ID = "VINE-USDT-SWAP"  # 交易标的
BAR = "5m"  # K线规格
LIMIT = 2  # 获取K线数量
LEVERAGE = 10  # 杠杆倍数
SizePoint = 0  # 下单数量的小数点保留位数
CONTRACT_FACE_VALUE = 10  # VINE-USDT-SWAP合约面值为10美元

# 振幅阈值参数
RANGE1_MIN = 1.0  # 振幅范围1最小值(1%)
RANGE1_MAX = 1.5  # 振幅范围1最大值(1.5%)
RANGE2_THRESHOLD = 2  # 振幅范围2阈值(2%)

# 交易执行参数
MARGIN = 5  # 保证金(USDT)
TAKE_PROFIT_PERCENT = 0.015  # 止盈比例改为1.5%
STOP_LOSS_PERCENT = 0.03  # 止损比例(3%)

# 环境变量账户后缀，支持多账号 (如OKX_API_KEY1, OKX_SECRET_KEY1, OKX_PASSPHRASE1)
ACCOUNT_SUFFIXES = ["", "1", "2", "3"]  # 空字符串代表无后缀的默认账号

# 前缀生成配置
PREFIX = "VINE"  # 使用标的名称作为前缀(如VINE)

# 网络请求重试配置
MAX_RETRIES = 3  # 最大重试次数
RETRY_DELAY = 2  # 重试间隔(秒)

# ==========================================

def get_beijing_time():
    """获取北京时间"""
    beijing_tz = timezone(timedelta(hours=8))
    return datetime.now(beijing_tz).strftime("%Y-%m-%d %H:%M:%S")


def get_env_var(var_name, suffix="", default=None):
    """获取环境变量或本地配置变量"""
    if IS_DEVELOPMENT:
        # 开发环境：从本地配置文件获取
        try:
            return globals()[f"{var_name}{suffix}"]
        except KeyError:
            return default
    else:
        # 生产环境：从环境变量获取
        return os.getenv(f"{var_name}{suffix}", default)


def get_orders_pending(trade_api, account_prefix=""):
    """获取当前账户下所有未成交订单信息"""
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


def get_pending_open_orders(trade_api, account_prefix=""):
    """
    获取需要撤销的开仓订单列表
    撤销所有相同标的的未成交限价开仓订单
    """
    try:
        all_pending_orders = get_orders_pending(trade_api, account_prefix)
        cancel_orders = []
        for order in all_pending_orders:
            ord_type = order.get('ordType', '')
            side = order.get('side', '')
            pos_side = order.get('posSide', '')
            is_limit_order = ord_type == 'limit'
            is_open_order = (
                (side == 'buy' and pos_side == 'long') or
                (side == 'sell' and pos_side == 'short')
            )
            if is_limit_order and is_open_order:
                cancel_orders.append({
                    "instId": INST_ID,
                    "ordId": order['ordId']
                })
                print(f"[{get_beijing_time()}] {account_prefix} [TO_CANCEL] 标记为待撤销: ordId={order['ordId']}, side={side}, posSide={pos_side}, ordType={ord_type}")
        return cancel_orders
    except Exception as e:
        print(f"[{get_beijing_time()}] {account_prefix} [ORDERS] 获取待撤销订单异常: {str(e)}")
        return []


def cancel_pending_open_orders(trade_api, account_prefix=""):
    """批量撤销需要取消的开仓订单"""
    cancel_orders = get_pending_open_orders(trade_api, account_prefix)
    if not cancel_orders:
        print(f"[{get_beijing_time()}] {account_prefix} [CANCEL] 无需要撤销的开仓订单")
        return False
    
    for attempt in range(MAX_RETRIES + 1):
        try:
            cancel_data = {"cancels": cancel_orders}
            print(f"[{get_beijing_time()}] {account_prefix} [CANCEL] 正在批量撤销{len(cancel_orders)}个开仓订单 (尝试 {attempt+1}/{MAX_RETRIES+1})")
            result = trade_api._request('POST', '/api/v5/trade/cancel-batch-orders', body=cancel_data)  # pylint: disable=protected-access
            if result and 'code' in result and result['code'] == '0':
                failed_orders = []
                for order_result in result['data']:
                    if order_result['sCode'] != '0':
                        failed_orders.append({
                            "ordId": order_result['ordId'],
                            "code": order_result['sCode'],
                            "msg": order_result['sMsg']
                        })
                if failed_orders:
                    print(f"[{get_beijing_time()}] {account_prefix} [CANCEL] 部分订单撤销失败: {json.dumps(failed_orders)}")
                else:
                    print(f"[{get_beijing_time()}] {account_prefix} [CANCEL] 所有{len(cancel_orders)}个订单撤销成功")
                    print(f"[{get_beijing_time()}] {account_prefix} [CANCEL] 等待2秒确保撤销操作完成...")
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
    """分析单个K线，返回信号、入场价和振幅信息"""
    # 解析K线数据
    timestamp = int(kline[0])
    open_price = float(kline[1])
    high_price = float(kline[2])
    low_price = float(kline[3])
    close_price = float(kline[4])

    # 计算并记录振幅变量
    body_change = abs(close_price - open_price)
    body_change_perc = body_change / open_price * 100
    total_range = high_price - low_price
    total_range_perc = total_range / low_price * 100

    # 检查条件
    in_range1 = (body_change_perc >= RANGE1_MIN) and (body_change_perc <= RANGE1_MAX)
    # 修改为实体振幅大于2%
    in_range2 = body_change_perc > RANGE2_THRESHOLD
    is_green = close_price > open_price
    is_red = close_price < open_price

    signal = None
    entry_price = None
    condition = ""

    # 判断是否满足交易条件
    if in_range1 or in_range2:
        if in_range1:
            entry_price = (high_price + low_price) / 2
            signal = 'LONG' if is_green else 'SHORT'
            condition = f"满足振幅范围1条件({RANGE1_MIN}%-{RANGE1_MAX}%)"
        elif in_range2:
            # 修改为使用收盘价入场
            entry_price = close_price
            # 保持反向交易信号
            signal = 'SHORT' if is_green else 'LONG'
            condition = f"满足振幅范围2条件(实体振幅> {RANGE2_THRESHOLD}%)"

    # 返回所有计算数据
    amp_info = {
        'timestamp': timestamp,
        'open': open_price,
        'high': high_price,
        'low': low_price,
        'close': close_price,
        'body_change': body_change,
        'body_change_perc': body_change_perc,
        'total_range': total_range,
        'total_range_perc': total_range_perc,
        'in_range1': in_range1,
        'in_range2': in_range2,
        'is_green': is_green,
        'is_red': is_red,
        'signal': signal,
        'entry_price': entry_price,
        'condition': condition
    }

    return signal, entry_price, amp_info


def generate_clord_id(prefix):
    """生成符合OKX要求的clOrdId：字母数字组合，1-32位"""
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    random_str = ''.join(random.choices(string.ascii_letters + string.digits, k=6))
    return f"{PREFIX}{timestamp}{random_str}"[:32]


def process_account_trading(account_suffix, signal, entry_price, amp_info):
    """处理单个账户的交易逻辑"""
    # 准备账户前缀标识
    suffix = account_suffix if account_suffix else ""  # 空后缀对应默认账户
    account_prefix = f"[ACCOUNT-{suffix}]" if suffix else "[ACCOUNT]"
    
    # 从环境变量获取账户信息
    api_key = get_env_var("OKX_API_KEY", suffix)
    secret_key = get_env_var("OKX_SECRET_KEY", suffix)
    passphrase = get_env_var("OKX_PASSPHRASE", suffix)
    flag = get_env_var("OKX_FLAG", suffix, "0")  # 默认实盘
    account_name = get_env_var("OKX_ACCOUNT_NAME", suffix) or f"账户{suffix}" if suffix else "默认账户"
    
    if not all([api_key, secret_key, passphrase]):
        print(f"[{get_beijing_time()}] {account_prefix} [ERROR] 账户信息不完整或未配置")
        return
    
    # 初始化API
    try:
        trade_api = Trade.TradeAPI(api_key, secret_key, passphrase, False, flag)
        print(f"[{get_beijing_time()}] {account_prefix} API初始化成功 - {account_name}")
    except Exception as e:
        print(f"[{get_beijing_time()}] {account_prefix} [ERROR] API初始化失败: {str(e)}")
        return
    
    # 1. 撤销现有的开仓订单
    print(f"[{get_beijing_time()}] {account_prefix} [ORDER] 检测到信号，先撤销现有开仓订单")
    canceled = cancel_pending_open_orders(trade_api, account_prefix)
    
    # 2. 计算合约数量（考虑合约面值）
    raw_size = (MARGIN * LEVERAGE) / (CONTRACT_FACE_VALUE * entry_price)
    size_rounded = round(raw_size, SizePoint)
    
    # 确保数量为10的整数倍
    if raw_size >= 1:
        # 向下取整到最近的10的倍数
        size = int(size_rounded // 10) * 10
        
        # 特殊处理：如果四舍五入后的值接近10的倍数但向下取整后为0
        if size == 0 and size_rounded >= 5:  # 如果大于等于5但小于10，使用最小交易量10
            size = 10
            print(f"[{get_beijing_time()}] {account_prefix} [SIZE_ADJUST] 数量过小但≥5，调整为最小交易量10")
    else:
        size = 0
        print(f"[{get_beijing_time()}] {account_prefix} [ERROR] 计算数量过小: {size_rounded}，无法交易")
    
    # 检查最终数量是否有效
    if size == 0:
        print(f"[{get_beijing_time()}] {account_prefix} [ERROR] 最终数量为0，放弃交易")
        
        # 发送失败通知
        notification_service.send_bark_notification(
            f"{account_prefix} 交易失败",
            f"计算数量为0，放弃交易\n"
            f"入场价格: {entry_price:.4f}\n"
            f"保证金: {MARGIN} USDT\n"
            f"杠杆: {LEVERAGE}倍",
            group="OKX自动交易通知"
        )
        return
    
    print(f"[{get_beijing_time()}] {account_prefix} [SIZE_CALC] 计算详情:")
    print(f"  原始数量: {raw_size:.4f}")
    print(f"  四舍五入后: {size_rounded}")
    print(f"  调整后数量: {size} (10的倍数)")

    # 根据信号方向计算止盈止损价格
    if signal == "LONG":
        take_profit_price = round(entry_price * (1 + TAKE_PROFIT_PERCENT), 5)
        stop_loss_price = round(entry_price * (1 - STOP_LOSS_PERCENT), 5)
    else:  # SHORT
        take_profit_price = round(entry_price * (1 - TAKE_PROFIT_PERCENT), 5)
        stop_loss_price = round(entry_price * (1 + STOP_LOSS_PERCENT), 5)

    # 生成符合要求的clOrdId
    cl_ord_id = generate_clord_id(account_prefix)

    # 构建止盈止损对象列表
    attach_algo_ord = {
        "attachAlgoClOrdId": generate_clord_id(account_prefix),
        "tpTriggerPx": str(take_profit_price),
        "tpOrdPx": "-1",  # 市价止盈
        "tpOrdKind": "condition",
        "slTriggerPx": str(stop_loss_price),
        "slOrdPx": "-1",  # 市价止损
        "tpTriggerPxType": "last",
        "slTriggerPxType": "last"
    }

    # 重构交易参数
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

    # 发送订单
    for attempt in range(MAX_RETRIES + 1):
        try:
            order_result = trade_api.place_order(**order_params)
            print(f"[{get_beijing_time()}] {account_prefix} [ORDER] 订单提交结果: {json.dumps(order_result)}")
            
            # 检查是否成功下单
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
    
    # 发送交易通知
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

    # 日志输出
    print(f"[{get_beijing_time()}] {account_prefix} [SIGNAL] {signal}@{entry_price:.4f}")
    print(f"[{get_beijing_time()}] {account_prefix} [ORDER] {json.dumps(order_params)}")
    print(f"[{get_beijing_time()}] {account_prefix} [RESULT] {json.dumps(order_result)}")


def get_kline_data():
    """获取并分析K线数据"""
    # 使用第一个账户的环境变量初始化市场API
    suffix = ACCOUNT_SUFFIXES[0] if ACCOUNT_SUFFIXES else ""
    api_key = get_env_var("OKX_API_KEY", suffix)
    secret_key = get_env_var("OKX_SECRET_KEY", suffix)
    passphrase = get_env_var("OKX_PASSPHRASE", suffix)
    flag = get_env_var("OKX_FLAG", suffix, "0")  # 默认实盘
    
    if not all([api_key, secret_key, passphrase]):
        print(f"[{get_beijing_time()}] [ERROR] 账户信息不完整，无法获取K线数据")
        return None, None, None
    
    # 初始化市场API
    try:
        market_api = MarketData.MarketAPI(api_key, secret_key, passphrase, False, flag)
        market_api.OK_ACCESS_TIMESTAMP = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        print(f"[{get_beijing_time()}] [MARKET] K线API初始化成功")
    except Exception as e:
        print(f"[{get_beijing_time()}] [ERROR] K线API初始化失败: {str(e)}")
        return None, None, None
    
    # 获取最近K线数据
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

    # 提取倒数第二根K线(前一根K线)
    prev_kline = result['data'][1]
    print(f"[{get_beijing_time()}] [DEBUG] 正在分析前一根K线: {prev_kline}")

    # 分析K线
    signal, entry_price, amp_info = analyze_kline(prev_kline)

    # 输出K线分析详情
    print(f"[{get_beijing_time()}] [KLINE] 分析结果:")
    print(f"  标的: {INST_ID} | K线规格: {BAR}")
    print(f"  开盘价: {amp_info['open']:.4f}")
    print(f"  最高价: {amp_info['high']:.4f}")
    print(f"  最低价: {amp_info['low']:.4f}")
    print(f"  收盘价: {amp_info['close']:.4f}")
    print(f"  K线实体变动: {amp_info['body_change']:.4f} ({amp_info['body_change_perc']:.2f}%)")
    print(f"  总振幅: {amp_info['total_range']:.4f} ({amp_info['total_range_perc']:.2f}%)")
    print(f"  振幅范围1({RANGE1_MIN}%-{RANGE1_MAX}%): {'满足' if amp_info['in_range1'] else '不满足'}")
    print(f"  振幅范围2(实体振幅> {RANGE2_THRESHOLD}%): {'满足' if amp_info['in_range2'] else '不满足'}")
    print(f"  是否为阳线: {amp_info['is_green']}")
    print(f"  是否为阴线: {amp_info['is_red']}")
    print(f"  信号: {signal if signal else '无信号'}")
    print(f"  入场价: {entry_price if entry_price else 'N/A'}")
    print(f"  条件: {amp_info['condition'] if amp_info['condition'] else '无交易条件'}")

    # 满足振幅条件时发送通知
    if amp_info['in_range1'] or amp_info['in_range2']:
        notification_service.send_amplitude_alert(
            symbol=INST_ID,
            amplitude=amp_info['body_change_perc'],
            threshold=RANGE2_THRESHOLD,
            open_price=amp_info['open'],
            latest_price=amp_info['close']
        )
        print(f"[{get_beijing_time()}] [AMPLITUDE] 发送振幅预警通知")
    
    return signal, entry_price, amp_info


if __name__ == "__main__":
    print(f"[{get_beijing_time()}] [INFO] 开始VINE自动交易策略")
    
    # 1. 获取K线数据并分析信号
    signal, entry_price, amp_info = get_kline_data()
    
    # 如果没有信号，退出程序
    if not signal:
        print(f"[{get_beijing_time()}] [INFO] 未检测到交易信号")
        if amp_info:
            print(f"[{get_beijing_time()}] [AMP_DETAIL] "
                  f"振幅范围1: {amp_info['in_range1']} "
                  f"振幅范围2: {amp_info['in_range2']} "
                  f"实体变动: {amp_info['body_change_perc']:.2f}% "
                  f"总振幅: {amp_info['total_range_perc']:.2f}%")
        else:
            print(f"[{get_beijing_time()}] [ERROR] 无K线数据")
        exit(0)
    
    # 2. 遍历所有账户执行交易
    print(f"[{get_beijing_time()}] [INFO] 开始处理所有账户交易")
    for suffix in ACCOUNT_SUFFIXES:
        process_account_trading(suffix, signal, entry_price, amp_info)
    
    print(f"[{get_beijing_time()}] [INFO] 所有账户交易处理完成")
