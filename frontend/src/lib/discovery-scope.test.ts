import { describe, expect, it } from 'vitest';
import {
  hasScopeData,
  homeSchoolOf,
  matchesScope,
  scopeChipFor,
} from './discovery-scope';

describe('homeSchoolOf', () => {
  it('defaults to uiuc for null profile, missing field, and empty string', () => {
    expect(homeSchoolOf(null)).toBe('uiuc');
    expect(homeSchoolOf({})).toBe('uiuc');
    expect(homeSchoolOf({ home_school: '' })).toBe('uiuc');
  });

  it('returns the stored slug when present', () => {
    expect(homeSchoolOf({ home_school: 'ucb' })).toBe('ucb');
  });
});

describe('hasScopeData', () => {
  it('is false for records without school or audience (pre-#189 cache)', () => {
    expect(hasScopeData({})).toBe(false);
  });

  it('is true when either field is present, including school: null', () => {
    expect(hasScopeData({ school: 'uiuc' })).toBe(true);
    expect(hasScopeData({ school: null })).toBe(true);
    expect(hasScopeData({ audience: 'open' })).toBe(true);
  });
});

describe('matchesScope', () => {
  const uiucCampus = { school: 'uiuc', audience: 'campus' as const };
  const nationalOpen = { school: null, audience: 'open' as const };
  const ucbUnknown = { school: 'ucb', audience: 'unknown' as const };
  const legacy = {};

  it("'' (全部) matches everything", () => {
    for (const opp of [uiucCampus, nationalOpen, ucbUnknown, legacy]) {
      expect(matchesScope(opp, '', 'uiuc')).toBe(true);
    }
  });

  it("'campus' (我的学校) matches only school === home_school", () => {
    expect(matchesScope(uiucCampus, 'campus', 'uiuc')).toBe(true);
    expect(matchesScope(nationalOpen, 'campus', 'uiuc')).toBe(false);
    expect(matchesScope(ucbUnknown, 'campus', 'uiuc')).toBe(false);
    expect(matchesScope(legacy, 'campus', 'uiuc')).toBe(false);
  });

  it("'campus' follows the home school after a switch", () => {
    expect(matchesScope(ucbUnknown, 'campus', 'ucb')).toBe(true);
    expect(matchesScope(uiucCampus, 'campus', 'ucb')).toBe(false);
  });

  it("'open' (对外开放) matches open and unknown audiences", () => {
    expect(matchesScope(nationalOpen, 'open', 'uiuc')).toBe(true);
    expect(matchesScope(ucbUnknown, 'open', 'uiuc')).toBe(true);
    expect(matchesScope(uiucCampus, 'open', 'uiuc')).toBe(false);
    expect(matchesScope(legacy, 'open', 'uiuc')).toBe(false);
  });
});

describe('scopeChipFor — chip rendering rules', () => {
  it('home-campus records get NO chip (majority case, avoid noise)', () => {
    expect(scopeChipFor({ school: 'uiuc', audience: 'campus' }, 'uiuc')).toBeNull();
    // Even a home-school record tagged open stays chipless — it's home campus.
    expect(scopeChipFor({ school: 'uiuc', audience: 'open' }, 'uiuc')).toBeNull();
  });

  it('records without scope metadata get NO chip', () => {
    expect(scopeChipFor({}, 'uiuc')).toBeNull();
  });

  it('national open records get an open chip with no host', () => {
    expect(scopeChipFor({ school: null, audience: 'open' }, 'uiuc'))
      .toEqual({ kind: 'open', host: null });
  });

  it('foreign open records get an open chip with the host shortName', () => {
    expect(scopeChipFor({ school: 'ucb', audience: 'open' }, 'uiuc'))
      .toEqual({ kind: 'open', host: 'UC Berkeley' });
  });

  it('unknown-audience records get an unknown chip', () => {
    expect(scopeChipFor({ school: 'ucb', audience: 'unknown' }, 'uiuc'))
      .toEqual({ kind: 'unknown', host: 'UC Berkeley' });
    expect(scopeChipFor({ school: null, audience: 'unknown' }, 'uiuc'))
      .toEqual({ kind: 'unknown', host: null });
  });

  it('foreign campus-only records get the students-only chip', () => {
    expect(scopeChipFor({ school: 'uiuc', audience: 'campus' }, 'ucb'))
      .toEqual({ kind: 'foreignCampus', host: 'UIUC' });
  });

  it('falls back to the raw slug for a host school not in the registry', () => {
    expect(scopeChipFor({ school: 'cmu', audience: 'open' }, 'uiuc'))
      .toEqual({ kind: 'open', host: 'cmu' });
  });
});
