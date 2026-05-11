# AI 持仓系统 3.0 系统分析索引

## 输出方式

本目录用于在 PRD 完成后，进入编码前的系统分析阶段。系统分析只定义模块边界、接口契约、数据流、状态机、失败处理和测试策略，不进入编码。

| 文件 | 范围 | 状态 |
| --- | --- | --- |
| `01-holdings-core-system-analysis.md` | 持仓核心产品系统分析：持仓 read models、WebApp/BFF、Domain Tools、股票/ETF 与 Sell Put 页面 | completed |
| `02-data-broker-reconciliation-system-analysis.md` | 数据源、富途同步、broker snapshot、freshness、对账与冲突处理系统分析 | completed |
| `03-interaction-confirmation-agent-system-analysis.md` | 交互、确认中心、OpenClaw/Hermes handoff、Environment Orchestrator、降级和推送系统分析 | completed |
| `04-architecture-integration-and-coding-entry.md` | 三份 PRD 与三份系统分析的架构整合、共享契约、编码任务切分和编码前确认结果 | completed |

## 编码前门槛

1. 三份 PRD 已 completed。
2. 三份系统分析完成并相互对齐。
3. 开发前确认 gate 已完成：A 类全部确认、B 类全部确认、C 类全部延后。
4. 形成编码任务切分、接口契约、测试策略和迁移顺序。

## 对齐结论

1. `tenant_id` 是 3.0 账号与数据隔离根；微信绑定后才有 `channel_binding_id` 和 `openclaw_account_id`。
2. Futu 是 P0 主源，Tencent Finance 是校验/fallback；主源异常时必须降低 `actionability_cap`。
3. 股票/ETF 与期权独立建模；Sell Put 可以生成草稿，但必须经过 RiskReview、Degradation 和 Confirmation。
4. WebApp 不做全局聊天，微信不做绑定/授权/账号切换。
5. Environment Orchestrator 统一签发 run contract，下游只能继承或收窄权限。
