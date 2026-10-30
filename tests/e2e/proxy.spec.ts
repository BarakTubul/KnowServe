// OPEN-21 same-origin proxy checks (docs/contracts/proxy.md). Real browser, no mocks.
//
// HOW THIS RUNS
//   E2E_BASE_URL   the frontend origin that serves /api via the Pages Function
//                  (local: `wrangler pages dev dist` on http://127.0.0.1:8788, or the pages.dev URL)
//   E2E_API_ORIGIN the API's DIRECT URL (local: http://localhost:8000, deployed: the run.app URL)
//   The API must run with KS_ENABLE_SPIKE_ENDPOINTS=true and KS_PROXY_SHARED_SECRET set.
//   From apps/frontend: E2E_BASE_URL=... E2E_API_ORIGIN=... pnpm e2e proxy.spec.ts
// Not covered here (header spoofing through the proxy): the API does not echo request headers, so
// that is asserted by the Function unit tests (functions/api/proxy.test.ts).
import { expect, test } from "@playwright/test";

function env(name: string): string {
  const v = process.env[name];
  if (!v) throw new Error(`${name} is required. Not skipping.`);
  return v.replace(/\/+$/, "");
}

test("open21_proxy_get_status_works_same_origin", async ({ page }) => {
  const base = env("E2E_BASE_URL");
  await page.goto(base);
  const r = await page.evaluate(async () => {
    const res = await fetch("/api/v1/status");
    return { status: res.status, body: await res.json() };
  });
  expect(r.status).toBe(200);
  expect(r.body.service).toBe("api");
});

test("open21_proxy_sse_arrives_incrementally", async ({ page }) => {
  const base = env("E2E_BASE_URL");
  await page.goto(base);
  // Warm up: local `wrangler pages dev` can take ~2 s on a cold request; measure streaming only.
  await page.evaluate(() => fetch("/api/v1/status").then((r) => r.text()));
  const r = await page.evaluate(async () => {
    const t0 = performance.now();
    const res = await fetch("/api/v1/spike/stream?seconds=6&interval=1");
    const reader = res.body!.getReader();
    const dec = new TextDecoder();
    const chunks: { t: number; text: string }[] = [];
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      chunks.push({ t: performance.now() - t0, text: dec.decode(value) });
    }
    return { status: res.status, ct: res.headers.get("content-type"), chunks };
  });
  expect(r.status).toBe(200);
  expect(r.ct).toContain("text/event-stream");
  expect(r.chunks.length).toBeGreaterThanOrEqual(4);
  expect(r.chunks[0]!.t).toBeLessThan(2500);
  const last = r.chunks[r.chunks.length - 1]!;
  expect(last.t - r.chunks[0]!.t).toBeGreaterThan(3500); // spread over time, not all at the end
  expect(r.chunks.map((c) => c.text).join("")).toContain("event: done");
});

test("open21_proxy_cookie_is_httponly_host_only_lax_and_hidden_from_js", async ({
  page,
  context,
}) => {
  const base = env("E2E_BASE_URL");
  await page.goto(base);
  const set = await page.evaluate(async () => {
    const res = await fetch("/api/v1/spike/cookie", { method: "POST" });
    return res.status;
  });
  expect(set).toBe(204);
  const host = new URL(base).hostname;
  const cookie = (await context.cookies()).find((c) => c.name === "ks_spike");
  expect(cookie).toBeDefined();
  expect(cookie!.httpOnly).toBe(true);
  expect(cookie!.sameSite).toBe("Lax");
  expect(cookie!.domain.startsWith(".")).toBe(false);
  expect(cookie!.domain).toBe(host);
  expect(await page.evaluate(() => document.cookie)).not.toContain("ks_spike");
  const echo = await page.evaluate(async () => {
    const res = await fetch("/api/v1/spike/echo");
    return res.json();
  });
  expect(echo.cookie_present).toBe(true);
});

test("open21_direct_api_access_without_secret_is_denied_but_health_is_open", async ({
  request,
}) => {
  const api = env("E2E_API_ORIGIN");
  const denied = await request.get(`${api}/v1/status`);
  expect(denied.status()).toBe(403);
  expect((await denied.json()).error.code).toBe("DIRECT_ACCESS_DENIED");

  const wrong = await request.get(`${api}/v1/status`, {
    headers: { "X-KS-Proxy-Secret": "definitely-wrong" },
  });
  expect(wrong.status()).toBe(403);
  expect((await wrong.json()).error.code).toBe("DIRECT_ACCESS_DENIED");

  const health = await request.get(`${api}/health/live`);
  expect(health.status()).toBe(200);
});

test("open21_proxy_does_not_leak_secret_in_responses", async ({ request }) => {
  const base = env("E2E_BASE_URL");
  const res = await request.get(`${base}/api/v1/status`, {
    headers: { "X-KS-Proxy-Secret": "attacker", "X-KS-Client-IP": "6.6.6.6" },
  });
  expect(res.status()).toBe(200);
  const blob = JSON.stringify(res.headers()) + (await res.text());
  expect(blob).not.toContain("local-only-proxy-secret");
  const other = await request.get(`${base}/api/health/live`);
  expect(other.status()).toBe(404);
  expect((await other.json()).error.code).toBe("NOT_FOUND");
});
