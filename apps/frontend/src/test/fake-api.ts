import { vi } from 'vitest';
import type { Department, Identity } from '@/lib/api/client';

export const DEPARTMENTS: Department[] = [
  { id: '11111111-1111-4111-8111-111111111111', name: 'Aurora Finance', slug: 'aurora-finance' },
  { id: '22222222-2222-4222-8222-222222222222', name: 'Borealis Legal', slug: 'borealis-legal' },
  { id: '33333333-3333-4333-8333-333333333333', name: 'Cirrus Operations', slug: 'cirrus' },
];

export function makeIdentity(overrides: Partial<Identity> = {}): Identity {
  return {
    user_id: '99999999-9999-4999-8999-999999999999',
    kind: 'registered',
    sign_in_provider: 'password',
    email: 'ada@example.com',
    display_name: null,
    active_department: DEPARTMENTS[0] ?? null,
    csrf_token: 'csrf-token-from-api',
    expires_at: new Date(Date.now() + 2 * 3600_000).toISOString(),
    ...overrides,
  };
}

export function jsonResponse(status: number, body?: unknown, headers: Record<string, string> = {}) {
  return new Response(body === undefined ? null : JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json', ...headers },
  });
}

export function errorResponse(
  status: number,
  code: string,
  message = code,
  headers: Record<string, string> = {},
) {
  return jsonResponse(
    status,
    { error: { code, message, request_id: 'req_0123456789abcdef' } },
    headers,
  );
}

export type Handler = (request: Request) => Response | Promise<Response>;

/**
 * Stubs `fetch` with a table keyed by `"METHOD /v1/path"` (the `/api` prefix is dropped). Unknown routes
 * answer 404 so a missing handler fails loudly. `calls` records every request.
 */
export function mockApi(routes: Record<string, Handler>) {
  const calls: { key: string; request: Request }[] = [];
  const table = { ...routes };
  vi.stubGlobal('fetch', async (input: Request) => {
    const url = new URL(input.url);
    const key = `${input.method} ${url.pathname.replace(/^\/api/, '')}`;
    calls.push({ key, request: input.clone() });
    const handler = table[key];
    if (!handler) return errorResponse(404, 'NOT_FOUND', `no mock for ${key}`);
    return handler(input.clone());
  });
  return {
    calls,
    routes: table,
    count: (key: string) => calls.filter((c) => c.key === key).length,
    last: (key: string) => calls.filter((c) => c.key === key).at(-1)?.request,
  };
}

export const ME = 'GET /v1/auth/me';
export const SESSION = 'POST /v1/auth/session';
export const DEMO_START = 'POST /v1/demo/start';
export const CONVERT = 'POST /v1/auth/convert';
export const LOGOUT = 'POST /v1/auth/logout';
export const DEPARTMENTS_LIST = 'GET /v1/departments';
export const SET_DEPARTMENT = 'PUT /v1/session/department';

export const unauthenticated: Handler = () => errorResponse(401, 'UNAUTHENTICATED');
export const departmentsOk: Handler = () => jsonResponse(200, { departments: DEPARTMENTS });
