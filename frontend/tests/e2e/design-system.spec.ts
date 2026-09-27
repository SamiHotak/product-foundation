import { expect, test } from "@playwright/test";

import {
  collectErrors,
  linkPath,
  newEmail,
  PASSWORD,
  signUpAndSignIn,
  toasts,
  waitForEmail,
} from "./helpers";

/**
 * Phase 3A: the app shell and design system, clicked through like a real user.
 * Command palette, forms with validation, toasts, data table, onboarding, theming.
 */

const DARK_BG = "rgb(13, 18, 32)";

test("command palette: Ctrl+K, search, arrow keys, Enter", async ({ page }) => {
  const errors = collectErrors(page);
  await signUpAndSignIn(page, "Carla Commands");
  await page.goto("/dashboard");

  // Keyboard shortcut opens it; typing filters; Enter opens the page.
  await page.keyboard.press("Control+k");
  const input = page.getByRole("combobox", { name: "Search pages and commands" });
  await expect(input).toBeFocused();
  await input.fill("api keys");
  await expect(page.getByRole("option").first()).toContainText("API keys");
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/settings\/api-keys$/);
  await expect(page.getByRole("dialog")).toHaveCount(0);

  // The top bar button opens it too. Keywords work ("team" finds Members).
  await page.getByRole("button", { name: "Search and commands" }).click();
  await input.fill("team");
  const options = page.getByRole("option");
  await expect(options.first()).toContainText("Members");
  // Arrow keys move the highlight.
  await expect(options.first()).toHaveAttribute("aria-selected", "true");
  await page.keyboard.press("ArrowDown");
  await expect(options.nth(1)).toHaveAttribute("aria-selected", "true");
  await page.keyboard.press("ArrowUp");
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/settings\/members$/);

  // Actions: switch the theme.
  await page.keyboard.press("Control+k");
  await input.fill("dark theme");
  await page.keyboard.press("Enter");
  await expect
    .poll(() => page.evaluate(() => getComputedStyle(document.body).backgroundColor))
    .toBe(DARK_BG);

  // Nothing found, then Escape closes.
  await page.keyboard.press("Control+k");
  await input.fill("xyzzy");
  await expect(page.getByText("Nothing found for “xyzzy”.")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);

  expect(errors).toEqual([]);
});

test("command palette hides pages you may not use", async ({ page, browser }) => {
  await signUpAndSignIn(page, "Owner Olga");
  const memberEmail = newEmail("palette");
  const res = await page.request.post("/api/organizations/current/invites", {
    data: { email: memberEmail, role: "member" },
  });
  expect(res.status()).toBe(201);
  const token = linkPath(
    (await waitForEmail(page.request, memberEmail, "invited you")).text,
    "/invite",
  ).split("token=")[1];

  const context = await browser.newContext();
  const member = await context.newPage();
  const joined = await member.request.post("/api/invites/signup", {
    data: { token, name: "Mo Member", password: PASSWORD },
  });
  expect(joined.status()).toBe(200);
  await member.goto("/dashboard");
  await member.keyboard.press("Control+k");
  const input = member.getByRole("combobox", { name: "Search pages and commands" });
  for (const hidden of ["billing", "audit", "api keys"]) {
    await input.fill(hidden);
    await expect(member.getByText(`Nothing found for “${hidden}”.`)).toBeVisible();
  }
  // Members may see the team, but not invite.
  await input.fill("invite");
  await expect(member.getByRole("option", { name: /Members/ })).toBeVisible();
  await expect(member.getByRole("option", { name: /Invite someone/ })).toHaveCount(0);
  await input.fill("members");
  await expect(member.getByRole("option", { name: /Members/ })).toBeVisible();

  // The owner does see them.
  await page.goto("/dashboard");
  await page.keyboard.press("Control+k");
  await page.getByRole("combobox").fill("billing");
  await expect(page.getByRole("option", { name: /Billing/ })).toBeVisible();
  await context.close();
});

test("profile: validation, save, change password", async ({ page, browser }) => {
  const errors = collectErrors(page);
  const email = await signUpAndSignIn(page, "Pia Profile");
  await page.goto("/settings");

  // Validation: an empty name is refused with a clear message next to the field.
  const profile = page.getByRole("form", { name: "Profile" });
  const name = profile.getByLabel("Name");
  await name.fill("");
  await profile.getByRole("button", { name: "Save profile" }).click();
  await expect(profile.getByText("Enter your name.")).toBeVisible();
  await expect(name).toHaveAttribute("aria-invalid", "true");
  await expect(name).toBeFocused();

  // Save: toast, and the user menu shows the new initials.
  await name.fill("Pia Neumann");
  await expect(name).toHaveAttribute("aria-invalid", "false");
  await profile.getByRole("button", { name: "Save profile" }).click();
  await expect(toasts(page)).toContainText("Profile saved.");
  await page.getByRole("button", { name: "Open user menu" }).click();
  await expect(page.getByRole("menu")).toContainText("Pia Neumann");
  await page.keyboard.press("Escape");

  // Password: mismatch and wrong current password show under the right fields.
  const pw = page.getByRole("form", { name: "Password" });
  await pw.getByLabel("Current password").fill("not my password");
  await pw.getByLabel("New password", { exact: true }).fill("a much better passphrase");
  await pw.getByLabel("Repeat new password").fill("a much better passphras");
  await pw.getByRole("button", { name: "Change password" }).click();
  await expect(pw.getByText("The passwords are not the same.")).toBeVisible();
  await pw.getByLabel("Repeat new password").fill("a much better passphrase");
  await pw.getByRole("button", { name: "Change password" }).click();
  await expect(pw.getByText("Your current password is not right.")).toBeVisible();
  await expect(pw.getByLabel("Current password")).toBeFocused();

  await pw.getByLabel("Current password").fill(PASSWORD);
  await pw.getByRole("button", { name: "Change password" }).click();
  await expect(toasts(page)).toContainText("Password changed.");
  await expect(pw.getByLabel("Current password")).toHaveValue("");

  // The new password works in a fresh browser.
  const other = await browser.newContext();
  const login = await other.request.post(`${new URL(page.url()).origin}/api/auth/login`, {
    data: { email, password: "a much better passphrase" },
  });
  expect(login.status()).toBe(200);
  await other.close();
  // The browser logs the refused wrong password (400) itself; that one is expected.
  expect(errors.filter((e) => !e.includes("status of 400"))).toEqual([]);
});

test("onboarding checklist: steps tick, hide with undo, show again", async ({ page }) => {
  const errors = collectErrors(page);
  await signUpAndSignIn(page, "Otto Onboarding");
  await page.goto("/dashboard");
  const checklist = page.getByRole("region", { name: "Get started" });
  await expect(checklist).toContainText("1 of 4 done");
  await expect(checklist.locator('[data-step="verify_email"]')).toHaveAttribute(
    "data-done",
    "true",
  );

  // Running a job ticks its step without a reload.
  await page
    .getByRole("region", { name: "Background jobs" })
    .getByRole("button", { name: "Run example job" })
    .click();
  await expect(checklist.locator('[data-step="run_job"]')).toHaveAttribute("data-done", "true");
  await expect(checklist).toContainText("2 of 4 done");

  // A step's button leads to the right page.
  await checklist.getByRole("link", { name: "Create a key" }).click();
  await expect(page).toHaveURL(/\/settings\/api-keys$/);

  // Hide, undo from the toast, hide again: stays hidden after a reload.
  await page.goto("/dashboard");
  await checklist.getByRole("button", { name: "Hide checklist" }).click();
  await expect(checklist).toHaveCount(0);
  await toasts(page).getByRole("button", { name: "Undo" }).click();
  await expect(checklist).toBeVisible();
  await checklist.getByRole("button", { name: "Hide checklist" }).click();
  await expect(checklist).toHaveCount(0);
  await page.reload();
  await expect(page.getByRole("heading", { name: "Dashboard", level: 1 })).toBeVisible();
  await expect(checklist).toHaveCount(0);

  // Settings → Profile brings it back.
  await page.goto("/settings");
  await page.getByRole("button", { name: "Show checklist" }).click();
  await expect(toasts(page)).toContainText("The checklist is back on the dashboard.");
  await page.goto("/dashboard");
  await expect(checklist).toBeVisible();
  expect(errors).toEqual([]);
});

test("data table: pages, search, sort, clear", async ({ page }) => {
  const errors = collectErrors(page);
  await signUpAndSignIn(page, "Tom Table");
  for (let i = 1; i <= 12; i++) {
    const res = await page.request.post("/api/organizations/current/api-keys", {
      data: { name: `Key ${String(i).padStart(2, "0")}`, scopes: ["jobs:read"] },
    });
    expect(res.status()).toBe(201);
  }
  await page.goto("/settings/api-keys");
  const table = page.getByRole("table", { name: "API keys" });
  const rows = table.locator("tbody tr");
  await expect(rows).toHaveCount(10);
  await expect(page.getByText("1–10 of 12")).toBeVisible();
  await expect(rows.first()).toContainText("Key 01");

  // Next page.
  await page.getByRole("button", { name: "Next page" }).click();
  await expect(rows).toHaveCount(2);
  await expect(page.getByText("11–12 of 12")).toBeVisible();
  await expect(page.getByRole("button", { name: "Next page" })).toBeDisabled();

  // Sort by name, descending (second click).
  await page.getByRole("button", { name: "Previous page" }).click();
  const nameHeader = table.getByRole("columnheader", { name: /Name/ });
  await nameHeader.getByRole("button").click();
  await expect(nameHeader).toHaveAttribute("aria-sort", "descending");
  await expect(rows.first()).toContainText("Key 12");

  // Search (goes back to page 1), then nothing found, then clear.
  await page.getByRole("searchbox", { name: "Search keys" }).fill("key 07");
  await expect(rows).toHaveCount(1);
  await expect(page.getByText("1–1 of 1 (filtered from 12)")).toBeVisible();
  await page.getByRole("searchbox", { name: "Search keys" }).fill("nope");
  await expect(table).toContainText("Nothing matches “nope”.");
  await table.getByRole("button", { name: "Clear search and filters" }).click();
  await expect(rows).toHaveCount(10);

  // More rows per page.
  await page.getByLabel("Rows per page").selectOption("25");
  await expect(rows).toHaveCount(12);
  expect(errors).toEqual([]);
});

test("forms: workspace name is validated and saved with a toast", async ({ page }) => {
  await signUpAndSignIn(page, "Wim Workspace");
  await page.goto("/settings/workspace");
  const form = page.getByRole("form", { name: "Workspace name" });
  await form.getByLabel("Name").fill("   ");
  await form.getByRole("button", { name: "Save name" }).click();
  await expect(form.getByText("Give the workspace a name.")).toBeVisible();
  await form.getByLabel("Name").fill("Wim & Co");
  await form.getByRole("button", { name: "Save name" }).click();
  await expect(toasts(page)).toContainText("Workspace name saved.");
  await expect(page.getByRole("button", { name: /Workspace: Wim & Co/ })).toBeVisible();
  // Nothing changed since the save: the button waits for a change.
  await expect(form.getByRole("button", { name: "Save name" })).toBeDisabled();
});

test("theming: name, accent and fonts come from config/product.ts", async ({ page }) => {
  await signUpAndSignIn(page, "Theo Theme");
  await page.goto("/dashboard");
  await expect(page).toHaveTitle(/Dashboard · Foundation/);
  await expect(page.getByRole("link", { name: "Foundation home" }).first()).toBeVisible();
  const vars = await page.evaluate(() => {
    const style = getComputedStyle(document.documentElement);
    return {
      brand: style.getPropertyValue("--brand").trim().toLowerCase(),
      font: style.getPropertyValue("--brand-font").trim(),
      body: getComputedStyle(document.body).fontFamily,
      heading: getComputedStyle(document.querySelector("h1")!).fontFamily,
    };
  });
  expect(vars.brand).toBe("#244ba6");
  expect(vars.font).toBe('"Hanken Grotesk Variable"');
  expect(vars.body).toContain("Hanken Grotesk Variable");
  expect(vars.heading).toContain("Hanken Grotesk Variable");
});
