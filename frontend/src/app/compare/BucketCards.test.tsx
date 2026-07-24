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

function readyRow(): CompareRow {
  return {
    opp: { id: 'opp-1', title: 'ML Lab RA', organization: 'Test U' } as Opportunity,
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
      application: { application_url: 'https://faculty.example.edu/profile' },
    } as Opportunity;

    render(<BucketCards rows={[faculty]} />);

    expect(screen.getByRole('link', { name: /View faculty profile/ })).toHaveAttribute(
      'href',
      'https://faculty.example.edu/profile',
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
});
