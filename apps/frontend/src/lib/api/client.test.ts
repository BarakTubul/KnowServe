import { afterEach, describe, expect, it, vi } from 'vitest';
import { createApiClient, getStatus } from './client';
import { ApiError } from './errors';

const OK = { service: 'api', version: '0.0.0', environment: 'local', database: 'ok' };

function jsonResponse(status: number, body: unknown, headers: Record<string, string> = {}) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json', ...headers },
  });
}

function stubFetch(res: () => Response) {
  const fn = vi.fn((req: Request) => {
    void req;
    return Promise.resolve(res());
  });
  vi.stubGlobal('fetch', fn);
  return fn;
}

afterEach(() => vi.unstubAllGlobals());

describe('fe_arch_01 / fe_arch_02 api client', () => {
  it('fe_arch_02_sends_credentials_include_to_the_configured_base_url', async () => {
    const fetchMock = stubFetch(() => jsonResponse(200, OK));
    const data = await getStatus(createApiClient('http://api.test'));
    expect(data.service).toBe('api');
    const req = fetchMock.mock.calls[0]?.[0] as Request;
    expect(req.url).toBe('http://api.test/v1/status');
    expect(req.credentials).toBe('include');
    expect(req.method).toBe('GET');
  });

  it('open21_default_base_url_is_same_origin_api_path', async () => {
    const fetchMock = stubFetch(() => jsonResponse(200, OK));
    await getStatus(createApiClient());
    const req = fetchMock.mock.calls[0]?.[0] as Request;
    expect(new URL(req.url).pathname).toBe('/api/v1/status');
    expect(new URL(req.url).origin).toBe(globalThis.location.origin);
  });

  it.each([
    [404, 'NOT_FOUND'],
    [422, 'VALIDATION_ERROR'],
    [503, 'DEPENDENCY_UNAVAILABLE'],
  ])('fe_arch_03_parses_error_envelope_%i_into_ApiError', async (status, code) => {
    stubFetch(() =>
      jsonResponse(status, {
        error: { code, message: 'nope', request_id: 'req_ab12cd34ef56ab12' },
      }),
    );
    const err = await getStatus(createApiClient('http://api.test')).catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    const apiErr = err as ApiError;
    expect(apiErr.status).toBe(status);
    expect(apiErr.code).toBe(code);
    expect(apiErr.message).toBe('nope');
    expect(apiErr.requestId).toBe('req_ab12cd34ef56ab12');
  });

  it('fe_arch_03_non_envelope_response_falls_back_to_header_request_id', async () => {
    stubFetch(
      () => new Response('bad gateway', { status: 502, headers: { 'X-Request-ID': 'req_h' } }),
    );
    const err = (await getStatus(createApiClient('http://api.test')).catch(
      (e: unknown) => e,
    )) as ApiError;
    expect(err.code).toBe('UNEXPECTED_RESPONSE');
    expect(err.status).toBe(502);
    expect(err.requestId).toBe('req_h');
  });

  it('fe_arch_03_network_failure_becomes_retryable_ApiError', async () => {
    vi.stubGlobal('fetch', () => Promise.reject(new TypeError('failed')));
    const err = (await getStatus(createApiClient('http://api.test')).catch(
      (e: unknown) => e,
    )) as ApiError;
    expect(err).toBeInstanceOf(ApiError);
    expect(err.code).toBe('NETWORK_ERROR');
    expect(err.status).toBe(0);
  });
});
