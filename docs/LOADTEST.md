# Load test

Checks the quality bar from the spec: **50 people at the same time, API requests with p95 under 200 ms**
(p95 = 95 of 100 requests are at least this fast), almost no errors.

The test uses [k6](https://k6.io) (one program, no accounts). It is `loadtest/k6/api.js`.

Each run of `loadtest_users` gives the test users a **new random password** and writes it, with the session cookies, only to the (private, mode 600) users file. `--cleanup` deletes the test users and the workspaces that only they belong to; a real workspace is never touched, even if it has a similar name.

## What it does

50 simulated people, each with their own login session, open pages (several API calls at once), read for
1 to 3 seconds and repeat. Besides them: an uptime check pings `/health/ready` 5 times a second, about 5 profile saves per second happen (writes), and a few log in (slow on purpose: Argon2).
No AI calls and no payments are made. It prints one clear verdict at the end (`RESULT: PASSED` or `NOT GOOD ENOUGH`).

| Limit (p95) | Default | Why |
| ----------- | ------- | --- |
| normal API calls | 200 ms (`P95_MS`) | the spec |
| `/health/ready` | 300 ms | uptime monitors time out |
| login | 2000 ms | Argon2 hashing is slow on purpose |
| website pages (`PAGES=1`) | 800 ms | server-rendered pages |
| failed API calls | under 1 % | |

## Run it on your PC (local)

Install k6 once (PowerShell): `winget install k6`. Then start the app and run:

```powershell
make dev
make migrate
make loadtest-users      # creates 50 test users + sessions in loadtest/users.json (git-ignored: live cookies!)
make loadtest            # about 2 minutes
make loadtest-clean      # deletes the test users again
```

More people or longer: `make loadtest ARGS="-e VUS=100 -e DURATION=120s"` (create enough users first:
the users file holds 50, so use `docker compose ... exec backend python -m app.scripts.loadtest_users --users 100 ...`).
With the website running too: add `-e PAGES=1`.

## Run it on a server (only yours!)

1. Do it **before you have customers**, or on a staging copy. The users are written into the real database.
2. On the server: `./deploy.sh compose exec -T backend python -m app.scripts.loadtest_users --users 50 --out /tmp/u.json --allow-production`
   then copy the file to your PC (`scp`). Delete it afterwards: it contains live session cookies.
3. On your PC: `k6 run -e BASE_URL=https://my-domain.com -e USERS_FILE=C:/path/u.json -e I_OWN_THIS_SERVER=yes loadtest/k6/api.js`
4. Clean up on the server: `... loadtest_users --cleanup --allow-production`.

The script refuses any address except localhost unless `I_OWN_THIS_SERVER=yes` is set. Per-IP limits (rate
limits, login lockout) will hit you: all 50 people come from your one address. The script is built for that
(sessions are made in advance and logins are few); if you see `429` answers, you are testing the limiter, not the server.

## Result in the sandbox (not your server!)

On the build machine (small Linux VM, API without Docker, local Postgres and Redis, 50 people, 60 s):
**API p95 70 ms** (limit 200 ms) and `RESULT: PASSED`.
This shows the code has no obvious slowness. It says **nothing** about a Hetzner server: run the test there
once (steps above) and write the numbers into your progress log.

## Reading a bad result

- API p95 too high, CPU of `backend` at 100 %: add `--workers` (see `backend` command in the compose file) or a bigger server.
- Slow only for one request (k6 shows it by name): look for a missing index (`EXPLAIN ANALYZE` in `make psql`).
- Many `unexpected_responses`: read the first lines of the k6 output. Usually the users file is old (sessions last 3 hours: run `make loadtest-users` again).
- `429`: see above, rate limits.

## Limits of this test

It does not test the AI endpoints, file uploads, Stripe, or the browser (JavaScript, images). It tests one server
with a warm cache for 1 to 2 minutes; it does not find memory leaks (run it for 30+ minutes with `-e DURATION=1800s` for that).
