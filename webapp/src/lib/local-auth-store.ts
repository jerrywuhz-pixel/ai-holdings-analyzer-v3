import { pbkdf2Sync, randomBytes, timingSafeEqual } from 'crypto';
import postgres from 'postgres';
import type { AppUser } from '@/lib/supabase';

const PASSWORD_ITERATIONS = 120_000;
const PASSWORD_KEY_LENGTH = 32;
const PASSWORD_DIGEST = 'sha256';

declare global {
  // eslint-disable-next-line no-var
  var __aiHoldingsLocalAuthSql: ReturnType<typeof postgres> | undefined;
}

export interface LocalRegistrationResult {
  email: string;
  code: string;
  expiresAt: string;
}

export interface AssignedLocalUser {
  id: string;
  loginName: string;
  email: string;
  displayName: string;
  role: 'user' | 'admin';
  updatedAt: string;
}

export interface WechatBoundAccountForAdmin {
  tenantId: string;
  displayName: string | null;
  accountStatus: string | null;
  channelAccountId: string | null;
  openclawAccountId: string | null;
  accountLabel: string | null;
  humanName: string | null;
  bindingStatus: string | null;
  boundAt: string | null;
  lastSeenAt: string | null;
  loginName: string | null;
  loginEmail: string | null;
  loginDisplayName: string | null;
  loginRole: 'user' | 'admin' | null;
  loginUpdatedAt: string | null;
}

export interface ChangeLocalPasswordResult {
  ok: boolean;
  error?: string;
}

function normalizeLoginName(loginName: string) {
  return loginName.trim().toLowerCase();
}

function getDatabaseUrl() {
  return process.env.WEBAPP_DATABASE_URL || process.env.DATABASE_URL || '';
}

export function localAuthDatabaseConfigured() {
  return Boolean(getDatabaseUrl());
}

function localAuthSchemaRepairEnabled() {
  return (process.env.WEBAPP_RUNTIME_SCHEMA_REPAIR || 'true').trim().toLowerCase() !== 'false';
}

function getSql() {
  const databaseUrl = getDatabaseUrl();
  if (!databaseUrl) {
    throw new Error('本地注册需要配置 DATABASE_URL 或 WEBAPP_DATABASE_URL');
  }

  if (!globalThis.__aiHoldingsLocalAuthSql) {
    globalThis.__aiHoldingsLocalAuthSql = postgres(databaseUrl, {
      max: 3,
      idle_timeout: 20,
      connect_timeout: 10,
      prepare: false,
    });
  }

  return globalThis.__aiHoldingsLocalAuthSql;
}

function hashPassword(password: string, salt = randomBytes(16).toString('hex')) {
  const hash = pbkdf2Sync(password, salt, PASSWORD_ITERATIONS, PASSWORD_KEY_LENGTH, PASSWORD_DIGEST).toString('hex');
  return { salt, hash };
}

function verifyPassword(password: string, salt: string, expectedHash: string) {
  const { hash } = hashPassword(password, salt);
  const left = Buffer.from(hash, 'hex');
  const right = Buffer.from(expectedHash, 'hex');
  return left.length === right.length && timingSafeEqual(left, right);
}

function envBootstrapUser(loginName: string, password: string): Omit<AppUser, 'provider'> | null {
  if (process.env.LOCAL_AUTH_ENABLED === 'false') {
    return null;
  }

  const configuredPassword = process.env.LOCAL_AUTH_PASSWORD || '';
  if (!configuredPassword || password !== configuredPassword) {
    return null;
  }

  const configuredLoginName = normalizeLoginName(process.env.LOCAL_AUTH_LOGIN_NAME || process.env.LOCAL_AUTH_EMAIL || '');
  const configuredDisplayName = normalizeLoginName(process.env.LOCAL_AUTH_DISPLAY_NAME || '');
  const normalizedLoginName = normalizeLoginName(loginName);
  if (normalizedLoginName !== configuredLoginName && normalizedLoginName !== configuredDisplayName) {
    return null;
  }

  return {
    id: process.env.LOCAL_AUTH_USER_ID || '00000000-0000-0000-0000-000000000000',
    email: process.env.LOCAL_AUTH_EMAIL || configuredLoginName,
    name: process.env.LOCAL_AUTH_DISPLAY_NAME || configuredLoginName,
    role: process.env.LOCAL_AUTH_ROLE === 'user' ? 'user' : 'admin',
  };
}

export async function ensureLocalAuthSchema() {
  if (!localAuthSchemaRepairEnabled()) {
    return;
  }

  const sql = getSql();
  await sql`
    CREATE TABLE IF NOT EXISTS public.local_auth_users (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      login_name text UNIQUE,
      email text NOT NULL UNIQUE,
      password_salt text NOT NULL,
      password_hash text NOT NULL,
      display_name text NOT NULL,
      role text NOT NULL DEFAULT 'user' CHECK (role IN ('user', 'admin')),
      email_verified_at timestamptz NOT NULL DEFAULT now(),
      created_at timestamptz NOT NULL DEFAULT now(),
      updated_at timestamptz NOT NULL DEFAULT now()
    )
  `;
  await sql`ALTER TABLE public.local_auth_users ADD COLUMN IF NOT EXISTS login_name text`;
  await sql`UPDATE public.local_auth_users SET login_name = email WHERE login_name IS NULL`;
  await sql`CREATE UNIQUE INDEX IF NOT EXISTS local_auth_users_login_name_key ON public.local_auth_users (login_name)`;
}

export async function upsertAssignedLocalUser({
  tenantId,
  loginName,
  email,
  password,
  displayName,
  role = 'user',
}: {
  tenantId: string;
  loginName: string;
  email?: string;
  password: string;
  displayName?: string;
  role?: 'user' | 'admin';
}): Promise<AssignedLocalUser> {
  const normalizedLoginName = normalizeLoginName(loginName);
  const normalizedEmail = normalizeLoginName(email || loginName);
  const normalizedTenantId = tenantId.trim();
  if (!normalizedTenantId) {
    throw new Error('缺少绑定账号 tenant_id');
  }
  if (!normalizedLoginName) {
    throw new Error('请输入登录名');
  }
  if (password.length < 6) {
    throw new Error('密码至少需要 6 位');
  }

  await ensureLocalAuthSchema();
  const sql = getSql();
  const { salt, hash } = hashPassword(password);
  const name = displayName?.trim() || normalizedLoginName || 'Hermes 用户';
  const existingByLogin = await sql<{ id: string }[]>`
    SELECT id
    FROM public.local_auth_users
    WHERE login_name = ${normalizedLoginName}
       OR email = ${normalizedLoginName}
       OR email = ${normalizedEmail}
    LIMIT 1
  `;
  if (existingByLogin[0] && existingByLogin[0].id !== normalizedTenantId) {
    throw new Error('该登录名已分配给其他微信账号，请换一个登录名。');
  }

  const existingById = await sql<{ id: string }[]>`
    SELECT id FROM public.local_auth_users WHERE id = ${normalizedTenantId} LIMIT 1
  `;
  const rows = existingById[0]
    ? await sql<{
        id: string;
        login_name: string;
        email: string;
        display_name: string;
        role: 'user' | 'admin';
        updated_at: string | Date;
      }[]>`
        UPDATE public.local_auth_users
        SET
          login_name = ${normalizedLoginName},
          email = ${normalizedEmail},
          password_salt = ${salt},
          password_hash = ${hash},
          display_name = ${name},
          role = ${role},
          email_verified_at = now(),
          updated_at = now()
        WHERE id = ${normalizedTenantId}
        RETURNING id, login_name, email, display_name, role, updated_at
      `
    : await sql<{
    id: string;
    login_name: string;
    email: string;
    display_name: string;
    role: 'user' | 'admin';
    updated_at: string | Date;
  }[]>`
    INSERT INTO public.local_auth_users (id, login_name, email, password_salt, password_hash, display_name, role, email_verified_at)
    VALUES (
      ${normalizedTenantId},
      ${normalizedLoginName},
      ${normalizedEmail},
      ${salt},
      ${hash},
      ${name},
      ${role},
      now()
    )
    RETURNING id, login_name, email, display_name, role, updated_at
  `;

  const user = rows[0];
  return {
    id: user.id,
    loginName: user.login_name,
    email: user.email,
    displayName: user.display_name,
    role: user.role,
    updatedAt: serializeDate(user.updated_at) || new Date().toISOString(),
  };
}

export async function validateLocalDbCredentials(loginName: string, password: string): Promise<Omit<AppUser, 'provider'> | null> {
  if (!getDatabaseUrl()) {
    return envBootstrapUser(loginName, password);
  }

  await ensureLocalAuthSchema();
  const sql = getSql();
  const rows = await sql<{
    id: string;
    email: string;
    password_salt: string;
    password_hash: string;
    display_name: string;
    role: 'user' | 'admin';
  }[]>`
    SELECT id, email, password_salt, password_hash, display_name, role
    FROM public.local_auth_users
    WHERE login_name = ${normalizeLoginName(loginName)}
       OR email = ${normalizeLoginName(loginName)}
    LIMIT 1
  `;
  const user = rows[0];
  if (!user || !verifyPassword(password, user.password_salt, user.password_hash)) {
    return envBootstrapUser(loginName, password);
  }

  return {
    id: user.id,
    email: user.email,
    name: user.display_name,
    role: user.role,
  };
}

export async function changeLocalUserPassword({
  userId,
  currentPassword,
  newPassword,
}: {
  userId: string;
  currentPassword: string;
  newPassword: string;
}): Promise<ChangeLocalPasswordResult> {
  if (!getDatabaseUrl()) {
    return { ok: false, error: '当前环境不支持修改本地账号密码' };
  }
  if (newPassword.length < 6) {
    return { ok: false, error: '新密码至少需要 6 位' };
  }
  if (currentPassword === newPassword) {
    return { ok: false, error: '新密码不能与当前密码相同' };
  }

  await ensureLocalAuthSchema();
  const sql = getSql();
  const rows = await sql<{
    id: string;
    password_salt: string;
    password_hash: string;
  }[]>`
    SELECT id, password_salt, password_hash
    FROM public.local_auth_users
    WHERE id = ${userId}
    LIMIT 1
  `;
  const user = rows[0];
  if (!user) {
    return { ok: false, error: '账号不存在，请联系管理员重新分配账号' };
  }
  if (!verifyPassword(currentPassword, user.password_salt, user.password_hash)) {
    return { ok: false, error: '当前密码不正确' };
  }

  const { salt, hash } = hashPassword(newPassword);
  await sql`
    UPDATE public.local_auth_users
    SET password_salt = ${salt},
        password_hash = ${hash},
        updated_at = now()
    WHERE id = ${userId}
  `;
  return { ok: true };
}

export async function getLocalUserById(userId: string): Promise<Omit<AppUser, 'provider'> | null> {
  if (!getDatabaseUrl()) {
    return null;
  }

  await ensureLocalAuthSchema();
  const sql = getSql();
  const rows = await sql<{
    id: string;
    email: string;
    display_name: string;
    role: 'user' | 'admin';
  }[]>`
    SELECT id, email, display_name, role
    FROM public.local_auth_users
    WHERE id = ${userId}
    LIMIT 1
  `;
  const user = rows[0];
  if (!user) return null;

  return {
    id: user.id,
    email: user.email,
    name: user.display_name,
    role: user.role,
  };
}

export async function listWechatBoundAccountsForAdmin(): Promise<WechatBoundAccountForAdmin[]> {
  if (!getDatabaseUrl()) {
    return [];
  }

  await ensureLocalAuthSchema();
  const sql = getSql();
  const rows = await sql<{
    tenant_id: string;
    display_name: string | null;
    account_status: string | null;
    channel_account_id: string | null;
    openclaw_account_id: string | null;
    account_label: string | null;
    human_name: string | null;
    binding_status: string | null;
    bound_at: string | Date | null;
    last_seen_at: string | Date | null;
    login_name: string | null;
    login_email: string | null;
    login_display_name: string | null;
    login_role: 'user' | 'admin' | null;
    login_updated_at: string | Date | null;
  }[]>`
    SELECT
      cb.tenant_id,
      ta.display_name,
      ta.account_status,
      cb.channel_account_id,
      cb.openclaw_account_id,
      cb.account_label,
      cb.human_name,
      cb.binding_status,
      cb.bound_at,
      cb.last_seen_at,
      lau.login_name,
      lau.email AS login_email,
      lau.display_name AS login_display_name,
      lau.role AS login_role,
      lau.updated_at AS login_updated_at
    FROM public.channel_bindings cb
    LEFT JOIN public.tenant_accounts ta ON ta.tenant_id = cb.tenant_id
    LEFT JOIN public.local_auth_users lau ON lau.id = cb.tenant_id
    WHERE cb.channel IN ('hermes_wechat', 'openclaw_wechat')
      AND cb.binding_status = 'active'
    ORDER BY cb.last_seen_at DESC NULLS LAST, cb.bound_at DESC NULLS LAST
  `;

  return rows.map((row) => ({
    tenantId: row.tenant_id,
    displayName: row.display_name,
    accountStatus: row.account_status,
    channelAccountId: row.channel_account_id,
    openclawAccountId: row.openclaw_account_id,
    accountLabel: row.account_label,
    humanName: row.human_name,
    bindingStatus: row.binding_status,
    boundAt: serializeDate(row.bound_at),
    lastSeenAt: serializeDate(row.last_seen_at),
    loginName: row.login_name,
    loginEmail: row.login_email,
    loginDisplayName: row.login_display_name,
    loginRole: row.login_role,
    loginUpdatedAt: serializeDate(row.login_updated_at),
  }));
}

function serializeDate(value: unknown) {
  if (value instanceof Date) return value.toISOString();
  return value ? String(value) : null;
}
