# Actual PDF archive HTTP contract (batch 33 candidate)

Only a formal authenticated account may access this API. Every operation verifies the current owner and a live auth session. Existing application events and pending application-v1 inputs stay unchanged. No hosted acceptance is claimed.

## Scope and input

`Scope = { expected_owner_id: UUID, opportunity_id: string, application_event_id: UUID }`. Opportunity IDs use the existing application ledger validation. All requests have Authorization Bearer; no filename/content in a URL. GET query has scope only (and cursor for lists). DELETE takes JSON `{...Scope, material_id: UUID}`.

POST `/api/application-materials` takes multipart with exactly `metadata` (JSON string, <= 8192 UTF-8 bytes) and `file` (original bytes). Metadata exact keys: `version: 1`, scope fields, `material_id: UUID`, `record_id: UUID`, `filename: string`, `mime_type: "application/pdf"`, `byte_length: integer`, `bytes_sha256: lowercase hex64`, `attested: true`. Filename 1–200 Unicode codepoints, no control characters or slash/backslash; PDF name extension required case-insensitively. Raw file is 1–50000000 bytes (50 MB, decimal); metadata MIME is application/pdf. The file part may use application/pdf, application/octet-stream or omit MIME; actual PDF structure is always verified, never inferred from MIME alone. Backend verifies actual size, hash and PDF structure. Password-protected, damaged or excessively complex PDFs (more than 2000 pages or over the isolated parser resource budget) are rejected without changing any bytes. Request envelope allowance is file limit + 65536 bytes; smaller configured deployment limits remain effective.

The browser persists metadata and random material/record IDs BEFORE first POST. It never persists PDF bytes in localStorage. Same uncertain attempt reuses the entire input. Reselecting the same bytes under another local filename keeps the originally frozen filename. A different file cannot replace an unresolved attempt.

## Receipt

All timestamps are UTC ISO strings. IDs and scope must match requested context. No extra untrusted content is rendered as HTML.

```json
{
  "version": 1,
  "owner_id": "uuid",
  "opportunity_id": "target",
  "application_event_id": "uuid",
  "material_id": "uuid",
  "record_id": "uuid",
  "status": "ready",
  "filename": "resume.pdf",
  "mime_type": "application/pdf",
  "byte_length": 1234,
  "bytes_sha256": "64 lowercase hex characters",
  "staged_at": "timestamp",
  "archived_at": "timestamp",
  "linked_at": "timestamp",
  "deleted_at": null,
  "confirmation_source": "user_reported"
}
```

- `staged`: archive/association are NOT confirmed; bytes_sha256/archived_at/linked_at/deleted_at null. Filename/size metadata is only declared, never a verified uploaded file. Lookup may return it after an uncertain save. Reselect original bytes and POST the same IDs again; no GET performs writes.
- `ready`: exact original file is archived and associated; archived_at and linked_at required. POST succeeds only with this receipt. No inference that the institution received the file.
- `deleted`: filename, mime_type, byte_length and bytes_sha256 are null; deleted_at required. Prior archived_at/linked_at remain if originally ready; IDs and times alone remain. Never download or resurrect.

POST returns `{version:1, record: Receipt, replayed: boolean}`. GET `/api/application-materials/{record_id}` with scope returns `{version:1,record:Receipt}` or 404. GET `/api/application-materials` with scope and optional `cursor_linked_at` + `cursor_record_id` returns `{version:1,items:Receipt[],next_cursor:{linked_at:string,record_id:UUID}|null}`. Page is 20; query 21 to prove more. Only ready or linked-then-deleted associations appear in the list. Descending (linked_at,record_id), strictly after supplied cursor.

GET `/api/application-materials/{record_id}/file` with scope returns original PDF bytes, attachment disposition, private no-store, no redirects. Headers: `x-ofe-material-id`, `x-ofe-material-record`, `x-ofe-material-sha256`. Client validates exact byte count/hash and matching IDs before creating a download, and checks owner again after every await. Deletion/authorization are checked again after object retrieval before response.

DELETE `/api/application-materials/{record_id}` with JSON `{...Scope, material_id: UUID}` returns `{version:1,record:Receipt}` where status=deleted. It first revokes logical access and queues physical cleanup; it does NOT claim physical bytes have already been removed. Exact retry returns original tombstone. Browser persists a separate opaque deletion intent before DELETE; an unknown result disables new download until tombstone is verified, survives reload and offers query/retry. It never clears another request's pending state.

## Safe errors

`{detail:{code:string}}`, no private payload/provider error in message. Codes: `material_not_configured` (503), `material_auth_required` (401), `material_owner_mismatch` (409), `material_invalid_request` (422), `material_invalid_pdf` (422), `material_too_large` (413), `material_conflict` (409), `material_not_found` (404), `material_deleted` (410), `material_expired` (409), `material_not_ready` (409), `material_busy` (503), `material_unavailable` (503), `material_invalid_receipt` (502). Network failure never proves no write. Unknown server code remains a generic failure.

## Lifecycle

- Stage precedes Storage write. Object key depends only on a permanent material UUID; upsert is disabled. Existing object retry verifies its actual bytes before finalization. Server-only finalize checks live session/stage authorization and declared/verified bytes match.
- Ready artifacts and associations move together during account merge without changing identifiers, bytes or timestamps. Unfinished stages are revoked; the new owner must explicitly choose the file under a new ID.
- Deletion clears private filename/hash/size metadata, immediately denies new authorized download, and keeps an opaque cleanup tombstone. Account deletion removes all user-facing archive data. Cleanup rechecks revoked object keys to catch uploads that complete exceptionally late; keys never reused.
- Automatic bounded cleanup and failure reporting belong in this package. SQL row deletion alone does not erase a Storage object.

- Cancellation uses the same DELETE endpoint with the frozen material ID, including before staging has completed. Only a verified deleted receipt permits clearing that upload attempt; a missing lookup is not cancellation. The database reserves the revoked ID permanently so a late POST cannot revive it.
- The backend enforces a 110-second overall request deadline, including multipart reception, and bounds simultaneous PDF I/O.

## Deployment verification still required

- The limit is 50 MB because that is the Supabase project-wide Storage upload cap (Pro default); a per-bucket cap alone cannot raise a lower project cap. Raise the project cap before raising this limit. The local verification stack explicitly sets this limit.
- Next 16.3.4 clones fallback rewrite request bodies even when the page Proxy matcher excludes `/api`. `experimental.proxyClientMaxBodySize` must preserve the 50 MB file plus its 65536-byte envelope. Verified through the local production build, not a hosted gateway.
- Independently verify the deployed gateway/body/time limits, peak concurrent memory, worker liveness and cleanup retry monitoring before release. No hosted service was changed for this package.
- Reference checked 2026-09-25: https://nextjs.org/docs/app/api-reference/config/next-config-js/proxyClientMaxBodySize.
