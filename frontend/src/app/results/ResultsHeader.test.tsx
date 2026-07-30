import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { ResultsHeader } from './ResultsHeader';
import type { MatchesResponse } from '@/lib/types';

const t = (k: string, vars?: Record<string, string | number>) =>
  vars ? `${k}{${Object.entries(vars).map(([a, b]) => `${a}=${b}`).join(',')}}` : k;

function renderHeader(fieldRelevantCount: number) {
  const data = {
    total: 5,
    high_priority: 1,
    good_match: 2,
    reach: 1,
    low_fit: 1,
    results: [],
    field_relevant_count: fieldRelevantCount,
  } as MatchesResponse;
  return render(
    <ResultsHeader
      loading={false}
      showSlowHint={false}
      data={data}
      filtered={[]}
      counts={{ all: 5 }}
      favs={new Set<string>()}
      activeTab="all"
      semanticRerank={false}
      onSemanticChange={() => {}}
      onOpenHelp={() => {}}
      onExport={() => {}}
      t={t}
    />,
  );
}

describe('ResultsHeader strong-match header', () => {
  it('does not render the dormant AI refine toggle', () => {
    renderHeader(0);
    expect(screen.queryByTestId('semantic-toggle')).not.toBeInTheDocument();
  });

  it('uses the singular variant for exactly one strong match', () => {
    renderHeader(1);
    expect(screen.getByText(/results\.fieldMatchesOne/)).toBeInTheDocument();
    expect(screen.queryByText(/results\.fieldMatches\{/)).not.toBeInTheDocument();
  });

  it('uses the plural variant with the count otherwise', () => {
    renderHeader(3);
    expect(screen.getByText(/results\.fieldMatches\{count=3\}/)).toBeInTheDocument();
  });

  it('hides the line entirely at zero', () => {
    renderHeader(0);
    expect(screen.queryByText(/results\.fieldMatches/)).not.toBeInTheDocument();
  });
});
