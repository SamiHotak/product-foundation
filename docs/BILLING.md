# Billing, plan limits and emails (phase 4A)

This page explains how paid plans work, and walks you through **one real Stripe test-mode
payment** on your laptop, click by click.

## How it works (short)

```
Owner clicks "Try Pro free for 14 days"      (Settings → Billing)
  → POST /api/billing/checkout               creates ONE Stripe customer per workspace
  → Stripe Checkout page                     card, billing address, VAT ID (B2B)
  → back to /settings/billing?checkout=success   the page waits for the webhook
Stripe → POST /api/billing/webhook           signature checked, each event handled once,
                                             the subscription is read FRESH from Stripe
  → subscriptions table (plan, status, period end, trial)
  → the new limits apply on the next request
Owner clicks "Manage billing" → Stripe customer portal: card, invoices, VAT ID, change plan, cancel
```

- **One source for plans:** `backend/app/core/plans.py`. The website, checkout and the limits
  all read it. `make stripe-sync` copies it into Stripe. Checkout refuses to start while a
  Stripe price differs from plans.py (so the page never shows a different price than we charge).
- **Stripe is the source of truth.** Our `subscriptions` table is a fast copy, kept fresh by
  webhooks. Plans that keep working: `trialing`, `active`, `past_due` (Stripe is still retrying
  the card). Everything else = the free plan.
- **One trial per workspace.** A trial asks for a card; nothing is charged until it ends. If
  there is no card at the end, the subscription ends (never a surprise bill).
- **Several products, one Stripe account:** every product sets its own `STRIPE_PREFIX`
  (e.g. `askdocs`). Products, prices and the portal settings are marked with it, and webhooks
  for customers of other products are ignored.
- **No double subscriptions:** a workspace has at most ONE open checkout (a new one expires the
  old one, so two browser tabs can't both be paid). Before a checkout, Stripe (not our copy)
  is asked: a subscription that still gives a plan → "use Manage billing"; a leftover that gives
  no plan (unpaid, incomplete, paused) is ended first. A webhook for a second paying
  subscription never replaces the first; it is logged as `second_paid_subscription` so you can
  refund it in the Stripe dashboard.
- **Webhooks lock the workspace's billing row before reading Stripe**, so a slow event can't
  overwrite a newer one. An old, ended subscription never overwrites the current one.
- **Deleting a workspace** deletes its Stripe customer first (in the nightly purge). That ends
  every subscription at once and removes the personal data at Stripe (Stripe keeps the invoices
  tax law needs). If Stripe can't be reached, the workspace waits for the next night.

## Plan limits

| Limit (plans.py) | Counted how | Checked when |
| --- | --- | --- |
| `members` | people + open invites | sending an invite, accepting an invite |
| `jobs_per_month` | a counter per calendar month (UTC), starts at 0 on the 1st | starting a metered job (the `example` job; GDPR exports never count) |
| `api_keys` | working keys (not revoked, not expired) | creating a key |

When a limit is reached the API answers **402** with code `limit_reached`. The app shows the
message with **See plans** (owner) or "ask the owner" (everyone else). Moving to a smaller plan
never deletes anything; the workspace just can't add more.

**Add a limit to a product** (e.g. `documents_per_month`):
1. add the field to `PlanLimits` in `plans.py` and give every plan a value;
2. add it to `Metric` and `LABELS` in `backend/app/services/usage.py` (+ a message in `_error`);
3. call `await usage.consume(org_id, "documents_per_month")` in the service, before the work,
   in the same transaction; for things you keep (like API keys) count them like `check_api_keys`;
4. add it to `UsageItem.metric` in `schemas/billing.py`, run `make api-client`, and add a test.

## Try it without Stripe (pretend checkout)

`make dev` runs with `BILLING_DEV_TOOLS=true`. Without Stripe keys, checkout and the billing
portal are small **pretend pages** of our own API ("TEST MODE: no real payment"). They change the
plan through the same code as a Stripe webhook. The e2e tests use them. The setting is refused
in production, and together with a LIVE Stripe key anywhere.

## One real Stripe test-mode payment (do this once)

You need: a Stripe account (free). Everything below uses **test mode**: no real money.

**1. Get your test key**

1. Sign in at https://dashboard.stripe.com. Make sure **Test mode** (or a **Sandbox**) is on
   (top of the page).
2. **Developers → API keys**. Copy the **Secret key**. It starts with `sk_test_`.

**2. Put it in `backend/.env`** (never commit this file)

```
STRIPE_SECRET_KEY=sk_test_...
```

```powershell
cd C:\Users\hotak\Desktop\projects\product-foundation
make restart s=backend
make restart s=worker
```

**3. Create the products and prices in Stripe**

```powershell
make stripe-sync ARGS=--dry-run     # only shows what it would do
make stripe-sync
```

You should see `done  create product foundation_pro`, four `create price ...` lines and
`create portal settings`. Run it again: now everything says `ok`. Check it in the Stripe
dashboard under **Product catalogue**.

**4. Forward webhooks to your laptop** (a second PowerShell window, keep it open)

```powershell
cd C:\Users\hotak\Desktop\projects\product-foundation
make stripe-listen
```

It prints `Your webhook signing secret is whsec_...`. Copy it into `backend/.env`:

```
STRIPE_WEBHOOK_SECRET=whsec_...
```

Then, in the first window: `make restart s=backend`. (If `stripe-listen` ever prints a
different secret, update the line and restart again.)

**5. Pay (test card)**

1. Open http://localhost:3000, sign in as the owner, go to **Settings → Billing**.
   The yellow "pretend pages" note is gone (real Stripe test mode now).
2. Click **Try Pro free for 14 days**. You land on Stripe's checkout page.
3. Card `4242 4242 4242 4242`, any future date (e.g. `12/34`), any CVC (`123`), any name,
   any address. VAT ID is optional (test value: `DE123456789`). Click **Start trial**.
4. You come back to Billing: "Confirming your payment…", then a toast and **Pro · Free trial**.
5. The `stripe-listen` window shows the events with `[200]`.
6. http://localhost:8025 (Mailpit): the email **"Your Pro trial has started"**.
7. **Settings → API keys**: create a second key. It works now (Free allowed 1, Pro allows 10).

**6. Portal and cancel**

1. **Settings → Billing → Manage billing**: Stripe's portal. You see the plan, the card and the
   invoice (0.00 € for the trial).
2. **Cancel subscription** → confirm → **Return to …**. The app shows **Ends soon**.
3. To end it now: Stripe dashboard → **Customers** → your customer → the subscription →
   **Cancel subscription** → **Immediately**. Within seconds the app shows **Free**, and Mailpit
   has "… is on the Free plan now".

**7. A failed payment (optional)**

1. Start a new checkout (no trial this time: one per workspace). Pay with
   `4000 0000 0000 0341`: Stripe accepts this card first, and every later charge fails.
   Tip: on a fresh workspace (create one in the workspace switcher) you get a trial again.
2. With a trial: in the Stripe dashboard, open the subscription and end the trial now
   (or use a **test clock**). The charge fails.
3. The app shows **Payment failed**, the owner gets the "Payment failed" email, and a banner
   appears on every page for the owner. Stripe retries; when it gives up, the workspace moves
   to Free.

**Write in your progress log:** "real Stripe test-mode payment worked on <date>".

Remove `STRIPE_SECRET_KEY` from `backend/.env` again (and restart) if you want the pretend
checkout back, e.g. before `make e2e`: the checkout parts of the e2e tests are skipped while
real keys are set.

## Emails

Templates live in `backend/app/services/email.py` (one layout; text + HTML; everything
escaped). See them all: `make email-preview`, then open http://localhost:8025.

| Email | When |
| --- | --- |
| Confirm your email / You already have an account / Reset password | sign-up and sign-in |
| Invite | an owner or admin invites someone |
| Account / workspace will be deleted | GDPR deletion scheduled |
| Your trial has started / Welcome to Pro | free → paid |
| Your trial ends on … | Stripe's `trial_will_end` (3 days before) |
| Payment failed | `invoice.payment_failed` |
| … is on the Free plan now | paid → free |

**Production provider** (phase 5, or now to test): Resend or Postmark.

1. Create an account, add your domain, add the DNS records they show (SPF, DKIM). Wait until
   the domain shows "verified".
2. `backend/.env` (production: the server's env file):
   ```
   EMAIL_PROVIDER=resend            # or postmark
   EMAIL_API_KEY=re_...             # Postmark: the server token
   EMAIL_FROM=Your Product <no-reply@your-domain.com>
   EMAIL_REPLY_TO=support@your-domain.com
   EMAIL_FOOTER_ADDRESS=Your company, street, city, Germany
   ```
3. `make email-preview` with `--to` your own address:
   `docker compose -f deploy/docker-compose.dev.yml exec backend python -m app.scripts.email_preview --to you@example.com`

Temporary provider problems (down, rate limit) are retried by the worker for about 30 minutes.
Permanent ones (e.g. domain not verified) are logged as `email_send_failed` and not retried.

## Going live (phase 5 does the server part)

1. Stripe: finish **account activation** (company details, bank account).
2. Live keys go only into the server's env file: `STRIPE_SECRET_KEY=sk_live_...`.
3. On the server: `python -m app.scripts.stripe_sync --live` (the `--live` flag is required).
4. Stripe dashboard → **Developers → Webhooks → Add endpoint**:
   URL `https://your-domain/api/billing/webhook`, events exactly:
   `checkout.session.completed`, `customer.subscription.created`, `customer.subscription.updated`,
   `customer.subscription.deleted`, `customer.subscription.paused`, `customer.subscription.resumed`,
   `customer.subscription.trial_will_end`, `invoice.paid`, `invoice.payment_failed`.
   Copy its signing secret into `STRIPE_WEBHOOK_SECRET`. The app refuses to start in
   production with a Stripe key but no webhook secret.
5. Stripe → **Settings → Customer emails**: turn on receipts for successful payments. We send
   our own "Payment failed" email, so Stripe's failed-payment email can stay off.
6. Stripe → **Billing → Revenue recovery**: Smart Retries on (they decide when `past_due` ends).

## Tax and legal: what needs a professional

- **VAT:** prices in plans.py are **net** (`PRICES_INCLUDE_VAT = False`, "plus VAT", B2B).
  Checkout collects the customer's VAT ID. For EU business customers outside Germany the
  reverse-charge rules apply; for German customers you charge 19 %. Either use **Stripe Tax**
  (`STRIPE_AUTOMATIC_TAX=true`, register your tax IDs in Stripe first; Stripe charges a fee) or
  set up tax rates yourself. **Ask a tax advisor (Steuerberater) before going live**,
  including whether the Kleinunternehmerregelung applies to you.
- **Terms (AGB):** `legal/terms` now describes the real behaviour (trial with card, automatic
  renewal, cancel at period end, failed payments → free plan). It is a B2B template. Selling to
  consumers needs more (Widerruf, "Vertrag kündigen" button, gross prices). Have a lawyer check
  it before real customers pay.
- **Privacy policy:** lists what billing stores (Stripe customer id, plan, status, usage) and
  Stripe as a processor. Keep it true when you add providers.
