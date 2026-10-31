# Same-origin API proxy contract (OPEN-21, approved provisionally pending spike validation)

Requirements: AUTH-06, AUTH-14, AUTH-19, INFRA-11, FE-ARCH-02, SEC-13. Evidence for the choice: `docs/milestones/M0/hosting-comparison.md`. Until the M0 spike confirms the three open behaviors (incremental SSE, cookie pass-through, free-quota fit), this contract is provisional.

## Topology
The browser only talks to one origin, `https://<project>.pages.dev`. Static files are served by Cloudflare Pages. Requests to `/api/*` are handled by a Pages Function (`apps/frontend/functions/api/[[path]].ts`) that forwards them to the Cloud Run API at `API_ORIGIN`. The Worker service is not behind the proxy: QStash calls the Worker's own Cloud Run URL, authenticated by signature (SEC-14). The spike-only operator routes (`/internal/spike/jobs`, `jobs-outbox.md`) are also not proxied: the Function forwards only `/api/v1/*`, so they are unreachable through Cloudflare Pages. An operator calls the API's `run.app` URL directly and must send `X-KS-Proxy-Secret` as well as the OIDC bearer token.

```text
browser --/api/v1/...--> Pages Function --(+ X-KS-Proxy-Secret, X-KS-Client-IP)--> Cloud Run API /v1/...
```

## Function behavior
- **Paths:** only `/api/v1/*` is forwarded, with the `/api` prefix removed (`/api/v1/status` -> `${API_ORIGIN}/v1/status`). Any other `/api/*` path returns a 404 JSON error envelope. `_routes.json` includes only `/api/*`, so static assets never invoke the Function (free-quota protection).
- **Methods:** GET, POST, PUT, PATCH, DELETE. Anything else, including OPTIONS (not needed same-origin), returns 405.
- **Request headers:** forward only `accept`, `accept-language`, `content-type`, `content-length`, `cookie`, `last-event-id`, `origin`, `user-agent`, `x-csrf-token`, `x-request-id`. Drop everything else. Client-supplied `x-ks-*`, `x-forwarded-*`, `cf-*` and `host` are never forwarded. The Function adds `X-KS-Proxy-Secret` (from the Pages secret `PROXY_SHARED_SECRET`) and `X-KS-Client-IP` (from `CF-Connecting-IP`).
- **Request body:** streamed to the upstream, not buffered. The client's abort signal is passed to the upstream fetch, so closing the page cancels the upstream request.
- **Redirects:** never followed (`redirect: "manual"`); a redirect response is returned as is.
- **Response:** status and body are passed through **unbuffered** (SSE must arrive incrementally). All `Set-Cookie` headers are preserved with their attributes. Hop-by-hop headers and `access-control-*` are dropped. `Cache-Control: no-store` is added when the upstream sets none, and `X-Content-Type-Options: nosniff` is always added (`_headers` does not apply to Function responses).
- **Check order:** configuration is checked first (500 `PROXY_MISCONFIGURED`), then method (405), then path (404). Paths containing `..` (encoded or not), a backslash or `//` return 404, including an encoded `%2F` inside a segment. A client `x-request-id` is forwarded only if it matches `^[A-Za-z0-9_.-]{8,64}$`; the Function adds one to its own error responses.
- **Upstream failure:** a network error returns 502 with the error envelope, code `UPSTREAM_UNAVAILABLE`, and a `request_id`.
- **Configuration:** `API_ORIGIN` (plain variable, https) and `PROXY_SHARED_SECRET` (Pages secret). If either is missing the Function returns 500 `PROXY_MISCONFIGURED` and forwards nothing.

## API behavior (direct Cloud Run access protection)
- Setting `KS_PROXY_SHARED_SECRET`. When set, **every route except `/health/*`** requires header `X-KS-Proxy-Secret` with that value, compared in constant time. A missing or wrong value returns `403` with the error envelope, code `DIRECT_ACCESS_DENIED`, and the request is not processed. `/health/*` stays open for Cloud Run probes.
- In `KS_ENV=production` the API refuses to start without `KS_PROXY_SHARED_SECRET`. Outside production the guard is off when the setting is unset, so local development and CI work without it.
- `X-KS-Client-IP` is trusted only after the secret check passed, and only if it parses as an IP address; otherwise it is ignored. Without the secret check it is never read. Rate limits and audit logs (M1) key on this value.
- With the guard on, the CORS middleware is **not installed** (the same-origin route needs none), so even a preflight is rejected with 403. CORS stays enabled only when the guard is off (local development).
- The secret is never logged (MON-05).

## Secrets and rotation
One random value, held in two places: Google Secret Manager secret `proxy-shared-secret` (Terraform creates the container only; the user adds the value) and the Pages secret `PROXY_SHARED_SECRET` (set by the user with `wrangler pages secret put`). It never appears in the repository or in Terraform state. Rotation: add a new secret version, roll a new API revision (Cloud Run reads `latest` at start), then update the Pages secret and redeploy the Function; requests fail with 403 between the two steps, so rotate in a quiet window.

## Cookies and CSRF (unchanged)
The session cookie stays `Secure`, `HttpOnly`, host-only and `SameSite=Lax` (M1). The session-bound CSRF token and the Origin check remain mandatory; the Origin the API sees is the `pages.dev` origin, so `KS_API_ALLOWED_ORIGINS` is that single origin. CORS is not needed for the same-origin path.

## Local development
Vite proxies `/api` to `http://localhost:8000` (stripping the prefix), so development is same-origin too and the client always uses the base URL `/api`.

## Residual risks (documented, not hidden)
- The API's `run.app` URL stays publicly reachable. It rejects requests without the secret, but the secret is a shared bearer value: if it leaks, anyone can call the API directly (still bound by auth, CSRF and the Origin check). Rotate it.
- Free-quota exhaustion (100,000 Function requests/day shared) makes API calls fail while static pages keep loading (fail-closed API).
- Streaming through a Pages Function, `Set-Cookie` pass-through and the forwarded client IP are verified locally with the Workers runtime only; the deployed spike must confirm them on Cloudflare's edge.
