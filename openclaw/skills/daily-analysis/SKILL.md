# Daily Analysis Skill — 日终分析

## 触发条件

### 定时触发
- OpenClaw cron 表达式：`0 30 15 * * 1-5`（工作日 A股收盘后 15:30）
- 触发范围：所有已激活且当日有交易记录的用户

### 手动触发
用户通过微信 clawbot 发送：
- "今日复盘"
- "日终分析"
- "生成日报"

### 条件触发
- 当日 `trade_events` 数量 > 0 时自动执行
- 若当日无交易，仅生成极简版（市场行情 + 持仓概览）

## 输入格式

### 自动触发
由 cron 触发器传递：
```json
{
  "trigger_type": "cron",
  "analysis_date": "2024-01-15",
  "user_scope": "all_active_with_trades"
}
```

### 手动触发
```
用户：今日复盘
```
支持指定日期：
```
用户：复盘 2024-01-10
```

## 处理逻辑

### 1. 配额检查
```
调用模型前检查：
- 用户剩余 `daily_ai_calls` 配额 > 0
- 系统全局 AI 调用配额 > 0
- 若深度分析额度不足，仅输出结构化数据总结
```

### 2. 数据收集

#### 2.1 当日交易事件
```sql
SELECT * FROM trade_events
WHERE user_id = $1
  AND trade_date = $analysis_date
  AND status = 'confirmed'
ORDER BY created_at ASC;
```

#### 2.2 当前持仓快照
```sql
SELECT * FROM position_snapshots
WHERE user_id = $1
  AND total_quantity > 0
ORDER BY market_value DESC;
```

#### 2.3 历史对比（可选）
```sql
SELECT * FROM position_snapshots
WHERE user_id = $1
  AND last_computed_at < $analysis_date::timestamp
ORDER BY last_computed_at DESC
LIMIT 1;
```

### 3. 分析内容构建

#### 3.1 数据预处理
- 按 side 分组统计今日买入/卖出
- 计算今日净买入金额、净卖出金额
- 对比昨日持仓变化（新增/清仓/加仓/减仓）
- 计算当日实现盈亏（已卖出部分的价差收益）

#### 3.2 分析提示词构建

```
你是一位资深投资分析师，请基于以下数据生成今日投资复盘报告。

【今日交易】
{formatted_trades}

【当前持仓】
{formatted_positions}

【昨日持仓对比】
{formatted_changes}

请按以下结构输出（Markdown格式）：
1. 今日操作总结：列出每笔交易及操作逻辑
2. 当前持仓概览：按市值排序，标注重点持仓
3. 盈亏分析：实现盈亏 + 浮动盈亏，分析盈亏原因
4. 明日关注要点：基于持仓和今日市场，提出 2-3 条关注建议
5. 风险提醒：如有集中度风险、Sector 风险等

要求：
- 语言简洁专业，适合投资者快速阅读
- 数据必须准确，不得编造
- 若有亏损，给出建设性分析而非单纯批评
```

### 4. 模型调用

```
模型：gpt-5-mini（平衡成本与质量）
温度：0.3（确保数据准确性）
最大 token：2000
超时：30 秒
重试：失败时重试 2 次（指数退避）
```

### 5. 结果存储

#### 5.1 写入 daily_analysis 表

需要先确保表存在（由 migrations 创建）：
```sql
CREATE TABLE IF NOT EXISTS daily_analysis (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES users(id),
  analysis_date DATE NOT NULL,
  trade_summary JSONB,
  position_snapshot JSONB,
  ai_analysis_text TEXT,
  ai_model VARCHAR(50),
  ai_tokens_used INTEGER,
  delivery_status VARCHAR(20) DEFAULT 'pending',
  created_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(user_id, analysis_date)
);
```

#### 5.2 生成 delivery_runs 记录

```json
{
  "run_type": "daily_analysis",
  "user_id": "uuid",
  "analysis_id": "analysis_uuid",
  "target_platform": "wechat",
  "status": "ready",
  "content_summary": "日终分析报告（{trade_count}笔交易，{position_count}只持仓）",
  "scheduled_at": "2024-01-15T15:35:00Z",
  "created_at": "2024-01-15T15:30:00Z"
}
```

#### 5.3 claw 插件推送
- 通过 OpenClaw Gateway 的 claw 插件推送到用户微信
- 推送内容：AI 分析文本（分段，避免微信单条消息过长）
- 推送后更新投递状态

### 6. 配额扣减
- 成功调用后：user.daily_ai_calls -= 1
- 记录 `daily_analysis.ai_tokens_used`

## 输出格式

### 分析报告示例
```markdown
## 今日投资复盘（2024-01-15）

### 今日操作总结
- **买入** 贵州茅台(SH600519) 100股 @¥1680.00 | 标签：业绩驱动
  逻辑：茅台发布业绩预告超预期，早盘回调至1680附近加仓
- **卖出** 宁德时代(SZ300750) 100股 @¥210.00 | 标签：趋势跟随
  逻辑：股价触及短期压力位，减仓锁定部分利润

**今日净买入额**：¥168,000 | **净卖出额**：¥21,000

### 当前持仓概览
| 标的 | 数量 | 均价 | 市值 | 浮盈/亏 |
|------|------|------|------|---------|
| 贵州茅台 | 200股 | ¥1650 | ¥336,000 | +¥6,000 |
| 宁德时代 | 200股 | ¥195 | ¥42,000 | +¥3,000 |
| AAPL | 50股 | $185 | $9,750 | +$250 |

**总持仓市值**：约 ¥399,000

### 盈亏分析
- **今日实现盈亏**：+¥1,500（宁德时代减仓）
- **浮动盈亏**：+¥9,000（贵州茅台+宁德时代）
- 重仓茅台贡献主要浮盈，逻辑成立

### 明日关注要点
1. **茅台业绩预告全文**：关注机构评级变化，若评级上调可考虑持仓
2. **宁德突破验证**：今日减仓后若明日放量突破215，可重新接回
3. **美股开盘**：AAPL 财报临近，注意夜盘波动对持仓影响

### 风险提醒
- 茅台仓位占比 84%，集中度偏高，建议关注分散机会
- 现金比例偏低，预留加仓空间不足
```

### 极简版（无交易且配额不足时）
```
今日无交易记录。

当前持仓（3只）：
贵州茅台 200股 | 宁德时代 200股 | AAPL 50股
总持仓市值：约 ¥399,000

[今日深度分析额度已用完，明日恢复后再生成完整分析]
```

### 数据库输出字段
```json
{
  "id": "uuid",
  "user_id": "uuid",
  "analysis_date": "2024-01-15",
  "trade_summary": {
    "trade_count": 2,
    "buy_amount": 168000,
    "sell_amount": 21000,
    "realized_pnl": 1500,
    "trades": [...]
  },
  "position_snapshot": {
    "position_count": 3,
    "total_market_value": 399000,
    "positions": [...]
  },
  "ai_analysis_text": "markdown文本...",
  "ai_model": "gpt-5-mini",
  "ai_tokens_used": 1250,
  "delivery_status": "delivered",
  "created_at": "2024-01-15T15:32:00Z"
}
```

## 错误处理

| 错误场景 | 处理方式 |
|----------|----------|
| 配额不足 | 跳过深度分析，输出极简版；提示"今日深度分析额度已用完，明日恢复" |
| 模型调用超时/失败 | 重试 2 次后仍失败，降级为模板化总结；记录错误 |
| 当日无交易且无持仓 | 输出"暂无交易和持仓记录"，不调用 AI |
| 数据查询失败 | 回滚整个分析流程，记录错误并提示稍后重试 |
| 微信推送失败 | 标记重试；用户可通过"今日复盘"手动获取 |
| 重复分析同一日期 | 先查询 `daily_analysis` 是否已存在，存在则 UPDATE 而非 INSERT |
| 单用户数据量过大 | trade_events > 500 笔时，仅取最近 30 天数据用于分析 |

## 示例

### 示例 1：正常日终自动分析
```
[cron 15:30 触发]

系统：正在生成日终复盘摘要...
      
用户收到微信推送：
【今日投资复盘（2024-01-15）】
今日操作总结：
- 买入 贵州茅台 100股 @¥1680
...
完整报告可在 WebApp 查看。
```

### 示例 2：手动触发复盘
```
用户：今日复盘
系统：正在生成今日投资复盘...
      
      【今日投资复盘（2024-01-15）】
      ...
```

### 示例 3：配额不足
```
用户：今日复盘
系统：今日无交易记录。
      
      当前持仓（3只）：总市值约 ¥399,000
      
      今日深度分析额度已用完。你仍可查看当前持仓摘要；完整深度分析将在额度恢复后生成。
```

## 数据库操作

- **daily_analysis**：INSERT / UPDATE（日终分析报告）
- **trade_events**：SELECT（读取当日交易）
- **position_snapshots**：SELECT（读取当前持仓）
- **users**：SELECT（用户配置与配额）
- **users**：UPDATE（扣减 daily_ai_calls 配额）
- **delivery_runs**：INSERT（推送任务记录）
- **job_runs**：INSERT（任务执行日志）

## 扩展计划

| 阶段 | 功能 |
|------|------|
| Phase 1.2 | 基础日终分析（当前） |
| Phase 1.3 | 周报/月报聚合分析 |
| Phase 2.0 | 接入实时行情，盘中异动提醒 |
| Phase 2.1 | 多模型对比（GPT / Claude / 本地模型） |
| Phase 2.2 | 用户自定义分析模板与提示词 |
