/*
 * Roadmap page error-state tests. Before this fix the catch swallowed
 * API failures and the page fell into the misleading "all set" /
 * empty-CTA branches; these tests pin the distinct error card + retry.
 */

import { afterEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';

const mockGetFavorites = vi.fn();
const mockGetRoadmap = vi.fn();

// The page resets and re-requests synchronously inside the auth callback on a
// real uid change; tests drive that through this captured callback.
let authCallback: ((state: { user: { id: string } | null }) => void) | null = null;
vi.mock('@/lib/supabase', () => ({
  getFavorites: () => mockGetFavorites(),
  onAuthChange: (cb: (state: { user: { id: string } | null }) => void) => {
    authCallback = cb;
    return () => { authCallback = null; };
  },
}));

vi.mock('@/lib/api', () => ({
  getRoadmap: (...args: unknown[]) => mockGetRoadmap(...args),
}));

// Stable reference, like the real hook (useSyncExternalStore caches the
// parse) — a fresh object per render would re-fire the load effect forever.
const PROFILE = { college: 'Grainger', major: 'ECE', grade: 'Freshman' };
vi.mock('@/lib/use-local-storage-json', () => ({
  useLocalStorageJSON: () => PROFILE,
}));

vi.mock('next/navigation', () => ({
  useRouter: () => ({ back: vi.fn(), push: vi.fn(), replace: vi.fn() }),
}));

vi.mock('@/i18n/client', () => ({
  useT: () => ({ t: (key: string) => key }),
}));

import RoadmapPage from './page';

const ROADMAP = {
  skills: [
    {
      skill: 'PyTorch',
      needed_by: 2,
      priority: 'high',
      estimated_time: '4 weeks',
      courses: ['ECE 449'],
      course_catalog: 'uiuc' as const,
    },
  ],
  total_labs: 3,
  requested_targets: 3,
  resolved_targets: 3,
  unresolved_targets: 0,
  inactive_targets: 0,
  unverified_targets: 0,
  targets_with_skill_evidence: 3,
  targets_without_skill_evidence: 0,
};

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe('RoadmapPage — an identity switch clears the roadmap in the transition itself', () => {
  it('U1\'s roadmap leaves the screen inside the auth callback and U2\'s is requested afresh', async () => {
    // Before: `data` was never cleared on a switch. The effect re-ran for the
    // new owner's profile but left U1's skills on screen for U2 until the
    // round-trip finished — a passive refetch, not a clear.
    mockGetFavorites.mockResolvedValue(new Set(['opp-1']));
    mockGetRoadmap.mockResolvedValue(ROADMAP);
    render(<RoadmapPage />);
    await waitFor(() => expect(screen.getByText('PyTorch')).toBeInTheDocument());
    act(() => authCallback?.({ user: { id: 'u1' } }));

    act(() => authCallback?.({ user: { id: 'u2' } }));

    expect(screen.queryByText('PyTorch')).toBeNull();
    await waitFor(() => expect(mockGetRoadmap).toHaveBeenCalledTimes(2));
  });
});

describe('RoadmapPage — error state', () => {
  it('shows the error card (not the all-set state) when getRoadmap fails', async () => {
    mockGetFavorites.mockResolvedValue(new Set(['opp-1']));
    mockGetRoadmap.mockRejectedValue(new Error('500'));

    render(<RoadmapPage />);

    await waitFor(() => {
      expect(screen.getByText('roadmap.errorTitle')).toBeInTheDocument();
    });
    expect(screen.queryByText('roadmap.allSetTitle')).toBeNull();
    expect(screen.queryByText('roadmap.needFavoritesTitle')).toBeNull();
  });

  it('shows the error card when getFavorites itself fails', async () => {
    mockGetFavorites.mockRejectedValue(new Error('network'));

    render(<RoadmapPage />);

    await waitFor(() => {
      expect(screen.getByText('roadmap.errorTitle')).toBeInTheDocument();
    });
    expect(mockGetRoadmap).not.toHaveBeenCalled();
  });

  it('retry button re-runs the load and renders the roadmap on success', async () => {
    mockGetFavorites.mockResolvedValue(new Set(['opp-1']));
    mockGetRoadmap
      .mockRejectedValueOnce(new Error('500'))
      .mockResolvedValueOnce(ROADMAP);

    render(<RoadmapPage />);

    await waitFor(() => {
      expect(screen.getByText('roadmap.errorTitle')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole('button', { name: 'roadmap.errorRetry' }));

    await waitFor(() => {
      expect(screen.getByText('PyTorch')).toBeInTheDocument();
    });
    expect(screen.queryByText('roadmap.errorTitle')).toBeNull();
    expect(mockGetRoadmap).toHaveBeenCalledTimes(2);
  });
});

describe('RoadmapPage — evidence semantics', () => {
  it('says "insufficient evidence" instead of "already competitive" when no target lists skills', async () => {
    mockGetFavorites.mockResolvedValue(new Set(['opp-1', 'opp-2']));
    mockGetRoadmap.mockResolvedValue({
      ...ROADMAP,
      skills: [],
      total_labs: 2,
      requested_targets: 2,
      resolved_targets: 2,
      targets_with_skill_evidence: 0,
      targets_without_skill_evidence: 2,
    });

    render(<RoadmapPage />);

    await waitFor(() => {
      expect(screen.getByText('roadmap.noSkillEvidenceTitle')).toBeInTheDocument();
    });
    expect(screen.queryByText('roadmap.allSetTitle')).toBeNull();
  });

  it('keeps the all-set claim only when every resolved target published skill evidence', async () => {
    mockGetFavorites.mockResolvedValue(new Set(['opp-1']));
    mockGetRoadmap.mockResolvedValue({
      ...ROADMAP,
      skills: [],
      total_labs: 1,
      requested_targets: 1,
      resolved_targets: 1,
      targets_with_skill_evidence: 1,
      targets_without_skill_evidence: 0,
    });

    render(<RoadmapPage />);

    await waitFor(() => {
      expect(screen.getByText('roadmap.allSetTitle')).toBeInTheDocument();
    });
  });

  it('downgrades an empty gap list to "covered where evidence exists" when some targets list nothing', async () => {
    mockGetFavorites.mockResolvedValue(new Set(['opp-1', 'opp-2']));
    mockGetRoadmap.mockResolvedValue({
      ...ROADMAP,
      skills: [],
      total_labs: 2,
      requested_targets: 2,
      resolved_targets: 2,
      targets_with_skill_evidence: 1,
      targets_without_skill_evidence: 1,
    });

    render(<RoadmapPage />);

    await waitFor(() => {
      expect(screen.getByText('roadmap.evidenceCoveredTitle')).toBeInTheDocument();
    });
    expect(screen.getByText('roadmap.skillEvidenceIncompleteTitle')).toBeInTheDocument();
    expect(screen.queryByText('roadmap.allSetTitle')).toBeNull();
  });

  it('reports excluded inactive/unverified targets and stale ids instead of claiming all set', async () => {
    mockGetFavorites.mockResolvedValue(new Set(['gone', 'inactive', 'unverified']));
    mockGetRoadmap.mockResolvedValue({
      ...ROADMAP,
      skills: [],
      total_labs: 0,
      requested_targets: 3,
      resolved_targets: 0,
      unresolved_targets: 1,
      inactive_targets: 1,
      unverified_targets: 1,
      targets_with_skill_evidence: 0,
      targets_without_skill_evidence: 0,
    });

    render(<RoadmapPage />);

    await waitFor(() => {
      expect(screen.getByText('roadmap.noCurrentTargetsTitle')).toBeInTheDocument();
    });
    expect(screen.getByText('roadmap.activityExcludedTitle')).toBeInTheDocument();
    expect(screen.queryByText('roadmap.allSetTitle')).toBeNull();
  });

  it('shows the partial-resolution notice above a real skill list', async () => {
    mockGetFavorites.mockResolvedValue(new Set(['opp-1', 'gone']));
    mockGetRoadmap.mockResolvedValue({
      ...ROADMAP,
      total_labs: 1,
      requested_targets: 2,
      resolved_targets: 1,
      unresolved_targets: 1,
      targets_with_skill_evidence: 1,
    });

    render(<RoadmapPage />);

    await waitFor(() => {
      expect(screen.getByText('PyTorch')).toBeInTheDocument();
    });
    expect(screen.getByText('roadmap.unresolvedPartialTitle')).toBeInTheDocument();
  });
});

describe('RoadmapPage — course catalog gating', () => {
  it('shows UIUC course codes only for the uiuc catalog', async () => {
    mockGetFavorites.mockResolvedValue(new Set(['opp-1']));
    mockGetRoadmap.mockResolvedValue(ROADMAP);

    render(<RoadmapPage />);

    await waitFor(() => {
      expect(screen.getByText('ECE 449')).toBeInTheDocument();
    });
    expect(screen.getByText('roadmap.uiucCoursesLabel')).toBeInTheDocument();
  });

  it('never suggests UIUC courses to a non-UIUC student (null catalog)', async () => {
    mockGetFavorites.mockResolvedValue(new Set(['opp-1']));
    mockGetRoadmap.mockResolvedValue({
      ...ROADMAP,
      skills: [{
        ...ROADMAP.skills[0],
        courses: ['ECE 449'],
        course_catalog: null,
      }],
    });

    render(<RoadmapPage />);

    await waitFor(() => {
      expect(screen.getByText('PyTorch')).toBeInTheDocument();
    });
    expect(screen.queryByText('ECE 449')).toBeNull();
    expect(screen.queryByText('roadmap.uiucCoursesLabel')).toBeNull();
  });
});
