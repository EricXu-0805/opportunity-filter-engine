# Reviewed updates to saved imports

Reimporting a page creates a candidate. It does not replace a saved import. The update action requires an explicit review of the old saved entry and the new candidate.

## Storage API

```ts
updateCustomImport(
  opportunity: ImportedOpportunity,
  expected: CustomImport,
  token: OwnerToken,
):
  | { ok: true; entry: CustomImport }
  | { ok: false; reason:
      'owner_changed' | 'changed' | 'missing' |
      'identity_mismatch' | 'storage_failed' };
```

When opening review, the caller deep-copies the complete old entry and candidate and retains the original owner token. Confirmation uses those same values. It must not silently reread the current entry as a new `expected`, or capture a new token to make a stale review pass.

The comparison covers the entire persisted JSON entry, including source text, labels, suggestions, nested metadata and unknown retained fields. Object key order is irrelevant; array order and values are significant. Matching only `id` or `imported_at` is insufficient.

## Identity and retained data

- Successful replacement retains `id`, `imported_at`, other top-level entry fields and all other list entries. It replaces `opportunity` with the reviewed candidate and sets `updated_at`.
- The source type must remain the same. URL-backed entries must retain the same source address. Different populated secondary URLs are also rejected. Addresses are compared after trimming; this API does not infer redirect equivalence.
- Legacy entries may omit `url` or `source_url`; a missing alias is treated as empty. A populated alias may be supplied when it identifies the same page.
- If neither entry has a URL, title and organization must match. This is the existing limited identity rule for pasted entries, not proof that two pastes came from the same document.
- A URL entry and a URL-less paste are distinct even when their titles and organizations match. Different URLs are never merged solely by title.

## Failure behavior

| Reason | Meaning | Caller response |
| --- | --- | --- |
| `owner_changed` | Original identity is stale or cannot be confirmed. | Keep the candidate with its original workflow; do not transfer it to the new account. |
| `changed` | The saved entry differs from the reviewed snapshot, or its ID is ambiguous. | Require a fresh review before another update. |
| `missing` | The reviewed entry was deleted. | Keep the candidate; do not recreate the deleted entry implicitly. |
| `identity_mismatch` | Candidate and saved entry identify different sources. | Do not replace the saved entry. |
| `storage_failed` | Read, serialization, validation or persistence failed. | Keep the candidate and report that saving failed. |

The layer reads the authoritative owner-scoped storage before writing and compares the same reviewed snapshot again. The final prewrite read supplies the surrounding list, preserving unrelated entries added since the first read. After writing, it checks the same owner and rereads the full target entry. A silent failed write or synchronous storage subscriber that replaces/deletes the target cannot produce a successful result. Failure never triggers a rollback that could overwrite newer data.

## Damaged and legacy storage

`useCustomImports` and `readCustomImports` provide a safe display list: malformed arrays return an empty list, and invalid entries are filtered from a mixed list. These reads do not repair, delete or rewrite the original value.

Mutation uses a separate strict reader. Invalid JSON, a non-array value or any invalid entry blocks add, remove and update. It must not be treated as an empty writable list. Older entries can omit optional fields, and unknown fields remain intact. The existing add/remove APIs retain their `null`/`false` failure contracts; updates return `storage_failed`.

## Concurrency and validation limits

This synchronous API is not an atomic cross-tab transaction. An uncoordinated tab can still write between the final read and `setItem`, or after the final confirmation read. There is no shared lock protocol across every legacy writer. Closing that remaining race requires a coordinated transaction or lock design; passing these tests does not establish it.

The tests use synthetic opportunities and isolated browser storage. They cover full snapshots, source identity, account changes, malformed data, read/write failures, concurrent changes observed at the guarded reads, and postwrite replacement/deletion. They do not call a model, fetch a source, alter the corpus or establish the accuracy of imported suggestions. Complete local source storage does not change the existing AI excerpt boundary.
