import { expect, test } from "@playwright/test";

/**
 * Stock-detail E2E (needs FastAPI + Postgres with scores + Next). Registers, opens a scored stock's
 * detail from the list, and verifies the score decomposition renders with the Σ = composite
 * reconciliation — the US-02 explainability payoff, end to end.
 */
test("stock detail shows the decomposition summing to the composite", async ({ page }) => {
  const email = `e2e-detail-${Date.now()}@test.local`;

  await page.goto("/register");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill("correct-horse-battery-staple");
  await page.getByRole("button", { name: /create account/i }).click();
  await expect(page.getByText(/avg composite/i)).toBeVisible();

  // Open a scored stock via the list link.
  await page.getByRole("link", { name: "Stocks" }).click();
  await page.getByRole("link", { name: "HDFCBANK" }).click();

  await expect(page.getByRole("heading", { name: "HDFCBANK" })).toBeVisible();
  await expect(page.getByText(/score decomposition/i)).toBeVisible();
  await expect(page.getByText(/Σ contributions = composite/)).toBeVisible();
});
