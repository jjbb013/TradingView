import os
import csv
import time
import requests
import logging
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry

# 配置参数
API_URL = "https://www.okx.com/api/v5/market/history-candles"
API_KEY = os.getenv("OKX_API_KEY")  # 可选，但使用API KEY可以提高请求优先级
INSTRUMENTS = [
    #"VINE-USDT-SWAP",
    "BTC-USDT-SWAP",
    "ETH-USDT-SWAP",
    #"TRUMP-USDT-SWAP",
    #"DOGE-USDT-SWAP",
    #"ADA-USDT-SWAP"
]
TIMEFRAMES = [#"1m",
              #"3m",
              "5m",
              "15m",
              #"30m",
              #"1H",
              #"2H",
              #"4H"
    ]
DATA_DIR = "swap_kline_data"
DAYS_TO_FETCH = 30  # 获取过去多少天的数据
MAX_WORKERS = 3  # 并发线程数
RETRY_LIMIT = 5  # 重试次数
REQUEST_DELAY = 0.6  # 基本请求延迟（秒）
API_WAIT_CODES = ["50008", "50111", "50112"]  # OKX限速错误码
INST_TYPE = "SWAP"  # 永续合约类型

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[
        logging.FileHandler("swap_data_collector.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger()


class RateLimitExceeded(Exception):
    """自定义的限速异常"""
    pass


def create_retry_session():
    """创建带有重试机制的请求会话"""
    retry_strategy = Retry(
        total=RETRY_LIMIT,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
        backoff_factor=1.5,  # 增加回退因子
        respect_retry_after_header=True,
        raise_on_status=False
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session = requests.Session()
    session.mount("https://", adapter)
    return session


def get_beijing_time():
    """获取北京时间"""
    return datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")


def create_data_directory():
    """创建数据存储目录"""
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR)
        logger.info(f"创建数据目录: {DATA_DIR}")

    # 为每个标的创建子目录
    for inst in INSTRUMENTS:
        inst_dir = os.path.join(DATA_DIR, inst)
        if not os.path.exists(inst_dir):
            os.makedirs(inst_dir)


def calculate_time_boundaries():
    """计算数据获取的时间范围"""
    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(days=DAYS_TO_FETCH)
    return int(start_time.timestamp() * 1000), int(end_time.timestamp() * 1000)


def save_candles_to_csv(candles, instId, bar, start_ts, end_ts):
    """保存K线数据到CSV文件"""
    if not candles:
        return False

    # 生成文件名
    symbol = instId.split("-")[0]
    file_name = f"{symbol}_{bar}_{start_ts}_{end_ts}.csv"
    file_path = os.path.join(DATA_DIR, instId, file_name)

    # 写入CSV文件
    try:
        with open(file_path, "w", newline="", encoding='utf-8') as f:
            writer = csv.writer(f)
            # Swap合约K线字段: 时间戳, 开盘价, 最高价, 最低价, 收盘价, 成交量(张数), 成交量(币), 成交额, 状态
            writer.writerow(["timestamp", "open", "high", "low", "close", "volume", "volCcy", "volCcyQuote", "confirm"])
            for candle in candles:
                writer.writerow(candle)

        logger.info(f"保存 {len(candles)} 条 {instId}-{bar} 数据到 {file_path}")
        return True
    except Exception as e:
        logger.error(f"保存文件 {file_path} 失败: {str(e)}")
        return False


def fetch_swap_candles(session, instId, bar, before=None, after=None):
    """获取永续合约的历史K线数据"""
    params = {
        "instId": instId,
        "bar": bar,
        "limit": "100"  # 每次最多100条
    }

    # 添加分页参数
    if before:
        params["before"] = str(before)
    if after:
        params["after"] = str(after)

    headers = {"Content-Type": "application/json"}
    if API_KEY:
        headers["OK-ACCESS-KEY"] = API_KEY

    try:
        # 添加延迟避免触发限速
        time.sleep(REQUEST_DELAY)

        response = session.get(API_URL, params=params, headers=headers, timeout=30)

        # 检查响应状态
        if response.status_code != 200:
            logger.warning(f"HTTP {response.status_code} 错误: {response.text[:100]}")
            return []

        data = response.json()

        # 处理API错误
        if "code" in data and data["code"] != "0":
            error_msg = f"API错误 [{instId}-{bar}]: {data.get('code')} - {data.get('msg')}"

            # 特殊处理限速错误
            if data["code"] in API_WAIT_CODES:
                logger.warning(f"触发API限速: {data['msg']}")
                raise RateLimitExceeded(data["msg"])
            # 处理标的不存在的情况
            elif data["code"] in ["51001", "51005"]:
                logger.warning(f"标的不存在或不可用: {instId}")
                return "instrument_not_found"
            else:
                logger.error(error_msg)
                return []

        # 解析K线数据
        if not data.get("data"):
            logger.info(f"未获取到数据: {instId}-{bar}")
            return []

        return data["data"]

    except RateLimitExceeded as e:
        # 限速异常需要特殊处理
        wait_time = 10  # 等待10秒
        logger.info(f"因限速等待 {wait_time}秒...")
        time.sleep(wait_time)
        return fetch_swap_candles(session, instId, bar, before, after)  # 递归重试

    except requests.exceptions.RequestException as e:
        logger.error(f"请求异常 [{instId}-{bar}]: {str(e)}")
        return []

    except Exception as e:
        logger.error(f"处理 {instId}-{bar} 数据异常: {str(e)}")
        return []


def fetch_data_for_swap(session, instId, bar):
    """为单个永续合约标的和时间粒度获取数据"""
    logger.info(f"开始获取永续合约 {instId}-{bar} 历史K线数据...")

    # 计算时间范围 (获取过去7天的数据)
    start_time_ms, end_time_ms = calculate_time_boundaries()

    # 获取数据的起点（从最新时间开始往回获取）
    all_candles = []
    after = None
    before = None
    has_more = True
    request_count = 0
    total_candles = 0

    # 时间区间控制（防止无限循环）
    last_timestamp = end_time_ms

    while has_more:
        request_count += 1
        try:
            candles = fetch_swap_candles(session, instId, bar, before=before, after=after)

            # 检查特殊返回码
            if candles == "instrument_not_found":
                logger.warning(f"标的不存在: {instId}, 跳过")
                return instId, bar, 0

            if not candles:
                logger.info(f"没有更多数据: {instId}-{bar}")
                break

            # 记录第一条和最后一条的时间戳
            first_ts = int(candles[0][0])
            last_ts = int(candles[-1][0])

            # 添加到总数据
            all_candles.extend(candles)
            total_candles += len(candles)

            # 检查是否到达所需时间范围
            if last_ts <= start_time_ms:
                logger.info(f"达到时间范围下限: {instId}-{bar}")
                has_more = False

                # 过滤掉时间范围之外的数据
                all_candles = [c for c in all_candles if int(c[0]) >= start_time_ms]
                break

            # 设置下一批请求的参数（获取更早的数据）
            after = last_ts  # 使用最后一条的时间戳作为下次请求的起点

            # 每10次请求保存一次数据（防止内存过大）
            if request_count % 10 == 0 and all_candles:
                save_start = int(all_candles[0][0])
                save_end = int(all_candles[-1][0])
                if save_candles_to_csv(all_candles, instId, bar, save_start, save_end):
                    all_candles = []  # 清空已保存的数据

            # 记录最后一条数据的时间戳
            last_timestamp = last_ts

        except Exception as e:
            logger.error(f"获取数据时发生异常: {str(e)}")
            time.sleep(5)  # 异常后等待5秒

    # 保存剩余数据
    if all_candles:
        save_start = int(all_candles[0][0])
        save_end = int(all_candles[-1][0])
        save_candles_to_csv(all_candles, instId, bar, save_start, save_end)

    logger.info(f"完成永续合约 {instId}-{bar} 数据获取: 共 {total_candles} 条K线数据")
    return instId, bar, total_candles


def main():
    """主函数：并发获取所有永续合约数据"""
    logger.info("=" * 80)
    logger.info("开始获取永续合约历史K线数据")
    logger.info(f"标的: {', '.join(INSTRUMENTS)}")
    logger.info(f"时间粒度: {', '.join(TIMEFRAMES)}")
    logger.info(f"时间范围: 过去 {DAYS_TO_FETCH} 天")
    logger.info(f"并发数: {MAX_WORKERS}")
    logger.info("=" * 80)

    # 创建数据目录
    create_data_directory()

    # 准备所有任务
    tasks = []
    for instId in INSTRUMENTS:
        for bar in TIMEFRAMES:
            tasks.append((instId, bar))

    # 创建会话池
    sessions = [create_retry_session() for _ in range(MAX_WORKERS)]

    # 使用线程池处理任务
    completed_tasks = 0
    total_tasks = len(tasks)
    results = []

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        # 提交所有任务
        future_to_task = {}
        for i, (instId, bar) in enumerate(tasks):
            session = sessions[i % MAX_WORKERS]
            future = executor.submit(fetch_data_for_swap, session, instId, bar)
            future_to_task[future] = (instId, bar)

        # 处理完成的任务
        for future in as_completed(future_to_task):
            task = future_to_task[future]
            try:
                instId, bar, count = future.result()
                logger.info(f"任务完成: {instId}-{bar} => {count}条数据")
                results.append((instId, bar, count))
                completed_tasks += 1
            except Exception as e:
                logger.error(f"任务失败 {task[0]}-{task[1]}: {str(e)}")

    # 结果汇总
    total_candles = sum(count for _, _, count in results)

    logger.info("\n" + "=" * 60)
    logger.info("永续合约数据获取完成")
    logger.info(f"成功获取: {completed_tasks}/{total_tasks} 个组合的数据")
    logger.info(f"总获取条数: {total_candles} 条K线数据")
    logger.info(f"数据存储位置: {os.path.abspath(DATA_DIR)}")

    # 打印每个标的的统计信息
    logger.info("\n各标的数据统计:")
    for instId in INSTRUMENTS:
        inst_results = [r for r in results if r[0] == instId]
        inst_candles = sum(r[2] for r in inst_results)
        logger.info(f"{instId}: {len(inst_results)}个时间粒度, {inst_candles}条数据")

    logger.info("=" * 60)

    # 关闭所有会话
    for session in sessions:
        session.close()


if __name__ == "__main__":
    main()