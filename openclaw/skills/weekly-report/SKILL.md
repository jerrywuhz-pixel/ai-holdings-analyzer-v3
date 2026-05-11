# 周报生成 Skill — Weekly Report

## 触发条件

### 定时触发
- OpenClaw cron 表达式：`0 0 17 * * 5`（每周五收盘后 17:00）
- 触发范围：所有已激活且本周有交易记录或持仓变动的用户

### 手动触发
用户通过微信 clawbot 发送：
- "周报"
- "本周复盘"
- "生成周报"
- "本周总结"

### 条件触发
- 当周 `trade_events` 数量 > 0 时自动执行
- 若当周无交易且无持仓，仅生成极简市场回顾版

## 输入格式

### 自动触发（cron）
由定时调度器传递：
```json
{
  "trigger_type": "cron",
  "tenant_id": "uuid",
  "week_start": "2024-01-15",
  "week_end": "2024-01-19"
}
```

### 手动触发
```
用户：周报
用户：本周复盘
```

## 处理逻辑

### 1. 数据收集

#### 1.1 获取本周日报
从 `daily_reports` 获取本周 5 个交易日的日报数据：
```sql
SELECT * FROM daily_reports
WHERE tenant_id = $1
  AND report_date >= $week_start
  AND report_date <= $week_end
  AND report_type LIKE 'opportunity_%'
ORDER BY report_date ASC;
```

#### 1.2 获取最新持仓
从 `position_snapshots` 获取用户最新持仓快照：
```sql
SELECT * FROM position_snapshots
WHERE tenant_id = $1
  AND total_quantity > 0
ORDER BY market_value DESC;
```

#### 1.3 获取本周交易记录
从 `trade_events` 获取本周交易：
```sql
SELECT * FROM trade_events
WHERE tenant_id = $1
  AND trade_date >= $week_start
  AND trade_date <= $week_end
  AND status = 'confirmed'
ORDER BY trade_date ASC, created_at ASC;
```

### 2. 数据预处理
- 汇总本周各市场涨跌趋势（基于日报 market_overview）
- 计算本周交易统计：买入次数、卖出次数、净买入金额、实现盈亏
- 持仓变动：新增持仓、清仓、加仓、减仓
- 板块表现汇总：本周持续强势/弱势板块

### 3. AI 周报生成

#### 3.1 Prompt 构建
```
你是一位资深投资顾问，请基于以下数据生成本周投资周报。

【本周市场概览】
{daily_reports_summary}

【本周交易记录】
{formatted_trades}

【当前持仓】
{formatted_positions}

【本周板块趋势】
{sector_trends}

请按以下结构输出（Markdown格式）：
1. 本周市场回顾：各市场整体表现与关键事件
2. 交易总结：本周操作回顾，买卖逻辑复盘
3. 持仓分析：持仓组合表现、盈亏原因分析
4. 板块洞察：本周强势/弱势板块及下周展望
5. 下周策略：基于当前持仓和市场趋势的策略建议
6. 风险提示：集中度、板块、宏观等风险因素

要求：
- 语言简洁专业，适合投资者快速阅读
- 数据必须准确，不得编造
- 结合本周市场环境给出建设性建议
- 如有亏损，给出客观分析而非批评
```

#### 3.2 模型调用
```
模型：gpt-5-mini
温度：0.3
最大 token：3000
超时：45 秒
重试：失败时重试 2 次（指数退避）
```

### 4. 结果存储

#### 4.1 写入 daily_reports
```sql
INSERT INTO daily_reports (tenant_id, report_type, report_date, market, content, formatted_markdown)
VALUES ($1, 'weekly_summary', $week_end, 'CN', $content, $markdown)
ON CONFLICT (tenant_id, report_type, report_date)
DO UPDATE SET content = EXCLUDED.content, formatted_markdown = EXCLUDED.formatted_markdown;
```

#### 4.2 生成 delivery_runs
推送至用户微信（分段发送，避免超长消息）。

#### 4.3 配额扣减
- 成功调用后：user.daily_ai_calls -= 1

## 输出格式

### WeeklyReport 结构
```json
{
  "tenant_id": "uuid",
  "week_start": "2024-01-15",
  "week_end": "2024-01-19",
  "summary": {
    "cn_market_trend": "本周A股整体上涨，上证指数+2.3%",
    "us_market_trend": "本周美股震荡上行，SPY+0.8%",
    "hk_market_trend": "本周港股回调，恒指-1.2%"
  },
  "positions_analysis": [
    {
      "symbol": "SH600519",
      "name": "贵州茅台",
      "weekly_change": "+3.5%",
      "action": "HOLD",
      "comment": "消费板块本周回暖，茅台表现优于大盘"
    }
  ],
  "trades_review": {
    "total_trades": 5,
    "buy_count": 3,
    "sell_count": 2,
    "net_buy_amount": 256000,
    "realized_pnl": 8500
  },
  "strategy_suggestions": [
    {
      "symbol": "SZ300750",
      "action": "WATCH",
      "reason": "新能源板块下周有政策会议，可关注低吸机会"
    }
  ],
  "formatted_markdown": "## 投资周报 - 2024年第3周..."
}
```

### 给用户的消息（Markdown 示例）
```markdown
## 投资周报 - 2024年第3周（01.15 - 01.19）

### 本周市场回顾
- **A股**：上证指数收于3,089 ▲+2.3%，深证成指 ▲+1.8%，创业板 ▲+2.1%
- **美股**：SPY ▲+0.8%，纳指受科技股带动表现较好
- **港股**：恒指 ▼-1.2%，受外围市场拖累

### 交易总结
本周共 5 笔交易：
- 买入：3 笔（贵州茅台、宁德时代、AAPL）
- 卖出：2 笔（中国平安、TSLA）
- 净买入额：¥256,000
- 本周实现盈亏：+¥8,500

### 持仓分析
| 标的 | 周涨跌 | 状态 | 建议 |
|------|--------|------|------|
| 贵州茅台 | +3.5% | 浮盈 | 持有 |
| 宁德时代 | -1.2% | 浮亏 | 关注 |
| AAPL | +1.8% | 浮盈 | 持有 |

### 下周策略
1. 茅台可继续持有，关注年报预告时间
2. 宁德时代等待板块企稳后再加仓
3. 美股财报季临近，AAPL 注意夜盘波动

### 风险提示
- 茅台仓位集中度仍偏高（62%），注意分散
- 新能源板块政策不确定性较大
```

## 错误处理

| 错误场景 | 处理方式 |
|----------|----------|
| 本周无日报数据 | 从 position_snapshots 和 trade_events 直接生成简化周报 |
| 模型调用超时/失败 | 重试 2 次后降级为模板化周报总结 |
| 配额不足 | 跳过深度分析，仅输出结构化数据总结 |
| 无交易且无持仓 | 输出"本周无交易和持仓记录" + 市场回顾 |
| 数据查询失败 | 回滚整个流程，记录错误并提示稍后重试 |
| 日报数据不完整 | 基于可用数据生成，标注"部分数据缺失" |
| Supabase 写入失败 | 本地缓存后重试，不影响报告返回给用户 |

## 示例

### 示例 1：Cron 自动触发周报
```
[cron 周五 17:00 触发]

系统：正在生成本周投资周报...
     已汇总本周市场、持仓和交易记录。
     稍后会通过微信发送摘要，完整报告可在 WebApp 查看。
```

### 示例 2：手动触发
```
用户：周报

系统：正在生成本周投资周报...
      
      投资周报已生成。
      本周交易：5笔 | 净买入：¥256,000
      持仓：3只 | 总市值：约 ¥399,000
      ...
```

### 示例 3：本周无交易
```
用户：周报

系统：本周无交易记录。

      当前持仓（3只）：总市值约 ¥399,000
      
      本周市场回顾：
      A股 ▲+2.3% | 美股 ▲+0.8% | 港股 ▼-1.2%
      
      完整市场周报可在 WebApp 查看。
```

## 数据库操作

- **daily_reports**：SELECT（读取本周日报）、INSERT/UPDATE（写入周报）
- **position_snapshots**：SELECT（读取最新持仓）
- **trade_events**：SELECT（读取本周交易）
- **job_runs**：INSERT（任务执行日志）
- **delivery_runs**：INSERT（推送任务记录）
- **users**：SELECT/UPDATE（配额检查与扣减）

## 扩展计划

| 阶段 | 功能 |
|------|------|
| Phase 5.2 | 基础周报生成（当前） |
| Phase 5.3 | 月报/季报聚合分析 |
| Phase 6.0 | 多模型对比周报（GPT / Claude） |
| Phase 6.1 | 用户自定义周报模板与关注点 |
| Phase 6.2 | 周报 PDF 导出与分享 |
