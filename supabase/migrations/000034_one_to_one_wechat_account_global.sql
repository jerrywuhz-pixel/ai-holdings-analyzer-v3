-- 清理历史脏数据：避免已有重复 active 绑定阻塞唯一索引。保留每个微信账号最近一次活跃绑定，
-- 其余同账号的 active 绑定统一撤销，保持可追溯且可恢复。
WITH ranked AS (
  SELECT
    id,
    ROW_NUMBER() OVER (
      PARTITION BY openclaw_account_id
      ORDER BY COALESCE(updated_at, created_at) DESC, created_at DESC
    ) AS rn
  FROM public.channel_bindings
  WHERE channel = 'openclaw_wechat'
    AND binding_status = 'active'
),
dedupe AS (
  SELECT id
  FROM ranked
  WHERE rn > 1
)
UPDATE public.channel_bindings
SET
  binding_status = 'revoked',
  is_primary = FALSE,
  updated_at = now()
WHERE id IN (SELECT id FROM dedupe);

-- 进一步强化约束：同一个 openclaw_account_id 在 openclaw_wechat 渠道下只能被一个租户
-- 绑定为 active。
CREATE UNIQUE INDEX IF NOT EXISTS idx_channel_bindings_openclaw_wechat_account_active
  ON public.channel_bindings (openclaw_account_id)
  WHERE channel = 'openclaw_wechat'
    AND binding_status = 'active';
