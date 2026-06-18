-- Holdings 3.0 P0 — 微信渠道只允许每个租户仅保留一个有效绑定
--
-- 仅对 openclaw_wechat 渠道约束生效：同一租户只能有 1 个 active 绑定。
CREATE UNIQUE INDEX IF NOT EXISTS idx_channel_bindings_openclaw_wechat_active
  ON public.channel_bindings (tenant_id, channel)
  WHERE channel = 'openclaw_wechat'
    AND binding_status = 'active';

-- 既有数据清理：把重复绑定历史里非最新的一条先标记为暂停/撤销，
-- 避免历史脏数据阻塞唯一索引。
WITH ranked AS (
  SELECT
    id,
    tenant_id,
    ROW_NUMBER() OVER (
      PARTITION BY tenant_id
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
