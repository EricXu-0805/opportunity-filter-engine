import { afterEach, describe, expect, it, vi } from 'vitest';
import fixture from './__fixtures__/import-suggestions.json';
import type { ImportedOpportunity } from './api';

afterEach(() => { localStorage.clear(); vi.resetModules(); });

describe('actual API import suggestions survive Save and reopen', () => {
  it.each(fixture.cases)('$name preserves source and suggestions without creating qualifications', async ({ response, canonical }) => {
    const owner = await import('./identity-owner');
    const storage = await import('./custom-imports');
    owner.advanceOwnerEpoch('b57-fixture-owner');
    await owner.syncLocalIdentityOwner('b57-fixture-owner');
    const raw = response.opportunity as ImportedOpportunity;
    const saved = storage.addCustomImport(raw, owner.captureOwnerToken());
    expect(saved).not.toBeNull();
    const serialized = localStorage.getItem('ofe_custom_imports');
    vi.resetModules();
    const freshOwner = await import('./identity-owner');
    const freshStorage = await import('./custom-imports');
    freshOwner.advanceOwnerEpoch('b57-fixture-owner');
    await freshOwner.syncLocalIdentityOwner('b57-fixture-owner');
    const restored = freshStorage.readCustomImports()[0];
    expect(restored).toEqual(saved);
    expect(restored.opportunity.description_raw).toBe(raw.description_raw);
    const { customImportToOpp } = await import('@/app/favorites/types');
    const view = customImportToOpp(restored);
    expect(view.eligibility?.skills_required).toBeUndefined();
    expect(view.import_suggestions).toEqual({ skills: ['R', 'Java', 'C++'], summary: 'Generated summary to review.' });
    expect(view).not.toHaveProperty('skill_mentions');
    expect(canonical.eligibility.skills_required).toEqual([]);
    expect(canonical.eligibility.skills_preferred).toEqual([]);
    expect(canonical.metadata.skill_mentions).toEqual([]);
    expect(localStorage.getItem('ofe_custom_imports')).toBe(serialized);
  });
});
