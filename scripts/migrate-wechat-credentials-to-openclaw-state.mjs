#!/usr/bin/env node
import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';

const AES_PREFIX = 'aes-256-gcm:v1:';
const LOCAL_DEV_PREFIX = 'local-dev:v1:';

const inputPath = process.env.WECHAT_CREDENTIALS_CSV || '/tmp/wechat-creds.csv';
const stateDir = process.env.OPENCLAW_STATE_DIR || '/state';
const encryptionSecret = process.env.ONBOARDING_CREDENTIAL_ENCRYPTION_KEY || '';
const fieldEncoding = (process.env.WECHAT_CREDENTIALS_ENCODING || 'base64').trim().toLowerCase();

function decodeField(value) {
  if (fieldEncoding === 'hex') {
    return Buffer.from(value || '', 'hex').toString('utf8').trim();
  }
  return Buffer.from(value || '', 'base64').toString('utf8').trim();
}

function normalizeAccountId(value) {
  return String(value || '')
    .trim()
    .replace(/@/g, '-')
    .replace(/\./g, '-')
    .replace(/[^A-Za-z0-9_-]/g, '-');
}

function decryptCredential(value) {
  if (value.startsWith(LOCAL_DEV_PREFIX)) {
    return Buffer.from(value.slice(LOCAL_DEV_PREFIX.length), 'base64').toString('utf8');
  }

  if (!value.startsWith(AES_PREFIX)) {
    throw new Error('Unsupported credential ciphertext format');
  }

  if (!encryptionSecret) {
    throw new Error('ONBOARDING_CREDENTIAL_ENCRYPTION_KEY is required to decrypt credentials');
  }

  const [ivText, tagText, encryptedText] = value.slice(AES_PREFIX.length).split(':');
  if (!ivText || !tagText || !encryptedText) {
    throw new Error('Invalid credential ciphertext');
  }

  const key = crypto.createHash('sha256').update(encryptionSecret).digest();
  const decipher = crypto.createDecipheriv('aes-256-gcm', key, Buffer.from(ivText, 'base64url'));
  decipher.setAuthTag(Buffer.from(tagText, 'base64url'));
  return Buffer.concat([
    decipher.update(Buffer.from(encryptedText, 'base64url')),
    decipher.final(),
  ]).toString('utf8');
}

function writeJson(filePath, value, mode = 0o600) {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  fs.writeFileSync(filePath, JSON.stringify(value, null, 2), 'utf8');
  fs.chmodSync(filePath, mode);
}

if (!fs.existsSync(inputPath)) {
  throw new Error(`Credentials CSV not found: ${inputPath}`);
}

const rows = fs
  .readFileSync(inputPath, 'utf8')
  .split(/\r?\n/)
  .filter(Boolean);

const accountsDir = path.join(stateDir, 'openclaw-weixin', 'accounts');
const accountIds = [];
const channelAccounts = {};

for (const row of rows) {
  const [
    tenantId,
    ciphertextBase64,
    baseUrlBase64,
    syncBase64,
    accountIdBase64,
    userRefBase64,
    labelBase64,
    humanNameBase64,
    isPrimary,
    bindingStatus,
  ] = row.split(',');

  const rawAccountId = decodeField(accountIdBase64);
  if (!rawAccountId) continue;

  const accountId = normalizeAccountId(rawAccountId);
  const token = decryptCredential(decodeField(ciphertextBase64));
  const baseUrl = decodeField(baseUrlBase64) || 'https://ilinkai.weixin.qq.com';
  const userId = decodeField(userRefBase64);
  const syncBuf = decodeField(syncBase64);
  const displayName = decodeField(labelBase64) || decodeField(humanNameBase64);

  writeJson(path.join(accountsDir, `${accountId}.json`), {
    token,
    savedAt: new Date().toISOString(),
    baseUrl,
    ...(userId ? { userId } : {}),
  });

  if (syncBuf) {
    writeJson(path.join(accountsDir, `${accountId}.sync.json`), {
      get_updates_buf: syncBuf,
    });
  }

  accountIds.push(accountId);
  channelAccounts[accountId] = {
    enabled: true,
    ...(displayName ? { name: displayName } : {}),
    tenantId,
    isPrimary: isPrimary === 'true',
    bindingStatus,
  };
}

const uniqueAccountIds = [...new Set(accountIds)];
writeJson(path.join(stateDir, 'openclaw-weixin', 'accounts.json'), uniqueAccountIds);

const configPath = path.join(stateDir, 'openclaw.json');
let config = {};
if (fs.existsSync(configPath)) {
  config = JSON.parse(fs.readFileSync(configPath, 'utf8'));
}

config.plugins = {
  ...(config.plugins || {}),
  entries: {
    ...((config.plugins || {}).entries || {}),
    'openclaw-weixin': { enabled: true },
  },
};

config.channels = {
  ...(config.channels || {}),
  'openclaw-weixin': {
    ...((config.channels || {})['openclaw-weixin'] || {}),
    enabled: true,
    accounts: {
      ...(((config.channels || {})['openclaw-weixin'] || {}).accounts || {}),
      ...channelAccounts,
    },
    channelConfigUpdatedAt: new Date().toISOString(),
  },
};

writeJson(configPath, config);

console.log(JSON.stringify({
  migratedRows: rows.length,
  uniqueAccounts: uniqueAccountIds.length,
  stateDir,
}, null, 2));
