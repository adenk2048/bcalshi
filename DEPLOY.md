# Deploying Bcalshi to Render

This project is configured for a one-blueprint deploy on [Render](https://render.com).
The files involved: `render.yaml` (the stack), `build.sh` (build steps),
`requirements.txt` (dependencies), `.python-version` (Python 3.12.7), and the
production settings in `config/settings.py`.

---

## ⚠️ Step 0 — Clean the repository (do this first)

Right now the Git repo contains things that must **not** be deployed or public:

- `venv/` — ~7,000 files, Windows-specific, useless on Render's Linux build
- `__pycache__/` — ~1,700 compiled files
- `db.sqlite3` — **contains password hashes and live session tokens**

The new `.gitignore` stops *future* commits of these, but they're already tracked,
so untrack them once (this keeps the local files, only removes them from Git):

```bash
git rm -r --cached venv __pycache__ */__pycache__ db.sqlite3
git add .gitignore
git commit -m "Stop tracking venv, bytecode, and local database"
```

> Note: `db.sqlite3` has been in the public history. The session tokens in it can
> be rotated by running `python manage.py clearsessions` (or just don't reuse that
> file in production — Render uses a fresh Postgres database). Your dev passwords
> are hashed, but treat the superadmin password from setup as compromised and
> reset it once deployed.

---

## Step 1 — Install the new dependencies locally

Four packages were added (gunicorn, whitenoise, dj-database-url, psycopg2-binary).
They're already in your venv if you ran setup, but to be sure:

```bash
venv\Scripts\python -m pip install -r requirements.txt
```

Confirm the app still boots locally (still uses SQLite, DEBUG on):

```bash
venv\Scripts\python manage.py check
venv\Scripts\python manage.py runserver
```

---

## Step 2 — Push to GitHub

```bash
git add .
git commit -m "Add Render deploy config and harden settings"
git push origin main
```

Your remote is already set: `https://github.com/adenk2048/bcalshi`.

---

## Step 3 — Create the Render Blueprint

1. Sign up at [render.com](https://render.com) (free, log in with GitHub).
2. **New +** → **Blueprint**.
3. Select the `bcalshi` repository. Render reads `render.yaml` and shows a plan:
   one **web service** (`bcalshi`) + one **Postgres database** (`bcalshi-db`).
4. Click **Apply**. Render will:
   - provision Postgres and inject `DATABASE_URL`,
   - generate a strong `DJANGO_SECRET_KEY`,
   - run `build.sh` (install → collectstatic → migrate),
   - start gunicorn.

First build takes a few minutes. When it's live you'll get a URL like
`https://bcalshi.onrender.com` — `ALLOWED_HOSTS` picks that up automatically.

---

## Step 4 — Create your admin account on the live site

The production database is empty (it's a fresh Postgres, not your local SQLite).
Open the web service in Render → **Shell** tab → run:

```bash
python manage.py createsuperuser
```

Then log in at `https://<your-app>.onrender.com/admin/` to create markets, and
the `/control/` page works for the staff account you just made.

---

## Step 5 (optional) — Custom domain

1. Buy a domain (Cloudflare, Porkbun, Namecheap — ~$10–15/yr).
2. Render service → **Settings** → **Custom Domains** → add `bcalshi.com`.
3. Render shows the DNS record to create at your registrar (a CNAME, or an
   A/ALIAS for a root domain). Add it; HTTPS is issued automatically.
4. Add the domain to the `DJANGO_ALLOWED_HOSTS` env var (comma-separated) in
   Render so Django accepts it.

---

## Things to know about the free tier

- **The web service sleeps after ~15 min idle** and cold-starts on the next
  request (~30s delay). Fine for a hobby/demo; upgrade to paid ($7/mo) to keep
  it warm.
- **Free Postgres expires after ~30 days.** Back it up or upgrade before then.
  Back up anytime from the Render dashboard or with `pg_dump`.
- **Don't switch the web service to multiple instances on SQLite.** The matching
  engine uses row locking; that's why this setup uses Postgres. (You're fine —
  `render.yaml` already wires Postgres.)

## Redeploying

Just `git push`. Render auto-deploys on every push to `main`, re-running
`build.sh` (which re-applies migrations safely).
