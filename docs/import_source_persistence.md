# Persisted import-source labels

B59 preserves local source labels through `normalize(raw)` → `save_opportunities()` → the JSON loader. The manual JSON importer also recognizes the raw `url_parser` / `text_parser` object produced by Copy JSON, normalizes it, and retains its complete `description_raw`. It no longer sends that object through the older flat-format builder, which only understands `description`.

## Stored contract

The new optional field is `metadata.import_source`:

```json
{
  "version": 1,
  "description_source": "page_text",
  "ai_input_scope": "source_excerpt",
  "llm_enriched": true
}
```

- `description_source`: `page_text`, `page_excerpt`, `pasted_text`, or `unknown`.
- `ai_input_scope`: `source_excerpt` or `unknown`. This implementation does not accept `full_source`. The parser stamps it only when a short source reached the model whole; the browser import shows that, and a persisted copy records `unknown` because the stored record cannot show what the model received.
- `llm_enriched`: literal boolean. `true` records successful enrichment, not accurate interpretation. `false` means successful enrichment was not recorded; it does not prove that no provider was called.
- `version`: integer `1`; boolean `true` is invalid.

`url_parser` may carry `page_text` or historical `page_excerpt`. `text_parser` may carry `pasted_text`. A source-type conflict, empty/invalid body, unsupported label, or unsupported version cannot establish a readable source. AI excerpt scope additionally requires the literal successful-enrichment flag and explicit `source_excerpt` marker. Missing or unsupported scope remains unknown even when local source text is available.

Old records without labels remain unlabeled. Text length, source name, suggestions, review flags and URL alone do not imply complete reading. Malformed stored labels are replaced with the bounded unknown form in memory. The loader does not migrate or rewrite the source JSON file.

These are producer-recorded scope labels, not cryptographic receipts or claims of official status, manual review, an active opening, qualification accuracy, or student eligibility. They never turn model skill/summary suggestions into canonical requirements.

## Literal source text and display safety

For a recognized imported source, `description_raw` is a literal text field. The loader validates its label before deciding to preserve it; it must not run the legacy HTML-removal regex over comparisons such as `GPA < 3.0 ... scores > 80`. It also preserves literal markup examples from pasted text rather than executing or interpreting them.

`title`, `description_clean` and unlabeled/invalid legacy raw descriptions retain their previous cleaning behavior. Canonical detail `DescriptionSection` and custom-import `ImportSourceText` render descriptions as React text nodes. The server-rendered JSON-LD already escapes `<`. This change does not add HTML rendering, loosen public-source trust gates, or skip existing public privacy projection.

The standardized display description remains a cleaned, bounded convenience field; it is not the saved full source. Public projections may still redact content under their existing privacy rules. Source labels must not be used to bypass those rules.

## Manual JSON formats

- A full normalized record with an eligibility object uses the existing path.
- A known raw import with `description_raw` must have string title/source URL/URL fields, valid nonempty Unicode body text, and an `extra_fields` object. Invalid raw shape raises a fixed error without echoing content.
- The older flat `description` format and CSV path are unchanged.
- A pasted import keeps empty URL fields. No URL is invented and `validate_opportunity` continues to report its missing URL. Loading source text is not authorization to publish it.

## Validation and remaining limits

Tests use controlled local API responses, a stubbed model, blocked external connections, and temporary JSON files. They cover Copy JSON → normalization → save → actual loader, local source equality, valid excerpt preservation, old/malformed/conflicting labels, model-suggestion isolation, and comparison/literal-markup preservation. Model messages are checked to retain the existing excerpt boundary. The loader's ranking preparation is stubbed in these focused tests; no full-corpus matcher or live provider validation is claimed.

The reader's existing static-HTML/access-wall and merged-table-cell limitations remain. Neither the local source label nor these tests establish that AI received the complete source. Full-source model input remains pending explicit authorization of the receiving provider.
