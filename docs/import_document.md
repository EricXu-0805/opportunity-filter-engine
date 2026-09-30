# Importing the fetched HTML body

`src.collectors.import_document.extract_import_document(html, content_type=None)` is a local, deterministic reader. It makes no HTTP or model calls.

- `text` contains readable text from the complete fetched body. Paragraphs, headings, list items and table rows stay separate; table cells use tabs, including empty leading/trailing cells. Paragraph breaks within one cell are normalized to spaces; merged-cell visual layout is not reconstructed. Source formatting whitespace is normalized. Ordered-list numbers follow `start`, `reversed` and item `value` attributes. Each list computes its sequence once, so sibling numbering does not require repeated scans. Invalid numbering attributes retain the existing bullet fallback for that item and the remaining sequence; nested lists have independent numbering.
- Sibling `main`/`article` sections, headers, sidebars and footers remain included. A late deadline or application requirement is not dropped because of its position.
- `title` and `meta_summary` are separate fields. Metadata never substitutes for an absent body. `source_kind` is `fetched_html`.
- Scripts, styles, comments, head metadata, templates, SVG/canvas and embedded frame/object content are excluded. Explicit HTML `hidden`, `aria-hidden=true`, and inline `display:none`/`visibility:hidden` content is excluded. Static `details` text is retained.
- The helper has no text excerpt or extra length cap. The existing fetcher bounds HTTP response bytes. Any caller limit must reject the complete input explicitly, not send or save a silent prefix.

## Refused sources

`ImportDocumentError.reason` is one of these fixed codes. Exception messages never contain source text or URLs.

| Reason | Meaning |
| --- | --- |
| `invalid_html` | Invalid input type, invalid Unicode, or parsing failure |
| `unsupported_content_type` | Explicit non-HTML MIME type, known binary signature, or null byte |
| `empty_page` | No readable body or useful metadata |
| `metadata_only` | Title/summary exists, but fetched readable body is absent |
| `access_page` | Recognized access denial, sign-in wall or challenge page |
| `javascript_required` | Recognized script-only, JavaScript-required or loading shell without readable source |
| `too_large` | Reserved for an explicit source limit; the helper currently sets none |

Only `text/html` and `application/xhtml+xml` are accepted when a nonempty MIME type is supplied. A missing MIME type permits HTML or text fragments, while known binary signatures are rejected. This is not a general binary format detector.

A normal paragraph saying “log in to apply”, or a sign-in/CAPTCHA form beside readable opportunity content, is allowed. Real source sentences remain available when a separate login sentence shares their paragraph. Footer/header navigation links do not qualify as independent source for bypassing a login wall, but remain in successful source output. JavaScript skill requirements are not treated as a browser activation instruction. Access detection uses limited HTML and text patterns; it is not a guarantee that every site's gate is recognized.

## Scope and remaining work

- The result covers this response's static HTML. Linked pages, PDFs, image text, frames and content created by JavaScript were not read. External CSS, computed visibility, and interactive widgets are not rendered.
- Remaining access-wall cases include very short conditions, login instructions carrying a deadline in the same sentence, and source prose inside a password form: these may be explicitly refused. They are not evidence that the fetched source was read successfully.
- The reader preserves readable words and structure, not byte-identical HTML or visual layout. Keeping navigation/footer text may add noise; it avoids silently discarding source conditions.
- Extracted text is source material, not verified requirements. This module does not promote a mention to a required skill or validate eligibility.
- B58 source saving and complete-model-input work are separate. The reader's tests do not establish that a model received the full source. Full-model-input changes were stopped by automatic approval review and require explicit user authorization of the receiving provider; the integration must keep its existing model excerpt boundary until then.

Validation is offline: full-body/tail preservation, lists/tables, hidden content, metadata-only and access/JavaScript shells, MIME/binary failures, and ordinary application sign-in instructions. No live fetch, model request, service startup, or corpus write is part of these tests.
