-- Persist Tencent OpenClaw Weixin QR session metadata for WebApp-driven binding.

ALTER TABLE public.wechat_clawbot_auth_sessions
  ADD COLUMN IF NOT EXISTS session_key TEXT;
