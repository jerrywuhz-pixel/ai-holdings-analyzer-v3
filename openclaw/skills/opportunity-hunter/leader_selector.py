"""
Leader Selector — 龙头识别模块

识别热门板块中的龙头股，按涨幅+成交量综合排名，输出各板块 Top 3 龙头。
通过 data-service 批量获取个股行情。
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# ---------- 板块成分股映射 ----------

SECTOR_CONSTITUENTS: dict[str, dict[str, list[dict[str, str]]]] = {
    "CN": {
        "SH512660": [  # 军工
            {"symbol": "SH600893", "name": "航发动力"},
            {"symbol": "SH600760", "name": "中航沈飞"},
            {"symbol": "SH600862", "name": "中航高科"},
            {"symbol": "SZ002179", "name": "中航光电"},
            {"symbol": "SH600990", "name": "四创电子"},
            {"symbol": "SZ300034", "name": "钢研高纳"},
            {"symbol": "SH600038", "name": "中直股份"},
            {"symbol": "SZ300396", "name": "迪瑞机电"},
            {"symbol": "SH600184", "name": "光电股份"},
            {"symbol": "SZ002465", "name": "海格通信"},
        ],
        "SH512800": [  # 银行
            {"symbol": "SH601398", "name": "工商银行"},
            {"symbol": "SH601288", "name": "农业银行"},
            {"symbol": "SH600036", "name": "招商银行"},
            {"symbol": "SH601328", "name": "交通银行"},
            {"symbol": "SH601166", "name": "兴业银行"},
            {"symbol": "SH600016", "name": "民生银行"},
            {"symbol": "SH601818", "name": "光大银行"},
            {"symbol": "SH600000", "name": "浦发银行"},
            {"symbol": "SH601939", "name": "建设银行"},
            {"symbol": "SH601988", "name": "中国银行"},
        ],
        "SH512010": [  # 医药
            {"symbol": "SH600276", "name": "恒瑞医药"},
            {"symbol": "SZ000538", "name": "云南白药"},
            {"symbol": "SZ300015", "name": "爱尔眼科"},
            {"symbol": "SZ300760", "name": "迈瑞医疗"},
            {"symbol": "SH603259", "name": "药明康德"},
            {"symbol": "SZ002007", "name": "华兰生物"},
            {"symbol": "SH600196", "name": "复星医药"},
            {"symbol": "SZ000963", "name": "华东医药"},
            {"symbol": "SH601607", "name": "上海医药"},
            {"symbol": "SZ300122", "name": "智飞生物"},
        ],
        "SH512880": [  # 券商
            {"symbol": "SH601211", "name": "国泰君安"},
            {"symbol": "SH600030", "name": "中信证券"},
            {"symbol": "SH601688", "name": "华泰证券"},
            {"symbol": "SZ000776", "name": "广发证券"},
            {"symbol": "SH601788", "name": "光大证券"},
            {"symbol": "SH600837", "name": "海通证券"},
            {"symbol": "SZ000166", "name": "申万宏源"},
            {"symbol": "SH601555", "name": "东吴证券"},
            {"symbol": "SH600109", "name": "国金证券"},
            {"symbol": "SH601198", "name": "东兴证券"},
        ],
        "SH512690": [  # 白酒/消费
            {"symbol": "SH600519", "name": "贵州茅台"},
            {"symbol": "SZ000858", "name": "五粮液"},
            {"symbol": "SZ000568", "name": "泸州老窖"},
            {"symbol": "SH603589", "name": "口子窖"},
            {"symbol": "SZ002304", "name": "洋河股份"},
            {"symbol": "SH600809", "name": "山西汾酒"},
            {"symbol": "SZ000799", "name": "酒鬼酒"},
            {"symbol": "SH603369", "name": "今世缘"},
            {"symbol": "SZ000596", "name": "古井贡酒"},
            {"symbol": "SH600559", "name": "老白干酒"},
        ],
        "SH512480": [  # 半导体
            {"symbol": "SZ002371", "name": "北方华创"},
            {"symbol": "SH603986", "name": "兆易创新"},
            {"symbol": "SZ300661", "name": "圣邦股份"},
            {"symbol": "SH688981", "name": "中芯国际"},
            {"symbol": "SZ300782", "name": "卓胜微"},
            {"symbol": "SH603501", "name": "韦尔股份"},
            {"symbol": "SZ002049", "name": "紫光国微"},
            {"symbol": "SZ300014", "name": "亿纬锂能"},
            {"symbol": "SH688012", "name": "中微公司"},
            {"symbol": "SZ300223", "name": "北京君正"},
        ],
        "SH515790": [  # 光伏
            {"symbol": "SH601012", "name": "隆基绿能"},
            {"symbol": "SZ002459", "name": "晶澳科技"},
            {"symbol": "SH688599", "name": "天合光能"},
            {"symbol": "SZ300274", "name": "阳光电源"},
            {"symbol": "SZ002129", "name": "中环股份"},
            {"symbol": "SH600438", "name": "通威股份"},
            {"symbol": "SZ300750", "name": "宁德时代"},
            {"symbol": "SZ002709", "name": "天赐材料"},
            {"symbol": "SH688516", "name": "奥特维"},
            {"symbol": "SZ300861", "name": "美畅股份"},
        ],
        "SH516160": [  # 新能源车
            {"symbol": "SZ300750", "name": "宁德时代"},
            {"symbol": "SZ002594", "name": "比亚迪"},
            {"symbol": "SH600104", "name": "上汽集团"},
            {"symbol": "SZ002460", "name": "赣锋锂业"},
            {"symbol": "SH600699", "name": "均胜电子"},
            {"symbol": "SZ002466", "name": "天齐锂业"},
            {"symbol": "SZ002407", "name": "多氟多"},
            {"symbol": "SH600733", "name": "北汽蓝谷"},
            {"symbol": "SZ300014", "name": "亿纬锂能"},
            {"symbol": "SZ002812", "name": "恩捷股份"},
        ],
        "SH512400": [  # 有色金属
            {"symbol": "SH601899", "name": "紫金矿业"},
            {"symbol": "SH600362", "name": "江西铜业"},
            {"symbol": "SH601600", "name": "中国铝业"},
            {"symbol": "SZ000630", "name": "铜陵有色"},
            {"symbol": "SH600547", "name": "山东黄金"},
            {"symbol": "SZ002460", "name": "赣锋锂业"},
            {"symbol": "SH603993", "name": "洛阳钼业"},
            {"symbol": "SZ002466", "name": "天齐锂业"},
            {"symbol": "SH600489", "name": "中金黄金"},
            {"symbol": "SZ000831", "name": "中国稀土"},
        ],
        "SH512980": [  # 传媒
            {"symbol": "SZ300059", "name": "东方财富"},
            {"symbol": "SZ002230", "name": "科大讯飞"},
            {"symbol": "SZ300418", "name": "昆仑万维"},
            {"symbol": "SH603444", "name": "吉比特"},
            {"symbol": "SZ300454", "name": "深信服"},
            {"symbol": "SH600919", "name": "快乐购"},
            {"symbol": "SZ000917", "name": "电广传媒"},
            {"symbol": "SZ002602", "name": "世纪华通"},
            {"symbol": "SZ300570", "name": "太辰光"},
            {"symbol": "SH600633", "name": "浙数文化"},
        ],
    },
    "US": {
        "XLF": [  # 金融
            {"symbol": "BRK-B", "name": "Berkshire Hathaway"},
            {"symbol": "JPM", "name": "JPMorgan Chase"},
            {"symbol": "V", "name": "Visa"},
            {"symbol": "MA", "name": "Mastercard"},
            {"symbol": "BAC", "name": "Bank of America"},
            {"symbol": "WFC", "name": "Wells Fargo"},
            {"symbol": "GS", "name": "Goldman Sachs"},
            {"symbol": "MS", "name": "Morgan Stanley"},
            {"symbol": "BLK", "name": "BlackRock"},
            {"symbol": "SCHW", "name": "Charles Schwab"},
        ],
        "XLK": [  # 科技
            {"symbol": "AAPL", "name": "Apple"},
            {"symbol": "MSFT", "name": "Microsoft"},
            {"symbol": "NVDA", "name": "NVIDIA"},
            {"symbol": "AVGO", "name": "Broadcom"},
            {"symbol": "ADBE", "name": "Adobe"},
            {"symbol": "CRM", "name": "Salesforce"},
            {"symbol": "ORCL", "name": "Oracle"},
            {"symbol": "AMD", "name": "AMD"},
            {"symbol": "INTC", "name": "Intel"},
            {"symbol": "CSCO", "name": "Cisco"},
        ],
        "XLE": [  # 能源
            {"symbol": "XOM", "name": "ExxonMobil"},
            {"symbol": "CVX", "name": "Chevron"},
            {"symbol": "COP", "name": "ConocoPhillips"},
            {"symbol": "SLB", "name": "Schlumberger"},
            {"symbol": "EOG", "name": "EOG Resources"},
            {"symbol": "PXD", "name": "Pioneer Natural Resources"},
            {"symbol": "MPC", "name": "Marathon Petroleum"},
            {"symbol": "OXY", "name": "Occidental Petroleum"},
            {"symbol": "VLO", "name": "Valero Energy"},
            {"symbol": "WMB", "name": "Williams Companies"},
        ],
        "XLV": [  # 医疗
            {"symbol": "UNH", "name": "UnitedHealth"},
            {"symbol": "JNJ", "name": "Johnson & Johnson"},
            {"symbol": "LLY", "name": "Eli Lilly"},
            {"symbol": "PFE", "name": "Pfizer"},
            {"symbol": "ABBV", "name": "AbbVie"},
            {"symbol": "MRK", "name": "Merck"},
            {"symbol": "TMO", "name": "Thermo Fisher"},
            {"symbol": "ABT", "name": "Abbott Labs"},
            {"symbol": "MDT", "name": "Medtronic"},
            {"symbol": "DHR", "name": "Danaher"},
        ],
        "XLY": [  # 可选消费
            {"symbol": "AMZN", "name": "Amazon"},
            {"symbol": "TSLA", "name": "Tesla"},
            {"symbol": "HD", "name": "Home Depot"},
            {"symbol": "MCD", "name": "McDonald's"},
            {"symbol": "NKE", "name": "Nike"},
            {"symbol": "SBUX", "name": "Starbucks"},
            {"symbol": "LOW", "name": "Lowe's"},
            {"symbol": "TGT", "name": "Target"},
            {"symbol": "BKNG", "name": "Booking Holdings"},
            {"symbol": "TJX", "name": "TJX Companies"},
        ],
        "XLP": [  # 必选消费
            {"symbol": "PG", "name": "Procter & Gamble"},
            {"symbol": "KO", "name": "Coca-Cola"},
            {"symbol": "PEP", "name": "PepsiCo"},
            {"symbol": "COST", "name": "Costco"},
            {"symbol": "WMT", "name": "Walmart"},
            {"symbol": "PM", "name": "Philip Morris"},
            {"symbol": "MO", "name": "Altria"},
            {"symbol": "CL", "name": "Colgate-Palmolive"},
            {"symbol": "KMB", "name": "Kimberly-Clark"},
            {"symbol": "GIS", "name": "General Mills"},
        ],
        "XLI": [  # 工业
            {"symbol": "GE", "name": "General Electric"},
            {"symbol": "CAT", "name": "Caterpillar"},
            {"symbol": "HON", "name": "Honeywell"},
            {"symbol": "UNP", "name": "Union Pacific"},
            {"symbol": "BA", "name": "Boeing"},
            {"symbol": "MMM", "name": "3M"},
            {"symbol": "RTX", "name": "RTX Corporation"},
            {"symbol": "LMT", "name": "Lockheed Martin"},
            {"symbol": "DE", "name": "Deere"},
            {"symbol": "EMR", "name": "Emerson Electric"},
        ],
        "XLB": [  # 材料
            {"symbol": "LIN", "name": "Linde"},
            {"symbol": "APD", "name": "Air Products"},
            {"symbol": "SHW", "name": "Sherwin-Williams"},
            {"symbol": "FCX", "name": "Freeport-McMoRan"},
            {"symbol": "NEM", "name": "Newmont"},
            {"symbol": "DOW", "name": "Dow"},
            {"symbol": "DD", "name": "DuPont"},
            {"symbol": "ECL", "name": "Ecolab"},
            {"symbol": "NUE", "name": "Nucor"},
            {"symbol": "VMC", "name": "Vulcan Materials"},
        ],
        "XLRE": [  # 房地产
            {"symbol": "PLD", "name": "Prologis"},
            {"symbol": "AMT", "name": "American Tower"},
            {"symbol": "CCI", "name": "Crown Castle"},
            {"symbol": "EQIX", "name": "Equinix"},
            {"symbol": "PSA", "name": "Public Storage"},
            {"symbol": "O", "name": "Realty Income"},
            {"symbol": "SPG", "name": "Simon Property"},
            {"symbol": "DLR", "name": "Digital Realty"},
            {"symbol": "AVB", "name": "AvalonBay"},
            {"symbol": "EQR", "name": "Equity Residential"},
        ],
        "XLU": [  # 公用事业
            {"symbol": "NEE", "name": "NextEra Energy"},
            {"symbol": "DUK", "name": "Duke Energy"},
            {"symbol": "SO", "name": "Southern Company"},
            {"symbol": "D", "name": "Dominion Energy"},
            {"symbol": "AEP", "name": "American Electric Power"},
            {"symbol": "EXC", "name": "Exelon"},
            {"symbol": "SRE", "name": "Sempra"},
            {"symbol": "XEL", "name": "Xcel Energy"},
            {"symbol": "PEG", "name": "PSEG"},
            {"symbol": "WEC", "name": "WEC Energy"},
        ],
        "XLC": [  # 通信
            {"symbol": "META", "name": "Meta Platforms"},
            {"symbol": "GOOGL", "name": "Alphabet"},
            {"symbol": "DIS", "name": "Disney"},
            {"symbol": "NFLX", "name": "Netflix"},
            {"symbol": "CMCSA", "name": "Comcast"},
            {"symbol": "T", "name": "AT&T"},
            {"symbol": "VZ", "name": "Verizon"},
            {"symbol": "TMUS", "name": "T-Mobile"},
            {"symbol": "EA", "name": "Electronic Arts"},
            {"symbol": "TTWO", "name": "Take-Two Interactive"},
        ],
    },
    "HK": {
        "HK02800": [  # 盈富基金（恒指成分）
            {"symbol": "HK00700", "name": "腾讯控股"},
            {"symbol": "HK09988", "name": "阿里巴巴"},
            {"symbol": "HK03690", "name": "美团"},
            {"symbol": "HK09618", "name": "京东集团"},
            {"symbol": "HK01810", "name": "小米集团"},
            {"symbol": "HK02318", "name": "中国平安"},
            {"symbol": "HK01299", "name": "友邦保险"},
            {"symbol": "HK00941", "name": "中国移动"},
            {"symbol": "HK03988", "name": "中国银行"},
            {"symbol": "HK01398", "name": "工商银行"},
        ],
        "HK03032": [  # 恒生科技
            {"symbol": "HK00700", "name": "腾讯控股"},
            {"symbol": "HK09988", "name": "阿里巴巴"},
            {"symbol": "HK03690", "name": "美团"},
            {"symbol": "HK09618", "name": "京东集团"},
            {"symbol": "HK01810", "name": "小米集团"},
            {"symbol": "HK09999", "name": "网易"},
            {"symbol": "HK09888", "name": "百度"},
            {"symbol": "HK02015", "name": "理想汽车"},
            {"symbol": "HK09866", "name": "蔚来"},
            {"symbol": "HK01896", "name": "小鹏汽车"},
        ],
        "HK03040": [  # 恒生金融
            {"symbol": "HK02318", "name": "中国平安"},
            {"symbol": "HK01299", "name": "友邦保险"},
            {"symbol": "HK03988", "name": "中国银行"},
            {"symbol": "HK01398", "name": "工商银行"},
            {"symbol": "HK00939", "name": "建设银行"},
            {"symbol": "HK02388", "name": "中银香港"},
            {"symbol": "HK02628", "name": "中国人寿"},
            {"symbol": "HK00005", "name": "汇丰控股"},
            {"symbol": "HK00941", "name": "中国移动"},
            {"symbol": "HK00388", "name": "港交所"},
        ],
        "HK03046": [  # 恒生医疗
            {"symbol": "HK02269", "name": "药明生物"},
            {"symbol": "HK01093", "name": "石药集团"},
            {"symbol": "HK01177", "name": "中国生物制药"},
            {"symbol": "HK02331", "name": "李氏大药厂"},
            {"symbol": "HK01801", "name": "信达生物"},
            {"symbol": "HK06160", "name": "百济神州"},
            {"symbol": "HK02162", "name": "康诺亚"},
            {"symbol": "HK02015", "name": "理想汽车"},
            {"symbol": "HK09926", "name": "康方生物"},
            {"symbol": "HK02128", "name": "和黄医药"},
        ],
    },
}

# 综合评分权重
CHANGE_RATE_WEIGHT = 0.6
VOLUME_RANK_WEIGHT = 0.4


async def select_leaders(
    sector_symbol: str,
    market: str,
    data_service_url: str | None = None,
) -> list[dict[str, Any]]:
    """
    识别指定板块的龙头股。

    获取板块内个股行情，按涨幅+成交量综合排名，
    返回 Top 3 龙头股。

    Args:
        sector_symbol: 板块 ETF 代码，如 "SH512660"、"XLK"。
        market: 市场标识，"CN" / "US" / "HK"。
        data_service_url: data-service 基础 URL，
            默认从环境变量 DATA_SERVICE_URL 读取，
            回退到 "http://localhost:8000"。

    Returns:
        龙头股列表，每个元素包含：
        - symbol: 股票代码
        - name: 股票名称
        - change_rate: 涨跌幅（%）
        - score: 综合评分
        最多返回 3 个。
    """
    constituents = SECTOR_CONSTITUENTS.get(market, {}).get(sector_symbol, [])

    if not constituents:
        logger.warning(
            "No constituents mapped for sector '%s' in market '%s'",
            sector_symbol,
            market,
        )
        return []

    base_url = data_service_url or os.getenv(
        "DATA_SERVICE_URL", "http://localhost:8000"
    )

    # 批量获取成分股行情
    symbols = [c["symbol"] for c in constituents]
    name_map = {c["symbol"]: c["name"] for c in constituents}

    quotes = await _fetch_leader_quotes(base_url, symbols)

    # 计算综合评分
    scored: list[dict[str, Any]] = []
    valid_quotes: list[tuple[str, dict[str, Any]]] = []

    for sym in symbols:
        q = quotes.get(sym, {})
        change_rate = q.get("change_rate")
        if change_rate is None:
            continue
        valid_quotes.append((sym, q))

    # 按成交量排名计算 volume_rank_score
    volume_ranked = sorted(
        valid_quotes,
        key=lambda x: x[1].get("volume", 0) or 0,
        reverse=True,
    )
    total_count = len(volume_ranked)

    for idx, (sym, _q) in enumerate(volume_ranked):
        vol_rank_score = (total_count - idx) / total_count if total_count > 0 else 0
        q = quotes.get(sym, {})
        cr = q.get("change_rate", 0) or 0

        # 标准化 change_rate 到 0-1 范围（假设 ±10% 为正常范围）
        cr_normalized = max(0, min(1, (cr + 10) / 20))

        score = cr_normalized * CHANGE_RATE_WEIGHT + vol_rank_score * VOLUME_RANK_WEIGHT

        scored.append({
            "symbol": sym,
            "name": name_map.get(sym, ""),
            "change_rate": q.get("change_rate"),
            "price": q.get("price"),
            "score": round(score, 4),
        })

    # 按综合评分降序排列
    scored.sort(key=lambda x: x["score"], reverse=True)

    # 返回 Top 3
    return scored[:3]


async def _fetch_leader_quotes(
    base_url: str,
    symbols: list[str],
) -> dict[str, dict[str, Any]]:
    """
    调用 data-service 批量获取个股行情。

    Args:
        base_url: data-service 基础 URL。
        symbols: 股票代码列表。

    Returns:
        {symbol: quote_dict} 映射。
    """
    if not symbols:
        return {}

    url = f"{base_url.rstrip('/')}/api/quote/batch"
    payload = {"symbols": symbols}

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            body = resp.json()

        if body.get("ok") and isinstance(body.get("data"), dict):
            return body["data"]

        logger.warning(
            "data-service leader quotes returned non-ok: %s",
            body.get("message", "unknown"),
        )
        return {}
    except httpx.HTTPStatusError as exc:
        logger.error(
            "data-service leader quotes HTTP error: %s %s",
            exc.response.status_code,
            exc.response.text[:200],
        )
        return {}
    except httpx.RequestError as exc:
        logger.error("data-service leader quotes request error: %s", exc)
        return {}
    except Exception as exc:
        logger.error("Unexpected error in _fetch_leader_quotes: %s", exc)
        return {}
