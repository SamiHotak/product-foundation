import { expect, test } from "@playwright/test";

/**
 * Smoke test for the whole platform: the app loads, every service is healthy,
 * and a real background job runs in the Celery worker with live progress.
 */

test("landing page opens the app", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("link", { name: "Open the app" }).click();
  await expect(page).toHaveURL(/\/dashboard$/);
  await expect(page.getByRole("heading", { name: "Dashboard", level: 1 })).toBeVisible();
});

test("system status shows every service working", async ({ page }) => {
  await page.goto("/dashboard");
  const status = page.getByRole("region", { name: "System status" });
  for (const service of ["API", "Database", "Redis (queue and cache)"]) {
    await expect(status.getByRole("listitem").filter({ hasText: service })).toContainText(
      "working",
    );
  }
});

test("example job shows live progress and finishes", async ({ page }) => {
  await page.goto("/dashboard");
  const jobs = page.getByRole("region", { name: "Background jobs" });
  await expect(jobs.getByRole("button", { name: "Run example job" })).toBeEnabled();

  const created = page.waitForResponse(
    (res) => res.url().endsWith("/api/jobs/example") && res.request().method() === "POST",
  );
  await jobs.getByRole("button", { name: "Run example job" }).click();
  const job = (await (await created).json()) as { id: string };
  expect((await created).status()).toBe(202);

  const row = page.locator(`[data-job-id="${job.id}"]`);
  await expect(row).toBeVisible();
  // Live progress: the worker reports steps while the job runs.
  await expect(row).toHaveAttribute("data-job-status", "running");
  await expect(row).toContainText(/Step \d of 5/);
  await expect(row.getByRole("progressbar")).toBeVisible();
  // ... and finishes (5 one-second steps).
  await expect(row).toHaveAttribute("data-job-status", "done", { timeout: 45_000 });
  await expect(row).toContainText("100%");
  await expect(row).toContainText("Finished 5 steps.");
});

test("a failing job shows a clear error", async ({ page }) => {
  await page.goto("/dashboard");
  const jobs = page.getByRole("region", { name: "Background jobs" });
  const created = page.waitForResponse((res) => res.url().endsWith("/api/jobs/example"));
  await jobs.getByRole("button", { name: "Run a job that fails" }).click();
  const job = (await (await created).json()) as { id: string };

  const row = page.locator(`[data-job-id="${job.id}"]`);
  await expect(row).toHaveAttribute("data-job-status", "failed", { timeout: 45_000 });
  await expect(row).toContainText("Stopped at step 3 of 4 because you asked it to fail.");
});
