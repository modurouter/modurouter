import { NextRequest } from 'next/server';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';
export const maxDuration = 360;

// Deliberately expose only the chat API; this is not an arbitrary forward proxy.
export async function GET(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  return forward(request, context);
}
export async function POST(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  return forward(request, context);
}
async function forward(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const path = '/' + (await context.params).path.join('/');
  const allowed = request.method === 'GET'
    ? /^\/v1\/(me|config|usage|models(?:\/status)?|conversations(?:\/[a-f0-9-]+)?|runs\/[a-f0-9-]+)$/.test(path)
    : /^\/(auth\/guest|v1\/audio\/transcriptions|v1\/conversations(?:\/[a-f0-9-]+\/runs)?|v1\/runs\/[a-f0-9-]+\/cancel)$/.test(path);
  if (!allowed) return Response.json({ message: '지원하지 않는 요청입니다.' }, { status: 404 });
  // Next.js may construct nextUrl using its bind host (0.0.0.0), not the
  // browser-facing host. Never trust arbitrary Host/X-Forwarded-Host as an allowlist.
  const configuredOrigin = process.env.FRONTEND_ORIGIN || process.env.PRODUCTION_WEB_ORIGIN;
  const allowedOrigins = new Set([configuredOrigin || request.nextUrl.origin]);
  if (process.env.NODE_ENV === 'development' && !configuredOrigin) {
    const port = request.nextUrl.port ? `:${request.nextUrl.port}` : '';
    allowedOrigins.add(`http://localhost${port}`);
    allowedOrigins.add(`http://127.0.0.1${port}`);
  }
  const requestOrigin = request.headers.get('origin');
  if (request.method === 'POST' && (!requestOrigin || !allowedOrigins.has(requestOrigin))) {
    return Response.json({ code: 'CSRF_INVALID', message: '요청 출처를 확인할 수 없습니다.' }, { status: 403 });
  }
  const upstream = process.env.API_UPSTREAM_URL;
  const origin = process.env.BACKEND_WEB_ORIGIN;
  if (!upstream || !origin) return Response.json({ code: 'API_NOT_CONFIGURED', message: '서버 연결 설정이 필요합니다.' }, { status: 503 });
  const headers = new Headers({ 'Origin': origin, 'Accept': request.headers.get('accept') || 'application/json' });
  for (const name of ['content-type', 'x-csrf-token', 'idempotency-key']) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  const cookie = request.cookies.get('modurouter_session');
  if (cookie) headers.set('cookie', `modurouter_session=${cookie.value}`);
  try {
    const response = await fetch(new URL(path, upstream), {
      method: request.method, headers, cache: 'no-store', redirect: 'manual',
      body: request.method === 'POST' ? (path === '/v1/audio/transcriptions' ? await request.arrayBuffer() : await request.text()) : undefined,
      signal: AbortSignal.any([request.signal, AbortSignal.timeout(path === '/v1/audio/transcriptions' ? 330_000 : 150_000)]),
    });
    const out = new Headers({ 'Cache-Control': 'no-store', 'X-Accel-Buffering': 'no', 'Content-Type': response.headers.get('content-type') || 'application/json' });
    for (const value of response.headers.getSetCookie()) {
      if (!value.startsWith('modurouter_session=')) continue;
      let localCookie = value.replace(/;\s*Domain=[^;]+/ig, '');
      if (process.env.NODE_ENV === 'development' && request.nextUrl.protocol === 'http:') localCookie = localCookie.replace(/;\s*Secure/ig, '');
      out.append('Set-Cookie', localCookie);
    }
    return new Response(response.body, { status: response.status, headers: out });
  } catch {
    return Response.json({ code: 'UPSTREAM_UNAVAILABLE', message: '서버에 연결하지 못했어요. 잠시 후 다시 시도해 주세요.' }, { status: 502 });
  }
}
