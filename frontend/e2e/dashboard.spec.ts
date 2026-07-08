import { expect, test } from "@playwright/test";

/**
 * Data UI E2E (needs FastAPI + Postgres with scores + Next). Registers, then verifies the dashboard,
 * stocks list, and rankings render live data from the API through the BFF + typed client.
 */
test("dashboard + stocks + rankings render live data", async ({ page }) => {
  const email = `e2e-dash-${Date.now()}@test.local`;

  await page.goto("/register");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill("correct-horse-battery-staple");
  await page.getByRole("button", { name: /create account/i }).click();

  // Dashboard bento: market-overview strip + top-ranked tile.
  await expect(page.getByText(/avg composite/i)).toBeVisible();
  await expect(page.getByText(/top ranked/i)).toBeVisible();

  // Stocks list: table renders real rows.
  await page.getByRole("link", { name: "Stocks" }).click();
  await expect(page.getByRole("columnheader", { name: /composite/i })).toBeVisible();
  await expect(page.getByText("HDFCBANK")).toBeVisible();

  // Rankings: leaderboard + entitlement note.
  await page.getByRole("link", { name: "Rankings" }).click();
  await expect(page.getByRole("heading", { name: "Rankings" })).toBeVisible();
  await expect(page.getByText(/free tier/i)).toBeVisible();
});
