# OpenClaw Skills 总览

> AI 持仓投资分析系统 2.0 — Phase 1 Sprint 1.2
> 所有 Skills 通过 OpenClaw Gateway 统一管理，经 Gateway Data Access Middleware 访问数据库。

---

## Skill 清单

| Skill | 目录 | 触发方式 | 核心职责 | 数据库表 |
|-------|------|----------|----------|----------|
| **Trade Input** | `trade-input/` | 微信指令（买入/卖出/BUY/SELL） | 解析用户自然语言交易指令，写入 trade_events | trade_events, stock_catalog |
| **Broker Parse** | `broker-parse/` | 转发券商成交提醒消息 | 解析券商微信消息，自动录入交易，去重防重复 | trade_events |
| **Position Aggregate** | `position-aggregate/` | 交易写入后自动触发 / 手动"更新持仓" | 按 symbol 聚合 trade_events，计算持仓快照 | trade_events, position_snapshots, job_runs |
| **Daily Analysis** | `daily-analysis/` | Cron 每日 15:30 / 手动"今日复盘" | 生成 AI 驱动的日终分析报告，推送给用户 | trade_events, position_snapshots, daily_analysis, delivery_runs, users |
| **Profit Taking** | `profit-taking/` | Cron 每日 09:00 / 手动"今日止盈" | 基于大盘状态、ATR/RSI/均线和历史回测生成止盈行动计划 | position_snapshots, profit_taking_plans, delivery_runs, user_sessions |
| **Heartbeat** | `heartbeat/` | Cron 每5分钟 | 巡检超时 job、重试失败 delivery、标记放弃记录 | job_runs, delivery_runs, task_definitions |

---

## 架构关系

```
用户微信消息
     │
     ├─→ [Trade Input Skill] ──→ trade_events ─┐
     │                                          │
     ├─→ [Broker Parse Skill] ──→ trade_events ─┤
     │                                          │
     │     [PostgreSQL Trigger] ◄───────────────┘
     │              │
     │              ▼
     │     [Position Aggregate Skill]
     │              │
     │              ▼
     │        position_snapshots
     │              │
     │              ▼
     │     [Daily Analysis Skill] ──→ OpenAI API
     │              │                        │
     │              ▼                        ▼
     │      daily_analysis ◄────── ai_analysis_text
     │              │
     │              ▼
     │      delivery_runs ──→ claw 插件推送 ──→ 用户微信
     │
     └─→ [手动触发：更新持仓 / 今日复盘]
```

---

## Gateway 中间件访问数据库

所有 Skill 不直接连接数据库，而是通过 **Gateway Data Access Middleware** 调用：

### 统一接口
```typescript
// Gateway Middleware 提供的 DataAccessClient
interface DataAccessClient {
  // 查询（SELECT）
  query(sql: string, params: any[]): Promise<QueryResult>;
  
  // 写入（INSERT / UPDATE / DELETE）
  execute(sql: string, params: any[]): Promise<ExecuteResult>;
  
  // 事务
  transaction<T>(fn: (tx: Transaction) => Promise<T>): Promise<T>;
  
  // 批量写入
  batchInsert(table: string, rows: any[]): Promise<InsertResult>;
}
```

### 访问控制
- **Row Level Security (RLS)**：所有查询自动附加 `user_id = current_user_id()`
- **字段级脱敏**：`broker_raw_message` 等敏感字段仅 Skill 内部可见
- **操作审计**：所有数据库操作记录到 `gateway_audit_logs`

### 调用方式
```javascript
// Skill 内调用示例（由 Gateway 注入 client）
async function execute(skillContext) {
  const { db, userId } = skillContext;
  
  const trades = await db.query(
    'SELECT * FROM trade_events WHERE user_id = $1 AND trade_date = $2',
    [userId, '2024-01-15']
  );
  
  // ... 业务逻辑
  
  await db.execute(
    'INSERT INTO daily_analysis (user_id, analysis_date, ...) VALUES ($1, $2, ...)',
    [userId, '2024-01-15', ...]
  );
}
```

---

## 开发新 Skill 的规范指南

### 1. 目录结构

```
skills/
└── {skill-name}/
    ├── SKILL.md          # 本 Skill 的完整定义文档（必须）
    ├── handler.js        # Skill 主逻辑入口（必须）
    ├── parser.js         # 输入解析逻辑（可选）
    ├── validator.js      # 输入校验逻辑（可选）
    ├── prompts/          # AI 提示词模板（可选）
    │   └── analysis.txt
    └── tests/
        ├── parser.test.js
        └── handler.test.js
```

### 2. SKILL.md 格式规范

每个 `SKILL.md` 必须包含以下章节：

```markdown
# Skill 名称

## 触发条件
- 触发关键词 / cron 表达式 / 事件监听
- 非触发条件（避免误触发）

## 输入格式
- 用户输入示例
- 参数结构定义
- 正则模式（如适用）

## 处理逻辑
- 步骤化流程
- 状态机（如适用）
- 算法说明

## 输出格式
- 用户可见消息格式
- 数据库写入字段结构
- 返回值定义

## 错误处理
- 错误场景表格（场景 → 处理方式）

## 示例
- 至少 3 个完整对话示例（成功 / 失败 / 边界）

## 数据库操作
- 表名：操作类型（SELECT/INSERT/UPDATE/DELETE）
```

### 3. Handler 签名规范

```javascript
/**
 * Skill 主处理函数
 * @param {Object} ctx - Skill 上下文
 * @param {DataAccessClient} ctx.db - 数据库客户端
 * @param {string} ctx.userId - 当前用户 ID
 * @param {Object} ctx.userProfile - 用户配置
 * @param {string} ctx.rawMessage - 原始用户消息
 * @param {Object} ctx.metadata - 额外元数据（消息类型、时间戳等）
 * @returns {Promise<SkillResult>}
 */
async function handler(ctx) {
  // 1. 输入解析
  // 2. 校验与确认
  // 3. 业务逻辑
  // 4. 数据库操作
  // 5. 返回结果
}

// 返回值结构
interface SkillResult {
  type: 'message' | 'action' | 'confirm_required' | 'error';
  content: string;           // 用户可见消息
  data?: any;                // 附加数据（供 Gateway 使用）
  nextState?: string;        // 对话状态机下一状态
  actions?: Action[];        // 待执行动作（如推送、定时任务）
}
```

### 4. 数据库操作规范

- **必须**使用参数化查询（`$1, $2`），禁止字符串拼接 SQL
- **INSERT** 操作需处理 `ON CONFLICT`（幂等性）
- **UPDATE** 操作需带 `WHERE` 条件，避免全表更新
- **批量操作**使用 `batchInsert`，单批次不超过 500 条
- **敏感操作**（删除数据）需记录到 `gateway_audit_logs`

### 5. 错误处理规范

```javascript
try {
  // 业务逻辑
} catch (error) {
  // 1. 记录到 job_runs 或 gateway_error_logs
  await ctx.db.execute(
    'INSERT INTO gateway_error_logs (skill_name, error, context) VALUES ($1, $2, $3)',
    ['skill-name', error.message, JSON.stringify(ctx.metadata)]
  );
  
  // 2. 分类返回友好消息
  if (error.code === '23505') {  // unique_violation
    return { type: 'error', content: '该记录已存在，请勿重复操作。' };
  }
  if (error.code === 'P0001') {  // RLS 拒绝
    return { type: 'error', content: '权限不足，请联系管理员。' };
  }
  
  // 3. 未知错误脱敏
  return { type: 'error', content: '操作失败，请稍后重试。' };
}
```

### 6. AI 调用规范

- **配额检查**：调用前检查 `users.daily_ai_calls > 0`
- **模型选择**：默认 `gpt-5-mini`，高价值分析可申请升级
- **超时控制**：API 调用设置 30 秒超时，2 次重试
- **Token 限制**：输入 + 输出不超过模型上下文上限
- **结果缓存**：相同输入 24 小时内缓存结果

### 7. 测试要求

每个 Skill 必须包含：
- **单元测试**：parser / validator 覆盖率 > 80%
- **集成测试**：与 Gateway Middleware 的 mock 交互
- **样本测试**：至少 10 条真实输入样本的端到端测试

---

## Skill 开发检查清单

在提交新 Skill 前，确认以下事项：

- [ ] `SKILL.md` 包含全部 7 个必需章节
- [ ] `handler.js` 遵循标准函数签名
- [ ] 所有数据库操作使用参数化查询
- [ ] 错误场景全部覆盖并有友好提示
- [ ] 示例对话包含成功、失败、边界三种情况
- [ ] 无硬编码敏感信息（API Key、密码）
- [ ] 已通过单元测试和集成测试
- [ ] 更新了本 `README.md` 的 Skill 清单

---

## 版本历史

| 版本 | 日期 | 变更 |
|------|------|------|
| 1.2.0 | 2024-01-15 | Phase 1 Sprint 1.2 初始版本，4 个核心 Skill 定义完成 |
