import { describe, it, expect } from 'vitest';

import { getIntlBadge, getPaidBadge } from './badge-utils';

const t = (key: string) => key;

describe('getPaidBadge — canonical unknown semantics', () => {
  it('labels explicit values', () => {
    expect(getPaidBadge('yes', t)).toEqual({ label: 'badges.paid', variant: 'green' });
    expect(getPaidBadge('stipend', t)).toEqual({ label: 'badges.stipend', variant: 'blue' });
    expect(getPaidBadge('no', t)).toEqual({ label: 'badges.unpaid', variant: 'gray' });
  });

  it('every unknown form reads "not disclosed", never "Unpaid"', () => {
    // undefined / '' previously fell through to "Unpaid" — asserting a fact
    // nobody collected, the exact misrepresentation R70-D fixed for 'unknown'.
    for (const v of ['unknown', undefined, '', 'weird-enum'] as const) {
      expect(getPaidBadge(v, t).label).toBe('badges.notDisclosed');
    }
  });
});

describe('getIntlBadge — unknown stays a "verify", never a verdict', () => {
  it('maps explicit values', () => {
    expect(getIntlBadge('yes', t).variant).toBe('green');
    expect(getIntlBadge('no', t).variant).toBe('red');
  });

  it('unknown forms render the verify badge', () => {
    for (const v of ['unknown', undefined, ''] as const) {
      expect(getIntlBadge(v, t)).toEqual({ label: 'badges.intlVerify', variant: 'orange' });
    }
  });
});

describe('a card hedges exactly what the detail page hedges', () => {
  const t = (k: string) => k;

  it('calls a guessed pay value "funding mentioned", in grey', () => {
    // 201 live records carry paid='yes' because _detect_paid_from_text read it
    // off prose. The detail page says "Funding mentioned"; the results card and
    // the favorites card both render through this helper and still said "Paid"
    // in green, so the same record contradicted itself between two screens.
    expect(getPaidBadge('yes', t, 'inferred')).toEqual({
      label: 'badges.fundingMentioned', variant: 'gray',
    });
    expect(getPaidBadge('stipend', t, 'inferred')).toEqual({
      label: 'badges.fundingMentioned', variant: 'gray',
    });
  });

  it('leaves a stated pay value alone', () => {
    expect(getPaidBadge('yes', t)).toEqual({ label: 'badges.paid', variant: 'green' });
    expect(getPaidBadge('stipend', t)).toEqual({ label: 'badges.stipend', variant: 'blue' });
    expect(getPaidBadge('no', t).label).toBe('badges.unpaid');
  });

  it('downgrades a guessed "US only" to the verify state rather than a red no', () => {
    // 32 live records say international_friendly='no' because the tagger
    // matched a federal-organisation or title substring. A red "US only" chip
    // is what makes an international student close the tab.
    expect(getIntlBadge('no', t, 'inferred')).toEqual({
      label: 'badges.intlVerify', variant: 'orange',
    });
  });

  it('keeps a stated restriction red, and never downgrades a yes', () => {
    expect(getIntlBadge('no', t)).toEqual({ label: 'badges.intlUsOnly', variant: 'red' });
    expect(getIntlBadge('yes', t, 'inferred')).toEqual({ label: 'badges.intlOk', variant: 'green' });
  });
});
