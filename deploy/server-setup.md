# Server setup: click by click

This guide takes you from "nothing" to "my product runs on the internet with HTTPS".
Do the steps **in order**. Each step says what to click or type.
Plan about **2 to 3 hours** the first time. Most of it is waiting for DNS.

What you will have at the end:

- One Hetzner server in Germany (Ubuntu) running the whole product with Docker.
- Automatic HTTPS (Caddy gets the certificate for you).
- Automatic deploys from GitHub after every green CI run.
- Encrypted nightly database backups in a separate bucket.
- Error reports (Sentry) and an uptime check.

> Things marked **(check)** are names on other companies' websites. Their buttons and plan names
> change. If a name here does not match what you see, pick the closest one. The idea stays the same.

## What you need before you start

- A domain name you own (for example `my-domain.com`). You must be able to edit its DNS records.
- A GitHub repository with this code, and the `main` branch pushed.
- A credit card for Hetzner.
- About 30 EUR per month budget (server about 8 to 15 EUR, storage about 5 EUR, the rest is free tiers).
- Windows PowerShell. Every command in a grey box is meant to be pasted into PowerShell **on your PC**,
  unless the step says **"on the server"**.

Write every secret you create into your **password manager**. You will need them again.

---

## Step 1. Hetzner account and project

1. Go to <https://accounts.hetzner.com/signUp> and create an account. Confirm your email.
   Hetzner may ask for an ID check. That is normal and can take a few hours.
2. Open <https://console.hetzner.cloud>. Click **New project**. Name it `my-app`.

## Step 2. Make an SSH key on your PC

An SSH key is a pair of files. The **public** file goes to the server. The **private** file stays
on your PC and never goes anywhere else.

Open **PowerShell** and run:

```powershell
ssh-keygen -t ed25519 -C "my-app-admin" -f "$HOME\.ssh\my-app-admin"
```

- When it asks for a passphrase, type one and remember it (a passphrase is a password for the key file).
- Two files appear in `C:\Users\<you>\.ssh\`: `my-app-admin` (private, secret) and `my-app-admin.pub` (public).

Show the public key and copy it:

```powershell
Get-Content "$HOME\.ssh\my-app-admin.pub"
```

It is one line that starts with `ssh-ed25519`.

Then make a **second** key just for GitHub deploys, **without** a passphrase (GitHub cannot type one):

```powershell
ssh-keygen -t ed25519 -C "my-app-github-deploy" -N '""' -f "$HOME\.ssh\my-app-deploy"
```

> If your PowerShell says the `-N` part is wrong, run the command without `-N '""'` and just press
> Enter twice when it asks for a passphrase.

## Step 3. Create the server

1. In your Hetzner project click **Add Server**.
2. **Location:** pick **Falkenstein** or **Nuremberg** (Germany).
3. **Image:** **Ubuntu 24.04**.
4. **Type:** choose **Shared vCPU, x86 (Intel/AMD)**. Pick a plan with **4 GB RAM or more**
   (for example a "CPX21" or "CPX22"; **(check)** the current names).
   Do **not** pick the cheaper ARM ("CAX") plans: the deploy builds for x86.
5. **Networking:** keep **Public IPv4** and **Public IPv6** on.
6. **SSH keys:** click **Add SSH key**, paste the line from `my-app-admin.pub`, name it `my-app-admin`, save, and tick it.
7. **Backups (Hetzner):** you can tick this (about 20% extra). It is a second safety net for the whole
   server. It does **not** replace the database backups in Step 12.
8. **Name:** `my-app-1`. Click **Create & Buy now**.
9. After a minute the server shows an IPv4 address (like `203.0.113.10`). Write it down.
   Call it `SERVER_IP` in this guide.

## Step 4. Firewall (Hetzner)

The firewall blocks everything except what you need.

1. Left menu: **Firewalls** > **Create Firewall**.
2. **Inbound rules.** Delete any default rule you do not want, then have exactly these:

   | Protocol | Port | Source          | Why                     |
   | -------- | ---- | --------------- | ----------------------- |
   | TCP      | 22   | Any IPv4, IPv6  | SSH (you and GitHub)    |
   | TCP      | 80   | Any IPv4, IPv6  | HTTP (certificate + redirect) |
   | TCP      | 443  | Any IPv4, IPv6  | HTTPS                   |
   | UDP      | 443  | Any IPv4, IPv6  | HTTP/3                  |

   Leave **Outbound** empty (that means: allow all).
3. **Apply to:** choose your server `my-app-1`. Name the firewall `my-app-fw`. Click **Create Firewall**.

> GitHub's deploy servers have changing addresses, so port 22 must stay open to everyone.
> This is safe because Step 5 turns off password logins: only your keys work.

## Step 5. First login and safe basics

Log in from PowerShell (replace `SERVER_IP`):

```powershell
ssh -i "$HOME\.ssh\my-app-admin" root@SERVER_IP
```

The first time it asks "Are you sure you want to continue connecting". Type `yes`.
You are now **on the server** (the prompt shows `root@my-app-1`).

Run these blocks one after another.

**Update everything:**

```bash
apt update && apt -y upgrade
apt -y install ufw fail2ban unattended-upgrades curl ca-certificates gnupg
```

**Turn on automatic security updates** (choose **Yes** when it asks):

```bash
dpkg-reconfigure -plow unattended-upgrades
```

**Create the `deploy` user** (the user GitHub logs in as; it is not root):

```bash
adduser --disabled-password --gecos "" deploy
mkdir -p /home/deploy/.ssh
```

Now put **both** public keys in its `authorized_keys`. Open the file:

```bash
nano /home/deploy/.ssh/authorized_keys
```

Paste two lines: the content of `my-app-admin.pub` **and** the content of `my-app-deploy.pub`
(on your PC: `Get-Content "$HOME\.ssh\my-app-deploy.pub"`). Save with `Ctrl+O`, `Enter`, `Ctrl+X`. Then:

```bash
chown -R deploy:deploy /home/deploy/.ssh
chmod 700 /home/deploy/.ssh
chmod 600 /home/deploy/.ssh/authorized_keys
```

**Turn off password login.** Root may still log in, but **only with a key** (your admin key from
Step 2). You need root later for updates and reboots. The `deploy` user is only for GitHub.
First make sure the `deploy` login works (see the test below), then:

```bash
cat >/etc/ssh/sshd_config.d/99-hardening.conf <<'EOF'
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin prohibit-password
EOF
sshd -t && systemctl restart ssh
```

**Test before you close this window.** Open a **second** PowerShell window and run:

```powershell
ssh -i "$HOME\.ssh\my-app-admin" deploy@SERVER_IP
```

If you get in, all is good. If not, fix it **in the first window** (do not close it yet).

**Server firewall as a second layer** (in the first window, as root):

```bash
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw allow 443/udp
ufw --force enable
systemctl enable --now fail2ban
```

> The `deploy` user can run Docker, and that is the same as being root on this server. So guard the
> deploy key well (Step 11 explains how).

> Docker publishes ports by itself and bypasses `ufw`. That is fine here, because only Caddy
> publishes ports (80/443). The Hetzner firewall from Step 4 is the one that really counts.

## Step 6. Install Docker

Still in the first window, as root. These are the official Docker steps:

```bash
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" >/etc/apt/sources.list.d/docker.list
apt update
apt -y install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
usermod -aG docker deploy
docker --version && docker compose version
```

Both versions must print. (`usermod` lets the `deploy` user run Docker.)

**Make the app folder:**

```bash
mkdir -p /opt/app
chown deploy:deploy /opt/app
```

Now switch to the `deploy` user for the rest of the server steps:

```bash
su - deploy
```

## Step 7. DNS records

At the company where you bought the domain, open the DNS settings and add:

| Type | Name | Value        |
| ---- | ---- | ------------ |
| A    | `@`  | `SERVER_IP`  |
| A    | `www`| `SERVER_IP`  |

**Do not add `AAAA` (IPv6) records for now.** With Docker's default settings every IPv6 visitor
may look like the same address to the app, and then the per-IP limits (login lockout, rate limits)
would hit everybody together. Use IPv4 only until you have tested IPv6 on your server.

If the domain already has other `A` or `AAAA` records for `@` or `www`, delete them.

Check on your PC after a few minutes (it can take up to an hour):

```powershell
nslookup my-domain.com
```

It must show `SERVER_IP`. **Do not continue until it does.** Caddy needs this to get the certificate.

## Step 8. Storage buckets (files and backups)

You need **two separate buckets** with **two separate key pairs**. That way a leaked app key can never
delete your backups.

1. Hetzner console: your project > **Object Storage** > **Create bucket**. **(check)**
2. Location **Falkenstein** (`fsn1`). Name: `my-app-files`. **Private** (not public). Create.
3. Create a second bucket: `my-app-backups`, also **private**.
   Bucket names are global, so add something unique, like `my-app-files-x7k2`.
4. Left menu of your project: **Security** > **S3 credentials** > **Generate credentials**. **(check)**
   Copy the **Access key** and **Secret key** (the secret is shown only once). Name: `app-files`.
5. Generate a **second** credentials pair. Name: `app-backups`.

> Hetzner's S3 keys may work for all buckets of the project. If so, you cannot separate them by key.
> Then at least keep the two buckets and keep the backup keys in a different place than the app
> keys. If you want the strong separation, use a separate Hetzner project for the backup bucket.
> **(check)** how your account behaves, and tell me if you want to change this.

The endpoint for Falkenstein is `https://fsn1.your-objectstorage.com`. The region is `fsn1`.

## Step 9. Sentry (error reports)

Optional but recommended.

1. Go to <https://sentry.io/signup/>. **Choose the EU region (Frankfurt)** when it asks. This is
   important: the privacy policy of this product says errors go to the EU.
2. Create a project: platform **FastAPI**, name `backend`. Copy its **DSN** (a URL that starts with `https://`).
3. Create a second project: platform **Next.js**, name `frontend`. Copy its DSN.
4. Under **Settings** > **Security & Privacy** turn **Store IP addresses** off. **(check)**

## Step 10. The `.env` file on the server

Still on the server as `deploy`:

```bash
cd /opt/app
nano .env
```

Paste the content of `deploy/.env.example` from the repository, then fill in every value.
Make the secrets **on the server** like this (run it four times, use each result once):

```bash
openssl rand -hex 32
```

You need one for each of: `SECRET_KEY`, `POSTGRES_PASSWORD`, `REDIS_PASSWORD`.
(The backup passphrase is made in Step 12, in a separate file.)

Important values:

- `DOMAIN`: your domain, with no `https://` and no `www`.
- `ACME_EMAIL`: your email. Let's Encrypt warns you here before a certificate runs out.
- `IMAGE_PREFIX`: `ghcr.io/<github-user>/<repo-name>` **all lowercase**.
  For this repo: `ghcr.io/samihotak/product-foundation`. The deploy checks that it matches.
- `APP_NAME`: the same as `name` in `frontend/config/product.ts`.
- `DEMO_ENABLED`: keep `false` on a real product.
- `S3_*`: the app-files keys and bucket from Step 8. `S3_ORIGIN` is the endpoint without a path.
- `SENTRY_DSN`: the **backend** DSN from Step 9.
- Email keys (Resend or Postmark): from your email provider. Add your domain there and set the SPF and DKIM records they show.
- Stripe: leave empty until you are ready for live payments (Step 17).

Save with `Ctrl+O`, `Enter`, `Ctrl+X`, then lock the file:

```bash
chmod 600 .env
```

**Save a copy of the whole `.env` in your password manager now.**

## Step 11. GitHub: secrets, variables, environment

Open your repository on GitHub. Click **Settings**.

**a) Environment.** **Environments** > **New environment** > name it exactly `production` > **Configure environment**.
Optional: tick **Required reviewers** and add yourself. Then every deploy waits for your click.
That is a good safety switch for a real product.

**a2) Only `main` may deploy.** Still in **Environments** > `production`: under **Deployment branches and tags**
choose **Selected branches and tags** > add `main`. Also turn on branch protection for `main`
(**Settings** > **Branches** > **Add rule**: require a pull request and the CI checks). Reason: anybody
who can push a branch could otherwise write a workflow that uses the deploy key.

**b) Secrets.** Open the environment `production` (**Settings** > **Environments** > `production`) and
scroll to **Environment secrets** > **Add environment secret**. Use **environment** secrets, **not**
repository secrets. Environment secrets are only given to jobs that run for `production`, and
you limited that to `main` above:

- `DEPLOY_SSH_KEY`: the **whole** content of the private deploy key, including the first and last line:

  ```powershell
  Get-Content "$HOME\.ssh\my-app-deploy" -Raw | Set-Clipboard
  ```

  Then paste (`Ctrl+V`) into the secret box.
- `DEPLOY_KNOWN_HOSTS`: the server's fingerprint line, so GitHub knows it talks to your real server.
  On your PC (replace `SERVER_IP`):

  ```powershell
  ssh-keyscan -t ed25519 SERVER_IP | Set-Clipboard
  ```

  Paste the result. It looks like `203.0.113.10 ssh-ed25519 AAAA...`.
  (You are trusting the network for this one moment. If you want to be extra careful, compare with
  the fingerprint from Hetzner's console: Rescue tab, or run `ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub` on the server.)

**c) Variables.** **Settings** > **Secrets and variables** > **Actions** > tab **Variables** > **New repository variable**:

| Name                     | Value                                              |
| ------------------------ | -------------------------------------------------- |
| `DEPLOY_HOST`            | `SERVER_IP`                                        |
| `DOMAIN`                 | `my-domain.com`                                    |
| `DEPLOY_USER`            | `deploy`                                           |
| `NEXT_PUBLIC_SENTRY_DSN` | frontend DSN from Step 9 (leave out if no Sentry)  |

> The deploy does **nothing** until `DEPLOY_HOST` exists. That is on purpose.
> Variables (not secrets) may stay at repository level: they are not secret.
> A deploy of an older commit is skipped by itself when a newer commit is already on `main`.

**d) Package permission.** The deploy uses GitHub's own token to push images. Check
**Settings** > **Actions** > **General** > **Workflow permissions**: it must allow the workflow to
write packages. The `deploy.yml` file already asks for `packages: write`, so the default
usually works. **(check)** If the first deploy says "denied" when pushing, this is the place.

## Step 12. Backups: schedule and uptime checks

**a) Backup settings and nightly job (on the server as `deploy`).** The first deploy in Step 13 must be
done first, because it copies `backup.sh` to the server. Come back here after Step 13.

The backup keys live in their **own file**, `/opt/app/.env.backup`, not in `.env`. The app containers
read `.env` but never `.env.backup`. So even if the app gets hacked, the attacker cannot open or
delete your backups.

```bash
cd /opt/app
cp .env.backup.example .env.backup
nano .env.backup
chmod 600 .env.backup
```

Fill in: `BACKUP_PASSPHRASE` (make it with `openssl rand -hex 32`), and the `BACKUP_S3_*` values
(the **backup** bucket and keys from Step 8). **Copy the passphrase and the keys into your password
manager.** Without the passphrase your backups cannot be opened.

Optional but strongly recommended: <https://healthchecks.io> (free). Create a check named
`my-app backup`, period **1 day**, grace **2 hours**. Copy its ping URL into `HEALTHCHECK_URL`
in `.env.backup`. If no backup runs, they email you.

Then add the nightly job:

```bash
crontab -e
```

Choose `nano` if asked. Add this line at the end:

```
30 2 * * * cd /opt/app && ./backup.sh >> /opt/app/backup.log 2>&1
```

Save. (Runs every night at 02:30 server time.)

**b) Test the backup right now:**

```bash
cd /opt/app
./backup.sh
./restore-test.sh
```

The second command restores the newest backup into a scratch database and prints some row counts.
It must print `Restore worked.` with row counts. **Do this once now and again every few months.**
A backup you never restored is only a hope.

**c) Uptime check.** Free option: <https://uptimerobot.com> (or Better Stack).
Add a monitor: type **HTTP(s)**, URL `https://my-domain.com/api/health/ready`, every 5 minutes,
alert to your email. (This URL checks the database and Redis too, not only the website.)

## Step 13. First deploy

1. On GitHub: **Actions** tab > left list **Deploy** > **Run workflow** > branch `main`,
   **leave "tag" empty** > **Run workflow**.
   (Without a tag it builds the newest commit. A tag is only for going back, see below.)
2. Click the running workflow to watch it. It takes about 10 to 20 minutes the first time
   (building two images). Later runs are faster.
3. If you set required reviewers, click **Review deployments** > **production** > **Approve**.
4. The last steps are "Deploy" and "Check the public website". The public check tries for up to
   5 minutes, because Caddy needs a moment to get the certificate.
5. Open `https://my-domain.com`. You should see your site with a lock icon.

From now on, every push to `main` that passes CI deploys itself.

**If it fails**, open the red step and read the last lines. Most common causes:

| You see                                        | Meaning and fix                                                |
| ---------------------------------------------- | -------------------------------------------------------------- |
| `Secrets DEPLOY_SSH_KEY ... are needed`        | Step 11b is missing or misspelled.                             |
| `Host key verification failed`                 | `DEPLOY_KNOWN_HOSTS` is wrong. Redo `ssh-keyscan`.             |
| `Permission denied (publickey)`                | The deploy public key is not in `authorized_keys` (Step 5).    |
| `IMAGE_PREFIX in /opt/app/.env must be: ...`   | Fix `IMAGE_PREFIX` in `.env`, then run the workflow again.     |
| `denied` / `unauthorized` when pulling images  | Step 11d, or the workflow did not push the images.             |
| `.env ... problem` from `docker compose config`| A required value is empty in `.env`. The message names it.     |
| Public check fails but server is fine          | DNS (Step 7) or the Hetzner firewall (Step 4). Check both.     |

The deploy rolls back by itself if the new version is not healthy. On the very first deploy there is
nothing to roll back to, so just fix the cause and run the workflow again.

## Step 14. One-time setup on the server

After the first deploy works, on the server as `deploy`:

**Create the file bucket rules** (CORS, so browser uploads work):

```bash
cd /opt/app
./deploy.sh compose exec backend python -m app.scripts.storage_setup
```

**Make yourself admin.** First sign up on your site with your email, then:

```bash
./deploy.sh compose exec backend python -m app.scripts.make_admin you@my-domain.com
```

(To take admin rights away later, add `--remove` after the email.)

**Look at the status:**

```bash
./deploy.sh status
```

## Step 15. Check that errors reach Sentry

Skip if you did not set up Sentry.

1. Open your Sentry backend project. It should have no errors yet.
2. On the server:

   ```bash
   cd /opt/app
   ./deploy.sh compose exec backend python -c "import sentry_sdk; sentry_sdk.capture_message('setup test from server'); sentry_sdk.flush(5)"
   ```

3. Within a minute the message shows up in Sentry. Delete it afterwards.
4. For the frontend: open your site, press `F12`, open the **Console**, run
   `throw new Error("frontend sentry test")` in a fresh tab (it is safe), and look in the
   frontend Sentry project. If you use an ad blocker, turn it off for this test.
   (Errors travel through `/monitoring` on your own domain, so blockers rarely matter.)

## Step 16. Rolling back

**Automatic:** if a new version is unhealthy, the deploy goes back to the last good version alone.

**By hand, from GitHub:** **Actions** > **Deploy** > **Run workflow** > type an older tag in **tag**,
for example `sha-abc1234` (find the tags on the repository's **Packages** page, or in the
"Summary" of an older deploy run). No build happens, so it takes about a minute.

**By hand, on the server:**

```bash
cd /opt/app
./deploy.sh rollback
```

**Important:** a rollback does **not** undo database migrations. That is why every migration must
also work with the old code (see `docs/DEPLOYMENT.md`, "Migrations"). If a migration went really wrong,
restore the pre-deploy backup (see below) and ask for help before you do it: it removes newer data.

## Step 17. Before real customers

- **Stripe:** in the Stripe dashboard switch to live mode. Put the live secret key into `.env`.
  Add a webhook endpoint `https://my-domain.com/api/billing/webhook`,
  copy its signing secret into `STRIPE_WEBHOOK_SECRET`, and run `./deploy.sh deploy $(cat .deployed_tag)`
  again so the containers see the new `.env`. Then create the live products once: `./deploy.sh compose exec backend python -m app.scripts.stripe_sync --dry-run` (look at the plan), then again without `--dry-run`.
- **Legal pages:** fill in every `[placeholder]` in `frontend/config/legal.ts`. Have a lawyer read
  them. See `docs/LEGAL_TEMPLATES.md`.
- **Logs:** Docker keeps the newest 3 files of 10 MB per service, then overwrites the oldest.
  That is **size-based**, not "14 days". The privacy policy has a placeholder for the log retention
  time: write what is true for you (for example "a few days, depending on traffic").
- **Restore drill:** run `./restore-test.sh` again. Put a reminder in your calendar every 3 months.
- **Server updates:** security updates install by themselves (as root you can also run `apt update && apt upgrade`). Kernel updates need a reboot once in a while:
  log in as root (`ssh -i "$HOME\.ssh\my-app-admin" root@SERVER_IP`) and run `reboot` (the site is down for about a minute). Do it at a quiet time.

## Restoring a backup for real (emergency)

1. Do not panic. The backups are in your `my-app-backups` bucket.
2. `./restore-test.sh --list` shows the available backups.
3. `./restore-test.sh` shows how a restore works (it uses a scratch database).
4. To replace the **real** database, follow `docs/DEPLOYMENT.md`, section "Restore into the real
   database". It tests the backup first and takes a fresh backup before it deletes anything.

## Update the server itself

If you change `docker-compose.yml`, `Caddyfile` or the scripts in the repository, just push to `main`.
The deploy copies them to `/opt/app` every time. To apply only a changed Caddyfile without a full deploy:
`./deploy.sh reload-caddy`.
