# Professor condition-source refresh

B56 adds a bounded condition-source pass to the real `refresh_all` path, after collector merges have loaded the normalized corpus and before PI enrichment. It does not depend on missing research, email or title fields. Quick mode and national-only refreshes skip this pass; a school shard passes only its active faculty records.

## What is refreshed

- The current professor profile URL, plus previously retained pages whose URL and professor binding pass the shared page-ledger validator. No page links are discovered or followed as new research targets.
- A successful source or explicit successful empty page is due after 14 days by default. This is the refresh target; the downstream 60-day source-use window is a separate policy.
- Missing sources are due. Failed and unsupported attempts wait at least 24 hours before retry. A longer valid HTTP `Retry-After` is saved in that page's failure receipt. Failure does not advance the previous source's `checked_at` or create a successful check.
- Freshness uses each page's checked/empty-success time. The latest attempt on one page does not refresh another page.

The old `_apply_profile_enrich` remains a field-enrichment pass. The new pass updates only condition-source metadata; it does not rewrite research, name, title, email, general `last_verified`, or opportunity availability.

## Bounded requests and evidence

`refresh_faculty_condition_sources(records, *, max_requests=100, max_pages=100, freshness_days=14, retry_hours=24, deadline=None, persist=None, now=None)` mutates the supplied normalized-record references and returns counts.

- `max_requests` counts actual GET starts, including each redirect hop. `max_pages` also bounds zero-HTTP failures such as rejected URLs. Zero budget sends no requests.
- The shared `_safe_fetch` retains its URL/DNS checks, manual redirects, byte limit and timeout. The pass adds per-request budget/deadline hooks. It does not use models, automatic field enrichment, retries, CAP API calls or headless browsers.
- A 429 stops new requests for the pass. Every completed HTML source still needs the real final URL, timezone-aware fetch time, and the expected professor identity. Login pages, wrong identities and different-page redirects cannot become successful sources.
- Deadline checks stop new requests. They do not cancel a request already reading its bounded response; this is not a hard real-time network deadline.
- `now` provides a deterministic scheduling/failure-time reference for offline tests. Successful source time remains the actual transport observation; it is never replaced with the run's start time.

## Fairness and restart

Due pages sort by their last attempted time, then stable record ID and requested page URL. A failed early record therefore moves behind untouched records on the next persisted run. The page ledger is the queue state; there is no separate cursor to drift away from the corpus.

The function calls `persist()` after each changed page. The actual `refresh_all` callback writes the **full corpus**, batching at 20 changed pages or 60 seconds and flushing on normal completion or a handled exception. A hard process kill can lose the latest batch of up to 19 page attempts, which may be repeated. The implementation does not claim a durable per-request journal.

The shared ledger limits remain 32 stored pages and 8 active source blocks. A source-capacity rejection records an unsupported attempt without discarding previous sources. A page with no available ledger slot is reported as `capacity_blocked` and deferred without an HTTP request; existing pages and other professors can still proceed. These blocked pages require source-ledger review. They cannot be fixed merely by running more refresh batches.

The getter may expose one rejected page for scheduling, and the pass may add the current missing profile URL: at most 34 scheduling candidates for one valid record. The two extra candidates contain no usable source evidence and do not enlarge the persisted ledger.

## Reporting

`summary.condition_refresh` is separate from directory health and retirement evidence. It reports the selected input-record count, per-school counts and request/page budgets. No-due pages mean no refresh was needed; malformed or skipped records are never counted fresh.

- `due`: pages eligible for this pass before requests, including capacity-blocked pages.
- `retry_deferred`: pages needing refresh but still waiting for their retry time.
- `backlog`: pages still needing refresh after this pass, including failures, retry waits and capacity blocks.
- `attempted` and `condition_capture_counts`: completed page checks and their stored outcome; a captured response rejected by storage is reported unsupported.
- `updated`: changed **pages**, not unique professor records. `requests` includes redirects.
- `source_limit` / `storage_rejected`: attempted results that could not be accepted under the source contract. `capacity_blocked` describes requests deliberately not started.
- `minimum_runs_at_request_budget`: an optimistic lower bound from the initial backlog and request budget. It excludes failures, redirect overhead, page-budget restrictions, request latency and the actual schedule. It is null when the request budget is zero or page capacity blocks progress.

A 100-request batch is not complete school coverage. For example, 10,000 due pages require at least 100 such batches even if every page succeeds on its first request. The actual backlog and selected scope must guide the operating budget.

## Validation and remaining boundaries

Offline tests exercise real normalization, safe-fetch hooks with controlled HTTP responses, per-page capture, JSON save/reload and subsequent scheduling. They cover complete profiles, absent/old/empty sources, failure cooldown, fair continuation, redirect request accounting, 429, identity failures, private redirects, checkpoint failure, multi-page preservation and capacity blocks.

The local corpus and live sites were not refreshed. This change does not demonstrate that current stored professors already have checked conditions or that the default budget can maintain the full corpus within 14 days. Scheduled deployment, live coverage and a durable incremental checkpoint journal remain separate work.
