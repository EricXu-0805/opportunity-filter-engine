import { describe, it, expect } from 'vitest';
import {
  canDeliverReminder,
  classifyReminder,
  daysUntilReminder,
  collectReminders,
  formatReminderLabel,
} from './reminders';
import type { InteractionRecord } from './supabase';

const NOW = new Date('2026-04-17T10:00:00Z');

describe('classifyReminder', () => {
  it('returns overdue for past dates', () => {
    expect(classifyReminder('2026-04-10', NOW)).toBe('overdue');
  });

  it('returns today for same day', () => {
    expect(classifyReminder('2026-04-17', NOW)).toBe('today');
  });

  it('returns tomorrow for next day', () => {
    expect(classifyReminder('2026-04-18', NOW)).toBe('tomorrow');
  });

  it('returns this_week for 2-7 days out', () => {
    expect(classifyReminder('2026-04-22', NOW)).toBe('this_week');
    expect(classifyReminder('2026-04-24', NOW)).toBe('this_week');
  });

  it('returns upcoming for 8+ days out', () => {
    expect(classifyReminder('2026-04-28', NOW)).toBe('upcoming');
    expect(classifyReminder('2026-06-01', NOW)).toBe('upcoming');
  });

  it('returns null for malformed dates', () => {
    expect(classifyReminder('not-a-date', NOW)).toBeNull();
    expect(classifyReminder('', NOW)).toBeNull();
  });
});

describe('daysUntilReminder', () => {
  it('computes positive days for future', () => {
    expect(daysUntilReminder('2026-04-24', NOW)).toBe(7);
  });

  it('returns negative for past', () => {
    expect(daysUntilReminder('2026-04-10', NOW)).toBe(-7);
  });

  it('returns null for invalid input', () => {
    expect(daysUntilReminder('xx', NOW)).toBeNull();
  });
});

describe('collectReminders', () => {
  function makeMap(entries: Array<[string, Partial<InteractionRecord>]>): Map<string, InteractionRecord> {
    const m = new Map<string, InteractionRecord>();
    for (const [id, rec] of entries) {
      m.set(id, { type: 'applied', ...rec } as InteractionRecord);
    }
    return m;
  }

  it('returns [] when no reminders set', () => {
    const m = makeMap([['a', { type: 'applied' }]]);
    expect(collectReminders(m, NOW)).toEqual([]);
  });

  it('skips dismissed but KEEPS rejected, which the tracker still shows', () => {
    // Rejected used to be dropped here alongside dismissed. But a rejected
    // row is visible in Tracker and keeps whatever reminder the student set
    // — the cron simply never sends for it. Dropping it made that reminder
    // invisible on the dashboard in both directions: not counted as due
    // (right) and not counted as needing review (wrong). Deliverability is
    // decided downstream by canDeliverReminder; this function's job is only
    // to collect what exists.
    //
    // Dismissed stays dropped: it is the hide-everywhere status, excluded
    // from every Tracker column, and surfacing it here would resurrect
    // something the student explicitly put away.
    const m = makeMap([
      ['a', { type: 'rejected', remind_at: '2026-04-20' }],
      ['b', { type: 'dismissed', remind_at: '2026-04-20' }],
      ['c', { type: 'applied', remind_at: '2026-04-20' }],
    ]);
    const reminders = collectReminders(m, NOW);
    expect(reminders.map((r) => r.opportunityId).sort()).toEqual(['a', 'c']);
  });

  it('sorts overdue before today before upcoming', () => {
    const m = makeMap([
      ['future', { remind_at: '2026-05-01' }],
      ['today', { remind_at: '2026-04-17' }],
      ['overdue', { remind_at: '2026-04-10' }],
      ['tomorrow', { remind_at: '2026-04-18' }],
    ]);
    const ids = collectReminders(m, NOW).map(r => r.opportunityId);
    expect(ids).toEqual(['overdue', 'today', 'tomorrow', 'future']);
  });

  it('secondary-sorts by daysAway within same status', () => {
    const m = makeMap([
      ['further_future', { remind_at: '2026-05-10' }],
      ['near_future', { remind_at: '2026-04-28' }],
    ]);
    const ids = collectReminders(m, NOW).map(r => r.opportunityId);
    expect(ids).toEqual(['near_future', 'further_future']);
  });

  it('includes notes and type on output', () => {
    const m = makeMap([
      ['a', { type: 'interviewing', remind_at: '2026-04-20', notes: 'Prep questions' }],
    ]);
    const out = collectReminders(m, NOW);
    expect(out[0].notes).toBe('Prep questions');
    expect(out[0].type).toBe('interviewing');
  });
});

describe('formatReminderLabel', () => {
  const mk = (overrides: Partial<Parameters<typeof formatReminderLabel>[0]> = {}) => ({
    opportunityId: 'x',
    remindAt: '2026-04-20',
    daysAway: 3,
    status: 'this_week' as const,
    ...overrides,
  });

  it('formats overdue with plural', () => {
    expect(formatReminderLabel(mk({ status: 'overdue', daysAway: -5 }))).toBe('Overdue by 5 days');
  });

  it('formats overdue with singular', () => {
    expect(formatReminderLabel(mk({ status: 'overdue', daysAway: -1 }))).toBe('Overdue by 1 day');
  });

  it('formats today', () => {
    expect(formatReminderLabel(mk({ status: 'today', daysAway: 0 }))).toBe('Due today');
  });

  it('formats tomorrow', () => {
    expect(formatReminderLabel(mk({ status: 'tomorrow', daysAway: 1 }))).toBe('Due tomorrow');
  });

  it('formats this_week', () => {
    expect(formatReminderLabel(mk({ status: 'this_week', daysAway: 3 }))).toBe('In 3 days');
  });

  it('formats upcoming', () => {
    expect(formatReminderLabel(mk({ status: 'upcoming', daysAway: 12 }))).toBe('In 12 days');
  });
});

// The one predicate four surfaces share — the tracker board, the detail
// panel's date editor, the detail page's automatic suggestion, and the
// dashboard's due list. It copies the reminders cron's own two filters:
//   interaction_type in (contacted, applied, replied, interviewing)
//   AND the target is release-visible and still actionable
// A copy that drifts produces a control that accepts the click, stores the
// date, and then nothing arrives.
describe('canDeliverReminder', () => {
  const LIVE_LISTING = {
    source_type: 'campus_program',
    record_kind: 'listing',
    target_truth: {
      listing_state: 'open', reference_only: false, actionable: true,
      accepting_state: 'accepting', reason_code: null,
      verified_at: null, expires_at: null,
    },
  };
  // A directory page states no listing and no acceptance — both unknown.
  const LIVE_FACULTY = {
    source_type: 'faculty_research',
    record_kind: 'faculty_contact',
    target_truth: {
      listing_state: 'unknown', reference_only: false, actionable: true,
      accepting_state: 'unknown', reason_code: null,
      verified_at: null, expires_at: null,
    },
  };
  function deadListing(truth: unknown) {
    return { source_type: 'campus_program', record_kind: 'listing', target_truth: truth };
  }

  it.each(['contacted', 'applied', 'replied', 'interviewing'] as const)(
    'a live listing in %s is deliverable',
    (status) => {
      expect(canDeliverReminder(LIVE_LISTING as never, status)).toBe(true);
    },
  );

  it('a live faculty contact the student emailed is deliverable', () => {
    // The majority case: reminders are set on professors far more often than
    // on postings, and the cron does select this shape.
    expect(canDeliverReminder(LIVE_FACULTY as never, 'contacted')).toBe(true);
  });

  it.each(['rejected', 'dismissed'] as const)(
    'a live listing in %s is not — the cron query never selects it',
    (status) => {
      expect(canDeliverReminder(LIVE_LISTING as never, status)).toBe(false);
    },
  );

  it.each([
    ['closed', {
      listing_state: 'closed', reference_only: false, actionable: false,
      accepting_state: 'not_accepting', reason_code: 'listing_closed',
      verified_at: null, expires_at: null,
    }],
    ['reference-only', {
      listing_state: 'unknown', reference_only: true, actionable: false,
      accepting_state: 'unknown', reason_code: 'reference_only',
      verified_at: null, expires_at: null,
    }],
    ['inactive', {
      listing_state: 'unknown', reference_only: false, actionable: false,
      accepting_state: 'unknown', reason_code: 'inactive',
      verified_at: null, expires_at: null,
    }],
    ['absent', undefined],
    ['malformed', { listing_state: 'open' }],
  ])('a %s target is not deliverable even in a good status', (_label, truth) => {
    expect(canDeliverReminder(deadListing(truth) as never, 'applied')).toBe(false);
  });

  it('an unreviewed record kind is not deliverable', () => {
    expect(canDeliverReminder(
      { source_type: 'departmental_newsletter', record_kind: 'unknown' } as never,
      'applied',
    )).toBe(false);
  });

  it('a wire record_kind that disagrees with the source type is not deliverable', () => {
    // One of the two allowlists moved. Trusting either alone is how a renamed
    // source type silently becomes a listing.
    expect(canDeliverReminder(
      { ...LIVE_LISTING, record_kind: 'faculty_contact' } as never,
      'applied',
    )).toBe(false);
  });

  it('no target and no status are both refused', () => {
    expect(canDeliverReminder(undefined, 'applied')).toBe(false);
    expect(canDeliverReminder(LIVE_LISTING as never, undefined)).toBe(false);
  });
});
