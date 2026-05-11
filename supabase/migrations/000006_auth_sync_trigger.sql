-- AI 持仓投资分析系统 2.0 - Auth 同步触发器
-- Phase 1 Sprint 1.3: 用户与会话管理
-- 当新用户通过 Supabase Auth 注册时，自动在 public.users 创建记录

CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS TRIGGER AS $$
BEGIN
  INSERT INTO public.users (id, email, status, plan, created_at, updated_at)
  VALUES (
    NEW.id,
    NEW.email,
    'NEW',
    'free',
    NOW(),
    NOW()
  )
  ON CONFLICT (id) DO NOTHING;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- 绑定触发器到 auth.users
CREATE TRIGGER on_auth_user_created
  AFTER INSERT ON auth.users
  FOR EACH ROW EXECUTE FUNCTION public.handle_new_user();
