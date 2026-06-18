# AI 持仓投资分析系统 3.0

Hermes 驱动的多用户股票/期权持仓分析、微信消息交互与本地券商只读同步平台。

## 架构概览

- **Agent 层**: Hermes Runtime + 持仓分析 Agent + Hermes 机会猎手子 Agent
- **数据层**: Supabase-compatible PostgreSQL / 本地 Postgres + Redis + 对象存储
- **展示层**: Next.js App Router + Tailwind WebApp，支持注册、初始化、持仓与期权分析
- **数据源**: Python FastAPI 服务，支持 Yahoo Finance / Tushare / AkShare / Futu 本地 connector
- **交互通道**: Hermes 微信入口 + WebApp；P0 坚持 read-only / confirmation-first / 不自动下单

### 运行时边界（硬约束）

- 本仓库在轻量化服务器上的唯一运行时是 **Hermes**（data-service + GBrain + webapp）。
- 新部署不启动 OpenClaw 服务；微信入口、domain tools、消息路由与验收全部挂在 Hermes 体系内。
- 所有“可用性验证”和“上线验收”都按 Hermes 主体能力核验。

## 项目结构

```
.
├── supabase/          # 数据库 Schema、迁移、Edge Functions
├── data-service/      # Python FastAPI 数据源服务
├── webapp/            # Next.js 14 只读展示层
├── skills/            # Hermes 使用的 Skills / 参考工具资产
├── local_connectors/  # 用户本地 Futu OpenD 与 OpenAI/Codex bridge connector
├── product-design-v3/ # 3.0 产品、架构、部署和 readiness 文档
├── scripts/           # 部署与运维脚本
└── docs/              # 项目文档
```

## 快速开始

轻量服务器第一阶段部署见 `docs/LIGHTWEIGHT_SERVER_DEPLOY.md`；产品依赖和云端切流前检查见 `product-design-v3/36-product-feature-readiness-checklist.md` 与 `product-design-v3/37-production-dependency-config-package.md`。
