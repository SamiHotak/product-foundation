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
