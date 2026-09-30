# Private target resolution

B61 adds an authenticated read-only view of a saved private import. It does not turn the import into a public listing, verify its qualifications, or enable a writer. The owner can read the full accepted original and obtain a compact identity for Tracker display. There are no importer fetches, provider calls, outbound emails, corpus writes, new migrations or database/service operations in this implementation.

## Current consumer paths

These existing paths still require a public, release-visible corpus target:

| Consumer | Resolution and checks |
|---|---|
| `/cold-email`, `/cold-email/stream`, `/cold-email/variants`, `/cold-email/refine`, `/cold-email/validate` | `_email_target` → canonical ID lookup → `prepare_writing_snapshot` → public actionability, contact policy and target-version checks. |
| `/tailor`, `/tailor/renovate`, `/tailor/bullet` | Canonical ID lookup → actionability → detached anonymous projection and current writing version. |
| `/tailor/full-target/suggestions`, `/tailor/full-target/selection-plan` | Canonical ID lookup → actionability → public target context v4 and full snapshot/signature comparison. These routes currently do not take an authenticated private owner scope. |
| `/resume/full-target/export` | Renders the supplied validated document projection; it performs no target lookup or provider call. Export is not target verification. |

The new resolver does not change these writing paths. In B61, `/private-imports/[id]` reads the owner-bound private target and displays `ContactHistory` and `ApplicationHistory`. An active target can use `ApplicationRecordForm` to let the user confirm a record of a past application. Tracker resolves private IDs separately from public targets and retains a deleted-target placeholder linked to history. These are personal history records; they do not send an email, submit an application, or generate materials. Private email and résumé generation still require explicit consumer integration and private input-scope decisions.

## Resolver and endpoint

`resolve_private_import_target(target_id, *, authorization, expected_owner_id, expected_target_version=None)`:

1. Validates the `private-import:` UUID and owner shape. A malformed namespace is not a public lookup candidate.
2. Validates the optional `pit1:` version syntax.
3. Uses the B60 service to verify the current GoTrue user and then calls the owner/session-checked read RPC with the user's bearer token.
4. Refuses deletion tombstones and a mismatched expected version before projection.
5. Returns a detached `PrivateResolvedTarget` with private-only fields. No public lookup/fallback or normalizer is called.

The private service retains its database check for non-anonymous accounts, live sessions and merged/deleted owners. B61 tests mock that RPC boundary; they do not repeat native SQL validation after the B60 database incident.

`GET /api/private-import-targets/{id}/resolved?expected_owner_id=UUID` returns the current read view. Add `expected_target_version=pit1:...` to require a previously observed version. Duplicate/unknown query keys are rejected.

Response shape:

```json
{
  "version": 1,
  "target_scope": "private_import",
  "verification": "unverified",
  "id": "private-import:<uuid>",
  "owner_id": "<uuid>",
  "revision": 1,
  "target_version": "pit1:<sha256>",
  "detail": {
    "title": "Imported title",
    "organization": null,
    "description_raw": "Complete accepted original text",
    "source_url": null,
    "url": null,
    "location": null,
    "deadline": null,
    "posted_date": null,
    "import_source": null
  },
  "tracker": {
    "id": "private-import:<uuid>",
    "title": "Imported title",
    "organization": null,
    "source_url": null,
    "url": null,
    "target_scope": "private_import",
    "verification": "unverified",
    "target_version": "pit1:<sha256>"
  },
  "capabilities": {"read": true, "tracker_identity": true, "writes": false}
}
```

Organization/location/deadline/posted date are the imported string or null, including an existing empty string. They are not normalized or verified facts. `description_raw` retains the whole accepted original; it must be rendered as text, never HTML. `import_source` uses the conservative B59 labels and stays null when the stored source had no labels. These labels record scope, not official provenance or model authorization.

The compact Tracker identity contains no original text, recipient, requirements, inferred skills, public target truth or publication/lab evidence. `tracker_identity:true` permits identity display only; it is not a send/submission/event-write receipt. `writes:false` means this resolved view grants no material-generation or outbound-writing capability. It does not prohibit separately authorized personal history records, and it does not replace the B60 owner-authorized CRUD contract or the existing history APIs.

## Source and version boundaries

Only the private field allowlist is copied. Raw `extra_fields` cannot populate eligibility, availability, contact instructions, recipient email, professor rank, research/lab context, capabilities or target truth. Cached receipt decorations are also ignored and recomputed from the validated stored row. Model skill suggestions remain in the separate raw owner record, outside this projection.

Links pass the existing browser-safe HTTP(S) URL check and importer syntax gate. Credentials, unsupported schemes, literal IPs, localhost/private host suffixes, raw controls/backslashes, malformed percent-encoded hostnames, IPvFuture bracket hosts and embedded-email links are withheld as null in this view. Valid encoded paths and Unicode hostnames are retained; these finite checks do not implement every browser URL edge case. This performs no DNS lookup or HTTP request, does not prove a URL is official/public/current, and does not modify the raw stored URL. A hostname that resolves to a private IP is not ruled out by a syntax-only gate; the view never fetches that URL. A source link is never treated as a contact address.

The `pit1:` version is the B60 owner/ID/revision binding. A changed private record must be fetched again; an account transfer changes its owner binding. Resolution establishes what was read at that request, not a lock on future changes. Any later writer must re-resolve its expected owner/version at its own action boundary.

All responses are private/no-store. Errors contain fixed codes without source text:

- Invalid ID/owner/version/query: 422 `private_target_invalid_request`.
- Missing or another owner's ID: 404 `private_target_not_found`.
- Deleted target: 409 `private_target_deleted`.
- Valid but outdated version: 409 `private_target_changed`.
- Auth, owner-change, upstream failures and malformed storage receipts retain the B60 error codes.

## Verification and next integration

The controlled route suite covers full later paragraphs and Unicode/comparison characters; extra metadata trying to invent authority; unsafe links; owner/auth/session refusal; tombstones; stale versions before projection; invalid private IDs without public fallback; and detached response data. The tests replace GoTrue/PostgREST with MockTransport and explicitly forbid public projection, corpus lookup and model execution in the complete-source path. An actual synthetic FastAPI response is saved for the frontend parser contract check.

Remaining work is explicit:

- A reviewed public/private union in each writer and its restore/version checks.
- A separate private target context that never borrows public evidence authority. This read projection must not be passed wholesale to an existing generator.
- Recipient confirmation and private email policy, plus targeted résumé input scope and provenance.
- Private email sending and generated-material integration, including version-bound restoration of new writing drafts. B61 already displays existing contact/application history and supports user-confirmed past-application records; it does not add private material generation or sending.
- Hosted deployment and real account acceptance. B60 native SQL remains partially verified; B61 performs no native database test or migration.

The pending full-source model-input approval is unchanged. This endpoint returns the original to its owner; it does not send that text to a provider.
