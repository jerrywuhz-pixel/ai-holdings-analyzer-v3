import postgres from 'postgres';
import type { AppUser } from '@/lib/supabase';
import {
  ensureDefaultTradingRules,
  evaluateTradingDiscipline,
  type DisciplineEvaluationResult,
} from '@/lib/trading-rules';

declare global {
  // eslint-disable-next-line no-var
  var __aiHoldingsAccountSql: ReturnType<typeof postgres> | undefined;
}

export interface AccountWorkspaceContext {
  accountId: string;
  tenantId: string;
  ownerUserId: string;
  email: string;
  displayName: string;
  baseCurrency: string;
  status: string;
  portfolioViews: PortfolioViewContext[];
  activePortfolioViewId: string;
  followView: FollowViewContext | null;
  listView: ListViewContext | null;
  assetSources: AssetSourceContext[];
  manualPositionCount: number;
}

export interface PortfolioViewContext {
  id: string;
  name: string;
  slug: string;
  viewType: string;
  baseCurrency: string;
  isDefault: boolean;
  sourceCount: number;
}

export interface FollowViewContext {
  id: string;
  name: string;
  slug: string;
  strategyFocus: string;
  itemCount: number;
}

export interface ListViewContext {
  id: string;
  name: string;
  slug: string;
  listType: string;
  itemCount: number;
}

export interface AssetSourceContext {
  id: string;
  sourceKey: string;
  sourceName: string;
  sourceType: string;
  provider: string;
  priority: number;
  sourceQuality: string;
  isActive: boolean;
  lastSeenAt: string | null;
}

export interface ManualPositionInput {
  instrumentType?: 'stock' | 'etf' | 'option_contract';
  symbol: string;
  name?: string;
  market?: string;
  exchange?: string;
  quantity: number;
  averageCost?: number | null;
  marketPrice?: number | null;
  marketValue?: number | null;
  currency?: string;
  note?: string;
  sourceAsOf?: string | null;
  sourceTier?: string;
  sourceActionability?: string;
  sourceLineage?: Record<string, unknown>;
}

export interface ManualPositionRecord {
  id: string;
  symbol: string;
  name: string | null;
  market: string;
  instrumentType: string;
  positionSide: string;
  quantity: number;
  averageCost: number | null;
  marketPrice: number | null;
  marketValue: number | null;
  currency: string;
  optionType?: string | null;
  strike?: number | null;
  expiry?: string | null;
  multiplier?: number | null;
  unrealizedPnlPct?: number | null;
  sourceTier: string;
  sourceActionability: string;
  updatedAt: string;
}

export interface AccountManualPositionSnapshot {
  positions: ManualPositionRecord[];
  updatedAt: string | null;
}

export interface ManualPositionWriteResult {
  position: ManualPositionRecord;
  snapshotId: string;
  discipline: DisciplineEvaluationResult;
}

function normalizeEmail(email: string) {
  return email.trim().toLowerCase();
}

function databaseUrl() {
  return process.env.WEBAPP_DATABASE_URL || process.env.DATABASE_URL || '';
}

export function accountDatabaseConfigured() {
  return Boolean(databaseUrl());
}

function sqlClient() {
  const url = databaseUrl();
  if (!url) {
    throw new Error('账户工作区需要配置 DATABASE_URL 或 WEBAPP_DATABASE_URL');
  }

  if (!globalThis.__aiHoldingsAccountSql) {
    globalThis.__aiHoldingsAccountSql = postgres(url, {
      max: 4,
      idle_timeout: 20,
      connect_timeout: 10,
      prepare: false,
    });
  }

  return globalThis.__aiHoldingsAccountSql;
}

function runtimeSchemaRepairEnabled() {
  return (process.env.WEBAPP_RUNTIME_SCHEMA_REPAIR || 'true').trim().toLowerCase() !== 'false';
}

function userRole(user: AppUser) {
  return user.role === 'admin' ? 'admin' : 'user';
}

function userStatus(user: AppUser) {
  return user.role === 'admin' ? 'ACTIVE' : 'ACTIVE';
}

function normalizedInstrumentType(value?: string) {
  if (value === 'etf' || value === 'option_contract') return value;
  return 'stock';
}

function normalizedMarket(value?: string) {
  const market = (value || 'US').trim().toUpperCase();
  if (market === 'HK' || market === 'CN' || market === 'US') return market;
  return market || 'US';
}

function defaultExchange(market: string) {
  if (market === 'HK') return 'HKEX';
  if (market === 'CN') return 'SSE/SZSE';
  return 'US';
}

function currencyForMarket(market: string, requested?: string) {
  if (requested?.trim()) return requested.trim().toUpperCase();
  if (market === 'HK') return 'HKD';
  if (market === 'CN') return 'CNY';
  return 'USD';
}

function normalizeSourceTier(value?: string) {
  const tier = (value || 'user_confirmed').trim();
  if (tier === 'L1_trading' || tier === 'user_confirmed' || tier === 'estimated') return tier;
  return 'user_confirmed';
}

function normalizeSourceActionability(value?: string) {
  const actionability = (value || 'analysis_only').trim();
  if (actionability === 'trade_draft' || actionability === 'analysis_only' || actionability === 'blocked') {
    return actionability;
  }
  return 'analysis_only';
}

function toNumber(value: unknown) {
  if (value === null || value === undefined) return null;
  const numberValue = Number(value);
  return Number.isFinite(numberValue) ? numberValue : null;
}

function serializeDate(value: unknown) {
  if (value instanceof Date) return value.toISOString();
  return value ? String(value) : null;
}

async function ensureWorkspaceSchema() {
  if (!runtimeSchemaRepairEnabled()) {
    return;
  }

  const sql = sqlClient();
  await sql`
    CREATE TABLE IF NOT EXISTS public.users (
      id UUID PRIMARY KEY,
      email TEXT NOT NULL UNIQUE,
      role TEXT NOT NULL DEFAULT 'user',
      status TEXT NOT NULL DEFAULT 'ACTIVE',
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
  `;
  await sql`ALTER TABLE public.tenant_accounts ADD COLUMN IF NOT EXISTS account_id UUID`;
  await sql`UPDATE public.tenant_accounts SET account_id = gen_random_uuid() WHERE account_id IS NULL`;
  await sql`CREATE UNIQUE INDEX IF NOT EXISTS idx_tenant_accounts_account_id ON public.tenant_accounts(account_id)`;

  await sql`
    CREATE TABLE IF NOT EXISTS public.follow_views (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      tenant_id UUID NOT NULL REFERENCES public.tenant_accounts(tenant_id) ON DELETE CASCADE,
      name TEXT NOT NULL,
      slug TEXT NOT NULL,
      strategy_focus TEXT NOT NULL DEFAULT 'watchlist',
      base_currency TEXT NOT NULL DEFAULT 'USD',
      is_default BOOLEAN NOT NULL DEFAULT FALSE,
      settings JSONB NOT NULL DEFAULT '{}'::jsonb,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      CONSTRAINT follow_views_slug_not_blank CHECK (btrim(slug) <> '')
    )
  `;
  await sql`CREATE UNIQUE INDEX IF NOT EXISTS idx_follow_views_tenant_slug ON public.follow_views(tenant_id, slug)`;
  await sql`
    CREATE UNIQUE INDEX IF NOT EXISTS idx_follow_views_default
      ON public.follow_views(tenant_id)
      WHERE is_default = TRUE
  `;

  await sql`
    CREATE TABLE IF NOT EXISTS public.follow_view_items (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      tenant_id UUID NOT NULL REFERENCES public.tenant_accounts(tenant_id) ON DELETE CASCADE,
      follow_view_id UUID NOT NULL REFERENCES public.follow_views(id) ON DELETE CASCADE,
      symbol TEXT NOT NULL,
      name TEXT,
      market TEXT NOT NULL DEFAULT 'US',
      target_action TEXT NOT NULL DEFAULT 'watch',
      thesis TEXT,
      target_buy_zone JSONB NOT NULL DEFAULT '{}'::jsonb,
      sell_put_preferences JSONB NOT NULL DEFAULT '{}'::jsonb,
      trigger_rules JSONB NOT NULL DEFAULT '[]'::jsonb,
      risk_flags TEXT[] NOT NULL DEFAULT '{}'::text[],
      next_review_at TIMESTAMPTZ,
      data_lineage JSONB NOT NULL DEFAULT '[]'::jsonb,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      CONSTRAINT follow_view_items_symbol_not_blank CHECK (btrim(symbol) <> '')
    )
  `;
  await sql`
    CREATE UNIQUE INDEX IF NOT EXISTS idx_follow_view_items_unique
      ON public.follow_view_items(follow_view_id, symbol, market)
  `;

  await sql`
    CREATE TABLE IF NOT EXISTS public.list_views (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      tenant_id UUID NOT NULL REFERENCES public.tenant_accounts(tenant_id) ON DELETE CASCADE,
      name TEXT NOT NULL,
      slug TEXT NOT NULL,
      list_type TEXT NOT NULL DEFAULT 'closed_positions',
      base_currency TEXT NOT NULL DEFAULT 'USD',
      is_default BOOLEAN NOT NULL DEFAULT FALSE,
      settings JSONB NOT NULL DEFAULT '{}'::jsonb,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      CONSTRAINT list_views_slug_not_blank CHECK (btrim(slug) <> '')
    )
  `;
  await sql`CREATE UNIQUE INDEX IF NOT EXISTS idx_list_views_tenant_slug ON public.list_views(tenant_id, slug)`;
  await sql`
    CREATE UNIQUE INDEX IF NOT EXISTS idx_list_views_default
      ON public.list_views(tenant_id)
      WHERE is_default = TRUE
  `;

  await sql`
    CREATE TABLE IF NOT EXISTS public.list_view_items (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      tenant_id UUID NOT NULL REFERENCES public.tenant_accounts(tenant_id) ON DELETE CASCADE,
      list_view_id UUID NOT NULL REFERENCES public.list_views(id) ON DELETE CASCADE,
      symbol TEXT NOT NULL,
      name TEXT,
      market TEXT NOT NULL DEFAULT 'US',
      opened_at TIMESTAMPTZ,
      closed_at TIMESTAMPTZ,
      realized_pnl NUMERIC(18,2),
      exit_reason TEXT,
      review_summary TEXT,
      rebuy_status TEXT NOT NULL DEFAULT 'not_reviewed',
      rebuy_conditions JSONB NOT NULL DEFAULT '{}'::jsonb,
      data_lineage JSONB NOT NULL DEFAULT '[]'::jsonb,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      CONSTRAINT list_view_items_symbol_not_blank CHECK (btrim(symbol) <> '')
    )
  `;
  await sql`CREATE INDEX IF NOT EXISTS idx_list_view_items_symbol ON public.list_view_items(tenant_id, symbol, closed_at DESC)`;

  await sql`
    CREATE TABLE IF NOT EXISTS public.webapp_manual_positions (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      tenant_id UUID NOT NULL REFERENCES public.tenant_accounts(tenant_id) ON DELETE CASCADE,
      portfolio_view_id UUID NOT NULL REFERENCES public.portfolio_views(id) ON DELETE CASCADE,
      asset_source_id UUID NOT NULL REFERENCES public.asset_sources(id) ON DELETE RESTRICT,
      instrument_type public.instrument_type NOT NULL DEFAULT 'stock',
      symbol TEXT NOT NULL,
      name TEXT,
      market TEXT NOT NULL DEFAULT 'US',
      exchange TEXT,
      position_side public.position_side NOT NULL DEFAULT 'long',
      quantity NUMERIC(24,8) NOT NULL,
      average_cost NUMERIC(18,6),
      market_price NUMERIC(18,6),
      market_value NUMERIC(18,2),
      currency TEXT NOT NULL DEFAULT 'USD',
      source_quality public.source_quality NOT NULL DEFAULT 'user_confirmed',
      source_tier TEXT NOT NULL DEFAULT 'user_confirmed',
      source_actionability TEXT NOT NULL DEFAULT 'analysis_only',
      source_as_of TIMESTAMPTZ,
      source_lineage JSONB NOT NULL DEFAULT '{}'::jsonb,
      note TEXT,
      position_status public.portfolio_position_status NOT NULL DEFAULT 'open',
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      CONSTRAINT webapp_manual_positions_symbol_not_blank CHECK (btrim(symbol) <> ''),
      CONSTRAINT webapp_manual_positions_quantity_non_negative CHECK (quantity >= 0)
    )
  `;
  await sql`ALTER TABLE public.webapp_manual_positions ADD COLUMN IF NOT EXISTS source_tier TEXT NOT NULL DEFAULT 'user_confirmed'`;
  await sql`ALTER TABLE public.webapp_manual_positions ADD COLUMN IF NOT EXISTS source_actionability TEXT NOT NULL DEFAULT 'analysis_only'`;
  await sql`ALTER TABLE public.webapp_manual_positions ADD COLUMN IF NOT EXISTS source_as_of TIMESTAMPTZ`;
  await sql`ALTER TABLE public.webapp_manual_positions ADD COLUMN IF NOT EXISTS source_lineage JSONB NOT NULL DEFAULT '{}'::jsonb`;
  await sql`
    CREATE INDEX IF NOT EXISTS idx_webapp_manual_positions_tenant_status
      ON public.webapp_manual_positions(tenant_id, position_status, updated_at DESC)
  `;
  await sql`
    CREATE UNIQUE INDEX IF NOT EXISTS idx_webapp_manual_positions_open_unique
      ON public.webapp_manual_positions(tenant_id, portfolio_view_id, symbol, instrument_type)
      WHERE position_status = 'open'
  `;
  await sql`
    CREATE TABLE IF NOT EXISTS public.trading_rules (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      tenant_id UUID NOT NULL REFERENCES public.tenant_accounts(tenant_id) ON DELETE CASCADE,
      name TEXT NOT NULL,
      rule_key TEXT NOT NULL,
      rule_type TEXT NOT NULL,
      scopes TEXT[] NOT NULL DEFAULT '{}'::text[],
      markets TEXT[] NOT NULL DEFAULT '{}'::text[],
      instruments TEXT[] NOT NULL DEFAULT '{}'::text[],
      condition JSONB NOT NULL DEFAULT '{}'::jsonb,
      message TEXT NOT NULL,
      action_on_violation TEXT NOT NULL DEFAULT 'warn',
      priority INTEGER NOT NULL DEFAULT 100,
      is_active BOOLEAN NOT NULL DEFAULT TRUE,
      source TEXT NOT NULL DEFAULT 'user',
      last_triggered_at TIMESTAMPTZ,
      trigger_count BIGINT NOT NULL DEFAULT 0,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      CONSTRAINT trading_rules_rule_key_not_blank CHECK (btrim(rule_key) <> ''),
      CONSTRAINT trading_rules_name_not_blank CHECK (btrim(name) <> ''),
      CONSTRAINT trading_rules_rule_type_check CHECK (rule_type IN ('allowlist', 'blocklist', 'time_window', 'position_limit', 'risk_budget', 'confirmation_required', 'custom')),
      CONSTRAINT trading_rules_action_check CHECK (action_on_violation IN ('warn', 'block', 'require_confirmation')),
      CONSTRAINT trading_rules_priority_positive CHECK (priority > 0)
    )
  `;
  await sql`CREATE UNIQUE INDEX IF NOT EXISTS idx_trading_rules_tenant_key ON public.trading_rules(tenant_id, rule_key)`;
  await sql`CREATE INDEX IF NOT EXISTS idx_trading_rules_tenant_active ON public.trading_rules(tenant_id, is_active, priority)`;
  await sql`
    CREATE TABLE IF NOT EXISTS public.discipline_checks (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      tenant_id UUID NOT NULL REFERENCES public.tenant_accounts(tenant_id) ON DELETE CASCADE,
      symbol TEXT,
      instrument_type public.instrument_type,
      action_type TEXT NOT NULL,
      result TEXT NOT NULL,
      triggered_rule_ids UUID[] NOT NULL DEFAULT '{}'::uuid[],
      highest_action TEXT NOT NULL DEFAULT 'none',
      check_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      CONSTRAINT discipline_checks_action_type_not_blank CHECK (btrim(action_type) <> ''),
      CONSTRAINT discipline_checks_result_check CHECK (result IN ('passed', 'warned', 'blocked', 'requires_confirmation')),
      CONSTRAINT discipline_checks_highest_action_check CHECK (highest_action IN ('none', 'warn', 'block', 'require_confirmation'))
    )
  `;
  await sql`CREATE INDEX IF NOT EXISTS idx_discipline_checks_tenant_created ON public.discipline_checks(tenant_id, created_at DESC)`;
}

async function ensureAuthUser(user: AppUser) {
  const sql = sqlClient();
  const email = normalizeEmail(user.email);
  await sql`
    INSERT INTO public.users (id, email, role, status)
    VALUES (${user.id}, ${email}, ${userRole(user)}, ${userStatus(user)})
    ON CONFLICT (id) DO UPDATE SET
      email = EXCLUDED.email,
      role = EXCLUDED.role,
      status = 'ACTIVE',
      updated_at = now()
  `;
  await sql`
    INSERT INTO public.tenant_accounts (tenant_id, owner_user_id, display_name, account_status, base_currency)
    VALUES (${user.id}, ${user.id}, ${user.name || email}, 'active', 'USD')
    ON CONFLICT (tenant_id) DO UPDATE SET
      display_name = EXCLUDED.display_name,
      account_status = 'active',
      updated_at = now()
  `;
  await sql`UPDATE public.tenant_accounts SET account_id = gen_random_uuid() WHERE tenant_id = ${user.id} AND account_id IS NULL`;
}

async function ensureAssetSource(
  tenantId: string,
  sourceKey: string,
  sourceName: string,
  sourceType: string,
  provider: string,
  priority: number,
  sourceQuality: string,
  isActive = true
) {
  const sql = sqlClient();
  const rows = await sql<{ id: string }[]>`
    INSERT INTO public.asset_sources (
      tenant_id, source_key, source_name, source_type, provider, priority, source_quality, is_active
    )
    VALUES (
      ${tenantId}, ${sourceKey}, ${sourceName}, ${sourceType}, ${provider}, ${priority}, ${sourceQuality}, ${isActive}
    )
    ON CONFLICT (tenant_id, source_key) DO UPDATE SET
      source_name = EXCLUDED.source_name,
      source_type = EXCLUDED.source_type,
      provider = EXCLUDED.provider,
      priority = EXCLUDED.priority,
      source_quality = EXCLUDED.source_quality,
      is_active = EXCLUDED.is_active,
      updated_at = now()
    RETURNING id
  `;
  return rows[0].id;
}

async function ensurePortfolioView(
  tenantId: string,
  slug: string,
  name: string,
  viewType: string,
  baseCurrency: string,
  isDefault: boolean,
  settings: Record<string, unknown> = {}
) {
  const sql = sqlClient();
  if (isDefault) {
    const existingDefault = await sql<{ id: string }[]>`
      SELECT id
      FROM public.portfolio_views
      WHERE tenant_id = ${tenantId}
        AND is_default = TRUE
      LIMIT 1
    `;
    if (existingDefault[0]) {
      await sql`
        UPDATE public.portfolio_views
        SET
          name = COALESCE(name, ${name}),
          view_type = COALESCE(view_type, ${viewType}),
          base_currency = COALESCE(base_currency, ${baseCurrency}),
          settings = COALESCE(settings, '{}'::jsonb) || ${sql.json(settings as any)},
          updated_at = now()
        WHERE id = ${existingDefault[0].id}
      `;
      return existingDefault[0].id;
    }
  }

  const rows = await sql<{ id: string }[]>`
    INSERT INTO public.portfolio_views (
      tenant_id, name, slug, view_type, base_currency, is_default, settings
    )
    VALUES (${tenantId}, ${name}, ${slug}, ${viewType}, ${baseCurrency}, ${isDefault}, ${sql.json(settings as any)})
    ON CONFLICT (tenant_id, slug) DO UPDATE SET
      name = EXCLUDED.name,
      view_type = EXCLUDED.view_type,
      base_currency = EXCLUDED.base_currency,
      settings = public.portfolio_views.settings || EXCLUDED.settings,
      updated_at = now()
    RETURNING id
  `;
  return rows[0].id;
}

async function ensureWorkspaceDefaults(user: AppUser) {
  const sql = sqlClient();
  const tenantId = user.id;
  const manualSourceId = await ensureAssetSource(
    tenantId,
    'manual-webapp',
    '手工录入',
    'manual',
    'webapp',
    20,
    'user_confirmed',
    true
  );
  await ensureAssetSource(tenantId, 'message-trade-input', '买卖消息输入', 'message_trade_input', 'wechat_or_webapp', 30, 'user_confirmed', true);
  await ensureAssetSource(tenantId, 'ocr-input', '截图识别', 'ocr', 'webapp_or_wechat', 60, 'estimated', true);
  await ensureAssetSource(tenantId, 'voice-input', '语音识别', 'voice_asr', 'wechat_or_webapp', 65, 'estimated', true);
  await ensureAssetSource(tenantId, 'system-futu-market-data', '系统 Futu 行情源', 'broker_api', 'futu', 10, 'public_fallback', false);

  const defaultViewId = await ensurePortfolioView(
    tenantId,
    'all-assets',
    '全部资产',
    'system_default',
    'USD',
    true,
    { scope: 'A 股 / 港股 / 美股 / ETF / 期权' }
  );
  await ensurePortfolioView(
    tenantId,
    'option-income',
    '期权现金流',
    'options_income',
    'USD',
    false,
    { scope: 'Sell Put 与期权资金占用' }
  );
  await ensurePortfolioView(
    tenantId,
    'long-term',
    '长期持仓',
    'custom',
    'USD',
    false,
    { scope: '股票 / ETF 长期账户' }
  );

  const sourceRows = await sql<{ id: string }[]>`
    SELECT id FROM public.asset_sources WHERE tenant_id = ${tenantId} AND is_active = TRUE
  `;
  for (const source of sourceRows) {
    await sql`
      INSERT INTO public.portfolio_view_sources (tenant_id, portfolio_view_id, asset_source_id, include_mode)
      VALUES (${tenantId}, ${defaultViewId}, ${source.id}, 'include')
      ON CONFLICT (portfolio_view_id, asset_source_id) DO NOTHING
    `;
  }

  await sql`
    INSERT INTO public.follow_views (tenant_id, name, slug, strategy_focus, base_currency, is_default)
    VALUES (${tenantId}, '关注清单', 'default-follow', 'watchlist', 'USD', TRUE)
    ON CONFLICT (tenant_id, slug) DO UPDATE SET
      name = EXCLUDED.name,
      updated_at = now()
  `;
  await sql`
    INSERT INTO public.list_views (tenant_id, name, slug, list_type, base_currency, is_default)
    VALUES (${tenantId}, '清仓回溯', 'closed-positions', 'closed_positions', 'USD', TRUE)
    ON CONFLICT (tenant_id, slug) DO UPDATE SET
      name = EXCLUDED.name,
      updated_at = now()
  `;

  await sql`
    INSERT INTO public.broker_connections (
      tenant_id, broker, connection_label, permission_scope, auth_status, connection_mode,
      connector_kind, token_storage_mode, capabilities, status_detail, last_successful_sync_at
    )
    VALUES (
      ${tenantId}, 'manual', '手工录入', 'read_only', 'connected', 'webapp_manual',
      'manual_position_input', 'not_stored', ${sql.json(['positions'])},
      ${sql.json({ description: 'WebApp 手工录入的持仓来源' })}, now()
    )
    ON CONFLICT (tenant_id, connection_label) DO UPDATE SET
      auth_status = 'connected',
      status_detail = EXCLUDED.status_detail,
      updated_at = now()
  `;
  await ensureDefaultTradingRules(tenantId);

  return manualSourceId;
}

export async function ensureUserAccount(user: AppUser): Promise<AccountWorkspaceContext> {
  await ensureWorkspaceSchema();
  await ensureAuthUser(user);
  await ensureWorkspaceDefaults(user);
  return getAccountWorkspace(user);
}

export async function getAccountWorkspace(user: AppUser): Promise<AccountWorkspaceContext> {
  await ensureWorkspaceSchema();
  const sql = sqlClient();
  const accountRows = await sql<{
    account_id: string;
    tenant_id: string;
    owner_user_id: string;
    display_name: string | null;
    account_status: string;
    base_currency: string;
    email: string | null;
  }[]>`
    SELECT
      ta.account_id,
      ta.tenant_id,
      ta.owner_user_id,
      ta.display_name,
      ta.account_status,
      ta.base_currency,
      u.email
    FROM public.tenant_accounts ta
    JOIN public.users u ON u.id = ta.owner_user_id
    WHERE ta.owner_user_id = ${user.id}
    LIMIT 1
  `;

  const account = accountRows[0];
  if (!account) {
    throw new Error('当前登录用户尚未完成账户初始化');
  }

  const [views, followViews, listViews, sources, manualCountRows] = await Promise.all([
    sql<{
      id: string;
      name: string;
      slug: string;
      view_type: string;
      base_currency: string;
      is_default: boolean;
      source_count: number;
    }[]>`
      SELECT
        pv.id,
        pv.name,
        pv.slug,
        pv.view_type,
        pv.base_currency,
        pv.is_default,
        COUNT(pvs.id)::int AS source_count
      FROM public.portfolio_views pv
      LEFT JOIN public.portfolio_view_sources pvs
        ON pvs.portfolio_view_id = pv.id AND pvs.is_active = TRUE
      WHERE pv.tenant_id = ${account.tenant_id}
      GROUP BY pv.id
      ORDER BY pv.is_default DESC, pv.created_at ASC
    `,
    sql<{
      id: string;
      name: string;
      slug: string;
      strategy_focus: string;
      item_count: number;
    }[]>`
      SELECT
        fv.id,
        fv.name,
        fv.slug,
        fv.strategy_focus,
        COUNT(fvi.id)::int AS item_count
      FROM public.follow_views fv
      LEFT JOIN public.follow_view_items fvi ON fvi.follow_view_id = fv.id
      WHERE fv.tenant_id = ${account.tenant_id}
      GROUP BY fv.id
      ORDER BY fv.is_default DESC, fv.created_at ASC
    `,
    sql<{
      id: string;
      name: string;
      slug: string;
      list_type: string;
      item_count: number;
    }[]>`
      SELECT
        lv.id,
        lv.name,
        lv.slug,
        lv.list_type,
        COUNT(lvi.id)::int AS item_count
      FROM public.list_views lv
      LEFT JOIN public.list_view_items lvi ON lvi.list_view_id = lv.id
      WHERE lv.tenant_id = ${account.tenant_id}
      GROUP BY lv.id
      ORDER BY lv.is_default DESC, lv.created_at ASC
    `,
    sql<{
      id: string;
      source_key: string;
      source_name: string;
      source_type: string;
      provider: string;
      priority: number;
      source_quality: string;
      is_active: boolean;
      last_seen_at: string | null;
    }[]>`
      SELECT id, source_key, source_name, source_type, provider, priority, source_quality, is_active, last_seen_at
      FROM public.asset_sources
      WHERE tenant_id = ${account.tenant_id}
      ORDER BY priority ASC, created_at ASC
    `,
    sql<{ count: number }[]>`
      SELECT COUNT(*)::int AS count
      FROM public.webapp_manual_positions
      WHERE tenant_id = ${account.tenant_id} AND position_status = 'open'
    `,
  ]);

  const portfolioViews: PortfolioViewContext[] = views.map((view) => ({
    id: view.id,
    name: view.name,
    slug: view.slug,
    viewType: view.view_type,
    baseCurrency: view.base_currency,
    isDefault: view.is_default,
    sourceCount: Number(view.source_count) || 0,
  }));
  const defaultView = portfolioViews.find((view) => view.isDefault) ?? portfolioViews[0];

  return {
    accountId: account.account_id,
    tenantId: account.tenant_id,
    ownerUserId: account.owner_user_id,
    email: account.email || user.email,
    displayName: account.display_name || user.name || user.email,
    baseCurrency: account.base_currency,
    status: account.account_status,
    portfolioViews,
    activePortfolioViewId: defaultView?.id || '',
    followView: followViews[0]
      ? {
          id: followViews[0].id,
          name: followViews[0].name,
          slug: followViews[0].slug,
          strategyFocus: followViews[0].strategy_focus,
          itemCount: Number(followViews[0].item_count) || 0,
        }
      : null,
    listView: listViews[0]
      ? {
          id: listViews[0].id,
          name: listViews[0].name,
          slug: listViews[0].slug,
          listType: listViews[0].list_type,
          itemCount: Number(listViews[0].item_count) || 0,
        }
      : null,
    assetSources: sources.map((source) => ({
      id: source.id,
      sourceKey: source.source_key,
      sourceName: source.source_name,
      sourceType: source.source_type,
      provider: source.provider,
      priority: Number(source.priority),
      sourceQuality: source.source_quality,
      isActive: source.is_active,
      lastSeenAt: serializeDate(source.last_seen_at),
    })),
    manualPositionCount: Number(manualCountRows[0]?.count) || 0,
  };
}

export async function upsertManualPosition(
  user: AppUser,
  input: ManualPositionInput
): Promise<ManualPositionWriteResult> {
  const account = await ensureUserAccount(user);
  const sql = sqlClient();
  const symbol = input.symbol.trim().toUpperCase();
  if (!symbol) {
    throw new Error('请输入标的代码');
  }
  if (!Number.isFinite(input.quantity) || input.quantity <= 0) {
    throw new Error('持仓数量必须大于 0');
  }

  const instrumentType = normalizedInstrumentType(input.instrumentType);
  const market = normalizedMarket(input.market);
  const currency = currencyForMarket(market, input.currency);
  const averageCost = input.averageCost ?? null;
  const marketPrice = input.marketPrice ?? averageCost;
  const marketValue = input.marketValue ?? (marketPrice === null ? null : Number((input.quantity * marketPrice).toFixed(2)));
  const sourceTier = normalizeSourceTier(input.sourceTier);
  const sourceActionability = normalizeSourceActionability(input.sourceActionability);
  if (sourceActionability === 'blocked') {
    throw new Error('当前来源状态不允许写入持仓');
  }
  const discipline = await evaluateTradingDiscipline(account.tenantId, {
    actionType: 'manual_position',
    symbol,
    name: input.name,
    market,
    instrumentType,
    sourceTier,
    sourceActionability,
    payload: {
      quantity: input.quantity,
      averageCost,
      marketPrice,
      source: 'webapp_manual_positions',
    },
  });
  if (discipline.result === 'blocked') {
    throw new Error(`纪律规则已阻止本次记录：${discipline.message}`);
  }
  const sourceAsOf = input.sourceAsOf || new Date().toISOString();
  const sourceLineage = {
    source_type: 'manual_position_input',
    source_surface: 'webapp',
    source_tier: sourceTier,
    actionability: sourceActionability,
    fact_write_allowed: true,
    trade_action_allowed: false,
    ...(input.sourceLineage || {}),
  };
  const manualSource = account.assetSources.find((source) => source.sourceKey === 'manual-webapp');
  const portfolioViewId = account.activePortfolioViewId;

  if (!manualSource || !portfolioViewId) {
    throw new Error('账户默认资产视图尚未初始化');
  }

  const existingRows = await sql<{ id: string }[]>`
    SELECT id
    FROM public.webapp_manual_positions
    WHERE tenant_id = ${account.tenantId}
      AND portfolio_view_id = ${portfolioViewId}
      AND symbol = ${symbol}
      AND instrument_type = ${instrumentType}
      AND position_status = 'open'
    LIMIT 1
  `;

  const positionRows = existingRows[0]
    ? await sql<ManualPositionDbRow[]>`
        UPDATE public.webapp_manual_positions
        SET
          name = ${input.name?.trim() || null},
          market = ${market},
          exchange = ${input.exchange?.trim() || defaultExchange(market)},
          quantity = ${input.quantity},
          average_cost = ${averageCost},
          market_price = ${marketPrice},
          market_value = ${marketValue},
          currency = ${currency},
          source_tier = ${sourceTier},
          source_actionability = ${sourceActionability},
          source_as_of = ${sourceAsOf},
          source_lineage = ${sql.json(sourceLineage)},
          note = ${input.note?.trim() || null},
          updated_at = now()
        WHERE id = ${existingRows[0].id}
        RETURNING *
      `
    : await sql<ManualPositionDbRow[]>`
        INSERT INTO public.webapp_manual_positions (
          tenant_id, portfolio_view_id, asset_source_id, instrument_type, symbol, name,
          market, exchange, quantity, average_cost, market_price, market_value, currency,
          source_tier, source_actionability, source_as_of, source_lineage, note
        )
        VALUES (
          ${account.tenantId}, ${portfolioViewId}, ${manualSource.id}, ${instrumentType}, ${symbol},
          ${input.name?.trim() || null}, ${market}, ${input.exchange?.trim() || defaultExchange(market)},
          ${input.quantity}, ${averageCost}, ${marketPrice}, ${marketValue}, ${currency},
          ${sourceTier}, ${sourceActionability}, ${sourceAsOf}, ${sql.json(sourceLineage)}, ${input.note?.trim() || null}
        )
        RETURNING *
      `;

  const snapshotId = await rebuildManualBrokerSnapshot(account.tenantId);
  return { position: toManualPositionRecord(positionRows[0]), snapshotId, discipline };
}

export async function listManualPositions(
  account: AccountWorkspaceContext
): Promise<AccountManualPositionSnapshot> {
  await ensureWorkspaceSchema();
  const sql = sqlClient();
  const rows = await sql<ManualPositionDbRow[]>`
    SELECT
      id,
      symbol,
      name,
      market,
      instrument_type,
      position_side,
      quantity,
      average_cost,
      market_price,
      market_value,
      currency,
      source_tier,
      source_actionability,
      source_as_of,
      source_lineage,
      updated_at
    FROM public.webapp_manual_positions
    WHERE tenant_id = ${account.tenantId} AND position_status = 'open'
    ORDER BY updated_at DESC, symbol ASC
  `;
  const positions = rows.map(toManualPositionRecord);
  return {
    positions,
    updatedAt: positions[0]?.updatedAt ?? null,
  };
}

interface ManualPositionDbRow {
  id: string;
  symbol: string;
  name: string | null;
  market: string;
  instrument_type: string;
  position_side: string;
  quantity: string | number;
  average_cost: string | number | null;
  market_price: string | number | null;
  market_value: string | number | null;
  currency: string;
  source_tier: string;
  source_actionability: string;
  source_as_of?: string | Date | null;
  source_lineage?: unknown;
  updated_at: string | Date;
}

function toManualPositionRecord(row: ManualPositionDbRow): ManualPositionRecord {
  const quantity = Number(row.quantity);
  const averageCost = toNumber(row.average_cost);
  const marketPrice = resolveManualMarketPrice(toNumber(row.market_price), averageCost);
  const marketValue = resolveManualMarketValue(toNumber(row.market_value), quantity, marketPrice);
  const sourceLineage = asRecord(row.source_lineage);
  const displayName =
    row.name ||
    stringFromRecord(sourceLineage, 'display_name') ||
    stringFromRecord(sourceLineage, 'name') ||
    stringFromRecord(sourceLineage, 'stock_name') ||
    null;
  return {
    id: row.id,
    symbol: row.symbol,
    name: displayName,
    market: row.market,
    instrumentType: row.instrument_type,
    positionSide: row.position_side || 'long',
    quantity,
    averageCost,
    marketPrice,
    marketValue,
    currency: row.currency,
    optionType: stringFromRecord(sourceLineage, 'option_type'),
    strike: numberFromRecord(sourceLineage, 'strike'),
    expiry: stringFromRecord(sourceLineage, 'expiry'),
    multiplier: numberFromRecord(sourceLineage, 'multiplier'),
    unrealizedPnlPct: resolveManualPnlPct(marketPrice, averageCost),
    sourceTier: row.source_tier || 'user_confirmed',
    sourceActionability: row.source_actionability || 'analysis_only',
    updatedAt: serializeDate(row.source_as_of) || serializeDate(row.updated_at) || new Date().toISOString(),
  };
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? (value as Record<string, unknown>) : {};
}

function stringFromRecord(record: Record<string, unknown>, key: string) {
  const value = record[key];
  return typeof value === 'string' && value.trim() ? value.trim() : null;
}

function numberFromRecord(record: Record<string, unknown>, key: string) {
  const value = record[key];
  if (value === null || value === undefined || value === '') return null;
  const numberValue = Number(value);
  return Number.isFinite(numberValue) ? numberValue : null;
}

function resolveManualMarketPrice(marketPrice: number | null, averageCost: number | null) {
  if (marketPrice !== null) return marketPrice;
  if (averageCost !== null && averageCost > 0) return averageCost;
  return null;
}

function resolveManualMarketValue(marketValue: number | null, quantity: number, marketPrice: number | null) {
  if (marketValue !== null) return marketValue;
  if (!Number.isFinite(quantity) || marketPrice === null) return null;
  return Number((quantity * marketPrice).toFixed(2));
}

function resolveManualPnlPct(marketPrice: number | null, averageCost: number | null) {
  if (marketPrice === null || averageCost === null || averageCost <= 0) return null;
  return ((marketPrice - averageCost) / averageCost) * 100;
}

async function rebuildManualBrokerSnapshot(tenantId: string) {
  const sql = sqlClient();
  const [brokerRows, sourceRows, positionRows] = await Promise.all([
    sql<{ id: string }[]>`
      SELECT id
      FROM public.broker_connections
      WHERE tenant_id = ${tenantId} AND connection_label = '手工录入'
      LIMIT 1
    `,
    sql<{ id: string }[]>`
      SELECT id
      FROM public.asset_sources
      WHERE tenant_id = ${tenantId} AND source_key = 'manual-webapp'
      LIMIT 1
    `,
    sql<{
      id: string;
      asset_source_id: string;
      instrument_type: string;
      symbol: string;
      name: string | null;
      market: string;
      exchange: string | null;
      position_side: string;
      quantity: string | number;
      average_cost: string | number | null;
      market_price: string | number | null;
      market_value: string | number | null;
      currency: string;
      source_quality: string;
      source_tier: string;
      source_actionability: string;
      source_as_of: string | Date | null;
      source_lineage: unknown;
      note: string | null;
      updated_at: string | Date;
    }[]>`
      SELECT *
      FROM public.webapp_manual_positions
      WHERE tenant_id = ${tenantId} AND position_status = 'open'
      ORDER BY updated_at DESC
    `,
  ]);

  const brokerConnectionId = brokerRows[0]?.id;
  const assetSourceId = sourceRows[0]?.id;
  if (!brokerConnectionId || !assetSourceId) {
    throw new Error('手工录入数据来源尚未初始化');
  }

  const now = new Date().toISOString();
  const snapshotRows = await sql<{ id: string }[]>`
    INSERT INTO public.broker_sync_snapshots (
      tenant_id, broker_connection_id, asset_source_id, sync_window_key, trigger,
      status, as_of, received_at, coverage, summary, source_quality
    )
    VALUES (
      ${tenantId},
      ${brokerConnectionId},
      ${assetSourceId},
      ${`manual-webapp-${tenantId}-${Date.now()}`},
      'webapp_action',
      'succeeded',
      ${now},
      ${now},
      ${sql.json({ source: 'webapp_manual_positions' })},
      ${sql.json({ positions: positionRows.length })},
      'user_confirmed'
    )
    RETURNING id
  `;
  const snapshotId = snapshotRows[0].id;

  for (const position of positionRows) {
    const marketPrice = resolveManualMarketPrice(toNumber(position.market_price), toNumber(position.average_cost));
    const marketValue = resolveManualMarketValue(toNumber(position.market_value), Number(position.quantity), marketPrice);
    await sql`
      INSERT INTO public.broker_position_snapshots (
        tenant_id, broker_sync_snapshot_id, asset_source_id, instrument_type, provider_symbol,
        market, exchange, position_side, quantity, average_cost, cost_basis, market_price,
        market_value, currency, source_quality, reconciliation_status, position_payload,
        source_lineage, as_of
      )
      VALUES (
        ${tenantId},
        ${snapshotId},
        ${position.asset_source_id},
        ${position.instrument_type},
        ${position.symbol},
        ${position.market},
        ${position.exchange},
        ${position.position_side},
        ${position.quantity},
        ${position.average_cost},
        ${position.average_cost === null ? null : Number(position.average_cost) * Number(position.quantity)},
        ${marketPrice},
        ${marketValue},
        ${position.currency},
        ${position.source_quality},
        'unverified',
        ${sql.json({
          name: position.name,
          note: position.note,
          source: 'webapp_manual_position',
          source_tier: position.source_tier,
          source_actionability: position.source_actionability,
        })},
        ${sql.json([
          {
            source: 'webapp_manual_positions',
            position_id: position.id,
            source_tier: position.source_tier,
            actionability: position.source_actionability,
            lineage: position.source_lineage || {},
          },
        ] as any)},
        ${serializeDate(position.source_as_of) || serializeDate(position.updated_at) || now}
      )
    `;
  }

  await sql`
    UPDATE public.asset_sources
    SET last_seen_at = now(), updated_at = now()
    WHERE id = ${assetSourceId}
  `;
  await sql`
    UPDATE public.broker_connections
    SET last_successful_sync_at = now(), updated_at = now()
    WHERE id = ${brokerConnectionId}
  `;
  return snapshotId;
}

export function getEmailDeliveryMode() {
  const configured = Boolean(process.env.SMTP_HOST && process.env.SMTP_FROM);
  return {
    configured,
    mode: configured ? 'smtp' : 'server_log',
    host: process.env.SMTP_HOST || '',
    from: process.env.SMTP_FROM || '',
  };
}
