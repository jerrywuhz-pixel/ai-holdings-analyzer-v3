# AI 持仓投资分析系统 3.0

Agent 驱动的多用户股票/期权持仓分析、微信 ClawBot 交互与本地券商只读同步平台。

## 架构概览

- **Agent 层**: OpenClaw Gateway + 持仓分析 Agent + Hermes 机会猎手子 Agent
- **数据层**: Supabase-compatible PostgreSQL / 本地 Postgres + Redis + 对象存储
- **展示层**: Next.js App Router + Tailwind WebApp，支持注册、初始化、持仓与期权分析
- **数据源**: Python FastAPI 服务，支持 Yahoo Finance / Tushare / AkShare / Futu 本地 connector
- **交互通道**: 微信 ClawBot + WebApp；P0 坚持 read-only / confirmation-first / 不自动下单

## 项目结构

```
.
├── supabase/          # 数据库 Schema、迁移、Edge Functions
├── data-service/      # Python FastAPI 数据源服务
├── webapp/            # Next.js 14 只读展示层
├── openclaw/          # OpenClaw Gateway 配置与 Skills
├── local_connectors/  # 用户本地 Futu OpenD 与 OpenAI/Codex bridge connector
├── product-design-v3/ # 3.0 产品、架构、部署和 readiness 文档
├── scripts/           # 部署与运维脚本
└── docs/              # 项目文档
```

## 快速开始

轻量服务器第一阶段部署见 `docs/LIGHTWEIGHT_SERVER_DEPLOY.md`；产品依赖和云端切流前检查见 `product-design-v3/36-product-feature-readiness-checklist.md` 与 `product-design-v3/37-production-dependency-config-package.md`。
