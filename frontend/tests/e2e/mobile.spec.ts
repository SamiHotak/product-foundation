import { expect, test } from "@playwright/test";

import { signUpAndSignIn } from "./helpers";

test("phone: menu opens and the jobs panel fits the screen", async ({ page }) => {
  await signUpAndSignIn(page);
  await page.goto("/dashboard");
  await page.getByRole("button", { name: "Open menu" }).click();
  await expect(page.getByRole("navigation", { name: "Main" })).toBeVisible();
  await page.keyboard.press("Escape");

  const jobs = page.getByRole("region", { name: "Background jobs" });
  await expect(jobs.getByRole("button", { name: "Run example job" })).toBeVisible();
  // No sideways scrolling on a phone.
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow).toBeLessThanOrEqual(0);
});

test("phone: sign-in page fits the screen", async ({ page }) => {
  await page.goto("/login");
  await expect(page.getByRole("button", { name: "Sign in" })).toBeVisible();
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow).toBeLessThanOrEqual(0);
});

test("phone: settings pages fit the screen", async ({ page }) => {
  await signUpAndSignIn(page);
  for (const path of [
    "/settings",
    "/settings/workspace",
    "/settings/members",
    "/settings/billing",
    "/settings/api-keys",
    "/settings/privacy",
  ]) {
    await page.goto(path);
    await expect(page.getByRole("navigation", { name: "Settings" })).toBeVisible();
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow, path).toBeLessThanOrEqual(0);
  }
});

test("phone: every public page fits the screen", async ({ page }) => {
  for (const path of [
    "/",
    "/pricing",
    "/legal/imprint",
    "/legal/privacy",
    "/legal/terms",
    "/legal/dpa",
    "/signup",
    "/forgot-password",
  ]) {
    await page.goto(path);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow, path).toBeLessThanOrEqual(0);
  }
});

test("phone: website menu opens, and closes after choosing a link", async ({ page }) => {
  await page.goto("/");
  await page.getByLabel("Open menu").click();
  const menu = page.getByRole("navigation", { name: "Website menu" });
  await expect(menu).toBeVisible();
  await menu.getByRole("link", { name: "Pricing" }).click();
  await expect(page).toHaveURL(/\/pricing$/);
  await expect(menu).toBeHidden();
  // Escape closes it too.
  await page.getByLabel("Open menu").click();
  await expect(menu).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(menu).toBeHidden();
});
