import { describe, it, expect } from 'vitest';
import {
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

  it('skips rejected and dismissed interactions', () => {
    const m = makeMap([
      ['a', { type: 'rejected', remind_at: '2026-04-20' }],
      ['b', { type: 'dismissed', remind_at: '2026-04-20' }],
      ['c', { type: 'applied', remind_at: '2026-04-20' }],
    ]);
    const reminders = collectReminders(m, NOW);
    expect(reminders).toHaveLength(1);
    expect(reminders[0].opportunityId).toBe('c');
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
