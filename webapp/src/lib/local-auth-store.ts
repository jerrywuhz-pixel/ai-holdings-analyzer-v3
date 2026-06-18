import { pbkdf2Sync, randomBytes, randomInt, timingSafeEqual, createHmac } from 'crypto';
import postgres from 'postgres';
import type { AppUser } from '@/lib/supabase';

const PASSWORD_ITERATIONS = 120_000;
const PASSWORD_KEY_LENGTH = 32;
const PASSWORD_DIGEST = 'sha256';
const DEFAULT_TTL_MINUTES = 30;
const DEFAULT_MAX_ATTEMPTS = 5;

declare global {
  // eslint-disable-next-line no-var
  var __aiHoldingsLocalAuthSql: ReturnType<typeof postgres> | undefined;
}

export interface LocalRegistrationResult {
  email: string;
  code: string;
  expiresAt: string;
}

function normalizeEmail(email: string) {
  return email.trim().toLowerCase();
}

function getDatabaseUrl() {
  return process.env.WEBAPP_DATABASE_URL || process.env.DATABASE_URL || '';
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

function authSecret() {
  return (
    process.env.AUTH_SESSION_SECRET ||
    process.env.LOCAL_AUTH_PASSWORD ||
    'ai-holdings-local-auth-development-secret'
  );
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

function hashCode(email: string, code: string) {
  return createHmac('sha256', authSecret()).update(`${normalizeEmail(email)}:${code}`).digest('hex');
}

function generateCode() {
  return String(randomInt(100000, 1000000));
}

export async function ensureLocalAuthSchema() {
  const sql = getSql();
  await sql`
    CREATE TABLE IF NOT EXISTS public.local_auth_users (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
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
  await sql`
    CREATE TABLE IF NOT EXISTS public.local_auth_email_verifications (
      email text PRIMARY KEY,
      password_salt text NOT NULL,
      password_hash text NOT NULL,
      display_name text NOT NULL,
      role text NOT NULL DEFAULT 'user' CHECK (role IN ('user', 'admin')),
      code_hash text NOT NULL,
      expires_at timestamptz NOT NULL,
      attempts integer NOT NULL DEFAULT 0,
      created_at timestamptz NOT NULL DEFAULT now(),
      updated_at timestamptz NOT NULL DEFAULT now()
    )
  `;
  await sql`
    CREATE INDEX IF NOT EXISTS idx_local_auth_email_verifications_expires
      ON public.local_auth_email_verifications(expires_at)
  `;
}

export function localRegistrationEnabled() {
  return process.env.LOCAL_AUTH_REGISTRATION_ENABLED !== 'false';
}

export async function createLocalRegistration({
  email,
  password,
  displayName,
}: {
  email: string;
  password: string;
  displayName?: string;
}): Promise<LocalRegistrationResult> {
  if (!localRegistrationEnabled()) {
    throw new Error('本地注册暂未开启');
  }
  const normalizedEmail = normalizeEmail(email);
  if (password.length < 8) {
    throw new Error('密码至少需要 8 位');
  }

  await ensureLocalAuthSchema();
  const sql = getSql();
  const existing = await sql<{ id: string }[]>`
    SELECT id FROM public.local_auth_users WHERE email = ${normalizedEmail} LIMIT 1
  `;
  if (existing.length > 0) {
    throw new Error('这个邮箱已经注册，请直接登录');
  }

  const code = generateCode();
  const { salt, hash } = hashPassword(password);
  const ttlMinutes = Number(process.env.AUTH_VERIFICATION_TTL_MINUTES || DEFAULT_TTL_MINUTES);
  const expiresAt = new Date(Date.now() + ttlMinutes * 60 * 1000).toISOString();
  const name = displayName?.trim() || normalizedEmail.split('@')[0] || '投资用户';

  await sql`
    INSERT INTO public.local_auth_email_verifications (
      email, password_salt, password_hash, display_name, role, code_hash, expires_at, attempts
    )
    VALUES (
      ${normalizedEmail}, ${salt}, ${hash}, ${name}, 'user', ${hashCode(normalizedEmail, code)}, ${expiresAt}, 0
    )
    ON CONFLICT (email) DO UPDATE SET
      password_salt = EXCLUDED.password_salt,
      password_hash = EXCLUDED.password_hash,
      display_name = EXCLUDED.display_name,
      role = EXCLUDED.role,
      code_hash = EXCLUDED.code_hash,
      expires_at = EXCLUDED.expires_at,
      attempts = 0,
      updated_at = now()
  `;

  return { email: normalizedEmail, code, expiresAt };
}

export async function resendLocalRegistrationCode(email: string): Promise<LocalRegistrationResult> {
  if (!localRegistrationEnabled()) {
    throw new Error('本地注册暂未开启');
  }

  const normalizedEmail = normalizeEmail(email);
  await ensureLocalAuthSchema();
  const sql = getSql();
  const rows = await sql<{ email: string }[]>`
    SELECT email
    FROM public.local_auth_email_verifications
    WHERE email = ${normalizedEmail}
    LIMIT 1
  `;

  if (!rows[0]) {
    throw new Error('没有待确认的注册申请，请重新注册');
  }

  const code = generateCode();
  const ttlMinutes = Number(process.env.AUTH_VERIFICATION_TTL_MINUTES || DEFAULT_TTL_MINUTES);
  const expiresAt = new Date(Date.now() + ttlMinutes * 60 * 1000).toISOString();

  await sql`
    UPDATE public.local_auth_email_verifications
    SET
      code_hash = ${hashCode(normalizedEmail, code)},
      expires_at = ${expiresAt},
      attempts = 0,
      updated_at = now()
    WHERE email = ${normalizedEmail}
  `;

  return { email: normalizedEmail, code, expiresAt };
}

export async function verifyLocalRegistration({
  email,
  code,
}: {
  email: string;
  code: string;
}): Promise<Omit<AppUser, 'provider'>> {
  const normalizedEmail = normalizeEmail(email);
  const normalizedCode = code.trim();
  await ensureLocalAuthSchema();
  const sql = getSql();
  const rows = await sql<{
    email: string;
    password_salt: string;
    password_hash: string;
    display_name: string;
    role: 'user' | 'admin';
    code_hash: string;
    expires_at: string;
    attempts: number;
  }[]>`
    SELECT email, password_salt, password_hash, display_name, role, code_hash, expires_at, attempts
    FROM public.local_auth_email_verifications
    WHERE email = ${normalizedEmail}
    LIMIT 1
  `;

  const pending = rows[0];
  if (!pending) {
    throw new Error('验证码不存在或已失效，请重新注册');
  }

  if (new Date(pending.expires_at).getTime() < Date.now()) {
    await sql`DELETE FROM public.local_auth_email_verifications WHERE email = ${normalizedEmail}`;
    throw new Error('验证码已过期，请重新注册');
  }

  const maxAttempts = Number(process.env.AUTH_VERIFICATION_MAX_ATTEMPTS || DEFAULT_MAX_ATTEMPTS);
  if (pending.attempts >= maxAttempts) {
    await sql`DELETE FROM public.local_auth_email_verifications WHERE email = ${normalizedEmail}`;
    throw new Error('验证码尝试次数过多，请重新注册');
  }

  if (pending.code_hash !== hashCode(normalizedEmail, normalizedCode)) {
    await sql`
      UPDATE public.local_auth_email_verifications
      SET attempts = attempts + 1, updated_at = now()
      WHERE email = ${normalizedEmail}
    `;
    throw new Error('验证码不正确');
  }

  const inserted = await sql<{ id: string; email: string; display_name: string; role: 'user' | 'admin' }[]>`
    INSERT INTO public.local_auth_users (email, password_salt, password_hash, display_name, role, email_verified_at)
    VALUES (
      ${normalizedEmail},
      ${pending.password_salt},
      ${pending.password_hash},
      ${pending.display_name},
      ${pending.role},
      now()
    )
    ON CONFLICT (email) DO UPDATE SET
      password_salt = EXCLUDED.password_salt,
      password_hash = EXCLUDED.password_hash,
      display_name = EXCLUDED.display_name,
      role = EXCLUDED.role,
      email_verified_at = now(),
      updated_at = now()
    RETURNING id, email, display_name, role
  `;
  await sql`DELETE FROM public.local_auth_email_verifications WHERE email = ${normalizedEmail}`;

  const user = inserted[0];
  return {
    id: user.id,
    email: user.email,
    name: user.display_name,
    role: user.role,
  };
}

export async function validateLocalDbCredentials(email: string, password: string): Promise<Omit<AppUser, 'provider'> | null> {
  if (!getDatabaseUrl()) {
    return null;
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
    WHERE email = ${normalizeEmail(email)}
    LIMIT 1
  `;
  const user = rows[0];
  if (!user || !verifyPassword(password, user.password_salt, user.password_hash)) {
    return null;
  }

  return {
    id: user.id,
    email: user.email,
    name: user.display_name,
    role: user.role,
  };
}
