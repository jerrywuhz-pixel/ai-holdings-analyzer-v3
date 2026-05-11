# AI 持仓投资分析系统 2.0

Agent 驱动的多用户股票持仓分析与复盘平台。

## 架构概览

- **Agent 层**: OpenClaw Gateway + 持仓分析 Agent + Hermes 机会猎手子 Agent
- **数据层**: Supabase PostgreSQL (RLS 隔离) + Upstash Redis 缓存
- **展示层**: Next.js 14 App Router + Tailwind (只读 WebApp)
- **数据源**: Python FastAPI 服务，支持 Yahoo Finance / Tushare / AkShare 多源适配
- **交互通道**: 微信 clawbot (主入口) + WebApp (只读展示)

## 项目结构

```
.
├── supabase/          # 数据库 Schema、迁移、Edge Functions
├── data-service/      # Python FastAPI 数据源服务
├── webapp/            # Next.js 14 只读展示层
├── openclaw/          # OpenClaw Gateway 配置与 Skills
├── scripts/           # 部署与运维脚本
└── docs/              # 项目文档
```

## 快速开始

见 docs/ 目录下的部署文档。
