import { describe, expect, it } from 'vitest';
import { DEFAULT_PROFILE } from '@/app/home/types';
import { toMatchProfileRequest, toProfileRequest } from './api';
import { sourceDigest } from './experience-evidence';
import { hashProfile } from './match-utils';
import type { ExperienceEntry } from './types';

const project: ExperienceEntry = {
  id: 'team-pr', revision: 3, status: 'confirmed', text: 'Implemented a Python parser for our project.',
  source: { kind: 'github', repository: 'sample-org/sample', head_repository: null, number: 5, author: 'synthetic-user', title: 'Add parser' },
};
const manual: ExperienceEntry = {
  id: 'work-1', revision: 1, status: 'confirmed', text: 'Research Assistant — Example Organization\nFrom 2021 to 2023\nMapped land use with GIS.', source: { kind: 'manual' },
};

describe('experiences used by the actual matching request', () => {
  it('keeps original confirmed wording and source references without promoting them to skills', () => {
    const profile = { ...DEFAULT_PROFILE, experience_entries: [project, manual, { ...manual, id: 'pending', status: 'candidate' as const }] };
    const matched = toMatchProfileRequest(profile);
    expect(matched).toMatchObject({ match_experiences: [
      { id: project.id, revision: 3, status: 'confirmed', source: 'github', text: project.text },
      { id: manual.id, revision: 1, status: 'confirmed', source: 'manual', text: manual.text },
    ] });
    expect(matched.hard_skills).toEqual([]);
    expect(toProfileRequest(profile)).not.toHaveProperty('match_experiences');
    expect(JSON.stringify(matched)).not.toContain('synthetic-user');
  });
  it('sends only the approved wording bound to the exact current PDF, including Unicode offsets', async () => {
    const quote = '我使用 GIS 绘制了湿地图。';
    const prefix = 'Private 🙂\n';
    const raw = prefix + quote + '\nPrivate footer';
    const start = Array.from(prefix).length;
    const source = { kind: 'resume' as const, signature: await sourceDigest(raw), quote,
      start, end: start + Array.from(quote).length };
    const entry: ExperienceEntry = { id: 'pdf-excerpt', revision: 7, status: 'confirmed',
      text: 'I mapped wetlands using GIS. 我核对了原文。', source };
    const profile = { ...DEFAULT_PROFILE, resume_text: raw, experience_entries: [entry, project] };
    const request = toMatchProfileRequest(profile);
    expect(request).toMatchObject({ match_experiences: [
      { id: entry.id, revision: 7, status: 'confirmed', text: entry.text, source: 'resume' },
      { id: project.id, source: 'github' },
    ] });
    for (const localOnly of [quote, 'Private', source.signature]) expect(JSON.stringify(request)).not.toContain(localOnly);
    const originalHash = hashProfile(profile);
    for (const stale of [
      { ...profile, resume_text: raw + 'x' },
      { ...profile, resume_text: undefined },
      { ...profile, resume_text: raw + '\ud800' },
      { ...profile, experience_entries: [{ ...entry, source: { ...source, start: start+1, end: source.end+1 } }, project] },
      { ...profile, experience_entries: [{ ...entry, source: { ...source, quote: quote.replace('图','湖') } }, project] },
      ...(['candidate','rejected','withdrawn'] as const).map(status => ({...profile, experience_entries: [{...entry, status}, project]})),
    ]) {
      expect(toMatchProfileRequest(stale)).toMatchObject({ match_experiences: [{ id: project.id }] });
      expect(hashProfile(stale)).not.toBe(originalHash);
    }
    expect(toMatchProfileRequest(JSON.parse(JSON.stringify(profile)))).toEqual(request);
  });
  it('retains complete Unicode entries at both limits and rejects over-limit material intact', () => {
    const text = '😀'.repeat(5999) + '界';
    const entries = Array.from({ length: 10 }, (_, i) => ({ ...manual, id: 'long-' + i, text }));
    const profile = { ...DEFAULT_PROFILE, experience_entries: entries };
    expect(toMatchProfileRequest(profile)).toMatchObject({ match_experiences: entries.map(e => ({ id: e.id, text })) });
    const tooLong = [{...entries[0], text: text + '尾'}];
    const tooManyCharacters = [...entries, {...manual, id: 'last', text: '尾'}];
    for (const unmodified of [tooLong, tooManyCharacters]) {
      expect(() => toMatchProfileRequest({...profile, experience_entries: unmodified})).toThrow();
      expect(unmodified.at(-1)?.text.endsWith('尾')).toBe(true);
    }
  });
  it('changes the cached results when confirmed work changes, and returns to the original key after withdrawal', () => {
    const base = hashProfile(DEFAULT_PROFILE);
    const withEntry = (entry: ExperienceEntry) => ({ ...DEFAULT_PROFILE, experience_entries: [entry] });
    const original = hashProfile(withEntry(project));
    expect(original).not.toBe(base);
    expect(hashProfile(withEntry({ ...project, text: 'Processed samples using MATLAB.' }))).not.toBe(original);
    expect(hashProfile(withEntry({ ...project, revision: 4 }))).not.toBe(original);
    for (const status of ['candidate','rejected','withdrawn'] as const) {
      expect(hashProfile(withEntry({ ...project, status }))).toBe(base);
      expect(toMatchProfileRequest(withEntry({ ...project, status }))).not.toHaveProperty('match_experiences');
    }
    const corrupt = { ...project, source: { kind: 'unknown' } } as unknown as ExperienceEntry;
    expect(() => hashProfile(withEntry(corrupt))).not.toThrow();
    expect(() => toMatchProfileRequest(withEntry(corrupt))).toThrow();
  });
});
