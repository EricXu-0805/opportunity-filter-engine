import { afterEach, describe, expect, it } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import type { Opportunity } from '@/lib/types';
import BucketCards from './BucketCards';
import type { CompareRow } from './scores';

const FACTORS = {
  skill_match: 5,
  eligibility: 6,
  ease: 7,
  compensation: 8,
  deadline_runway: 9,
  intl_friendly: 10,
};

export const ACTIONABLE_TRUTH = {
  listing_state: 'open',
  reference_only: false,
  actionable: true,
  accepting_state: 'accepting',
  reason_code: null,
  verified_at: null,
  expires_at: null,
} as const;

function readyRow(): CompareRow {
  return {
    // A live truth, because a comparison card only makes its claims about a
    // target the server still vouches for. Without one the default row is
    // `unknown` and every assertion below would be reading the degraded card.
    opp: {
      id: 'opp-1', title: 'ML Lab RA', organization: 'Test U',
      // A reviewed source type: an unreviewed one is no longer actionable, so
      // the default row would otherwise be the degraded reference card.
      source_type: 'campus_program',
      target_truth: { ...ACTIONABLE_TRUTH },
    } as Opportunity,
    inputIndex: 0,
    status: 'ready',
    factors: FACTORS,
    match: {
      explanation: 'Great topical fit.',
      method: 'llm',
      final_score: 82,
      bucket: 'good_match',
      reasons_fit: ['Canonical strong ML background'],
      reasons_gap: ['Canonical coursework gap'],
      matcher_version: 'test-matcher-v1',
    },
  };
}

afterEach(cleanup);

describe('BucketCards — canonical match truth', () => {
  it('uses canonical score, bucket, and reasons without substituting local factor estimates', () => {
    render(<BucketCards rows={[readyRow()]} />);

    expect(screen.getByText('82%')).toBeInTheDocument();
    expect(screen.getByText('Good match')).toBeInTheDocument();
    expect(screen.getByText('Canonical strong ML background')).toBeInTheDocument();
    expect(screen.getByText('Canonical coursework gap')).toBeInTheDocument();
    expect(screen.getByText('AI-adjusted')).toBeInTheDocument();
    expect(screen.queryByText('7%')).not.toBeInTheDocument();
  });

  it('states that the remaining decision factors are estimates when canonical explanation fails', () => {
    const failed: CompareRow = {
      ...readyRow(),
      status: 'error',
      match: null,
    };
    render(<BucketCards rows={[failed]} />);

    expect(screen.getByText(/Match score unavailable/i)).toBeInTheDocument();
    expect(screen.getByText(/radar below still shows estimated decision factors/i)).toBeInTheDocument();
    expect(screen.queryByText(/\d+%/)).not.toBeInTheDocument();
  });

  it('does not label a professor profile link as an application form', () => {
    const faculty = readyRow();
    faculty.opp = {
      ...faculty.opp,
      id: 'faculty-stanford-ee-123',
      source_type: 'faculty_research',
      url: 'https://faculty.example.edu/real-profile',
      application: { application_url: 'https://fake.example.edu/apply' },
    } as Opportunity;

    render(<BucketCards rows={[faculty]} />);

    expect(screen.getByRole('link', { name: /View faculty profile/ })).toHaveAttribute(
      'href',
      'https://faculty.example.edu/real-profile',
    );
    expect(screen.queryByRole('link', { name: /^Apply$/ })).toBeNull();
  });

  it.each([
    [true, 'estimated'],
    [null, 'verify date'],
    [undefined, 'verify date'],
  ] as const)(
    'keeps deadline precision %s visible as %s',
    (deadlineIsEstimate, expectedLabel) => {
      const row = readyRow();
      row.opp = {
        ...row.opp,
        deadline: '2026-08-01',
        deadline_is_estimate: deadlineIsEstimate,
      } as Opportunity;

      render(<BucketCards rows={[row]} />);

      expect(screen.getByText(new RegExp(expectedLabel))).toBeInTheDocument();
    },
  );

  it('shows a confirmed deadline without an estimate warning', () => {
    const row = readyRow();
    row.opp = {
      ...row.opp,
      deadline: '2026-08-01',
      deadline_is_estimate: false,
    } as Opportunity;

    render(<BucketCards rows={[row]} />);

    expect(screen.getByText(/2026-08-01/)).toBeInTheDocument();
    expect(screen.queryByText(/estimated|verify date/)).toBeNull();
  });

  it('does not claim "Rolling" from the blanket is_rolling default alone', () => {
    const row = readyRow();
    row.opp = { ...row.opp, is_rolling: true } as Opportunity;

    render(<BucketCards rows={[row]} />);

    expect(screen.getByText(/No fixed deadline/)).toBeInTheDocument();
    expect(screen.queryByText(/Rolling/)).toBeNull();
  });

  it('claims "Rolling" only with scraped rolling evidence', () => {
    const row = readyRow();
    row.opp = {
      ...row.opp,
      is_rolling: true,
      metadata: { is_active: true, confidence_score: 0.9, deadline_note: 'Rolling admissions' },
    } as Opportunity;

    render(<BucketCards rows={[row]} />);

    expect(screen.getByText(/Rolling/)).toBeInTheDocument();
    expect(screen.queryByText(/No fixed deadline/)).toBeNull();
  });

  it('a listed date wins over the is_rolling flag', () => {
    const row = readyRow();
    row.opp = {
      ...row.opp,
      is_rolling: true,
      deadline: '2026-08-01',
      deadline_is_estimate: false,
    } as Opportunity;

    render(<BucketCards rows={[row]} />);

    expect(screen.getByText(/2026-08-01/)).toBeInTheDocument();
    expect(screen.queryByText(/Rolling|No fixed deadline/)).toBeNull();
  });

  it('hides a poisoned faculty deadline and rolling claim', () => {
    const row = readyRow();
    row.opp = {
      ...row.opp,
      source_type: 'faculty_research',
      deadline: '2099-12-31',
      deadline_is_estimate: false,
      is_rolling: true,
      metadata: {
        is_active: true,
        confidence_score: 0.9,
        deadline_note: 'Rolling admissions',
      },
    } as Opportunity;

    render(<BucketCards rows={[row]} />);

    expect(screen.getByText(/Current opening and deadline not confirmed/)).toBeInTheDocument();
    expect(screen.queryByText(/2099-12-31/)).toBeNull();
    expect(screen.queryByText(/Rolling/)).toBeNull();
  });
});

describe('BucketCards degrades a dead target on its own', () => {
  // Defence in depth. CompareTable already partitions, so in the current wiring
  // a dead row cannot arrive here — which is exactly why this layer is easy to
  // remove by accident. This component is exported, rendered directly, and one
  // refactor away from being handed the full list again; everything it renders
  // (a percentage, bars, strengths, concerns, an AI paragraph, an Apply
  // button) is a claim that only holds for a live target.
  function deadRow(truth: unknown): CompareRow {
    const row = readyRow();
    const opp = {
      ...row.opp,
      // The kind the reason belongs on. `faculty_not_accepting` quotes a
      // named person, so only a `faculty_research` row can carry it; on the
      // default listing the payload is unreadable and this block would be
      // asserting the generic banner while claiming to test the quotation.
      ...((truth as { reason_code?: string } | null)?.reason_code === 'faculty_not_accepting'
        ? { source_type: 'faculty_research' }
        : {}),
      source_url: 'https://example.edu/source-page',
      url: 'https://example.edu/display-page',
      application: { application_url: 'https://example.edu/apply-here' },
      deadline: '2099-12-31',
      deadline_is_estimate: false,
      paid: 'yes',
      target_truth: truth,
    } as unknown as Opportunity;
    if (truth === undefined) {
      delete (opp as unknown as Record<string, unknown>).target_truth;
    }
    row.opp = opp;
    return row;
  }

  const REASONS: [string, unknown, string][] = [
    ['closed', {
      ...ACTIONABLE_TRUTH, actionable: false, listing_state: 'closed',
      accepting_state: 'not_accepting', reason_code: 'listing_closed',
      reference_only: true,
    }, 'Closed — no longer accepting applications'],
    ['reference-only', {
      ...ACTIONABLE_TRUTH, actionable: false, listing_state: 'unknown',
      accepting_state: 'unknown', reason_code: 'reference_only', reference_only: true,
    }, 'Reference record — not an open listing'],
    ['inactive', {
      ...ACTIONABLE_TRUTH, actionable: false, listing_state: 'unknown',
      accepting_state: 'unknown', reason_code: 'inactive',
    }, 'Inactive — no longer carried in the catalog'],
    ['faculty-stop', {
      ...ACTIONABLE_TRUTH, actionable: false, listing_state: 'unknown',
      accepting_state: 'not_accepting', reason_code: 'faculty_not_accepting',
    }, 'Source profile states this faculty member is not currently accepting undergraduate students'],
    ['missing', undefined, 'Status unconfirmed — check the source'],
    ['null', null, 'Status unconfirmed — check the source'],
    ['malformed', { listing_state: 'open' }, 'Status unconfirmed — check the source'],
    [
      'self-contradicting',
      { ...ACTIONABLE_TRUTH, listing_state: 'closed' },
      'Status unconfirmed — check the source',
    ],
  ];

  it.each(REASONS)('renders %s as reference-only with its own words', (_label, truth, status) => {
    render(<BucketCards rows={[deadRow(truth)]} />);

    const card = screen.getByTestId('compare-reference-card');
    expect(card).toHaveTextContent('ML Lab RA');
    expect(card).toHaveTextContent(status);

    // A canonical match object is still attached to the row — the guard has to
    // win over it, not merely cope with its absence.
    expect(screen.queryByText('82%')).toBeNull();
    expect(screen.queryByText('Good match')).toBeNull();
    expect(screen.queryByText('Canonical strong ML background')).toBeNull();
    expect(screen.queryByText('Canonical coursework gap')).toBeNull();
    expect(screen.queryByText('Great topical fit.')).toBeNull();
    expect(screen.queryByText(/2099-12-31/)).toBeNull();
    expect(screen.queryByLabelText(/% match/)).toBeNull();

    // Source link only — never the application URL, under any label.
    const links = Array.from(card.querySelectorAll('a')).map((a) => a.getAttribute('href'));
    expect(links).toContain('https://example.edu/source-page');
    expect(links).not.toContain('https://example.edu/apply-here');
    expect(links).not.toContain('https://example.edu/display-page');
  });

  it('never blurs four reasons into one label', async () => {
    // The failure this guards is silent: every card renders, every one says
    // something plausible, and all four say the same wrong thing.
    const { dictionaries } = await import('@/i18n/dictionaries');
    for (const locale of ['en', 'zh'] as const) {
      const status = dictionaries[locale].compare.status;
      const values = Object.values(status);
      expect(new Set(values).size).toBe(values.length);
    }
  });

  it('does not claim every excluded target was reported closed by its source', async () => {
    // `status_unverified` means we could not read the truth at all, and
    // `inactive` is our catalog's own judgement. Neither is something a
    // source published, so the section copy must not say it was.
    const { dictionaries } = await import('@/i18n/dictionaries');
    for (const locale of ['en', 'zh'] as const) {
      const body = dictionaries[locale].compare.referenceOnlyBody;
      expect(body).not.toMatch(/source reported|来源页的说法/);
      expect(body).not.toMatch(/no longer open|已经不再开放/);
    }
  });

  it('still renders a live row normally beside a dead one', () => {
    // The gate is per row, not per list: one dead target must not blank the
    // comparison the student actually asked for.
    render(<BucketCards rows={[readyRow(), deadRow(REASONS[0][1])]} />);

    expect(screen.getByText('82%')).toBeInTheDocument();
    expect(screen.getAllByTestId('compare-reference-card')).toHaveLength(1);
  });
});
