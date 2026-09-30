# Files, AI, admin and demo (phase 4B)

This page explains four parts of the foundation, how to try them locally, and what to do
before production. Plans and limits live in `backend/app/core/plans.py` (see docs/BILLING.md).

- [Files](#files)
- [AI (the LLM gateway)](#ai-the-llm-gateway)
- [Admin pages](#admin-pages)
- [Demo mode](#demo-mode)
- [What to do before production](#before-production)

---

## Files

**Where:** `/files` in the app. Code: `backend/app/services/files.py`, `storage.py`,
`file_types.py`, `file_scan.py`, `virus_scan.py`; UI: `frontend/components/files/`.

### How an upload works

1. The browser asks `POST /api/files/uploads` with the name and size. The server checks the
   name and type (allowed list in `file_types.py`), the size (`FILES_MAX_BYTES`, 25 MB) and
   the plan's storage (`storage_mb`), then returns a **signed upload form**.
2. The browser uploads **straight to the storage** (big files never pass through our API).
   The form only allows the exact size and type, for 15 minutes, and only to a **staging
   key** `uploads/<workspace>/<file>`.
3. The browser calls `POST /api/files/{id}/complete`. The server **copies** the staged file
   to its final key `orgs/<workspace>/files/<file>` (browsers can never write there), then
   checks the copy: size, and that the first bytes really are a PDF / PNG / ... ("a text
   file called photo.png" is refused).
4. With `CLAMAV_HOST` set, the file is "scanning" until a background job has checked it
   for viruses. Otherwise it is "ready" at once.

Why copy first? The signed form works for 15 minutes. Without the copy, someone could
upload a clean file, wait for the check, and then send other bytes with the same form.

**Downloads** are signed links that work for 5 minutes and always download (never open in
the browser). **Deleting** a file deletes the bytes and the row. A file that is still
uploading can't be deleted until its form has expired (otherwise bytes could arrive
without being counted); stuck uploads are removed by the nightly clean-up.

**Nightly clean-up** (Celery beat, 03:47 UTC): uploads never completed, and staged objects
older than a day. `make storage-setup` also adds a bucket rule that deletes `uploads/`
after a day, where the storage supports it.

**Plan limit:** `storage_mb`. The real size counts (uploads in progress count too). Full =
402 `limit_reached`, shown with "See plans".

**API keys** can have `files:read` (list + download) and `files:write` (upload). Keys can
never delete files.

### Locally

`make dev` starts **SeaweedFS** (the `s3` service; MinIO no longer publishes Docker images).
The browser reaches it through the Next.js server at `/storage`, so nothing else is needed.
Storage browser: http://localhost:8333 (S3 API only; use the app to look at files).

### Virus scan (optional)

Set `CLAMAV_HOST` (and `CLAMAV_PORT`, default 3310) to a running `clamd`, e.g. the
`clamav/clamav` Docker image. Honest note: ClamAV needs about 1–1.5 GB RAM. On a small
server, only run it when strangers can upload files to your product.

---

## AI (the LLM gateway)

**Where:** `backend/app/llm/`. Every AI call in every product goes through
`LlmGateway.run(task, text, organization_id=..., user_id=...)`.

For every call, in this order:

1. **Kill switches:** `LLM_ENABLED=false` (needs a restart), or **"Pause all AI"** on
   `/admin` (works at once, no restart).
2. **Guardrails:** size limit; the user's text is wrapped as data between tags, and the
   instructions say it is never an instruction (prompt-injection defence). The model gets
   no tools.
3. **Plan limit:** one "AI request" is counted (`ai_requests_per_month`). If the model
   could not be reached at all, the request is given back.
4. **The model** is called with the task's model, instructions, **structured output** (a
   Pydantic model), timeout. Temporary errors are retried with backoff.
5. **Checks:** the schema, plus the task's own `check`.
6. **Cost:** tokens and cost (prices in `app/llm/pricing.py`) are saved in `llm_calls`, and
   a trace goes to **Langfuse** in the background.

The example feature is the **AI summary** on the dashboard. It runs as a background job.

### Try it locally

Without a key a free **pretend model** answers (`LLM_DEV_FAKE=true` in the dev compose;
refused in production). For the real model put `OPENAI_API_KEY=sk-...` in `backend/.env`
and `make restart`. **Set a monthly budget limit in the OpenAI dashboard first.**

### Langfuse (see cost per call)

1. https://cloud.langfuse.com → sign up → choose the **EU** region → new project.
2. Project settings → API keys → create. Put them in `backend/.env`:
   `LANGFUSE_PUBLIC_KEY=pk-lf-...`, `LANGFUSE_SECRET_KEY=sk-lf-...`
3. `make restart`, summarize a text on the dashboard, open Langfuse → Tracing. You see the
   task, model, tokens, cost and time.

By default **no texts** go to Langfuse (privacy by default). `LLM_TRACE_CONTENT=true` also
sends the text and the answer. If you turn it on, change the privacy policy text
(`frontend/app/(marketing)/legal/privacy/page.tsx`, section "AI features").

### Add an AI task to a product

1. In `app/llm/tasks.py`: an output model (Pydantic), and an `LlmTask` in `TASKS`
   (model, instructions, output, limits, `check`, `fake`).
2. Evaluation examples in `app/llm/evals/data/<task>.jsonl` (copy `summarize.jsonl`).
3. A background job that calls `gateway.run(...)` (see `ai_summary` in
   `app/workers/tasks.py`), registered in `app/workers/registry.py`.
4. `make eval ARGS="--task <task> --live --save-baseline"` once, then after every change
   `make eval ARGS="--task <task> --live"` → you get a **before → after** table.

**Rules for evals:** the examples are for measuring. Never change the instructions to fix
one example ("tuning on the test set"). Add new examples when real users show a new kind
of problem.

CI runs the pretend-model eval with the tests. A second workflow
(`.github/workflows/eval-nightly.yml`) runs the **real model** every night, if you add the
GitHub secret `OPENAI_API_KEY` (cost: well under 1 cent a night).

Change a task's model without code: `LLM_MODELS={"summarize": "gpt-6.1-sol"}`. When you
add a model, add its price to `app/llm/pricing.py` (from
https://developers.openai.com/api/docs/pricing).

Known detail: if a worker crashes in the middle of an AI job, the job runs again and can
count one extra AI request. That is rare and on the customer's side of the limit; we
accept it instead of risking a lost job.

---

## Admin pages

**Where:** `/admin` (only for app admins; everyone else gets "not found").

Give yourself admin rights (you must have signed up first):

```powershell
make admin email=you@example.com
make admin email=you@example.com ARGS=--remove     # take them away
```

Admin rights are never given through the website or the API.

Pages: **Overview** (numbers, AI kill switch, AI cost this month), **Workspaces**, **Users**,
**Subscriptions** (from the `subscriptions` table), **AI usage** (calls and cost per workspace),
**Failed jobs** (retry).

**View as a user** (support): Users → "View as". For at most 1 hour you see the app as
that person. It is **read-only**: you can look and try features (example job, AI summary,
downloads), but you can't change settings, members, passwords, billing or API keys, and
you can't export data. The customer's audit log shows "support viewed your workspace".
"Stop viewing" brings back your own admin session. The rules are in one file:
`backend/app/core/restrictions.py`.

---

## Demo mode

The **"Try the demo"** button (login page) signs visitors into a shared workspace with
invented data: a small team, files, jobs, audit events, AI usage, the Pro plan.

- It is **read-mostly**: visitors can look around, download sample files, run the example
  job and the AI summary. Everything else is refused with a friendly message.
- **AI in the demo** only works with the **sample text** (all visitors share one account,
  so their own texts would be seen by the next visitor), and at most `DEMO_AI_PER_HOUR`
  (10) summaries per visitor per hour.
- **Nightly reset** (04:07 UTC) puts the starting data back and signs visitors out.
- `make seed` creates the data (the first click on the button also does);
  `make seed ARGS=--reset` resets it now.
- On: `DEMO_ENABLED=true` (the dev compose has it). Off: the button disappears and open
  demo sessions end.

---

## Before production

- [ ] Hetzner Object Storage: create a bucket (Germany) and S3 keys. Set `S3_ENDPOINT`,
      `S3_REGION`, `S3_BUCKET`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`, leave `S3_PUBLIC_URL`
      empty, then run `make storage-setup` once (bucket CORS for your domain + clean-up
      rule). Steps: `deploy/server-setup.md` (on the server: `./deploy.sh compose exec backend python -m app.scripts.storage_setup`).
- [ ] OpenAI: key with a **monthly budget limit**; for EU data residency an eligible project
      and `OPENAI_BASE_URL=https://eu.api.openai.com/v1`.
- [ ] Langfuse keys (EU region). Decide `LLM_TRACE_CONTENT` and make the privacy policy say
      the same.
- [ ] Legal: `frontend/config/legal.ts` lists OpenAI and Langfuse as processors, and the
      privacy policy + DPA describe files, AI and support access. Sign the DPAs with
      OpenAI and Langfuse, and let a lawyer check the texts before `reviewed: true`.
- [ ] Decide on ClamAV (RAM!) and on `DEMO_ENABLED`.
- [ ] `make admin email=...` for yourself on the server.
