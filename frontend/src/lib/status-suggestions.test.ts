import { describe, it, expect } from 'vitest';
import { suggestReminderForStatusChange } from './status-suggestions';

const NOW = new Date('2026-05-23T10:00:00Z');

describe('suggestReminderForStatusChange', () => {
  it('suggests +7d follow-up when moving to replied from null', () => {
    const s = suggestReminderForStatusChange(null, 'replied', NOW);
    expect(s).not.toBeNull();
    expect(s!.reason).toBe('follow_up_after_reply');
    expect(s!.daysAhead).toBe(7);
    expect(s!.date).toBe('2026-05-30');
  });

  it('suggests +7d follow-up when moving from applied to replied', () => {
    const s = suggestReminderForStatusChange('applied', 'replied', NOW);
    expect(s!.reason).toBe('follow_up_after_reply');
    expect(s!.date).toBe('2026-05-30');
  });

  it('suggests +3d thank-you when moving to interviewing from any prior status', () => {
    const fromReplied = suggestReminderForStatusChange('replied', 'interviewing', NOW);
    const fromApplied = suggestReminderForStatusChange('applied', 'interviewing', NOW);
    const fromNull = suggestReminderForStatusChange(null, 'interviewing', NOW);
    for (const s of [fromReplied, fromApplied, fromNull]) {
      expect(s).not.toBeNull();
      expect(s!.reason).toBe('thank_you_after_interview');
      expect(s!.daysAhead).toBe(3);
      expect(s!.date).toBe('2026-05-26');
    }
  });

  it('returns null when moving to applied (no useful default follow-up window)', () => {
    expect(suggestReminderForStatusChange(null, 'applied', NOW)).toBeNull();
    expect(suggestReminderForStatusChange('replied', 'applied', NOW)).toBeNull();
  });

  it('returns null when moving to terminal states (rejected, dismissed)', () => {
    expect(suggestReminderForStatusChange('interviewing', 'rejected', NOW)).toBeNull();
    expect(suggestReminderForStatusChange('applied', 'dismissed', NOW)).toBeNull();
    expect(suggestReminderForStatusChange(null, 'rejected', NOW)).toBeNull();
  });

  it('returns null when status did not actually change (idempotent re-click)', () => {
    expect(suggestReminderForStatusChange('replied', 'replied', NOW)).toBeNull();
    expect(suggestReminderForStatusChange('interviewing', 'interviewing', NOW)).toBeNull();
  });

  it('handles month/year rollover in date arithmetic', () => {
    const dec = new Date('2026-12-30T10:00:00Z');
    const s = suggestReminderForStatusChange(null, 'replied', dec);
    expect(s!.date).toBe('2027-01-06');
  });
});
