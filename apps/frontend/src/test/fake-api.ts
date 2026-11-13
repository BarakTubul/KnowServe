import { vi } from 'vitest';
import type { Department, Identity } from '@/lib/api/client';
import type { components } from '@/lib/api/schema';

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

// --- Admin (M3) fixtures -------------------------------------------------------------------------

export type AdminDocumentFixture = components['schemas']['AdminDocumentOut'];

export function makeAdminDocument(
  overrides: Partial<AdminDocumentFixture> = {},
): AdminDocumentFixture {
  const [owner] = DEPARTMENTS;
  if (!owner) throw new Error('fixture needs departments');
  return {
    document_id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
    revision_id: 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
    status: 'ready',
    phase: null,
    failure_code: null,
    failure_message: null,
    delivery_state: 'done',
    can_retry: false,
    can_replace: false,
    title: 'Leave policy',
    filename: 'leave-policy.pdf',
    owner_department: owner,
    allowed_departments: [owner],
    page_count: 3,
    size_bytes: 20_480,
    created_at: '2026-11-13T09:00:00Z',
    updated_at: '2026-11-13T09:05:00Z',
    ...overrides,
  };
}

export function adminPage(items: AdminDocumentFixture[], nextCursor: string | null = null) {
  return jsonResponse(200, { items, has_more: nextCursor !== null, next_cursor: nextCursor });
}

export const ADMIN_LIST = 'GET /v1/admin/documents';
export const ADMIN_CREATE = 'POST /v1/admin/documents';
export const ADMIN_PREVIEW = 'POST /v1/admin/imports/preview';
export const ADMIN_CONFIRM = 'POST /v1/admin/imports/confirm';
export const adminDocKey = (method: string, id: string, suffix = '') =>
  `${method} /v1/admin/documents/${id}${suffix}`;

/** An Admin identity with a chosen active department (Admin routes do not need one). */
export function makeAdminIdentity(overrides: Partial<Identity> = {}): Identity {
  return makeIdentity({ kind: 'admin', email: 'admin@example.com', ...overrides });
}
