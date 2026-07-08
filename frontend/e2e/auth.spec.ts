import { expect, test } from "@playwright/test";

/**
 * Auth flow E2E (needs FastAPI + Postgres + Next running). Registers a fresh user, lands in the
 * protected shell, then signs out back to the login surface — exercising the BFF proxy, the typed
 * client, the httpOnly refresh cookie, and the route-group guards end to end.
 */
test("register → protected shell → logout", async ({ page }) => {
  const email = `e2e-${Date.now()}@test.local`;

  await page.goto("/register");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill("correct-horse-battery-staple");
  await page.getByRole("button", { name: /create account/i }).click();

  // Lands on the overview inside the (app) shell.
  await expect(page.getByRole("heading", { name: /welcome back/i })).toBeVisible();

  // Sign out → back to the login surface.
  await page.getByRole("button", { name: /account menu/i }).click();
  await page.getByRole("menuitem", { name: /sign out/i }).click();
  await expect(page.getByRole("button", { name: /sign in/i })).toBeVisible();
});
