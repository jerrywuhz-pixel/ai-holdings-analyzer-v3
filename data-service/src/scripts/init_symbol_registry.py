"""
symbol_registry 初始化脚本

通过外部 API（Tushare / Yahoo Finance）拉取 A 股、美股、港股基础信息，
并批量 upsert 到 Supabase `symbol_registry` 表。

运行方式:
    cd data-service/src
    python -m scripts.init_symbol_registry

环境变量依赖:
    SUPABASE_URL               Supabase 项目 URL
    SUPABASE_SERVICE_ROLE_KEY  Supabase Service Role Key（需写权限）
    TUSHARE_TOKEN              Tushare Pro API Token
"""

from __future__ import annotations

import os
import sys
import time
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# 可选依赖：优雅降级
# ---------------------------------------------------------------------------
try:
    import tushare as ts

    TUSHARE_AVAILABLE = True
except ImportError:
    TUSHARE_AVAILABLE = False

try:
    import httpx

    HTTPX_AVAILABLE = True
except ImportError:
    HTTPX_AVAILABLE = False

try:
    from supabase import create_client

    SUPABASE_AVAILABLE = True
except ImportError:
    SUPABASE_AVAILABLE = False

# ---------------------------------------------------------------------------
# 预定义 Top 股票列表（美股 + 港股）
# 注：生产环境可改为从外部 CSV / API 加载
# ---------------------------------------------------------------------------

# 美股 Top 100（按市值与流动性精选，覆盖 S&P 500 / NASDAQ 核心标的）
US_TOP_STOCKS: List[str] = [
    # 科技巨头
    "AAPL",
    "MSFT",
    "GOOGL",
    "GOOG",
    "AMZN",
    "NVDA",
    "TSLA",
    "META",
    "AVGO",
    "ORCL",
    "ADBE",
    "CRM",
    "AMD",
    "INTC",
    "CSCO",
    "QCOM",
    "TXN",
    "IBM",
    "NOW",
    "PANW",
    "SNOW",
    "UBER",
    "ABNB",
    "PYPL",
    "SQ",
    "SHOP",
    "NET",
    "DDOG",
    "CRWD",
    "ZS",
    "FTNT",
    "PLTR",
    "COIN",
    "RBLX",
    "U",
    "ROKU",
    "ZM",
    "DOCU",
    "TWLO",
    "OKTA",
    "FSLY",
    # 金融
    "BRK-B",
    "JPM",
    "BAC",
    "WFC",
    "GS",
    "MS",
    "C",
    "BLK",
    "AXP",
    "SCHW",
    "PNC",
    "USB",
    "TFC",
    "COF",
    "SPGI",
    "ICE",
    "CME",
    "MCO",
    "BK",
    "STT",
    # 医疗健康
    "JNJ",
    "UNH",
    "LLY",
    "PFE",
    "ABBV",
    "TMO",
    "MRK",
    "ABT",
    "DHR",
    "BMY",
    "AMGN",
    "GILD",
    "VRTX",
    "REGN",
    "BIIB",
    "ZTS",
    "ISRG",
    "SYK",
    "MDT",
    "EW",
    "HUM",
    "CI",
    "ELV",
    "CVS",
    # 消费
    "WMT",
    "COST",
    "HD",
    "MCD",
    "NKE",
    "SBUX",
    "LOW",
    "TGT",
    "TJX",
    "PG",
    "KO",
    "PEP",
    "MDLZ",
    "GIS",
    "KMB",
    "CL",
    "MO",
    "PM",
    "STZ",
    "MNST",
    # 工业 / 能源 / 原材料
    "XOM",
    "CVX",
    "COP",
    "EOG",
    "OXY",
    "MPC",
    "VLO",
    "PSX",
    "SLB",
    "HAL",
    "GE",
    "HON",
    "BA",
    "CAT",
    "DE",
    "UPS",
    "FDX",
    "LMT",
    "NOC",
    "RTX",
    "GD",
    "TDG",
    "ITW",
    "ETN",
    "EMR",
    "MMM",
    # 电信 / 公用事业
    "VZ",
    "T",
    "TMUS",
    "CMCSA",
    "CHTR",
    "NEE",
    "DUK",
    "SO",
    "D",
    "AEP",
    "SRE",
    "EXC",
    "PEG",
    "ED",
    "XEL",
    "WEC",
    # 房地产 / REITs
    "PLD",
    "AMT",
    "CCI",
    "EQIX",
    "PSA",
    "O",
    "DLR",
    "WELL",
    "SBAC",
    "AVB",
    # 传媒 / 娱乐
    "DIS",
    "NFLX",
    "WBD",
    "FOX",
    "NWS",
    "LYV",
    "SPOT",
    "TTWO",
    "EA",
    "ATVI",
    # 汽车 / 交通
    "F",
    "GM",
    "RIVN",
    "LCID",
    "NIO",
    "XPEV",
    "LI",
    "TM",
    "HMC",
    # 其他大型蓝筹
    "V",
    "MA",
    "AXP",
    "LIN",
    "APD",
    "ECL",
    "NEM",
    "FCX",
    "DOW",
    "LYB",
    "PPG",
    "IFF",
    "ALB",
    "CF",
    "MOS",
]

# 港股 Top 50（恒生指数成分股及高流动性标的）
# 值为 HKEX 五位数字代码（可带前导零）
HK_TOP_STOCKS: List[str] = [
    "00001",
    "00002",
    "00003",
    "00005",
    "00006",
    "00011",
    "00012",
    "00016",
    "00017",
    "00019",
    "00027",
    "00066",
    "00083",
    "00101",
    "00144",
    "00151",
    "00175",
    "00207",
    "00231",
    "00238",
    "00267",
    "00288",
    "00293",
    "00322",
    "00386",
    "00388",
    "00669",
    "00688",
    "00700",
    "00762",
    "00823",
    "00836",
    "00857",
    "00883",
    "00939",
    "00941",
    "00992",
    "01038",
    "01044",
    "01088",
    "01093",
    "01109",
    "01113",
    "01177",
    "01211",
    "01299",
    "01398",
    "01810",
    "01928",
    "02018",
    "02313",
    "02318",
    "02319",
    "02382",
    "02388",
    "02628",
    "02688",
    "03690",
    "03988",
    "06060",
    "06690",
    "09618",
    "09626",
    "09988",
    "09999",
]

YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"


def _fetch_yahoo_metadata(yahoo_symbol: str) -> Optional[Dict[str, Any]]:
    """通过 Yahoo Finance Chart API 获取单只股票元信息（同步）。"""
    if not HTTPX_AVAILABLE:
        return None

    url = YAHOO_CHART_URL.format(symbol=yahoo_symbol)
    try:
        with httpx.Client(timeout=15.0) as client:
            resp = client.get(url, headers={"Accept": "application/json"})
            resp.raise_for_status()
            data = resp.json()
    except Exception:
        return None

    chart = data.get("chart", {})
    if chart.get("error"):
        return None

    results = chart.get("result")
    if not results:
        return None

    return results[0].get("meta", {})


def _build_cn_records() -> List[Dict[str, Any]]:
    """通过 Tushare 获取 A 股列表并转换为 symbol_registry 记录。"""
    records: List[Dict[str, Any]] = []
    if not TUSHARE_AVAILABLE:
        print("[WARN] tushare not installed, skipping A-share data.")
        return records

    token = os.getenv("TUSHARE_TOKEN")
    if not token:
        print("[WARN] TUSHARE_TOKEN not set, skipping A-share data.")
        return records

    try:
        pro = ts.pro_api(token)
        df = pro.stock_basic(exchange="", list_status="L")
    except Exception as exc:
        print(f"[WARN] Failed to fetch A-share list from Tushare: {exc}")
        return records

    for _, row in df.iterrows():
        ts_code = str(row.get("ts_code", "")).strip()
        name = str(row.get("name", "")).strip()
        if not ts_code or len(ts_code) < 3:
            continue

        suffix = ts_code[-3:].upper()
        code = ts_code[:-3]

        if suffix == ".SH":
            symbol = f"SH{code}"
            exchange = "SH"
            exchange_name = "上海证券交易所"
            yahoo_suffix = ".SS"
        elif suffix == ".SZ":
            symbol = f"SZ{code}"
            exchange = "SZ"
            exchange_name = "深圳证券交易所"
            yahoo_suffix = ".SZ"
        else:
            # 跳过北交所等其他市场，后续可扩展
            continue

        provider_symbols = {
            "tushare": ts_code,
            "yahoo": f"{code}{yahoo_suffix}",
            "akshare": code,
        }

        aliases = [name]
        # 可在此处扩展常见缩写 / 拼音缩写
        records.append(
            {
                "symbol": symbol,
                "provider_symbols": provider_symbols,
                "market": "CN",
                "exchange": exchange,
                "exchange_name": exchange_name,
                "name_zh": name,
                "name_en": None,
                "aliases": aliases,
                "is_active": True,
            }
        )

    return records


def _build_us_records() -> List[Dict[str, Any]]:
    """基于预定义列表，通过 Yahoo Finance 获取美股元信息。"""
    records: List[Dict[str, Any]] = []
    if not HTTPX_AVAILABLE:
        print("[WARN] httpx not installed, skipping US stock metadata fetch.")
        # 仍写入基础占位记录
        for ticker in US_TOP_STOCKS:
            records.append(
                {
                    "symbol": ticker.upper(),
                    "provider_symbols": {"yahoo": ticker.upper()},
                    "market": "US",
                    "exchange": "NASDAQ",
                    "exchange_name": "NASDAQ",
                    "name_zh": None,
                    "name_en": ticker.upper(),
                    "aliases": [ticker.upper()],
                    "is_active": True,
                }
            )
        return records

    for idx, ticker in enumerate(US_TOP_STOCKS, 1):
        ticker = ticker.strip().upper()
        meta = _fetch_yahoo_metadata(ticker)

        if meta is None:
            print(f"  [{idx}/{len(US_TOP_STOCKS)}] {ticker}: metadata not found, using fallback.")
            records.append(
                {
                    "symbol": ticker,
                    "provider_symbols": {"yahoo": ticker},
                    "market": "US",
                    "exchange": "NASDAQ",
                    "exchange_name": "NASDAQ",
                    "name_zh": None,
                    "name_en": ticker,
                    "aliases": [ticker],
                    "is_active": True,
                }
            )
            continue

        exchange = meta.get("exchangeName", "NASDAQ")
        exchange_name = meta.get("fullExchangeName") or exchange
        name_en = meta.get("shortName") or meta.get("longName") or ticker

        print(f"  [{idx}/{len(US_TOP_STOCKS)}] {ticker}: {name_en} @ {exchange_name}")
        records.append(
            {
                "symbol": ticker,
                "provider_symbols": {"yahoo": ticker},
                "market": "US",
                "exchange": exchange,
                "exchange_name": exchange_name,
                "name_zh": None,
                "name_en": name_en,
                "aliases": list({ticker, name_en}),
                "is_active": True,
            }
        )

        # 简单限速：避免过快请求 Yahoo
        time.sleep(0.15)

    return records


def _build_hk_records() -> List[Dict[str, Any]]:
    """基于预定义列表，通过 Yahoo Finance 获取港股元信息。"""
    records: List[Dict[str, Any]] = []
    if not HTTPX_AVAILABLE:
        print("[WARN] httpx not installed, skipping HK stock metadata fetch.")
        for code in HK_TOP_STOCKS:
            symbol = f"HK{code.zfill(5)}"
            records.append(
                {
                    "symbol": symbol,
                    "provider_symbols": {
                        "yahoo": f"{str(int(code)).zfill(4)}.HK",
                        "longbridge": f"{int(code)}.HK",
                    },
                    "market": "HK",
                    "exchange": "HKEX",
                    "exchange_name": "香港交易所",
                    "name_zh": None,
                    "name_en": None,
                    "aliases": [symbol],
                    "is_active": True,
                }
            )
        return records

    for idx, code in enumerate(HK_TOP_STOCKS, 1):
        code = code.strip()
        symbol = f"HK{code.zfill(5)}"
        # Yahoo 港股格式：去除前导零后补足 4 位（如 00700 -> 0700.HK）
        yahoo_code = str(int(code)).zfill(4)
        yahoo_sym = f"{yahoo_code}.HK"
        longbridge_sym = f"{int(code)}.HK"

        meta = _fetch_yahoo_metadata(yahoo_sym)

        if meta is None:
            print(f"  [{idx}/{len(HK_TOP_STOCKS)}] {symbol}: metadata not found, using fallback.")
            records.append(
                {
                    "symbol": symbol,
                    "provider_symbols": {
                        "yahoo": yahoo_sym,
                        "longbridge": longbridge_sym,
                    },
                    "market": "HK",
                    "exchange": "HKEX",
                    "exchange_name": "香港交易所",
                    "name_zh": None,
                    "name_en": None,
                    "aliases": [symbol],
                    "is_active": True,
                }
            )
            continue

        name = meta.get("shortName") or meta.get("longName") or ""
        print(f"  [{idx}/{len(HK_TOP_STOCKS)}] {symbol}: {name}")
        records.append(
            {
                "symbol": symbol,
                "provider_symbols": {
                    "yahoo": yahoo_sym,
                    "longbridge": longbridge_sym,
                },
                "market": "HK",
                "exchange": "HKEX",
                "exchange_name": "香港交易所",
                "name_zh": name,
                "name_en": name,
                "aliases": list({symbol, name}),
                "is_active": True,
            }
        )

        time.sleep(0.15)

    return records


def _upsert_records(
    supabase_client, records: List[Dict[str, Any]], batch_size: int = 500
) -> Dict[str, int]:
    """分批 upsert 记录到 symbol_registry，返回成功/失败计数。"""
    stats = {"success": 0, "failed": 0}
    total = len(records)

    for i in range(0, total, batch_size):
        batch = records[i : i + batch_size]
        try:
            # supabase-py v2 upsert 会自动处理冲突列（基于表的唯一约束）
            supabase_client.table("symbol_registry").upsert(batch).execute()
            stats["success"] += len(batch)
            print(f"  Upserted batch {i + 1}-{min(i + batch_size, total)} / {total}")
        except Exception as exc:
            stats["failed"] += len(batch)
            print(f"  [ERROR] Failed to upsert batch {i + 1}-{min(i + batch_size, total)}: {exc}")

    return stats


def main() -> int:
    print("=" * 60)
    print("symbol_registry initialization script")
    print("=" * 60)

    # ------------------------------------------------------------------
    # 环境检查
    # ------------------------------------------------------------------
    if not SUPABASE_AVAILABLE:
        print("[FATAL] supabase-py not installed. Please install: pip install supabase")
        return 1

    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

    if not supabase_url or not supabase_key:
        print("[FATAL] SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set.")
        return 1

    try:
        supabase = create_client(supabase_url, supabase_key)
    except Exception as exc:
        print(f"[FATAL] Failed to create Supabase client: {exc}")
        return 1

    # ------------------------------------------------------------------
    # 1. A 股（Tushare）
    # ------------------------------------------------------------------
    print("\n[1/3] Fetching CN A-share list from Tushare ...")
    cn_records = _build_cn_records()
    print(f"      -> {len(cn_records)} records prepared.")

    # ------------------------------------------------------------------
    # 2. 美股（Yahoo Finance）
    # ------------------------------------------------------------------
    print("\n[2/3] Fetching US stock metadata from Yahoo Finance ...")
    us_records = _build_us_records()
    print(f"      -> {len(us_records)} records prepared.")

    # ------------------------------------------------------------------
    # 3. 港股（Yahoo Finance）
    # ------------------------------------------------------------------
    print("\n[3/3] Fetching HK stock metadata from Yahoo Finance ...")
    hk_records = _build_hk_records()
    print(f"      -> {len(hk_records)} records prepared.")

    # ------------------------------------------------------------------
    # 合并并写入数据库
    # ------------------------------------------------------------------
    all_records = cn_records + us_records + hk_records
    print(f"\n[UPSERT] Total records to upsert: {len(all_records)}")

    if not all_records:
        print("[WARN] No records to upsert. Exiting.")
        return 0

    stats = _upsert_records(supabase, all_records)
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"  CN records : {len(cn_records)}")
    print(f"  US records : {len(us_records)}")
    print(f"  HK records : {len(hk_records)}")
    print(f"  Total      : {len(all_records)}")
    print(f"  Upserted   : {stats['success']}")
    print(f"  Failed     : {stats['failed']}")
    print("=" * 60)

    return 0 if stats["failed"] == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
