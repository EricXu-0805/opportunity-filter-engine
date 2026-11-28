import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { render, screen, within } from '@testing-library/react';
import { expect, it, vi } from 'vitest';
import { OpportunityCard } from '@/app/favorites/OpportunityCard';
import type { TFunc } from '@/app/favorites/types';
import type { MatchResult, Opportunity } from '@/lib/types';
import MatchCard from './MatchCard';

vi.mock('@/i18n/client', () => ({ useT: () => ({ t: (key: string) => key, locale: 'en' }) }));

const roster = 'https://neuroscience.jhu.edu/research/faculty';
type FacultyRow = Opportunity & {
  metadata: { faculty_title_observation?: { source: string; profile: string } };
};
const records: FacultyRow[] = JSON.parse(readFileSync(resolve('../data/processed/shards/jhu.json'), 'utf8'));
const observed = records.filter(row => row.metadata?.faculty_title_observation?.source === roster);
const controls = [
  ['faculty-jhu-som-893e6408', 'https://profiles.hopkinsmedicine.org/provider/jeremy-nathans/2777740'],
  ['faculty-jhu-bsph-3ec22da2', 'https://publichealth.jhu.edu/faculty/4790/seth-blackshaw'],
];
const noop = () => {};
const t = ((key: string) => key) as TFunc;

it('has source-backed JHU neuroscience appointments to render', () => {
  expect(observed.length).toBeGreaterThan(0);
});

it.each([
  ...observed.map(row => [row.id, row.metadata.faculty_title_observation!.profile]),
  ...controls,
])('opens the original person from both match and saved cards for %s', (id, person) => {
  const row = records.find(record => record.id === id)!;
  // The server's answer for a row whose stored link is the person's own page.
  const faculty_page = { kind: 'profile' as const, url: row.source_url || row.url! };
  const opportunity: Opportunity = { ...row, record_kind: 'faculty_contact', faculty_page };
  const match: MatchResult = {
    opportunity_id: id, opportunity, eligibility_score: 0.9, readiness_score: 0.8, upside_score: 0.7,
    final_score: 85, bucket: 'high_priority', reasons_fit: [], reasons_gap: [], next_steps: [],
  };
  render(<>
    <div data-testid="match"><MatchCard match={match} onDraftEmail={noop} /></div>
    <div data-testid="saved"><OpportunityCard
      opp={{ id, title: row.title, source_type: row.source_type, source: row.source,
        source_url: row.source_url, url: row.url, faculty_page }}
      selectionMode={false} isSelected={false} selectedSize={0} isExpanded hasProfile={false}
      onToggleExpand={noop} onToggleSelect={noop} onRemove={noop} onOpenEmailModal={noop}
      tailorDisabled={false} t={t}
    /></div>
  </>);
  for (const surface of ['match', 'saved']) {
    expect(within(screen.getByTestId(surface)).getByRole('link', { name: 'card.viewFacultyPage' }))
      .toHaveAttribute('href', person);
  }
});
