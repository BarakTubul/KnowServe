/**
 * The session-bound CSRF token (AUTH-14) lives in memory only (FE-AUTH-06): it is taken from the
 * identity response and never written to web storage. A reload re-fetches it through GET /v1/auth/me.
 */
let csrfToken: string | null = null;

export function setCsrfToken(token: string | null): void {
  csrfToken = token;
}

export function getCsrfToken(): string | null {
  return csrfToken;
}
