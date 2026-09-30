import { readFile } from "node:fs/promises";

import { expect, test } from "@playwright/test";

import { collectErrors, makeAdmin, signUpAndSignIn, toasts } from "./helpers";

/**
 * Phase 4B, clicked through like real users: files (upload straight to the S3 storage,
 * checks, download, delete), the AI summary (pretend model locally), "Try the demo", and
 * the admin area (numbers, AI kill switch, view as a customer).
 */

test("files: upload, refuse a fake file, download, delete", async ({ page }) => {
  const errors = collectErrors(page);
  await signUpAndSignIn(page, "Fiona Files");
  await page.goto("/files");
  await page.waitForLoadState("networkidle");
  await expect(page.getByRole("heading", { name: "No files yet" })).toBeVisible();

  // Upload two files at once: one real, one text file pretending to be a PNG.
  const notes = "Kick-off notes\nShoot on 14 October.\nÄpfel und Birnen.\n";
  await page.locator("#file-input").setInputFiles([
    { name: "Kick-off notes.txt", mimeType: "text/plain", buffer: Buffer.from(notes) },
    { name: "photo.png", mimeType: "image/png", buffer: Buffer.from("<script>x</script>") },
  ]);
  const row = page.locator('[data-file="Kick-off notes.txt"]');
  await expect(row).toBeVisible();
  await expect(row).toContainText("Fiona Files");
  const refused = page.locator('[data-upload="photo.png"]');
  await expect(refused).toHaveAttribute("data-phase", "error");
  await expect(refused).toContainText("not a real PNG image");
  await expect(page.locator('[data-file="photo.png"]')).toHaveCount(0);

  // Download: a short-lived link straight from the storage, saved with the original name.
  const downloadPromise = page.waitForEvent("download");
  await row.getByRole("button", { name: "Download Kick-off notes.txt" }).click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toBe("Kick-off notes.txt");
  expect(await readFile((await download.path())!, "utf8")).toBe(notes);

  // Storage counts against the plan.
  await page.goto("/settings/billing");
  await page.waitForLoadState("networkidle");
  await expect(page.locator('[data-metric="storage_mb"]')).toContainText("1 MB of 100 MB");

  await page.goto("/files");
  await page.waitForLoadState("networkidle");
  await row.getByRole("button", { name: "Delete Kick-off notes.txt" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Delete file" }).click();
  await expect(toasts(page)).toContainText("deleted");
  await expect(page.getByRole("heading", { name: "No files yet" })).toBeVisible();
  expect(errors.filter((e) => !e.includes("status of 400"))).toEqual([]);
});

test("AI summary runs as a job and counts against the plan", async ({ page }) => {
  const errors = collectErrors(page);
  await signUpAndSignIn(page, "Aiden AI");
  await page.goto("/dashboard");
  await page.waitForLoadState("networkidle");
  const panel = page.locator("#ai");
  await panel.getByRole("button", { name: "Use a sample text" }).click();
  await panel.getByRole("button", { name: "Summarize" }).click();
  const summary = page.getByTestId("ai-summary");
  await expect(summary).toBeVisible();
  await expect(summary.getByRole("heading")).toContainText("Bäckerei Lange");
  await expect(summary.getByRole("listitem").first()).toBeVisible();
  await expect(summary).toContainText("tokens");

  await page.goto("/settings/billing");
  await page.waitForLoadState("networkidle");
  await expect(page.locator('[data-metric="ai_requests_per_month"]')).toContainText("1 of 50");
  expect(errors).toEqual([]);
});

test("try the demo: sample data, read-only, then sign up", async ({ page }) => {
  const errors = collectErrors(page);
  await page.goto("/login");
  await page.waitForLoadState("networkidle");
  await page.getByRole("button", { name: "Try the demo, no sign-up" }).click();
  await expect(page).toHaveURL(/\/dashboard$/);
  const banner = page.getByTestId("demo-banner");
  await expect(banner).toContainText("shared demo");

  await page.goto("/files");
  await page.waitForLoadState("networkidle");
  await expect(page.locator('[data-file="Price list 2026.csv"]')).toBeVisible();
  await expect(page.getByText("Choose files")).toHaveCount(0);
  await expect(page.getByText("you can download the sample files, not upload")).toBeVisible();

  await page.goto("/settings/members");
  await page.waitForLoadState("networkidle");
  await expect(page.locator('[data-member-email="mia.weber@example.com"]')).toBeVisible();

  // AI works in the demo, with the sample text only (visitors share one account).
  await page.goto("/dashboard");
  await page.waitForLoadState("networkidle");
  const ai = page.locator("#ai");
  await expect(ai).toContainText("Demo: sample text only");
  await ai.getByRole("button", { name: "Use a sample text" }).click();
  await ai.getByRole("button", { name: "Summarize" }).click();
  await expect(page.getByTestId("ai-summary")).toContainText("Bäckerei Lange");

  // Changes are refused with a friendly message.
  await page.goto("/settings/workspace");
  await page.waitForLoadState("networkidle");
  const form = page.getByRole("form", { name: "Workspace name" });
  await form.getByLabel("Name").fill("Mine now");
  await form.getByRole("button", { name: "Save name" }).click();
  await expect(page.getByRole("alert").filter({ hasText: "shared demo" })).toBeVisible();

  await banner.getByRole("button", { name: "Create your free account" }).click();
  await expect(page).toHaveURL(/\/signup$/);
  expect(errors.filter((e) => !e.includes("status of 403"))).toEqual([]);
});

test("admin: numbers, AI kill switch, view the app as a customer", async ({ browser, page }) => {
  const errors = collectErrors(page);
  // A customer in their own browser.
  const customerContext = await browser.newContext();
  const customer = await customerContext.newPage();
  const customerEmail = await signUpAndSignIn(customer, "Carla Customer");

  await signUpAndSignIn(page, "Adam Admin");
  // Not an admin yet: no menu item, and /admin does not exist for them.
  await page.goto("/dashboard");
  await page.waitForLoadState("networkidle");
  await expect(page.getByRole("link", { name: "Admin" })).toHaveCount(0);
  await makeAdmin(page);

  await page.goto("/dashboard");
  await page.waitForLoadState("networkidle");
  await page.getByRole("link", { name: "Admin" }).first().click();
  await expect(page).toHaveURL(/\/admin$/);
  await expect(page.getByText("Workspaces", { exact: true }).first()).toBeVisible();

  // The kill switch: customers see "paused" at once.
  await page.getByRole("button", { name: "Pause all AI" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Pause AI" }).click();
  await expect(page.getByText("Paused", { exact: true })).toBeVisible();
  try {
    await customer.goto("/dashboard");
    await customer.waitForLoadState("networkidle");
    await expect(customer.locator("#ai")).toContainText("AI features are paused right now.");
  } finally {
    await page.getByRole("button", { name: "Resume AI" }).click();
    await expect(page.getByText("Running", { exact: true })).toBeVisible();
  }

  // View the app as the customer (support).
  await page.getByRole("link", { name: "Users" }).click();
  await page.waitForLoadState("networkidle");
  await page.getByLabel("Search name or email").fill(customerEmail);
  const userRow = page.locator(`[data-user-email="${customerEmail}"]`);
  await userRow.getByRole("button", { name: "View as" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "View as this user" }).click();
  await expect(page).toHaveURL(/\/dashboard$/);
  const note = page.getByTestId("impersonating");
  await expect(note).toContainText("Carla Customer");
  await expect(page.getByRole("link", { name: "Admin" })).toHaveCount(0);

  // The customer's audit log shows that support looked.
  await page.goto("/settings/audit-log");
  await page.waitForLoadState("networkidle");
  await expect(page.locator('[data-action="admin.impersonation_started"]')).toBeVisible();

  await note.getByRole("button", { name: "Stop viewing" }).click();
  await expect(page).toHaveURL(/\/admin\/users$/);
  await expect(page.getByTestId("impersonating")).toHaveCount(0);
  await customerContext.close();
  expect(errors).toEqual([]);
});
