import { expect, test, type Browser, type Page } from "@playwright/test";

import { linkPath, newEmail, PASSWORD, signUpAndSignIn, waitForEmail } from "./helpers";

/**
 * Teams: invite -> accept -> role limits, API keys, and the audit trail.
 * Clicked through like real users, with emails read from Mailpit.
 */

function collectErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on("console", (msg) => {
    if (msg.type() === "error") errors.push(msg.text());
  });
  page.on("pageerror", (err) => errors.push(err.message));
  return errors;
}

/** The owner invites `email` from Settings → Workspace; returns the invite link path. */
async function invite(page: Page, email: string, role: "Member" | "Admin"): Promise<string> {
  await page.goto("/settings/workspace");
  const form = page.getByRole("form", { name: "Invite someone" });
  await form.getByLabel("Invite by email").fill(email);
  await form.getByLabel("Role").selectOption({ label: role });
  await form.getByRole("button", { name: "Send invite" }).click();
  await expect(form.getByText(`Invite sent to ${email}`)).toBeVisible();
  await expect(page.getByRole("list", { name: "Open invites" })).toContainText(email);
  const mail = await waitForEmail(page.request, email, "invited you");
  return linkPath(mail.text, "/invite");
}

/** A new person opens the invite link in their own browser and creates an account. */
async function acceptAsNewUser(browser: Browser, link: string, name: string): Promise<Page> {
  const context = await browser.newContext();
  const page = await context.newPage();
  await page.goto(link);
  await expect(page.getByRole("heading", { name: /^Join .+'s workspace$/ })).toBeVisible();
  await page.getByLabel("Your name").fill(name);
  await page.getByLabel("Choose a password").fill(PASSWORD);
  await page.getByRole("button", { name: "Create account and join" }).click();
  await expect(page).toHaveURL(/\/dashboard$/);
  return page;
}

test("sign up, invite, accept, and role limits", async ({ page, browser }) => {
  const errors = collectErrors(page);
  await signUpAndSignIn(page, "Olivia Owner");
  const memberEmail = newEmail("member");
  const link = await invite(page, memberEmail, "Member");

  const member = await acceptAsNewUser(browser, link, "Mia Member");
  const memberErrors = collectErrors(member);
  await expect(member.getByRole("button", { name: /Workspace: Olivia's workspace/ })).toBeVisible();

  // A member sees the team, but none of the admin tools.
  await member.goto("/settings/workspace");
  const settingsNav = member.getByRole("navigation", { name: "Settings" });
  await expect(settingsNav.getByRole("link", { name: "Workspace" })).toBeVisible();
  await expect(settingsNav.getByRole("link", { name: "API keys" })).toHaveCount(0);
  await expect(settingsNav.getByRole("link", { name: "Audit log" })).toHaveCount(0);
  const members = member.getByRole("list", { name: "Members" });
  await expect(members).toContainText("Olivia Owner");
  await expect(members).toContainText("Mia Member (you)");
  await expect(member.getByLabel("Invite by email")).toHaveCount(0);
  await expect(member.getByRole("combobox", { name: /Role of/ })).toHaveCount(0);
  await member.goto("/settings/api-keys");
  await expect(
    member.getByText("Only owners and admins can see and create API keys."),
  ).toBeVisible();
  // The API refuses too (hiding buttons is not the security).
  const forbidden = await member.request.post("/api/organizations/current/invites", {
    data: { email: newEmail("sneaky") },
  });
  expect(forbidden.status()).toBe(403);

  // The owner makes Mia an admin; Mia's app shows the admin tools after a reload.
  await page.goto("/settings/workspace");
  await page.getByRole("combobox", { name: "Role of Mia Member" }).selectOption("admin");
  await expect(page.getByRole("combobox", { name: "Role of Mia Member" })).toHaveValue("admin");
  await member.goto("/settings/workspace");
  await expect(
    member.getByRole("navigation", { name: "Settings" }).getByRole("link", { name: "API keys" }),
  ).toBeVisible();
  await expect(member.getByLabel("Invite by email")).toBeVisible();

  // Everything is in the audit log.
  await page.goto("/settings/audit-log");
  const log = page.getByRole("region", { name: "Audit log" });
  await expect(log).toContainText(`Olivia Owner invited ${memberEmail} as member`);
  await expect(log).toContainText("Mia Member joined as member");
  await expect(log).toContainText(`changed the role of ${memberEmail} from member to admin`);

  expect(errors).toEqual([]);
  expect(memberErrors).toEqual([]);
  await member.context().close();
});

test("an existing user signs in from the invite link and joins", async ({ page, browser }) => {
  await signUpAndSignIn(page, "Owen Owner");
  // Bob already has an account (and is signed out in his own browser).
  const bobContext = await browser.newContext();
  const bob = await bobContext.newPage();
  const bobEmail = await signUpAndSignIn(bob, "Bob Builder");
  await bob.request.post("/api/auth/logout");

  const link = await invite(page, bobEmail, "Admin");
  await bob.goto(link);
  await expect(bob.getByRole("heading", { name: "Join Owen's workspace" })).toBeVisible();
  await bob.getByRole("link", { name: "Sign in to accept" }).click();
  await expect(bob).toHaveURL(/\/login\?next=/);
  await bob.getByLabel("Email").fill(bobEmail);
  await bob.getByLabel("Password", { exact: true }).fill(PASSWORD);
  await bob.getByRole("button", { name: "Sign in" }).click();

  // Back on the invite page, now signed in with the right email.
  await expect(bob).toHaveURL(/\/invite\?token=/);
  await bob.getByRole("button", { name: "Join workspace" }).click();
  await expect(bob).toHaveURL(/\/dashboard$/);
  await expect(bob.getByRole("button", { name: /Workspace: Owen's workspace/ })).toBeVisible();
  await bobContext.close();
});

test("the owner can't leave, and transfers ownership", async ({ page, browser }) => {
  await signUpAndSignIn(page, "Tina Transfer");
  const link = await invite(page, newEmail("heir"), "Member");
  const heir = await acceptAsNewUser(browser, link, "Hugo Heir");

  await page.goto("/settings/workspace");
  await expect(page.getByText("You own this workspace, so you can't leave it.")).toBeVisible();
  await page.getByRole("button", { name: "More actions for Hugo Heir" }).click();
  await page.getByRole("menuitem", { name: "Make owner" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Make owner" }).click();
  await expect(page.getByRole("list", { name: "Members" })).toContainText("Owner");
  await expect(page.getByRole("button", { name: "Leave Tina's workspace" })).toBeVisible();

  await heir.goto("/settings/privacy");
  await expect(heir.getByRole("heading", { name: "Delete this workspace" })).toBeVisible();
  await heir.context().close();
});

test("API key: create, copy once, use, revoke", async ({ page }) => {
  await signUpAndSignIn(page, "Kai Keys");
  await page.goto("/settings/api-keys");
  const form = page.getByRole("form", { name: "Create an API key" });
  await form.getByLabel("Name").fill("Nightly import");
  await form.getByRole("button", { name: "Create key" }).click();

  const reveal = page.getByRole("region", { name: "Your new API key" });
  await expect(reveal).toContainText("“Nightly import” is ready");
  const key = (await reveal.getByTestId("new-api-key").textContent())?.trim() ?? "";
  expect(key).toMatch(/^pf_[A-Za-z0-9_-]{40,}$/);
  await reveal.getByRole("button", { name: "I copied the key" }).click();
  await expect(page.getByRole("region", { name: "Your new API key" })).toHaveCount(0);

  // A script uses the key, without any cookie.
  const script = await page.context().browser()!.newContext();
  const ok = await script.request.get("/api/jobs", { headers: { Authorization: `Bearer ${key}` } });
  expect(ok.status()).toBe(200);
  const denied = await script.request.post("/api/jobs/example", {
    headers: { Authorization: `Bearer ${key}` },
    data: { steps: 1 },
  });
  expect(denied.status()).toBe(403); // read-only key

  const row = page.locator('[data-key-name="Nightly import"]');
  await expect(row).toContainText("Read jobs");
  await page.reload();
  await expect(row).toContainText(/Last used/);
  await row.getByRole("button", { name: "Revoke" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Revoke key" }).click();
  await expect(page.getByText("No API keys yet")).toBeVisible();
  const revoked = await script.request.get("/api/jobs", {
    headers: { Authorization: `Bearer ${key}` },
  });
  expect(revoked.status()).toBe(401);
  await script.close();
});
