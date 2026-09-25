# Batch 33 material archive RPC contract

Status: local SQL implementation complete. Dedicated, full regression, concurrency, and real Supabase CLI migration tests passed; local security advisor reported no issues. These SQL tests use disposable PostgreSQL with platform stubs; real Auth/PostgREST/Storage integration is validated separately.

## Boundary

- Formal, active Supabase account only. Every user RPC checks auth.uid == expected owner, auth.users.is_anonymous = false, no merged-source tombstone, JWT exp, and auth.sessions(id = JWT session_id, user_id = uid, not_after null or future).
- Browser roles have no new table DML or bucket object access. Public RPC wrappers are SECURITY INVOKER; privileged implementations are private with explicit per-role EXECUTE grants and fixed search_path.
- The backend forwards the user JWT for stage/read/download-authorize/delete. Only the trusted backend service_role may finalize verified bytes and operate cleanup jobs. HTTP responses omit the upload object. A user holding their JWT can also call stage directly and read their own stage_token/object_key/session_id; these fields fence concurrent attempts and do not grant Storage or finalize permission. Integrity depends on the service-only byte verification and finalize path, not secrecy from the owner.
- PDF only, 1..67108864 bytes. Filename: 1..200 Unicode codepoints, nonblank, no control characters or / or backslash, case-insensitive .pdf suffix; exact name retained until deletion, never used in object key. MIME fixed application/pdf. SHA256 lowercase 64 hex. Client-declared hash does not imply verification.
- Global material_id UUID; record_id UUID. Fixed private bucket `application-materials`, object key `pdf/<material_id>.pdf`, never reused or overwritten. No dependence on owner or document revision.

## JSON artifact row

All keys always present. Timestamps are ISO timestamptz strings; UUIDs lowercase. Rows are returned only after owner + opportunity + application-event checks.

```
{
  material_id, record_id, application_event_id, opportunity_id, owner_id,
  status: "staged" | "ready" | "deleted",
  filename: string | null,
  mime_type: "application/pdf" | null,
  byte_length: integer | null,
  sha256: string | null,
  created_at: timestamp,
  expires_at: timestamp,
  archived_at: timestamp | null,
  recorded_at: timestamp | null,
  deleted_at: timestamp | null,
  confirmation_source: "user_reported"
}
```

`sha256` is null while staged; `filename/mime_type/byte_length` describe the declared upload then. Ready sha256 is backend-verified. All filename/MIME/size/hash fields become null on deletion. `expires_at` is the original 24-hour staging deadline, not a ready-file retention deadline. Archived and recorded times originate from atomic finalization. A deleted staged row has null archived_at/recorded_at and never appears in the recorded-material list.

## User-JWT RPCs

1. `stage_application_material(p_expected_owner text, p_material_id uuid, p_record_id uuid, p_application_event_id uuid, p_opportunity_id text, p_filename text, p_byte_length bigint, p_sha256 text) -> {artifact, upload, replayed}`.
   - Locks the owner and reserves the row before Storage upload. Verifies the existing application event belongs to this exact owner/target. Frozen request includes all supplied scalar values except expected owner (ownership may transfer for ready records).
   - Same immutable metadata + same IDs: exact retry. A staged retry creates a fresh stage_token and stores the calling JWT session_id/exp. Earlier upload authorization is fenced off. Existing ready record returns upload:null without re-upload/finalize. A deleted/expired ID is permanently unavailable; choose a new material UUID.
   - `upload = {bucket, object_key, stage_token, session_id, authorized_until}` for staged records only. authorized_until = min(JWT exp, original stage expires_at).
   - Anonymous/absent/revoked/expired sessions fail. A fresh valid JWT may reauthorize an otherwise unexpired staged request without changing IDs/content or extending the 24-hour deadline.
2. `get_application_material(p_expected_owner text, p_record_id uuid, p_application_event_id uuid, p_opportunity_id text) -> {artifact: row|null}`.
   - Returns staged/ready/deleted; missing ID returns null. An existing ID under another owner/target returns null, never its metadata. Original event must still belong to caller.
3. `list_application_materials(p_expected_owner text, p_application_event_id uuid, p_opportunity_id text, p_before_recorded_at timestamptz DEFAULT NULL, p_before_record_id uuid DEFAULT NULL, p_limit integer DEFAULT 20) -> {items: row[], next_cursor: {recorded_at,record_id}|null}`.
   - Only finalized associations (ready or subsequently deleted). Descending recorded_at,record_id; limit+1; limit 1..50. Both cursor values or neither. Empty success is distinct from RPC error.
4. `authorize_application_material_download(p_expected_owner text, p_record_id uuid, p_application_event_id uuid, p_opportunity_id text) -> {artifact, bucket, object_key}`.
   - Ready only. Proxy download reauthorizes immediately before responding; no public or long-lived signed link.
5. `delete_application_material(p_expected_owner text, p_record_id uuid, p_material_id uuid, p_application_event_id uuid, p_opportunity_id text) -> {artifact, replayed}`.
   - Both record_id and material_id are required. If neither ID is reserved, cancellation creates a redacted deleted artifact and permanent cleanup tombstone before the first stage; a late upload cannot revive it. Existing IDs must match owner/event/opportunity and each other exactly; conflicts roll back without disclosing another row. Owner -> material lock order matches stage. Unassociated cancellation rows stay out of lists. Ready/staged -> deleted, immediately redacts filename/hash/size/auth-capability fields and enqueues cleanup atomically. Repeated deletion returns the tombstone. Original application event is unchanged. This does not claim physical bytes have already been deleted.

## Service-role-only RPCs

6. `finalize_application_material(p_verified_owner uuid, p_verified_session_id uuid, p_material_id uuid, p_stage_token uuid, p_verified_byte_length bigint, p_verified_sha256 text) -> {artifact,replayed}`.
   - Check current owner exists and is formal/active; stage token, session identity, stored JWT expiration, auth.sessions existence/not_after, staging deadline, and exact verified-vs-declared size/hash. Backend must validate/download/hash actual immutable object bytes before calling.
   - Atomically sets ready/verified metadata and inserts application_material_records. Does not update application_events/interactions/status/reminders. Same valid ready replay is read-only; mismatched payload conflicts. Revoked/expired stage cannot finalize.
7. `claim_material_cleanup(p_limit integer DEFAULT 20) -> {jobs:[{material_id,bucket,object_key,claim_token,claimed_until}]}`.
   - Service only, limit 1..100. First atomically revokes an equally bounded batch of expired staged rows. Claims due private outbox rows with SKIP LOCKED and five-minute claim lease.
   - Only irreversibly revoked object keys enter outbox. Those keys can never become ready/reused, so a stale worker cannot delete any newly archived artifact. Replacing a lease token fences acknowledgments, not the external Storage operation; fixed revoked keys make that late operation safe.
8. `ack_material_cleanup(p_material_id uuid, p_claim_token uuid, p_success boolean) -> {accepted:boolean}`.
   - Old token or expired/replaced claim returns false; current success records last successful removal and schedules another check in 24h, failure retries after five minutes. Never removes the opaque-key tombstone: a paused backend upload may arrive after a prior successful removal.
   - Outbox keeps only opaque material UUID/object key, times/counters/lease token. No owner, filename, hash, document, or event identity.

## Lifecycle and atomicity

- Account merge uses existing sorted owner advisory locks: ready artifacts and their associations move owner in one transaction; IDs/keys/hash/bytes/times remain fixed. Unfinished staged artifacts are revoked+redacted+queued, not resumed under the new owner. Their minimal tombstones move to the destination for honest lookup. Existing event-ID collisions still abort the whole merge.
- Account deletion removes all artifact/association metadata while reliably retaining only opaque cleanup tombstones. Deleting an old source account cannot delete transferred target artifacts. Material UUID reuse also checks cleanup tombstones after metadata erasure.
- Expiry/revoke changes must commit even when upload/finalize is refused: use a returned deleted artifact or explicit typed error result after performing the transaction, never an exception that rolls back its cleanup enqueue. A worker also catches abandoned stages.
- Storage writes/removals exclusively use the Storage API. SQL only owns lifecycle and cleanup intent. No SQL DELETE of storage.objects.
- New tables use owner RLS but no direct browser SELECT/DML; reads go through bounded session-aware RPCs so a signed-out JWT cannot bypass the auth.sessions check. Private outbox also has RLS and no browser grants.

## Stable errors

- SQLSTATE 42501, message `material_identity_unavailable`: owner/session/anonymous/merged mismatch.
- SQLSTATE 22023, `invalid_application_material`: invalid fields/cursor/limits.
- SQLSTATE 23505, `application_material_conflict`: same reserved ID, different immutable request or verified payload.
- SQLSTATE P0002, `application_material_not_found`: missing scoped event/required row.
- Deleted/expired stages return `{artifact, upload:null, replayed:true}` from stage; finalize returns `{artifact,replayed:true}` with status deleted, never ready. Backend maps these to a deleted/expired response, not upload success.
- Download of staged/deleted returns SQLSTATE 55000, `application_material_unavailable`.

## Official references checked 2026-09-25

- https://supabase.com/docs/guides/storage/schema/design — objects must be changed through Storage API; SQL only stores metadata.
- https://supabase.com/docs/guides/storage/management/delete-objects — remove deletes actual bytes; raw metadata deletion does not.
- https://supabase.com/docs/guides/auth/sessions — JWT session_id identifies auth.sessions; sign-out removes the session row; JWT alone can remain valid.
- https://github.com/supabase/auth/blob/master/migrations/20221114143122_add_session_not_after_column.up.sql — nullable not_after is the session expiry timestamp.
- https://github.com/supabase/auth/blob/master/internal/models/sessions.go — id/user_id/not_after fields and NotAfter validity check.
- Changelog retrieved to /private/tmp/ofe-b33-supabase-changelog.md. No applicable storage/auth schema breaking change in the scanned recent entries; management-log endpoint and extension version pinning changes do not affect this migration.

## Stage credential visibility

The owner can call the authenticated stage RPC directly and see their own attempt nonce, session ID and opaque object key. These are concurrency identifiers, not Storage or service-role authorization. The HTTP archive API never forwards them. Only service-role finalization, after verifying actual Storage bytes, can mark the archive ready; the owner cannot read or write this bucket directly.
