import { captureTextareaSelection } from './email-revision';
import { Buffer } from 'node:buffer';
import { describe, expect, it } from 'vitest';
import { applyEmailReplacement, captureValidSelection, type EmailTextSelection } from './email-revision';

function selection(body: string, start: number, end: number): EmailTextSelection {
  const captured = captureValidSelection(body, start, end);
  expect(captured).not.toBeNull();
  return captured!;
}

function expectOutsideUnchanged(body: string, captured: EmailTextSelection, replacement: string, result: string) {
  const prefix = result.slice(0, captured.start_utf16);
  const suffix = result.slice(captured.start_utf16 + replacement.length);
  expect(prefix).toBe(body.slice(0, captured.start_utf16));
  expect(suffix).toBe(body.slice(captured.end_utf16));
  expect(Buffer.from(prefix, 'utf8')).toEqual(Buffer.from(body.slice(0, captured.start_utf16), 'utf8'));
  expect(Buffer.from(suffix, 'utf8')).toEqual(Buffer.from(body.slice(captured.end_utf16), 'utf8'));
}

describe('captureValidSelection', () => {
  it('uses textarea UTF-16 offsets across Chinese, emoji and line endings without normalization', () => {
    const body = '前😀\r\n本人贡献\n尾';
    expect(captureValidSelection(body, 1, 9)).toEqual({ start_utf16: 1, end_utf16: 9, text: '😀\r\n本人贡献' });
    expect(captureValidSelection(body, 0, body.length)).toEqual({ start_utf16: 0, end_utf16: body.length, text: body });
  });

  it.each([
    [0, 0], [2, 2], [3, 1], [-1, 2], [0, 5], [5, 6],
    [0.5, 2], [0, 2.5], [NaN, 2], [0, NaN], [Infinity, 2], [0, Infinity],
    ['0', 2], [0, '2'], [null, 2], [0, undefined],
  ])('rejects empty, reversed, out-of-range or noninteger offsets (%s, %s)', (start, end) => {
    expect(captureValidSelection('abcd', start as number, end as number)).toBeNull();
  });

  it.each([[1, 2], [2, 3], [0, 2], [2, 4]])('rejects an endpoint inside an emoji surrogate pair (%i, %i)', (start, end) => {
    expect(captureValidSelection('A😀B', start, end)).toBeNull();
  });

  it('accepts an intact emoji, whitespace-only selection and exact decomposed characters', () => {
    expect(captureValidSelection('A😀B', 1, 3)?.text).toBe('😀');
    expect(captureValidSelection('A \t\nB', 1, 4)?.text).toBe(' \t\n');
    expect(captureValidSelection('e\u0301', 0, 2)?.text).toBe('e\u0301');
    expect(captureValidSelection('', 0, 0)).toBeNull();
  });
});

describe('applyEmailReplacement', () => {
  it('changes only the selected second occurrence, not the identical first occurrence', () => {
    const body = 'Same claim.\nSame claim.\nSame claim.';
    const captured = selection(body, 12, 23);
    const result = applyEmailReplacement(body, captured, 'My specific contribution.');
    expect(result).toBe('Same claim.\nMy specific contribution.\nSame claim.');
    expectOutsideUnchanged(body, captured, 'My specific contribution.', result!);
  });

  it.each(['', '新贡献😀\n第二行', '  unchanged spacing\r\n', 'e\u0301', '$& $` $\''])('preserves text outside a multiline range with replacement %j', replacement => {
    const prefix = '  前😀\r\n', selected = '原文\n第二行', suffix = '\r\n尾e\u0301  ';
    const body = prefix + selected + suffix;
    const captured = selection(body, prefix.length, prefix.length + selected.length);
    const result = applyEmailReplacement(body, captured, replacement);
    expect(result).toBe(prefix + replacement + suffix);
    expectOutsideUnchanged(body, captured, replacement, result!);
    expect(captured.text).toBe(selected);
  });

  it('allows replacing the entire body with an empty string', () => {
    const body = '邮件😀\r\n';
    expect(applyEmailReplacement(body, selection(body, 0, body.length), '')).toBe('');
  });

  it('rejects stale or tampered selection text and never relocates it', () => {
    const body = 'First claim.\nSecond claim.';
    const captured = selection(body, 13, body.length);
    expect(applyEmailReplacement('prefix ' + body, captured, 'new')).toBeNull();
    expect(applyEmailReplacement(body, { ...captured, text: 'second claim.' }, 'new')).toBeNull();
    expect(applyEmailReplacement(body, { ...captured, start_utf16: 0 }, 'new')).toBeNull();
  });

  it('revalidates caller-provided endpoints before applying a proposal', () => {
    expect(applyEmailReplacement('A😀B', { start_utf16: 1, end_utf16: 2, text: '\ud83d' }, 'x')).toBeNull();
    expect(applyEmailReplacement('abc', { start_utf16: 1, end_utf16: 1, text: '' }, 'x')).toBeNull();
    expect(applyEmailReplacement('abc', null as unknown as EmailTextSelection, 'x')).toBeNull();
    expect(applyEmailReplacement('abc', { start_utf16: 0, end_utf16: 1, text: 'a' }, null as unknown as string)).toBeNull();
  });

  it('preserves exact prefix and suffix bytes for every scalar-boundary range in a mixed Unicode body', () => {
    const body = '中😀\r\ne\u0301尾🧪';
    const boundaries = [0];
    for (const point of body) boundaries.push(boundaries[boundaries.length - 1] + point.length);
    for (let from = 0; from < boundaries.length - 1; from++) {
      for (let to = from + 1; to < boundaries.length; to++) {
        const captured = selection(body, boundaries[from], boundaries[to]);
        for (const replacement of ['', '替换😀\n']) {
          const result = applyEmailReplacement(body, captured, replacement);
          expect(result).not.toBeNull();
          expectOutsideUnchanged(body, captured, replacement, result!);
        }
      }
    }
  });
});


describe('textarea line-ending offsets', () => {
  it.each(['\r\n', '\r', '\n'])('maps %j line endings without changing raw prefixes or suffixes', newline => {
    const body = ['😀 same', '中文same', '', 'same', 'suffix'].join(newline);
    const value = body.replace(/\r\n?/g, '\n'); const start = value.lastIndexOf('same');
    const range = captureTextareaSelection(body, value, start, start + 4)!;
    expect(range).toEqual({ start_utf16: body.lastIndexOf('same'), end_utf16: body.lastIndexOf('same') + 4, text: 'same' });
    expect(applyEmailReplacement(body, range, 'new')).toBe(body.slice(0, range.start_utf16) + 'new' + body.slice(range.end_utf16));
  });
  it('preserves selected raw CRLF while replacing a multiline excerpt', () => {
    const body = 'Dear,\r\n😀first\rsecond\r\nLast'; const value = body.replace(/\r\n?/g, '\n');
    const range = captureTextareaSelection(body, value, value.indexOf('😀'), value.indexOf('Last'))!;
    expect(range.text).toBe('😀first\rsecond\r\n');
    expect(applyEmailReplacement(body, range, 'new\n')).toBe('Dear,\r\nnew\nLast');
  });
  it('rejects unrelated API values and half-surrogate boundaries', () => {
    expect(captureTextareaSelection('a\r\nb', 'different', 0, 2)).toBeNull();
    expect(captureTextareaSelection('😀\r\nb', '😀\nb', 0, 1)).toBeNull();
  });
});
