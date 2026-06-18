#!/usr/bin/env node
import fs from 'node:fs';
import path from 'node:path';

const stateDir = process.env.OPENCLAW_STATE_DIR || '/state';
const webappUrl = (process.env.WEBAPP_INTERNAL_URL || 'http://webapp:3000').replace(/\/+$/, '');
const routeUrl = `${webappUrl}/api/openclaw/wechat/route-message`;
const secret =
  process.env.OPENCLAW_WEIXIN_ROUTE_ADAPTER_SECRET ||
  process.env.OPENCLAW_CRON_SECRET ||
  process.env.WECHAT_CLAWBOT_BRIDGE_SECRET ||
  '';
const pollIntervalMs = Math.max(2, Number(process.env.OPENCLAW_WEIXIN_ROUTE_ADAPTER_INTERVAL_SECONDS || 5)) * 1000;
const apiTimeoutMs = Math.max(5000, Number(process.env.OPENCLAW_WEIXIN_ROUTE_ADAPTER_API_TIMEOUT_MS || 30000));
const channelVersion = process.env.WECHAT_CHANNEL_VERSION || '2.4.4';
const ilinkAppId = process.env.WECHAT_ILINK_APP_ID || 'bot';
const ilinkClientVersion = process.env.WECHAT_ILINK_CLIENT_VERSION || deriveClientVersion(channelVersion);

if (!secret) {
  throw new Error('OPENCLAW_WEIXIN_ROUTE_ADAPTER_SECRET or OPENCLAW_CRON_SECRET is required');
}

function deriveClientVersion(version) {
  const [major = 0, minor = 0, patch = 0] = version.split('.').map((part) => Number.parseInt(part, 10) || 0);
  return String(((major & 0xff) << 16) | ((minor & 0xff) << 8) | (patch & 0xff));
}

function log(message, extra) {
  const suffix = extra ? ` ${JSON.stringify(extra)}` : '';
  console.log(`${new Date().toISOString()} [openclaw-weixin-route-adapter] ${message}${suffix}`);
}

function accountIndexPath() {
  return path.join(stateDir, 'openclaw-weixin', 'accounts.json');
}

function accountPath(accountId) {
  return path.join(stateDir, 'openclaw-weixin', 'accounts', `${accountId}.json`);
}

function syncPath(accountId) {
  return path.join(stateDir, 'openclaw-weixin', 'accounts', `${accountId}.sync.json`);
}

function deriveRawAccountId(accountId) {
  if (accountId.endsWith('-im-bot')) return `${accountId.slice(0, -7)}@im.bot`;
  if (accountId.endsWith('-im-wechat')) return `${accountId.slice(0, -10)}@im.wechat`;
  return accountId;
}

function readJson(filePath, fallback) {
  try {
    return JSON.parse(fs.readFileSync(filePath, 'utf8'));
  } catch {
    return fallback;
  }
}

function writeJson(filePath, value) {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  fs.writeFileSync(filePath, JSON.stringify(value, null, 2), 'utf8');
  fs.chmodSync(filePath, 0o600);
}

function randomWechatUin() {
  return Buffer.from(String(Math.floor(Math.random() * 1_000_000_000)), 'utf8').toString('base64');
}

function headers(token) {
  return {
    'Content-Type': 'application/json',
    Authorization: `Bearer ${token}`,
    AuthorizationType: 'ilink_bot_token',
    'X-WECHAT-UIN': randomWechatUin(),
    'iLink-App-Id': ilinkAppId,
    'iLink-App-ClientVersion': ilinkClientVersion,
  };
}

async function postJson(url, body, requestHeaders) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), apiTimeoutMs);
  try {
    const response = await fetch(url, {
      method: 'POST',
      cache: 'no-store',
      headers: requestHeaders,
      body: JSON.stringify(body),
      signal: controller.signal,
    });
    const text = await response.text();
    const payload = text ? JSON.parse(text) : {};
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}: ${text.slice(0, 240)}`);
    }
    const ret = Number(payload?.ret ?? payload?.errcode ?? 0);
    if (Number.isFinite(ret) && ret !== 0) {
      throw new Error(`ret=${ret}: ${String(payload?.errmsg || payload?.message || '').slice(0, 160)}`);
    }
    return payload;
  } finally {
    clearTimeout(timer);
  }
}

async function getUpdates(accountId, account) {
  const sync = readJson(syncPath(accountId), {});
  const baseUrl = (account.baseUrl || 'https://ilinkai.weixin.qq.com').replace(/\/+$/, '');
  return postJson(`${baseUrl}/ilink/bot/getupdates`, {
    get_updates_buf: sync.get_updates_buf || '',
    base_info: {
      channel_version: channelVersion,
      bot_agent: process.env.WECHAT_BOT_AGENT || 'OpenClaw',
    },
  }, headers(account.token));
}

async function routeMessage(accountId, rawAccountId, getUpdatesBuf, message) {
  return postJson(routeUrl, {
    accountId,
    rawAccountId,
    getUpdatesBuf,
    message,
  }, {
    'Content-Type': 'application/json',
    Authorization: `Bearer ${secret}`,
  });
}

async function pollAccount(accountId) {
  const account = readJson(accountPath(accountId), null);
  if (!account?.token) {
    log('account missing token, skipped', { accountId });
    return { accountId, messages: 0, routed: 0, skipped: 0 };
  }

  const rawAccountId = deriveRawAccountId(accountId);
  const updates = await getUpdates(accountId, account);
  const messages = Array.isArray(updates.msgs) ? updates.msgs : Array.isArray(updates.messages) ? updates.messages : [];
  let routed = 0;
  let skipped = 0;

  for (const message of messages) {
    const result = await routeMessage(accountId, rawAccountId, updates.get_updates_buf || '', message);
    routed += Number(result.messagesForwarded || 0);
    skipped += Number(result.messagesSkipped || 0);
  }

  if (updates.get_updates_buf) {
    writeJson(syncPath(accountId), { get_updates_buf: updates.get_updates_buf });
  }

  return { accountId, messages: messages.length, routed, skipped };
}

async function tick() {
  const accounts = readJson(accountIndexPath(), []);
  if (!Array.isArray(accounts) || accounts.length === 0) {
    log('no configured openclaw-weixin accounts found');
    return;
  }

  for (const accountId of accounts) {
    try {
      const result = await pollAccount(accountId);
      if (result.messages > 0 || result.routed > 0 || result.skipped > 0) {
        log('poll result', result);
      }
    } catch (error) {
      log('poll failed', { accountId, error: error instanceof Error ? error.message : String(error) });
    }
  }
}

log('starting', { stateDir, routeUrl, pollIntervalMs });
await tick();
setInterval(() => {
  tick().catch((error) => log('tick failed', { error: error instanceof Error ? error.message : String(error) }));
}, pollIntervalMs);
