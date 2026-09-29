import { afterEach, describe, expect, it, vi } from 'vitest';
import fixture from './__fixtures__/url-import-sources.json';
import type { ImportedOpportunity } from './api';

afterEach(() => {
  localStorage.clear();
  vi.resetModules();
});

// These are actual backend.main /import-url responses produced with synthetic
// HTTP pages. Only the transport was replaced; the receipt is not hand-authored.
const accepted = fixture.cases.filter((item) => item.response.ok);

describe('URL import source receipt persistence', () => {
  it.each(accepted)('keeps $name source evidence after saving and a fresh module read', async (item) => {
    const identity = await import('./identity-owner');
    const imports = await import('./custom-imports');
    identity.advanceOwnerEpoch('b56-url-owner');
    await identity.syncLocalIdentityOwner('b56-url-owner');
    const opportunity = item.response.opportunity as ImportedOpportunity;
    const saved = await imports.addCustomImport(opportunity, identity.captureOwnerToken());
    expect(saved.ok).toBe(true);
    if (!saved.ok) throw new Error(saved.reason);
    expect(imports.readCustomImports()[0].opportunity).toEqual(opportunity);
    const serialized = localStorage.getItem('ofe_custom_imports');
    expect(serialized).toContain('contact_instruction_capture');

    // Drop JS module caches, retaining only localStorage: this checks the
    // persistence path rather than comparing the original in-memory object.
    vi.resetModules();
    const freshIdentity = await import('./identity-owner');
    const freshImports = await import('./custom-imports');
    freshIdentity.advanceOwnerEpoch('b56-url-owner');
    await freshIdentity.syncLocalIdentityOwner('b56-url-owner');
    const restored = freshImports.readCustomImports();
    expect(restored).toEqual([saved.entry]);
    expect(restored[0].opportunity.extra_fields).toEqual(opportunity.extra_fields);
    expect(restored[0].opportunity.extra_fields.needs_manual_review).toBe(true);
    expect(localStorage.getItem('ofe_custom_imports')).toBe(serialized);
  });

  it('does not move a saved source bundle into another owner', async () => {
    const identity = await import('./identity-owner');
    const imports = await import('./custom-imports');
    identity.advanceOwnerEpoch('b56-first-owner');
    await identity.syncLocalIdentityOwner('b56-first-owner');
    const token = identity.captureOwnerToken();
    const opportunity = accepted[0].response.opportunity as ImportedOpportunity;
    expect((await imports.addCustomImport(opportunity, token)).ok).toBe(true);
    identity.advanceOwnerEpoch('b56-second-owner');
    await identity.syncLocalIdentityOwner('b56-second-owner');
    expect(imports.readCustomImports()).toEqual([]);
    expect(await imports.addCustomImport(opportunity, token)).toEqual({ ok: false, reason: 'owner_changed' });
  });
});
