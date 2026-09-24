import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { webcrypto } from 'node:crypto';
import type { ExperienceEntry } from './types';
import {
  activeExperienceEntries, createManualCandidate, createResumeCandidates,
  isActiveExperience, removeResumeEntries, sourceDigest,
  validateExperienceEntries, withdrawResumeEntries,
} from './experience-evidence';

beforeEach(() => vi.stubGlobal('crypto', webcrypto));
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });
const manual = (overrides: Partial<ExperienceEntry> = {}): ExperienceEntry => ({
  id: 'exp-1', revision: 1, text: 'Built a robot.', status: 'candidate', source: { kind: 'manual' }, ...overrides,
});

describe('experience evidence input contract', () => {
  it('hashes full exact UTF-8 with SHA-256, including tails and whitespace', async () => {
    expect(await sourceDigest('abc')).toBe('ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad');
    expect(await sourceDigest('abc ')).not.toBe(await sourceDigest('abc'));
    expect(await sourceDigest('x'.repeat(59_999) + 'A')).not.toBe(await sourceDigest('x'.repeat(59_999) + 'B'));
  });
  it('does not substitute a weak hash when WebCrypto is unavailable', async () => {
    vi.stubGlobal('crypto', {});
    await expect(sourceDigest('resume')).rejects.toMatchObject({ code: 'source_digest_unavailable' });
  });
  it.each(['\ud800', '\udfff', 'before\ud800after', '\ud800\ud800', '\udfff\udfff'])('refuses malformed Unicode before hashing or proposing entries: %j', async (raw) => {
    const digest = vi.spyOn(webcrypto.subtle, 'digest');
    await expect(sourceDigest(raw)).rejects.toMatchObject({ code: 'invalid_unicode' });
    await expect(createResumeCandidates(raw)).rejects.toMatchObject({ code: 'invalid_unicode' });
    expect(digest).not.toHaveBeenCalled();
  });
  it('keeps literal replacement characters, valid surrogate pairs and decomposed Unicode exact', async () => {
    await expect(sourceDigest('\ufffd')).resolves.toMatch(/^[a-f0-9]{64}$/);
    expect(await sourceDigest('é')).not.toBe(await sourceDigest('e\u0301'));
    const [entry] = await createResumeCandidates('研究\ud83d\ude00成果');
    expect(entry.source).toMatchObject({ quote: '研究😀成果', start: 0, end: 5 });
  });
  it('rejects unknown entry and source keys rather than dropping them', () => {
    const resume = { kind: 'resume', signature: 'a'.repeat(64), quote: 'actual', start: 0, end: 6 };
    for (const entry of [
      { ...manual(), surprise: 'hidden data' },
      { ...manual(), source: { kind: 'manual', quote: 'old quote' } },
      { ...manual(), source: { ...resume, surprise: 'hidden data' } },
    ]) {
      expect(validateExperienceEntries([entry])).toEqual({ ok: false, code: 'invalid_entry' });
      expect(activeExperienceEntries([entry], { rawText: 'actual', expectedDigest: 'a'.repeat(64) })).toEqual([]);
    }
  });
  it('rejects malformed Unicode in persisted IDs, entry text and source quotes without changing the input', () => {
    for (const invalid of [
      { ...manual(), id: '\ud800' },
      { ...manual(), text: 'before\udfffafter' },
      { ...manual(), source: { kind: 'resume', signature: 'a'.repeat(64), quote: '\ud800', start: 0, end: 1 } },
    ]) {
      const serialized = JSON.stringify(invalid);
      expect(validateExperienceEntries([invalid])).toEqual({ ok: false, code: 'invalid_unicode' });
      expect(JSON.stringify(invalid)).toBe(serialized);
    }
  });
  it('uses Unicode codepoint limits for the complete resume', async () => {
    await expect(sourceDigest('😀'.repeat(60_000))).resolves.toMatch(/^[a-f0-9]{64}$/);
    await expect(sourceDigest('😀'.repeat(60_001))).rejects.toMatchObject({ code: 'resume_too_long' });
  });
  it('treats legacy omission as unconfirmed empty, but rejects null/object', () => {
    expect(validateExperienceEntries(undefined)).toEqual({ ok: true, value: [] });
    expect(validateExperienceEntries(null).ok).toBe(false);
    expect(validateExperienceEntries({}).ok).toBe(false);
  });
  it.each([
    { id: '' }, { id: 'x'.repeat(81) }, { revision: 0 }, { revision: 1.1 },
    { revision: Number.MAX_SAFE_INTEGER + 1 }, { status: 'invented' },
    { text: '  ' }, { text: 'x'.repeat(6_001) }, { source: { kind: 'unknown' } },
  ])('rejects malformed entry %j', (invalid) => {
    expect(validateExperienceEntries([{ ...manual(), ...invalid }]).ok).toBe(false);
  });
  it('rejects duplicate IDs and entry/count/text budgets without truncation', () => {
    expect(validateExperienceEntries([manual(), manual()])).toEqual({ ok: false, code: 'duplicate_id' });
    expect(validateExperienceEntries(Array.from({ length: 101 }, (_, i) => manual({ id: `${i}` })))).toEqual({ ok: false, code: 'too_many_entries' });
    const max = Array.from({ length: 10 }, (_, i) => manual({ id: `${i}`, text: '😀'.repeat(6_000) }));
    expect(validateExperienceEntries(max).ok).toBe(true);
    expect(validateExperienceEntries([...max, manual()])).toEqual({ ok: false, code: 'text_limit' });
  });
  it('separately bounds quote budgets and requires safe codepoint ranges', () => {
    const source = { kind: 'resume' as const, signature: 'a'.repeat(64), quote: 'x'.repeat(6_000), start: 0, end: 6_000 };
    const entries = Array.from({ length: 11 }, (_, i) => manual({ id: `${i}`, text: 'edited', source }));
    expect(validateExperienceEntries(entries)).toEqual({ ok: false, code: 'quote_limit' });
    for (const invalid of [{ start: -1 }, { start: 0.5 }, { end: 60_001 }, { end: 5_999 }, { signature: 'A'.repeat(64) }]) {
      expect(validateExperienceEntries([manual({ source: { ...source, ...invalid } })]).ok).toBe(false);
    }
  });
});

describe('local proposals and confirmed eligibility', () => {
  it('retains exact Unicode offsets, CRLF and quotes while producing only candidates', async () => {
    const raw = '  姓名😀\r\n\r\n  Built a robot.\r\nPublished a paper.  \r\n\r\n尾部✅';
    const first = await createResumeCandidates(raw);
    expect(first).toHaveLength(3);
    expect(await createResumeCandidates(raw)).toEqual(first);
    for (const entry of first) {
      expect(entry.status).toBe('candidate');
      expect(entry.id.length).toBeLessThanOrEqual(80);
      if (entry.source.kind !== 'resume') throw new Error('expected source');
      expect(Array.from(raw).slice(entry.source.start, entry.source.end).join('')).toBe(entry.source.quote);
    }
    expect(first[2].text).toBe('尾部✅');
    expect(activeExperienceEntries(first, { rawText: raw, expectedDigest: await sourceDigest(raw) })).toEqual([]);
  });
  it('splits a long paragraph without discarding its final evidence', async () => {
    const raw = 'x'.repeat(6_000) + 'TAIL';
    const entries = await createResumeCandidates(raw);
    expect(entries.map((entry) => entry.text).join('')).toBe(raw);
    expect(entries).toHaveLength(2);
    expect(entries[1].source).toMatchObject({ start: 6_000, end: 6_004, quote: 'TAIL' });
  });
  it('rejects too many local candidates as a whole', async () => {
    await expect(createResumeCandidates(Array.from({ length: 101 }, (_, i) => `Project ${i}`).join('\n')))
      .rejects.toMatchObject({ code: 'too_many_entries' });
  });
  it('does not treat an explicit manual add as confirmation', () => {
    expect(createManualCandidate('Built the actual device', 'manual')).toMatchObject({ status: 'candidate', revision: 1, source: { kind: 'manual' } });
  });
  it('allows rewritten confirmed text only while the original quote and digest match', async () => {
    const raw = '😀\nBuilt the robot';
    const [, candidate] = await createResumeCandidates(raw);
    const confirmed = { ...candidate, status: 'confirmed' as const, revision: 2, text: 'I built a robot.' };
    const context = { rawText: raw, expectedDigest: await sourceDigest(raw) };
    expect(isActiveExperience(confirmed, context)).toBe(true);
    expect(isActiveExperience({ ...confirmed, status: 'rejected' }, context)).toBe(false);
    expect(isActiveExperience(confirmed, { ...context, expectedDigest: 'b'.repeat(64) })).toBe(false);
    expect(isActiveExperience(confirmed, { ...context, rawText: raw.replace('robot', 'paper') })).toBe(false);
    if (confirmed.source.kind !== 'resume') throw new Error('expected resume');
    expect(isActiveExperience({ ...confirmed, source: { ...confirmed.source, start: 3, end: 18 } }, context)).toBe(false);
  });
  it('replaces resume sources by withdrawn revisions and removes only resume sources on deletion', async () => {
    const [candidate] = await createResumeCandidates('Built a robot');
    const confirmed = { ...candidate, status: 'confirmed' as const, revision: 2 };
    const own = manual({ status: 'confirmed' });
    const withdrawn = withdrawResumeEntries([confirmed, own]);
    expect(withdrawn[0]).toMatchObject({ status: 'withdrawn', revision: 3, source: confirmed.source });
    expect(withdrawn[1]).toEqual(own);
    expect(withdrawResumeEntries(withdrawn)).toEqual(withdrawn);
    expect(removeResumeEntries(withdrawn)).toEqual([own]);
    expect(isActiveExperience(own, { rawText: '', expectedDigest: '' })).toBe(true);
  });
});
