# Position Aggregate Skill — 持仓聚合

## 触发条件

### 手动触发
用户通过微信 clawbot 发送以下指令：
- "更新持仓"
- "刷新持仓"
- "计算持仓"
- "持仓快照"

### 自动触发
- `trade_events` 表发生 INSERT 或 UPDATE（由 PostgreSQL Trigger `trigger_update_positions` 调用）
- 每日开盘前（cron 09:00）自动刷新一次，确保持仓与昨日一致

### 防抖机制
- 自动触发时，若 5 秒内已有聚合任务在执行，合并为一次执行
- 手动触发不受防抖限制，立即执行

## 输入格式

### 手动触发
纯文本指令，无额外参数。支持限定 symbol：
- "更新持仓 茅台" — 仅更新茅台持仓
- "刷新持仓 AAPL" — 仅更新 AAPL 持仓

### 自动触发
由 PostgreSQL Trigger 传递参数：
```json
{
  "user_id": "uuid",
  "affected_symbols": ["600519.SH", "AAPL"],
  "trigger_event_id": "evt_xxx",
  "trigger_type": "INSERT | UPDATE | DELETE | CRON"
}
```

## 处理逻辑

### 1. 获取待计算范围
- 若指定 symbol：仅计算该 symbol
- 若未指定：获取该用户所有 trade_events 涉及的唯一 symbol 列表

### 2. 读取 trade_events
按 user_id + symbol 过滤，读取所有状态为 `confirmed` 的交易事件：
```sql
SELECT * FROM trade_events
WHERE user_id = $1
  AND symbol = $2
  AND status = 'confirmed'
ORDER BY trade_date ASC, created_at ASC;
```

### 3. 逐 symbol 计算持仓

```
对于每个 symbol:
  total_quantity = SUM(BUY quantity) - SUM(SELL quantity)
  total_cost = SUM(BUY price * quantity) - SUM(SELL price * quantity)  // 简化 FIFO
  average_cost = total_cost / total_quantity  (if total_quantity > 0)
  
  // 记录计算溯源
  computed_from_event_ids = [所有参与计算的 event_id 列表]
  
  // 实时价格获取（仅手动触发或日终时）
  current_price = call market_data_api(symbol)
  unrealized_pnl = (current_price - average_cost) * total_quantity
```

**成本算法**：默认使用加权平均成本法（Average Cost）。未来可扩展 FIFO/LIFO 配置。

### 4. 写入 position_snapshots

**插入或更新逻辑**：
- 查询该 user_id + symbol 是否已有记录
- 若无：INSERT
- 若有且 `computed_from_event_ids` 有变化：UPDATE
- 若有且无变化：跳过写入（幂等性）

### 5. 生成响应

聚合完成后返回给用户：
- 总持仓数量
- 各 symbol 持仓列表（数量、均价、市值、盈亏）
- 本次计算涉及的 trade_events 数量

## 输出格式

### 给用户的消息
```
持仓快照已更新（{symbol_count} 只标的）

当前持仓：
├─ 贵州茅台(SH600519)  200股  均价¥1650.00  市值¥336000  浮盈+¥10000
├─ 宁德时代(SZ300750)  300股  均价¥200.00   市值¥63000   浮亏-¥3000
├─ Apple(US:AAPL)      50股   均价$185.00   市值$9750    浮盈+$250

总持仓市值：约 ¥399,000
```

### position_snapshots 表结构
```json
{
  "id": "uuid",
  "user_id": "uuid",
  "symbol": "600519.SH",
  "market": "CN",
  "total_quantity": 200,
  "average_cost": 1650.00,
  "total_cost": 330000.00,
  "current_price": 1680.00,
  "market_value": 336000.00,
  "unrealized_pnl": 10000.00,
  "currency": "CNY",
  "realized_pnl_ytd": 5000.00,
  "computed_from_event_ids": ["evt_001", "evt_002", "evt_005"],
  "last_computed_at": "2024-01-15T15:30:00Z",
  "last_trade_event_id": "evt_005",
  "created_at": "2024-01-01T00:00:00Z",
  "updated_at": "2024-01-15T15:30:00Z"
}
```

### 聚合日志（写入 job_runs）
```json
{
  "job_type": "position_aggregate",
  "user_id": "uuid",
  "status": "success",
  "input": {"symbols": [...], "trigger": "manual|auto"},
  "output": {"updated": 3, "unchanged": 0, "failed": 0},
  "started_at": "timestamp",
  "completed_at": "timestamp"
}
```

## 错误处理

| 错误场景 | 处理方式 |
|----------|----------|
| trade_events 为空 | 返回"暂无交易记录，请先录入交易" |
| 净持仓为 0（全部清仓）| 保留 position_snapshots 记录但标记 `is_closed=true`，`total_quantity=0` |
| 卖出数量 > 买入数量 | 标记数据异常，记录 `warning: 'negative_position'`，通知用户核对交易记录 |
| 市场价格获取失败 | 跳过市值和盈亏计算，使用 `market_value=null`，不阻塞聚合 |
| 计算溯源 event_ids 超过 1000 个 | 截断存储最近 1000 个，记录 `warning: 'event_ids_truncated'` |
| 并发写入冲突 | 使用 `ON CONFLICT (user_id, symbol) DO UPDATE` 保证幂等 |

## 示例

### 示例 1：手动触发全量更新
```
用户：更新持仓
系统：持仓快照已更新（3 只标的）

      当前持仓：
      ├─ 贵州茅台(SH600519)  200股  均价¥1650.00  市值¥336000  浮盈+¥10000
      ├─ 宁德时代(SZ300750)  300股  均价¥200.00   市值¥63000   浮亏-¥3000
      ├─ Apple(US:AAPL)      50股   均价$185.00   市值$9750    浮盈+$250
      
      总持仓市值：约 ¥399,000
```

### 示例 2：交易后自动触发
```
用户：买入茅台100股@1680（确认后）
系统：已记录买入交易。
      
      持仓已自动刷新。
      
      持仓快照已更新（贵州茅台）：
      贵州茅台(SH600519)  200股  均价¥1650.00 → ¥1660.00  市值¥336000
```

### 示例 3：清仓后状态
```
用户：卖出茅台200股@1700（确认后）
系统：已记录卖出交易。
      
      持仓已自动刷新。
      
      贵州茅台(SH600519) 已清仓（0股）
      本次卖出实现盈亏：+¥8000
```

## 数据库操作

- **trade_events**：SELECT（读取用户全部 confirmed 交易事件）
- **position_snapshots**：SELECT（查询现有持仓）
- **position_snapshots**：INSERT / UPDATE（写入或更新快照，ON CONFLICT）
- **job_runs**：INSERT（记录聚合任务执行日志）

## 性能考量

- 单用户 symbol 数量通常 < 50，聚合可在 < 500ms 完成
- trade_events 按 (user_id, symbol, trade_date) 建立复合索引
- 批量更新使用 `INSERT ... ON CONFLICT DO UPDATE` 减少往返
- 高频交易用户（>1000 events）启用增量计算：仅重新计算受影响的 symbol
