import { expect, test } from "@playwright/test";

import { signUpAndSignIn, waitForEmail } from "./helpers";

/** GDPR: export my data as a ZIP, and schedule / cancel deleting the account. */

test("export my data and download the ZIP", async ({ page }) => {
  await signUpAndSignIn(page, "Dana Data");
  await page.goto("/settings/privacy");
  const block = page.getByRole("region", { name: "Download your data" });
  await block.getByRole("button", { name: "Export my data" }).click();

  // The real worker builds the ZIP; the row switches to a download link when done.
  const download = block.getByRole("link", { name: "Download" });
  await expect(download).toBeVisible({ timeout: 45_000 });
  await expect(block).toContainText(/my-data-\d{4}-\d{2}-\d{2}\.zip/);
  const [file] = await Promise.all([page.waitForEvent("download"), download.click()]);
  expect(file.suggestedFilename()).toMatch(/^my-data-.+\.zip$/);

  // Private: the export job is not in the workspace's job list for others,
  // and it shows in my own dashboard list.
  await page.goto("/dashboard");
  await expect(
    page.getByRole("list", { name: "Recent jobs" }).getByText("Data export"),
  ).toBeVisible();
});

test("schedule and cancel deleting my account", async ({ page }) => {
  const email = await signUpAndSignIn(page, "Del Delete");
  await page.goto("/settings/privacy");
  await page.getByRole("button", { name: "Delete my account" }).click();
  const dialog = page.getByRole("dialog");
  const confirm = dialog.getByRole("button", { name: "Delete my account" });
  await expect(confirm).toBeDisabled();
  await dialog.getByLabel(/Type your email/).fill(email);
  await confirm.click();

  // Every page warns about it now, and an email explains how to cancel.
  await expect(
    page.getByRole("status").filter({ hasText: "Your account will be deleted on" }),
  ).toBeVisible();
  await waitForEmail(page.request, email, "will be deleted");
  await page.goto("/dashboard");
  await expect(page.getByText(/Your account will be deleted on/)).toBeVisible();

  await page.getByRole("link", { name: "Keep my account" }).click();
  await expect(page).toHaveURL(/\/settings\/privacy$/);
  await page.getByRole("button", { name: "Keep my account" }).click();
  await expect(page.getByRole("button", { name: "Delete my account" })).toBeVisible();
  await expect(page.getByText(/Your account will be deleted on/)).toHaveCount(0);
});
