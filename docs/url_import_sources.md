# URL import source evidence

A URL import records the page that was actually fetched. It does not turn a user-submitted opportunity into an official or verified listing.

## Fetch and parse

- `parse_url` and `parse_url_llm` retain the final response URL and the time the response body finished loading. They use the existing bounded, redirect-aware `_safe_fetch` path.
- The submitted and final addresses must identify the same page. The shared `same_source_page` check permits a trailing slash and an HTTP-to-HTTPS upgrade; a different path, host, query, or HTTPS downgrade rejects the import. The response contains no opportunity draft in that case.
- Capture keeps the requested address, actual final address, and record address separately. This lets later refreshes update the correct page without relabeling another page's content.
- Supplying `html=` directly to `parse_url` only parses fields. Without a fetched response, it does not create source evidence or a successful capture receipt.
- LLM extraction can fill its existing allowlisted opportunity fields. It cannot replace the source URL, source passages, or capture receipt.

## Capture outcomes

A successfully fetched page can return `captured`, `empty`, or `unsupported`. `empty` means the supported page was read and had no relevant condition passages; it does not mean the applicant faces no conditions. `unsupported` leaves conditions unverified. Fetch failure returns no new draft. A redirect to another page is rejected before its content is presented as an import.

The capture receipt and passages are retained through normalization. Existing public identity and source gates still apply: a manually imported page remains unverified unless separate source validation establishes its identity. This change does not grant it official-source status.

## Request accounting

`_safe_fetch` accepts optional `before_request(url)` and `on_response(response)` hooks. Each redirect hop passes the existing URL and DNS checks, then calls `before_request` before its actual GET. Returning false or raising stops the fetch. `on_response` observes every response, including redirects and 429 responses, before status handling. Responses are closed on all paths. The hooks add no retry or extra request.

## Save and reopen

The API only returns a review draft. The browser's existing Save action stores the complete opportunity object with its current identity owner; reopening reads that serialized object. A separate manual-import path normalizes and writes records to a JSON file. Tests cover both paths separately:

- Actual API responses from controlled HTTP pages are saved with the browser's production storage functions and read again after resetting the JavaScript modules. Capture status, source text, URLs, and dates remain unchanged; account changes retain existing owner protections.
- A controlled API response goes through the actual normalizer, manual importer, temporary JSON file, loader, and public detail endpoint. The public record remains unverified.

These checks use synthetic pages, no external network or model, and temporary storage. They do not establish extraction accuracy on live websites. Existing display-description and LLM-excerpt limits remain outside this source-attribution change.
