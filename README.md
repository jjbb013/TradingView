# OKX TRUMP 自动交易脚本

## 脚本简介
`okx_trump_trading_strategy.py` 是基于青龙面板的 OKX 永续合约自动交易脚本，支持自动下单、止盈止损、委托监控与自动撤单。

## 主要功能
- 支持 TRUMP-USDT-SWAP 合约自动交易
- 策略参数：杠杆10倍，止盈2%，止损3%，振幅5%
- 下单前自动检查当前账户下该标的未成交委托单
- 若当前价格已超过止盈价且未成交，则自动撤销该委托单
- 下单数量为保证金10USDT，10倍杠杆，向上取整为10的倍数
- 支持多账号环境变量配置
- 详细日志与通知推送

## 参数说明
- `INST_ID`：交易标的（TRUMP-USDT-SWAP）
- `LEVERAGE`：杠杆倍数（10）
- `MARGIN`：每次下单保证金（10 USDT）
- `TAKE_PROFIT_PERCENT`：止盈百分比（0.02）
- `STOP_LOSS_PERCENT`：止损百分比（0.03）
- `AMPLITUDE_PERCENT`：触发策略的K线振幅（0.05）
- `PRICE_TOLERANCE`：止盈价比较容差（0.0001）

## 使用方法
1. 配置 OKX API 环境变量（支持多账号）
2. 将脚本添加到青龙面板，设置定时任务
3. 查看日志和通知，监控自动交易执行情况

## 注意事项
- 需提前在 OKX 设置好API权限
- 需安装 okx-python-sdk、notification_service 等依赖
- 脚本仅供学习和研究，实盘风险自负
- 委托撤单逻辑依赖于 attachAlgoOrds 或 linkedAlgoOrd 的止盈价信息

---
如需自定义策略或有其他需求，欢迎随时联系开发者。