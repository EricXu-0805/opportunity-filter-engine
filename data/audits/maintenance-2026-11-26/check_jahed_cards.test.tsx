import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { render, screen } from '@testing-library/react';
import { test, expect } from 'vitest';
import MatchCard from '@/components/MatchCard';
import { OpportunityCard } from '@/app/favorites/OpportunityCard';
import type { Opp } from '@/app/favorites/types';
import { translate } from '@/i18n/translate';
import type { MatchResult } from '@/lib/types';

const directory = process.env.OFE_ACTUAL_CARD_INPUTS!;
const originalId = 'faculty-ucsd-nano-8a42e65d';
const biography = 'https://jacobsschool.ucsd.edu/faculty/profile?id=527';
const noop = () => {};

test('the normal matching view result links to the named faculty biography', () => {
  const match: MatchResult = JSON.parse(readFileSync(join(directory, 'match.json'), 'utf8'));
  expect(match.opportunity_id).toBe(originalId);
  render(<MatchCard match={match} onDraftEmail={noop} />);
  expect(screen.getByRole('link', { name: 'Faculty page' })).toHaveAttribute('href', biography);
});

test('the normal saved-opportunity card links the public detail to the named faculty biography', () => {
  const detail: Opp = JSON.parse(readFileSync(join(directory, 'detail.json'), 'utf8'));
  expect(detail.id).toBe(originalId);
  render(<OpportunityCard opp={detail} isExpanded selectionMode={false} isSelected={false}
    selectedSize={0} hasProfile={false} onToggleExpand={noop} onToggleSelect={noop}
    onRemove={noop} onOpenEmailModal={noop} tailorDisabled={false}
    t={(key, vars) => translate('en', key, vars)} />);
  expect(screen.getByRole('link', { name: 'Faculty page' })).toHaveAttribute('href', biography);
});
