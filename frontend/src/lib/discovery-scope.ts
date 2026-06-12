/*
 * Discovery-scope model (PR #187 decision, 2026-06): the home school is
 * identity; which opportunities a user sees is decided by each record's
 * own `audience`. These pure helpers back the /results scope facet and
 * MatchCard's host+audience chip so the rules live (and are tested) in
 * one place.
 */

import type { Opportunity } from './types';
import { bySlug } from './schools';

export type ScopeValue = '' | 'campus' | 'open';

type ScopedOpportunity = Pick<Opportunity, 'school' | 'audience'>;

export function homeSchoolOf(profile: { home_school?: string } | null): string {
  return profile?.home_school || 'uiuc';
}

/** True when the record carries any scope metadata at all. Cached match
 *  results from before PR #189 have neither field — the facet hides itself
 *  rather than filtering on data that isn't there. */
export function hasScopeData(opp: ScopedOpportunity): boolean {
  return opp.school !== undefined || opp.audience !== undefined;
}

export function matchesScope(
  opp: ScopedOpportunity,
  scope: ScopeValue,
  homeSchool: string,
): boolean {
  if (scope === 'campus') return opp.school === homeSchool;
  if (scope === 'open') return opp.audience === 'open' || opp.audience === 'unknown';
  return true;
}

export type ScopeChipKind = 'open' | 'unknown' | 'foreignCampus';

export interface ScopeChip {
  kind: ScopeChipKind;
  /** Host school display name, or null for national programs. */
  host: string | null;
}

/**
 * Chip rule: home-campus records show nothing (the majority — avoid
 * noise); everything else gets one subtle host+audience chip. Records
 * without scope metadata also show nothing.
 */
export function scopeChipFor(opp: ScopedOpportunity, homeSchool: string): ScopeChip | null {
  if (!hasScopeData(opp)) return null;
  if (opp.school === homeSchool) return null;
  const host = opp.school ? (bySlug(opp.school)?.shortName ?? opp.school) : null;
  if (opp.audience === 'open') return { kind: 'open', host };
  if (opp.audience === 'unknown') return { kind: 'unknown', host };
  if (opp.audience === 'campus' && host) return { kind: 'foreignCampus', host };
  return null;
}
