# Quant Options Strategy Skill — 量化与期权策略

## 触发条件

### 手动触发
用户通过微信 clawbot 或 OpenClaw 管理端发送：
- "量化策略"
- "回测半导体"
- "光通信策略"
- "期权策略"
- "生成期权方案"
- "Hermes 策略评估"

### 定时触发
- A 股：工作日 16:20 后更新半导体/光通信策略信号
- 美股：美东收盘后更新美股半导体策略信号
- 期权：标的进入观察清单、隐含波动率异常、财报/事件窗口前触发风险检查

### 非触发条件
- 交易录入、券商成交解析、持仓聚合、普通日报生成不由本 Skill 处理。
- 仅问行情或普通板块涨跌时，优先交给 opportunity-hunter；涉及回测、仓位、组合、期权结构或策略执行时转入本 Skill。

## 职责边界

**明确分工：所有量化策略和期权相关策略统一由 Hermes 执行。**

- Hermes 负责：策略研究、回测验证、信号生成、组合权重、风控阈值、期权希腊值评估、期权价差结构、策略执行建议。
- Trade Input 负责：记录用户已确认交易。
- Broker Parse 负责：解析券商成交提醒。
- Position Aggregate 负责：聚合实际持仓。
- Daily Analysis / Weekly Report 负责：基于 Hermes 输出和持仓数据做复盘与报告。
- Opportunity Hunter 负责：市场扫描、板块机会发现，并把需要量化或期权判断的事项交给 Hermes。

## 输入格式

### 量化策略评估
```json
{
  "trigger_type": "manual|cron",
  "strategy_family": "semiconductor_optical",
  "markets": ["CN", "US"],
  "universe": ["US_SEMI_TOP30", "CN_SEMI_OPTICAL_TOP50"],
  "as_of_date": "2026-04-26",
  "risk_profile": "balanced"
}
```

### 期权策略评估
```json
{
  "trigger_type": "manual|event",
  "strategy_family": "options",
  "underlying": "NVDA",
  "market": "US",
  "direction": "bullish|bearish|neutral|hedge",
  "max_loss": 1000,
  "event_window": "earnings|none"
}
```

## 处理逻辑

### Hermes MVP 部署入口
- 核心模型：`sellput_models.py`
- 开仓/持仓评分引擎：`sellput_scorecard.py`
- Markdown 报告格式化：`sellput_formatter.py`
- Hermes 服务入口：`hermes_sellput.py`
- Gateway cron/API：`POST /api/cron/sellput-score`

当前 MVP 支持标准化输入下的单合约开仓评分、持仓评分、候选合约排序扫描。开仓评分通过 `FutuSellPutDataSource` 调用 data-service 的 `/api/quote/{symbol}?source=futu` 补齐标的实时行情，并在报告中标注 `market_data.source=futu`。真实期权链数据源、历史回测数据仓库和自动交易执行不在 MVP 范围内。

### 1. 数据准备
- 读取行情、成交量、复权价格、持仓、标的池、期权链和无风险利率。
- Sell Put 开仓评分优先使用 Futu OpenD 的标的实时行情；若 data-service 中 Futu 不可用，data-service 内部按持仓行情优先级回退到 Yahoo/Tushare/Longbridge/AkShare。
- 标准化市场字段：`CN`、`US`、`HK`。
- 丢弃上市时间过短、流动性不足、停牌或缺失关键价格字段的标的。

### 2. 半导体和光通信量化策略
当前已验证策略族：

| 策略 | 标的池 | 核心逻辑 | 使用场景 |
|------|--------|----------|----------|
| S1 多因子动量轮动 | 美股半导体 TOP30、A股光通信/半导体 TOP50 | 60 日动量 60% + 20 日低波动 40%，月度调仓 | 趋势行情、强主题行情 |
| S2 风险平价智能贝塔 | 同上 | 滚动 Sharpe 50% + 距 252 日高点 30% + 成交量稳定 20%，逆波动加权 | 控回撤、降低个股集中风险 |
| S3 跨市场联动 | 美股半导体信号控制 A 股仓位 | 美股半导体 20 日动量和回撤决定 A 股暴露 30%-100% | 风险预算、跨市场分散 |

有效性判定：
- 年化收益为正；
- Sharpe ratio > 0.4；
- 最大回撤低于策略风险预算；
- 相对基准具备收益、波动或回撤至少一项优势；
- 最近一期持仓可解释且不集中于无法交易标的。

### 3. 期权策略
Hermes 可评估但必须标注最大亏损、到期日和波动率假设：
- 方向性：买入看涨/看跌、牛市价差、熊市价差。
- 收益增强：备兑看涨、现金担保看跌。
- 波动率：跨式、宽跨式、日历价差。
- 风险对冲：保护性看跌、领口策略。

禁止输出无法定义最大亏损的裸卖期权建议，除非用户配置明确允许且账户权限、保证金和风控通过。

### 4. 风控
- 单一标的建议权重不得超过用户风险配置上限。
- 策略信号必须给出止损、失效条件或复核日期。
- 对期权必须输出最大亏损、盈亏平衡点、主要希腊值风险和流动性提醒。
- 所有策略输出均为研究和执行建议，不直接写入 `trade_events`；真实交易仍需用户确认后由 Trade Input 记录。

## 输出格式

### StrategyEvaluation
```json
{
  "strategy_family": "semiconductor_optical",
  "as_of_date": "2026-04-26",
  "is_effective": true,
  "evidence": {
    "A_S1_Momentum": {"total_return": 682.58, "sharpe": 1.284, "max_drawdown": -39.39},
    "A_S2_RiskParity": {"total_return": 292.52, "sharpe": 0.983, "max_drawdown": -35.54},
    "S3_CrossMkt": {"total_return": 108.51, "sharpe": 0.578, "max_drawdown": -39.58}
  },
  "recommendation": "enable_for_hermes",
  "limits": ["US_S1 alpha versus US benchmark is weak", "all results are historical backtests"]
}
```

### 用户消息
```markdown
## Hermes 策略评估

结论：半导体和光通信策略可启用，但按风险分层执行。

- 主用：A股 S1 动量轮动、A股 S2 风险平价。
- 辅助：S3 跨市场联动用于仓位控制。
- 谨慎：美股 S1 更适合主题暴露，超额收益不稳定。
```

## 错误处理

| 错误场景 | 处理方式 |
|----------|----------|
| 缺少行情数据 | 返回数据缺口，禁止生成执行建议 |
| 回测样本过短 | 标记 `is_effective=false`，仅输出研究观察 |
| 期权链缺失 | 不生成期权结构，只给出需要补充的数据 |
| 最大亏损不可计算 | 拒绝输出策略，要求改用有限风险结构 |
| 用户风险配置缺失 | 使用 conservative 默认配置并提示补充 |

## 数据库操作

- `position_snapshots`: SELECT，读取当前持仓和集中度。
- `daily_reports`: INSERT/UPDATE，写入 Hermes 策略评估摘要。
- `job_runs`: INSERT/UPDATE，记录回测和策略任务状态。
- `trade_events`: 不直接写入；真实交易必须由 Trade Input 在用户确认后写入。
