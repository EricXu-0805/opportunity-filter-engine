import { describe, expect, it } from 'vitest';

import type { MatchVerdict } from '@/lib/match-feedback';

import { mergeHydratedFeedback } from './feedback-hydration';

describe('mergeHydratedFeedback', () => {
  it('does not let a stale hydration response overwrite a newer vote', () => {
    const merged = mergeHydratedFeedback(
      new Map<string, MatchVerdict>([['opp-1', 'up']]),
      new Map<string, MatchVerdict>([['opp-1', 'down']]),
      new Map([['opp-1', 0]]),
      new Map([['opp-1', 1]]),
    );

    expect(merged.get('opp-1')).toBe('up');
  });

  it('hydrates unchanged ids while independently preserving mutated ids', () => {
    const merged = mergeHydratedFeedback(
      new Map<string, MatchVerdict>([['opp-1', 'up']]),
      new Map<string, MatchVerdict>([
        ['opp-1', 'down'],
        ['opp-2', 'down'],
      ]),
      new Map([
        ['opp-1', 0],
        ['opp-2', 0],
      ]),
      new Map([['opp-1', 1]]),
    );

    expect(merged).toEqual(new Map([
      ['opp-1', 'up'],
      ['opp-2', 'down'],
    ]));
  });

  it('ignores hydrated ids that were never requested', () => {
    const merged = mergeHydratedFeedback(
      new Map<string, MatchVerdict>(),
      new Map<string, MatchVerdict>([['opp-9', 'up']]),
      new Map(),
      new Map(),
    );

    expect(merged.size).toBe(0);
  });
});
