import createClient from 'openapi-fetch';
import { ApiError, parseApiError } from './errors';
import type { components, paths } from './schema';

const DEFAULT_BASE_URL = '/api';

export type StatusResponse = components['schemas']['StatusResponse'];

export function resolveBaseUrl(): string {
  return (import.meta.env.VITE_API_BASE_URL ?? DEFAULT_BASE_URL).replace(/\/+$/, '');
}

/** The one typed API client (FE-ARCH-01). Components must use it, never fetch directly. */
export function createApiClient(baseUrl: string = resolveBaseUrl()) {
  // Request() needs an absolute URL; a path base such as /api is resolved against the page origin.
  const absolute = baseUrl.startsWith('/') ? `${globalThis.location.origin}${baseUrl}` : baseUrl;
  return createClient<paths>({
    baseUrl: absolute,
    credentials: 'include', // session cookie (FE-ARCH-02); CSRF is added in M1
    // Resolve fetch at call time so it can be stubbed in tests.
    fetch: (request) => globalThis.fetch(request),
  });
}

interface Result {
  data?: unknown;
  error?: unknown;
  response: Response;
}

/** Run a request and unwrap it; every failure becomes an ApiError. */
async function call<T>(run: () => Promise<Result>): Promise<T> {
  let result: Result;
  try {
    result = await run();
  } catch {
    throw new ApiError({ code: 'NETWORK_ERROR', message: 'Could not reach the API', status: 0 });
  }
  if (result.response.ok && result.data !== undefined) return result.data as T;
  throw parseApiError(
    result.response.status,
    result.error,
    result.response.headers.get('X-Request-ID'),
  );
}

export function getStatus(client = createApiClient()): Promise<StatusResponse> {
  return call<StatusResponse>(() => client.GET('/v1/status'));
}
