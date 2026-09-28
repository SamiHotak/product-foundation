import { expect, test } from "@playwright/test";

import { collectErrors, signUpAndSignIn, toasts, waitForEmail } from "./helpers";

/**
 * Phase 4A: plan limits and upgrading, clicked through like a real owner.
 *
 * Locally and in CI the "checkout" is the pretend page (BILLING_DEV_TOOLS), which changes
 * the plan through the same backend code as Stripe's webhook. With real Stripe test keys
 * in backend/.env, the checkout part is skipped here; test it by hand (docs/BILLING.md).
 */

test("limit reached -> see plans -> upgrade -> limit lifted -> cancel -> free", async ({
  page,
}) => {
  const errors = collectErrors(page);
  const email = await signUpAndSignIn(page, "Bea Billing");

  // Free plan: one API key.
  await page.goto("/settings/api-keys");
  await page.waitForLoadState("networkidle");
  const form = page.getByRole("form", { name: "Create an API key" });
  await form.getByLabel("Name").fill("First");
  await form.getByRole("button", { name: "Create key" }).click();
  await page.getByRole("button", { name: "I copied the key" }).click();
  await form.getByLabel("Name").fill("Second");
  await form.getByRole("button", { name: "Create key" }).click();
  const limit = form.getByRole("alert");
  await expect(limit).toContainText("The Free plan allows 1 API key.");
  await limit.getByRole("link", { name: "See plans" }).click();

  await expect(page).toHaveURL(/\/settings\/billing$/);
  await expect(page.getByTestId("current-plan")).toContainText("Free");
  const keysMeter = page.locator('[data-metric="api_keys"]');
  await expect(keysMeter).toContainText("1 of 1");
  await expect(keysMeter).toContainText("All used");

  const overview = await (await page.request.get("/api/billing/current")).json();
  test.skip(
    overview.provider !== "dev",
    "Real Stripe keys are set: test checkout by hand (docs/BILLING.md).",
  );

  // Choose Pro, yearly, with the free trial.
  await page.waitForLoadState("networkidle");
  await page.getByText("Yearly", { exact: true }).click();
  const pro = page.locator('[data-plan="pro"]');
  await expect(pro).toContainText("a year");
  await pro.getByRole("button", { name: "Try Pro free for 14 days" }).click();

  // The pretend checkout page (Stripe's page in production).
  await expect(page.getByRole("heading", { name: "Checkout: Pro" })).toBeVisible();
  await expect(page.getByText("Free for 14 days, then charged.")).toBeVisible();
  await page.getByRole("button", { name: "Pay (pretend)" }).click();

  // Back in the app: the new plan is there, and its limits apply at once.
  await expect(page).toHaveURL(/\/settings\/billing$/);
  await expect(toasts(page)).toContainText("is on the new plan");
  await expect(page.getByTestId("current-plan")).toContainText("Pro");
  await expect(page.getByTestId("current-plan")).toContainText("Free trial");
  await expect(page.locator('[data-metric="api_keys"]')).toContainText("1 of 10");
  expect((await waitForEmail(page.request, email, "trial has started")).text).toContain("Pro plan");

  await page.goto("/settings/api-keys");
  await page.waitForLoadState("networkidle");
  await form.getByLabel("Name").fill("Second");
  await form.getByRole("button", { name: "Create key" }).click();
  await expect(page.getByRole("region", { name: "Your new API key" })).toContainText(
    "“Second” is ready",
  );

  // Cancel in the (pretend) billing portal: back to free, nothing deleted.
  await page.goto("/settings/billing");
  await page.waitForLoadState("networkidle");
  await page.getByTestId("current-plan").getByRole("button", { name: "Manage billing" }).click();
  await expect(page.getByRole("heading", { name: "Billing portal" })).toBeVisible();
  await page.getByRole("button", { name: "Cancel now" }).click();
  await expect(page.getByText("No paid plan.")).toBeVisible();
  await page.getByRole("link", { name: "Back to the app" }).click();
  await expect(page).toHaveURL(/\/settings\/billing$/);
  await expect(page.getByTestId("current-plan")).toContainText("Free");
  await expect(page.locator('[data-metric="api_keys"]')).toContainText("2 of 1");
  await waitForEmail(page.request, email, "on the Free plan now");

  // A second trial is not offered, and the audit log tells the story.
  await expect(page.locator('[data-plan="pro"]').getByRole("button")).toHaveText("Upgrade to Pro");
  await page.goto("/settings/audit-log");
  await expect(page.getByText("changed the plan from Free to Pro").first()).toBeVisible();
  await expect(page.getByText("changed the plan from Pro to Free").first()).toBeVisible();

  // The browser logs the expected "402 limit reached" answer; nothing else may appear.
  expect(errors.filter((e) => !e.includes("status of 402"))).toEqual([]);
});

test("cancelling checkout changes nothing and says so", async ({ page }) => {
  const errors = collectErrors(page);
  await signUpAndSignIn(page, "Cora Cancel");
  const overview = await (await page.request.get("/api/billing/current")).json();
  test.skip(overview.provider !== "dev", "Real Stripe keys are set.");
  await page.goto("/settings/billing");
  await page.waitForLoadState("networkidle");
  await page.locator('[data-plan="business"]').getByRole("button").click();
  await page.getByRole("button", { name: "Back without paying" }).click();
  await expect(page.getByText("Checkout cancelled. Nothing was charged.")).toBeVisible();
  await expect(page.getByTestId("current-plan")).toContainText("Free");
  expect(errors).toEqual([]);
});
