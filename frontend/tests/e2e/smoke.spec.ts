import { expect, test } from "@playwright/test";

import { signUpAndSignIn } from "./helpers";

// Every test here uses the app, so each starts with a fresh signed-in user.
test.beforeEach(async ({ page }, testInfo) => {
  if (testInfo.title !== "landing page links to sign in") await signUpAndSignIn(page);
});

/**
 * Smoke test for the whole platform: the app loads, every service is healthy,
 * and a real background job runs in the Celery worker with live progress.
 */

test("landing page links to sign in", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("link", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/login$/);
  await expect(page.getByRole("heading", { name: "Sign in", level: 1 })).toBeVisible();
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

const DARK_BG = "rgb(13, 18, 32)"; // --canvas in dark mode
const LIGHT_BG = "rgb(241, 243, 246)"; // --canvas in light mode

function collectErrors(page: import("@playwright/test").Page): string[] {
  const errors: string[] = [];
  page.on("console", (msg) => {
    if (msg.type() === "error") errors.push(msg.text());
  });
  page.on("pageerror", (err) => errors.push(err.message));
  return errors;
}

async function background(page: import("@playwright/test").Page): Promise<string> {
  return page.evaluate(() => getComputedStyle(document.body).backgroundColor);
}

test("pages load without console errors, in light and dark mode", async ({ page }) => {
  const errors = collectErrors(page);
  for (const scheme of ["light", "dark"] as const) {
    await page.emulateMedia({ colorScheme: scheme });
    for (const path of [
      "/",
      "/dashboard",
      "/settings",
      "/settings/workspace",
      "/settings/api-keys",
      "/settings/audit-log",
      "/settings/privacy",
    ]) {
      await page.goto(path);
      await page.waitForLoadState("networkidle");
      // "Same as device" (the default) follows the device with CSS only.
      expect(await background(page)).toBe(scheme === "dark" ? DARK_BG : LIGHT_BG);
    }
  }
  expect(errors).toEqual([]);
});

test("no errors when a browser extension changes the page", async ({ page }) => {
  // Extensions (password managers, translators, ...) edit the page before React loads.
  // React then re-renders on the client; that must not cause any errors.
  await page.addInitScript(() => {
    document.addEventListener("DOMContentLoaded", () => {
      // Seen on a real machine: an extension adds a <style> at the top of <head>.
      const style = document.createElement("style");
      style.textContent = "body[unresolved] { opacity: 0; }";
      document.head.prepend(style);
      document.body.prepend(document.createTextNode(" "));
      document.body.setAttribute("data-extension", "1");
      document.documentElement.setAttribute("data-extension", "1");
    });
  });
  const errors = collectErrors(page);
  await page.goto("/dashboard");
  await page.waitForLoadState("networkidle");
  await expect(page.getByRole("heading", { name: "Dashboard", level: 1 })).toBeVisible();
  // React always reports that the extension changed the HTML (a "hydration" warning);
  // that one is expected. Anything else (like "Encountered a script tag") is our bug.
  const ours = errors.filter((e) => !/hydrat/i.test(e));
  expect(ours).toEqual([]);
  // Our product accent color still applies (it lives on <html>, not in <head>).
  const accent = await page.evaluate(() =>
    getComputedStyle(document.documentElement).getPropertyValue("--brand").trim(),
  );
  expect(accent.toLowerCase()).toBe("#244ba6");
  // The page still works after React re-renders it.
  await expect(
    page.getByRole("region", { name: "Background jobs" }).getByRole("button", {
      name: "Run example job",
    }),
  ).toBeEnabled();
});

test("the theme choice is saved and correct on the first paint", async ({ page }) => {
  await page.emulateMedia({ colorScheme: "light" });
  await page.goto("/dashboard");
  await page.getByRole("button", { name: "Open user menu" }).click();
  await page.getByRole("menuitemradio", { name: "Dark" }).click();
  expect(await background(page)).toBe(DARK_BG);

  // After a reload the server sends dark HTML straight away (no white flash).
  const html = await (await page.request.get("/dashboard")).text();
  expect(html).toMatch(/<html[^>]*class="dark"/);
  await page.reload();
  expect(await background(page)).toBe(DARK_BG);

  // Back to "Same as device": follows the device again.
  await page.getByRole("button", { name: "Open user menu" }).click();
  await page.getByRole("menuitemradio", { name: "Same as device" }).click();
  expect(await background(page)).toBe(LIGHT_BG);
  await page.emulateMedia({ colorScheme: "dark" });
  expect(await background(page)).toBe(DARK_BG);
});
