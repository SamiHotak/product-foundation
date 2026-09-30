# Legal templates (Impressum, Datenschutz, AGB, AVV)

> **These are starting points, not legal advice.** I am not a lawyer, and neither is the AI that
> wrote this. German law is strict and warning letters (*Abmahnungen*) for a missing or wrong
> Impressum or privacy policy are real. Before a product takes real customers, have the texts
> checked by a lawyer, or use a paid generator that updates its texts when the law changes
> (for example eRecht24, IT-Recht Kanzlei, Händlerbund). Then set `reviewed: true`.

The pages are already built. You change **one file**: `frontend/config/legal.ts`.

| Page | German name | Law | File |
| --- | --- | --- | --- |
| `/legal/imprint` | Impressum | § 5 DDG (was § 5 TMG until May 2024) | `app/(marketing)/legal/imprint/page.tsx` |
| `/legal/privacy` | Datenschutzerklärung | Art. 13 GDPR (DSGVO), § 25 TDDDG | `app/(marketing)/legal/privacy/page.tsx` |
| `/legal/terms` | AGB | §§ 305 ff. BGB | `app/(marketing)/legal/terms/page.tsx` |
| `/legal/dpa` | AVV (Auftragsverarbeitungsvertrag) | Art. 28 GDPR | `app/(marketing)/legal/dpa/page.tsx` |

Every legal page shows a yellow **"Template, not legal advice"** box while `reviewed` is `false`
or any `[bracketed]` value is left in `config/legal.ts`. Placeholders are highlighted on the page.
Links to all four are in the footer of every public page (the Impressum must be easy to find).

---

## Before you go live: checklist

1. [ ] Fill in `company` in `config/legal.ts`: full name / company with legal form, street
       address (no P.O. box), email, phone. VAT id and register entry if you have them.
2. [ ] Check `supervisoryAuthority` (default: LDI NRW, correct for a business in NRW).
3. [ ] Update `processors`: only providers you really use, with their real region
       (Resend or Postmark, Sentry EU or US, Plausible or Umami). Add new ones when a phase adds
       them (phase 4B: **OpenAI** and **Langfuse** for AI features; file storage stays at Hetzner).
4. [ ] Replace the remaining `[..]` values in the page files (log retention days, availability %,
       breach notice hours, place of jurisdiction).
5. [ ] DPA security list: backups (encrypted, separate bucket, 14 days), SSH-key-only access and
       Sentry error reports are now described as facts (phase 5A). They are only true after you
       finished `deploy/server-setup.md`. Remove what you do not use. It is a promise to customers.
       The privacy page says Sentry EU: create the Sentry project in the **EU region**.
6. [ ] Decide: businesses only, or consumers too? (see below)
7. [ ] Prices: `PRICES_INCLUDE_VAT` in `backend/app/core/plans.py` (ask your tax advisor;
       Kleinunternehmer under § 19 UStG charge no VAT and must say so on invoices).
8. [ ] Lawyer or paid generator checks all four texts. Update the `updated` date.
9. [ ] Set `reviewed: true`. The warning box disappears.
10. [ ] Get the signed DPAs from your own providers (Hetzner, Stripe, email provider, Sentry,
        analytics). Most offer them in their dashboard.

---

## Impressum

Required for every business website in Germany, reachable from every page.

Must contain: name (company + legal form, and the managing director for a GmbH/UG), a street
address where you can be served legal papers, email, and a second fast way to contact you
(usually a phone number). If you have them: register court + number, VAT id (USt-IdNr.).

Notes:
- The EU online dispute resolution (ODR) platform was shut down in July 2025, so the old "ODR
  link" sentence is no longer needed. The template has the § 36 VSBG sentence instead (only
  required with more than 10 employees, but harmless).
- A blog with editorial content also needs a person "responsible for content" (§ 18 (2) MStV).
  Add it if you start publishing articles.
- Working from home: your private address becomes public. A business address service
  (*ladungsfähige Geschäftsadresse*) is a common solution; ask the lawyer.

## Datenschutzerklärung (privacy policy)

The template describes what **this code base really does**:
- server logs (IP, time, page, browser),
- accounts, workspaces, Google sign-in,
- the audit log (365 days),
- only necessary cookies: `session` (30 days), `theme` (1 year), `google_oauth` / `google_next`
  (10 minutes). These need no consent under § 25 (2) No. 2 TDDDG, **so no cookie banner is needed**
  as long as you add nothing that sets other cookies or reads the device (no Google Analytics,
  no Facebook pixel, no YouTube embeds, no Google Fonts from Google's servers — our fonts are
  self-hosted),
- cookie-less statistics through our own API (see `backend/app/services/analytics.py`),
- emails, Stripe payments, deletion after 14 days, exports kept 7 days.

**Every time a product adds a feature that processes personal data** (AI, file uploads, a new
provider), add it to this page and to `processors`. For AI features, also say which data is sent
to the model provider and that it is not used for training (check the provider's terms).

Cookie-less analytics: German authorities (DSK) accept statistics without consent when nothing is
stored on the device and IPs are not kept. Plausible and Umami are built for that. Our server
removes query strings and keeps only the referrer's origin. Still name the provider in the policy.

## AGB (terms of service)

The template is for **business customers only (B2B, § 14 BGB)**. That keeps it much simpler.
It covers: contract start, service and availability, free plan and trial, prices and payment,
automatic renewal and cancellation, customer duties, data (with the DPA), limited liability
in the standard German form, changes to the terms, German law and jurisdiction.

**Selling to consumers (B2C) needs much more:** a withdrawal policy (*Widerrufsbelehrung*) and
model withdrawal form, the "cancel contract" button (*Kündigungsbutton*, § 312k BGB), prices
including VAT (PAngV), the "order with obligation to pay" button text (§ 312j BGB), and limits on
automatic renewal (§ 309 No. 9 BGB). Don't open to consumers without a lawyer.

To make B2B-only real: the signup page links to the Terms, and (phase 4A) Stripe Checkout asks
for the billing address and offers the "I'm purchasing as a business" fields (company name,
VAT ID). The VAT ID is not forced, because some small businesses have none. Clause 4-6 describe
the real billing behaviour: a trial asks for a card and continues as a paid plan unless
cancelled (we email a reminder), plans renew automatically, cancelling works at the end of the
period, and failed payments end in the free plan (no data is deleted). Let a lawyer check this.

## AVV / DPA (data processing agreement)

Your business customers store personal data (their team, their customers) in your product, so
you process data **on their behalf**. Art. 28 GDPR requires a contract for that. Publishing it and
making it part of the Terms (clause 8) is the common SaaS way. Some bigger customers will send
their own DPA; compare it with this one before signing.

The template covers: subject and duration, types of data and people, instructions,
confidentiality, security measures (Art. 32), subprocessors (with 30 days' notice and a right to
object), help with data subject requests, breach notification, deletion at the end, audits.

The security list must stay **true**. Current facts from this code base: servers in Germany,
TLS, Argon2id password hashes, hashed API keys and tokens, role-based access, workspace
isolation (proven by `backend/tests/test_org_isolation.py`), rate limits, audit log. Backups
and SSH access come in phase 5.

---

## What is NOT covered

- **Records of processing** (*Verzeichnis von Verarbeitungstätigkeiten*, Art. 30 GDPR): an
  internal document you keep. Generators and lawyers usually provide a template.
- **Data protection officer**: needed from 20 people regularly processing personal data. Not now.
- **EU AI Act**: transparency duties apply when products show AI-generated content or chatbots.
  Handle this in the product files (AskDocs, LeadPilot, InvoiceAI Pro) when AI features ship.
- **Tax** (VAT, invoices, OSS for EU customers): ask a tax advisor (*Steuerberater*).
