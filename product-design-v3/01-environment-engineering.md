# Environment Engineering 设计原则

## 核心理解

Aymen Furter 的文章把 agent 设计分为三层：

| 层 | 本系统中的含义 |
| --- | --- |
| Prompt Engineering | 每个 agent 的角色、话术、输出格式、风险提示 |
| Context Engineering | 给 agent 动态装配持仓、行情、交易历史、memory、工具结果 |
| Environment Engineering | 设计 agent 可见、可做、可调用、可失败、可追踪、可审批的完整运行环境 |

对 AI 持仓系统来说，最重要的不是“让 agent 更聪明”，而是让每个 agent 进入一个**租户级、任务级、权限级明确的环境**。这里的租户级环境继承当前 `routing.json.tenantId`，也就是持仓 3.0 的系统账号。agent 不应该靠猜测知道自己是谁、服务哪个账户、能不能读券商数据、能不能推送、能不能下单。

## 3.0 的环境工程原则

| 原则 | 设计落点 |
| --- | --- |
| 租户级环境 | 每次 agent run 必须绑定持仓系统 `tenant_id`；涉及微信交互时绑定 `channel_binding_id` 和 `openclaw_account_id`，涉及券商数据时绑定 `asset_source_id`/`broker_connection_id` |
| 工具最小化 | 日常对话只开放只读查询和解释工具；研究 agent 开放行情、新闻、财报、期权链；交易账号工具默认只读 |
| 资源先于工具 | 持仓、交易流水、行情快照、券商同步状态作为 read-only resources 注入，而不是让 agent 自己扫全库 |
| 可执行动作显式化 | 推送、写入 memory、写入交易事件、同步券商、创建止盈计划都必须有明确 tool schema、审计和幂等键 |
| 高风险人审 | 下单、删除、跨账号迁移、券商授权、期权策略建议升级为“执行建议”前必须有确认 |
| 反馈可行动 | 工具错误返回结构化错误：错误类型、可重试性、数据新鲜度、fallback 来源、下一步建议 |
| 全链路观测 | 每次消息、工具调用、模型调用、数据源 fallback、推送状态都进入 trace 和审计 |

## 微环境划分

3.0 不建议一个“大 agent”拥有所有工具，而是按任务创建微环境。

| 微环境 | 默认模型 | 可见数据 | 可用工具 | 不允许 |
| --- | --- | --- | --- | --- |
| 日常对话环境 | MiniMax M2.7 | 当前系统账号摘要、统一资产视图、用户偏好 memory | 问答、只读查询、轻量解释 | 调用券商生产写接口、跨账号读 memory |
| 交易录入环境 | MiniMax M2.7 或小模型 + 规则 | 当前账号、symbol registry、最近交易、数据来源 | 解析、校验、写 `trade_events`、触发聚合 | 直接改历史成交，除非确认 |
| 持仓分析环境 | GPT-5.5 或强推理模型 | 当前账号持仓、行情、成本、策略标签 | 组合分析、风险归因、止盈止损计划 | 访问其他账号、执行交易 |
| 深度研究环境 | GPT-5.5 | 市场数据、财报、新闻、研报摘要、用户 watchlist | web/data research、生成研究报告 | 写持仓真相源、私自推送高频消息 |
| 期权 sell put 环境 | GPT-5.5 + deterministic calculators | 期权链、Greeks、IV、现金/保证金、标的基本面 | strike 筛选、情景压力、assignment 预案 | 忽略流动性和现金约束给出建议 |
| Cron 推送环境 | 规则引擎 + 小模型摘要 | account schedule、channel binding、消息模板、outbox | 任务执行、重试、补偿、状态更新 | 临时猜测目标会话 |
| Memory 整理环境 | 小模型或批处理 | 当前账号对话、确认过的事实、交易复盘 | 提炼 memory、去重、过期 | 将 A 账号偏好写入 B 账号 |
| Ops 环境 | 规则 + 管理员模型 | 系统健康、任务队列、失败投递 | 诊断、重试、告警 | 查看用户敏感持仓明细，除非授权 |

## Agent Run Contract

每个 agent run 都需要一个环境合约：

```json
{
  "run_id": "uuid",
  "tenant_id": "routing.tenantId",
  "channel_binding_id": "uuid",
  "openclaw_account_id": "routing.accountId",
  "session_space": "routing.sessionSpace",
  "asset_source_id": "uuid|null",
  "environment_type": "daily_chat | research | option_sell_put | cron_delivery",
  "model_policy": {
    "primary": "minimax-m2.7",
    "escalate_to": "gpt-5.5",
    "escalation_reason_required": true
  },
  "tool_policy": {
    "read_resources": ["positions", "quotes", "memory_summary"],
    "write_tools": ["delivery_outbox.create"],
    "forbidden_tools": ["broker.trade.place_order"]
  },
  "data_policy": {
    "max_staleness_seconds": 900,
    "allow_stale_with_label": true,
    "require_source_citation": true
  },
  "approval_policy": {
    "requires_user_confirmation": ["broker_auth", "trade_execution", "delete_memory"]
  }
}
```

## 与最新成果的关系

- MCP 的核心价值不是“多接工具”，而是把 tools、resources、prompts 变成可发现、可约束、可复用的协议层。本系统应把行情、持仓、期权链、券商只读查询做成 MCP-style resources/tools，而不是让 agent 直连数据库。
- A2A 的价值在于跨框架 agent 通信。3.0 可以先内部 HTTP/RPC，保留 A2A adapter 作为后续扩展，使 OpenClaw、Hermes、LangGraph、ADK agent 都能以同一任务协议协作。
- LangGraph 的 checkpoint/persistence 思路适合长流程研究、人工审批、失败恢复。即使不采用 LangGraph，也要把“可恢复状态”设计进 `agent_runs`、`agent_steps`、`tool_calls`。
- OpenTelemetry GenAI semantic conventions 应成为可观测性命名参考，避免每个 agent 自己发散记录日志字段。

## 设计约束

1. **持仓真相源必须在数据库，不在 agent memory。**
2. **memory 是解释和偏好，不是交易凭证。**
3. **每个推送都必须可追溯到账号、任务、数据快照、模型版本和 channel binding。**
4. **所有投资建议都要标明数据时点、置信度、依据和不可用数据。**
5. **期权模块必须把风险计算放在确定性工具里，模型只负责解释、筛选和生成报告。**
6. **任何后台写入都必须带来源。** 手工录入、微信买卖消息、OCR、券商 API 同步和系统派生结果都要写入 `source_type`、`source_ref`、`ingestion_run_id` 或等价字段。

## 参考

- [Environment Engineering: Platform Engineering for AI Agents](https://aymenfurter.ch/articles/environment-engineering-platform-engineering-for-ai-agents/)
- [Model Context Protocol architecture](https://modelcontextprotocol.io/docs/learn/architecture)
- [A2A Protocol](https://github.com/a2aproject/A2A)
- [LangGraph persistence](https://docs.langchain.com/oss/python/langgraph/persistence)
- [OpenTelemetry GenAI semantic conventions](https://opentelemetry.io/docs/specs/semconv/gen-ai/)
