# Start a new product from this template

About 30 minutes for the first run. You end with a separate repository for your product (AskDocs, LeadPilot, ...)
that has all the shared parts (login, workspaces, billing, files, AI gateway, deploy, tests).

## 0. Make the template usable on GitHub (once, in the browser)

1. Open the Foundation repository on GitHub > **Settings** (the tab on the right, with the gear).
2. On the **General** page, near the top, tick **Template repository**. It saves by itself.
3. The repository page now has a green button **Use this template**.

Do this once. Changing the template later does not change products that were already created from it
(see "Getting fixes from the template" below).

## 1. Create the new repository

1. Open the template repository > **Use this template** > **Create a new repository**.
2. Owner: you. Name: for example `askdocs`. **Private** is a good default. Click **Create repository**.
3. In PowerShell: `git clone https://github.com/<you>/askdocs.git` and `cd askdocs`.

(No GitHub template? `git clone` the template, delete the `.git` folder, run `git init`. Same result.)

## 2. Run the rename script

```powershell
python scripts/new_product.py --name AskDocs --tagline "Ask questions about your documents." `
  --accent "#0F766E" --accent-dark "#5EEAD4" --github-user <you> --repo askdocs --dry-run
```

`--dry-run` only lists the files. If it looks right, run the same command without `--dry-run`. It changes
exactly these places and stops without changing anything if one does not look as expected:

| File | What |
| ---- | ---- |
| `frontend/config/product.ts` | name, tagline, logo letter, accent colors |
| `deploy/docker-compose.dev.yml`, `deploy/.env.example` | `APP_NAME`, `IMAGE_PREFIX` |
| `backend/app/core/config.py` | default app name and sender name |
| `frontend/package.json`, `package-lock.json` | package name |
| `frontend/tests/e2e/design-system.spec.ts` | the name the browser test looks for |
| `deploy/server-setup.md` | the example image path |

Check the accent colors for contrast (text on buttons needs 4.5:1): <https://webaim.org/resources/contrastchecker/>.

## After the script (by hand)

1. **Logo:** put your files in `frontend/public/` and set `logo` in `frontend/config/product.ts`
   (see the comments there). Also replace the favicon if you have one.
2. **Fonts:** another font = `npm install @fontsource-variable/<font>` in `frontend/`, import it at the top of
   `product.ts`, put its name in `fonts`.
3. **README.md:** change the title and the first paragraph. Optional: `name` in `backend/pyproject.toml`
   and the `scope` name in `backend/app/llm/tracing.py` (internal names, nobody sees them).
4. **Legal texts:** `frontend/config/legal.ts` (your company, address, processors) and `docs/LEGAL_TEMPLATES.md`.
   Set `reviewed: true` only after a lawyer or you have checked the texts.
5. **Plans and prices:** `backend/app/core/plans.py`, then `make stripe-sync`.
6. **Navigation and onboarding steps:** `nav`, `navFooter`, `onboarding` in `product.ts`.
7. Run `make dev`, open <http://localhost:3000>, then `make check` (all must be green).
8. Commit: `git add -A` / `git commit -m "Start AskDocs from the template"` / `git push`.

## Removing parts you do not need

Remove a feature completely or not at all: half-removed code breaks the tests. Order for each part:
(1) the menu entry in `product.ts`, (2) the frontend pages, (3) the API router in `backend/app/main.py`,
(4) services/models, (5) a **new Alembic migration** that drops the tables (never edit old migrations), (6) the tests of that part,
(7) the line in the privacy policy / processor list if a provider is gone (`frontend/config/legal.ts`).
Run `make check` after each part.

| Part | Safe to remove? | Note |
| ---- | --------------- | ---- |
| Demo mode (`DEMO_ENABLED`) | yes, just keep it `false` | nothing to delete |
| Example background job, onboarding step `run_job` | yes | also remove the step from `onboarding` in `product.ts` and the key in `backend/app/services/onboarding.py` |
| Billing / Stripe | yes, but big | leave plans on "free" first; remove Stripe from the processor list when it is gone |
| Files, AI gateway | yes | AI: remove the provider from the processor list and DPA list |
| Admin pages, API keys | possible | check `permissions.py` and the navigation |
| Login, workspaces, roles, audit log | **no** | everything depends on them (tenant isolation) |

## Getting fixes from the template

Products are copies. To take a later fix from the template:

```powershell
git remote add template https://github.com/<you>/product-foundation.git
git fetch template
git cherry-pick <commit>        # one fix
```

Expect conflicts in files you changed (`product.ts`, `legal.ts`). Look at each one; run `make check`.

## Checklist: is my new product really mine?

- [ ] `grep -ri foundation frontend/config backend/app/core deploy/.env.example` finds nothing you did not intend
- [ ] The email sender, privacy policy and imprint show **your** company
- [ ] New random secrets for this product (`deploy/.env.example`): never reuse them from another product
- [ ] Own server, own database, own buckets, own Stripe account / products
- [ ] `docs/FIRST_DEPLOY.md` done once for this product
