# Saved import updates, coordination and recovery

Reimporting a source creates a candidate. It does not replace a saved import. Updating requires an explicit review of the complete old entry and the new candidate.

## Write API

All four mutation functions return promises:

```ts
addCustomImport(opportunity, token)
updateCustomImport(opportunity, expected, token)
// { ok: true, entry: CustomImport } | { ok: false, reason }

removeCustomImport(id, token)
resetCustomImports(expectedRaw, token)
// { ok: true } | { ok: false, reason }
```

The caller captures the owner token when the action starts. Update review also freezes complete copies of the saved entry and candidate. Confirmation passes those same values; it cannot silently adopt a newer entry or owner. Each function copies mutable inputs before waiting for a lock. Callers await the result, retain the candidate on failure, and check that their UI action and identity are still current before displaying completion.

The update comparison covers all persisted JSON fields, including nested metadata and unknown retained fields. Object key order is irrelevant; array order and values remain significant. A matching ID or timestamp alone cannot authorize replacement.

| Failure reason | Meaning |
| --- | --- |
| `owner_changed` | The original account or storage generation is no longer valid. |
| `changed` | The complete reviewed entry or recovery bytes changed; recovery also returns this when the data is no longer damaged. |
| `missing` | The reviewed update target was deleted. |
| `identity_mismatch` | Candidate and saved entry identify different sources. |
| `storage_failed` | Storage, serialization, readback or lock-request execution failed. |
| `storage_damaged` | Stored JSON or entries are invalid. Ordinary writes are blocked. |
| `coordination_unavailable` | The browser cannot provide the required Web Locks coordination. |
| `lock_timeout` | The request could not acquire the shared lock within ten seconds. |

## Shared transaction boundary

Add, update, remove and explicit recovery use `PRIVATE_STORAGE_LOCK`, the same exclusive Web Lock as identity transitions and namespace cleanup. Reads, comparison, mutation and verification happen synchronously inside the acquired lock. There is no network request or awaited identity work in that callback. Two cooperating tabs cannot read the same old list and each replace the other's addition.

A queued action rechecks its original owner after acquiring the lock. The timeout applies only while waiting. Timeout aborts the pending lock request, and an expired callback still refuses mutation if an implementation later invokes it. Once the lock is acquired, the pending timer is cleared. Missing or failed coordination does not fall back to an unlocked write.

Success also requires verified storage contents. A silent write failure, synchronous subscriber replacement or deletion cannot report a successful save. Failure never rolls back newer data.

This is cooperative coordination, not a localStorage transaction primitive. Older application builds, developer tools, extensions or direct storage writes that do not use the shared lock remain outside the guarantee. The implementation does not claim protection against those writers or persistence after a browser clears site data. See the [W3C Web Locks specification](https://www.w3.org/TR/web-locks/) for named-lock scope, release and request cancellation.

## Source identity and retained fields

- Update keeps the saved ID, original `imported_at`, unknown top-level entry fields and other imports. It replaces `opportunity` with the reviewed candidate and sets `updated_at`.
- Source type must match. URL-backed entries must retain the same source address; conflicting populated secondary addresses are also rejected. Comparisons trim whitespace but do not infer redirect equivalence.
- Legacy records can omit `url` or `source_url`. Missing aliases count as empty; an alias can be supplied if it identifies the same page.
- Two URL-less entries use the existing title-and-organization identity rule. That rule does not prove the pastes came from the same document.
- A URL entry and a URL-less paste remain distinct, even with matching titles and organizations. Different URLs are never merged solely by title.

## Storage health and explicit recovery

`useCustomImportStorageState()` and owner-bound `readCustomImportStorageState(token)` return one of:

```ts
{ status: 'ready', entries: CustomImport[] }
{ status: 'damaged', entries: CustomImport[] }
{ status: 'unavailable', entries: [], reason }
```

Damaged storage can still display its valid neighboring entries. Invalid JSON, invalid entry shapes and duplicate IDs block ordinary mutation. Display never repairs, removes or rewrites bytes. The older `useCustomImports`/`readCustomImports` list-only helpers remain available for display; callers needing recovery or write availability use the health contract.

Recovery is explicit:

1. `captureCustomImportRecovery(token)` returns `{ok: true, raw}` only for a readable damaged value. Normal status reads do not expose raw damaged content. The caller keeps the same token with the snapshot and verifies it before exporting a backup.
2. An export preserves the raw value inside a JSON backup envelope. A download request is not proof the browser saved a backup file.
3. After a separate confirmation, `resetCustomImports(expectedRaw, token)` acquires the shared lock, checks the exact raw bytes and original owner, and requires the data to remain damaged.
4. Successful reset writes an empty list and verifies it. Changed, repaired, deleted, unreadable or differently owned storage cannot be cleared by an old confirmation.

No automatic migration or cleanup runs. Optional omissions and unknown fields in otherwise valid legacy entries remain compatible. A reset is destructive only to the explicitly reviewed damaged imports value; it does not change profiles or other storage keys.

## Evidence and remaining scope

The B60 tests exercise two independent module contexts sharing a queued lock, held-lock barriers, simultaneous adds and updates, deletion without resurrection, identity changes, generation changes, unavailable locks, timeout without late writes, and recovery conflicts. A separate local Chromium harness loads the actual production modules in two pages of one browser context and repeats the core cases with native Web Locks. Its documents and scripts are fulfilled from local memory; no service, source website, model or corpus is involved.

Complete local source preservation and the model's existing excerpt scope are unchanged. These storage checks establish neither the accuracy of imported content nor full-source AI processing.
