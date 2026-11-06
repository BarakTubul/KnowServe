import { afterEach, describe, expect, it, vi } from 'vitest';
import { createApiClient, listDepartments, logout, setActiveDepartment } from './client';
import { setCsrfToken } from './csrf';
import { ApiError, parseApiError } from './errors';
import { emitApiError, subscribeApiErrors } from './events';

function stubFetch(res: () => Response) {
  const fn = vi.fn((req: Request) => {
    void req;
    return Promise.resolve(res());
  });
  vi.stubGlobal('fetch', fn);
  return fn;
}

const IDENTITY = {
  user_id: '99999999-9999-4999-8999-999999999999',
  kind: 'demo',
  sign_in_provider: 'anonymous',
  csrf_token: 'x',
  expires_at: '2030-01-01T00:00:00Z',
};

afterEach(() => {
  setCsrfToken(null);
  vi.unstubAllGlobals();
});

describe('FE-ARCH-02 CSRF and credentials', () => {
  it('fe_arch_02_a_mutation_sends_credentials_include_and_the_csrf_header', async () => {
    setCsrfToken('csrf-123');
    const fetchMock = stubFetch(
      () =>
        new Response(JSON.stringify(IDENTITY), { headers: { 'content-type': 'application/json' } }),
    );
    await setActiveDepartment(
      '11111111-1111-4111-8111-111111111111',
      createApiClient('http://api.test'),
    );
    const req = fetchMock.mock.calls[0]?.[0] as Request;
    expect(req.method).toBe('PUT');
    expect(req.credentials).toBe('include');
    expect(req.headers.get('X-CSRF-Token')).toBe('csrf-123');
  });

  it('fe_arch_02_reads_do_not_carry_the_csrf_header', async () => {
    setCsrfToken('csrf-123');
    const fetchMock = stubFetch(
      () =>
        new Response(JSON.stringify({ departments: [] }), {
          headers: { 'content-type': 'application/json' },
        }),
    );
    await listDepartments(createApiClient('http://api.test'));
    const req = fetchMock.mock.calls[0]?.[0] as Request;
    expect(req.headers.get('X-CSRF-Token')).toBeNull();
    expect(req.credentials).toBe('include');
  });

  it('fe_arch_02_logout_accepts_204_and_sends_the_csrf_header', async () => {
    setCsrfToken('csrf-123');
    const fetchMock = stubFetch(() => new Response(null, { status: 204 }));
    await expect(logout(createApiClient('http://api.test'))).resolves.toBeUndefined();
    expect((fetchMock.mock.calls[0]?.[0] as Request).headers.get('X-CSRF-Token')).toBe('csrf-123');
  });
});

describe('FE-ARCH-03 error envelope and events', () => {
  it('fe_arch_03_retry_after_seconds_is_parsed_and_other_formats_ignored', () => {
    const body = { error: { code: 'RATE_LIMITED', message: 'slow down', request_id: 'req_1' } };
    expect(parseApiError(429, body, null, '30').retryAfterSeconds).toBe(30);
    expect(parseApiError(429, body, null, 'Wed, 21 Oct 2026 07:28:00 GMT').retryAfterSeconds).toBe(
      undefined,
    );
    expect(parseApiError(429, body, null, null).retryAfterSeconds).toBeUndefined();
  });

  it('fe_arch_03_authenticated_failures_are_broadcast_and_public_ones_are_not', async () => {
    const seen: string[] = [];
    const unsubscribe = subscribeApiErrors((e) => seen.push(e.code));
    const failing = () =>
      new Response(
        JSON.stringify({ error: { code: 'UNAUTHENTICATED', message: 'm', request_id: 'r' } }),
        {
          status: 401,
          headers: { 'content-type': 'application/json' },
        },
      );
    stubFetch(failing);
    await expect(listDepartments(createApiClient('http://api.test'))).rejects.toBeInstanceOf(
      ApiError,
    );
    await expect(logout(createApiClient('http://api.test'))).rejects.toBeInstanceOf(ApiError);
    expect(seen).toEqual(['UNAUTHENTICATED']); // only the authenticated call, not logout
    unsubscribe();
    emitApiError(new ApiError({ code: 'X', message: 'x', status: 500 }));
    expect(seen).toHaveLength(1);
  });
});
