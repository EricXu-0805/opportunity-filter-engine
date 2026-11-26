import { describe, expect, it } from 'vitest';
import { DEFAULT_PROFILE } from '@/app/home/types';
import { toMatchProfileRequest, toProfileRequest } from './api';
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
