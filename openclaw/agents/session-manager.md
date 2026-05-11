# 会话管理（Session Management）

> AI 持仓投资分析系统 2.0 - OpenClaw Agent 文档
> Phase 1 Sprint 1.3: 用户与会话管理

---

## 概述

OpenClaw 与微信生态的交互依赖 `contextToken` 来维持有状态对话。`public.user_sessions` 表作为 `contextToken` 的持久化存储，确保：

1. Agent 重启或 Token 过期后，仍能恢复与同一微信用户的对话上下文。
2. 多设备（Web + 微信 + Telegram）可同时在线，各自维护独立的会话通道。
3. 长期未活跃的会话可被清理，降低安全和存储风险。

---

## contextToken 的生命周期

### 1. 生成

- 当用户首次通过微信与 OpenClaw Agent 交互时，OpenClaw 平台返回一个 `contextToken`。
- 后端立即将该 Token 持久化到 `public.user_sessions`：
  ```sql
  INSERT INTO public.user_sessions (
    tenant_id, session_type, context_token, conversation_id, device_info, ip_address, is_active
  ) VALUES (
    '<user_id>', 'wechat_claw', '<token>', '<conversation_id>', '<device_info>', '<ip>', TRUE
  );
  ```

### 2. 使用

- 每次向 OpenClaw 发送消息时，必须在 HTTP Header 或请求体中携带当前有效的 `contextToken`。
- 后端从 `user_sessions` 读取该用户的活跃 Token，用于构建 OpenClaw API 请求。

### 3. 刷新

- `contextToken` 本身由 OpenClaw 平台管理有效期（通常 24h ~ 7d，以平台文档为准）。
- 每次成功交互后，Agent 应更新 `last_active_at`：
  ```sql
  UPDATE public.user_sessions
  SET last_active_at = now()
  WHERE id = '<session_id>';
  ```
- 如果 OpenClaw 响应中携带了新的 `contextToken`（平台刷新策略），后端应同步更新数据库：
  ```sql
  UPDATE public.user_sessions
  SET context_token = '<new_token>', last_active_at = now(), updated_at = now()
  WHERE id = '<session_id>';
  ```

### 4. 失效

- **自然过期**：OpenClaw 返回 Token 过期错误（如 HTTP 401 / `token_expired`）。
- **主动注销**：用户在 WebApp 点击「退出登录」或微信发送「退出」。
- **安全风控**：检测到异常 IP、设备变更或用户状态变为 `SUSPENDED`。

失效后应将 `is_active` 置为 `FALSE`，但不立即删除记录，保留用于审计和故障排查：
```sql
UPDATE public.user_sessions
SET is_active = FALSE, updated_at = now()
WHERE id = '<session_id>';
```

---

## 每次交互更新 `last_active_at`

### 机制

所有经过 OpenClaw Agent 的消息（无论是用户主动发送、Broker 推送、还是定时日报触发）都视为一次「交互」。

在消息处理管道的入口层，统一执行：

```typescript
// Edge Function / API 层伪代码
async function onMessage(tenantId: string, conversationId: string) {
  // 1. 更新会话活跃时间
  await supabase
    .from('user_sessions')
    .update({ last_active_at: new Date().toISOString() })
    .eq('tenant_id', tenantId)
    .eq('conversation_id', conversationId)
    .eq('is_active', true);

  // 2. 执行业务逻辑（持仓分析、交易录入等）
  // ...
}
```

### 作用

- **统计**：用于计算 DAU/WAU、用户留存、识别沉默用户。
- **清理**：定时任务（如每天凌晨）清理 `last_active_at < now() - interval '30 days'` 且 `is_active = false` 的旧记录。
- **降级**：对 `last_active_at` 超过 7 天但 `is_active = true` 的会话，发送唤醒消息或降低推送频率。

---

## Token 过期后的恢复策略

### 检测 Token 失效

在向 OpenClaw 发送消息前，先检查 Token 有效性：

```typescript
async function getValidContextToken(tenantId: string, sessionType: string): Promise<string | null> {
  const { data: session } = await supabase
    .from('user_sessions')
    .select('id, context_token, last_active_at')
    .eq('tenant_id', tenantId)
    .eq('session_type', sessionType)
    .eq('is_active', true)
    .order('last_active_at', { ascending: false })
    .limit(1)
    .single();

  if (!session) return null;

  // 可选：通过 OpenClaw 健康检查接口预检 token（若平台支持）
  const isValid = await openclaw.validateToken(session.context_token);
  if (!isValid) {
    // 标记失效
    await supabase.from('user_sessions')
      .update({ is_active: false })
      .eq('id', session.id);
    return null;
  }

  return session.context_token;
}
```

### 恢复路径

| 场景 | 处理方式 |
|------|---------|
| Token 过期，但用户仍在 7 天内活跃 | 调用 OpenClaw 重新初始化会话 API，获取新 Token，更新 `user_sessions`，对用户无感知 |
| Token 过期，且用户长期未活跃（>7d）| 发送微信模板消息：「您的会话已过期，请回复「开始」重新激活」 |
| 完全无法恢复（OpenClaw 侧会话已销毁）| 引导用户重新完成 Pairing（流程2），或在微信端重新触发 `contextToken` 生成流程 |
| 用户状态为 `SUSPENDED` | 拒绝恢复，回复提示充值/申诉 |

### 重试与降级

```typescript
async function sendWithTokenRecovery(tenantId: string, message: string) {
  let token = await getValidContextToken(tenantId, 'wechat_claw');

  if (!token) {
    token = await reinitializeOpenClawSession(tenantId);
  }

  if (!token) {
    await notifyUserSessionExpired(tenantId);
    return { success: false, reason: 'SESSION_EXPIRED' };
  }

  try {
    return await openclaw.sendMessage(token, message);
  } catch (err) {
    if (err.code === 'TOKEN_EXPIRED') {
      token = await reinitializeOpenClawSession(tenantId);
      if (token) {
        return await openclaw.sendMessage(token, message);
      }
    }
    throw err;
  }
}
```

---

## 多设备登录处理

### 设计原则

- **一个用户，多个会话**：同一 `tenant_id` 可在 `user_sessions` 中存在多条记录，只要 `(session_type, conversation_id)` 组合唯一。
- **通道隔离**：Web、微信、Telegram 的会话 Token 互相独立，互不影响。
- **可选互踢**：同一 `session_type` 下是否只允许一个活跃会话，由产品策略决定（当前阶段建议允许共存）。

### 表设计支撑

```sql
-- 天然的多设备支持：UNIQUE(tenant_id, session_type, conversation_id)
-- 允许：
--   (user_1, 'wechat_claw', 'conv_A')  -- 手机微信
--   (user_1, 'wechat_claw', 'conv_B')  -- 平板微信（同一 openid 的不同对话，罕见但可能）
--   (user_1, 'web',        'session_C') -- WebApp
--   (user_1, 'telegram',   'chat_D')    -- Telegram Bot
```

### 并发场景处理

| 场景 | 行为 |
|------|------|
| 用户同时在 WebApp 和微信查询持仓 | 两个会话独立，各自持有不同 `contextToken`，后端分别响应 |
| 微信端 Token 过期，WebApp 正常 | 仅影响微信推送；WebApp 会话不受影响 |
| 用户在 WebApp 修改昵称 | 数据写入 `public.users`，双端下次交互时读取最新数据 |
| 用户发送「退出」到微信 Agent | 仅将当前微信会话 `is_active = false`；WebApp 保持登录 |
| Admin 在后台禁用用户 (`status='SUSPENDED'`) | 所有该 `tenant_id` 的活跃会话批量置为 `is_active = false`，全渠道拒绝服务 |

### 批量会话管理（Admin / 系统级）

```sql
-- 禁用用户时，级联下线所有会话
UPDATE public.user_sessions
SET is_active = FALSE, updated_at = now()
WHERE tenant_id = '<user_id>' AND is_active = TRUE;

-- 查询用户所有活跃会话（用于在线设备列表）
SELECT session_type, conversation_id, device_info, last_active_at
FROM public.user_sessions
WHERE tenant_id = '<user_id>' AND is_active = TRUE
ORDER BY last_active_at DESC;
```

---

## 清理与归档策略

| 数据类型 | 清理条件 | 操作 |
|---------|---------|------|
| 非活跃会话 | `is_active = false` 且 `updated_at < now() - interval '30 days'` | DELETE |
| 超期活跃会话 | `last_active_at < now() - interval '90 days'` 且 `is_active = true` | 先标记 `is_active = false`，再 30 天后 DELETE |
| 无效 pairing_code | `openclaw_pairing_code` 生成时间超过 10 分钟 | 定期脚本清空（或单独 `pairing_code_expires_at` 字段） |

建议通过 Supabase Cron / pg_cron 配置定时任务：

```sql
-- 每天凌晨 3 点清理过期会话（需安装 pg_cron）
SELECT cron.schedule('cleanup-expired-sessions', '0 3 * * *', $$
  DELETE FROM public.user_sessions
  WHERE is_active = false AND updated_at < now() - interval '30 days';
$$);
```

---

## 与 delivery_runs 的协作

`delivery_runs` 表记录每一次消息下发的任务。在创建 `delivery_runs` 记录时，应关联当前使用的 `context_token`：

```sql
INSERT INTO public.delivery_runs (
  job_run_id, tenant_id, channel, content, context_token,
  target_conversation, idempotency_key
)
VALUES (
  '<job_id>', '<tenant_id>', 'wechat_claw', '{"text":"持仓日报..."}',
  '<context_token>', '<conversation_id>', '<uuid>'
);
```

这样即使发送失败需要重试，也能从 `delivery_runs` 中回溯当时使用的 Token，便于排查是 Token 问题还是网络问题。
