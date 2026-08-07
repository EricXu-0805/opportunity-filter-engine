/* @vitest-environment jsdom */
// Narrow integration test: proves the CALLER (OpportunityDetail) actually
// remounts TrackerPanel across an identityGeneration change, via a real
// key={`${identityGeneration}:${opp.id}`} — not just that the hook exposes
// the right number (see use-opportunity-detail.test.tsx for that). Every
// OTHER child is stubbed so this stays a narrow, fast test of the wiring,
// with the REAL TrackerPanel doing the actual mount/unmount work.
import { describe, it, expect, vi } from 'vitest';
import { useRef } from 'react';
import { render, screen, fireEvent } from '@testing-library/react';

vi.mock('@/i18n/client', () => ({
  useT: () => ({ t: (key: string) => key }),
}));

vi.mock('@/components/StorageStatusBanner', () => ({ default: () => null }));
vi.mock('./ContactRevealSection', () => ({ ContactRevealSection: () => null }));
vi.mock('./DetailSections', () => ({
  DescriptionSection: () => null,
  RecentWorksSection: () => null,
  AtAGlanceSection: () => null,
  EligibilitySection: () => null,
  ApplicationSection: () => null,
  KeywordsSection: () => null,
}));
vi.mock('./OpportunityHeader', () => ({ OpportunityHeader: () => null }));
vi.mock('./SimilarOpportunities', () => ({ SimilarOpportunities: () => null }));
vi.mock('./InteractionPills', () => ({ InteractionPills: () => null }));
vi.mock('./ChatDrawer', () => ({ ChatDrawer: () => null }));
vi.mock('./ProfessorFollowToggle', () => ({ ProfessorFollowToggle: () => null }));
// A sentinel mock, NOT the real TailorModal: the real component has its OWN
// ownerScopeKey-driven reset effect, which would clear its draft on a prop
// change alone — a test built on the real component would stay green even
// with the parent's key REMOVED, proving nothing about the key itself. This
// sentinel's mountId is generated exactly once per genuine mount (useRef's
// initializer), so it can ONLY change via an actual unmount+remount — the
// one thing a missing key would fail to cause. The real ownerReady/
// ownerScopeKey props are rendered too, so the wiring of those (separately
// from the key) stays covered.
vi.mock('@/components/TailorModal', () => ({
  default: function MockTailorModal(props: { isOpen: boolean; ownerReady: boolean; ownerScopeKey: string | null }) {
    const mountIdRef = useRef(Math.random().toString(36).slice(2));
    if (!props.isOpen) return null;
    return (
      <div data-testid="mock-tailor-modal">
        <span data-testid="mount-id">{mountIdRef.current}</span>
        <span data-testid="owner-ready">{String(props.ownerReady)}</span>
        <span data-testid="owner-scope-key">{String(props.ownerScopeKey)}</span>
      </div>
    );
  },
}));

const mockHookState = vi.hoisted(() => ({ current: null as unknown }));
vi.mock('./use-opportunity-detail', () => ({
  useOpportunityDetail: () => mockHookState.current,
}));

import OpportunityDetail from './OpportunityDetail';
import { STORAGE_KEYS } from '@/lib/storage-keys';

function baseHookResult(overrides: Record<string, unknown> = {}) {
  return {
    identityGeneration: 1,
    ownerScopeKey: 'owner-1',
    isFavorited: false,
    favoriteLoading: false,
    favoriteError: false,
    retryFavoriteHydration: () => {},
    favoriteSaving: false,
    favoriteSaveError: false,
    ownerReady: true,
    interactionDetail: { type: 'applied', notes: 'U1 notes' },
    interaction: 'applied',
    interactionLoading: false,
    interactionError: false,
    retryInteractionHydration: () => {},
    statusSaving: false,
    statusError: false,
    retryTrack: () => {},
    emailModalOpen: false,
    setEmailModalOpen: () => {},
    shareCopied: false,
    chatDrawerOpen: false,
    setChatDrawerOpen: () => {},
    tailorOpen: false,
    setTailorOpen: () => {},
    renovationOpen: false,
    setRenovationOpen: () => {},
    suggestion: null,
    suggestionSaving: false,
    suggestionError: false,
    handleStar: async () => {},
    handleTrack: async () => {},
    saveDetails: async () => ({ status: 'committed' as const }),
    handleUseSuggestion: async () => {},
    handleDismissSuggestion: () => {},
    handleShare: async () => {},
    ...overrides,
  };
}

const opp = { id: 'opp-1', title: 'Test Opportunity' } as never;

describe('OpportunityDetail — TrackerPanel is keyed by identityGeneration', () => {
  it('an identityGeneration bump (a real account switch) force-remounts TrackerPanel — an uncommitted local draft from the OLD identity never leaks into the NEW one, even when both share the same opportunity id', () => {
    mockHookState.current = baseHookResult({
      identityGeneration: 1,
      interactionDetail: { type: 'applied', notes: 'U1 notes' },
    });
    const { rerender } = render(<OpportunityDetail opp={opp} />);

    // detail.notes is truthy, so the panel starts already expanded.
    const textarea = screen.getByPlaceholderText('detail.tracker.notesPlaceholder') as HTMLTextAreaElement;
    expect(textarea.value).toBe('U1 notes');
    fireEvent.change(textarea, { target: { value: 'U1 unsaved draft, never blurred' } });
    expect(textarea.value).toBe('U1 unsaved draft, never blurred');

    // A real account switch — SAME opportunity id, but a NEW
    // identityGeneration and a different (U2's own) interactionDetail.
    mockHookState.current = baseHookResult({
      identityGeneration: 2,
      interactionDetail: { type: 'applied', notes: 'U2 notes' },
    });
    rerender(<OpportunityDetail opp={opp} />);

    const remounted = screen.getByPlaceholderText('detail.tracker.notesPlaceholder') as HTMLTextAreaElement;
    expect(remounted.value).toBe('U2 notes'); // fresh instance — U1's draft never leaked through
  });

  it('a re-render with the SAME identityGeneration does NOT remount TrackerPanel — an uncommitted draft survives an unrelated parent re-render', () => {
    mockHookState.current = baseHookResult({ identityGeneration: 1 });
    const { rerender } = render(<OpportunityDetail opp={opp} />);
    const textarea = screen.getByPlaceholderText('detail.tracker.notesPlaceholder') as HTMLTextAreaElement;
    fireEvent.change(textarea, { target: { value: 'still typing' } });

    // Same identityGeneration — some other, unrelated state changed (e.g. shareCopied).
    mockHookState.current = baseHookResult({ identityGeneration: 1, shareCopied: true });
    rerender(<OpportunityDetail opp={opp} />);

    const stillThere = screen.getByPlaceholderText('detail.tracker.notesPlaceholder') as HTMLTextAreaElement;
    expect(stillThere.value).toBe('still typing'); // NOT remounted — draft preserved
  });
});

describe('OpportunityDetail — TailorModal is keyed by identityGeneration (C1-R2B)', () => {
  it('an identityGeneration bump force-remounts TailorModal — proven via a sentinel mount-id that can ONLY change on a genuine unmount+remount, not merely on a prop change (the real component\'s own ownerScopeKey-driven internal reset would otherwise mask a missing key). tailorOpen is kept true across BOTH renders (the mock fully controls it) to isolate the key\'s OWN protection from hydrate()\'s separate setTailorOpen(false) safety net', async () => {
    window.localStorage.setItem(STORAGE_KEYS.PROFILE, JSON.stringify({
      institution: 'UIUC', major: 'CS', grade: 'Sophomore', is_international: false,
      research_interests: 'ml', skills: [],
    }));

    mockHookState.current = baseHookResult({
      identityGeneration: 1,
      ownerScopeKey: 'owner-1',
      tailorOpen: true,
    });
    const { rerender } = render(<OpportunityDetail opp={opp} />);
    // next/dynamic({ssr:false}) resolves the (mocked) module asynchronously
    // even in this test environment — findByTestId waits for it instead of
    // assuming a synchronous first paint.
    const mountId1 = (await screen.findByTestId('mount-id')).textContent;
    expect(screen.getByTestId('owner-ready').textContent).toBe('true');
    expect(screen.getByTestId('owner-scope-key').textContent).toBe('owner-1');

    // A real account switch — identityGeneration bumps, ownerScopeKey
    // changes, tailorOpen STAYS true (the mock doesn't flip it, unlike the
    // real hook's hydrate()) — isolating the key's own contribution.
    mockHookState.current = baseHookResult({
      identityGeneration: 2,
      ownerScopeKey: 'owner-2',
      tailorOpen: true,
    });
    rerender(<OpportunityDetail opp={opp} />);

    const mountId2 = screen.getByTestId('mount-id').textContent;
    expect(mountId2).not.toBe(mountId1); // genuinely torn down and recreated — a fresh instance
    expect(screen.getByTestId('owner-scope-key').textContent).toBe('owner-2'); // real props still flow through
  });

  it('a re-render with the SAME identityGeneration does NOT remount TailorModal — the sentinel\'s mount-id survives an unrelated parent re-render', async () => {
    window.localStorage.setItem(STORAGE_KEYS.PROFILE, JSON.stringify({
      institution: 'UIUC', major: 'CS', grade: 'Sophomore', is_international: false,
      research_interests: 'ml', skills: [],
    }));

    mockHookState.current = baseHookResult({ identityGeneration: 1, ownerScopeKey: 'owner-1', tailorOpen: true });
    const { rerender } = render(<OpportunityDetail opp={opp} />);
    const mountId1 = (await screen.findByTestId('mount-id')).textContent;

    mockHookState.current = baseHookResult({
      identityGeneration: 1, ownerScopeKey: 'owner-1', tailorOpen: true, shareCopied: true,
    });
    rerender(<OpportunityDetail opp={opp} />);

    const mountId2 = screen.getByTestId('mount-id').textContent;
    expect(mountId2).toBe(mountId1); // NOT remounted — same instance throughout
  });
});
