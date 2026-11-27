import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { translate } from '@/i18n/translate';

const i18n = vi.hoisted(() => ({ locale: 'en' as 'en' | 'zh' }));

// The real dictionaries: these tests are about the words a student reads.
vi.mock('@/i18n/client', () => ({
  useT: () => ({
    locale: i18n.locale,
    t: (key: string, vars?: Record<string, string | number>) => translate(i18n.locale, key, vars),
  }),
}));

vi.mock('@/lib/api', () => ({
  getGapAnalysis: vi.fn(),
  getResponsivenessSignals: vi.fn().mockResolvedValue({}),
}));

import MatchCard from './MatchCard';
import type { MatchResult, Opportunity } from '@/lib/types';

const OPEN = {
  listing_state: 'open', reference_only: false, actionable: true,
  accepting_state: 'accepting', reason_code: null, verified_at: null, expires_at: null,
} as const;
const CLOSED = {
  listing_state: 'closed', reference_only: false, actionable: false,
  accepting_state: 'not_accepting', reason_code: 'listing_closed', verified_at: null, expires_at: null,
} as const;

// What the ranker returns for every faculty profile (_decision_unknowns).
const FACULTY_SIX = [
  'opportunity.preferred_year', 'opportunity.majors', 'opportunity.paid',
  'opportunity.application_effort', 'opportunity.on_campus', 'opportunity.deadline',
];
// Every field the ranker can name, and one this build does not know.
const EVERY_FIELD = [
  'profile.year', 'profile.major', 'opportunity.preferred_year', 'opportunity.majors',
  'opportunity.resume_required', 'opportunity.international_friendly', 'opportunity.paid',
  'opportunity.application_effort', 'opportunity.on_campus', 'opportunity.deadline',
  'profile.gpa', 'future.field',
];

const HEADING = { en: 'What to verify', zh: '需要核实的条件' };
const POSTING_TERMS = {
  en: ['Eligible class years', 'Eligible majors', 'Whether a resume is required', 'Compensation',
    'Application effort', 'Whether the work is on campus', 'Application deadline'],
  zh: ['可申请的年级', '可申请的专业', '是否要求提交简历', '报酬', '申请所需投入', '是否需要到校', '申请截止日期'],
};
const ABOUT_THE_STUDENT = {
  en: ['Your class year', 'Your major', 'Eligibility for international students',
    'Whether your GPA meets the listed minimum', 'Other unconfirmed conditions'],
  zh: ['你的年级', '你的专业', '国际学生申请资格', '你的 GPA 是否达到所列最低要求', '其他尚待核实的条件'],
};

function card(opportunity: Partial<Opportunity>, unknowns: string[]): MatchResult {
  return {
    opportunity_id: 'opp-1', eligibility_score: 0.9, readiness_score: 0.8, upside_score: 0.7,
    final_score: 85, bucket: 'high_priority', reasons_fit: [], reasons_gap: [], next_steps: [], unknowns,
    opportunity: {
      id: 'opp-1', title: 'Pat Lee', organization: 'Example University', target_truth: { ...OPEN },
      opportunity_type: 'Research', paid: 'unknown', location: 'Urbana, IL', on_campus: true,
      description_clean: 'Research on soil sensors.', keywords: ['soil sensors'],
      eligibility: { international_friendly: 'unknown', preferred_year: [], majors: [], skills_required: [],
        citizenship_required: false },
      application: { contact_method: 'email' },
      metadata: { is_active: true, confidence_score: 0.9 },
      ...opportunity,
    } as Opportunity,
  };
}

/** The heading and entries of the card's verify block, or null when the card has none. */
function verifyBlock(match: MatchResult): string[] | null {
  const { unmount } = render(<MatchCard match={match} onDraftEmail={() => {}} />);
  fireEvent.click(screen.getByText(translate(i18n.locale, 'card.showDetails')));
  const heading = screen.queryByText(HEADING[i18n.locale]);
  const items = heading && Array.from(heading.closest('details')!.querySelectorAll('li'), li => li.textContent ?? '');
  unmount();
  return items;
}

const NOT_A_CURRENT_LISTING: Array<[string, Partial<Opportunity>]> = [
  ['a faculty profile', { source_type: 'faculty_research' }],
  ['a closed listing', { source_type: 'campus_program', target_truth: { ...CLOSED } }],
  ['a record of a kind nobody reviewed', { source_type: 'kind_added_later' }],
];

beforeEach(() => {
  i18n.locale = 'en';
});

describe.each(['en', 'zh'] as const)('what a card asks the student to verify (%s)', (locale) => {
  beforeEach(() => {
    i18n.locale = locale;
  });

  it.each(NOT_A_CURRENT_LISTING)('asks nothing about a posting on %s', (_name, opportunity) => {
    expect(verifyBlock(card(opportunity, FACULTY_SIX))).toBeNull();
    expect(verifyBlock(card(opportunity, [...FACULTY_SIX, 'opportunity.resume_required']))).toBeNull();
  });

  it.each(NOT_A_CURRENT_LISTING)('keeps what is about the student on %s', (_name, opportunity) => {
    expect(verifyBlock(card(opportunity, EVERY_FIELD))).toEqual(ABOUT_THE_STUDENT[locale]);
  });

  it('keeps every entry on a current listing', () => {
    const [year, major, intl, gpa, other] = ABOUT_THE_STUDENT[locale];
    const [years, majors, resume, ...rest] = POSTING_TERMS[locale];
    expect(verifyBlock(card({ source_type: 'campus_program' }, EVERY_FIELD))).toEqual(
      [year, major, years, majors, resume, intl, ...rest, gpa, other],
    );
  });
});
