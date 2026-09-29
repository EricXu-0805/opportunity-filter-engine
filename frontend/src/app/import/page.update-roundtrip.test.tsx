import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { dictionaries } from '@/i18n/dictionaries';
import fixture from './__fixtures__/update-api.json';

const localeState = vi.hoisted(() => ({ current: 'en' as 'en' | 'zh' }));
vi.mock('@/i18n/client', async () => {
  const { dictionaries: words } = await import('@/i18n/dictionaries');
  const t = (key: string) => key.split('.').reduce<unknown>((v, k) => (v as Record<string, unknown>)?.[k], words[localeState.current]) as string;
  return { useT: () => ({ t, locale: localeState.current, setLocale: vi.fn() }) };
});
vi.mock('@/lib/supabase', () => ({ getRevealAccessToken: async () => null, refreshRevealAccessToken: async () => null }));
const fetchMock = vi.fn();
const t = (key: string) => key.split('.').reduce<unknown>((v, k) => (v as Record<string, unknown>)?.[k], dictionaries[localeState.current]) as string;
const response = (body: unknown) => new Response(JSON.stringify(body), { status: 200, headers: { 'content-type': 'application/json' } });

beforeEach(() => { localStorage.clear(); fetchMock.mockReset(); vi.stubGlobal('fetch', fetchMock); vi.resetModules(); });
afterEach(() => { cleanup(); localStorage.clear(); vi.unstubAllGlobals(); });

// Actual local API response bodies, controlled fetch/model upstream; this test
// mocks only HTTP delivery. The real adapter, page and storage operations run.
describe('actual reimport response → reviewed update → reopened favorite', () => {
  it.each(['en', 'zh'] as const)('retains the id and full new material in %s, without touching existing draft keys', async (locale) => {
    localeState.current = locale;
    const owner = await import('@/lib/identity-owner');
    owner.advanceOwnerEpoch('b59-roundtrip-owner'); await owner.syncLocalIdentityOwner('b59-roundtrip-owner');
    const storage = await import('@/lib/custom-imports');
    const { writeLocalStorageJSON } = await import('@/lib/use-local-storage-json');
    const { STORAGE_KEYS } = await import('@/lib/storage-keys');
    const { default: ImportPage } = await import('./page');
    fetchMock.mockResolvedValueOnce(response(fixture.initial)).mockResolvedValueOnce(response(fixture.updated));
    const mounted = render(<ImportPage />);
    fireEvent.change(screen.getByPlaceholderText(t('import.urlPlaceholder')), { target: { value: fixture.initial.opportunity.source_url } });
    fireEvent.click(screen.getByText(t('import.fetchButton')));
    await screen.findByText(fixture.initial.opportunity.title);
    fireEvent.click(screen.getByText(t('import.saveToList')));
    await screen.findByText(t('import.saved'));
    const originalEntry = storage.readCustomImports()[0];
    const emailKey = STORAGE_KEYS.COLD_EMAIL_DRAFT_PREFIX + originalEntry.id;
    const resumeKey = STORAGE_KEYS.TAILOR_DRAFT_PREFIX + originalEntry.id;
    // Deliberately opaque sentinels: preservation of these keys is asserted,
    // not validity or availability of custom-target email/resume workflows.
    expect(writeLocalStorageJSON(emailKey, { prior_material: 'Existing email' }, owner.captureOwnerToken())).toBe(true);
    expect(writeLocalStorageJSON(resumeKey, { prior_material: 'Existing resume' }, owner.captureOwnerToken())).toBe(true);
    const draftsBefore = [localStorage.getItem(emailKey), localStorage.getItem(resumeKey)];
    fireEvent.click(screen.getByText(t('import.tryAnother')));
    fireEvent.change(screen.getByPlaceholderText(t('import.urlPlaceholder')), { target: { value: fixture.updated.opportunity.source_url } });
    fireEvent.click(screen.getByText(t('import.fetchButton')));
    await screen.findByRole('button', { name: t('import.reviewUpdate') });
    expect(storage.readCustomImports()[0]).toEqual(originalEntry);
    fireEvent.click(screen.getByRole('button', { name: t('import.reviewUpdate') }));
    const previous = screen.getByRole('region', { name: t('import.previousVersion') });
    const replacement = screen.getByRole('region', { name: t('import.newVersion') });
    const previousButton = within(previous).getByRole('button', { name: t('import.expandSource') });
    const newButton = within(replacement).getByRole('button', { name: t('import.expandSource') });
    fireEvent.click(previousButton); fireEvent.click(newButton);
    expect(document.getElementById(previousButton.getAttribute('aria-controls')!)?.textContent).toBe(fixture.initial.opportunity.description_raw);
    expect(document.getElementById(newButton.getAttribute('aria-controls')!)?.textContent).toBe(fixture.updated.opportunity.description_raw);
    expect(within(replacement).getByText(t('import.excerptAiInput'))).toBeInTheDocument();
    expect(within(replacement).queryByText(t('import.fullAiInput'))).toBeNull();
    expect(screen.getByText(t('import.updateDraftsNotice'))).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: t('import.confirmUpdate') }));
    await screen.findByText(t('import.updated'));
    const updated = storage.readCustomImports();
    expect(updated).toHaveLength(1); expect(updated[0].id).toBe(originalEntry.id);
    expect(updated[0].imported_at).toBe(originalEntry.imported_at);
    expect(updated[0].opportunity).toEqual(fixture.updated.opportunity);
    expect([localStorage.getItem(emailKey), localStorage.getItem(resumeKey)]).toEqual(draftsBefore);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    for (const [url, options] of fetchMock.mock.calls) {
      expect(url).toMatch(/\/import-url$/);
      expect(JSON.parse(options.body)).toEqual({ url: fixture.initial.opportunity.source_url });
    }
    const savedRaw = localStorage.getItem('ofe_custom_imports');
    mounted.unmount(); vi.resetModules();
    const freshOwner = await import('@/lib/identity-owner');
    freshOwner.advanceOwnerEpoch('b59-roundtrip-owner'); await freshOwner.syncLocalIdentityOwner('b59-roundtrip-owner');
    const { readCustomImports } = await import('@/lib/custom-imports');
    const restored = readCustomImports()[0];
    expect(restored).toEqual(updated[0]);
    expect(localStorage.getItem('ofe_custom_imports')).toBe(savedRaw);
    const { customImportToOpp } = await import('@/app/favorites/types');
    const { OpportunityCard } = await import('@/app/favorites/OpportunityCard');
    const view = customImportToOpp(restored);
    expect(view.import_source?.aiInputScope).toBe('source_excerpt');
    expect(view.eligibility?.skills_required).toBeUndefined();
    render(<OpportunityCard opp={view} selectionMode={false} isSelected={false} selectedSize={0} isExpanded hasProfile={false}
      onToggleExpand={vi.fn()} onToggleSelect={vi.fn()} onRemove={vi.fn()} onOpenEmailModal={vi.fn()} tailorDisabled={false} t={t} />);
    fireEvent.click(screen.getByRole('button', { name: t('import.expandSource') }));
    expect(screen.getByText(/LATE_NEW_SOURCE/).textContent).toBe(fixture.updated.opportunity.description_raw);
    expect(screen.getByText(/LATE_NEW_SOURCE/)).not.toHaveClass('line-clamp-4');
    expect([localStorage.getItem(emailKey), localStorage.getItem(resumeKey)]).toEqual(draftsBefore);
  });
});
