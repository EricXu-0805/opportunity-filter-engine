/** Offsets use the UTF-16 units exposed by textarea selectionStart/selectionEnd. */
export type EmailTextSelection = {
  start_utf16: number;
  end_utf16: number;
  text: string;
};

function splitsSurrogatePair(body: string, offset: number): boolean {
  if (offset === 0 || offset === body.length) return false;
  const before = body.charCodeAt(offset - 1);
  const after = body.charCodeAt(offset);
  return before >= 0xd800 && before <= 0xdbff && after >= 0xdc00 && after <= 0xdfff;
}

/** Capture exact text without trimming, normalizing line endings, or searching
 * for a matching occurrence elsewhere in the body. A caret is not a selection. */
export function captureValidSelection(body: string, start: number, end: number): EmailTextSelection | null {
  if (typeof body !== 'string' || !Number.isInteger(start) || !Number.isInteger(end)
    || start < 0 || end > body.length || start >= end
    || splitsSurrogatePair(body, start) || splitsSurrogatePair(body, end)) return null;
  return { start_utf16: start, end_utf16: end, text: body.slice(start, end) };
}

/** The caller must also verify the proposal's whole-body hash and source/owner
 * receipts. This checks only the captured range and preserves its surroundings. */
export function applyEmailReplacement(baseBody: string, selection: EmailTextSelection, replacement: string): string | null {
  if (!selection || typeof selection !== 'object' || typeof selection.text !== 'string'
    || typeof replacement !== 'string') return null;
  const current = captureValidSelection(baseBody, selection.start_utf16, selection.end_utf16);
  if (!current || current.text !== selection.text) return null;
  return baseBody.slice(0, current.start_utf16) + replacement + baseBody.slice(current.end_utf16);
}

/** Textareas expose an LF-normalized API value. Translate those offsets back
 * to the exact original text so CRLF drafts do not drift or silently edit all. */
export function captureTextareaSelection(body: string, value: string, start: number, end: number): EmailTextSelection | null {
  if (!captureValidSelection(value, start, end)) return null;
  let normalized = '';
  const boundaries = [0];
  for (let at = 0; at < body.length;) {
    const unit = body[at++];
    if (unit === '\r') {
      if (body[at] === '\n') at++;
      normalized += '\n';
    } else normalized += unit;
    boundaries.push(at);
  }
  if (normalized !== value) return null;
  return captureValidSelection(body, boundaries[start], boundaries[end]);
}
