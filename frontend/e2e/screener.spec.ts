import { expect, test } from "@playwright/test";

/**
 * Screener + comparison E2E (needs FastAPI + Postgres with scores + Next). Registers, runs a
 * screen, saves it, then selects two names and opens the side-by-side comparison — the QV-040
 * US-01 payoff end to end.
 */
test("screen the universe, save it, and compare two names", async ({ page }) => {
  const email = `e2e-screener-${Date.now()}@test.local`;

  await page.goto("/register");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill("correct-horse-battery-staple");
  await page.getByRole("button", { name: /create account/i }).click();
  await expect(page.getByText(/avg composite/i)).toBeVisible();

  // Open the screener and run a permissive screen (composite ≥ 0 → the whole scored universe).
  await page.getByRole("link", { name: "Screener" }).click();
  await expect(page.getByRole("heading", { name: "Screener" })).toBeVisible();
  await page.getByLabel("Value").first().fill("0");
  await page.getByRole("button", { name: /run screen/i }).click();

  // Results render; the URL carries the shareable state.
  await expect(page.getByText(/match/i)).toBeVisible();
  await expect(page).toHaveURL(/f=composite_score/);

  // Save the current screen.
  await page.getByLabel("Screen name").fill(`e2e ${Date.now()}`);
  await page.getByRole("button", { name: /save screen/i }).click();
  await expect(page.getByText(/^Saved\.$/)).toBeVisible();

  // Select the first two rows and compare.
  const checkboxes = page.getByRole("checkbox");
  await checkboxes.nth(0).check();
  await checkboxes.nth(1).check();
  await page.getByRole("link", { name: /compare/i }).click();

  await expect(page.getByRole("heading", { name: "Compare" })).toBeVisible();
  await expect(page.getByText("Factor scores")).toBeVisible();
  await expect(page.getByRole("row", { name: /composite/i })).toBeVisible();
});
