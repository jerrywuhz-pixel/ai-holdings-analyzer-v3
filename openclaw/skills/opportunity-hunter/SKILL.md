# 机会猎手 Skill — Opportunity Hunter

## 触发条件

### 定时触发
- OpenClaw cron 表达式：
  - A 股：`0 0 16 * * 1-5`（工作日收盘后 16:00）
  - 美股：`0 30 17 * * 1-5`（美东收盘后 17:30，北京时间次日 05:30）
  - 港股：`0 15 16 * * 1-5`（港股收盘后 16:15）
- 触发范围：所有已激活用户（按 market 逐市场生成）

### 手动触发
用户通过微信 clawbot 发送：
- "机会日报"
- "今日机会"
- "市场扫描"
- "猎手报告"

### 指定市场触发
- "机会日报 A股" / "机会日报 CN"
- "机会日报 美股" / "机会日报 US"
- "机会日报 港股" / "机会日报 HK"

## 输入格式

### 自动触发（cron）
由定时调度器传递：
```json
{
  "trigger_type": "cron",
  "market": "CN",
  "date": "2024-01-15"
}
```

### 手动触发
```
用户：机会日报
用户：今日机会 US
```

## 处理逻辑

### 1. Market Scanner — 市场扫描
调用 data-service 获取市场统揽数据：
- HTTP POST http://data-service:8000/api/quote/batch 传入指数成分股
- **CN**：获取上证指数(SH000001)、深证成指(SZ399001)、创业板指(SZ399006) + 批量 A 股涨跌分布
- **US**：获取 SPY、QQQ、DIA、IWM + 市场广度数据
- **HK**：获取 HSI(HKHSI)、HSCEI + 港股市场统计
- 计算当日涨跌分布（advance/decline/flat）、成交额统计

### 2. Sector Hunter — 板块猎手
分析板块表现：
- 调用 data-service 批量获取板块 ETF/指数行情
- **CN**：预定义板块 ETF（军工、银行、医药、消费、科技、新能源、地产、券商、有色、钢铁等）
- **US**：Sector SPDR ETFs（XLF、XLK、XLE、XLV、XLY、XLP、XLI、XLB、XLRE、XLU、XLC）
- **HK**：板块 ETF（盈富基金、恒生科技、恒生金融等）
- 按 change_rate 排序，输出领涨/领跌板块 Top 10

### 3. Leader Selector — 龙头识别
识别热门板块的龙头股：
- 对每个热门板块，获取板块内个股行情（预定义映射）
- 按涨幅 + 成交量综合排名
- 输出各板块龙头 1-3 只
- 综合评分公式：`score = change_rate * 0.6 + volume_rank_score * 0.4`

### 4. Strategy Council — 策略建议
结合持仓数据生成个性化建议：
- 从 Supabase `position_snapshots` 读取用户最新持仓
- 匹配持仓所属板块，判断是否受热门板块带动
- 生成持仓相关板块的个性化建议
- 建议类型：HOLD（持有观望）、ADD（逢低加仓）、REDUCE（减仓锁定）、WATCH（关注入场）

### 5. Report Formatter — 日报格式化
生成 Markdown 格式日报，包含：
- 市场概览表格
- 板块涨跌排行
- 龙头股清单
- 策略建议（含持仓关联）
- 写入 `daily_reports` 表

## 输出格式

### OpportunityReport 结构
```json
{
  "market": "CN",
  "date": "2024-01-15",
  "market_overview": {
    "advance_count": 2850,
    "decline_count": 1520,
    "flat_count": 380,
    "total_volume": 856700000000,
    "index_quotes": [
      {"symbol": "SH000001", "name": "上证指数", "price": 3089.34, "change_rate": 1.23}
    ]
  },
  "top_sectors": [
    {
      "name": "军工",
      "symbol": "SH512660",
      "change_rate": 3.45,
      "volume": 12340000000,
      "leaders": [
        {"symbol": "SH600893", "name": "航发动力", "change_rate": 5.67},
        {"symbol": "SH600760", "name": "中航沈飞", "change_rate": 4.32}
      ]
    }
  ],
  "strategy_suggestions": [
    {
      "symbol": "SH600519",
      "action": "HOLD",
      "reason": "贵州茅台属消费板块，今日消费板块小幅上涨+0.8%，当前更适合继续观察持有"
    }
  ],
  "formatted_report": "## 市场机会观察 - A股 - 2024-01-15\n..."
}
```

### 给用户的消息（Markdown）
```markdown
## 市场机会观察 - A股 - 2024-01-15

### 市场概览
| 指标 | 数值 |
|------|------|
| 上涨 | 2850 |
| 下跌 | 1520 |
| 平盘 | 380 |
| 总成交额 | ¥8567亿 |

**主要指数：**
- 上证指数 3089.34 ▲+1.23%
- 深证成指 10234.56 ▲+1.45%
- 创业板指 2034.12 ▲+1.89%

### 板块表现前 10
| 排名 | 板块 | 涨跌幅 | 成交额 |
|------|------|--------|--------|
| 1 | 军工 | +3.45% | ¥123亿 |
| 2 | 券商 | +2.89% | ¥98亿 |
| ... | ... | ... | ... |

### 代表性个股速览
**军工板块代表性个股：**
- 航发动力(SH600893) ▲+5.67%
- 中航沈飞(SH600760) ▲+4.32%

### 持仓观察与操作纪律
- **贵州茅台(SH600519)**：继续观察持有。依据：消费板块小幅上涨 +0.8%，当前未触发减仓纪律。
- **宁德时代(SZ300750)**：加入关注清单观察。依据：新能源板块今日回调 -1.2%，等板块企稳后再评估是否加仓。

以上内容用于观察和复盘，交易前请以实时行情、账户可用资金和你的交易纪律为准。
```

### 数据库输出字段
写入 `daily_reports` 表：
```json
{
  "report_type": "opportunity_cn",
  "report_date": "2024-01-15",
  "market": "CN",
  "content": {
    "market_overview": {...},
    "top_sectors": [...],
    "strategy_suggestions": [...]
  },
  "formatted_markdown": "## 市场机会观察..."
}
```

## 错误处理

| 错误场景 | 处理方式 |
|----------|----------|
| data-service 不可用 | 跳过市场扫描和板块分析，生成极简版报告（仅策略建议），记录错误到 job_runs |
| 部分板块行情获取失败 | 跳过失败板块，基于可用数据继续分析，在报告中标注"部分数据缺失" |
| 龙头股行情获取失败 | 仅展示成功获取的龙头股，不足 3 只则展示已有结果 |
| Supabase 连接失败 | 仍生成报告但不写入数据库，本地缓存后重试 |
| 持仓数据为空 | 策略建议部分显示"暂无持仓；以上板块和个股仅作为观察线索，不构成买入建议"，不调用持仓关联分析 |
| 所有数据源均失败 | 返回"今日市场数据暂时不可用，请稍后重试"，记录错误并等待下次重试 |
| 同一市场同日重复生成 | 查询 daily_reports 是否已存在，存在则 UPDATE 而非 INSERT |

## 示例

### 示例 1：Cron 自动触发 A 股日报
```
[cron 16:00 触发]

系统：正在生成 A 股市场机会观察...
      已获取主要指数、市场涨跌分布和板块表现。
      已结合你的持仓生成观察结论。
      稍后会通过微信发送摘要，完整报告可在 WebApp 查看。
```

### 示例 2：手动触发美股日报
```
用户：机会日报 US

系统：美股市场机会观察已生成。
      S&P 500 4,890.23 ▲+0.87%
      表现较强板块：科技(XLK) +2.15%
      已结合你的持仓生成观察结论。
      完整报告可在 WebApp 查看。
```

### 示例 3：数据源部分失败
```
系统：A 股市场机会观察已生成，但部分板块数据暂时缺失。
      本次结论只基于已获取的数据；银行、地产、钢铁板块暂不参与排序。
      相关标的仅供观察，交易前请重新查看实时行情。
```

## 数据库操作

- **daily_reports**：INSERT / UPDATE（市场日报，ON CONFLICT 更新）
- **position_snapshots**：SELECT（读取用户最新持仓）
- **job_runs**：INSERT（任务执行日志）
- **data-service**：POST /api/quote/batch（批量行情获取）

## 架构关系

```
Cron / 手动触发
       │
       ▼
[HermesOrchestrator]
       │
       ├──→ [Market Scanner] ──→ data-service /api/quote/batch
       │         │
       │         ▼
       │    market_overview
       │
       ├──→ [Sector Hunter] ──→ data-service /api/quote/batch
       │         │
       │         ▼
       │    top_sectors (ranked)
       │
       ├──→ [Leader Selector] ──→ data-service /api/quote/batch
       │         │
       │         ▼
       │    leaders per sector
       │
       ├──→ [Strategy Council] ──→ Supabase position_snapshots
       │         │
       │         ▼
       │    strategy_suggestions
       │
       ├──→ [Report Formatter]
       │         │
       │         ▼
       │    formatted_markdown
       │
       └──→ [Supabase daily_reports] ──→ INSERT/UPDATE
                │
                ▼
           [delivery_runs] ──→ 微信推送 ──→ 用户微信
```
