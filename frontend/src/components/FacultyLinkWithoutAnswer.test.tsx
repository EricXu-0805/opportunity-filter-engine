import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import BucketCards from '@/app/compare/BucketCards';
import type { CompareRow } from '@/app/compare/scores';
import { OpportunityCard } from '@/app/favorites/OpportunityCard';
import { OpportunityHeader } from '@/app/opportunities/[id]/OpportunityHeader';
import { LanguageProvider } from '@/i18n/client';
import { translate } from '@/i18n/translate';
import type { MatchResult, Opportunity } from '@/lib/types';
import MatchCard from './MatchCard';

vi.mock('next/navigation', () => ({ useRouter: () => ({ refresh: vi.fn() }) }));

// The site and the API deploy separately, minutes to an hour apart. Until the
// API sends `faculty_page`, a professor row arrives as it does below, and
// every surface must read as it did before the field existed.
const TRUTH = {
  listing_state: 'unknown', reference_only: false, actionable: true, accepting_state: 'unknown',
  reason_code: null, verified_at: null, expires_at: null,
} as const;
const person = 'https://chem.example.edu/people/ada-example';
const roster = 'https://www.philosophy.pitt.edu/people';
const professor = (source: string, url: string) => ({
  id: 'faculty-example-chem-00000001', title: 'Ada Example', organization: 'Example University',
  pi_name: 'Ada Example', source, source_type: 'faculty_research', record_kind: 'faculty_contact',
  target_truth: { ...TRUTH }, metadata: { is_active: true }, url,
});
// A match card carries the shown link only; the other payloads cite the page that was read as well.
const full = (row: ReturnType<typeof professor>) => ({ ...row, source_url: row.url }) as unknown as Opportunity;
const noop = () => {};

const SURFACES = {
  'match card': (row: ReturnType<typeof professor>) => {
    const match = {
      opportunity_id: row.id, opportunity: row as unknown as Opportunity, eligibility_score: 0.9,
      readiness_score: 0.8, upside_score: 0.7, final_score: 85, bucket: 'high_priority',
      reasons_fit: [], reasons_gap: [], next_steps: [],
    } as MatchResult;
    return <MatchCard match={match} onDraftEmail={noop} />;
  },
  'detail header': (row: ReturnType<typeof professor>, locale: 'en' | 'zh') => (
    <OpportunityHeader
      opp={full(row)} profile={null} isFavorited={false} favoriteDisabled={false} favoriteBusy={false}
      shareCopied={false} onStar={noop} onOpenEmailModal={noop} onOpenTailorModal={noop} tailorDisabled={false}
      onOpenRenovationModal={undefined} onShare={noop} t={(key) => translate(locale, key)}
    />
  ),
  'favorites card': (row: ReturnType<typeof professor>, locale: 'en' | 'zh') => (
    <OpportunityCard
      opp={full(row) as never} selectionMode={false} isSelected={false} selectedSize={0} isExpanded hasProfile
      onToggleExpand={noop} onToggleSelect={noop} onRemove={noop} onOpenEmailModal={noop}
      onOpenTailorModal={noop} tailorDisabled={false} t={(key, vars) => translate(locale, key, vars)}
    />
  ),
  'compare card': (row: ReturnType<typeof professor>) => {
    const compared: CompareRow = {
      opp: full(row), inputIndex: 0, status: 'ready',
      factors: { skill_match: 5, eligibility: 6, ease: 7, compensation: 8, deadline_runway: 9, intl_friendly: 10 },
      match: {
        explanation: '', method: 'llm', final_score: 82, bucket: 'good_match', reasons_fit: [], reasons_gap: [],
        matcher_version: 'test-matcher-v1',
      },
    };
    return <BucketCards rows={[compared]} />;
  },
};
type Surface = keyof typeof SURFACES;

// [surface, the label for the person's page, the label for a page that is only cited] as the merge base showed them.
const WORDS: Record<'en' | 'zh', [Surface, string, string | null][]> = {
  en: [
    ['match card', 'Faculty page', null],
    ['detail header', 'View faculty profile', 'View source'],
    ['favorites card', 'Faculty page', 'View the source page'],
    ['compare card', 'View faculty profile', 'View source'],
  ],
  zh: [
    ['match card', '教师主页', null],
    ['detail header', '查看教师主页', '查看来源页'],
    ['favorites card', '教师主页', '查看来源页'],
    ['compare card', '查看教师主页', '查看来源'],
  ],
};
const DIRECTORY = /department directory|院系教师名录/i;

afterEach(cleanup);

describe.each(['en', 'zh'] as const)('a professor row from an API that does not send faculty_page (%s)', (locale) => {
  const show = (surface: Surface, row: ReturnType<typeof professor>) => render(
    <LanguageProvider initialLocale={locale}>{SURFACES[surface](row, locale)}</LanguageProvider>,
  );

  it.each(WORDS[locale])('%s: the link is still offered as "%s"', (surface, profileLabel) => {
    show(surface, professor('example_faculty', person));
    expect(screen.getByRole('link', { name: profileLabel })).toHaveAttribute('href', person);
    expect(screen.queryByRole('link', { name: DIRECTORY })).toBeNull();
  });

  it.each(WORDS[locale])('%s: a roster the old rules knew is still not the person’s page', (surface, profileLabel, sourceLabel) => {
    show(surface, professor('pitt_faculty', roster));
    expect(screen.queryByRole('link', { name: profileLabel })).toBeNull();
    expect(screen.queryByRole('link', { name: DIRECTORY })).toBeNull();
    if (sourceLabel) expect(screen.getByRole('link', { name: sourceLabel })).toHaveAttribute('href', roster);
    else expect(document.querySelector(`a[href="${roster}"]`)).toBeNull();
  });
});
