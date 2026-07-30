/**
 * Shared badge label helpers for opportunity cards.
 *
 * Extracted in R70-E from `MatchCard.tsx` so `OpportunityCard.tsx` can
 * import the same logic instead of maintaining a duplicate inline ternary.
 * The duplication had drifted: OpportunityCard's inline `paid` ternary
 * still mislabeled `paid='unknown'` as "Unpaid", the exact bug that
 * R70-D fixed for MatchCard. Centralising here closes that loop and
 * keeps future label changes in one place.
 *
 * Both helpers take the translator (`t`) so badge text honours the
 * current locale instead of hardcoded English.
 */

export type IntlBadgeVariant = 'green' | 'red' | 'orange';
export type PaidBadgeVariant = 'green' | 'blue' | 'gray';

export interface BadgeResult<V> {
  label: string;
  variant: V;
}

export function getIntlBadge(
  friendly: string | undefined,
  t: (key: string) => string,
): BadgeResult<IntlBadgeVariant> {
  if (friendly === 'yes') return { label: t('badges.intlOk'), variant: 'green' };
  if (friendly === 'no') return { label: t('badges.intlUsOnly'), variant: 'red' };
  return { label: t('badges.intlVerify'), variant: 'orange' };
}

export function getPaidBadge(
  paid: string | undefined,
  t: (key: string) => string,
): BadgeResult<PaidBadgeVariant> {
  if (paid === 'stipend') return { label: t('badges.stipend'), variant: 'blue' };
  if (paid === 'yes') return { label: t('badges.paid'), variant: 'green' };
  // Canonical unknown semantics: ONLY an explicit 'no' is "Unpaid".
  // R70-D distinguished 'unknown' ("not disclosed") from 'no'; the
  // undefined/'' case still fell through to the misleading "Unpaid" —
  // asserting a fact nobody collected. Missing data reads as not disclosed.
  if (paid === 'no') return { label: t('badges.unpaid'), variant: 'gray' };
  return { label: t('badges.notDisclosed'), variant: 'gray' };
}
