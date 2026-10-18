import { describe, it, expect } from 'vitest';

import { translate } from '@/i18n/translate';
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
      label: 'badges.payUnconfirmed', variant: 'gray',
    });
  });

  it('marks an "unpaid" we inferred instead of stating it', () => {
    // A configured program's pay answer or a scan of the prose can say 'no'
    // too; the card printed it as the program's own plain "Unpaid".
    expect(getPaidBadge('no', t, 'inferred')).toEqual({
      label: 'badges.unpaidInferred', variant: 'gray',
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

  it('keeps a stated restriction red and a stated welcome a plain green "Intl OK"', () => {
    expect(getIntlBadge('no', t)).toEqual({ label: 'badges.intlUsOnly', variant: 'red' });
    expect(getIntlBadge('yes', t)).toEqual({ label: 'badges.intlOk', variant: 'green' });
    expect(getIntlBadge('yes', t, null)).toEqual({ label: 'badges.intlOk', variant: 'green' });
  });

  it('marks a welcome we inferred as our inference', () => {
    // purdue-af71941ba814 (a configured program's answer) and sro-3d5d9a42 (a
    // keyword scan of the SRO page) showed a plain green "Intl OK" on the
    // card while the detail page called the same answer a system inference.
    expect(getIntlBadge('yes', t, 'inferred')).toEqual({ label: 'badges.intlOkInferred', variant: 'orange' });
    const en = (key: string) => translate('en', key);
    const zh = (key: string) => translate('zh', key);
    expect(getIntlBadge('yes', en, 'inferred').label).toBe('Intl OK (inferred)');
    expect(getIntlBadge('yes', zh, 'inferred').label).toBe('接受国际生（推断）');
    expect(getIntlBadge('yes', en).label).toBe('Intl OK');
  });
});

describe('a Simplify "Does Not Offer Sponsorship" listing says what the listing says (M121)', () => {
  it('names the label instead of "US Only", which the listing does not say', () => {
    // 12 live Simplify internships whose one restriction is that label: an
    // international student now sees them, with "CPT/OPT may still apply".
    expect(getIntlBadge('no', t, undefined, 'no_sponsorship')).toEqual({
      label: 'badges.intlNoSponsorship', variant: 'orange',
    });
    expect(getIntlBadge('no', t, null, 'no_sponsorship').label).toBe('badges.intlNoSponsorship');
  });

  it('keeps "US Only" for a stated citizenship rule', () => {
    expect(getIntlBadge('no', t, undefined, null)).toEqual({ label: 'badges.intlUsOnly', variant: 'red' });
    expect(getIntlBadge('no', t)).toEqual({ label: 'badges.intlUsOnly', variant: 'red' });
  });

  it('has the words in both languages', () => {
    const en = (key: string) => translate('en', key);
    const zh = (key: string) => translate('zh', key);
    expect(getIntlBadge('no', en, undefined, 'no_sponsorship').label).toBe('No visa sponsorship');
    expect(getIntlBadge('no', zh, undefined, 'no_sponsorship').label).toBe('不提供签证担保');
  });
});
