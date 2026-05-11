# 用户注册与配对流程

> AI 持仓投资分析系统 2.0 - OpenClaw Agent 文档
> Phase 1 Sprint 1.3: 用户与会话管理

---

## 概述

系统支持三种用户注册/配对路径，覆盖 WebApp 邮箱用户、微信生态用户以及跨平台绑定场景。所有路径最终都在 `public.users` 表中产生统一的租户记录（`tenant_id`），作为持仓、交易、分析的唯一身份标识。

---

## 流程1：Supabase Auth 注册（WebApp 邮箱注册）

### 时序

```
用户填写邮箱+密码 → Supabase Auth 创建用户 → Trigger: on_auth_user_created
  → 自动插入 public.users (status='NEW', plan='free')
  → 用户登录 WebApp → 可录入交易 / 查看持仓分析
```

### 说明

1. 用户在前端 WebApp 调用 `supabase.auth.signUp({ email, password })`。
2. Supabase Auth 在 `auth.users` 中创建记录。
3. 数据库触发器 `on_auth_user_created` 自动在 `public.users` 中插入对应记录：
   - `id` = `auth.users.id`
   - `email` = 注册邮箱
   - `status` = `'NEW'`
   - `plan` = `'free'`
   - `role` = `'user'`（默认）
4. 用户通过邮箱验证后，即可登录 WebApp 使用核心功能。
5. 该用户后续可通过「流程2」绑定微信，实现微信端接收持仓日报。

### 约束

- `public.users.id` 是 `auth.users.id` 的外键，且为 PRIMARY KEY，因此必须先有 Auth 记录。
- `public.users` 的 CHECK 约束要求 `email IS NOT NULL OR wechat_openid IS NOT NULL`，邮箱注册场景天然满足。

---

## 流程2：微信 OpenClaw Pairing（已有邮箱用户绑定微信）

### 时序

```
用户在微信发送 "配对" → OpenClaw Agent 生成 pairing_code（6位数字）
  → 返回给用户，并提示在 WebApp 输入
  → 用户在 WebApp「账号绑定」页输入 pairing_code
  → WebApp 调用 Edge Function / API 验证并绑定
  → 更新 public.users:
       openclaw_pairing_code = NULL,
       wechat_openid         = <openid>
  → 绑定完成，微信与 WebApp 数据互通
```

### Agent 指令（OpenClaw）

当用户消息匹配「配对|绑定|关联|link」意图时：

1. 调用后端 API `POST /pairing/generate`（携带当前微信 `openid`）。
2. 后端生成唯一 `pairing_code`（6 位随机数字，有效期 10 分钟），写入 `public.users.openclaw_pairing_code`。
3. Agent 向用户回复：
   > "您的配对码是 **123456**，请在 WebApp「账号绑定」页面输入该码完成绑定。配对码 10 分钟内有效。"
4. 用户在 WebApp 输入 pairing_code 后，后端校验：
   - 如果存在且未过期，将 `wechat_openid` 写入对应 `public.users` 记录，并清空 `pairing_code`。
   - 返回绑定成功。
5. 绑定后，微信端的 `conversation_id` 与 `tenant_id` 关联，后续持仓日报可直接推送至该微信对话。

### 幂等性

- 同一微信 `openid` 只能绑定到一个 `public.users` 记录（`wechat_openid` 有 UNIQUE 约束）。
- 若用户重复发送「配对」，生成新的 `pairing_code` 覆盖旧值即可。

---

## 流程3：直接微信注册（无邮箱用户）

### 时序

```
用户首次在微信与 Agent 交互
  → Agent 检测到 wechat_openid 无对应 public.users 记录
  → Agent 引导用户完成简单注册（仅需昵称）
  → 后端通过 Supabase Auth Admin API 创建匿名/临时 Auth 用户
  → Trigger 自动创建 public.users（email=NULL, wechat_openid=<openid>）
  → 更新 nickname → 注册完成，用户可立即录入交易
  → 后续用户可随时通过「流程2反向操作」或 WebApp 绑定邮箱
```

### Agent 指令（OpenClaw）

1. **首次识别**：每次收到微信消息，先调用 `GET /users/by-wechat?openid=XXX` 查询是否已有绑定用户。
2. **未注册引导**：
   - 若未找到记录，Agent 回复：
     > "您好！我是您的 AI 持仓助手。为了帮您记录交易和分析持仓，我需要先为您创建账号。请回复您的昵称（例如：小明）："
   - 用户回复昵称后，Agent 调用 `POST /users/wechat-register`：
     ```json
     {
       "wechat_openid": "xxx",
       "wechat_nickname": "小明",
       "conversation_id": "yyy"
     }
     ```
3. **后端处理**：
   - 使用 `service_role` 调用 Supabase Auth Admin API 创建新用户（`email` 留空或生成占位符）。
   - `on_auth_user_created` 触发器自动创建 `public.users` 记录。
   - 后端再执行 `UPDATE public.users SET wechat_openid = ..., wechat_nickname = ..., status = 'NEW' WHERE id = <auth_user_id>`。
4. **注册完成**：
   - Agent 回复：
     > "欢迎小明！您已注册成功。您可以：
     > 1. 直接发送交易记录（如：买入 100 股腾讯 0700.HK @ 380.5）
     > 2. 发送「持仓」查看当前分析
     > 3. 访问 https://app.example.com 绑定邮箱，解锁 WebApp 全部功能"

### 后续邮箱绑定

- 用户访问 WebApp → 点击「已有微信账号？用邮箱解锁」→ 输入邮箱 + 设置密码。
- 后端调用 Auth Admin API 为该 `auth.users` 记录更新 `email` 和 `encrypted_password`。
- 用户验证邮箱后即可用邮箱登录 WebApp，所有历史交易和持仓数据自动同步。

---

## 状态流转

```
                    ┌─────────────────────────────┐
                    │ 首次完成交易录入 / 人工审核   │
                    ▼                             │
┌────────┐     ┌─────────┐     ┌───────────┐     │
│  NEW   │────▶│ ACTIVE  │────▶│ SUSPENDED │─────┘
└────────┘     └─────────┘     └───────────┘
   │               ▲                  ▲
   │               │                  │
   │         恢复缴费/申诉通过       欠费 / 违规
   │               │                  │
   └───────────────┘                  │
         重新激活（admin 操作）────────┘
```

| 状态 | 说明 | 可执行操作 |
|------|------|-----------|
| `NEW` | 刚注册，尚未产生任何交易数据 | 录入交易、查看演示数据、绑定微信 |
| `ACTIVE` | 正常活跃用户 | 全部功能（录入、分析、接收日报） |
| `SUSPENDED` | 欠费、违规或主动暂停 | 只读查看历史数据，不可录入新交易；Agent 提示充值/申诉 |
| `DELETED` | 用户注销（软删除） | 无，数据保留 90 天后清理 |

### 状态变更触发条件

- `NEW` → `ACTIVE`：
  - 用户首次成功录入一笔交易（`trade_events` 产生记录）。
  - 或由 Admin 后台手动激活。
- `ACTIVE` → `SUSPENDED`：
  - 订阅到期且宽限期结束（Billing 系统调用）。
  - 检测到违规操作（如恶意刷 API）。
- `SUSPENDED` → `ACTIVE`：
  - 用户续费成功。
  - Admin 人工解封。

---

## 数据模型关联

```
auth.users (Supabase Auth)
    │ id (PK)
    ▼
public.users (业务用户表)
    │ id (PK, FK → auth.users.id)
    │ email
    │ wechat_openid (UNIQUE)
    │ openclaw_pairing_code
    │ status, plan, role
    ▼
public.user_sessions (会话表)
    │ tenant_id (FK → public.users.id)
    │ context_token (OpenClaw)
    │ conversation_id (微信对话 ID)
```

---

## 安全与合规

- `public.users` 的 RLS 策略确保用户只能读写自己的记录（`id = auth.uid()`）。
- `service_role` 拥有全部权限，供后端 Edge Function / OpenClaw Agent 在需要时绕过 RLS 进行跨用户操作（如 Admin 审核）。
- `wechat_openid` 属于敏感信息，禁止在前端直接暴露；所有微信相关查询必须通过后端 API 代理。
- `pairing_code` 必须设置 TTL（如 Redis 10 分钟过期或数据库字段 `pairing_code_expires_at`），防止暴力破解。
