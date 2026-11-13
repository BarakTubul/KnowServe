import createClient from 'openapi-fetch';
import { getCsrfToken } from './csrf';
import { ApiError, parseApiError } from './errors';
import { emitApiError } from './events';
import type { components, paths } from './schema';

const DEFAULT_BASE_URL = '/api';

export type StatusResponse = components['schemas']['StatusResponse'];
export type Identity = components['schemas']['IdentityResponse'];
export type Department = components['schemas']['DepartmentOut'];

export type ApiClient = ReturnType<typeof createApiClient>;

const MUTATING = new Set(['POST', 'PUT', 'PATCH', 'DELETE']);

export function resolveBaseUrl(): string {
  return (import.meta.env.VITE_API_BASE_URL ?? DEFAULT_BASE_URL).replace(/\/+$/, '');
}

/** The one typed API client (FE-ARCH-01). Components must use it, never fetch directly. */
export function createApiClient(baseUrl: string = resolveBaseUrl()) {
  // Request() needs an absolute URL; a path base such as /api is resolved against the page origin.
  const absolute = baseUrl.startsWith('/') ? `${globalThis.location.origin}${baseUrl}` : baseUrl;
  const client = createClient<paths>({
    baseUrl: absolute,
    credentials: 'include', // session cookie (FE-ARCH-02)
    // Resolve fetch at call time so it can be stubbed in tests.
    fetch: (request) => globalThis.fetch(request),
  });
  client.use({
    onRequest({ request }) {
      // Session-bound CSRF token on every mutation once an identity is known (AUTH-14).
      const csrf = getCsrfToken();
      if (csrf && MUTATING.has(request.method.toUpperCase())) {
        request.headers.set('X-CSRF-Token', csrf);
      }
      return request;
    },
  });
  return client;
}

export interface Result {
  data?: unknown;
  error?: unknown;
  response: Response;
}

export interface CallOptions {
  /**
   * Calls made without a KnowServe session (status, the session exchange, `me`, logout) handle their
   * errors locally. Everything else reports 401/409/429/503 to the global handler (FE-AUTH-05).
   */
  public?: boolean;
  /** 204 No Content is a success without a body. */
  empty?: boolean;
}

/** Run a request and unwrap it; every failure becomes an ApiError. */
export async function call<T>(run: () => Promise<Result>, options: CallOptions = {}): Promise<T> {
  let result: Result;
  try {
    result = await run();
  } catch {
    const networkError = new ApiError({
      code: 'NETWORK_ERROR',
      message: 'Could not reach the API',
      status: 0,
    });
    throw networkError;
  }
  if (result.response.ok && (result.data !== undefined || options.empty)) {
    return result.data as T;
  }
  const error = parseApiError(
    result.response.status,
    result.error,
    result.response.headers.get('X-Request-ID'),
    result.response.headers.get('Retry-After'),
  );
  if (!options.public) emitApiError(error);
  throw error;
}

export function getStatus(client = createApiClient()): Promise<StatusResponse> {
  return call<StatusResponse>(() => client.GET('/v1/status'), { public: true });
}

/** Hydrates the session state (AUTH-09, FE-AUTH-01). A 401 means "no session", not an error to broadcast. */
export function getMe(client = createApiClient()): Promise<Identity> {
  return call<Identity>(() => client.GET('/v1/auth/me'), { public: true });
}

/** Session exchange (AUTH-30). The ID token is passed through and never kept. */
export function createSession(idToken: string, client = createApiClient()): Promise<Identity> {
  return call<Identity>(() => client.POST('/v1/auth/session', { body: { id_token: idToken } }), {
    public: true,
  });
}

export function startDemo(idToken: string, client = createApiClient()): Promise<Identity> {
  return call<Identity>(() => client.POST('/v1/demo/start', { body: { id_token: idToken } }), {
    public: true,
  });
}

/** Demo to Registered conversion (AUTH-34); needs the Demo session cookie and CSRF token. */
export function convertDemo(idToken: string, client = createApiClient()): Promise<Identity> {
  return call<Identity>(() => client.POST('/v1/auth/convert', { body: { id_token: idToken } }));
}

export function logout(client = createApiClient()): Promise<void> {
  return call<void>(() => client.POST('/v1/auth/logout'), { public: true, empty: true });
}

export async function listDepartments(client = createApiClient()): Promise<Department[]> {
  const body = await call<components['schemas']['DepartmentsResponse']>(() =>
    client.GET('/v1/departments'),
  );
  return body.departments;
}

export function setActiveDepartment(
  departmentId: string,
  client = createApiClient(),
): Promise<Identity> {
  return call<Identity>(() =>
    client.PUT('/v1/session/department', { body: { department_id: departmentId } }),
  );
}

/**
 * A fresh `Idempotency-Key` (`^[A-Za-z0-9_-]{8,128}$`, docs/contracts/admin-api.md). One key belongs to one
 * user action: the caller keeps it for retries of that same action and asks for a new one for the next.
 */
export function newIdempotencyKey(): string {
  return globalThis.crypto.randomUUID();
}

/**
 * Multipart body for the generated client. The schema types file parts as strings, so the FormData is
 * passed through a cast; the client then leaves Content-Type to the browser, which adds the boundary.
 */
export function multipartBody(fields: Iterable<readonly [string, string | Blob]>): never {
  const form = new FormData();
  for (const [name, value] of fields) form.append(name, value);
  return form as never;
}
