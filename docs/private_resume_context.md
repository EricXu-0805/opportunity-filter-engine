# Private résumé source

`GET /api/private-import-targets/{id}/resume-context` gives the owner of a saved private import the complete import as the target of a full résumé draft. It is a read: it writes nothing, calls no model and performs no public corpus lookup. The snapshot is always unverified; it is not evidence that the opening exists, that the student is eligible, or that contact is permitted.

## Request

- `id` is a `private-import:<uuid>` identifier.
- Query keys: `expected_owner_id` (required, UUID) and `expected_target_version` (optional, `pit1:<sha256>`). Duplicate or unknown keys are refused.
- A `Bearer` token is required. The route uses `resolve_private_import_target` (see `docs/private_target_resolution.md`): the token is verified with Supabase Auth, its user must equal `expected_owner_id`, and the read RPC returns only that user's row. The owner never comes from anything but the verified token and the query that must match it.

## Response

```json
{
  "version": 1,
  "target_scope": "private_import",
  "verification": "unverified",
  "context": {
    "context_version": 5,
    "opportunity_id": "private-import:<uuid>",
    "title": "Imported title",
    "organization": "",
    "source_url": "",
    "description": "Complete accepted original text",
    "requirements": [],
    "private_source": {
      "version": 1,
      "purpose": "resume",
      "target_scope": "private_import",
      "verification": "unverified",
      "owner_id": "<uuid>",
      "revision": 1,
      "source_version": "pit1:<sha256>",
      "import_source": null
    }
  },
  "target_signature": "v1:sha256:<sha256>"
}
```

- `title`, `organization` and `description` are the stored import's values; a missing organization is `""`. `description` is the complete stored `description_raw` (at most 5 × 1024 × 1024 codepoints), with line breaks and Unicode kept; it is never replaced by an import summary.
- `source_url` is the stored source link, else the stored link, after the syntax gate of `docs/private_target_resolution.md`; a withheld link is `""`.
- `requirements` is always `[]`. Skills, papers or lab details guessed at import time never become requirements.
- `import_source` is the conservative import label (or `null`), copied as stored. It records how the text was imported, not that it is official.
- `source_version` is the `pit1:` binding of id, owner and revision. A changed import has a new revision and so a new version and signature.
- `target_signature` is `v1:sha256:` of the canonical JSON of `context` (sorted keys, compact, non-ASCII kept), the same signature a résumé draft stores as `base.target_signature`.

The route checks its own output before answering: the exact key sets above, the storage length limits, no NUL or unpaired surrogate, a non-blank title and description, import labels that follow the scope rules of `src/import_source.py`, and a `source_version` that matches the id, owner and revision. A row that fails is refused with 422 `private_target_invalid_request`, never repaired; the limits are the import storage limits, so a row saved through the import routes fits.

Responses are `private, no-store`. Errors carry only a fixed code:

| Case | Status | Code |
|---|---|---|
| No or invalid bearer, guest session | 401 | `private_target_auth_required` |
| Token user is not `expected_owner_id` | 409 | `private_target_owner_changed` |
| Unknown id, or another owner's id | 404 | `private_target_not_found` |
| Deleted import | 409 | `private_target_deleted` |
| `expected_target_version` is not the current version | 409 | `private_target_changed` |
| Malformed id, owner, version or query | 422 | `private_target_invalid_request` |

With the `resume_renovate` release switch off, the release gate answers 404 `{"detail": "Not found"}` before any auth or storage call, as it does for the public résumé routes.

## Boundaries

Version 5 is a separate private target. Public résumé contexts (versions 1-4) are built from the anonymous public projection; a private import is never turned into one. The public full-target AI routes do not accept a version 5 draft. A matching version or signature shows which import was read at that request, not that its content is true or current at a later action; a writer must read again at its own action boundary.
