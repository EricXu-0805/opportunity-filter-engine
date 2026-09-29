# URL import source evidence

A URL import records the page that was actually fetched. It does not turn a user-submitted opportunity into an official or verified listing.

## Fetch and parse

- `parse_url` and `parse_url_llm` retain the final response URL and the time the response body finished loading. They use the existing bounded, redirect-aware `_safe_fetch` path.
- The submitted and final addresses must identify the same page. The shared `same_source_page` check permits a trailing slash and an HTTP-to-HTTPS upgrade; a different path, host, query, or HTTPS downgrade rejects the import. The response contains no opportunity draft in that case.
- Capture keeps the requested address, actual final address, and record address separately. This lets later refreshes update the correct page without relabeling another page's content.
- Supplying `html=` directly to `parse_url` only parses fields. Without a fetched response, it does not create source evidence or a successful capture receipt.
- LLM extraction can suggest opportunity fields. It cannot replace the source URL, source passages, capture receipt, or source description. Generated titles carry an inference marker so they cannot supply source qualifications.

## Capture outcomes

A successfully fetched page can return `captured`, `empty`, or `unsupported`. `empty` means the supported page was read and had no relevant condition passages; it does not mean the applicant faces no conditions. `unsupported` leaves conditions unverified. Fetch failure returns no new draft. A redirect to another page is rejected before its content is presented as an import.

The capture receipt and passages are retained through normalization. Existing public identity and source gates still apply: a manually imported page remains unverified unless separate source validation establishes its identity. This change does not grant it official-source status.

## Request accounting

`_safe_fetch` accepts optional `before_request(url)` and `on_response(response)` hooks. Each redirect hop passes the existing URL and DNS checks, then calls `before_request` before its actual GET. Returning false or raising stops the fetch. `on_response` observes every response, including redirects and 429 responses, before status handling. Responses are closed on all paths. The hooks add no retry or extra request.

## Save and reopen

The API only returns a review draft. The browser's existing Save action stores the complete opportunity object with its current identity owner; reopening reads that serialized object. A separate manual-import path normalizes and writes records to a JSON file. Tests cover both paths separately:

- Actual API responses from controlled HTTP pages are saved with the browser's production storage functions and read again after resetting the JavaScript modules. Capture status, source text, URLs, and dates remain unchanged; account changes retain existing owner protections.
- A controlled API response goes through the actual normalizer, manual importer, temporary JSON file, loader, and public detail endpoint. The public record remains unverified.

These checks use synthetic pages, no external network or model, and temporary storage. They do not establish extraction accuracy on live websites. Those B56 checks established attribution. B58 separately changes local source preservation and display; its model excerpt remains unchanged.

## Model suggestions and original text (B57)

`description_raw` retains the existing source excerpt for URL imports and the complete submitted text for paste imports. A model summary is stored separately as `extra_fields.suggested_description`; model skill arrays are combined into `extra_fields.suggested_skills`, with an inference marker. All model-enriched drafts remain `needs_manual_review=true`. These suggestion fields are not canonical eligibility or positive matching signals.

The import page and saved custom cards show suggestions with a review notice. Older browser records with `extra_fields.skills_required` or `skills_preferred` retain their strings and stored payload; the display reads them as suggestions rather than remapping them to canonical qualifications. No storage migration deletes or rewrites user records. Save failure leaves the current source and suggestions available.

URL V1 text is still an OpenGraph/meta description or a body excerpt of up to 2,000 characters. This batch preserves that excerpt; it does not make it a complete webpage copy. The separate condition-source capture keeps its existing passage contract. The model still receives the existing bounded excerpt, so a successful import does not establish that the model read every sentence of a long pasted source. The complete pasted source now remains available to the user and downstream source-based processing.


## Complete local source and explicit model scope (B58)

New URL imports now save all readable text in the fetched static HTML body as `description_raw`, with `description_source="page_text"`. The page metadata summary is separate in `page_meta_summary`. Paragraphs, lists, table rows, and late source conditions are retained. This supersedes B57's URL storage excerpt, not its model-input boundary. Old browser records are not migrated or relabeled.

The reader refuses empty, metadata-only, recognized access/JavaScript walls, and unsupported non-HTML responses. The route returns HTTP 422 with `import_source_unreadable` and a fixed safe reason/message; no source text or submitted URL appears in these errors. A reserved `too_large` reader exception maps to HTTP 413, but no new model-input budget is enabled in this batch. The existing 5 MiB fetch cap still uses the previous fetch-failure response.

**The model still receives only the previous excerpt.** `_legacy_model_hints` preserves the previous metadata/body hint independently of the newly saved full body. The body excerpt remains 4,000 characters; the fallback description hint remains 2,000 characters. This prevents the full local description from expanding the existing model payload. Paste imports likewise keep their complete submitted source while the model receives the previous 4,000-character prefix.

A successful model enrichment stamps `ai_input_scope="source_excerpt"`. Missing configuration and failed/invalid model responses do not claim successful reading. The scope marker is assigned by the parser; model output cannot set it. Import and saved custom cards can expand the source and distinguish current page text, pasted text, historical excerpts, and unknown legacy scope. Storage failure keeps the preview available. Duplicate URLs keep the existing saved record under the existing behavior; this does not upgrade old sources.

Full-source model input and its serialized-input budget remain pending explicit authorization of the receiving model providers. Automatic approval review refused that separate code change; the proposed tests are retained as pending evidence, not passing implementation tests. No real model call or provider configuration was performed. Static source preservation also does not read linked pages, PDFs, images, or JavaScript-rendered content, and does not establish model understanding or requirement accuracy.

The temporary normalized-file roundtrip additionally verifies that complete `description_raw` and a late source skill survive normalization, saving, and loading. That normalized schema does not yet persist the browser import's `description_source` / `ai_input_scope` fields. This is separate remaining work; browser Save/reopen retains the original extra fields.
