# Private import target storage

B60 adds owner-bound persistence for imported opportunities. It does not publish an opportunity or enable email, résumé, matching, or Tracker actions. Those consumers still resolve the public corpus. The new API has no provider, importer fetch, outbound email, or corpus-write call.

The storage is designed for a user's private account database, including a future hosted deployment. This batch validates it only with mocked HTTP and an isolated local scratch database; it does not apply a hosted migration. Full-source model processing remains a separate, unapproved change.

## API

All paths start with `/api/private-import-targets`. All responses, including validation and request-size errors, are `private, no-store`. Identifiers are `private-import:` followed by a canonical lowercase UUID. A client generates the identifier once and retains it when retrying creation.

- `PUT /{id}` takes `{expected_owner_id, expected_revision, opportunity}`. Revision `0` creates; a positive revision updates only that current revision.
- `GET /{id}?expected_owner_id=...` reads one owned record, including a deletion tombstone.
- `DELETE /{id}` takes `{expected_owner_id, expected_revision}`. It clears `opportunity` and retains a tombstone. A later PUT cannot revive that identifier.
- `GET ?expected_owner_id=...&limit=20` lists active summaries, newest first. The maximum limit is 50. A next page supplies both `before_updated_at` and `before_id` from `next_cursor`. Updates between pages can move a record; this is keyset pagination, not a frozen historical snapshot.

The full response is `{version:1,target,replayed}`. A target contains:

- `id`, `owner_id`, `revision`, `created_at`, `updated_at`, `deleted_at`;
- `opportunity`: the complete accepted raw import JSON, or `null` after deletion;
- `import_source`: the conservative B59 source labels, or `null` when absent/deleted;
- `target_scope:'private_import'`, `verification:'unverified'`;
- `target_version`.

A list response is `{version:1,items,next_cursor}`. Each item contains the identity, revision, timestamps, scope, verification and target version above, plus `title`, `organization` (string or null), `source_url`, `url`, and `source`. Lists omit `opportunity` and `import_source`; a single GET returns the original. `next_cursor` is null or `{updated_at,id}` for the last returned item.

`target_version` is `pit1:` plus SHA-256 of compact, UTF-8, sorted-key JSON containing exactly `{id,owner_id,revision}`. JSON uses no spaces. The SQL write contract increments revision whenever content or deletion state changes. Account transfer changes the owner, so its version changes too. The token is a version binding, not a signature or proof that an arbitrary client object is authentic.

Exact retry returns the original row, unchanged timestamps and `replayed:true`, when the current revision is the request's expected revision plus one and the full JSON payload matches. A different stale payload returns conflict. Delete retries use the same prior revision and tombstone revision. A GET tombstone returns 200 with `opportunity:null`, `import_source:null`, and a non-null `deleted_at`; active lists exclude it. Cross-owner reads and missing IDs both return 404, and never fall back to a public target. A stale expected owner for the current authenticated session returns 409 before storage.

## Accepted source and size

The opportunity has required strings `source`, `title`, `description_raw`; `source` is `url_parser` or `text_parser`. Optional fields are `source_url`, `url`, `organization`, `deadline`, `posted_date`, `location`, `raw_html`, and `extra_fields`. Nullable optional strings follow the raw importer shape. Other top-level fields are rejected; nested JSON metadata is preserved.

- Opportunity compact UTF-8 JSON: at most 8 MiB.
- Request envelope: at most 8 MiB + 64 KiB. A configured lower global body limit also applies.
- Description: nonblank, at most 5,242,880 Unicode code points.
- Extra fields: object, at most 256 KiB compact UTF-8 JSON.
- Title: nonblank, at most 1,000 code points.
- Organization/location: at most 2,000 code points each.
- Source URL/URL: at most 8,192 code points each; omitted or blank paste URLs remain blank.
- Deadline/posted date: at most 128 code points each; these are imported strings, not validated availability facts.
- JSON nesting: maximum depth 32, root depth 0. NUL, unpaired surrogates, non-finite numbers and non-JSON values are rejected.

No field is truncated. Oversized body/description/metadata/aggregate data returns 413. Shape, unsupported fields and short-field length violations return 422. Source labels only describe the recorded import process; they do not prove official provenance, current eligibility, or model verification. `full_source` is never promoted to an accepted AI scope. Raw metadata may retain a claimed `target_truth`, contact snapshot, or model suggestion for the owner's review, but no such value is copied into a public projection, canonical qualification, or writing target. A future consumer must use a purpose-specific private projection and owner resolver, never pass raw metadata into public evidence helpers.

## Authentication and persistence

The API verifies the current bearer session through GoTrue, rejects anonymous accounts and disallowed login providers, and compares the expected owner. It then calls PostgREST RPCs with the user's bearer token, not the service-role bearer. The server key is used only as the configured API key.

Migration `20260929041441_private_import_targets.sql` adds one RLS-enabled table. Browser and service roles receive no direct table access. Public invoker RPCs delegate to private definer functions with an empty `search_path`, explicit `auth.uid()` owner/session checks, fixed object names and revoked PUBLIC/anon execution. Writes use the existing owner lock and an additional target-ID lock. Global IDs prevent two owners from claiming one persisted identity.

The migration depends on the existing `private.target_resume_json_bytes`, `private.material_user`, and `private.material_owner_session`. The material helpers require a live non-anonymous auth user, unexpired JWT, current session row and no merged-account tombstone. This check runs again inside the database transaction, after the API check. The existing proof-bound account-merge transaction transfers these targets through a new tombstone trigger; a deleted auth account removes its private records by FK cascade. This batch does not implement or re-audit the entire account-merge protocol.

Error bodies contain only `detail.code`:

| Code | Status |
|---|---:|
| `private_target_auth_required` | 401 |
| `private_target_owner_changed` | 409 |
| `private_target_not_found` | 404 |
| `private_target_conflict` | 409 |
| `private_target_deleted` | 409 |
| `private_target_invalid_request` | 422 |
| `private_target_too_large` | 413 |
| `private_target_invalid_receipt` | 502 |
| `private_target_unavailable` | 503 |

The generic rate limiter can separately return its existing 429 response. No errors return submitted text, URL, SQL detail, or storage payload.

## Validation and remaining integration

The new actual-route tests mock every GoTrue/PostgREST request and cover create/read/update/delete, retry, retained Chinese/emoji/end-of-source content, summary listing, truthful source labels, wrong owner, anonymous login, safe SQL errors, malformed input, poisoned receipts, and normal/chunked request limits. Related body-limit and B59 source-persistence tests remain part of the focused check.

The SQL bootstrap refuses database names outside `ofe_b60_%`. It copies the existing production owner/session and byte-count helper bodies into an isolated fixture schema with platform identity stubs; it does not replay cron migrations, alter roles, or claim to validate hosted GoTrue/Storage. The SQL suite exercises the actual new migration and these real helper bodies. The initial native PostgreSQL 17.6 run passed its first eight groups, then the server crashed while calling a temporary test helper after `SET ROLE anon`. The server recovered automatically. Further native runs were stopped; the remaining ACL/account-deletion checks and native concurrency were not verified. The revised suite uses catalog ACL checks instead of that cross-role temporary-helper path, but it has not been rerun. This is partial SQL evidence, not a complete migration acceptance.

Still required before the complete private-import journey is available:

- Authenticated central private/public target resolver and purpose-specific unverified projection.
- Email/refinement/manual validation and full-resume context/version integration without expanding model input scope.
- Private target selection, draft restore and explicit source status in the UI.
- Tracker event, history and material views that resolve the owner's private ID while retaining historical records after target deletion.
- Local import adoption and explicit cloud-save/update controls. This batch does not silently upload existing localStorage entries.
- Hosted migration/application deployment and real account acceptance. None is performed here.
