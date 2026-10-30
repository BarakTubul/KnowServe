// Same-origin API proxy (OPEN-21, docs/contracts/proxy.md). Cloudflare Pages Function.
// Only /api/v1/* is forwarded to API_ORIGIN with the /api prefix removed.
// Keep this file free of Cloudflare-only types so it also runs under Node/Vitest.

export interface Env {
  API_ORIGIN?: string;
  PROXY_SHARED_SECRET?: string;
}

type FetchImpl = (input: Request) => Promise<Response>;

const ALLOWED_METHODS = new Set(['GET', 'POST', 'PUT', 'PATCH', 'DELETE']);

const FORWARD_REQUEST_HEADERS = [
  'accept',
  'accept-language',
  'content-type',
  'content-length',
  'cookie',
  'last-event-id',
  'origin',
  'user-agent',
  'x-csrf-token',
  'x-request-id',
];

const DROP_RESPONSE_HEADERS = new Set([
  'connection',
  'keep-alive',
  'proxy-authenticate',
  'proxy-authorization',
  'te',
  'trailer',
  'trailers',
  'transfer-encoding',
  'upgrade',
  'set-cookie', // re-added one by one
]);

const REQUEST_ID_RE = /^[A-Za-z0-9_.-]{8,64}$/;

function newRequestId(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(8));
  return 'req_' + Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');
}

function errorResponse(
  status: number,
  code: string,
  message: string,
  requestId: string,
  extra: Record<string, string> = {},
): Response {
  return new Response(JSON.stringify({ error: { code, message, request_id: requestId } }), {
    status,
    headers: {
      'content-type': 'application/json',
      'cache-control': 'no-store',
      'x-content-type-options': 'nosniff',
      'x-request-id': requestId,
      ...extra,
    },
  });
}

function validApiOrigin(raw: string | undefined): URL | null {
  if (!raw) return null;
  let url: URL;
  try {
    url = new URL(raw);
  } catch {
    return null;
  }
  const local =
    url.protocol === 'http:' && (url.hostname === 'localhost' || url.hostname === '127.0.0.1');
  if (url.protocol !== 'https:' && !local) return null;
  return url;
}

/** Map the browser path to the upstream path, or null when it must not be forwarded. */
export function upstreamPath(pathname: string): string | null {
  // Reject anything that could escape /v1/ after decoding or normalisation.
  let decoded: string;
  try {
    decoded = decodeURIComponent(pathname);
  } catch {
    return null;
  }
  if (decoded.includes('\\') || decoded.includes('//')) return null;
  if (decoded.split('/').some((s) => s === '.' || s === '..')) return null;
  if (!pathname.startsWith('/api/v1/')) return null;
  return pathname.slice('/api'.length);
}

export async function handle(
  request: Request,
  env: Env,
  fetchImpl: FetchImpl = (r) => fetch(r),
): Promise<Response> {
  const inbound = request.headers.get('x-request-id');
  const requestId = inbound && REQUEST_ID_RE.test(inbound) ? inbound : newRequestId();

  const origin = validApiOrigin(env.API_ORIGIN);
  const secret = env.PROXY_SHARED_SECRET;
  if (!origin || !secret) {
    return errorResponse(500, 'PROXY_MISCONFIGURED', 'The API proxy is not configured', requestId);
  }

  const method = request.method.toUpperCase();
  if (!ALLOWED_METHODS.has(method)) {
    return errorResponse(405, 'METHOD_NOT_ALLOWED', 'Method not allowed', requestId, {
      allow: 'GET, POST, PUT, PATCH, DELETE',
    });
  }

  const url = new URL(request.url);
  const path = upstreamPath(url.pathname);
  if (path === null) {
    return errorResponse(404, 'NOT_FOUND', 'Not found', requestId);
  }

  const headers = new Headers();
  for (const name of FORWARD_REQUEST_HEADERS) {
    const value = request.headers.get(name);
    if (value !== null) headers.set(name, value);
  }
  headers.set('x-request-id', requestId);
  headers.set('x-ks-proxy-secret', secret);
  const clientIp = request.headers.get('cf-connecting-ip');
  if (clientIp) headers.set('x-ks-client-ip', clientIp);

  const target = new URL(path + url.search, origin);
  const init: RequestInit & { duplex?: 'half' } = {
    method,
    headers,
    redirect: 'manual',
    signal: request.signal,
  };
  if (method !== 'GET' && request.body) {
    init.body = request.body;
    init.duplex = 'half';
  }

  let upstream: Response;
  try {
    upstream = await fetchImpl(new Request(target, init));
  } catch {
    return errorResponse(502, 'UPSTREAM_UNAVAILABLE', 'The API is unreachable', requestId);
  }

  const out = new Headers();
  upstream.headers.forEach((value, name) => {
    const n = name.toLowerCase();
    if (DROP_RESPONSE_HEADERS.has(n) || n.startsWith('access-control-')) return;
    out.set(name, value);
  });
  for (const cookie of upstream.headers.getSetCookie()) out.append('set-cookie', cookie);
  if (!out.has('cache-control')) out.set('cache-control', 'no-store');
  out.set('x-content-type-options', 'nosniff');
  if (!out.has('x-request-id')) out.set('x-request-id', requestId);

  return new Response(upstream.body, {
    status: upstream.status,
    statusText: upstream.statusText,
    headers: out,
  });
}

export const onRequest = (context: { request: Request; env: Env }): Promise<Response> =>
  handle(context.request, context.env);
