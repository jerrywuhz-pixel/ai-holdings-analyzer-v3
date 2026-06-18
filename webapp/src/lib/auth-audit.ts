import { createHash } from 'crypto';
import type { NextRequest } from 'next/server';

type AuthAuditLevel = 'info' | 'warn' | 'error';

export function authEmailHash(email: string) {
  return createHash('sha256').update(email.trim().toLowerCase()).digest('hex').slice(0, 16);
}

function clientIp(request?: NextRequest) {
  const forwarded = request?.headers.get('x-forwarded-for')?.split(',')[0]?.trim();
  return forwarded || request?.headers.get('x-real-ip') || undefined;
}

export function authAudit(
  event: string,
  {
    email,
    request,
    level = 'info',
    ...details
  }: {
    email?: string;
    request?: NextRequest;
    level?: AuthAuditLevel;
    [key: string]: unknown;
  } = {}
) {
  const payload = {
    scope: 'auth',
    event,
    email_hash: email ? authEmailHash(email) : undefined,
    ip: clientIp(request),
    ...details,
  };

  const message = `[auth_audit] ${JSON.stringify(payload)}`;
  if (level === 'error') {
    console.error(message);
  } else if (level === 'warn') {
    console.warn(message);
  } else {
    console.info(message);
  }
}
