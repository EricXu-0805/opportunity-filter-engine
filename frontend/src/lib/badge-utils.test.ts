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
