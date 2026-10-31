import { expect, test } from "@playwright/test";

// MOCKED: the /v1/status call is intercepted with page.route. This only proves the frontend
// renders correctly against a canned response. It is NOT backend evidence and NOT M0-AC02 evidence.
test("m0_ac02_mocked_status_page_renders_success_state", async ({ page }) => {
  const baseUrl = process.env["E2E_BASE_URL"];
  if (!baseUrl) {
    throw new Error(
      "E2E_BASE_URL is required (for example http://localhost:4173). Not skipping.",
    );
  }
  await page.route("**/v1/status", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      headers: {
        "access-control-allow-origin": new URL(baseUrl).origin,
        "access-control-allow-credentials": "true",
      },
      body: JSON.stringify({
        service: "api",
        version: "0.0.0",
        environment: "local",
        database: "ok",
      }),
    }),
  );
  await page.goto(baseUrl);
  await expect(page.getByTestId("demo-mode-badge")).toHaveText("Demo Mode");
  await expect(page.getByTestId("api-status")).toBeVisible();
  await expect(page.getByTestId("api-service")).toHaveText("api");
});

test("m0_ac02_mocked_status_page_renders_error_state", async ({ page }) => {
  const baseUrl = process.env["E2E_BASE_URL"];
  if (!baseUrl) {
    throw new Error(
      "E2E_BASE_URL is required (for example http://localhost:4173). Not skipping.",
    );
  }
  await page.route("**/v1/status", (route) =>
    route.fulfill({
      status: 503,
      contentType: "application/json",
      headers: {
        "access-control-allow-origin": new URL(baseUrl).origin,
        "access-control-allow-credentials": "true",
      },
      body: JSON.stringify({
        error: {
          code: "DEPENDENCY_UNAVAILABLE",
          message: "down",
          request_id: "req_0123456789abcdef",
        },
      }),
    }),
  );
  await page.goto(baseUrl);
  await expect(page.getByTestId("api-error-code")).toHaveText(
    "DEPENDENCY_UNAVAILABLE",
  );
  await expect(page.getByTestId("api-error-request-id")).toHaveText(
    "req_0123456789abcdef",
  );
});
