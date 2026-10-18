# RUNBOOK — operating JoinALab

Checked against the code on 2026-10-09. Every command in a code block was run
that day, except the ones marked **operator**: those need production secrets
or change production. Releases and rollback have their own document,
`docs/RELEASE.md`. Open work is not tracked here (section 9).

## 1. Check what is deployed

```bash
curl -sS https://opportunity-filter-engine-api.onrender.com/api/health
curl -sS https://opportunity-filter-engine-api.onrender.com/api/ready
curl -sS https://joinalab.com/ | grep -o 'data-release-sha="[^"]*"'
```

`/api/health` reports the backend's `release_sha`; the page attribute reports
the frontend's. Both should name the same `main` commit: on 2026-10-09 both
said `6e7530d0`. `/api/ready` answers 200 with `"ready": true`, or 503 with
the failing checks (corpus freshness among them) listed in `reasons`. Render
deploys a `main` commit only after its CI checks pass
(`autoDeployTrigger: checksPass` in `render.yaml`).

## 2. Data refresh

`.github/workflows/refresh-data.yml` runs every day at 06:07 UTC (every schedule
here starts a few minutes past the hour, because GitHub starts top-of-hour
schedules late). It takes the
shard for the UTC weekday (`date -u +%u`, 1 = Monday) from `WEEKLY_ROTATION`
in `scripts/refresh_rotation.py`, so each school is re-scraped once a week.
Monday's shard carries `uiuc`, and Sunday (7) is `national`: the SRO catalog,
NSF REU, SimplifyJobs internships and the campus programs open to students of
every school (the 14 `<slug>_external_research` sources: 13 campus configs and
UC Berkeley's registry). Print any day's shard:

```bash
python3 scripts/refresh_rotation.py --day 1
python3 scripts/refresh_rotation.py --day 7
```

A program moved in a config between a school's own bucket and its open bucket
changes file. Its old row retires on the day that writes the old file, and its
new record publishes on the next day that writes the new one. Until the old row
retires, the log says `held N moved program record(s)`. A listed program can
be missing for up to six days, but it is never listed twice, with one exception.
The hold matches the program's key. If the edit renames the key and changes the
URL too, and the new file's day comes first, the new record publishes beside
the old row until the old file's day retires it. A local run of every source
(`refresh_all` with neither `--schools` nor `--national`) collects each
school's own sources before its open ones, so a program moved out of the open
bucket is missing after that run and lands on the next one.

A program moved between a school's campus and lab sources stays in its file
but gets another id. The run that writes the file retires its old row, and its
new record takes the old row's place. If the old row was closed and shares the
new record's URL or title, that happens once a run loads the record's page, as
below; if both changed, the new record lands at once with its status unknown.
A new record that is a near-duplicate of another row, even a retired one, is
still dropped, so the program is not listed until that row stops matching
(today only CMU's uro_getting_started would be affected if moved).

A program whose page said applications are closed is not listed, so it holds
nothing back, and its old row retires closed. A new record with the old row's
URL is instead dropped as that row's near-duplicate (the log counts it in
`suppressed N near-duplicate(s) vs corpus`) until the old row has retired and
a deep run of the new file loads the record's page. A quick run, or one on
which that page fails to load, leaves the record out. A closed program renamed
with its URL waits the same way. If the page reopens before the old file's
day, the program stays unlisted until the new file's first day after it, up to
13 days after the edit, or later if that day's run cannot load the page. Its
new source must crawl the page (list it in its `seeds`), or the program is
never listed again. In a campus config (`campus_graph`), a record on a page
its config shares with another program (`shared_program_page`) is never
dropped as a near-duplicate, but a quick run or a failed load leaves it out
all the same. So does a program renamed back to a key, or moved back to a
file, where its row retired, or both in one edit: that row comes back only on
a run that loads its page, even before the closed row in the other file
retires. A closed row makes a record wait for a read only if it has the
record's key, or it retired in a file the run writes, or it sits in the other
file under a key that file's sources no longer list. So in a campus config a
closed program still listed in the other file holds no other program back,
even on a shared page. UC Berkeley's registry (`ucb_campus`) has no
shared-page exemption: there a record on the page of such a program is
dropped as that row's near-duplicate, even on a run that reads the page open.
In both, a closed program retired in the other file and listed there again
holds no other program back. The wait does not look at how old the closed
reading is: a program coming back to its own retired row waits for a run that
loads its page if a row on that page retired closed in that file (another
program's on a shared page, or its own under a key it has dropped), even if a
later run read the page open. That is cautious, and a new program on that page
waits the same way. The log counts the records left out to wait for a read in
`suppressed N near-duplicate(s) vs corpus` too.

To retire a config's open programs, empty the open source's `programs` and
leave the source in place until a Sunday run has passed. A deleted open source
has no run that retires its rows in national.json. While the emptied source
stays in the config:

- It emits no record. A Sunday on which its seed page fails to load makes it a
  source error, and the release withholds all of national.json, the SRO
  catalog, NSF REU and SimplifyJobs rows included.
- From the Sunday that retires its last row, it reports `suspicious_zero`
  ("0 records, previously 0") every Sunday, and national.json publishes
  degraded, until the source is deleted.

`--day` refuses to answer when a supported school sits in no shard or in two.
That check exists because 25 registered schools were once in no shard and
went unrefreshed after onboarding. A school leaves the rotation only by
leaving the product (`src/school_scope.py`).

What one scheduled run does:

1. Scrapes its shard in deep mode, with a 240-minute source budget (210 on a
   day that also runs the Illinois Experts pass). The job itself times out at
   350 minutes.
2. In the first seven days of the month, follows each faculty profile link of
   the shard (`OFE_ENRICH_PROFILES=1`). On the first Monday it also runs the
   Illinois Experts pass for `uiuc`, capped at 30 minutes.
3. Runs the corpus-wide offline passes (`python -m src.normalizers.enrich_processed --save`,
   `python -m src.normalizers.deactivate_past --save`) and the data-quality
   tests.
4. Writes back only the shards it was allowed to refresh and whose sources
   succeeded, opens an `auto/refresh-data-*` PR, and squash-merges it once the
   required checks pass. That step needs the `REFRESH_PAT` secret.
5. Checks in to the dead man's switch (section 3).

GitHub can start a scheduled run late; the 2026-10-02 run started 5.5 hours
late. Scheduled and manual runs sit in separate concurrency groups, and the
first step keeps them apart: a manual run defers to a refresh in progress, and
a scheduled run cancels a manual one.

**Manual run (operator).** Actions → Refresh Opportunity Data → Run workflow.
`schools` takes comma-separated school slugs or `national`; empty means a
full refresh. `deep` and `enrich_profiles` are `true`/`false`. The
workflow validates `schools` with this command, which you can run first:

```bash
python3 scripts/refresh_rotation.py --schools ucla --allow-full
python3 scripts/refresh_rotation.py --schools ucla --allow-full --needs-browser
```

The second prints whether the run will install headless Chromium. To read a
refresh's options locally, run `python -m src.collectors.refresh_all --help`;
publish data through the workflow's PR, not a hand-committed shard.

## 3. Other scheduled jobs

| Workflow | When (UTC) | What it does |
|---|---|---|
| `ops-scan.yml` | daily 11:13 | `POST /api/cron/ops-scan`: files collector and drift incidents |
| `snapshot-reminder.yml` | daily 13:23 | Once a week (the week's first good run) emails the operator when a hand-exported snapshot (CMU) is due |
| `daily-reminders.yml` | daily 23:11 | `GET /api/cron/reminders` (Web Push, email fallback), then the data-quality check and the feedback and orders digests |
| `saved-searches-refresh.yml` | daily 23:41 | `GET /api/cron/saved-searches/refresh`, then `/digest` |
| `campus-seed-health.yml` | Sunday 12:19 | Probes configured seed and program URLs for dead pages |
| `release-gate.yml` | manual only | The release gate (`docs/RELEASE.md`) |

Every scheduled workflow checks in with `POST /api/cron/heartbeat` at the
end. A pg_cron job from migration 032 files an incident for any heartbeat that
misses its deadline, and `ops-scan` checks the pg_cron job's own heartbeat.
`docs/RELEASE.md` ("The dead man's switch") has the drill. `ops-scan`,
`daily-reminders` and `saved-searches-refresh` start with a "Require the
secrets this cron runs on" step that names the secrets each needs. Every
workflow above also has a manual Run workflow button (**operator**).

## 4. Database migrations

### Why the 52 names look different

`supabase/migrations/` held 52 files on 2026-10-15. A migration's version is
the part of its name before the first underscore. The Supabase CLI applies
files in filename order and records each version once.

| Names | Count | Where they came from |
|---|---|---|
| `001`–`034` | 34 | The original three-digit sequence. `001` was written on 2026-07-24 (#646) to recreate tables first made in the dashboard. The last two, `033` (2026-08-27) and `034` (2026-09-05), landed after the first timestamp file. |
| `0181_oauth_merge_secret`, `0201_usage_events` | 2 | Renamed from `018_` and `020_` in #646 because two files shared each version, which made `supabase db push` impossible. Content unchanged. In filename order `0181_` runs before `018_` and `0201_` before `020_`. |
| `20260819164641_…` onward | 16 | `YYYYMMDDHHMMSS` UTC timestamps, the format `supabase migration new` writes. Every migration since 2026-09-24 uses it. |

The replay in CI (`supabase/tests/run_supabase_cli_migration_test.sh`)
applies every file into an empty database in that order.

### Rule for a new migration

1. Create it with `supabase migration new <snake_case_name>`. It gets a UTC
   timestamp later than every existing file. Never use a three-digit name: a
   `035_` sorts before all the timestamp files, so a fresh replay would run it
   before 16 migrations it may depend on. `tests/test_docs_current.py` fails on
   any new name that is not a 14-digit timestamp later than `20260930220000`,
   the newest version when the check was written.
2. Never edit or rename a migration that production has run. Write a new one
   that supersedes it; the chain is forward-only (`docs/RELEASE.md`,
   "Migration recovery").
3. Add the version to the array in
   `supabase/tests/migration_history_contract_test.sql`. Add its SQL test
   under `supabase/tests/` and name that test in a runner CI executes.
   `tests/test_ci_gate_honesty.py` fails while the version is missing from
   the array or a SQL test is named by no CI runner.
4. Replay locally:

   ```bash
   bash supabase/tests/run_flow_b_test.sh
   bash supabase/tests/run_supabase_cli_migration_test.sh
   ```

5. **Operator:** the owner applies it to production by hand, through the
   dashboard SQL editor or the Supabase MCP `apply_migration`, sending the
   file unchanged. Never run `supabase db push` against
   production. Production's history records `012`, `013` and `014` under
   timestamp versions such as `20260611111920`, so match its ledger to the
   files by name, not by version string (`docs/RELEASE.md`, section 5, and
   `supabase/MIGRATION_REPAIR.md`). `scripts/check_migration_parity.py` does
   that match offline: `--print-sql` prints the read-only export query, and
   `--applied <export>` reads its result back and exits 1 on drift, such as
   a file production never ran or a row the repo does not have. Running the
   query against production waits on the owner's OK.

`supabase db push` with the pinned CLI 2.95.4 works only on an empty
database. On 2026-10-09 a scratch database that had taken the full chain
refused all five follow-up pushes tried: with and without `--include-all`,
with and without a new migration file. Each time the CLI reported remote
versions `018` and `020` as missing locally. `supabase migration list` shows
the mismatch: it lists the remote `018` before `0181` and the local `018`
after it.

## 5. Release flags

`docs/product_scope.md` lists every flag, its state and why each closed one
is closed. A flag flips only in that feature's acceptance PR, which edits both
`backend/lib/release_scope.py` and `frontend/src/lib/release-scope.ts`, moves
the feature from `UNACCEPTED_FEATURES` to `ACCEPTED_FEATURES` in
`tests/test_release_scope.py`, and updates the table in
`docs/product_scope.md`.

## 6. Setting up a new environment

1. **Supabase.** Enable Authentication → Sign In / Providers → Anonymous
   Sign-Ins. Without it, `signInAnonymously()` returns HTTP 422
   (`anonymous_provider_disabled`), and the app keeps favorites in the browser
   under a "Saved locally only" banner. Then apply the migrations. Into an
   empty database `supabase db push` takes the whole chain, which is what the
   CI replay does (section 4).
2. **Secrets.** `docs/RELEASE.md` section 6 lists every variable the
   backend, the frontend build and the workflows read, whether production
   needs it, and what breaks without it. The backend's go in the Render
   dashboard (`render.yaml` holds only non-secret settings), the frontend's
   build variables in Vercel, and the workflows' in GitHub repository
   secrets. Section 3 says where the cron workflows name theirs.
3. **Web Push.** Generate a VAPID keypair and set `VAPID_PRIVATE_KEY`,
   `VAPID_PUBLIC_KEY` and `VAPID_SUBJECT` on the backend. Keep the private key
   in a password manager.

   ```bash
   python scripts/generate_vapid_keys.py
   ```

   The script also prints a `NEXT_PUBLIC_VAPID_PUBLIC_KEY` line. Nothing on the
   frontend reads it: the browser asks `GET /api/push/vapid-public-key`, which
   answers 503 until the backend has a public key, and the backend accepts
   that name only as a fallback for `VAPID_PUBLIC_KEY`.
4. **Check** with section 1's commands against the new hosts.

## 7. Releases and rollback

`docs/RELEASE.md`: the gate, the evidence each check needs, rollback for
Render, Vercel and the database, and the known weak spots.

## 8. Data export and deletion request

> **Partly run in production.** Written on 2026-10-12 from
> `supabase/migrations/` and the code that reads it. Its SQL first ran on a
> local PostgreSQL 16 replay of the migrations (all but the superseded `004`)
> on top of `supabase/tests/_stubs.sql`, with a seed script adding the
> `auth.users` columns `email`, `created_at` and `last_sign_in_at` and the
> `auth.identities` table the stubs lack. There the SQL exported, deleted and
> re-exported a test account and a guest merged into it and left a second
> account untouched; Storage was simulated by deleting `storage.objects` rows,
> auth users were deleted with SQL, and the token wait in step 5 was not
> exercised.
>
> On 2026-10-13 the owner had it run on the production test account, through
> the Supabase MCP connector (which runs as `postgres`, like the SQL editor):
>
> - the table check listed 25 tables with a `device_id` or `owner_id` column,
>   all of them in the table below;
> - the account had 4 uids: itself and 3 merged guests, all anonymous with no
>   email;
> - the export returned rows for `auth.users` 4, `auth.identities` 1,
>   `profiles` 1, `profile_versions` 39, `favorites` 1, `analytics_events` 114,
>   `target_resumes` 7, `target_resume_versions` 17, `private_import_targets` 1,
>   `merge_grants` 3 and `merged_devices` 3 (about 627 KB of JSON), and 0 rows
>   for every other table; the file listing was empty;
> - step 2 deleted exactly the exported rows of its tables: `profiles` 1,
>   `profile_versions` 39, `favorites` 1, `analytics_events` 114,
>   `merge_grants` 3.
>
> Steps 3 to 6 were not run in production: the connector declined
> `DELETE FROM auth.users`, so step 3 needs the dashboard (Authentication →
> Users) as written below, and steps 4 to 6 come after it. Step 1 and the
> material cleanup check have not run against real Storage anywhere.

Privacy §7 (`frontend/src/app/privacy/page.tsx`) promises a full export or
deletion within 30 days of an emailed request, after checking that the request
is genuinely the student's. Every step is **operator**. The SQL runs in the
Supabase dashboard's SQL editor, which runs as `postgres` rather than as a
student; files are handled in its Storage browser.

**Which rows belong to the student.** The app keys almost every row by
`device_id`, the auth user id as text (`auth.uid()::text`, migration 006). A
signed-in account also owns each guest session merged into it: `merged_devices`
(017) holds one row per merged guest uid (`source_device_id`) with the
account's uid as `target_device_id`. The merge re-keys the guest's rows to the
account but leaves its tracker attachments in Storage under the guest's uid,
and the guest's auth user stays (anonymous, no email). The queries below
therefore search the account's uid and every uid merged into it. Step 4 of
the deletion removes the `merged_devices` rows that link them, so the list of
uids is worked out once, saved, and pasted into every later query as a fixed
list.

| Keyed by | Tables |
|---|---|
| `id` (the uid) | `profiles` |
| `device_id` | `profile_versions`, `favorites`, `interactions`, `interaction_status_changes`, `interaction_merge_archive` (also `source_device_id`), `saved_searches`, `match_feedback`, `push_subscriptions`, `analytics_events`, `waitlist`, `feedback`, `orders`, `usage_events`, `resume_renovations` and `resume_renovation_versions` (also `owner_id`), `professor_follows`, `professor_update_reads`, `contact_events`, `application_events`, `outcome_notes` |
| `owner_id` (uuid) | `target_resumes`, `target_resume_versions`, `private_import_targets`, `material_artifacts`, `application_material_records`, `contact_material_records` |
| something else | `feedback_events` (`ticket_id` of the student's `feedback`); `ops_incidents` (a reminder or digest failure names the uid or a saved search id in `dedup_key`); `merge_grants` (`source_device_id`, `redeemed_by`, `target_email`); `merged_devices` |
| Storage | `tracker-attachments`: objects named `<device_id>/<opportunity_id>/<file>`. `application-materials`: objects named `pdf/<material_id>.pdf`, found through `material_artifacts.object_key` |

The table comes from the migrations. A table created in the dashboard would
not be in it, so before each request list every table in `public` that has a
`device_id` or `owner_id` column (read only) and compare. A table missing from
the table above needs its rows exported and deleted by hand, and this section
updated.

```sql
SELECT c.relname AS table_name, string_agg(a.attname, ', ' ORDER BY a.attname) AS key_columns
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum > 0 AND NOT a.attisdropped
WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p') AND a.attname IN ('device_id', 'owner_id')
GROUP BY c.relname
ORDER BY 1;
```

Rows written before migration 006 are keyed by a device id the browser made
up, not by an auth uid. Nothing ties them to a student, so this procedure
neither finds nor deletes them (`20260925052636_legacy_renovation_cas_rpc.sql`
leaves such `resume_renovations` rows unclaimed for the same reason).

### Find the account

```sql
SELECT id, email, is_anonymous, created_at FROM auth.users
WHERE lower(email) = lower('student@example.edu');
```

A guest session has no email, so a guest's request can only be found from the
uid itself. If the request gives a guest uid, first check whether that guest
was merged into an account:

```sql
SELECT target_device_id FROM public.merged_devices
WHERE source_device_id = '00000000-0000-0000-0000-000000000000';
```

If it returns a row, the guest's rows now belong to that account: repeat the
check with the account's uid until it returns nothing, then act on the request
as that account's, found by its uid and verified against its email.

Then list the uids to search: the account's uid and every guest uid merged
into it, with what `auth.users` holds for each. Put the account's uid in
place of the zero uuid.

```sql
WITH RECURSIVE owned(device_id) AS (
  SELECT '00000000-0000-0000-0000-000000000000'::text
  UNION
  SELECT m.source_device_id FROM public.merged_devices m JOIN owned o ON m.target_device_id = o.device_id
)
SELECT o.device_id, u.email, u.is_anonymous, '{' || string_agg(o.device_id, ',') OVER () || '}' AS saved_ids
FROM owned o LEFT JOIN auth.users u ON u.id::text = o.device_id
ORDER BY u.is_anonymous, o.device_id;
```

Every row other than the account's must show `is_anonymous` true and no
email (or nothing at all, if that guest's auth user is already gone; keep it
in the list). A merged uid that shows a signed-in account (an email, or
`is_anonymous` false) is a separate account. Do not include it unless the
student shows it is theirs as well, verified the same way as the first;
otherwise leave it out of the list and treat it as someone else's data.

Save the `saved_ids` value (with any such uid removed) and the account's
email with the request. Every query below starts with
`ids AS (SELECT '{…}'::text[] AS a, lower('…') AS email)`: put the saved list
in place of `{00000000-0000-0000-0000-000000000000}` and the email in place of
`student@example.edu` (for a guest with no account, replace
`lower('student@example.edu')` with `NULL::text`). From the export on, use
only the saved list: step 4 removes the rows that link the guest uids to the
account, so the list cannot be worked out again afterwards.

### Export (SELECT only)

One row per table: its row count and its rows as JSON. The `owned_device_ids`
row lists the uids searched. Push keys, merge-grant tokens and hashes are left
out.

```sql
WITH ids AS (SELECT '{00000000-0000-0000-0000-000000000000}'::text[] AS a, lower('student@example.edu') AS email),
searches AS (
  SELECT coalesce(array_agg(s.id::text), '{}') AS a FROM public.saved_searches s, ids WHERE s.device_id = ANY (ids.a)
),
export(source, rows) AS (
  SELECT 'owned_device_ids', (SELECT to_jsonb(a) FROM ids)
  UNION ALL SELECT 'auth.users', (SELECT jsonb_agg(jsonb_build_object('id', t.id, 'email', t.email,
      'is_anonymous', t.is_anonymous, 'created_at', t.created_at, 'last_sign_in_at', t.last_sign_in_at))
    FROM auth.users t, ids WHERE t.id::text = ANY (ids.a))
  UNION ALL SELECT 'auth.identities', (SELECT jsonb_agg(jsonb_build_object('provider', t.provider,
      'identity_data', t.identity_data, 'created_at', t.created_at))
    FROM auth.identities t, ids WHERE t.user_id::text = ANY (ids.a))
  UNION ALL SELECT 'profiles', (SELECT jsonb_agg(t) FROM public.profiles t, ids WHERE t.id = ANY (ids.a))
  UNION ALL SELECT 'profile_versions', (SELECT jsonb_agg(t) FROM public.profile_versions t, ids WHERE t.device_id = ANY (ids.a))
  UNION ALL SELECT 'favorites', (SELECT jsonb_agg(t) FROM public.favorites t, ids WHERE t.device_id = ANY (ids.a))
  UNION ALL SELECT 'interactions', (SELECT jsonb_agg(t) FROM public.interactions t, ids WHERE t.device_id = ANY (ids.a))
  UNION ALL SELECT 'interaction_status_changes', (SELECT jsonb_agg(t) FROM public.interaction_status_changes t, ids WHERE t.device_id = ANY (ids.a))
  UNION ALL SELECT 'interaction_merge_archive', (SELECT jsonb_agg(t) FROM public.interaction_merge_archive t, ids
    WHERE t.device_id = ANY (ids.a) OR t.source_device_id = ANY (ids.a))
  UNION ALL SELECT 'saved_searches', (SELECT jsonb_agg(t) FROM public.saved_searches t, ids WHERE t.device_id = ANY (ids.a))
  UNION ALL SELECT 'match_feedback', (SELECT jsonb_agg(t) FROM public.match_feedback t, ids WHERE t.device_id = ANY (ids.a))
  UNION ALL SELECT 'push_subscriptions', (SELECT jsonb_agg(to_jsonb(t) - 'p256dh' - 'auth') FROM public.push_subscriptions t, ids WHERE t.device_id = ANY (ids.a))
  UNION ALL SELECT 'analytics_events', (SELECT jsonb_agg(t) FROM public.analytics_events t, ids WHERE t.device_id = ANY (ids.a))
  UNION ALL SELECT 'waitlist', (SELECT jsonb_agg(t) FROM public.waitlist t, ids WHERE t.device_id = ANY (ids.a))
  UNION ALL SELECT 'feedback', (SELECT jsonb_agg(t) FROM public.feedback t, ids WHERE t.device_id = ANY (ids.a))
  UNION ALL SELECT 'feedback_events', (SELECT jsonb_agg(t) FROM public.feedback_events t, ids
    WHERE t.ticket_id IN (SELECT f.id FROM public.feedback f WHERE f.device_id = ANY (ids.a)))
  UNION ALL SELECT 'orders', (SELECT jsonb_agg(t) FROM public.orders t, ids WHERE t.device_id = ANY (ids.a))
  UNION ALL SELECT 'usage_events', (SELECT jsonb_agg(t) FROM public.usage_events t, ids WHERE t.device_id = ANY (ids.a))
  UNION ALL SELECT 'resume_renovations', (SELECT jsonb_agg(t) FROM public.resume_renovations t, ids WHERE t.device_id = ANY (ids.a))
  UNION ALL SELECT 'resume_renovation_versions', (SELECT jsonb_agg(t) FROM public.resume_renovation_versions t, ids WHERE t.device_id = ANY (ids.a))
  UNION ALL SELECT 'professor_follows', (SELECT jsonb_agg(t) FROM public.professor_follows t, ids WHERE t.device_id = ANY (ids.a))
  UNION ALL SELECT 'professor_update_reads', (SELECT jsonb_agg(t) FROM public.professor_update_reads t, ids WHERE t.device_id = ANY (ids.a))
  UNION ALL SELECT 'contact_events', (SELECT jsonb_agg(t) FROM public.contact_events t, ids WHERE t.device_id = ANY (ids.a))
  UNION ALL SELECT 'application_events', (SELECT jsonb_agg(t) FROM public.application_events t, ids WHERE t.device_id = ANY (ids.a))
  UNION ALL SELECT 'outcome_notes', (SELECT jsonb_agg(t) FROM public.outcome_notes t, ids WHERE t.device_id = ANY (ids.a))
  UNION ALL SELECT 'target_resumes', (SELECT jsonb_agg(t) FROM public.target_resumes t, ids WHERE t.owner_id::text = ANY (ids.a))
  UNION ALL SELECT 'target_resume_versions', (SELECT jsonb_agg(t) FROM public.target_resume_versions t, ids WHERE t.owner_id::text = ANY (ids.a))
  UNION ALL SELECT 'private_import_targets', (SELECT jsonb_agg(t) FROM public.private_import_targets t, ids WHERE t.owner_id::text = ANY (ids.a))
  UNION ALL SELECT 'material_artifacts', (SELECT jsonb_agg(t) FROM public.material_artifacts t, ids WHERE t.owner_id::text = ANY (ids.a))
  UNION ALL SELECT 'application_material_records', (SELECT jsonb_agg(t) FROM public.application_material_records t, ids WHERE t.owner_id::text = ANY (ids.a))
  UNION ALL SELECT 'contact_material_records', (SELECT jsonb_agg(t) FROM public.contact_material_records t, ids WHERE t.owner_id::text = ANY (ids.a))
  UNION ALL SELECT 'ops_incidents', (SELECT jsonb_agg(t) FROM public.ops_incidents t, ids, searches
    WHERE EXISTS (SELECT 1 FROM unnest(ids.a || searches.a) k WHERE strpos(t.dedup_key, k) > 0))
  UNION ALL SELECT 'merge_grants', (SELECT jsonb_agg(to_jsonb(t) - 'token' - 'secret_hash') FROM public.merge_grants t, ids
    WHERE t.source_device_id = ANY (ids.a) OR t.redeemed_by = ANY (ids.a) OR lower(t.target_email) = ids.email)
  UNION ALL SELECT 'merged_devices', (SELECT jsonb_agg(t) FROM public.merged_devices t, ids
    WHERE t.source_device_id = ANY (ids.a) OR t.target_device_id = ANY (ids.a))
)
SELECT source, coalesce(jsonb_array_length(rows), 0) AS row_count, rows FROM export;
```

Files, listed for the same uids. An `application-materials` row with
no `created_at` has no object left (deleted by the student and already
erased, or never uploaded). Keep the `application-materials` names: the
deletion check below needs them after the rows that point to them are gone.

```sql
WITH ids AS (SELECT '{00000000-0000-0000-0000-000000000000}'::text[] AS a, lower('student@example.edu') AS email)
SELECT o.bucket_id, o.name, o.created_at, NULL AS material_status
FROM storage.objects o, ids
WHERE o.bucket_id = 'tracker-attachments' AND (storage.foldername(o.name))[1] = ANY (ids.a)
UNION ALL
SELECT 'application-materials', a.object_key, o.created_at, a.status
FROM public.material_artifacts a CROSS JOIN ids
LEFT JOIN storage.objects o ON o.bucket_id = 'application-materials' AND o.name = a.object_key
WHERE a.owner_id::text = ANY (ids.a)
ORDER BY 1, 2;
```

Download each listed object that exists from the Storage browser and send the
files with the query results.

### Deletion

Export first, so the counts can be compared afterwards. Then, in this order:

1. **Tracker attachments.** In the Storage browser, delete the folder of each
   saved uid in `tracker-attachments`. Use Storage, not SQL: deleting a
   `storage.objects` row does not erase the stored file
   (`docs/material_archive_http_contract.md`). Rerun the file listing; no
   `tracker-attachments` row may remain.
2. **Rows keyed by `device_id`, plus the incidents and merge grants that name
   the student.** One statement; it returns how many rows it deleted from each
   table. `feedback_events` go with their `feedback` (`ON DELETE CASCADE`),
   and `ops_incident_events` with their `ops_incidents`. It leaves
   `contact_events`, `application_events` and `outcome_notes` alone: their
   trigger refuses a delete while the auth user exists.

   ```sql
   WITH ids AS (SELECT '{00000000-0000-0000-0000-000000000000}'::text[] AS a, lower('student@example.edu') AS email),
   searches AS (
     SELECT coalesce(array_agg(s.id::text), '{}') AS a FROM public.saved_searches s, ids WHERE s.device_id = ANY (ids.a)
   ),
   d_ops_incidents AS (DELETE FROM public.ops_incidents t USING ids, searches
     WHERE EXISTS (SELECT 1 FROM unnest(ids.a || searches.a) k WHERE strpos(t.dedup_key, k) > 0) RETURNING 1),
   d_profiles AS (DELETE FROM public.profiles t USING ids WHERE t.id = ANY (ids.a) RETURNING 1),
   d_profile_versions AS (DELETE FROM public.profile_versions t USING ids WHERE t.device_id = ANY (ids.a) RETURNING 1),
   d_favorites AS (DELETE FROM public.favorites t USING ids WHERE t.device_id = ANY (ids.a) RETURNING 1),
   d_interactions AS (DELETE FROM public.interactions t USING ids WHERE t.device_id = ANY (ids.a) RETURNING 1),
   d_interaction_status_changes AS (DELETE FROM public.interaction_status_changes t USING ids WHERE t.device_id = ANY (ids.a) RETURNING 1),
   d_interaction_merge_archive AS (DELETE FROM public.interaction_merge_archive t USING ids
     WHERE t.device_id = ANY (ids.a) OR t.source_device_id = ANY (ids.a) RETURNING 1),
   d_saved_searches AS (DELETE FROM public.saved_searches t USING ids WHERE t.device_id = ANY (ids.a) RETURNING 1),
   d_match_feedback AS (DELETE FROM public.match_feedback t USING ids WHERE t.device_id = ANY (ids.a) RETURNING 1),
   d_push_subscriptions AS (DELETE FROM public.push_subscriptions t USING ids WHERE t.device_id = ANY (ids.a) RETURNING 1),
   d_analytics_events AS (DELETE FROM public.analytics_events t USING ids WHERE t.device_id = ANY (ids.a) RETURNING 1),
   d_waitlist AS (DELETE FROM public.waitlist t USING ids WHERE t.device_id = ANY (ids.a) RETURNING 1),
   d_feedback AS (DELETE FROM public.feedback t USING ids WHERE t.device_id = ANY (ids.a) RETURNING 1),
   d_orders AS (DELETE FROM public.orders t USING ids WHERE t.device_id = ANY (ids.a) RETURNING 1),
   d_usage_events AS (DELETE FROM public.usage_events t USING ids WHERE t.device_id = ANY (ids.a) RETURNING 1),
   d_resume_renovations AS (DELETE FROM public.resume_renovations t USING ids WHERE t.device_id = ANY (ids.a) RETURNING 1),
   d_resume_renovation_versions AS (DELETE FROM public.resume_renovation_versions t USING ids WHERE t.device_id = ANY (ids.a) RETURNING 1),
   d_professor_follows AS (DELETE FROM public.professor_follows t USING ids WHERE t.device_id = ANY (ids.a) RETURNING 1),
   d_professor_update_reads AS (DELETE FROM public.professor_update_reads t USING ids WHERE t.device_id = ANY (ids.a) RETURNING 1),
   d_merge_grants AS (DELETE FROM public.merge_grants t USING ids
     WHERE t.source_device_id = ANY (ids.a) OR t.redeemed_by = ANY (ids.a) OR lower(t.target_email) = ids.email RETURNING 1)
   SELECT (SELECT count(*) FROM d_ops_incidents) AS ops_incidents,
     (SELECT count(*) FROM d_profiles) AS profiles,
     (SELECT count(*) FROM d_profile_versions) AS profile_versions,
     (SELECT count(*) FROM d_favorites) AS favorites,
     (SELECT count(*) FROM d_interactions) AS interactions,
     (SELECT count(*) FROM d_interaction_status_changes) AS interaction_status_changes,
     (SELECT count(*) FROM d_interaction_merge_archive) AS interaction_merge_archive,
     (SELECT count(*) FROM d_saved_searches) AS saved_searches,
     (SELECT count(*) FROM d_match_feedback) AS match_feedback,
     (SELECT count(*) FROM d_push_subscriptions) AS push_subscriptions,
     (SELECT count(*) FROM d_analytics_events) AS analytics_events,
     (SELECT count(*) FROM d_waitlist) AS waitlist,
     (SELECT count(*) FROM d_feedback) AS feedback,
     (SELECT count(*) FROM d_orders) AS orders,
     (SELECT count(*) FROM d_usage_events) AS usage_events,
     (SELECT count(*) FROM d_resume_renovations) AS resume_renovations,
     (SELECT count(*) FROM d_resume_renovation_versions) AS resume_renovation_versions,
     (SELECT count(*) FROM d_professor_follows) AS professor_follows,
     (SELECT count(*) FROM d_professor_update_reads) AS professor_update_reads,
     (SELECT count(*) FROM d_merge_grants) AS merge_grants;
   ```

3. **The auth users.** First rerun the uid list query from "Find the
   account". If it shows a uid the saved list lacks (a guest merged in since),
   check it as described there, add it to the list, and repeat steps 1 and 2
   with the new list. Then delete every saved uid that still has an auth user
   (the export's `auth.users` row) under Authentication → Users, and never a
   signed-in account that was left out of the list. The triggers below fire
   only when the `auth.users` row is really deleted, so a soft delete is not
   enough. For each deleted user:
   - `auth_user_delete_contact_events`,
     `auth_user_delete_application_events` and
     `auth_user_delete_outcome_notes` delete its `contact_events`,
     `application_events` and `outcome_notes`;
   - `auth_user_delete_materials` queues every `material_artifacts` object key
     in `private.material_cleanup_outbox` and deletes the artifacts; their
     `application_material_records` and `contact_material_records` go with
     them (`ON DELETE CASCADE`, which the records' guard allows once the auth
     row is gone);
   - `ON DELETE CASCADE` from `auth.users` removes `target_resumes` (and their
     `target_resume_versions`), `private_import_targets`, and any
     `resume_renovations` or `resume_renovation_versions` step 2 left.
4. **The merge tombstones**, last, so no guest session counts as active again
   while its auth user still exists. First re-run the id-list query from
   "Find the account": a guest merged into the account after step 3's re-check
   would otherwise lose its link here and keep its empty guest login. If the
   list shows a uid that is not in the saved list, add it and handle it as
   step 3 does (steps 2-3 for that uid) before running this step:

   ```sql
   WITH ids AS (SELECT '{00000000-0000-0000-0000-000000000000}'::text[] AS a, lower('student@example.edu') AS email)
   DELETE FROM public.merged_devices m USING ids
   WHERE m.source_device_id = ANY (ids.a) OR m.target_device_id = ANY (ids.a);
   ```

5. **Wait out open sessions.** Deleting an auth user does not end a session
   that is already open: its access token stays valid until it expires, so a
   tab the student left open can still write rows keyed by one of the saved
   uids (for example `favorites` or `analytics_events`) and upload tracker
   attachments, both during the deletion and for up to one token lifetime
   after step 3. That lifetime is the project's JWT expiry, 3,600 seconds
   unless it was changed; the dashboard shows it in the project settings as
   the JWT (access token) expiry, and Supabase's Management API returns it as
   `jwt_exp` in the project's auth config. Wait that long plus a few minutes
   after step 3, then run step 2's statement and the file listing again, and
   delete any `tracker-attachments` folder the listing shows, as in step 1.
6. **Check.** Rerun the export: every `row_count` is 0 except
   `owned_device_ids`, which keeps the saved list. Rerun the file listing: no
   rows. If a count is not 0:
   - a table that step 2 deletes from, or a `tracker-attachments` file:
     something wrote after the last run of step 2. Run step 2 (and step 1)
     again; if step 3 was less than one token lifetime ago, wait until it is
     not, and check again;
   - `auth.users`: a listed user was not deleted; delete it as in step 3,
     then repeat steps 5 and 6;
   - `merged_devices`: repeat step 4;
   - any other table: those rows should have gone with the auth user. Do not
     delete them by hand (a `material_artifacts` row deleted that way never
     queues its file for erasure); find out why they stayed, fix this section,
     and record what happened here.

   Then check that the backend's cleanup loop (`backend/lib/material_cleanup.py`,
   every 60 seconds) erased the `application-materials` files; put the names
   saved from the export in the array:

   ```sql
   SELECT o.object_key, o.attempts, o.last_removed_at, o.completed_at,
     EXISTS (SELECT 1 FROM storage.objects s WHERE s.bucket_id = 'application-materials' AND s.name = o.object_key) AS file_left
   FROM private.material_cleanup_outbox o
   WHERE o.object_key = ANY ('{pdf/00000000-0000-0000-0000-000000000000.pdf}'::text[]);
   ```

   Each key needs a row with `file_left` false and `last_removed_at` set.
   `completed_at` stays empty until the loop has found the file absent again
   24 hours after the key was queued.

Nothing here reaches the student's browser storage, the hosting and error
logs, or mail the email provider holds (privacy §6). Tell the student to
clear the site data in their browser.

## 9. Open work

The single to-do list is the owner's MVP checklist (the private "OE todolist"
Google Doc, MVP tab, items numbered from M01). Work that is not in it is not planned.
