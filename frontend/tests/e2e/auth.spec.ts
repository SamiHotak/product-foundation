import { expect, test } from "@playwright/test";

import { linkPath, newEmail, PASSWORD, signUpAndSignIn, waitForEmail } from "./helpers";

/**
 * The main account flows, clicked through like a real user.
 * Emails are read from Mailpit.
 */

test("sign up, confirm email, land in own workspace", async ({ page }) => {
  const email = newEmail("signup");
  await page.goto("/signup");
  await page.getByLabel("Your name").fill("Ezat Hotak");
  await page.getByLabel("Work email").fill(email);
  await page.getByLabel("Password", { exact: true }).fill(PASSWORD);
  await page.getByRole("button", { name: "Create account" }).click();

  await expect(page.getByRole("heading", { name: "Check your inbox" })).toBeVisible();
  await expect(page.getByText(email)).toBeVisible();

  const mail = await waitForEmail(page.request, email, "Confirm your email");
  await page.goto(linkPath(mail.text, "/verify-email"));

  await expect(page).toHaveURL(/\/dashboard$/);
  await expect(page.getByRole("button", { name: /Workspace: Ezat's workspace/ })).toBeVisible();
  await page.getByRole("button", { name: "Open user menu" }).click();
  await expect(page.getByRole("menu")).toContainText(email);
});

test("sign-up form explains mistakes", async ({ page }) => {
  await page.goto("/signup");
  await page.getByLabel("Work email").fill("not-an-email");
  await page.getByLabel("Password", { exact: true }).fill("short");
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page.getByText("Enter your name.")).toBeVisible();
  await expect(page.getByText("Enter a valid email address.")).toBeVisible();
  await expect(page.getByText("Use at least 10 characters.")).toBeVisible();
});

test("signed-out visitors are sent to sign in", async ({ page }) => {
  await page.goto("/dashboard");
  await expect(page).toHaveURL(/\/login$/);
  await page.goto("/settings");
  await expect(page).toHaveURL(/\/login$/);
});

test("sign out, wrong password, then sign in", async ({ page }) => {
  const email = await signUpAndSignIn(page, "Sam Signin");
  await page.goto("/dashboard");
  await page.getByRole("button", { name: "Open user menu" }).click();
  await page.getByRole("menuitem", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/\/login$/);

  // The session really ended: the app sends us back to sign in.
  await page.goto("/dashboard");
  await expect(page).toHaveURL(/\/login$/);

  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password", { exact: true }).fill("wrong password");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.locator("form").getByRole("alert")).toContainText(
    "Email or password is wrong.",
  );

  await page.getByLabel("Password", { exact: true }).fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/dashboard$/);
  await expect(page.getByRole("button", { name: /Workspace: Sam's workspace/ })).toBeVisible();
});

test("unconfirmed account gets a new link from the sign-in page", async ({ page }) => {
  const email = newEmail("unverified");
  await page.request.post("/api/auth/signup", {
    data: { name: "Una", email, password: PASSWORD },
  });
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password", { exact: true }).fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.locator("form").getByRole("alert")).toContainText("Confirm your email first");
  await page.getByRole("button", { name: "Send a new confirmation link" }).click();
  await expect(page.getByText("New link sent")).toBeVisible();
});

test("forgot password: reset by email, old password stops working", async ({ page, browser }) => {
  const email = await signUpAndSignIn(page, "Rita Reset");
  // A second browser (like a phone) is signed in too; the reset must sign it out.
  const other = await browser.newContext();
  const otherPage = await other.newPage();
  await otherPage.request.post("/api/auth/login", { data: { email, password: PASSWORD } });
  expect((await otherPage.request.get("/api/auth/me")).status()).toBe(200);

  await page.request.post("/api/auth/logout");
  await page.goto("/login");
  await page.getByRole("link", { name: "Forgot password?" }).click();
  await expect(page.getByRole("heading", { name: "Reset your password" })).toBeVisible();
  await page.getByLabel("Email").fill(email);
  await page.getByRole("button", { name: "Email me a reset link" }).click();
  await expect(page.getByText("a reset link is on its way")).toBeVisible();

  const mail = await waitForEmail(page.request, email, "Reset your");
  await page.goto(linkPath(mail.text, "/reset-password"));
  await page.getByLabel("New password", { exact: true }).fill("a brand new password");
  await page.getByLabel("Repeat new password").fill("a brand new password");
  await page.getByRole("button", { name: "Save new password" }).click();
  await expect(page).toHaveURL(/\/dashboard$/);

  expect((await otherPage.request.get("/api/auth/me")).status()).toBe(401);
  const old = await other.request.post("/api/auth/login", { data: { email, password: PASSWORD } });
  expect(old.status()).toBe(401);
  await other.close();
});

test("create a workspace and switch between workspaces", async ({ page }) => {
  await signUpAndSignIn(page, "Wanda Work");
  await page.goto("/dashboard");

  // A job in the first workspace.
  const jobs = page.getByRole("region", { name: "Background jobs" });
  await jobs.getByRole("button", { name: "Run example job" }).click();
  await expect(jobs.getByRole("list", { name: "Recent jobs" }).getByRole("listitem")).toHaveCount(
    1,
  );

  await page.getByRole("button", { name: /Workspace: Wanda's workspace/ }).click();
  await page.getByRole("menuitem", { name: "Create workspace" }).click();
  await page.getByLabel("Workspace name").fill("Client project");
  await page.getByRole("button", { name: "Create workspace" }).click();

  // The new workspace is active and has its own (empty) data.
  await expect(page.getByRole("button", { name: /Workspace: Client project/ })).toBeVisible();
  await expect(page.getByText("No jobs yet.")).toBeVisible();

  await page.getByRole("button", { name: /Workspace: Client project/ }).click();
  await page.getByRole("menuitem", { name: /Wanda's workspace/ }).click();
  await expect(page.getByRole("button", { name: /Workspace: Wanda's workspace/ })).toBeVisible();
  await expect(jobs.getByRole("list", { name: "Recent jobs" }).getByRole("listitem")).toHaveCount(
    1,
  );
});

test("auth pages load without console errors", async ({ page }) => {
  const errors: string[] = [];
  page.on("console", (msg) => {
    if (msg.type() === "error") errors.push(msg.text());
  });
  page.on("pageerror", (err) => errors.push(err.message));
  for (const path of [
    "/login",
    "/signup",
    "/forgot-password",
    "/verify-email?email=a%40b.co",
    "/reset-password",
  ]) {
    await page.goto(path);
    await page.waitForLoadState("networkidle");
  }
  expect(errors).toEqual([]);
});
