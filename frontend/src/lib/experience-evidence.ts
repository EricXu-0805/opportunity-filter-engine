import type { ExperienceEntry } from './types';
import { MAX_RESUME_TEXT_CHARACTERS, resumeTextCharacters } from './resume-input';

export const MAX_EXPERIENCE_ENTRIES = 100;
export const MAX_EXPERIENCE_ENTRY_CHARACTERS = 6_000;
export const MAX_EXPERIENCE_TOTAL_CHARACTERS = 60_000;
const DIGEST = /^[a-f0-9]{64}$/;
const STATUSES = new Set(['candidate', 'confirmed', 'rejected', 'withdrawn']);

export type ExperienceValidationCode =
  | 'invalid_entries' | 'invalid_entry' | 'duplicate_id' | 'too_many_entries'
  | 'text_limit' | 'quote_limit' | 'resume_too_long' | 'source_digest_unavailable' | 'invalid_unicode';

export class ExperienceEvidenceError extends Error {
  constructor(public readonly code: ExperienceValidationCode) {
    super(code);
    this.name = 'ExperienceEvidenceError';
  }
}

export type ExperienceValidation =
  | { ok: true; value: ExperienceEntry[] }
  | { ok: false; code: ExperienceValidationCode };

function record(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === 'object' && !Array.isArray(value);
}

function exactKeys(value: Record<string, unknown>, keys: readonly string[]): boolean {
  const present = Object.keys(value);
  return present.length === keys.length && present.every((key) => keys.includes(key));
}

/** TextEncoder replaces lone UTF-16 surrogates. Reject them before hashing so
 *  the source digest always describes the exact text accepted by Python UTF-8. */
function wellFormedUnicode(value: string): boolean {
  for (const character of value) {
    const point = character.codePointAt(0)!;
    if (point >= 0xd800 && point <= 0xdfff) return false;
  }
  return true;
}

function nonemptyText(value: unknown, limit: number): value is string {
  return typeof value === 'string' && value.trim().length > 0
    && resumeTextCharacters(value) <= limit;
}

/** Structural validation only. A well-formed historical source can be stale;
 *  source eligibility is checked separately against the exact current resume. */
export function validateExperienceEntries(value: unknown): ExperienceValidation {
  if (value === undefined) return { ok: true, value: [] };
  if (!Array.isArray(value)) return { ok: false, code: 'invalid_entries' };
  if (value.length > MAX_EXPERIENCE_ENTRIES) return { ok: false, code: 'too_many_entries' };
  let textTotal = 0;
  let quoteTotal = 0;
  const ids = new Set<string>();
  for (const entry of value) {
    if (!record(entry)
      || !exactKeys(entry, ['id', 'revision', 'status', 'text', 'source'])
      || !nonemptyText(entry.id, 80)
      || !Number.isSafeInteger(entry.revision) || (entry.revision as number) < 1
      || typeof entry.status !== 'string' || !STATUSES.has(entry.status)
      || !nonemptyText(entry.text, MAX_EXPERIENCE_ENTRY_CHARACTERS)
      || !record(entry.source)) return { ok: false, code: 'invalid_entry' };
    if (!wellFormedUnicode(entry.id) || !wellFormedUnicode(entry.text)) return { ok: false, code: 'invalid_unicode' };
    if (ids.has(entry.id)) return { ok: false, code: 'duplicate_id' };
    ids.add(entry.id);
    textTotal += resumeTextCharacters(entry.text);
    const source = entry.source;
    if (source.kind === 'resume') {
      if (!exactKeys(source, ['kind', 'signature', 'quote', 'start', 'end'])
        || typeof source.signature !== 'string' || !DIGEST.test(source.signature)
        || !nonemptyText(source.quote, MAX_EXPERIENCE_ENTRY_CHARACTERS)
        || !Number.isSafeInteger(source.start) || (source.start as number) < 0
        || !Number.isSafeInteger(source.end) || (source.end as number) <= (source.start as number)
        || (source.end as number) > MAX_RESUME_TEXT_CHARACTERS
        || (source.end as number) - (source.start as number) !== resumeTextCharacters(source.quote)) {
        return { ok: false, code: 'invalid_entry' };
      }
      if (!wellFormedUnicode(source.quote)) return { ok: false, code: 'invalid_unicode' };
      quoteTotal += resumeTextCharacters(source.quote);
    } else if (source.kind !== 'manual' || !exactKeys(source, ['kind'])) {
      return { ok: false, code: 'invalid_entry' };
    }
  }
  if (textTotal > MAX_EXPERIENCE_TOTAL_CHARACTERS) return { ok: false, code: 'text_limit' };
  if (quoteTotal > MAX_EXPERIENCE_TOTAL_CHARACTERS) return { ok: false, code: 'quote_limit' };
  return { ok: true, value: value as ExperienceEntry[] };
}

function requireEntries(value: unknown): ExperienceEntry[] {
  const checked = validateExperienceEntries(value);
  if (!checked.ok) throw new ExperienceEvidenceError(checked.code);
  return checked.value;
}

/** SHA-256 of the complete, unnormalized UTF-8 resume. No weak-hash fallback. */
export async function sourceDigest(rawText: string): Promise<string> {
  if (!wellFormedUnicode(rawText)) throw new ExperienceEvidenceError('invalid_unicode');
  if (resumeTextCharacters(rawText) > MAX_RESUME_TEXT_CHARACTERS) {
    throw new ExperienceEvidenceError('resume_too_long');
  }
  try {
    const digest = await globalThis.crypto.subtle.digest('SHA-256', new TextEncoder().encode(rawText));
    return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, '0')).join('');
  } catch {
    throw new ExperienceEvidenceError('source_digest_unavailable');
  }
}

export interface ExperienceSourceContext {
  rawText: string;
  /** Must be computed from rawText with sourceDigest by the calling session. */
  expectedDigest: string;
}

export function isActiveExperience(entry: ExperienceEntry, context: ExperienceSourceContext): boolean {
  if (!validateExperienceEntries([entry]).ok || entry.status !== 'confirmed') return false;
  if (entry.source.kind === 'manual') return true;
  const { source } = entry;
  return wellFormedUnicode(context.rawText) && DIGEST.test(context.expectedDigest)
    && source.signature === context.expectedDigest
    && resumeTextCharacters(context.rawText) <= MAX_RESUME_TEXT_CHARACTERS
    && Array.from(context.rawText).slice(source.start, source.end).join('') === source.quote;
}

/** This fail-closed read is for generation eligibility, never for saving or
 *  repairing persisted data. Persistence must report an invalid structure. */
export function activeExperienceEntries(value: unknown, context: ExperienceSourceContext): ExperienceEntry[] {
  const checked = validateExperienceEntries(value);
  return checked.ok ? checked.value.filter((entry) => isActiveExperience(entry, context)) : [];
}

/** Local paragraph/line proposals retain exact codepoint offsets. Oversized
 *  paragraphs are split at whitespace where possible, without losing text.
 *  An over-limit result is rejected as a whole, never silently truncated. */
export async function createResumeCandidates(rawText: string): Promise<ExperienceEntry[]> {
  const signature = await sourceDigest(rawText);
  const points = Array.from(rawText);
  const spans: Array<[number, number]> = [];
  const hasParagraphBreak = /\r?\n[\t ]*\r?\n/.test(rawText);
  const boundary = hasParagraphBreak ? /\r?\n[\t ]*\r?\n/g : /\r?\n/g;
  let start = 0;
  let utf16Start = 0;
  for (const match of rawText.matchAll(boundary)) {
    const end = start + resumeTextCharacters(rawText.slice(utf16Start, match.index));
    spans.push([start, end]);
    start = end + resumeTextCharacters(match[0]);
    utf16Start = match.index + match[0].length;
  }
  spans.push([start, points.length]);
  const entries: ExperienceEntry[] = [];
  for (const [from, to] of spans) {
    let left = from;
    let right = to;
    while (left < right && /\s/u.test(points[left])) left += 1;
    while (right > left && /\s/u.test(points[right - 1])) right -= 1;
    while (left < right) {
      let end = Math.min(left + MAX_EXPERIENCE_ENTRY_CHARACTERS, right);
      if (end < right) {
        let split = end;
        while (split > left && !/\s/u.test(points[split - 1])) split -= 1;
        if (split > left) end = split;
      }
      if (entries.length >= MAX_EXPERIENCE_ENTRIES) throw new ExperienceEvidenceError('too_many_entries');
      const quote = points.slice(left, end).join('');
      entries.push({
        id: `r:${signature}:${left}:${end}`, revision: 1, status: 'candidate', text: quote,
        source: { kind: 'resume', signature, quote, start: left, end },
      });
      left = end;
      while (left < right && /\s/u.test(points[left])) left += 1;
    }
  }
  return requireEntries(entries);
}

export function createManualCandidate(text: string, id: string = globalThis.crypto.randomUUID()): ExperienceEntry {
  return requireEntries([{ id, revision: 1, status: 'candidate', text, source: { kind: 'manual' } }])[0];
}

/** A replacement keeps the old evidence visible, but revokes its eligibility. */
export function withdrawResumeEntries(value: unknown): ExperienceEntry[] {
  return requireEntries(requireEntries(value).map((entry) => entry.source.kind === 'resume' && entry.status !== 'withdrawn'
    ? { ...entry, status: 'withdrawn', revision: entry.revision + 1 } : entry));
}

/** Deleting the resume removes its quoted material. Explicit manual entries stay. */
export function removeResumeEntries(value: unknown): ExperienceEntry[] {
  return requireEntries(value).filter((entry) => entry.source.kind === 'manual');
}
