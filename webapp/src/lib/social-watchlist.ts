import postgres from 'postgres';

declare global {
  // eslint-disable-next-line no-var
  var __aiHoldingsSocialWatchlistSql: ReturnType<typeof postgres> | undefined;
}

export type SocialPlatform = 'twitter' | 'xhs' | 'youtube';

export interface SocialWatchAccount {
  id: string;
  tenantId: string | null;
  platform: SocialPlatform;
  handle: string;
  displayName: string | null;
  url: string | null;
  channelUrl: string | null;
  userId: string | null;
  xsecToken: string | null;
  symbols: string[];
  priority: number;
  isActive: boolean;
  notes: string | null;
  updatedAt: string;
}

export interface SocialWatchAccountInput {
  id?: string;
  tenantId?: string | null;
  platform: string;
  handle: string;
  displayName?: string | null;
  url?: string | null;
  channelUrl?: string | null;
  userId?: string | null;
  xsecToken?: string | null;
  symbols?: string[];
  priority?: number;
  isActive?: boolean;
  notes?: string | null;
}

function databaseUrl() {
  return process.env.WEBAPP_DATABASE_URL || process.env.DATABASE_URL || '';
}

export function socialWatchlistDatabaseConfigured() {
  return Boolean(databaseUrl());
}

function sqlClient() {
  const url = databaseUrl();
  if (!url) {
    throw new Error('社媒关注清单需要配置 DATABASE_URL 或 WEBAPP_DATABASE_URL');
  }
  if (!globalThis.__aiHoldingsSocialWatchlistSql) {
    globalThis.__aiHoldingsSocialWatchlistSql = postgres(url, {
      max: 2,
      idle_timeout: 20,
      connect_timeout: 5,
    });
  }
  return globalThis.__aiHoldingsSocialWatchlistSql;
}

export function normalizeSocialPlatform(value: string): SocialPlatform {
  const normalized = value.trim().toLowerCase();
  if (normalized === 'x' || normalized === 'twitter') return 'twitter';
  if (normalized === 'xiaohongshu' || normalized === 'xhs') return 'xhs';
  if (normalized === 'yt' || normalized === 'youtube') return 'youtube';
  throw new Error('平台必须是 X/Twitter、小红书或 YouTube');
}

export function normalizeSymbols(values: string[]) {
  const symbols = values
    .flatMap((value) => value.split(/[,\s，、]+/))
    .map((value) => value.trim().toUpperCase())
    .filter(Boolean);
  return Array.from(new Set(symbols.length ? symbols : ['*']));
}

function cleanOptional(value: string | null | undefined) {
  const trimmed = String(value ?? '').trim();
  return trimmed || null;
}

function normalizeInput(input: SocialWatchAccountInput) {
  const raw = input as SocialWatchAccountInput & Record<string, unknown>;
  const platform = normalizeSocialPlatform(input.platform);
  const handle = String(input.handle || '').trim().replace(/^@+/, '');
  if (!handle) {
    throw new Error('账号标识 handle 必填');
  }
  const symbols = normalizeSymbols(input.symbols || []);
  const channelUrl = cleanOptional(input.channelUrl ?? (raw.channel_url as string | undefined));
  const userId = cleanOptional(input.userId ?? (raw.user_id as string | undefined));
  const xsecToken = cleanOptional(input.xsecToken ?? (raw.xsec_token as string | undefined));
  if (platform === 'youtube' && !channelUrl) {
    throw new Error('YouTube 账号必须填写 channel_url');
  }
  if (platform === 'xhs' && (!userId || !xsecToken)) {
    throw new Error('小红书账号必须填写 user_id 和 xsec_token');
  }
  return {
    id: cleanOptional(input.id),
    tenantId: cleanOptional(input.tenantId ?? (raw.tenant_id as string | undefined)),
    platform,
    handle,
    displayName: cleanOptional(input.displayName ?? (raw.display_name as string | undefined)),
    url: cleanOptional(input.url),
    channelUrl,
    userId,
    xsecToken,
    symbols,
    priority: Math.max(0, Math.min(9999, Number.isFinite(input.priority) ? Number(input.priority) : 100)),
    isActive: input.isActive !== false,
    notes: cleanOptional(input.notes),
  };
}

export async function ensureSocialWatchlistSchema() {
  const sql = sqlClient();
  await sql`CREATE EXTENSION IF NOT EXISTS pgcrypto`;
  await sql`
    CREATE TABLE IF NOT EXISTS public.social_watch_accounts (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      tenant_id UUID NULL,
      platform TEXT NOT NULL CHECK (platform IN ('twitter', 'xhs', 'youtube')),
      handle TEXT NOT NULL,
      display_name TEXT,
      url TEXT,
      channel_url TEXT,
      user_id TEXT,
      xsec_token TEXT,
      symbols TEXT[] NOT NULL DEFAULT ARRAY['*']::TEXT[],
      priority INTEGER NOT NULL DEFAULT 100,
      is_active BOOLEAN NOT NULL DEFAULT TRUE,
      notes TEXT,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
  `;
  await sql`
    CREATE INDEX IF NOT EXISTS social_watch_accounts_lookup_idx
    ON public.social_watch_accounts (is_active, platform, priority, handle)
  `;
}

function rowToAccount(row: Record<string, any>): SocialWatchAccount {
  return {
    id: row.id,
    tenantId: row.tenant_id ?? null,
    platform: row.platform,
    handle: row.handle,
    displayName: row.display_name ?? null,
    url: row.url ?? null,
    channelUrl: row.channel_url ?? null,
    userId: row.user_id ?? null,
    xsecToken: row.xsec_token ?? null,
    symbols: Array.isArray(row.symbols) ? row.symbols : ['*'],
    priority: Number(row.priority ?? 100),
    isActive: Boolean(row.is_active),
    notes: row.notes ?? null,
    updatedAt: row.updated_at ? new Date(row.updated_at).toISOString() : '',
  };
}

export async function listSocialWatchAccountsForAdmin() {
  await ensureSocialWatchlistSchema();
  const sql = sqlClient();
  const rows = await sql<Record<string, any>[]>`
    SELECT *
    FROM public.social_watch_accounts
    ORDER BY is_active DESC, priority ASC, platform ASC, handle ASC
  `;
  return rows.map(rowToAccount);
}

export async function getSocialWatchAccount(id: string) {
  await ensureSocialWatchlistSchema();
  const sql = sqlClient();
  const rows = await sql<Record<string, any>[]>`
    SELECT *
    FROM public.social_watch_accounts
    WHERE id = ${id}
    LIMIT 1
  `;
  return rows[0] ? rowToAccount(rows[0]) : null;
}

export async function saveSocialWatchAccount(input: SocialWatchAccountInput) {
  await ensureSocialWatchlistSchema();
  const account = normalizeInput(input);
  const sql = sqlClient();
  if (account.id) {
    const rows = await sql<Record<string, any>[]>`
      UPDATE public.social_watch_accounts
      SET
        tenant_id = ${account.tenantId},
        platform = ${account.platform},
        handle = ${account.handle},
        display_name = ${account.displayName},
        url = ${account.url},
        channel_url = ${account.channelUrl},
        user_id = ${account.userId},
        xsec_token = ${account.xsecToken},
        symbols = ${account.symbols},
        priority = ${account.priority},
        is_active = ${account.isActive},
        notes = ${account.notes},
        updated_at = now()
      WHERE id = ${account.id}
      RETURNING *
    `;
    if (!rows[0]) throw new Error('未找到要更新的关注账号');
    return rowToAccount(rows[0]);
  }
  const rows = await sql<Record<string, any>[]>`
    INSERT INTO public.social_watch_accounts (
      tenant_id, platform, handle, display_name, url, channel_url, user_id,
      xsec_token, symbols, priority, is_active, notes
    )
    VALUES (
      ${account.tenantId}, ${account.platform}, ${account.handle}, ${account.displayName},
      ${account.url}, ${account.channelUrl}, ${account.userId}, ${account.xsecToken},
      ${account.symbols}, ${account.priority}, ${account.isActive}, ${account.notes}
    )
    RETURNING *
  `;
  return rowToAccount(rows[0]);
}

export async function deleteSocialWatchAccount(id: string) {
  await ensureSocialWatchlistSchema();
  const sql = sqlClient();
  await sql`DELETE FROM public.social_watch_accounts WHERE id = ${id}`;
}

export async function importSocialWatchAccountsJson(raw: string) {
  let payload: unknown;
  try {
    payload = JSON.parse(raw);
  } catch {
    throw new Error('JSON 格式不正确');
  }
  const rows = Array.isArray(payload)
    ? payload
    : typeof payload === 'object' && payload !== null && Array.isArray((payload as any).accounts)
      ? (payload as any).accounts
      : null;
  if (!rows) {
    throw new Error('JSON 需要是数组，或包含 accounts 数组');
  }
  const saved = [];
  for (const row of rows) {
    if (typeof row !== 'object' || row === null) continue;
    saved.push(await saveSocialWatchAccount(row as SocialWatchAccountInput));
  }
  return saved;
}

export function maskSecret(value: string | null) {
  if (!value) return '-';
  if (value.length <= 10) return '••••';
  return `${value.slice(0, 4)}••••${value.slice(-4)}`;
}
