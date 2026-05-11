-- AI 持仓投资分析系统 2.0 - 开发环境种子数据
-- Phase 1 Sprint 1.3: 用户与会话管理

-- 开发环境种子数据
INSERT INTO auth.users (id, email, encrypted_password, email_confirmed_at, raw_app_meta_data, raw_user_meta_data)
VALUES
  ('00000000-0000-0000-0000-000000000001', 'dev@example.com', '$2a$10$PLACEHOLDER_HASH', now(), '{"provider":"email","providers":["email"]}', '{"name":"Dev User"}')
ON CONFLICT DO NOTHING;

-- public.users 会通过触发器自动创建，但这里显式补充微信信息
UPDATE public.users SET
  wechat_openid = 'fake_wechat_openid_001',
  wechat_nickname = '开发用户',
  status = 'ACTIVE',
  role = 'admin'
WHERE id = '00000000-0000-0000-0000-000000000001';
