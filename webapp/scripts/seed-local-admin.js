const { existsSync, readFileSync } = require('fs');
const { resolve } = require('path');
const { pbkdf2Sync, randomBytes, randomUUID } = require('crypto');
const postgres = require('postgres');

const repoRoot = resolve(__dirname, '..', '..');

function loadEnvFile(path) {
  if (!existsSync(path)) return;
  for (const line of readFileSync(path, 'utf8').split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith('#') || !trimmed.includes('=')) continue;
    const index = trimmed.indexOf('=');
    const key = trimmed.slice(0, index).trim();
    let value = trimmed.slice(index + 1).trim();
    if (
      (value.startsWith('"') && value.endsWith('"')) ||
      (value.startsWith("'") && value.endsWith("'"))
    ) {
      value = value.slice(1, -1);
    }
    if (!process.env[key]) {
      process.env[key] = value;
    }
  }
}

loadEnvFile(resolve(repoRoot, '.env.server'));
loadEnvFile(resolve(repoRoot, '.env'));
loadEnvFile(resolve(repoRoot, 'webapp', '.env.local'));
loadEnvFile(resolve(repoRoot, 'webapp', '.env'));

function databaseUrl() {
  if (process.env.WEBAPP_DATABASE_URL) return process.env.WEBAPP_DATABASE_URL;
  if (process.env.DATABASE_URL) return process.env.DATABASE_URL;

  const user = process.env.POSTGRES_USER || 'postgres';
  const password = process.env.POSTGRES_PASSWORD || 'postgres';
  const configuredHost = process.env.POSTGRES_HOST || '127.0.0.1';
  const host = configuredHost === 'host.docker.internal' ? '127.0.0.1' : configuredHost;
  const port = process.env.POSTGRES_PORT || process.env.POSTGRES_HOST_PORT || '5432';
  const database = process.env.POSTGRES_DB || 'ai_holdings';
  return `postgresql://${encodeURIComponent(user)}:${encodeURIComponent(password)}@${host}:${port}/${database}`;
}

function normalize(value) {
  return String(value || '').trim().toLowerCase();
}

function hashPassword(password, salt = randomBytes(16).toString('hex')) {
  const hash = pbkdf2Sync(password, salt, 120000, 32, 'sha256').toString('hex');
  return { salt, hash };
}

async function main() {
  const loginName = normalize(process.env.LOCAL_AUTH_LOGIN_NAME || process.env.LOCAL_AUTH_EMAIL || 'jerrywu');
  const email = normalize(process.env.LOCAL_AUTH_EMAIL || loginName);
  const password = process.env.LOCAL_AUTH_PASSWORD || '123456';
  const displayName = String(process.env.LOCAL_AUTH_DISPLAY_NAME || loginName || 'Hermes Admin').trim();
  const role = process.env.LOCAL_AUTH_ROLE === 'user' ? 'user' : 'admin';
  const configuredUserId = normalize(process.env.LOCAL_AUTH_USER_ID);

  if (!loginName) throw new Error('LOCAL_AUTH_LOGIN_NAME is required');
  if (password.length < 6) throw new Error('LOCAL_AUTH_PASSWORD must be at least 6 characters');

  const sql = postgres(databaseUrl(), {
    max: 1,
    idle_timeout: 5,
    connect_timeout: 10,
    prepare: false,
  });
  const { salt, hash } = hashPassword(password);

  try {
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

    const existing = await sql`
      SELECT id
      FROM public.local_auth_users
      WHERE login_name = ${loginName}
         OR email = ${loginName}
         OR email = ${email}
      LIMIT 1
    `;
    const id =
      existing[0]?.id ||
      (configuredUserId && configuredUserId !== '00000000-0000-0000-0000-000000000000'
        ? configuredUserId
        : randomUUID());

    const rows = await sql`
      INSERT INTO public.local_auth_users (
        id,
        login_name,
        email,
        password_salt,
        password_hash,
        display_name,
        role,
        email_verified_at,
        created_at,
        updated_at
      )
      VALUES (${id}, ${loginName}, ${email}, ${salt}, ${hash}, ${displayName}, ${role}, now(), now(), now())
      ON CONFLICT (id) DO UPDATE SET
        login_name = EXCLUDED.login_name,
        email = EXCLUDED.email,
        password_salt = EXCLUDED.password_salt,
        password_hash = EXCLUDED.password_hash,
        display_name = EXCLUDED.display_name,
        role = EXCLUDED.role,
        email_verified_at = now(),
        updated_at = now()
      RETURNING id, login_name, display_name, role, updated_at
    `;

    console.log(JSON.stringify(rows[0]));
  } finally {
    await sql.end();
  }
}

main().catch((error) => {
  console.error(error.message);
  process.exit(1);
});
