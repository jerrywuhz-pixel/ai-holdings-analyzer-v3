# AI 持仓系统 3.0 云部署费用对比

> 对比对象：阿里云、Google Cloud Run 体系、Vercel + Supabase。  
> 估算口径：P0 正式生产版，小规模真实用户，包含 WebApp、OpenClaw Gateway、Data Service、Hermes Worker、PostgreSQL、对象存储、缓存、定时任务、日志监控。  
> 不含：MiniMax/OpenAI token、付费行情源、可信 FX API、短信邮件、域名备案、人工运维。

## 1. 总结

| 方案 | 月费用估算 | 国内访问 | 运维复杂度 | 适配本系统 | 结论 |
| --- | ---: | --- | --- | --- | --- |
| 阿里云 SAE + RDS + OSS | ¥1,800-3,500 | 好 | 中 | 高 | 国内生产首选 |
| Google Cloud Run + Cloud SQL | ¥1,800-4,000 | 一般/偏弱 | 中 | 高 | 海外/香港用户可选，不适合作为国内主路径 |
| Vercel + Supabase | ¥400-1,500 起；生产增强约 ¥1,500-3,000 | 一般/不稳定 | 低 | 中 | 原型和海外轻量生产很香，但国内真实持仓生产不建议全依赖 |

我的建议：

1. **国内主路径：阿里云。**
2. **海外/快速 Demo：Vercel + Supabase。**
3. **Google Cloud：保留为备选，不作为国内默认。**

## 2. 阿里云费用

P0 正式生产推荐：

| 资源 | 配置 | 月费用估算 |
| --- | --- | ---: |
| SAE | WebApp / Gateway / Data Service / Worker | ¥700-1,500 |
| RDS PostgreSQL | 高可用 2c4g / ESSD 100GB | ¥350-900 |
| Tair / Redis | 1-2GB | ¥120-300 |
| OSS | 100-500GB，历史行情和 artifact | ¥100-400 |
| SLS / ARMS / CloudMonitor | 日志、APM、告警 | ¥200-800 |
| ALB / WAF / CDN / DNS | 公网入口和安全 | ¥300-1,000 |
| KMS / EventBridge / ACR | 密钥、cron、镜像 | ¥50-300 |

合计：**¥1,800-3,500/月**。

优点：

- 国内访问、微信链路、备案和合规路径更顺。
- OSS、RDS、SAE、SLS、ARMS 都在同一云内，数据链路简单。
- 适合未来接国内消息渠道、企业微信、钉钉、飞书。

缺点：

- 价格不一定最低。
- 需要新增 OSS/KMS/SAE/ACR 部署脚本。

## 3. Google Cloud Run 费用

P0 正式生产推荐：

| 资源 | 对应服务 | 月费用估算 |
| --- | --- | ---: |
| 容器计算 | Cloud Run | ¥400-1,200 |
| 数据库 | Cloud SQL PostgreSQL | ¥600-1,600 |
| Redis | Memorystore | ¥300-800 |
| 对象存储 | Cloud Storage | ¥50-300 |
| 调度 | Cloud Scheduler | 很低，通常几十元内 |
| 日志监控 | Cloud Logging / Monitoring | ¥100-600 |
| 入口安全 | Load Balancer / CDN / Armor | ¥300-1,000 |

合计：**¥1,800-4,000/月**。

优点：

- Cloud Run 对容器和自动伸缩很友好。
- 工具链成熟，部署脚本我们已经有一版雏形。
- 海外访问体验通常好。

缺点：

- 国内访问不稳定，微信用户体验和 API latency 风险较大。
- Google Cloud 没有中国大陆通用 Region。
- 数据、对象存储、日志和模型调用都可能走跨境链路。

判断：费用和阿里云差不多，不是主要差距；**主要输在国内网络和合规路径**。

## 4. Vercel + Supabase 费用

### 4.1 轻量版

| 资源 | 配置 | 月费用估算 |
| --- | --- | ---: |
| Vercel | Pro 1 seat | $20，约 ¥145 |
| Supabase | Pro | $25，约 ¥180 |
| Supabase compute | Micro/Small | $0-15，约 ¥0-110 |
| Supabase Storage | Pro 内含一定额度，超量另计 | ¥0-200 |
| Observability / Log Drain | 可选 | ¥0-500 |

合计：**¥400-1,500/月**。

### 4.2 生产增强版

如果需要更接近真实金融系统的稳定性：

- Supabase compute 升到 Medium/Large。
- 开启 PITR。
- 增加日志导出/监控。
- Worker / Python services 另找容器平台托管。

估算：**¥1,500-3,000/月**，如果长任务 worker 单独上云还会再增加。

优点：

- 上手最快。
- WebApp/Next.js 部署体验最好。
- Supabase Auth、Postgres、Storage、Realtime 一体化，原型阶段效率很高。
- 小流量时最便宜。

缺点：

- 国内访问不稳定，Supabase/Vercel 对微信渠道不是最稳。
- Python `data-service`、OpenClaw Gateway、Hermes Worker 不适合全部塞进 Vercel。
- 金融持仓系统的日志、审计、回放、对象存储、长任务 worker，后期会突破 Vercel/Supabase 的舒适区。
- 国内备案、域名、安全策略和企业级告警不如阿里云顺。

判断：适合 **Demo / 海外用户 / 内部原型**。如果面向国内微信用户和真实持仓，建议只把 Vercel 作为前端备选，不作为全栈生产默认。

## 5. 同配置结论

| 维度 | 阿里云 | Google Cloud | Vercel + Supabase |
| --- | --- | --- | --- |
| 初期费用 | 中 | 中 | 低 |
| 国内访问 | 强 | 弱 | 中弱 |
| 长任务 worker | 强 | 强 | 弱 |
| 对象存储/历史行情 | 强 | 强 | 中 |
| 数据库生产能力 | 强 | 强 | 中强 |
| 微信渠道稳定性 | 强 | 弱 | 中弱 |
| 运维复杂度 | 中 | 中 | 低 |
| 未来 10 万级扩展 | 强 | 强 | 中 |
| 国内合规/备案 | 强 | 弱 | 弱 |

## 6. 推荐路线

如果目标是：

- 面向国内用户
- 微信/OpenClaw 是核心交互
- 真实持仓和历史行情要长期沉淀
- 后续可能付费和扩展多用户

推荐：

```text
阿里云 SAE + RDS PostgreSQL + OSS + Tair/Redis + EventBridge + SLS/ARMS
```

如果目标是：

- 快速上线 Demo
- 成本最低
- 暂时不追求国内访问稳定
- 用户主要是自己或海外

可以选：

```text
Vercel + Supabase
```

Google Cloud 的性价比并没有明显超过阿里云；在国内场景下，除非有现成 GCP 团队和海外用户，否则不建议作为默认路线。

## 7. 价格依据

- 阿里云 SAE：按 CPU、内存、请求、公网出口转 CU 计费；中国内地第一档 CU 单价约 `0.00005144 元/CU`。
- 阿里云 OSS：标准、本地冗余、低频、归档等按 GB/月、请求和流量计费。
- Google Cloud Run：按 vCPU-second、GiB-second、请求、出网等计费，Cloud SQL、Artifact Registry、Eventarc 等另计。
- Google Cloud Scheduler：按 job 计费，少量 cron 成本很低。
- Vercel Pro：`$20/月`，包含 `$20` 用量额度；Pro 包含更高的 Edge Requests 和 Fast Data Transfer 额度。
- Supabase Pro：`$25/月` 起，包含 100k MAU、8GB disk、100GB file storage、250GB egress、7 日备份；更大 compute、PITR、Log Drains 另计。
