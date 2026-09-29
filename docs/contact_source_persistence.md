# Contact source persistence

B55 keeps source observations intact when a collector refreshes a directory record. The capture receipt describes this attempt; each source's `checked_at` remains the time its page was actually observed. General `metadata.last_verified` is not a substitute.

## Merge rules

`carry_forward_contact_instruction_sources(existing, incoming)` changes only the incoming source bundle and capture receipt. It detaches copied dictionaries from the old record.

| Incoming observation | Result |
| --- | --- |
| No capture or source supplied | Keep the old bound source and its original observation date. |
| `captured` with a valid complete bundle | Replace the previous bundle. |
| `empty` with an explicit empty source list | Clear the previous bundle and retain an empty receipt. |
| Ordinary `failed` or `unsupported` | Keep the old bound source; retain the failed attempt separately. Ignore any source list attached to this failed attempt. |
| Explicit identity, URL, redirect, source withdrawal, or ambiguous program scope | Clear the previous source and retain the receipt. |
| Invalid receipt, binding, date, or source shape | Do not adopt the new source. Keep only a valid previous state that still belongs to this record. |
| Older observation, or captured observation at the same time as an empty/withdrawn state | Do not restore the previous source. |

A B54 snapshot without a receipt remains compatible only when the capture key is absent. A malformed explicit receipt cannot use this compatibility path. An empty/withdrawn state requires a strictly later successful observation to acquire a source again; same-time legacy replay is rejected too.

Sources are carried only across a stable record ID, record URL set, source type, faculty identity and organization. Faculty snapshots must also bind their own identity to the record. Changed records do not inherit an old person's or project's requirements.

The existing source limits remain: at most 8 snapshots, 160 sections per snapshot, 1,000 characters per heading and 4,000 per section body. Receipt and source dates must be timezone-aware and not in the future. Successful receipt and source dates must agree. The implementation does not truncate source text to fit these limits.

## Actual collection and storage

- Faculty profile HTML uses the fetcher's requested URL, final URL and observation time. Missing fetch metadata produces a failed receipt; it does not create a new observation time for copied HTML.
- Rendered HTML records the final URL before closing the browser. Ordinary fetches use the existing `ucb_common.fetch_soup` observation metadata.
- Same-resource trailing slashes and HTTP-to-HTTPS upgrades are permitted. Changed host, resource path or query is a binding failure. The stored source keeps the actual final URL; the record binding retains the requested URL.
- The faculty adapter retains the historical five-item enrichment tuple. Receipt data travels separately through normalization.
- Generic normalization preserves explicit empty source lists and capture receipts.
- UIUC, UCB and faculty-graph upserts share the carry rule. Campus/SRO adapters call the same helper before replacing metadata.
- Public projection consumes the retained sources through existing eligibility/contact rules and removes raw source and capture metadata from public metadata.

## Different-ID duplicate records

The existing dedup policy still chooses a canonical record. For a duplicate with an incoming source bundle, a source update is allowed only when there is exactly one matching canonical entity: same normalized URL, exact title, nonempty organization, source type and faculty name. The canonical ID and other fields remain unchanged. No bundle means this new source-identity scan is skipped.

Shared URLs or similar titles alone cannot transfer requirements. The historical global same-URL/different-title drop policy is unchanged. Campus configuration can identify separate programs explicitly; broader entity deduplication remains separate work. A record missing its organization is not treated as a proven same-entity match merely to preserve a newer source.

## Coverage limits and next work

- Complete faculty records can still skip profile enrichment when the existing research/email/title fetch rules do not request it. `always` enables enrichment; it does not force every complete profile to be fetched. This batch adds no school-wide requests or scheduler. Such profiles may still have no receipt.
- The existing time budget can stop before later profiles. Unvisited profiles are not reported as freshly checked.
- The source bundle is replaced atomically by a successful capture. Independent per-page refresh, page-specific withdrawal and combining separate profile/lab/application-page observations are not implemented.
- A later task should define a bounded refresh queue for missing or expired receipts, including independent page identity, last success, last attempt, retry reason and a school-level request budget.
- Synthetic offline tests prove state transfer and local storage behavior. They do not prove current website coverage or successful live collection. No corpus was applied during B55 validation.

## Verification

`tests/test_contact_source_persistence.py` covers 90 cases: preservation, withdrawals, same-time replay, malformed receipts/metadata, source binding, capture outcomes, actual render metadata, three faculty upsert styles and a campus dedup update through temporary JSON and public projection. The related six-file regression set passed 559 tests.
