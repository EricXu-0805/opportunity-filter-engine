/**
 * Word-level diff for the tailor modal's side-by-side view (R71-G).
 *
 * Classic LCS over whitespace-preserving tokens, producing an ordered
 * segment list the modal renders as:
 *   - original side: equal + removed words (added words filtered out)
 *   - tailored side: equal + added words   (removed words filtered out)
 *
 * Bullets are capped at 500 chars upstream (~80 tokens), so the O(m*n)
 * table is trivially small — no need for a windowed/Myers diff.
 */

export type DiffSegmentType = 'equal' | 'added' | 'removed';

export interface DiffSegment {
  value: string;
  type: DiffSegmentType;
}

// Split into word + whitespace runs so spacing rebuilds exactly when the
// segments are concatenated back together.
function tokenize(text: string): string[] {
  return text.match(/\S+|\s+/g) ?? [];
}

// Case-insensitive token equality so a capitalization-only change ("built"
// vs "Built") reads as equal rather than a spurious add+remove pair.
function eq(a: string, b: string): boolean {
  return a.toLowerCase() === b.toLowerCase();
}

/**
 * Diff `original` → `tailored` at word granularity.
 *
 * Returns segments in tailored reading order: equal and added words land
 * where they appear in `tailored`, removed words land where they were in
 * `original` relative to the surrounding equal anchors.
 */
export function diffWords(original: string, tailored: string): DiffSegment[] {
  const a = tokenize(original);
  const b = tokenize(tailored);
  const m = a.length;
  const n = b.length;

  // dp[i][j] = LCS length of a[i:] and b[j:].
  const dp: number[][] = Array.from({ length: m + 1 }, () =>
    new Array<number>(n + 1).fill(0),
  );
  for (let i = m - 1; i >= 0; i--) {
    for (let j = n - 1; j >= 0; j--) {
      dp[i][j] = eq(a[i], b[j])
        ? dp[i + 1][j + 1] + 1
        : Math.max(dp[i + 1][j], dp[i][j + 1]);
    }
  }

  const out: DiffSegment[] = [];
  let i = 0;
  let j = 0;
  while (i < m && j < n) {
    if (eq(a[i], b[j])) {
      out.push({ value: b[j], type: 'equal' });
      i++;
      j++;
    } else if (dp[i + 1][j] >= dp[i][j + 1]) {
      out.push({ value: a[i], type: 'removed' });
      i++;
    } else {
      out.push({ value: b[j], type: 'added' });
      j++;
    }
  }
  while (i < m) out.push({ value: a[i++], type: 'removed' });
  while (j < n) out.push({ value: b[j++], type: 'added' });
  return out;
}

// Whitespace-only tokens carry no semantic change, so the renderer styles
// them as plain regardless of diff type (avoids a highlighted blank space).
export function isWhitespace(value: string): boolean {
  return /^\s+$/.test(value);
}
