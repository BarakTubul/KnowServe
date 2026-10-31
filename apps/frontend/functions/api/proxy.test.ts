// @vitest-environment node
import { describe, expect, it, vi } from 'vitest';
import { handle, upstreamPath, type Env } from './[[path]]';

const SECRET = 'local-only-proxy-secret-not-a-secret';
const ENV: Env = { API_ORIGIN: 'https://api.example.run.app', PROXY_SHARED_SECRET: SECRET };

function upstreamOk(init?: ResponseInit & { body?: BodyInit | null }) {
  return vi.fn((r: Request) => {
    void r;
    return Promise.resolve(new Response(init && 'body' in init ? init.body : 'ok', init));
  });
}

function req(path: string, init: RequestInit & { duplex?: 'half' } = {}) {
  return new Request('https://app.pages.dev' + path, init);
}

describe('open21 path allow-list and prefix stripping', () => {
  it('open21_strips_api_prefix_and_keeps_query', async () => {
    const f = upstreamOk();
    await handle(req('/api/v1/status?a=1&b=%20x'), ENV, f);
    expect(f.mock.calls[0]?.[0].url).toBe('https://api.example.run.app/v1/status?a=1&b=%20x');
  });

  it.each([
    '/api/v1x/status',
    '/api/v1',
    '/api/health/live',
    '/api/other',
    '/api',
    '/api/v1/%2e%2e/health/live',
    '/api/v1/%2E%2E/%2e%2e/x',
    '/api/v1/../health',
    '/api/v1//status',
    '/api/v1/%5c..%5cx',
    '/api/v1/%zz',
  ])('open21_non_v1_or_traversal_path_%s_is_404_envelope_and_not_forwarded', async (p) => {
    const f = upstreamOk();
    const res = await handle(req(p), ENV, f);
    expect(res.status).toBe(404);
    const body = (await res.json()) as { error: { code: string; request_id: string } };
    expect(body.error.code).toBe('NOT_FOUND');
    expect(body.error.request_id).toMatch(/^req_/);
    expect(f).not.toHaveBeenCalled();
  });

  it('open21_upstreamPath_maps_only_v1', () => {
    expect(upstreamPath('/api/v1/a/b')).toBe('/v1/a/b');
    expect(upstreamPath('/api/v2/a')).toBeNull();
  });

  it('m0ac17_operator_job_routes_are_never_forwarded_by_the_public_proxy', async () => {
    const f = upstreamOk();
    for (const path of [
      '/api/internal/spike/jobs',
      '/api/internal/spike/jobs/00000000-0000-0000-0000-000000000000/retry',
      '/api/v1/../internal/spike/jobs',
      '/api/v1/%2e%2e/internal/spike/jobs',
      '/api/%2e%2e/internal/spike/jobs',
      '/internal/spike/jobs',
    ]) {
      expect(upstreamPath(path)).toBeNull();
      const res = await handle(req(path, { method: 'POST' }), ENV, f as unknown as typeof fetch);
      expect(res.status).toBe(404);
    }
    expect(f).not.toHaveBeenCalled();
  });
});

describe('open21 methods', () => {
  it.each(['GET', 'POST', 'PUT', 'PATCH', 'DELETE'])('open21_method_%s_allowed', async (m) => {
    const f = upstreamOk();
    const res = await handle(
      req('/api/v1/x', { method: m, body: m === 'GET' ? undefined : 'b' }),
      ENV,
      f,
    );
    expect(res.status).toBe(200);
    expect(f.mock.calls[0]?.[0].method).toBe(m);
  });

  it.each(['OPTIONS', 'HEAD', 'PURGE', 'PROPFIND'])('open21_method_%s_is_405', async (m) => {
    const f = upstreamOk();
    const res = await handle(req('/api/v1/x', { method: m }), ENV, f);
    expect(res.status).toBe(405);
    expect(f).not.toHaveBeenCalled();
  });
});

describe('open21 request headers', () => {
  it('open21_forwards_only_allow_listed_headers_and_drops_spoofed_ones', async () => {
    const f = upstreamOk();
    await handle(
      req('/api/v1/x', {
        headers: {
          accept: 'application/json',
          'accept-language': 'en',
          cookie: 'ks_session=abc',
          origin: 'https://app.pages.dev',
          'user-agent': 'ua',
          'x-csrf-token': 'tok',
          'last-event-id': '3',
          'x-ks-proxy-secret': 'attacker',
          'x-ks-client-ip': '6.6.6.6',
          'x-ks-other': 'x',
          'x-forwarded-for': '6.6.6.6',
          'x-forwarded-host': 'evil',
          'cf-ray': 'r',
          'cf-connecting-ip': '203.0.113.9',
          authorization: 'Bearer nope',
          'x-custom': 'nope',
          host: 'evil.example',
        },
      }),
      ENV,
      f,
    );
    const h = f.mock.calls[0]?.[0].headers as Headers;
    const names = [...h.keys()].sort();
    expect(names).toEqual(
      [
        'accept',
        'accept-language',
        'cookie',
        'last-event-id',
        'origin',
        'user-agent',
        'x-csrf-token',
        'x-ks-client-ip',
        'x-ks-proxy-secret',
        'x-request-id',
      ].sort(),
    );
    expect(h.get('x-ks-proxy-secret')).toBe(SECRET);
    expect(h.get('x-ks-client-ip')).toBe('203.0.113.9');
    expect(h.get('cookie')).toBe('ks_session=abc');
  });

  it('open21_spoofed_client_ip_is_not_forwarded_when_cf_header_absent', async () => {
    const f = upstreamOk();
    await handle(req('/api/v1/x', { headers: { 'x-ks-client-ip': '6.6.6.6' } }), ENV, f);
    const h = f.mock.calls[0]?.[0].headers as Headers;
    expect(h.has('x-ks-client-ip')).toBe(false);
  });

  it('open21_request_id_honored_when_valid_else_generated', async () => {
    const f = upstreamOk();
    await handle(req('/api/v1/x', { headers: { 'x-request-id': 'req_abcdef0123456789' } }), ENV, f);
    expect((f.mock.calls[0]?.[0].headers as Headers).get('x-request-id')).toBe(
      'req_abcdef0123456789',
    );
    await handle(req('/api/v1/x', { headers: { 'x-request-id': 'bad id!' } }), ENV, f);
    expect((f.mock.calls[1]?.[0].headers as Headers).get('x-request-id')).toMatch(
      /^req_[0-9a-f]{16}$/,
    );
  });

  it('open21_request_body_is_streamed_to_upstream', async () => {
    const f = vi.fn(async (r: Request) => new Response(await r.text()));
    const res = await handle(
      req('/api/v1/x', {
        method: 'POST',
        body: '{"a":1}',
        headers: { 'content-type': 'application/json' },
      }),
      ENV,
      f,
    );
    expect(await res.text()).toBe('{"a":1}');
  });
});

describe('open21 response handling', () => {
  it('open21_preserves_multiple_set_cookie_headers_without_adding_domain', async () => {
    const c1 = 'ks_session=abc; Path=/; Max-Age=300; Secure; HttpOnly; SameSite=Lax';
    const c2 = 'ks_csrf=def; Expires=Wed, 21 Oct 2026 07:28:00 GMT; Path=/; Secure; SameSite=Lax';
    const up = new Headers();
    up.append('set-cookie', c1);
    up.append('set-cookie', c2);
    const res = await handle(
      req('/api/v1/x'),
      ENV,
      upstreamOk({ status: 204, body: null, headers: up }),
    );
    expect(res.headers.getSetCookie()).toEqual([c1, c2]);
    for (const c of res.headers.getSetCookie()) expect(c.toLowerCase()).not.toContain('domain=');
    expect(res.status).toBe(204);
  });

  it('open21_drops_hop_by_hop_and_access_control_headers', async () => {
    const res = await handle(
      req('/api/v1/x'),
      ENV,
      upstreamOk({
        headers: {
          connection: 'close',
          'keep-alive': 'timeout=5',
          'access-control-allow-origin': '*',
          'access-control-allow-credentials': 'true',
          'x-app': 'kept',
        },
      }),
    );
    expect(res.headers.has('access-control-allow-origin')).toBe(false);
    expect(res.headers.has('access-control-allow-credentials')).toBe(false);
    expect(res.headers.has('keep-alive')).toBe(false);
    expect(res.headers.get('x-app')).toBe('kept');
  });

  it('open21_cache_control_no_store_added_only_when_absent_and_nosniff_always', async () => {
    const a = await handle(req('/api/v1/x'), ENV, upstreamOk());
    expect(a.headers.get('cache-control')).toBe('no-store');
    expect(a.headers.get('x-content-type-options')).toBe('nosniff');
    const b = await handle(
      req('/api/v1/x'),
      ENV,
      upstreamOk({
        headers: { 'cache-control': 'no-cache, no-transform', 'x-content-type-options': 'x' },
      }),
    );
    expect(b.headers.get('cache-control')).toBe('no-cache, no-transform');
    expect(b.headers.get('x-content-type-options')).toBe('nosniff');
  });

  it('open21_redirects_are_not_followed_and_returned_as_is', async () => {
    const f = vi.fn((r: Request) => {
      expect(r.redirect).toBe('manual');
      return Promise.resolve(new Response(null, { status: 302, headers: { location: '/v1/y' } }));
    });
    const res = await handle(req('/api/v1/x'), ENV, f);
    expect(res.status).toBe(302);
    expect(res.headers.get('location')).toBe('/v1/y');
    expect(f).toHaveBeenCalledTimes(1);
  });

  it('open21_upstream_failure_is_502_envelope', async () => {
    const res = await handle(req('/api/v1/x'), ENV, () => Promise.reject(new TypeError('down')));
    expect(res.status).toBe(502);
    const body = (await res.json()) as { error: { code: string; request_id: string } };
    expect(body.error.code).toBe('UPSTREAM_UNAVAILABLE');
    expect(body.error.request_id).toMatch(/^req_/);
  });
});

describe('open21 streaming and abort', () => {
  it('open21_sse_passthrough_is_incremental_first_chunk_before_upstream_closes', async () => {
    const enc = new TextEncoder();
    let closeUpstream: () => void = () => {};
    let closed = false;
    const body = new ReadableStream<Uint8Array>({
      start(c) {
        c.enqueue(enc.encode('data: 1\n\n'));
        setTimeout(() => c.enqueue(enc.encode('data: 2\n\n')), 30);
        closeUpstream = () => {
          closed = true;
          c.close();
        };
      },
    });
    const res = await handle(req('/api/v1/spike/stream'), ENV, () =>
      Promise.resolve(new Response(body, { headers: { 'content-type': 'text/event-stream' } })),
    );
    const reader = res.body!.getReader();
    const first = await reader.read();
    expect(new TextDecoder().decode(first.value)).toBe('data: 1\n\n');
    expect(closed).toBe(false); // delivered while upstream is still open
    const second = await reader.read();
    expect(new TextDecoder().decode(second.value)).toBe('data: 2\n\n');
    expect(closed).toBe(false);
    closeUpstream();
    expect((await reader.read()).done).toBe(true);
    expect(res.headers.get('content-type')).toBe('text/event-stream');
  });

  it('open21_client_abort_propagates_to_upstream_signal', async () => {
    const ctl = new AbortController();
    let upstreamSignal: AbortSignal | undefined;
    const f = (r: Request) => {
      upstreamSignal = r.signal;
      return Promise.resolve(new Response('x'));
    };
    await handle(new Request('https://app.pages.dev/api/v1/x', { signal: ctl.signal }), ENV, f);
    expect(upstreamSignal?.aborted).toBe(false);
    ctl.abort();
    expect(upstreamSignal?.aborted).toBe(true);
  });
});

describe('open21 configuration', () => {
  it.each<[string, Env]>([
    ['missing origin', { PROXY_SHARED_SECRET: SECRET }],
    ['missing secret', { API_ORIGIN: 'https://api.example.run.app' }],
    ['empty both', {}],
    [
      'http non-local origin',
      { API_ORIGIN: 'http://api.example.com', PROXY_SHARED_SECRET: SECRET },
    ],
    ['garbage origin', { API_ORIGIN: 'not a url', PROXY_SHARED_SECRET: SECRET }],
  ])('open21_misconfigured_%s_is_500_and_no_upstream_call', async (_n, env) => {
    const f = upstreamOk();
    const res = await handle(req('/api/v1/x'), env, f);
    expect(res.status).toBe(500);
    expect(((await res.json()) as { error: { code: string } }).error.code).toBe(
      'PROXY_MISCONFIGURED',
    );
    expect(f).not.toHaveBeenCalled();
  });

  it.each(['http://localhost:8000', 'http://127.0.0.1:8000'])(
    'open21_local_http_origin_%s_allowed',
    async (o) => {
      const f = upstreamOk();
      const res = await handle(req('/api/v1/x'), { API_ORIGIN: o, PROXY_SHARED_SECRET: SECRET }, f);
      expect(res.status).toBe(200);
    },
  );

  it('open21_secret_never_appears_in_response_headers_or_body', async () => {
    const cases: Response[] = [
      await handle(req('/api/v1/x'), ENV, upstreamOk()),
      await handle(req('/api/nope'), ENV, upstreamOk()),
      await handle(req('/api/v1/x', { method: 'OPTIONS' }), ENV, upstreamOk()),
      await handle(req('/api/v1/x'), ENV, () => Promise.reject(new Error(SECRET))),
      await handle(req('/api/v1/x'), { PROXY_SHARED_SECRET: SECRET }, upstreamOk()),
    ];
    for (const res of cases) {
      const text = await res.text();
      expect(text).not.toContain(SECRET);
      for (const [k, v] of res.headers) {
        expect(k).not.toContain(SECRET);
        expect(v).not.toContain(SECRET);
      }
    }
  });
});
