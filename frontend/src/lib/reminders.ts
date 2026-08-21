import type { InteractionRecord, InteractionType } from './supabase';
import { targetPosture } from './target-truth';
import type { Opportunity } from './types';

/**
 * Whether the reminders cron would actually send for this row.
 *
 * Copied from that job's own two filters, and kept in one place because four
 * surfaces offer to create or reschedule a reminder — the tracker board, the
 * detail panel's date editor, the detail page's automatic suggestion, and the
 * cold-email follow-up chips — and a copy that drifts produces the worst
 * possible outcome: a control that accepts the click, stores the date, and
 * then nothing ever arrives. The student stops watching for the thing itself.
 *
 *   1. `interaction_type=in.(contacted,applied,replied,interviewing)`
 *   2. the target is release-visible AND still actionable
 *
 * The second is checked here through `targetPosture`, which is this client's
 * reading of the same truth envelope the cron reads server-side.
 */
export const REMINDABLE_STATUSES: ReadonlySet<InteractionType> = new Set<InteractionType>([
  'contacted', 'applied', 'replied', 'interviewing',
]);

type ReminderTarget = Pick<Opportunity, 'target_truth' | 'source_type'> & {
  record_kind?: string;
};

export function canDeliverReminder(
  target: ReminderTarget | null | undefined,
  status: InteractionType | undefined,
): boolean {
  if (!target || !status) return false;
  if (!REMINDABLE_STATUSES.has(status)) return false;
  return targetPosture(target) === 'actionable';
}

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
    // 'dismissed' is the hide-everywhere status and stays dropped here —
    // Tracker excludes it from every column, and a dashboard note about it
    // would resurrect something the student explicitly put away.
    //
    // 'rejected' is different and used to be dropped alongside it. A rejected
    // row IS visible in Tracker, and it keeps any reminder the student set —
    // the cron just never sends for it. Dropping it here meant that reminder
    // was invisible on the dashboard in both directions: not counted as due
    // (correct) and not counted as needing review (wrong), so a date the
    // student is still looking at simply had no representation anywhere.
    // canDeliverReminder sorts it into needs-review downstream.
    if (rec.type === 'dismissed') return;
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
