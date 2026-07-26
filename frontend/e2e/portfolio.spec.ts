import { expect, test } from "@playwright/test";

/**
 * Portfolio risk + rebalancing UI E2E (QV-060) — needs FastAPI + Postgres + Next.
 * Registers, creates a portfolio, opens its detail page, and verifies the builder surface now
 * carries the Risk dashboard and Rebalance panel (empty-state is acceptable without seeded prices).
 */
test("portfolio detail shows risk + rebalance surfaces", async ({ page }) => {
  const email = `e2e-port-${Date.now()}@test.local`;

  await page.goto("/register");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill("correct-horse-battery-staple");
  await page.getByRole("button", { name: /create account/i }).click();

  // Go to Portfolios and create one.
  await page.getByRole("link", { name: "Portfolios" }).click();
  await page.getByPlaceholder(/name a new portfolio/i).fill("E2E Risk");
  await page.getByRole("button", { name: /new portfolio/i }).click();

  // Open its detail page.
  await page.getByRole("link", { name: /E2E Risk/ }).click();

  // Builder surface carries the new Risk + Rebalance sections.
  await expect(page.getByRole("heading", { name: "Risk", exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Rebalance", exact: true })).toBeVisible();
  await expect(page.getByLabel(/drift threshold/i)).toBeVisible();
  await expect(page.getByRole("button", { name: /check drift/i })).toBeVisible();
});
