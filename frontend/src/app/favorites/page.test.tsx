/* @vitest-environment jsdom */
// Narrow integration test: proves the CALLER (FavoritesPage) actually
// remounts TailorModal across an identityGeneration change, via a real
// key={`${identityGeneration}:${tailorModal.id}`} — mirrors
// OpportunityDetail.test.tsx's own TailorModal-keying proof (same C1-R2B
// concern, different page). Every OTHER child is stubbed so this stays a
// narrow, fast test of the wiring, with a sentinel TailorModal doing the
// actual mount/unmount work.
import { describe, it, expect, vi } from 'vitest';
import { useRef } from 'react';
import { render, screen, fireEvent } from '@testing-library/react';

vi.mock('@/i18n/client', () => ({
  useT: () => ({ t: (key: string) => key }),
}));

vi.mock('next/navigation', () => ({
  useRouter: () => ({ back: vi.fn(), push: vi.fn(), replace: vi.fn() }),
}));

vi.mock('@/lib/custom-imports', () => ({
  useCustomImports: () => [],
}));

vi.mock('@/components/StorageStatusBanner', () => ({ default: () => null }));
vi.mock('@/components/SaveFavoritesAnchor', () => ({ default: () => null }));
vi.mock('./FavoritesEmptyState', () => ({ FavoritesEmptyState: () => null }));
vi.mock('./FavoritesHeader', () => ({ FavoritesHeader: () => null }));
vi.mock('./SavedSearchesSection', () => ({ SavedSearchesSection: () => null }));
vi.mock('./use-saved-searches', () => ({
  useSavedSearches: () => ({
    savedSearches: [],
    digests: null,
    handleRemove: async () => {},
    handleApplyOptimisticClear: () => {},
    handleDigestSave: async () => true,
  }),
}));
vi.mock('./SelectionFooter', () => ({ SelectionFooter: () => null }));
vi.mock('@/components/ColdEmailModal', () => ({ default: () => null }));

// A sentinel mock, NOT the real OpportunityCard: exposes onOpenTailorModal
// via a plain button and tailorDisabled as visible text, so the test can
// drive + assert the fail-closed gate without exercising the real card's
// full render.
vi.mock('./OpportunityCard', () => ({
  OpportunityCard: (props: {
    opp: { id: string; title: string };
    onOpenTailorModal?: (opp: { id: string; title: string }) => void;
    tailorDisabled: boolean;
  }) => (
    <div data-testid={`opp-card-${props.opp.id}`}>
      <span data-testid={`tailor-disabled-${props.opp.id}`}>{String(props.tailorDisabled)}</span>
      <button
        type="button"
        disabled={props.tailorDisabled}
        onClick={() => props.onOpenTailorModal?.(props.opp)}
      >
        {`Tailor ${props.opp.title}`}
      </button>
    </div>
  ),
}));

// A sentinel mock, NOT the real TailorModal: the real component has its OWN
// ownerScopeKey-driven reset effect (and now a profile-fingerprint-driven
// one too), which would clear/reset its internal state on a prop change
// alone — a test built on the real component would stay green even with
// the page's key REMOVED, proving nothing about the key itself. This
// sentinel's mountId is generated exactly once per genuine mount (useRef's
// initializer), so it can ONLY change via an actual unmount+remount — the
// one thing a missing/wrong key would fail to cause. The real
// opportunityId/ownerReady/ownerScopeKey props are rendered too, so the
// wiring of those (separately from the key) stays covered.
vi.mock('@/components/TailorModal', () => ({
  default: function MockTailorModal(props: {
    isOpen: boolean;
    opportunityId: string;
    ownerReady: boolean;
    ownerScopeKey: string | null;
  }) {
    const mountIdRef = useRef(Math.random().toString(36).slice(2));
    if (!props.isOpen) return null;
    return (
      <div data-testid="mock-tailor-modal">
        <span data-testid="mount-id">{mountIdRef.current}</span>
        <span data-testid="tailor-opp-id">{props.opportunityId}</span>
        <span data-testid="owner-ready">{String(props.ownerReady)}</span>
        <span data-testid="owner-scope-key">{String(props.ownerScopeKey)}</span>
      </div>
    );
  },
}));

const mockHookState = vi.hoisted(() => ({ current: null as unknown }));
vi.mock('./use-favorites-data', () => ({
  useFavoritesData: () => mockHookState.current,
}));

import FavoritesPage from './page';
import { STORAGE_KEYS } from '@/lib/storage-keys';
import { enterLocalOnlyMode } from '@/lib/identity-owner';

function baseHookResult(overrides: Record<string, unknown> = {}) {
  return {
    // A saved record that is still live carries the server's truth; the page
    // gates its modals on it.
    serverOpportunities: [{
      id: 'opp-1',
      title: 'Opp One',
      // A confirmed listing: reviewed source type plus the wire kind the
      // server sends with it. An unreviewed one is no longer actionable, so
      // this fixture would otherwise be a dead row and every modal assertion
      // would measure the refusal path.
      source_type: 'campus_program',
      record_kind: 'listing',
      target_truth: {
        listing_state: 'open',
        reference_only: false,
        actionable: true,
        accepting_state: 'accepting',
        reason_code: null,
        verified_at: null,
        expires_at: null,
      },
    }],
    loading: false,
    error: false,
    retry: () => {},
    unavailableCount: 0,
    identityGeneration: 1,
    ownerReady: true,
    ownerScopeKey: 'owner-1',
    handleRemove: async () => {},
    removeError: null,
    retryRemove: () => {},
    ...overrides,
  };
}

function setProfile() {
  // useLocalStorageJSON(PROFILE) is gated by the local-owner readiness
  // barrier (PROFILE is a USER_SCOPED key) — a raw localStorage write alone
  // is invisible to it until an identity (or, here, the confirmed
  // local-only realm) is established, exactly as in the real unconfigured-
  // Supabase app.
  enterLocalOnlyMode();
  window.localStorage.setItem(STORAGE_KEYS.PROFILE, JSON.stringify({
    institution: 'UIUC', major: 'CS', grade: 'Sophomore', is_international: false,
    research_interests: 'ml', skills: [],
  }));
}

describe('FavoritesPage — TailorModal is keyed by identityGeneration (C1-R2B)', () => {
  it('an identityGeneration bump (a real account switch) force-remounts TailorModal — proven via a sentinel mount-id that can ONLY change on a genuine unmount+remount. tailorModal stays open across both renders (page-owned state, never explicitly closed here) to isolate the key\'s OWN protection', async () => {
    setProfile();
    mockHookState.current = baseHookResult({ identityGeneration: 1, ownerScopeKey: 'owner-1' });
    const { rerender } = render(<FavoritesPage />);

    fireEvent.click(screen.getByRole('button', { name: 'Tailor Opp One' }));
    const mountId1 = (await screen.findByTestId('mount-id')).textContent;
    expect(screen.getByTestId('owner-ready').textContent).toBe('true');
    expect(screen.getByTestId('owner-scope-key').textContent).toBe('owner-1');
    expect(screen.getByTestId('tailor-opp-id').textContent).toBe('opp-1');

    // A real account switch — SAME target opportunity, but a NEW
    // identityGeneration and a different ownerScopeKey.
    mockHookState.current = baseHookResult({ identityGeneration: 2, ownerScopeKey: 'owner-2' });
    rerender(<FavoritesPage />);

    const mountId2 = screen.getByTestId('mount-id').textContent;
    expect(mountId2).not.toBe(mountId1); // genuinely torn down and recreated — a fresh instance
    expect(screen.getByTestId('owner-scope-key').textContent).toBe('owner-2'); // real props still flow through
  });

  it('a re-render with the SAME identityGeneration (e.g. a manual data retry — different serverOpportunities/unavailableCount, same identity) does NOT remount TailorModal — the sentinel\'s mount-id survives', async () => {
    setProfile();
    mockHookState.current = baseHookResult({ identityGeneration: 1, ownerScopeKey: 'owner-1' });
    const { rerender } = render(<FavoritesPage />);

    fireEvent.click(screen.getByRole('button', { name: 'Tailor Opp One' }));
    const mountId1 = (await screen.findByTestId('mount-id')).textContent;

    // Same identityGeneration/ownerScopeKey — only data-shaped fields
    // changed, exactly like retry()'s own contract (never touches
    // identityGeneration/ownerScopeKey).
    mockHookState.current = baseHookResult({
      identityGeneration: 1,
      ownerScopeKey: 'owner-1',
      unavailableCount: 3,
    });
    rerender(<FavoritesPage />);

    const mountId2 = screen.getByTestId('mount-id').textContent;
    expect(mountId2).toBe(mountId1); // NOT remounted — same instance throughout
  });

  it('ownerReady=false fail-closed gate: the Tailor CTA is disabled and a click never opens the modal — no mount-id sentinel ever appears', async () => {
    setProfile();
    mockHookState.current = baseHookResult({ ownerReady: false });
    render(<FavoritesPage />);

    expect(screen.getByTestId('tailor-disabled-opp-1').textContent).toBe('true');
    const cta = screen.getByRole('button', { name: 'Tailor Opp One' });
    expect(cta).toBeDisabled();
    fireEvent.click(cta); // no-op — jsdom/browsers never dispatch click on a disabled button
    expect(screen.queryByTestId('mock-tailor-modal')).toBeNull();
  });

  it('ownerReady=true: the gate is open, the CTA is enabled, and clicking it wires ownerScopeKey through to the modal', async () => {
    setProfile();
    mockHookState.current = baseHookResult({ ownerReady: true, ownerScopeKey: 'owner-9' });
    render(<FavoritesPage />);

    expect(screen.getByTestId('tailor-disabled-opp-1').textContent).toBe('false');
    const cta = screen.getByRole('button', { name: 'Tailor Opp One' });
    expect(cta).not.toBeDisabled();
    fireEvent.click(cta);

    expect(await screen.findByTestId('mock-tailor-modal')).toBeTruthy();
    expect(screen.getByTestId('owner-scope-key').textContent).toBe('owner-9');
  });
});

describe('an open Tailor modal is re-checked on every render, not only at open', () => {
  const HISTORICAL = {
    listing_state: 'closed',
    reference_only: true,
    actionable: false,
    accepting_state: 'not_accepting',
    reason_code: 'listing_closed',
    verified_at: null,
    expires_at: null,
  } as const;

  const ACTIONABLE = {
    listing_state: 'open',
    reference_only: false,
    actionable: true,
    accepting_state: 'accepting',
    reason_code: null,
    verified_at: null,
    expires_at: null,
  } as const;

  function withTarget(target: Record<string, unknown> | null) {
    return baseHookResult({
      ownerReady: true,
      ownerScopeKey: 'owner-9',
      identityGeneration: 1,
      serverOpportunities: target ? [target] : [],
    });
  }

  const live = () => ({
    id: 'opp-1', title: 'Opp One',
    source_type: 'campus_program', record_kind: 'listing',
    target_truth: { ...ACTIONABLE },
  });

  const DEGRADED: [string, unknown][] = [
    ['historical', HISTORICAL],
    ['null truth', null],
    ['malformed truth', { listing_state: 'open' }],
  ];

  it.each(DEGRADED)('unmounts the modal when the target becomes %s', async (_label, truth) => {
    // The modal opened while the target was live. A refresh then closed it —
    // same identity, so nothing remounts and no callback runs again. Checking
    // only at open time would leave a Tailor session attached to a target the
    // server has already started refusing.
    setProfile();
    mockHookState.current = withTarget(live());
    const { rerender } = render(<FavoritesPage />);
    fireEvent.click(screen.getByRole('button', { name: 'Tailor Opp One' }));
    expect(await screen.findByTestId('mock-tailor-modal')).toBeTruthy();

    // Same record, same confirmed kind — only the truth degrades, so the
    // unmount can only be attributed to the truth.
    mockHookState.current = withTarget({
      id: 'opp-1', title: 'Opp One',
      source_type: 'campus_program', record_kind: 'listing',
      target_truth: truth,
    });
    rerender(<FavoritesPage />);

    expect(screen.queryByTestId('mock-tailor-modal')).toBeNull();
  });

  it('unmounts the modal when the target disappears from the corpus', async () => {
    setProfile();
    mockHookState.current = withTarget(live());
    const { rerender } = render(<FavoritesPage />);
    fireEvent.click(screen.getByRole('button', { name: 'Tailor Opp One' }));
    expect(await screen.findByTestId('mock-tailor-modal')).toBeTruthy();

    mockHookState.current = withTarget(null);
    rerender(<FavoritesPage />);

    expect(screen.queryByTestId('mock-tailor-modal')).toBeNull();
  });
});
