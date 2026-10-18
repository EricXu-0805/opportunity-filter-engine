/* @vitest-environment jsdom */
// M59: the real header, saved-searches section and cards, so the page's heading outline
// is the one a screen reader walks. Data hooks, modals and the private-import panels are stubbed.
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import axe from 'axe-core';
const feed = vi.hoisted(() => ({ savedSearches: [] as unknown[], selectionMode: false }));
vi.mock('@/i18n/client', () => ({ useT: () => ({ t: (key: string) => key, locale: 'en' }) }));
vi.mock('next/navigation', () => ({ useRouter: () => ({ back: vi.fn(), push: vi.fn() }) }));
vi.mock('@/lib/custom-imports', () => ({ useCustomImportStorageState: () => ({ status: 'ready', entries: [] }) }));
vi.mock('@/lib/use-profile-refresh', () => ({ useProfileRefresh: () => ({ status: 'ready', refresh: async () => true, checkForAction: async () => null }) }));
vi.mock('./use-favorites-data', () => ({ useFavoritesData: () => ({ serverOpportunities: [{ id: 'opp-1', title: 'Protein folding lab',
  source_type: 'campus_program', record_kind: 'listing', target_truth: { listing_state: 'open', reference_only: false, actionable: true,
    accepting_state: 'accepting', reason_code: null, verified_at: null, expires_at: null } }],
  loading: false, error: false, retry: vi.fn(), unavailableCount: 0, identityGeneration: 1, ownerScopeKey: 'local', ownerReady: true,
  handleRemove: vi.fn(), removeError: null, retryRemove: vi.fn() }) }));
vi.mock('./use-saved-searches', () => ({ useSavedSearches: () => ({ savedSearches: feed.savedSearches, digests: null, loadError: false,
  retryLoad: async () => {}, handleRemove: async () => {}, handleApplyOptimisticClear: () => {}, handleDigestSave: async () => true, accountEmail: null }) }));
// Compare selection is the state in which the page drops the saved-searches section.
vi.mock('./use-compare-selection', async original => {
  const real = await original<typeof import('./use-compare-selection')>();
  return { useCompareSelection: () => ({ ...real.useCompareSelection(), selectionMode: feed.selectionMode }) };
});
vi.mock('@/components/StorageStatusBanner', () => ({ default: () => null }));
vi.mock('@/components/SaveFavoritesAnchor', () => ({ default: () => null }));
vi.mock('@/components/PrivateImportList', () => ({ default: () => null }));
vi.mock('@/components/PrivateImportAdoptionPanel', () => ({ default: () => null }));
vi.mock('./SelectionFooter', () => ({ SelectionFooter: () => null }));
vi.mock('@/components/CheckedColdEmailModal', () => ({ default: () => null }));
vi.mock('@/components/CheckedTailorModal', () => ({ default: () => null }));
import FavoritesPage from './page';
const search = { id: 's1', name: 'Biology', query: 'protein', filters: {}, sort_by: 'match', tab: 'all', created_at: '2026-10-01T00:00:00Z',
  updated_at: '2026-10-01T00:00:00Z', last_run_at: null, last_result_ids: [], new_match_ids: [] };
beforeEach(() => { feed.savedSearches = []; feed.selectionMode = false; });
describe('Favorites heading outline', () => {
  it.each([
    ['with a saved search', [search], false, ['1 favorites.title', '2 favorites.savedSearches.sectionTitle', '2 favorites.listHeading', '3 Protein folding lab']],
    ['with no saved searches', [], false, ['1 favorites.title', '2 favorites.savedSearches.sectionTitle', '2 favorites.listHeading', '3 Protein folding lab']],
    ['without the saved-searches section', [search], true, ['1 favorites.title', '2 favorites.listHeading', '3 Protein folding lab']],
  ])('heads the saved cards with their own h2 %s', async (_case, savedSearches, selectionMode, outline) => {
    // The card titles are h3. Without the saved-searches h2 they followed the page's h1 directly,
    // and with it a screen reader filed the saved opportunities under "Saved searches".
    feed.savedSearches = savedSearches; feed.selectionMode = selectionMode;
    render(<main id="main-content"><FavoritesPage /></main>);
    const { violations } = await axe.run(document, { runOnly: { type: 'rule', values: ['heading-order'] } });
    expect(violations.map(v => `${v.id}: ${v.nodes.map(n => n.target.join(' ')).join(', ')}`)).toEqual([]);
    expect(screen.getAllByRole('heading').map(h => `${h.tagName[1]} ${h.textContent}`)).toEqual(outline);
  });
});
