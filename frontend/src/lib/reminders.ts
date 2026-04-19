import type { InteractionRecord } from './supabase';

export type ReminderStatus = 'overdue' | 'today' | 'tomorrow' | 'this_week' | 'upcoming' | null;

export interface ReminderInfo {
  opportunityId: string;
  remindAt: string;
  daysAway: number;
  status: Exclude<ReminderStatus, null>;
  notes?: string;
  type?: string;
}

export function classifyReminder(remindAt: string, now: Date = new Date()): ReminderStatus {
  const due = Date.parse(remindAt + 'T00:00:00');
  if (isNaN(due)) return null;
  const days = Math.ceil((due - now.getTime()) / 86400000);
  if (days < 0) return 'overdue';
  if (days === 0) return 'today';
  if (days === 1) return 'tomorrow';
  if (days <= 7) return 'this_week';
  return 'upcoming';
}

export function daysUntilReminder(remindAt: string, now: Date = new Date()): number | null {
  const due = Date.parse(remindAt + 'T00:00:00');
  if (isNaN(due)) return null;
  return Math.ceil((due - now.getTime()) / 86400000);
}

const STATUS_RANK: Record<Exclude<ReminderStatus, null>, number> = {
  overdue: 0,
  today: 1,
  tomorrow: 2,
  this_week: 3,
  upcoming: 4,
};

export function collectReminders(
  interactions: Map<string, InteractionRecord>,
  now: Date = new Date(),
): ReminderInfo[] {
  const out: ReminderInfo[] = [];
  interactions.forEach((rec, id) => {
    if (!rec.remind_at) return;
    if (rec.type === 'rejected' || rec.type === 'dismissed') return;
    const status = classifyReminder(rec.remind_at, now);
    if (!status) return;
    const days = daysUntilReminder(rec.remind_at, now);
    if (days === null) return;
    out.push({
      opportunityId: id,
      remindAt: rec.remind_at,
      daysAway: days,
      status,
      notes: rec.notes,
      type: rec.type,
    });
  });
  out.sort((a, b) => {
    const rank = STATUS_RANK[a.status] - STATUS_RANK[b.status];
    if (rank !== 0) return rank;
    return a.daysAway - b.daysAway;
  });
  return out;
}

export function formatReminderLabel(info: ReminderInfo): string {
  switch (info.status) {
    case 'overdue':
      return info.daysAway === -1 ? 'Overdue by 1 day' : `Overdue by ${-info.daysAway} days`;
    case 'today':
      return 'Due today';
    case 'tomorrow':
      return 'Due tomorrow';
    case 'this_week':
      return `In ${info.daysAway} days`;
    case 'upcoming':
      return `In ${info.daysAway} days`;
  }
}
