import { beforeEach, describe, expect, it } from 'vitest';
import { translate } from '@/i18n/translate';
import { advanceOwnerEpoch, captureOwnerToken, syncLocalIdentityOwner } from './identity-owner';
import {
  MATCH_VIEW_CONTRACT_VERSION,
  TARGET_TRUTH_CONTRACT,
  readMatchCache,
  writeMatchCache,
} from './match-cache';
import { opportunityApplicationUrl, pendingApplicationOpening } from './target-truth';
import type { MatchesResponse, Opportunity } from './types';

// What the server sends for a program whose page states its opening
// (backend/lib/public_projection.py, src/program_windows.public_opening).
const OPENING = {
  on: '2026-11-15',
  at: '2026-11-15T06:00:00+00:00',
  text: 'November 15',
  quote: 'November 15: Online application opens.',
  source_url: 'https://summerprogram.unl.edu/',
};
const BEFORE = Date.parse('2026-11-15T05:59:59Z');
const AT = Date.parse(OPENING.at);

function program(overrides: Record<string, unknown> = {}): Opportunity {
  return {
    id: 'unl-1',
    title: 'Summer Research Program',
    source_type: 'campus_program',
    record_kind: 'listing',
    target_truth: {
      listing_state: 'unknown', reference_only: false, actionable: true,
      accepting_state: 'unknown', reason_code: null, verified_at: null, expires_at: null,
    },
    application: { application_url: 'https://summerprogram.unl.edu/' },
    ...overrides,
  } as unknown as Opportunity;
}

describe('pendingApplicationOpening', () => {
  it('reads the stated opening until its campus midnight', () => {
    expect(pendingApplicationOpening(program({ application_opens: OPENING }), BEFORE)).toEqual(OPENING);
    expect(pendingApplicationOpening(program({ application_opens: OPENING }), AT)).toBeNull();
    expect(pendingApplicationOpening(program({ application_opens: OPENING }), AT + 86400000)).toBeNull();
  });

  it('reads an older backend payload, which has no opening, as stating none', () => {
    expect(pendingApplicationOpening(program(), BEFORE)).toBeNull();
    expect(pendingApplicationOpening(program({ application_opens: null }), BEFORE)).toBeNull();
  });

  it.each([
    ['a string', 'November 15'],
    ['a list', [OPENING]],
    ['no instant', { ...OPENING, at: undefined }],
    ['an unreadable instant', { ...OPENING, at: 'mid November' }],
    ['no date text', { ...OPENING, text: ' ' }],
    ['no quote', { ...OPENING, quote: 7 }],
  ])('reads an opening it cannot parse (%s) as none', (_label, value) => {
    expect(pendingApplicationOpening(program({ application_opens: value }), BEFORE)).toBeNull();
  });

  it('keeps no source link that is not a string', () => {
    expect(pendingApplicationOpening(program({ application_opens: { ...OPENING, source_url: 5 } }), BEFORE))
      .toEqual({ ...OPENING, source_url: null });
  });
});

describe('Apply before a stated opening', () => {
  it('is withheld while the opening is ahead and offered once it passes', () => {
    expect(opportunityApplicationUrl(program({
      application_opens: { ...OPENING, at: '2999-11-15T06:00:00+00:00' },
    }))).toBeUndefined();
    expect(opportunityApplicationUrl(program({
      application_opens: { ...OPENING, at: '2000-11-15T06:00:00+00:00' },
    }))).toBe('https://summerprogram.unl.edu/');
  });

  it('is offered as before on an older backend payload', () => {
    expect(opportunityApplicationUrl(program())).toBe('https://summerprogram.unl.edu/');
  });
});

describe('the opening on a cached results page', () => {
  beforeEach(async () => {
    localStorage.clear();
    advanceOwnerEpoch('opening-uid');
    await syncLocalIdentityOwner('opening-uid');
  });

  it('survives a cache hit, so Apply does not come back on a restored card', () => {
    const response = {
      total: 1, high_priority: 0, good_match: 1, reach: 0, low_fit: 0,
      results: [{
        opportunity_id: 'unl-1', eligibility_score: 70, readiness_score: 60, upside_score: 50,
        final_score: 65, bucket: 'good_match', reasons_fit: [], reasons_gap: [], next_steps: [],
        opportunity: program({ application_opens: OPENING, description_clean: 'x' }),
      }],
      contract_version: MATCH_VIEW_CONTRACT_VERSION,
      target_truth_contract: TARGET_TRUTH_CONTRACT,
    } as unknown as MatchesResponse;

    expect(writeMatchCache('h1', false, response, captureOwnerToken())).toBe(true);
    expect(readMatchCache('h1', false)!.results[0].opportunity.application_opens).toEqual(OPENING);
  });
});

describe('the opening labels', () => {
  it('carry the page’s own date in English and Chinese', () => {
    expect(translate('en', 'badges.applicationsOpenOn', { date: 'November 15' }))
      .toBe('Applications open November 15');
    expect(translate('zh', 'badges.applicationsOpenOn', { date: 'November 15' })).toBe('申请开放日：November 15');
    expect(translate('en', 'detail.openingQuote', { quote: OPENING.quote }))
      .toBe('The program page: “November 15: Online application opens.”');
    expect(translate('zh', 'detail.openingQuote', { quote: OPENING.quote }))
      .toBe('项目页原文：“November 15: Online application opens.”');
  });
});
