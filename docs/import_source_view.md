# Imported source text in the interface

The import preview and custom favorites show the saved source text as plain text. A four-line preview has a **Read full source / Collapse source** control. Expanding changes only the display; the complete string is retained in the saved import. Ordinary catalog cards keep their existing description and action gates.

## Source and AI input range

- `description_source=page_text`: readable text extracted from the current HTML page. This does not include linked pages or guarantee JavaScript-loaded content.
- `description_source=pasted_text`: pasted source text.
- `description_source=page_excerpt`: historical page excerpt.
- Missing/unrecognized source metadata: generic saved description; no completeness claim.
- The full-input note requires `ai_input_scope=full_source`, `description_source=page_text` or `pasted_text`, and nonempty source text. It means the input was supplied in full, not that AI interpreted it correctly.
- `ai_input_scope=source_excerpt` with a recognized, nonempty source displays that only an excerpt was processed.
- Missing, malformed, or contradictory scope stays unknown. Existing saved imports are not upgraded automatically.

AI suggestions remain separate from application requirements. Plain-text source rendering avoids interpreting source Markdown/HTML as interface content. The source link remains available through the existing opportunity link.

## Recoverable errors

The API adapter preserves only the recognized import error code for the new structured failures; it does not display server messages, page contents, or private request URLs. `import_input_too_large` explains that the input cannot be processed completely and offers reducing the selected material (or pasting material from a long page). `import_source_unreadable` offers pasting the source text. Both keep the original form input. Existing unsafe-URL and transport handling remain.

Save failure retains the preview and suggestions. Account ownership, stale-response checks, quota errors, and duplicate handling use the existing storage path. Reimporting an already saved URL does not overwrite its older saved record.

## Verification boundary

Component and API-adapter tests cover both languages, full-tail visibility, scope refusal, input retention/retry, stale owners, and save/reopen. Backend response fixtures used for roundtrip tests are documented in the batch evidence. A controlled `full_source` fixture tests the display contract; it alone does not prove that the current backend sends full source or that model results are accurate. No browser layout or real-provider quality claim follows from these component tests.
