import { expect, test, type Page } from "@playwright/test";

import { collectErrors, signUpAndSignIn } from "./helpers";

/** The public website: landing page, pricing, legal pages, analytics, SEO files. */

const PUBLIC_PAGES = [
  "/",
  "/pricing",
  "/legal/imprint",
  "/legal/privacy",
  "/legal/terms",
  "/legal/dpa",
];

const DARK_BG = "rgb(13, 18, 32)";
const LIGHT_BG = "rgb(241, 243, 246)";

type Plans = {
  currency: string;
  plans: { id: string; name: string; price_monthly: number; highlighted: boolean }[];
};

async function background(page: Page): Promise<string> {
  return page.evaluate(() => getComputedStyle(document.body).backgroundColor);
}

test("landing page has every section and the plans from the API", async ({ page }) => {
  const errors = collectErrors(page);
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  for (const name of [
    "What is already done",
    "How it works",
    "Simple pricing",
    "Questions and answers",
  ]) {
    await expect(page.getByRole("heading", { level: 2, name })).toBeVisible();
  }
  // The app preview in the hero (a video when one is configured).
  await expect(page.getByRole("img", { name: /Preview of/ })).toBeVisible();

  // Prices come from the backend: the page shows exactly what the API says.
  const plans = (await (await page.request.get("/api/billing/plans")).json()) as Plans;
  const pricing = page.locator("#pricing");
  for (const plan of plans.plans) {
    const card = pricing.locator(`[data-plan="${plan.id}"]`);
    await expect(card.getByRole("heading", { name: plan.name })).toBeVisible();
    await expect(card).toContainText(`€${plan.price_monthly / 100}`);
  }
  const highlighted = plans.plans.find((p) => p.highlighted);
  if (highlighted) {
    await expect(pricing.locator(`[data-plan="${highlighted.id}"]`)).toContainText("Recommended");
  }
  expect(errors).toEqual([]);
});

test("the main button leads to sign-up, and FAQ answers open", async ({ page }) => {
  await page.goto("/");
  const faq = page.locator("#faq");
  const first = faq.locator("details").first();
  await first.locator("summary").click();
  await expect(first).toHaveAttribute("open", "");
  await expect(first.locator("p")).toBeVisible();

  await page.getByRole("banner").getByRole("link", { name: "Create account" }).click();
  await expect(page).toHaveURL(/\/signup$/);
  await expect(page.getByRole("link", { name: "Terms" })).toHaveAttribute("href", "/legal/terms");
});

test("pricing page compares the plans", async ({ page }) => {
  await page.goto("/pricing");
  await expect(page.getByRole("heading", { level: 1, name: "Simple pricing" })).toBeVisible();
  const table = page.getByRole("table", { name: "What each plan includes" });
  await expect(table.getByRole("rowheader", { name: "API keys" })).toBeVisible();
  await expect(table).toContainText("Unlimited");
  await expect(page.getByText("All prices plus VAT.")).toBeVisible();
});

test("public pages load without errors in light and dark mode", async ({ page }) => {
  const errors = collectErrors(page);
  for (const scheme of ["light", "dark"] as const) {
    await page.emulateMedia({ colorScheme: scheme });
    for (const path of PUBLIC_PAGES) {
      await page.goto(path);
      await page.waitForLoadState("networkidle");
      await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
      expect(await background(page), path).toBe(scheme === "dark" ? DARK_BG : LIGHT_BG);
    }
  }
  expect(errors).toEqual([]);
});

test("legal pages are linked from every public page and warn while unreviewed", async ({
  page,
}) => {
  await page.goto("/pricing");
  const footer = page.getByRole("contentinfo");
  for (const [name, heading] of [
    ["Imprint", "Imprint"],
    ["Privacy policy", "Privacy policy"],
    ["Terms", "Terms"],
    ["Data processing agreement", "Data processing agreement"],
  ]) {
    await footer.getByRole("link", { name, exact: true }).click();
    await expect(page.getByRole("heading", { level: 1, name: heading })).toBeVisible();
    // Until config/legal.ts is filled in and reviewed, a warning box is shown.
    await expect(page.getByRole("note", { name: "Template warning" })).toBeVisible();
  }
});

test("the website works without JavaScript (menu and FAQ)", async ({ browser }) => {
  const context = await browser.newContext({
    javaScriptEnabled: false,
    viewport: { width: 390, height: 844 },
  });
  const page = await context.newPage();
  await page.goto("/");
  await page.getByLabel("Open menu").click();
  await expect(page.getByRole("navigation", { name: "Website menu" })).toBeVisible();
  const first = page.locator("#faq details").first();
  await first.locator("summary").click();
  await expect(first.locator("p")).toBeVisible();
  await context.close();
});

test("a signed-in visitor sees 'Open the app'", async ({ page }) => {
  await signUpAndSignIn(page);
  await page.goto("/");
  await page.getByRole("banner").getByRole("link", { name: "Open the app" }).click();
  await expect(page).toHaveURL(/\/dashboard$/);
});

test("page views are sent without query strings or fragments", async ({ page }) => {
  const sent: { name: string; path: string; referrer?: string }[] = [];
  await page.route("**/api/analytics/event", async (route) => {
    sent.push(route.request().postDataJSON());
    await route.fulfill({ status: 204 });
  });
  // A one-time token in the address must never leave the browser in analytics.
  await page.goto("/reset-password?token=very-secret#x");
  await expect.poll(() => sent.length).toBeGreaterThan(0);
  expect(sent[0]).toMatchObject({ name: "pageview", path: "/reset-password" });
  expect(JSON.stringify(sent)).not.toContain("very-secret");

  // Moving to another page in the app sends one more page view.
  await page.goto("/");
  await page.getByRole("banner").getByRole("link", { name: "Pricing" }).click();
  await expect.poll(() => sent.map((e) => e.path)).toContain("/pricing");
});

test("no page views when the browser asks not to be tracked", async ({ page }) => {
  let count = 0;
  await page.route("**/api/analytics/event", async (route) => {
    count += 1;
    await route.fulfill({ status: 204 });
  });
  await page.addInitScript(() => {
    Object.defineProperty(navigator, "globalPrivacyControl", { value: true });
  });
  await page.goto("/pricing");
  await page.waitForLoadState("networkidle");
  expect(count).toBe(0);
});

test("the analytics endpoint answers 204 (off by default)", async ({ request }) => {
  const response = await request.post("/api/analytics/event", { data: { path: "/" } });
  expect(response.status()).toBe(204);
});

test("robots.txt and sitemap.xml list the public pages only", async ({ request }) => {
  const robots = await (await request.get("/robots.txt")).text();
  expect(robots).toContain("Disallow: /dashboard");
  expect(robots).toContain("Disallow: /settings");
  expect(robots).toMatch(/Sitemap: https?:\/\/.+\/sitemap\.xml/);
  const sitemap = await (await request.get("/sitemap.xml")).text();
  for (const path of ["/pricing", "/legal/privacy"]) expect(sitemap).toContain(`${path}</loc>`);
  expect(sitemap).not.toContain("/dashboard");
});

test("no errors on the landing page when a browser extension changes it", async ({ page }) => {
  await page.addInitScript(() => {
    document.addEventListener("DOMContentLoaded", () => {
      const style = document.createElement("style");
      style.textContent = "body[unresolved] { opacity: 0; }";
      document.head.prepend(style);
      document.body.prepend(document.createTextNode(" "));
      document.documentElement.setAttribute("data-extension", "1");
    });
  });
  const errors = collectErrors(page);
  await page.goto("/");
  await page.waitForLoadState("networkidle");
  expect(errors.filter((e) => !/hydrat/i.test(e))).toEqual([]);
  await page.getByRole("banner").getByRole("link", { name: "Pricing" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Simple pricing" })).toBeVisible();
});
