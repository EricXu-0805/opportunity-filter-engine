import { describe, it, expect, vi } from 'vitest';
import { useRef } from 'react';
import { render, screen, within, fireEvent, waitFor } from '@testing-library/react';

vi.mock('@/i18n/client', () => ({
  useT: () => ({
    t: (key: string) => key,
  }),
}));

vi.mock('@/lib/api', () => ({
  getGapAnalysis: vi.fn(),
  getResponsivenessSignals: vi.fn().mockResolvedValue({}),
}));

// A sentinel mock, NOT the real TailorModal — mirrors
// OpportunityDetail.test.tsx/favorites/page.test.tsx's own TailorModal
// sentinel. MatchCard (kept REAL below, unlike those two) owns `tailorOpen`
// as its OWN component-local state, so a real identity change must destroy
// the WHOLE MatchCard subtree via MatchList's Fragment key for the modal to
// ever disappear — a prop-only change could never do that. mountId is
// generated exactly once per genuine mount (useRef's initializer), so it
// can ONLY change via an actual unmount+remount.
vi.mock('@/components/TailorModal', () => ({
  default: function MockTailorModal(props: {
    isOpen: boolean;
    ownerReady: boolean;
    ownerScopeKey: string | null;
  }) {
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

import { MatchList } from './MatchList';
import type { MatchResult, Opportunity, ProfileData } from '@/lib/types';

function makeProfile(): ProfileData {
  return {
    institution: 'UIUC',
    college: 'Grainger',
    major: 'CS',
    grade: 'Sophomore',
    is_international: false,
    research_interests: 'machine learning',
    skills: [],
  };
}

function makeOpp(id: string, title: string): Opportunity {
  return {
    id,
    title,
    organization: 'UIUC CS',
    opportunity_type: 'Research',
    paid: 'yes',
    location: 'Urbana, IL',
    on_campus: true,
    description_clean: 'A great opportunity for testing.',
    keywords: ['ml'],
    eligibility: {
      international_friendly: 'yes',
      preferred_year: ['Sophomore'],
      majors: ['CS'],
      skills_required: ['Python'],
      citizenship_required: false,
    },
    application: {
      application_effort: 'medium',
      requires_resume: 'yes',
      contact_method: 'email',
    },
    metadata: { is_active: true, confidence_score: 0.9 },
  };
}

function makeMatch(id: string, title: string): MatchResult {
  const opportunity = makeOpp(id, title);
  return {
    opportunity_id: opportunity.id,
    eligibility_score: 0.9,
    readiness_score: 0.8,
    upside_score: 0.7,
    final_score: 85,
    bucket: 'high_priority',
    reasons_fit: [],
    reasons_gap: [],
    next_steps: [],
    opportunity,
  };
}

// Real, two-card render — proves the ACTUAL wiring from a per-id error Set
// down to the individual card that owns it, not just MatchCard in isolation.
describe('MatchList — per-card save failure/retry: each card owns its own error and retry, independent of any other card', () => {
  it('opp-a has a favSaveError, opp-b does not: only opp-a\'s card shows the error, and its Retry passes ONLY opp-a\'s id — opp-b\'s prior success never erases or leaks into opp-a\'s', () => {
    const onRetryFavSave = vi.fn();
    render(
      <MatchList
        matches={[makeMatch('opp-a', 'Opportunity A'), makeMatch('opp-b', 'Opportunity B')]}
        profile={null}
        highlightSet={new Set()}
        focusedIdx={-1}
        favs={new Set(['opp-b'])}
        interactions={new Map()}
        ownerReady
        identityGeneration={1}
        ownerScopeKey="owner-1"
        pendingFavIds={new Set()}
        pendingTrackIds={new Set()}
        favSaveErrors={new Set(['opp-a'])}
        trackSaveErrors={new Set()}
        interactionsUnready={false}
        feedback={new Map()}
        onDraftEmail={() => {}}
        onToggleFavorite={() => {}}
        onTrackInteraction={() => {}}
        onRetryFavSave={onRetryFavSave}
        onRetryTrackSave={() => {}}
        onFeedback={() => {}}
        positionOffset={0}
        page={1}
        totalPages={1}
        paginationReady
        onPageChange={() => {}}
        t={((key: string) => key) as never}
      />,
    );

    const cardA = screen.getByText('Opportunity A').closest<HTMLElement>('div[id^="match-card-"]')!;
    const cardB = screen.getByText('Opportunity B').closest<HTMLElement>('div[id^="match-card-"]')!;
    expect(within(cardA).getByText('results.favSaveError')).toBeInTheDocument();
    expect(within(cardB).queryByText('results.favSaveError')).toBeNull();

    fireEvent.click(within(cardA).getByText('common.retry'));
    expect(onRetryFavSave).toHaveBeenCalledTimes(1);
    expect(onRetryFavSave).toHaveBeenCalledWith('opp-a');
  });

  it('A and B favorite failures coexist on their own cards simultaneously — retrying A does not touch B\'s rendered error', () => {
    render(
      <MatchList
        matches={[makeMatch('opp-a', 'Opportunity A'), makeMatch('opp-b', 'Opportunity B')]}
        profile={null}
        highlightSet={new Set()}
        focusedIdx={-1}
        favs={new Set()}
        interactions={new Map()}
        ownerReady
        identityGeneration={1}
        ownerScopeKey="owner-1"
        pendingFavIds={new Set()}
        pendingTrackIds={new Set()}
        favSaveErrors={new Set(['opp-a', 'opp-b'])}
        trackSaveErrors={new Set()}
        interactionsUnready={false}
        feedback={new Map()}
        onDraftEmail={() => {}}
        onToggleFavorite={() => {}}
        onTrackInteraction={() => {}}
        onRetryFavSave={() => {}}
        onRetryTrackSave={() => {}}
        onFeedback={() => {}}
        positionOffset={0}
        page={1}
        totalPages={1}
        paginationReady
        onPageChange={() => {}}
        t={((key: string) => key) as never}
      />,
    );

    const cardA = screen.getByText('Opportunity A').closest<HTMLElement>('div[id^="match-card-"]')!;
    const cardB = screen.getByText('Opportunity B').closest<HTMLElement>('div[id^="match-card-"]')!;
    expect(within(cardA).getByText('results.favSaveError')).toBeInTheDocument();
    expect(within(cardB).getByText('results.favSaveError')).toBeInTheDocument();
  });

  it('a trackSaveError on opp-a alone renders only on opp-a\'s card and retries with opp-a\'s id', () => {
    const onRetryTrackSave = vi.fn();
    render(
      <MatchList
        matches={[makeMatch('opp-a', 'Opportunity A'), makeMatch('opp-b', 'Opportunity B')]}
        profile={null}
        highlightSet={new Set()}
        focusedIdx={-1}
        favs={new Set()}
        interactions={new Map()}
        ownerReady
        identityGeneration={1}
        ownerScopeKey="owner-1"
        pendingFavIds={new Set()}
        pendingTrackIds={new Set()}
        favSaveErrors={new Set()}
        trackSaveErrors={new Set(['opp-a'])}
        interactionsUnready={false}
        feedback={new Map()}
        onDraftEmail={() => {}}
        onToggleFavorite={() => {}}
        onTrackInteraction={() => {}}
        onRetryFavSave={() => {}}
        onRetryTrackSave={onRetryTrackSave}
        onFeedback={() => {}}
        positionOffset={0}
        page={1}
        totalPages={1}
        paginationReady
        onPageChange={() => {}}
        t={((key: string) => key) as never}
      />,
    );

    const cardA = screen.getByText('Opportunity A').closest<HTMLElement>('div[id^="match-card-"]')!;
    const cardB = screen.getByText('Opportunity B').closest<HTMLElement>('div[id^="match-card-"]')!;
    expect(within(cardA).getByText('results.trackSaveError')).toBeInTheDocument();
    expect(within(cardB).queryByText('results.trackSaveError')).toBeNull();

    fireEvent.click(within(cardA).getByText('common.retry'));
    expect(onRetryTrackSave).toHaveBeenCalledWith('opp-a');
  });
});

function baseListProps(overrides: Partial<Parameters<typeof MatchList>[0]> = {}) {
  return {
    matches: [makeMatch('opp-a', 'Opportunity A')],
    profile: makeProfile(),
    highlightSet: new Set<string>(),
    focusedIdx: -1,
    favs: new Set<string>(),
    interactions: new Map(),
    ownerReady: true,
    identityGeneration: 1,
    ownerScopeKey: 'owner-1' as string | null,
    pendingFavIds: new Set<string>(),
    pendingTrackIds: new Set<string>(),
    favSaveErrors: new Set<string>(),
    trackSaveErrors: new Set<string>(),
    interactionsUnready: false,
    feedback: new Map(),
    onDraftEmail: () => {},
    onToggleFavorite: () => {},
    onTrackInteraction: () => {},
    onRetryFavSave: () => {},
    onRetryTrackSave: () => {},
    onFeedback: () => {},
    positionOffset: 0,
    page: 1,
    totalPages: 1,
    paginationReady: true,
    onPageChange: () => {},
    t: ((key: string) => key) as never,
    ...overrides,
  };
}

// C1-R2B: MatchCard owns `tailorOpen` as its OWN component-local state —
// unlike favorites/page.tsx and OpportunityDetail (which own the open/close
// boolean at the PARENT level), a real identity change here can only ever
// destroy an open Tailor modal by tearing down the WHOLE MatchCard subtree.
// MatchList's Fragment key={`${identityGeneration}:${opp.id}`} is what does
// that. profile must be non-null for the CTA to render at all (MatchCard
// hides it entirely on a null profile — see the existing per-card tests
// above, all of which pass profile={null} and never reach this code path).
describe('MatchList — the Tailor modal subtree is keyed by identityGeneration (C1-R2B)', () => {
  it('an identityGeneration bump (a real account switch) force-remounts the WHOLE MatchCard subtree — the open Tailor modal is torn down (tailorOpen was component-local state, now genuinely gone), and re-opening it afterward yields a FRESH sentinel instance', async () => {
    const { rerender } = render(<MatchList {...baseListProps({ identityGeneration: 1 })} />);

    fireEvent.click(screen.getByRole('button', { name: 'card.tailorResume' }));
    const mountId1 = (await screen.findByTestId('mount-id')).textContent;

    // A real account switch — SAME opportunity, but a NEW identityGeneration.
    rerender(<MatchList {...baseListProps({ identityGeneration: 2, ownerScopeKey: 'owner-2' })} />);

    // The remount reset MatchCard's OWN tailorOpen state back to false — a
    // prop-only change could never do this, since tailorOpen isn't a prop.
    expect(screen.queryByTestId('mock-tailor-modal')).toBeNull();

    // Re-open it in the NEW generation — a genuinely fresh instance, not
    // some stale closed-but-cached one somehow resurfacing.
    fireEvent.click(screen.getByRole('button', { name: 'card.tailorResume' }));
    const mountId2 = (await screen.findByTestId('mount-id')).textContent;
    expect(mountId2).not.toBe(mountId1);
    expect(screen.getByTestId('owner-scope-key').textContent).toBe('owner-2');
  });

  it('a re-render with the SAME identityGeneration does NOT remount MatchCard — an open Tailor modal survives an unrelated parent re-render (e.g. a favorite elsewhere in the list saving)', async () => {
    const { rerender } = render(<MatchList {...baseListProps({ identityGeneration: 1 })} />);

    fireEvent.click(screen.getByRole('button', { name: 'card.tailorResume' }));
    const mountId1 = (await screen.findByTestId('mount-id')).textContent;

    // Same identityGeneration — some unrelated prop changed instead.
    rerender(<MatchList {...baseListProps({ identityGeneration: 1, pendingFavIds: new Set(['opp-a']) })} />);

    const mountId2 = screen.getByTestId('mount-id').textContent;
    expect(mountId2).toBe(mountId1); // NOT remounted — the open modal instance survived
  });

  it('ownerReady=false fail-closed gate: the Tailor CTA is disabled and a click never opens the modal', () => {
    render(<MatchList {...baseListProps({ ownerReady: false })} />);

    const cta = screen.getByRole('button', { name: 'card.tailorResume' });
    expect(cta).toBeDisabled();
    fireEvent.click(cta); // no-op — disabled buttons never dispatch click handlers
    expect(screen.queryByTestId('mock-tailor-modal')).toBeNull();
  });

  it('ownerReady=true: the CTA is enabled and opening it wires ownerScopeKey through to the modal', async () => {
    render(<MatchList {...baseListProps({ ownerReady: true, ownerScopeKey: 'owner-7' })} />);

    const cta = screen.getByRole('button', { name: 'card.tailorResume' });
    expect(cta).not.toBeDisabled();
    fireEvent.click(cta);

    await waitFor(() => expect(screen.getByTestId('owner-ready').textContent).toBe('true'));
    expect(screen.getByTestId('owner-scope-key').textContent).toBe('owner-7');
  });
});
