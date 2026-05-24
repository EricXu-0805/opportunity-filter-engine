import type { InteractionType } from './supabase';

export type SuggestionReason = 'follow_up_after_reply' | 'thank_you_after_interview';

export interface ReminderSuggestion {
  date: string;
  reason: SuggestionReason;
  daysAhead: number;
}

const DAYS = {
  follow_up_after_reply: 7,
  thank_you_after_interview: 3,
} as const;

function addDays(now: Date, n: number): string {
  const d = new Date(now);
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
}

export function suggestReminderForStatusChange(
  from: InteractionType | null | undefined,
  to: InteractionType,
  now: Date = new Date(),
): ReminderSuggestion | null {
  if (from === to) return null;

  if (to === 'replied') {
    return {
      date: addDays(now, DAYS.follow_up_after_reply),
      reason: 'follow_up_after_reply',
      daysAhead: DAYS.follow_up_after_reply,
    };
  }

  if (to === 'interviewing') {
    return {
      date: addDays(now, DAYS.thank_you_after_interview),
      reason: 'thank_you_after_interview',
      daysAhead: DAYS.thank_you_after_interview,
    };
  }

  return null;
}
