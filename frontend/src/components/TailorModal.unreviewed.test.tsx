/**
 * A rewrite is shown only when the response says it was reviewed (criterion 1, round 1).
 *
 * The backend before w14 (main, w13.6) returns rewrites with no `status` and
 * no review. Vercel deploys fail-open while Render can hold the backend
 * (docs/RELEASE.md), so this client can meet such a backend; it refuses its
 * rules, and keeps the student's own line for any bullet not marked rewritten.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

vi.mock('@/i18n/client', () => {
  const stableT = (key: string, vars?: Record<string, string | number>) =>
    vars && Object.keys(vars).length ? `${key}:${Object.values(vars).map(String).join('|')}` : key;
  return { useT: () => ({ t: stableT, locale: 'en' as const, setLocale: () => {} }) };
});

const status = vi.hoisted(() => ({ version: 'w14.1' }));
const mockTailorResume = vi.fn();
const mockGetTailorStatus = vi.fn();
vi.mock('@/lib/api', () => ({
  tailorResume: async (...args: unknown[]) => {
    const result = await mockTailorResume(...args);
    return { opportunity_id: args[1], target_version: (args[3] as { expectedTargetVersion?: string }).expectedTargetVersion,
      pipeline_version: status.version, generated_at: '2026-10-03T00:00:00+00:00', ...result };
  },
  getTailorStatus: (...args: unknown[]) => mockGetTailorStatus(...args),
  extractResumeBullets: vi.fn(),
}));

import TailorModal from '@/components/TailorModal';
import { advanceOwnerEpoch, syncLocalIdentityOwner } from '@/lib/identity-owner';
import type { Opportunity, ProfileData, TailorResponse } from '@/lib/types';

const fullText = (s: string) => (_content: string, el: Element | null): boolean => el?.textContent === s;
const profile: ProfileData = { institution: 'UIUC', college: 'Grainger', major: 'CS', grade: 'Sophomore', is_international: false,
  research_interests: 'machine learning', skills: [{ name: 'Python', level: 'experienced' }], coursework: ['CS 225'], resume_text: '' };
const target: Opportunity = { id: 'opp-123', title: 'Some research opportunity', organization: 'UIUC', source_type: 'manual', record_kind: 'listing',
  writing_target_version: `wt1:${'a'.repeat(64)}`, opportunity_type: 'research', paid: 'unknown', location: 'Urbana', on_campus: true,
  description_clean: 'Student research', keywords: ['research'],
  eligibility: { preferred_year: [], majors: [], skills_required: [], international_friendly: 'unknown', citizenship_required: null },
  application: { application_effort: 'unknown', requires_resume: 'yes', contact_method: 'email' },
  metadata: { is_active: true, confidence_score: 1 },
  target_truth: { listing_state: 'open', accepting_state: 'accepting', actionable: true, reference_only: false,
    reason_code: null, verified_at: null, expires_at: null } };

beforeEach(async () => {
  vi.resetAllMocks();
  window.localStorage.clear();
  advanceOwnerEpoch(null); advanceOwnerEpoch('owner-1'); await syncLocalIdentityOwner('owner-1');
  status.version = 'w14.1';
  mockGetTailorStatus.mockImplementation(async () => ({ ai_available: true, pipeline_version: status.version }));
});

const unreviewed = 'Led the Python ML experiments for the CS 225 research project';
const submitted = 'Worked on Python projects in CS 225';
const open = () => render(<TailorModal isOpen onClose={vi.fn()} opportunityId="opp-123" opportunityTitle="Some research opportunity"
  target={target} ownerReady ownerScopeKey="owner-1" profile={profile} />);
const generate = () => {
  fireEvent.change(screen.getByPlaceholderText('tailor.bulletsPlaceholder'), { target: { value: submitted } });
  fireEvent.click(screen.getByRole('button', { name: /tailor\.generate/ }));
};

describe('TailorModal and an unreviewed rewrite', () => {
  it('refuses the rules of a pre-review (w13.6) backend and sends nothing', async () => {
    status.version = 'w13.6';
    open();
    await waitFor(() => expect(screen.getByText('tailor.rulesUnavailable')).toBeTruthy());
    expect(mockTailorResume).not.toHaveBeenCalled();
  });

  it('shows the submitted line for a bullet the response does not mark as rewritten', async () => {
    mockTailorResume.mockResolvedValueOnce({ method: 'ai', warnings: [],
      tailored_bullets: [{ text: unreviewed, source_evidence: 'Python; CS 225', source_index: 0 }] } satisfies TailorResponse);
    open();
    await waitFor(() => expect(mockGetTailorStatus).toHaveBeenCalled());
    generate();
    await waitFor(() => expect(mockTailorResume).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(screen.getByText('tailor.methodAi')).toBeTruthy());
    expect(screen.queryAllByText(fullText(unreviewed))).toHaveLength(0);
    expect(screen.getAllByText(fullText(submitted)).length).toBeGreaterThan(0);
  });

  it('still shows a rewrite the response marks as rewritten', async () => {
    const rewrite = 'Built Python projects in CS 225';
    mockTailorResume.mockResolvedValueOnce({ method: 'ai', warnings: [],
      tailored_bullets: [{ text: rewrite, source_evidence: submitted, source_index: 0, status: 'rewritten', reason_code: null, ops: ['verb_first'], links: [] }] } satisfies TailorResponse);
    open();
    await waitFor(() => expect(mockGetTailorStatus).toHaveBeenCalled());
    generate();
    await waitFor(() => expect(screen.getAllByText(fullText(rewrite)).length).toBeGreaterThan(0));
  });
});
