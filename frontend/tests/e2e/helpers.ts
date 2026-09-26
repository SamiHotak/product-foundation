import { expect, type APIRequestContext, type Page } from "@playwright/test";

/** Mailpit catches every email in dev/CI. Inside Docker it is http://mailpit:8025. */
const MAILPIT = process.env.MAILPIT_URL ?? "http://localhost:8025";

export const PASSWORD = "correct horse battery";

/** A fresh, unique address for each test. */
export function newEmail(prefix = "e2e"): string {
  return `${prefix}-${Date.now()}-${Math.floor(Math.random() * 1e6)}@example.com`;
}

type MailpitSummary = { ID: string; Subject: string };

/** Wait for the newest email to `to` (optionally whose subject contains `subject`). */
export async function waitForEmail(
  request: APIRequestContext,
  to: string,
  subject = "",
): Promise<{ subject: string; text: string }> {
  let found: MailpitSummary | undefined;
  await expect
    .poll(
      async () => {
        const res = await request.get(`${MAILPIT}/api/v1/search`, {
          params: { query: `to:"${to}"` },
        });
        const body = (await res.json()) as { messages: MailpitSummary[] };
        found = body.messages.find((m) => m.Subject.includes(subject));
        return Boolean(found);
      },
      { timeout: 20_000, message: `email to ${to} (${subject})` },
    )
    .toBe(true);
  const message = await request.get(`${MAILPIT}/api/v1/message/${found!.ID}`);
  const body = (await message.json()) as { Subject: string; Text: string };
  return { subject: body.Subject, text: body.Text };
}

/** The path + token of the link in an email, e.g. "/verify-email?token=abc". */
export function linkPath(text: string, path: string): string {
  const match = text.match(new RegExp(`${path}\\?token=[A-Za-z0-9_-]+`));
  expect(match, `link to ${path} in email`).not.toBeNull();
  return match![0];
}

/**
 * Create a verified, signed-in user fast (through the API, not the UI).
 * The cookies land in the page's browser context.
 */
export async function signUpAndSignIn(page: Page, name = "Test User"): Promise<string> {
  const email = newEmail();
  const signup = await page.request.post("/api/auth/signup", {
    data: { name, email, password: PASSWORD },
  });
  expect(signup.status()).toBe(202);
  const mail = await waitForEmail(page.request, email, "Confirm");
  const token = linkPath(mail.text, "/verify-email").split("token=")[1];
  const verify = await page.request.post("/api/auth/verify-email", { data: { token } });
  expect(verify.status()).toBe(200);
  return email;
}
