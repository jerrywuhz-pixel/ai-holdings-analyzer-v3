# AI 持仓系统 3.0 PRD 索引

## 输出方式

本目录用于把前期产品架构设计收敛成可执行 PRD。当前按三条主线并行产出：

| 文件 | 范围 | 状态 |
| --- | --- | --- |
| `01-holdings-core-prd.md` | 持仓核心产品：Dashboard、持仓工作台、股票/ETF 详情、Sell Put 工作台、确认中心联动 | completed |
| `02-data-broker-reconciliation-prd.md` | 数据源、富途同步、腾讯财经校验、多来源资产、对账和冲突处理 | completed |
| `03-interaction-confirmation-agent-prd.md` | WebApp/微信交互、确认中心、页面内 AI、OpenClaw/Hermes handoff、错误降级和推送 | completed |

## 已确认决策

1. WebApp 不需要全局聊天入口，AI 入口嵌入具体页面上下文。
2. Auth 首期沿用 Supabase Auth。
3. 付费/配额不进入 P0。
4. P0 支持多个 `portfolio_view`。
5. Futu 是美港股、ETF、期权链和券商账户数据主源。
6. 腾讯财经作为稳定校验源和 fallback，不作为交易级唯一依据。
7. P0 不做自动下单，只生成草稿、确认记录和人工执行清单。
8. 微信不做绑定、券商授权或账号切换，这些只在 WebApp/后台完成。

## PRD 完成后的下一步

三份 PRD 已完成，系统分析阶段也已输出到 `../system-analysis/`：

1. `../system-analysis/01-holdings-core-system-analysis.md`
2. `../system-analysis/02-data-broker-reconciliation-system-analysis.md`
3. `../system-analysis/03-interaction-confirmation-agent-system-analysis.md`
4. `../system-analysis/04-architecture-integration-and-coding-entry.md`

编码前应先 review `04-architecture-integration-and-coding-entry.md` 中的共享契约、任务切分和建议确认项。

## 最新实现对齐（2026-05-20）

三份 PRD 的 P0 范围已进入实现和第一阶段部署验证：

1. 持仓核心：Dashboard、持仓工作台、Sell Put、确认中心、数据页和设置页已具备 P0 WebApp 展示能力，且用户可见文案已去除内部工程术语。
2. 数据/券商/对账：Futu 继续按用户本地 connector + read-only 上传脱敏快照设计；阿里云服务器不直接连接用户本地 OpenD。
3. 交互/确认/Agent：MiniMax M2.7 已作为日常文本/意图 live route；GPT-5.5 深研 route 已有 OpenAI API key / `openai-codex` bridge 契约，但当前服务器尚未启用 deep auth。
4. 部署验收：第一阶段使用 `production_readiness.py --profile lightweight`；正式生产切流仍必须通过 `--profile production`。

## 一致性检查

三份 PRD 已对齐以下边界：

1. Dashboard 只展示数据 freshness，不把富途同步作为主操作。
2. 高注意力动作统一进入确认中心。
3. 确认不等于自动下单授权。
4. 页面内 AI 必须绑定页面上下文，不做 WebApp 全局聊天。
5. Futu 是 P0 主源；腾讯财经是校验和 fallback。
6. 数据过期、对账失败、关键字段缺失时必须降级，不输出可执行交易建议。
