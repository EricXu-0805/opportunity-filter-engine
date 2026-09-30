# Program collector source capture

B55 covers the shared `campus_graph` collector and UIUC SRO's existing deep-detail requests. All validation used controlled offline HTML and temporary JSON files. It did not refresh the live corpus.

## Saved source and transport

- The shared capture helper retains complete selected paragraphs/lists or supported Drupal field values, together with their actual headings, final page URL, requested record URL and timezone-aware observation time.
- `contact_instruction_capture` records `captured`, `empty`, `unsupported` or `failed`. `contact_instruction_sources: []` is explicit successful empty evidence, not a missing observation.
- An absent or invalid transport observation is a failure. A different final page is `redirect_mismatch`; same-page fragments/trailing slashes and HTTP-to-HTTPS upgrades follow `same_source_page`.
- Login/error pages do not verify a record. Unsupported DOM, missing Drupal labels or source-budget overflow remain unsupported; no partial excerpt becomes an authoritative source.
- These receipts describe capture, not semantic correctness. The condition and contact readers retain their separate finite scope, freshness and interpretation checks.

## Campus graph

`fetch_and_normalize_with_evidence(school, deep=True)` consumes already fetched pages; it adds no HTTP requests. Source capture runs independently of the existing 400-character display excerpt.

- Only the actual fetched program/discovery URL supplies that record's source.
- Different configured program keys sharing an equivalent page remain separate records. Their full page is `unsupported / ambiguous_program_scope`, including fragment variants. No per-anchor scope extraction is implemented.
- `metadata.collector_school` retains the collector's ownership even for external opportunities whose public `school` is null. `shared_program_page` is a configuration fact, not a successful observation.
- A failed discovered page is still omitted from publishable discoveries. Its receipt travels through the explicit `condition_capture_updates` evidence list into `merge_into_processed(..., condition_capture_updates=...)`. Each update includes `school`, `collector_source`, `requested_url` and `capture`, and can only affect the exact matching existing ownership and URL. Successful content never uses this URL-wide channel.
- Ordinary failure preserves a valid previous snapshot with its previous `checked_at`; explicit redirect/scope revocation removes it. Same-ID merges use the common source carry helper. The separate Berkeley collector only receives this merge-preservation call; its independent capture path is not added in B55.

The old list-only `fetch_and_normalize` wrapper remains compatible. Callers using that wrapper cannot forward omitted-discovery failure updates; the scheduled refresh uses the evidence API. Legacy external records with no `collector_school` and `school: null` are not guessed into a school by failure updates. A later exact same-ID refresh can establish the ownership.

## SRO

`fetch_and_normalize_with_evidence(deep=False)` returns `(records, evidence)`; `fetch_and_normalize` remains a list wrapper. Deep mode uses the existing detail request schedule.

- Drupal eligibility, deadline and application-link fields use the real `.field__label` / `.field-label` and complete value. Existing page headings are retained as context. Labels are never generated from schema field names.
- A successful recognized empty listing table ends pagination. Missing tables, partially unparsed rows, failed requests and page-cap exhaustion do not prove a complete list. Valid rows from a partial page can still be retained.
- Failed or unsupported detail checks do not set `deep_scraped`. A new record without a successful detail check has `metadata.last_verified: null`. Successful checks use the capture's actual observation time.
- On a quick/failed/unsupported refresh, prior detail fields and their verification time survive the list refresh. The current capture receipt still records the failure. A new list title can change without declaring old detail facts freshly verified.
- `normalization_failed` counts records that could not be normalized instead of hiding them behind a nonempty result list.

Evidence invariants:

- `list_pages_attempted = list_pages_loaded + list_pages_failed`; loaded means a fully parsed list page, including a real empty terminal table.
- `detail_pages_attempted = detail_pages_loaded + detail_pages_failed`; loaded means HTTP success, including a later redirect/DOM rejection.
- Sum of the four `condition_capture_counts` equals detail attempts for SRO and actual page attempts for normally completed campus crawls.
- `condition_capture_complete` is true only with at least one attempt and no failed/unsupported capture. Zero quick-mode attempts are not a capture success or a capture failure.

## Boundaries

- The existing normalized display/heuristic fields still have their previous excerpt and inference rules. The new retained source is independent of `eligibility_text_raw[:500]`, citizenship keyword windows and display excerpts; these old values are not upgraded to website-stated facts.
- The adapters support bounded HTML/Drupal structures, not arbitrary PDFs, JavaScript widgets, shared-program section segmentation or semantic identity inference. Unsupported content is reported rather than silently truncated.
- No new detail requests were added to RSS, URAP, the independent Berkeley crawler or the URL importer. The URL importer's final-URL handling remains a separate follow-up.
- Current-corpus backfill and successful live-site verification remain outstanding. Passing offline cases does not mean stored opportunities already have checked sources.
