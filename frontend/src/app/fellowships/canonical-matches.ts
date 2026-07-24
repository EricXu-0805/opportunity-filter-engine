import type { MatchResult, Opportunity } from '@/lib/types';

const CANONICAL_BUCKETS = new Set(['high_priority', 'good_match', 'reach', 'low_fit']);

export function isCanonicalProgramMatch(value: unknown): value is MatchResult {
  if (!value || typeof value !== 'object') return false;
  const candidate = value as Partial<MatchResult>;
  return typeof candidate.opportunity_id === 'string'
    && typeof candidate.final_score === 'number'
    && Number.isFinite(candidate.final_score)
    && candidate.final_score >= 0
    && candidate.final_score <= 100
    && typeof candidate.bucket === 'string'
    && CANONICAL_BUCKETS.has(candidate.bucket)
    && Array.isArray(candidate.reasons_fit)
    && candidate.reasons_fit.every((reason) => typeof reason === 'string')
    && Array.isArray(candidate.reasons_gap)
    && candidate.reasons_gap.every((reason) => typeof reason === 'string')
    && !!candidate.opportunity
    && typeof candidate.opportunity === 'object'
    && candidate.opportunity.id === candidate.opportunity_id
    && ['fellowship', 'summer_program'].includes(
      candidate.opportunity.opportunity_type ?? '',
    );
}

export function sortProgramsByCanonicalMatch(
  opportunities: Opportunity[],
  matches: ReadonlyMap<string, MatchResult>,
): Opportunity[] {
  return opportunities
    .map((opportunity, inputIndex) => ({
      opportunity,
      inputIndex,
      match: matches.get(opportunity.id),
    }))
    .sort((left, right) => {
      if (left.match && right.match) {
        return right.match.final_score - left.match.final_score
          || left.inputIndex - right.inputIndex;
      }
      if (left.match) return -1;
      if (right.match) return 1;
      return left.inputIndex - right.inputIndex;
    })
    .map(({ opportunity }) => opportunity);
}
