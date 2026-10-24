import { expect, test } from "@playwright/test";

// M0-AC02 smoke. Real stack: run against the deployed (or local full-stack) frontend, no mocks.
test("m0_ac02_status_page_shows_demo_badge_and_api_status", async ({
  page,
}) => {
  const baseUrl = process.env["E2E_BASE_URL"];
  if (!baseUrl) {
    throw new Error(
      "E2E_BASE_URL is required (for example E2E_BASE_URL=https://app.example.com). Not skipping.",
    );
  }
  await page.goto(baseUrl);
  await expect(page.getByTestId("demo-mode-badge")).toHaveText("Demo Mode");
  await expect(page.getByTestId("api-status")).toBeVisible();
  await expect(page.getByTestId("api-service")).toHaveText("api");
});
