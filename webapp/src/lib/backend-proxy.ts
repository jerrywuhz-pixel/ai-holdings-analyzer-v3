import { NextRequest, NextResponse } from 'next/server';

const HOP_BY_HOP_HEADERS = new Set([
  'connection',
  'keep-alive',
  'proxy-authenticate',
  'proxy-authorization',
  'te',
  'trailers',
  'transfer-encoding',
  'upgrade',
]);

function buildServiceBaseUrl(): string {
  const candidates = [
    process.env.NEXT_PUBLIC_DATA_SERVICE_URL,
    process.env.DATA_SERVICE_URL,
    process.env.HERMES_INGRESS_URL,
    'http://127.0.0.1:8000',
  ];
  for (const value of candidates) {
    if (value && value.trim()) return value.trim().replace(/\/+$/, '');
  }
  return 'http://127.0.0.1:8000';
}

function buildTargetUrl(prefix: string, slug: string[], search: string) {
  const prefixPath = `api/${prefix}`.replace(/\/+/g, '/').replace(/\/$/, '');
  const path = slug.length ? `/${slug.join('/')}` : '';
  return `${buildServiceBaseUrl()}/${prefixPath}${path}${search}`;
}

function injectInternalHeaders(headers: Headers) {
  const token = process.env.HERMES_DOMAIN_TOOLS_KEY || process.env.HERMES_INTERNAL_TOKEN || '';
  if (!token) return;

  headers.set('X-Hermes-Domain-Tools-Key', token);
  headers.set('X-Hermes-Internal-Token', token);
  headers.set('X-OpenClaw-Skill-Key', token);
}

function sanitizeRequestHeaders(request: NextRequest): Headers {
  const headers = new Headers();
  const requestEntries = Array.from(request.headers.entries());
  for (let i = 0; i < requestEntries.length; i++) {
    const [key, value] = requestEntries[i];
    const lowered = key.toLowerCase();
    if (['host'].includes(lowered)) continue;
    if (lowered === 'connection' && request.headers.get('connection')) continue;
    headers.set(key, value);
  }

  injectInternalHeaders(headers);
  return headers;
}

function sanitizeResponseHeaders(headers: Headers): Headers {
  const out = new Headers();
  const responseEntries = Array.from(headers.entries());
  for (let i = 0; i < responseEntries.length; i++) {
    const [key, value] = responseEntries[i];
    if (!HOP_BY_HOP_HEADERS.has(key.toLowerCase())) {
      out.set(key, value);
    }
  }

  return out;
}

export async function proxyToBackend(request: NextRequest, prefix: 'hermes' | 'openclaw', slug: string[]) {
  const method = request.method.toUpperCase();
  const targetUrl = buildTargetUrl(prefix, slug, request.nextUrl.search);
  const headers = sanitizeRequestHeaders(request);
  const init: RequestInit = { method, headers };

  if (!['GET', 'HEAD'].includes(method)) {
    init.body = await request.arrayBuffer();
  }

  let backendResponse: Response;
  try {
    backendResponse = await fetch(targetUrl, init);
  } catch (error) {
    return NextResponse.json(
      {
        error: 'backend_request_failed',
        details: error instanceof Error ? error.message : '未知网络错误',
        target: targetUrl,
      },
      { status: 502 }
    );
  }

  const responseBody = backendResponse.body;
  return new NextResponse(responseBody, {
    status: backendResponse.status,
    statusText: backendResponse.statusText,
    headers: sanitizeResponseHeaders(backendResponse.headers),
  });
}
