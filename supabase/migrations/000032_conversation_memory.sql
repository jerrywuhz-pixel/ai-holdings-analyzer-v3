-- Product-level conversation memory shared by OpenClaw light chat and Hermes deep research.

CREATE TABLE IF NOT EXISTS public.conversation_threads (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES public.tenant_accounts(tenant_id) ON DELETE CASCADE,
  channel_binding_id UUID REFERENCES public.channel_bindings(id) ON DELETE SET NULL,
  openclaw_account_id TEXT,
  channel TEXT NOT NULL DEFAULT 'openclaw_wechat',
  target_conversation TEXT,
  context_token TEXT,
  session_space TEXT,
  thread_key TEXT NOT NULL,
  summary TEXT NOT NULL DEFAULT '',
  summary_turn_count INTEGER NOT NULL DEFAULT 0,
  last_turn_at TIMESTAMPTZ,
  thread_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT conversation_threads_key_not_blank CHECK (btrim(thread_key) <> ''),
  CONSTRAINT conversation_threads_summary_turn_count_nonnegative CHECK (summary_turn_count >= 0)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_conversation_threads_tenant_key
  ON public.conversation_threads (tenant_id, thread_key);

CREATE INDEX IF NOT EXISTS idx_conversation_threads_binding_seen
  ON public.conversation_threads (channel_binding_id, last_turn_at DESC);

CREATE TABLE IF NOT EXISTS public.conversation_turns (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  thread_id UUID NOT NULL REFERENCES public.conversation_threads(id) ON DELETE CASCADE,
  tenant_id UUID NOT NULL REFERENCES public.tenant_accounts(tenant_id) ON DELETE CASCADE,
  channel_binding_id UUID REFERENCES public.channel_bindings(id) ON DELETE SET NULL,
  message_id TEXT,
  role TEXT NOT NULL,
  content_type TEXT NOT NULL DEFAULT 'text',
  content TEXT NOT NULL,
  route TEXT,
  provider TEXT,
  model TEXT,
  response_id TEXT,
  raw_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT conversation_turns_role_check CHECK (role IN ('user', 'assistant', 'system', 'tool')),
  CONSTRAINT conversation_turns_content_type_check CHECK (content_type IN ('text', 'voice', 'image', 'event', 'system')),
  CONSTRAINT conversation_turns_content_not_blank CHECK (btrim(content) <> '')
);

CREATE INDEX IF NOT EXISTS idx_conversation_turns_thread_created
  ON public.conversation_turns (thread_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_conversation_turns_tenant_created
  ON public.conversation_turns (tenant_id, created_at DESC);

CREATE UNIQUE INDEX IF NOT EXISTS idx_conversation_turns_message_dedupe
  ON public.conversation_turns (thread_id, role, message_id)
  WHERE message_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS public.conversation_summaries (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  thread_id UUID NOT NULL REFERENCES public.conversation_threads(id) ON DELETE CASCADE,
  tenant_id UUID NOT NULL REFERENCES public.tenant_accounts(tenant_id) ON DELETE CASCADE,
  summary_text TEXT NOT NULL,
  turn_count INTEGER NOT NULL DEFAULT 0,
  source_turn_id UUID REFERENCES public.conversation_turns(id) ON DELETE SET NULL,
  summary_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT conversation_summaries_turn_count_nonnegative CHECK (turn_count >= 0)
);

CREATE INDEX IF NOT EXISTS idx_conversation_summaries_thread_created
  ON public.conversation_summaries (thread_id, created_at DESC);

ALTER TABLE public.conversation_threads ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.conversation_turns ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.conversation_summaries ENABLE ROW LEVEL SECURITY;

CREATE POLICY "conversation_threads_select_tenant"
  ON public.conversation_threads FOR SELECT
  USING (tenant_id = public.current_tenant_id());

CREATE POLICY "conversation_threads_service_all"
  ON public.conversation_threads FOR ALL
  TO service_role
  USING (true)
  WITH CHECK (true);

CREATE POLICY "conversation_turns_select_tenant"
  ON public.conversation_turns FOR SELECT
  USING (tenant_id = public.current_tenant_id());

CREATE POLICY "conversation_turns_service_all"
  ON public.conversation_turns FOR ALL
  TO service_role
  USING (true)
  WITH CHECK (true);

CREATE POLICY "conversation_summaries_select_tenant"
  ON public.conversation_summaries FOR SELECT
  USING (tenant_id = public.current_tenant_id());

CREATE POLICY "conversation_summaries_service_all"
  ON public.conversation_summaries FOR ALL
  TO service_role
  USING (true)
  WITH CHECK (true);

COMMENT ON TABLE public.conversation_threads IS
  'Product-level conversation thread shared by OpenClaw light chat and Hermes deep research; not a provider-specific chat session.';

COMMENT ON TABLE public.conversation_turns IS
  'Immutable user/assistant turns used to keep WeChat conversations continuous across model routes.';

COMMENT ON TABLE public.conversation_summaries IS
  'Rolling conversation summaries used as compact shared context. Chat memory does not directly write holdings facts.';

