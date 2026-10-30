# KnowServe frontend

Vite + React + TypeScript. The browser talks to one origin; `/api/*` is handled by a Cloudflare Pages Function
(`functions/api/[[path]].ts`, contract: `docs/contracts/proxy.md`) that forwards `/api/v1/*` to the Cloud Run API
with the `/api` prefix removed. The client base URL defaults to `/api` (`VITE_API_BASE_URL` overrides).

## The Function

Allow-lists paths (`/api/v1/*`), methods and request headers; adds `X-KS-Proxy-Secret` and `X-KS-Client-IP`;
streams bodies unbuffered (SSE); keeps every `Set-Cookie`; returns the standard error envelope on failure.
`public/_routes.json` limits invocations to `/api/*`. The pure handler `handle(request, env, fetchImpl)` is unit
tested in `functions/api/proxy.test.ts`.

## Variables (Pages settings, never committed)

- `API_ORIGIN`: https origin of the API (http only for localhost/127.0.0.1).
- `PROXY_SHARED_SECRET`: Pages secret, same value as the API's `KS_PROXY_SHARED_SECRET`.

## Run locally

- Dev (same-origin through Vite): start the API on :8000, then `pnpm dev`; Vite proxies `/api` to it.
- With the real Workers runtime (workerd, local only, not Cloudflare's edge):
  `pnpm build && npx wrangler pages dev dist --port 8788 --binding API_ORIGIN=http://localhost:8000 --binding PROXY_SHARED_SECRET=local-only-proxy-secret-not-a-secret`
  (API started with the same `KS_PROXY_SHARED_SECRET` and `KS_ENABLE_SPIKE_ENDPOINTS=true`).
  Then `E2E_BASE_URL=http://127.0.0.1:8788 E2E_API_ORIGIN=http://localhost:8000 pnpm e2e proxy.spec.ts`.
