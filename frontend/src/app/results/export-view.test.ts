import { describe, expect, it } from 'vitest';
import type { MatchViewRequestState } from '@/lib/api';
import type { MatchResult } from '@/lib/types';
import { favoriteExportView, favoriteRowsForTab } from './export-view';

const view: MatchViewRequestState = {
  tab: 'high_priority',
  search_query: 'robotics',
  paid: 'yes',
  intl: '',
  source: 'uiuc_faculty',
  on_campus: '',
  deadline: '30',
  min_score: 70,
  scope: 'campus',
  sort_by: 'deadline',
  show_dismissed: false,
  favorite_ids: ['high', 'good'],
  dismissed_ids: [],
  today: '2026-07-31',
};

function row(id: string, bucket: MatchResult['bucket']): MatchResult {
  return {
    opportunity_id: id,
    eligibility_score: 80,
    readiness_score: 80,
    upside_score: 80,
    final_score: 80,
    bucket,
    reasons_fit: [],
    reasons_gap: [],
    next_steps: [],
    unknowns: [],
    opportunity: { id } as MatchResult['opportunity'],
  };
}

describe('favorite export view', () => {
  it('changes only the tab so field/search filters remain exact', () => {
    expect(favoriteExportView(view)).toEqual({ ...view, tab: 'starred' });
  });

  it('reconstructs the active bucket intersection from canonical rows', () => {
    const rows = [
      row('high', 'high_priority'),
      row('good', 'good_match'),
      row('reach', 'reach'),
    ];
    expect(favoriteRowsForTab(rows, 'high_priority').map((item) => item.opportunity_id))
      .toEqual(['high']);
    expect(favoriteRowsForTab(rows, 'all')).toEqual(rows);
    expect(favoriteRowsForTab(rows, 'starred')).toEqual(rows);
  });
});
