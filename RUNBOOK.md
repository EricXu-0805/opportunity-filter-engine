# RUNBOOK — Operator actions required after this session

This session shipped infrastructure that needs one-time operator setup
before the features go live. Work through the sections in order.

## 1. Supabase — enable Anonymous Sign-ins  ⚠️ REQUIRED

Dashboard → **Authentication → Sign In / Providers → Anonymous Sign-Ins → Enable**.

Without this, `signInAnonymously()` returns HTTP 422 (`anonymous_provider_disabled`)
and users can't save profiles/favorites/interactions. The app now degrades
gracefully: favorites are written to `localStorage` (`ofe_favs_fallback`)
and an amber **"Saved locally only"** banner appears on Results/Favorites
pages. When you flip the switch on, the next `getFavorites()` call will
backfill any local-only favorites into Supabase automatically.

To verify it's enabled, run:

```bash
curl -sS -X POST "https://<project-ref>.supabase.co/auth/v1/signup" \
  -H "apikey: <anon-key>" -H "Content-Type: application/json" -d '{}'
# Success → {"user": {...}}    Disabled → {"error_code":"anonymous_provider_disabled"}
```

## 2. Supabase — apply migrations 006 and 007

Dashboard → **SQL Editor → New query**, paste each file, run in order.

```bash
supabase/migrations/006_anonymous_auth_rls.sql   # Anonymous auth RLS
supabase/migrations/007_push_subscriptions.sql   # Push subscription table
```

Or via CLI: `supabase db push`.

Verify:

```sql
SELECT policyname, cmd FROM pg_policies
WHERE tablename IN ('profiles', 'favorites', 'interactions', 'profile_versions', 'push_subscriptions')
ORDER BY tablename, policyname;
```

Each table should have SELECT/INSERT/UPDATE/DELETE (or subset) policies
referencing `auth.uid()::text`.

## 3. Vercel — env var cleanup

**Delete** (no longer used):

- `NEXT_PUBLIC_SUPABASE_JWT_SECRET`

**Keep** (unchanged):

- `NEXT_PUBLIC_SUPABASE_URL`
- `NEXT_PUBLIC_SUPABASE_ANON_KEY`

**Add** (for Web Push — optional, skip if not using push):

- `NEXT_PUBLIC_VAPID_PUBLIC_KEY` — public key (see step 4)

## 4. Web Push — generate VAPID keypair

```bash
pip install cryptography
python scripts/generate_vapid_keys.py
```

The script prints three env vars. Paste them:

| Env var | Where |
|---|---|
| `NEXT_PUBLIC_VAPID_PUBLIC_KEY` | Vercel (frontend) |
| `VAPID_PRIVATE_KEY` | Backend host (Render/Fly/your server) |
| `VAPID_PUBLIC_KEY` | Backend host |
| `VAPID_SUBJECT` | Backend host, e.g. `mailto:you@example.com` |

The private key must stay secret — store in a password manager.

Until you set `NEXT_PUBLIC_VAPID_PUBLIC_KEY`, the "Enable notifications"
button on `/dashboard` stays hidden (graceful degradation).

## 5. Push cron — wire up scheduler

The backend exposes `GET /api/cron/reminders` (guarded by `CRON_SECRET`)
that scans overdue reminders and fires Web Push notifications.

### 5a. Backend env

```
CRON_SECRET=<long random string, e.g. `openssl rand -hex 32`>
SUPABASE_URL=https://<your-project>.supabase.co
SUPABASE_SERVICE_ROLE_KEY=<service role key from Supabase dashboard>
VAPID_PRIVATE_KEY=<from step 4>
VAPID_PUBLIC_KEY=<from step 4>
VAPID_SUBJECT=mailto:you@example.com
```

### 5b. Backend dependency

```bash
pip install pywebpush httpx
```

Add both to `requirements.txt` if you're deploying to a fresh host:

```
pywebpush>=1.14
httpx>=0.25
```

### 5c. Scheduler

Pick one:

**Option A — Vercel Cron** (if backend runs on Vercel):
Add to `vercel.json`:

```json
{
  "crons": [
    { "path": "/api/cron/reminders", "schedule": "0 13 * * *" }
  ]
}
```

**Option B — GitHub Actions** (backend anywhere):

```yaml
name: daily-reminders
on:
  schedule:
    - cron: '0 13 * * *'
jobs:
  ping:
    runs-on: ubuntu-latest
    steps:
      - run: |
          curl -sf \
            -H "Authorization: Bearer ${{ secrets.CRON_SECRET }}" \
            "${{ secrets.BACKEND_URL }}/api/cron/reminders"
```

**Option C — external cron service** (cron-job.org, EasyCron): configure
a GET to `https://<your-backend>/api/cron/reminders` with header
`Authorization: Bearer <CRON_SECRET>`.

Daily 1pm UTC (~8am Central during DST) is a reasonable default so
overdue items get surfaced mid-morning.

## 6. Verification

After the above, sanity check:

1. Open the app in an **incognito** window (to get a fresh anonymous auth).
2. Home → fill out a profile → refresh — profile should still be there.
3. Star an opportunity → `/favorites` → see it listed.
4. Open `/dashboard` — you should see the "Enable notifications" button
   (only if VAPID key is set and browser supports Web Push).
5. Click it → accept browser permission → check Supabase dashboard → table
   `push_subscriptions` should have a new row with your `auth.uid()`.
6. Add a reminder on any opportunity detail page with `remind_at` set to
   today.
7. Manually trigger: `curl -H "Authorization: Bearer $CRON_SECRET" \
   https://<backend>/api/cron/reminders` — should return `{"sent": 1, ...}`
   and the browser should show a notification.

## 7. Rollback

If anything goes wrong:

- **Migration 006** — recreate 004 policies by pasting
  `supabase/migrations/004_rls_device_scoping.sql` and restoring old
  `frontend/src/lib/supabase.ts` from git history
  (`git show HEAD~1:frontend/src/lib/supabase.ts`).
- **Push** — remove `NEXT_PUBLIC_VAPID_PUBLIC_KEY` from Vercel. The
  subscribe UI disappears, no new subscriptions happen, existing
  subscriptions sit inert until the cron runs.

## Live environment (as of Apr 2026)

| Service | URL | Notes |
|---|---|---|
| Frontend | https://opportunity-filter-engine.vercel.app | Vercel Hobby, Next.js 14 |
| Backend | https://opportunity-filter-engine-api.onrender.com | Render Free, FastAPI (cold starts ~30s) |
| Database | https://mjpirkyduibkakvlbdko.supabase.co | Supabase Free |
| Cron | `.github/workflows/daily-reminders.yml` | GitHub Actions, daily 13:00 UTC |

### Environment variables deployed

**Vercel (2):**
- `BACKEND_URL` → Render URL
- `NEXT_PUBLIC_VAPID_PUBLIC_KEY`

**Render (6):**
- `CRON_SECRET`
- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY` (⚠️ bypasses RLS, keep secret)
- `VAPID_PRIVATE_KEY`
- `VAPID_PUBLIC_KEY`
- `VAPID_SUBJECT`

**GitHub Secrets (2):**
- `BACKEND_URL`
- `CRON_SECRET` (must match Render's value)

### Applied Supabase migrations
- 001 (pre-existing)
- 002_interactions
- 003_profile_versions
- 005_interaction_notes (columns: notes, remind_at, last_contacted_at)
- 006_anonymous_auth_rls (auth.uid()::text policies, supersedes 004)
- 007_push_subscriptions

Migration 004 was defined but superseded by 006 — do not apply.

## Data quality — majors/keywords enricher

`src/normalizers/enricher.py` backfills `eligibility.majors` and
`keywords` for opportunities whose upstream source left them empty or
tagged `"Unsorted"`. Wired into `uiuc_our_rss`, `handshake`, and
`manual_importer` normalizers, so new entries are enriched on ingestion.

To retroactively enrich the current dataset:

```bash
# Preview changes
python3 -m src.normalizers.enrich_processed --dry-run

# Persist
python3 -m src.normalizers.enrich_processed --save
```

Rules are regex-based and conservative — never overwrites real upstream
data. Extend `MAJOR_PATTERNS` / `KEYWORD_PATTERNS` in the enricher when
new domains (e.g. a new humanities source) are added.

## Email endpoints (Resend)

Three new endpoints under `/api/email/*`:

- `POST /api/email/send-matches` — send top-50 filtered matches to an email
- `POST /api/email/send-favorites` — send saved opportunities + notes
- `POST /api/email/restore-link` — send a signed URL that verifies on `/restore`

All three return **503** when env vars are unset — the UI falls back
gracefully. To enable:

1. Sign up at [resend.com](https://resend.com) (100 emails/day free).
2. Verify a sending domain or use the built-in `onboarding@resend.dev`
   for testing (not for production — Resend throttles).
3. Add to **Render** env vars:
   ```
   RESEND_API_KEY=re_xxx
   RESEND_FROM_EMAIL=OpportunityEngine <hello@yourdomain.com>
   ```
4. For restore links to work, also set `RESTORE_LINK_SECRET` (or reuse
   `ADMIN_TOKEN`). HMAC-signed, 30-day TTL.

Rate-limits: 3 per IP per hour, enforced in `backend/main.py`.

## What this session deferred

The following were initially planned but **not shipped** to keep the
session focused on infrastructure + Anonymous Auth + Web Push + Compare:

- **Tracker v2** (markdown notes, file attachments, timeline view).
- **Admin dashboard** for data-quality monitoring.
- **College/major i18n** is partial — section headings and form labels
  are translated, but college/major dropdown *values* still render as
  English only (they're dictionary-gated but only `colleges.*` is
  populated, not individual majors). Keys preserve English as form state
  so nothing breaks on locale switch.
