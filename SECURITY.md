# Security Model

## Identity: Supabase Anonymous Auth

This app has no login UI. On first visit each browser silently calls
`supabase.auth.signInAnonymously()` which returns a real `auth.uid()` UUID
backed by the Supabase auth server. The session is persisted in
localStorage (`ofe_auth` key) and auto-refreshed by supabase-js.

The UUID acts as a **bearer token** — whoever holds the session can read
and write that device's data. Same security model as a session cookie.

Previously (pre-migration 006) we used a client-signed HMAC JWT with a
`device_id` claim. That approach required `NEXT_PUBLIC_SUPABASE_JWT_SECRET`
to be exposed to the browser and bypassed Supabase's own auth layer.
Migration 006 removes that custom scheme.

## Row-level security

All four user-data tables (`profiles`, `profile_versions`, `favorites`,
`interactions`) have RLS policies that require `auth.uid()::text` to
match the row's `device_id` column (or `id` for `profiles`). Requests
without a session see no rows.

See `supabase/migrations/006_anonymous_auth_rls.sql` for the policies.

## What this defends against

| Attack | Before 006 | After 006 |
|---|---|---|
| Dump all profiles | ❌ Denied (via 004) | ❌ Denied |
| Read victim's profile with guessed UUID | ❌ Denied | ❌ Denied |
| Write row claiming victim's device_id | ❌ Denied | ❌ Denied |
| Forged JWT via leaked JWT secret | ✅ Possible (client-signed) | ❌ Denied (server-issued only) |

## What this does NOT defend against

- **Stolen session.** If an attacker obtains the victim's session token
  (via XSS, physical device access, logs, or a compromised browser
  extension), they can access that victim's data. Mitigation:
  content-security-policy, strict third-party script policy, keep
  localStorage secret.
- **User on shared device.** Anyone with access to the same browser
  profile can see the data. Expected — this is a per-session model.
- **Server-side compromise.** Supabase service-role key bypasses RLS.
  Keep it in GitHub secrets, never ship it to the client.

## Threat model assumption

Opportunity data (the `opportunities.json` read-only side) is public.
The sensitive data is the user's **profile + behavior** (favorites,
applications) — these are protected by RLS + anonymous auth.

## Running the RLS migration

Supabase must have **Anonymous Sign-ins** enabled
(Authentication → Sign In / Providers → Anonymous Sign-Ins → Enable).
Then apply migration 006:

```bash
supabase db push
# or paste supabase/migrations/006_anonymous_auth_rls.sql into
# dashboard → SQL Editor and run.
```

After running, verify:

```sql
SELECT policyname, cmd FROM pg_policies
WHERE tablename IN ('profiles', 'favorites', 'interactions', 'profile_versions')
ORDER BY tablename, policyname;
```

Each table should have SELECT/INSERT/UPDATE/DELETE policies referencing
`auth.uid()::text`.

## Legacy data (pre-006)

Rows created before migration 006 had `device_id` values derived from a
client-generated UUID in localStorage, not from `auth.uid()`. These rows
are orphaned under RLS — no logged-in anonymous user can read them.
Acceptable because the app has no production users yet. If you need to
preserve any, do a one-time admin-key merge after first login.

## Deprecated env vars

`NEXT_PUBLIC_SUPABASE_JWT_SECRET` is no longer used. You can delete it
from Vercel.
