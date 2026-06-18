import crypto from 'crypto';

export interface ClawbotQrSession {
  qrcode: string;
  qrcodeUrl: string | null;
  sessionKey?: string;
  botToken?: string;
  accountId?: string;
  userId?: string;
  baseUrl?: string;
  redirectHost?: string;
  getUpdatesBuf?: string;
  raw: unknown;
}

export interface ClawbotQrStatus {
  status: string;
  botToken?: string;
  accountId?: string;
  userId?: string;
  baseUrl?: string;
  redirectHost?: string;
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

export interface ClawbotSendTextInput {
  toUserId: string;
  contextToken: string;
  text: string;
}

export interface ClawbotConfig {
  typingTicket?: string;
  raw: unknown;
}

export interface ClawbotSendTypingInput {
  toUserId: string;
  contextToken: string;
  typingTicket?: string | null;
  status: 'typing' | 'cancel';
}

export interface ClawbotCdnMediaInput {
  fullUrl?: string | null;
  encryptQueryParam?: string | null;
  aesKeyBase64?: string | null;
  aesKeyHex?: string | null;
}

export interface ClawbotDownloadedMedia {
  buffer: Buffer;
  contentType: string | null;
}

const DEFAULT_CLAWBOT_API_BASE_URL = 'https://ilinkai.weixin.qq.com';
const DEFAULT_CLAWBOT_CDN_BASE_URL = 'https://novac2c.cdn.weixin.qq.com/c2c';
const LOCAL_DEV_PREFIX = 'local-dev:v1:';
const AES_PREFIX = 'aes-256-gcm:v1:';
const DEFAULT_CHANNEL_VERSION = '2.4.4';
const DEFAULT_MAX_IMAGE_BYTES = 8 * 1024 * 1024;

function apiBaseUrl() {
  return (process.env.WECHAT_CLAWBOT_API_BASE_URL || DEFAULT_CLAWBOT_API_BASE_URL).replace(/\/+$/, '');
}

function normalizeBaseUrl(baseUrl?: string | null) {
  return (baseUrl || apiBaseUrl()).replace(/\/+$/, '');
}

function cdnBaseUrl() {
  return (process.env.WECHAT_CLAWBOT_CDN_BASE_URL || DEFAULT_CLAWBOT_CDN_BASE_URL).replace(/\/+$/, '');
}

function randomWechatUin() {
  const value = crypto.randomBytes(4).readUInt32BE(0).toString();
  return Buffer.from(value, 'utf8').toString('base64');
}

function channelVersion() {
  return process.env.WECHAT_CHANNEL_VERSION || DEFAULT_CHANNEL_VERSION;
}

function ilinkClientVersion() {
  if (process.env.WECHAT_ILINK_CLIENT_VERSION) return process.env.WECHAT_ILINK_CLIENT_VERSION;
  const [major = 0, minor = 0, patch = 0] = channelVersion()
    .split('.')
    .map((part) => Number.parseInt(part, 10) || 0);
  return String(((major & 0xff) << 16) | ((minor & 0xff) << 8) | (patch & 0xff));
}

function clawbotHeaders(botToken?: string) {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    AuthorizationType: 'ilink_bot_token',
    'X-WECHAT-UIN': randomWechatUin(),
    'iLink-App-Id': process.env.WECHAT_ILINK_APP_ID || 'bot',
    'iLink-App-ClientVersion': ilinkClientVersion(),
  };

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
    const payload = JSON.parse(text);
    const record = asRecord(payload);
    const ret = numericCode(record?.ret);
    const errcode = numericCode(record?.errcode);
    const message = pickString(payload, ['errmsg', 'err_msg', 'error_message', 'message', 'msg']) || '';
    if (typeof ret === 'number' && ret !== 0) {
      throw new Error(`Clawbot API returned ret=${ret}: ${message.slice(0, 160)}`);
    }
    if (typeof errcode === 'number' && errcode !== 0) {
      throw new Error(`Clawbot API returned errcode=${errcode}: ${message.slice(0, 160)}`);
    }
    return payload;
  } catch (error) {
    if (error instanceof Error && error.message.startsWith('Clawbot API returned')) {
      throw error;
    }
    throw new Error(`Clawbot API returned non-JSON response: ${text.slice(0, 240)}`);
  }
}

function numericCode(value: unknown) {
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  if (typeof value === 'string' && /^-?\d+$/.test(value.trim())) return Number(value);
  return null;
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

  let emptyCandidate: unknown[] | null = null;
  for (const key of keys) {
    const item = record[key];
    if (Array.isArray(item)) {
      if (item.length) return item;
      emptyCandidate ||= item;
    }
  }

  for (const nested of Object.values(record)) {
    const result = pickArray(nested, keys);
    if (result.length) return result;
  }

  return emptyCandidate || [];
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

function baseInfo() {
  return {
    channel_version: channelVersion(),
    bot_agent: process.env.WECHAT_BOT_AGENT || 'OpenClaw',
  };
}

export async function requestClawbotQrSession(localTokenList: string[] = []): Promise<ClawbotQrSession> {
  const url = new URL('/ilink/bot/get_bot_qrcode', `${apiBaseUrl()}/`);
  url.searchParams.set('bot_type', '3');
  const sessionKey = crypto.randomUUID();

  const response = await fetch(url.toString(), {
    method: 'POST',
    cache: 'no-store',
    headers: clawbotHeaders(),
    body: JSON.stringify({
      local_token_list: localTokenList,
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
    redirectHost: pickString(payload, ['redirect_host', 'redirectHost', 'base_host', 'baseHost']),
    getUpdatesBuf: pickString(payload, ['get_updates_buf', 'getUpdatesBuf']),
    raw: payload,
  };
}

type ClawbotQrStatusOptions = {
  baseUrl?: string | null;
  verifyCode?: string | null;
};

export async function requestClawbotQrStatus(
  qrcode: string,
  options: ClawbotQrStatusOptions = {}
): Promise<ClawbotQrStatus> {
  const url = new URL('/ilink/bot/get_qrcode_status', `${normalizeBaseUrl(options.baseUrl)}/`);
  url.searchParams.set('qrcode', qrcode);
  if (options.verifyCode) {
    url.searchParams.set('verify_code', options.verifyCode);
  }

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
      base_info: baseInfo(),
    }),
  });
  const payload = await parseJsonResponse(response);

  return {
    messages: pickArray(payload, ['msgs', 'messages', 'updates']),
    getUpdatesBuf: pickString(payload, [
      'get_updates_buf',
      'getUpdatesBuf',
      'getupdates_buf',
      'next_get_updates_buf',
      'nextGetUpdatesBuf',
    ]),
    raw: payload,
  };
}

export async function requestClawbotSendTextMessage(
  baseUrl: string | null | undefined,
  botToken: string,
  input: ClawbotSendTextInput
) {
  const url = new URL('/ilink/bot/sendmessage', `${normalizeBaseUrl(baseUrl)}/`);
  const response = await fetch(url.toString(), {
    method: 'POST',
    cache: 'no-store',
    headers: clawbotHeaders(botToken),
    body: JSON.stringify({
      msg: {
        from_user_id: '',
        to_user_id: input.toUserId,
        client_id: `ai-holdings-${crypto.randomUUID()}`,
        message_type: 2,
        message_state: 2,
        context_token: input.contextToken,
        item_list: [
          {
            type: 1,
            text_item: {
              text: input.text,
            },
          },
        ],
      },
      base_info: baseInfo(),
    }),
  });

  return parseJsonResponse(response);
}

export async function requestClawbotConfig(
  baseUrl: string | null | undefined,
  botToken: string,
  toUserId: string,
  contextToken?: string | null
): Promise<ClawbotConfig> {
  const url = new URL('/ilink/bot/getconfig', `${normalizeBaseUrl(baseUrl)}/`);
  const response = await fetch(url.toString(), {
    method: 'POST',
    cache: 'no-store',
    headers: clawbotHeaders(botToken),
    body: JSON.stringify({
      ilink_user_id: toUserId,
      context_token: contextToken || '',
      base_info: baseInfo(),
    }),
  });
  const payload = await parseJsonResponse(response);

  return {
    typingTicket: pickString(payload, ['typing_ticket', 'typingTicket']),
    raw: payload,
  };
}

export async function requestClawbotSendTyping(
  baseUrl: string | null | undefined,
  botToken: string,
  input: ClawbotSendTypingInput
) {
  const typingTicket =
    input.typingTicket ||
    (await requestClawbotConfig(baseUrl, botToken, input.toUserId, input.contextToken)).typingTicket;
  if (!typingTicket) {
    throw new Error('Clawbot API did not return typing_ticket');
  }

  const url = new URL('/ilink/bot/sendtyping', `${normalizeBaseUrl(baseUrl)}/`);
  const response = await fetch(url.toString(), {
    method: 'POST',
    cache: 'no-store',
    headers: clawbotHeaders(botToken),
    body: JSON.stringify({
      ilink_user_id: input.toUserId,
      typing_ticket: typingTicket,
      status: input.status === 'typing' ? 1 : 2,
      base_info: baseInfo(),
    }),
  });

  return parseJsonResponse(response);
}

function buildCdnDownloadUrl(encryptQueryParam: string) {
  const url = new URL('/c2c/download', `${cdnBaseUrl()}/`);
  url.searchParams.set('encrypted_query_param', encryptQueryParam);
  return url.toString();
}

function decodeCdnAesKey(input: ClawbotCdnMediaInput): Buffer | null {
  if (input.aesKeyHex && /^[0-9a-f]{32}$/i.test(input.aesKeyHex.trim())) {
    return Buffer.from(input.aesKeyHex.trim(), 'hex');
  }
  if (!input.aesKeyBase64) return null;

  const decoded = Buffer.from(input.aesKeyBase64.trim(), 'base64');
  if (decoded.length === 16) return decoded;
  const ascii = decoded.toString('utf8').trim();
  if (/^[0-9a-f]{32}$/i.test(ascii)) {
    return Buffer.from(ascii, 'hex');
  }
  throw new Error('Clawbot CDN media aes_key is not a supported AES-128 key');
}

function decryptCdnMedia(buffer: Buffer, aesKey: Buffer) {
  const decipher = crypto.createDecipheriv('aes-128-ecb', aesKey, null);
  decipher.setAutoPadding(true);
  return Buffer.concat([decipher.update(buffer), decipher.final()]);
}

export async function downloadClawbotCdnMedia(input: ClawbotCdnMediaInput): Promise<ClawbotDownloadedMedia> {
  const url = input.fullUrl || (input.encryptQueryParam ? buildCdnDownloadUrl(input.encryptQueryParam) : '');
  if (!url) {
    throw new Error('Clawbot image message did not include a downloadable media URL');
  }

  const response = await fetch(url, {
    method: 'GET',
    cache: 'no-store',
  });
  if (!response.ok) {
    throw new Error(`Clawbot CDN returned HTTP ${response.status}`);
  }

  const maxBytes = Number(process.env.WECHAT_CLAWBOT_MAX_IMAGE_BYTES || DEFAULT_MAX_IMAGE_BYTES);
  const contentLength = Number(response.headers.get('content-length') || '0');
  if (Number.isFinite(contentLength) && contentLength > maxBytes) {
    throw new Error(`Clawbot CDN image is too large: ${contentLength} bytes`);
  }

  const encryptedBuffer = Buffer.from(await response.arrayBuffer());
  if (encryptedBuffer.length > maxBytes) {
    throw new Error(`Clawbot CDN image is too large: ${encryptedBuffer.length} bytes`);
  }

  const aesKey = decodeCdnAesKey(input);
  const buffer = aesKey ? decryptCdnMedia(encryptedBuffer, aesKey) : encryptedBuffer;
  return {
    buffer,
    contentType: response.headers.get('content-type'),
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
