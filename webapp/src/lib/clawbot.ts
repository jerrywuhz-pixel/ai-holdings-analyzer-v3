import crypto from 'crypto';

export interface ClawbotQrSession {
  qrcode: string;
  qrcodeUrl: string | null;
  sessionKey?: string;
  botToken?: string;
  accountId?: string;
  userId?: string;
  baseUrl?: string;
  getUpdatesBuf?: string;
  raw: unknown;
}

export interface ClawbotQrStatus {
  status: string;
  botToken?: string;
  accountId?: string;
  userId?: string;
  baseUrl?: string;
  getUpdatesBuf?: string;
  alreadyConnected?: boolean;
  raw: unknown;
}

export interface ClawbotUpdates {
  messages: unknown[];
  getUpdatesBuf?: string;
  raw: unknown;
}

export interface BindingCandidate {
  fromUserId: string | null;
  toUserId: string | null;
  contextToken: string | null;
  text: string;
}

const DEFAULT_CLAWBOT_API_BASE_URL = 'https://ilinkai.weixin.qq.com';
const LOCAL_DEV_PREFIX = 'local-dev:v1:';
const AES_PREFIX = 'aes-256-gcm:v1:';
const DEFAULT_ILINK_CLIENT_VERSION = '65536';

function apiBaseUrl() {
  return (process.env.WECHAT_CLAWBOT_API_BASE_URL || DEFAULT_CLAWBOT_API_BASE_URL).replace(/\/+$/, '');
}

function normalizeBaseUrl(baseUrl?: string | null) {
  return (baseUrl || apiBaseUrl()).replace(/\/+$/, '');
}

function randomWechatUin() {
  const value = crypto.randomBytes(4).readUInt32BE(0).toString();
  return Buffer.from(value, 'utf8').toString('base64');
}

function clawbotHeaders(botToken?: string) {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    AuthorizationType: 'ilink_bot_token',
    'X-WECHAT-UIN': randomWechatUin(),
    'iLink-App-ClientVersion': process.env.WECHAT_ILINK_CLIENT_VERSION || DEFAULT_ILINK_CLIENT_VERSION,
  };

  const ilinkAppId = process.env.WECHAT_ILINK_APP_ID;
  if (ilinkAppId) {
    headers['iLink-App-Id'] = ilinkAppId;
  }

  if (botToken) {
    headers.Authorization = `Bearer ${botToken}`;
  }

  return headers;
}

async function parseJsonResponse(response: Response) {
  const text = await response.text();
  if (!response.ok) {
    throw new Error(`Clawbot API returned HTTP ${response.status}: ${text.slice(0, 240)}`);
  }
  if (!text) {
    return {};
  }
  try {
    return JSON.parse(text);
  } catch (error) {
    throw new Error(`Clawbot API returned non-JSON response: ${text.slice(0, 240)}`);
  }
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value) ? (value as Record<string, unknown>) : null;
}

function pickString(value: unknown, keys: string[]): string | undefined {
  const record = asRecord(value);
  if (!record) return undefined;

  for (const key of keys) {
    const item = record[key];
    if (typeof item === 'string' && item.trim()) {
      return item.trim();
    }
  }

  for (const nested of Object.values(record)) {
    const result = pickString(nested, keys);
    if (result) return result;
  }

  return undefined;
}

function pickArray(value: unknown, keys: string[]): unknown[] {
  const record = asRecord(value);
  if (!record) return [];

  for (const key of keys) {
    const item = record[key];
    if (Array.isArray(item)) return item;
  }

  for (const nested of Object.values(record)) {
    const result = pickArray(nested, keys);
    if (result.length) return result;
  }

  return [];
}

function qrcodeImageUrl(payload: unknown) {
  const explicitUrl = pickString(payload, ['qrcode_url', 'qr_code_url', 'url', 'qrcodeUrl']);
  if (explicitUrl) return explicitUrl;

  const content = pickString(payload, ['qrcode_img_content', 'qrcode_image_content', 'qr_code_image_content']);
  if (!content) return null;
  if (content.startsWith('http://') || content.startsWith('https://')) return content;
  if (content.startsWith('data:image/')) return content;
  return `data:image/png;base64,${content}`;
}

export async function requestClawbotQrSession(): Promise<ClawbotQrSession> {
  const url = new URL('/ilink/bot/get_bot_qrcode', `${apiBaseUrl()}/`);
  url.searchParams.set('bot_type', '3');
  const sessionKey = crypto.randomUUID();

  const response = await fetch(url.toString(), {
    method: 'POST',
    cache: 'no-store',
    headers: clawbotHeaders(),
    body: JSON.stringify({
      local_token_list: [],
    }),
  });
  const payload = await parseJsonResponse(response);
  const qrcode = pickString(payload, ['qrcode', 'qr_code', 'qrcode_id']);
  if (!qrcode) {
    throw new Error('Clawbot API did not return qrcode');
  }

  return {
    qrcode,
    qrcodeUrl: qrcodeImageUrl(payload),
    sessionKey,
    botToken: pickString(payload, ['bot_token', 'botToken']),
    accountId: pickString(payload, ['ilink_bot_id', 'bot_id', 'account_id']),
    userId: pickString(payload, ['ilink_user_id', 'user_id', 'from_user_id']),
    baseUrl: pickString(payload, ['baseurl', 'base_url', 'baseUrl']),
    getUpdatesBuf: pickString(payload, ['get_updates_buf', 'getUpdatesBuf']),
    raw: payload,
  };
}

export async function requestClawbotQrStatus(qrcode: string): Promise<ClawbotQrStatus> {
  const url = new URL('/ilink/bot/get_qrcode_status', `${apiBaseUrl()}/`);
  url.searchParams.set('qrcode', qrcode);

  const response = await fetch(url.toString(), {
    method: 'GET',
    cache: 'no-store',
    headers: clawbotHeaders(),
  });
  const payload = await parseJsonResponse(response);

  return {
    status: pickString(payload, ['status', 'state']) || 'unknown',
    botToken: pickString(payload, ['bot_token', 'botToken']),
    accountId: pickString(payload, ['ilink_bot_id', 'bot_id', 'account_id']),
    userId: pickString(payload, ['ilink_user_id', 'user_id', 'from_user_id']),
    baseUrl: pickString(payload, ['baseurl', 'base_url', 'baseUrl']),
    getUpdatesBuf: pickString(payload, ['get_updates_buf', 'getUpdatesBuf']),
    alreadyConnected: pickString(payload, ['status', 'state']) === 'binded_redirect',
    raw: payload,
  };
}

export async function requestClawbotUpdates(
  baseUrl: string | null | undefined,
  botToken: string,
  getUpdatesBuf?: string | null
): Promise<ClawbotUpdates> {
  const url = new URL('/ilink/bot/getupdates', `${normalizeBaseUrl(baseUrl)}/`);
  const response = await fetch(url.toString(), {
    method: 'POST',
    cache: 'no-store',
    headers: clawbotHeaders(botToken),
    body: JSON.stringify({
      get_updates_buf: getUpdatesBuf || '',
      base_info: { channel_version: '1.0.2' },
    }),
  });
  const payload = await parseJsonResponse(response);

  return {
    messages: pickArray(payload, ['msgs', 'messages', 'updates']),
    getUpdatesBuf: pickString(payload, ['get_updates_buf', 'getUpdatesBuf']),
    raw: payload,
  };
}

export function generateBindCode() {
  return `AH3-${crypto.randomBytes(3).toString('hex').toUpperCase()}`;
}

function encryptionKey() {
  const secret = process.env.ONBOARDING_CREDENTIAL_ENCRYPTION_KEY;
  if (!secret) {
    if (process.env.NODE_ENV === 'production') {
      throw new Error('ONBOARDING_CREDENTIAL_ENCRYPTION_KEY is required in production');
    }
    return null;
  }
  return crypto.createHash('sha256').update(secret).digest();
}

export function encryptCredential(value: string) {
  const key = encryptionKey();
  if (!key) {
    return `${LOCAL_DEV_PREFIX}${Buffer.from(value, 'utf8').toString('base64')}`;
  }

  const iv = crypto.randomBytes(12);
  const cipher = crypto.createCipheriv('aes-256-gcm', key, iv);
  const encrypted = Buffer.concat([cipher.update(value, 'utf8'), cipher.final()]);
  const authTag = cipher.getAuthTag();
  return `${AES_PREFIX}${[
    iv.toString('base64url'),
    authTag.toString('base64url'),
    encrypted.toString('base64url'),
  ].join(':')}`;
}

export function decryptCredential(value: string) {
  if (value.startsWith(LOCAL_DEV_PREFIX)) {
    return Buffer.from(value.slice(LOCAL_DEV_PREFIX.length), 'base64').toString('utf8');
  }

  if (!value.startsWith(AES_PREFIX)) {
    throw new Error('Unsupported credential ciphertext format');
  }

  const key = encryptionKey();
  if (!key) {
    throw new Error('ONBOARDING_CREDENTIAL_ENCRYPTION_KEY is required to decrypt stored credentials');
  }

  const [ivText, tagText, encryptedText] = value.slice(AES_PREFIX.length).split(':');
  if (!ivText || !tagText || !encryptedText) {
    throw new Error('Invalid credential ciphertext');
  }

  const decipher = crypto.createDecipheriv('aes-256-gcm', key, Buffer.from(ivText, 'base64url'));
  decipher.setAuthTag(Buffer.from(tagText, 'base64url'));
  return Buffer.concat([
    decipher.update(Buffer.from(encryptedText, 'base64url')),
    decipher.final(),
  ]).toString('utf8');
}

function collectText(value: unknown): string[] {
  if (typeof value === 'string') {
    return [value];
  }
  if (Array.isArray(value)) {
    return value.flatMap(collectText);
  }

  const record = asRecord(value);
  if (!record) return [];

  return Object.entries(record).flatMap(([key, nested]) => {
    if (['text', 'content', 'message', 'msg'].includes(key) && typeof nested === 'string') {
      return [nested];
    }
    return collectText(nested);
  });
}

export function findBindingCandidate(messages: unknown[], bindCode: string): BindingCandidate | null {
  const normalizedCode = bindCode.trim().toUpperCase();
  for (const message of messages) {
    const texts = collectText(message);
    const matchedText = texts.find((text) => text.toUpperCase().includes(normalizedCode));
    if (!matchedText) continue;

    return {
      fromUserId: pickString(message, ['from_user_id', 'fromUserId']) || null,
      toUserId: pickString(message, ['to_user_id', 'toUserId']) || null,
      contextToken: pickString(message, ['context_token', 'contextToken']) || null,
      text: matchedText,
    };
  }

  return null;
}
