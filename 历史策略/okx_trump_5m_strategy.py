"""
TRUMP-USDT-SWAP 5m自动交易策略
参数：止盈=0.042，止损=0.044，振幅=0.012
"""
from notification_service import notification_service
import okx.MarketData as MarketData
import okx.Trade as Trade
import time
from datetime import datetime, timezone, timedelta

# 策略参数
INST_ID = "TRUMP-USDT-SWAP"
BAR = "5m"
LEVERAGE = 10
MARGIN = 10
TAKE_PROFIT_PERCENT = 0.042
STOP_LOSS_PERCENT = 0.044
AMPLITUDE_PERCENT = 0.012

ACCOUNT_SUFFIXES = ["", "1", "2", "3"]
MAX_RETRIES = 3
RETRY_DELAY = 2

# 省略API密钥获取、撤单、下单等通用函数，直接复用你主策略脚本的相关实现
# 只需替换参数即可
# ...
# 你可以直接复制okx_trump_trading_strategy.py的主流程和函数，只需替换上面参数 