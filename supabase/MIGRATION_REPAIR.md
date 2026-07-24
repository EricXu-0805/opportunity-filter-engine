# Supabase migration history repair (prod: mjpirkyduibkakvlbdko, PG17)

## Observed state (read 2026-07-22, re-verified 2026-07-24)

Prod has 17 public tables and 471 real users, but
`supabase_migrations.schema_migrations` contains only THREE rows:

- `20260611111920_match_feedback` — hosted alias of local `012`
- `20260611115956_saved_search_digest` — hosted alias of local `013`
- `20260612065309_advisor_hardening` — hosted alias of local `014`

Everything else in `supabase/migrations/` was applied to prod via the
Management API (SQL executed directly), which bypasses the CLI's history
table entirely. The three rows exist because those migrations went through
the hosted migration flow; never delete or "repair" them.

## Hard rule

**Never run `supabase db push` against prod until history repair is
complete.** The CLI sees ~20 "unapplied" migrations and would re-execute
SQL against live tables. Also: `supabase db pull` is NOT a read-only
probe — it writes a migration file and may offer to update remote
history. Run it only in a disposable checkout, never in a release
worktree. CI proves the chain against a throwaway local cluster only.

## Repair plan (manual, approval-gated, NOT in any PR)

1. Confirm backup/PITR status in the Supabase dashboard first; record the
   recovery point. Stop if recoverability is unknown.
2. Capture evidence before touching history:

   ```bash
   supabase migration list --linked
   supabase db dump --linked --schema public --schema storage \
     --file <secure-location>/joinalab-before.sql
   ```

3. Verify each local migration's effect already exists in prod (SQL editor
   spot-checks: table shapes, policies, function signatures). A visible
   table does not prove its columns/policies/ACLs — check the parts each
   migration owns.
4. Backfill history entries for already-applied migrations, in file
   order, marking them applied WITHOUT executing SQL:

   ```bash
   supabase migration repair --status applied 001 002 003 ... 021
   ```

   Keep the three hosted alias rows as-is (they cover 012/013/014 — do
   not double-record those under local version numbers).
5. Re-run `supabase migration list --linked` and confirm local files and
   remote history agree. Only then does `db push` become safe for future
   migrations.

## Why the chain is now replayable

`001` codifies the Dashboard-created `profiles`/`favorites` tables
(idempotent, no ACL statements — later migrations own grants/RLS), the
former duplicate versions `018`/`020` were renamed `0181`/`0201`, and
`006` drops `current_device_id()` only after replacing the 004 policies
that referenced it (real CLI push failed with SQLSTATE 2BP01 before).
CI replays the full chain with the pinned real CLI on every PR.
