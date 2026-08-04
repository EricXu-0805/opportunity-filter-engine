'use client';

import { useEffect, useState } from 'react';
import {
  ArrowRight,
  BarChart3,
  BellRing,
  BookOpenCheck,
  CalendarClock,
  GraduationCap,
  Loader2,
  MessageSquare,
  Send,
  StickyNote,
  Users,
  XCircle,
} from 'lucide-react';
import Link from 'next/link';

import PushToggle from '@/components/PushToggle';
import StorageStatusBanner from '@/components/StorageStatusBanner';
import { useT } from '@/i18n/client';
import { getOpportunitiesByIds } from '@/lib/api';
import { daysUntil } from '@/lib/match-utils';
import { collectReminders, type ReminderInfo } from '@/lib/reminders';
import { getFavorites, getInteractionsFull } from '@/lib/supabase';
import type { InteractionRecord, InteractionType } from '@/lib/supabase';
import { useAuthUid } from '@/lib/use-auth-uid';

import { ProfessorUpdatesSection } from './ProfessorUpdatesSection';

type Replier = (key: string, vars?: Record<string, string | number>) => string;
type LoadStatus = 'loading' | 'ready' | 'error';

const STATUS_CONFIG: Record<InteractionType, { labelKey: string; icon: React.ElementType; color: string; bg: string }> = {
  contacted: { labelKey: 'tracker.status.contacted', icon: Send, color: 'text-sky-600', bg: 'bg-sky-50' },
  applied: { labelKey: 'tracker.status.applied', icon: Send, color: 'text-indigo-600', bg: 'bg-indigo-50' },
  replied: { labelKey: 'tracker.status.replied', icon: MessageSquare, color: 'text-emerald-600', bg: 'bg-emerald-50' },
  rejected: { labelKey: 'tracker.status.rejected', icon: XCircle, color: 'text-red-500', bg: 'bg-red-50' },
  interviewing: { labelKey: 'tracker.status.interviewing', icon: Users, color: 'text-violet-600', bg: 'bg-violet-50' },
  dismissed: { labelKey: 'tracker.status.dismissed', icon: XCircle, color: 'text-gray-400', bg: 'bg-gray-50' },
};

interface TrackedOpp {
  id: string;
  title?: string;
  organization?: string;
  opportunity_type?: string;
  status: InteractionType;
  notes?: string;
  remind_at?: string;
}

interface FavoriteDeadline {
  id: string;
  title?: string;
  organization?: string;
  deadline: string;
  deadlineIsEstimate: boolean | null;
  daysLeft: number;
}

interface ReminderRow extends ReminderInfo {
  title?: string;
  organization?: string;
}

interface SavedState { status: LoadStatus; count: number }
interface DeadlineState { status: LoadStatus; items: FavoriteDeadline[] }
interface TrackerState { status: LoadStatus; items: TrackedOpp[] }
interface ReminderState {
  status: LoadStatus;
  items: ReminderRow[];
  total: number;
  detailsUnavailable: boolean;
}

function sortDeadlines(a: FavoriteDeadline, b: FavoriteDeadline): number {
  const aPast = a.daysLeft < 0;
  const bPast = b.daysLeft < 0;
  if (aPast !== bPast) return aPast ? 1 : -1;
  return aPast ? b.daysLeft - a.daysLeft : a.daysLeft - b.daysLeft;
}

export default function DashboardPage() {
  const { t } = useT();
  const [saved, setSaved] = useState<SavedState>({ status: 'loading', count: 0 });
  const [deadlines, setDeadlines] = useState<DeadlineState>({ status: 'loading', items: [] });
  const [tracker, setTracker] = useState<TrackerState>({ status: 'loading', items: [] });
  const [reminders, setReminders] = useState<ReminderState>({
    status: 'loading',
    items: [],
    total: 0,
    detailsUnavailable: false,
  });
  // W14 cross-tab uid isolation: epoch bumps only on a real identity switch,
  // re-running the load below under the new auth context.
  const { epoch: authEpoch } = useAuthUid();

  useEffect(() => {
    let cancelled = false;

    /* eslint-disable react-hooks/set-state-in-effect --
       Reset before fetching — a no-op on mount, the isolation clear on an
       identity switch (stale Account-A metrics must never render for B).
       Must run synchronously before the async loads below kick off. */
    setSaved({ status: 'loading', count: 0 });
    setDeadlines({ status: 'loading', items: [] });
    setTracker({ status: 'loading', items: [] });
    setReminders({ status: 'loading', items: [], total: 0, detailsUnavailable: false });
    /* eslint-enable react-hooks/set-state-in-effect */

    async function loadFavorites() {
      let favoriteIds: Set<string>;
      try {
        favoriteIds = await getFavorites();
      } catch {
        if (!cancelled) {
          setSaved({ status: 'error', count: 0 });
          setDeadlines({ status: 'error', items: [] });
        }
        return;
      }
      if (cancelled) return;
      setSaved({ status: 'ready', count: favoriteIds.size });
      if (favoriteIds.size === 0) {
        setDeadlines({ status: 'ready', items: [] });
        return;
      }
      try {
        const opportunities = await getOpportunitiesByIds(Array.from(favoriteIds));
        if (cancelled) return;
        // The batch endpoint should already honor the IDs, but this client-side
        // allow-list is deliberate: a global or stale record can never leak
        // into the student's saved-deadline inbox.
        const items = opportunities
          .filter((opportunity) => {
            const id = typeof opportunity.id === 'string' ? opportunity.id : '';
            return favoriteIds.has(id) && typeof opportunity.deadline === 'string';
          })
          .map((opportunity): FavoriteDeadline | null => {
            const deadline = opportunity.deadline as string;
            const remaining = daysUntil(deadline);
            if (remaining === null) return null;
            return {
              id: opportunity.id as string,
              title: typeof opportunity.title === 'string' ? opportunity.title : undefined,
              organization: typeof opportunity.organization === 'string'
                ? opportunity.organization
                : undefined,
              deadline,
              deadlineIsEstimate: typeof opportunity.deadline_is_estimate === 'boolean'
                ? opportunity.deadline_is_estimate
                : null,
              daysLeft: remaining,
            };
          })
          .filter((item): item is FavoriteDeadline => item !== null)
          .sort(sortDeadlines)
          .slice(0, 8);
        setDeadlines({ status: 'ready', items });
      } catch {
        if (!cancelled) setDeadlines({ status: 'error', items: [] });
      }
    }

    async function loadTracker() {
      let interactions: Map<string, InteractionRecord>;
      try {
        interactions = await getInteractionsFull();
      } catch {
        if (!cancelled) {
          setTracker({ status: 'error', items: [] });
          setReminders({ status: 'error', items: [], total: 0, detailsUnavailable: false });
        }
        return;
      }
      if (cancelled) return;

      const allReminders = collectReminders(interactions);
      const reminderItems = allReminders.slice(0, 5);

      if (interactions.size === 0) {
        setTracker({ status: 'ready', items: [] });
        setReminders({ status: 'ready', items: [], total: 0, detailsUnavailable: false });
        return;
      }

      try {
        const trackedIds = Array.from(interactions.keys());
        const opportunities = await getOpportunitiesByIds(trackedIds);
        if (cancelled) return;
        const byId = new Map(
          opportunities
            .filter((o) => typeof o.id === 'string' && interactions.has(o.id as string))
            .map((o) => [o.id as string, o]),
        );
        setTracker({
          status: 'ready',
          items: trackedIds.map((id) => {
            const record = interactions.get(id)!;
            const opportunity = byId.get(id);
            return {
              id,
              title: typeof opportunity?.title === 'string' ? opportunity.title : undefined,
              organization: typeof opportunity?.organization === 'string'
                ? opportunity.organization
                : undefined,
              opportunity_type: typeof opportunity?.opportunity_type === 'string'
                ? opportunity.opportunity_type
                : undefined,
              status: record.type,
              notes: record.notes,
              remind_at: record.remind_at,
            };
          }),
        });
        setReminders({
          status: 'ready',
          total: allReminders.length,
          detailsUnavailable: false,
          items: reminderItems.map((item) => {
            const opportunity = byId.get(item.opportunityId);
            return {
              ...item,
              title: typeof opportunity?.title === 'string' ? opportunity.title : undefined,
              organization: typeof opportunity?.organization === 'string'
                ? opportunity.organization
                : undefined,
            };
          }),
        });
      } catch {
        if (cancelled) return;
        // Statuses and reminder dates still came from the student's persisted
        // tracker. Preserve those real actions and label only the missing
        // title lookup.
        setTracker({
          status: 'ready',
          items: Array.from(interactions.entries()).map(([id, record]) => ({
            id,
            status: record.type,
            notes: record.notes,
            remind_at: record.remind_at,
          })),
        });
        setReminders({
          status: 'ready',
          items: reminderItems,
          total: allReminders.length,
          detailsUnavailable: true,
        });
      }
    }

    void loadFavorites();
    void loadTracker();
    return () => { cancelled = true; };
  }, [authEpoch]);

  const statusCounts: Record<string, number> = { applied: 0, replied: 0, rejected: 0, interviewing: 0 };
  for (const item of tracker.items) {
    if (item.status in statusCounts) statusCounts[item.status] += 1;
  }
  const trackerReady = tracker.status === 'ready';

  return (
    <div className="mx-auto max-w-5xl px-4 py-10 sm:px-6 sm:py-16 lg:px-8">
      <header className="mb-8 sm:mb-10">
        <h1 className="text-2xl font-bold tracking-tight text-gray-900 sm:text-4xl">
          {t('dashboard.title')}
        </h1>
        <p className="mt-1.5 max-w-2xl text-[13px] text-gray-400 sm:mt-2 sm:text-[15px]">
          {t('dashboard.subtitle')}
        </p>
      </header>

      <StorageStatusBanner />

      <section aria-labelledby="dashboard-summary" className="mb-10">
        <h2 id="dashboard-summary" className="mb-4 text-sm font-semibold text-gray-900">
          {t('dashboard.summary.title')}
        </h2>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
          <StatCard
            testId="saved-summary"
            value={saved.status === 'ready' ? saved.count : null}
            label={t('dashboard.summary.saved')}
            color="text-amber-600"
          />
          <StatCard
            value={trackerReady ? statusCounts.applied : null}
            label={t('tracker.status.applied')}
            color="text-indigo-600"
          />
          <StatCard
            value={trackerReady ? statusCounts.replied : null}
            label={t('tracker.status.replied')}
            color="text-emerald-600"
          />
          <StatCard
            value={trackerReady ? statusCounts.interviewing : null}
            label={t('tracker.status.interviewing')}
            color="text-violet-600"
          />
          <StatCard
            value={trackerReady ? statusCounts.rejected : null}
            label={t('tracker.status.rejected')}
            color="text-red-500"
          />
        </div>
        <div className="mt-3 space-y-1">
          {saved.status === 'error' && (
            <p className="text-xs text-red-600">{t('dashboard.saved.errorTitle')}</p>
          )}
          {tracker.status === 'error' && (
            <p className="text-xs text-red-600">{t('dashboard.trackerSection.errorTitle')}</p>
          )}
        </div>
      </section>

      <div className="space-y-6">
        <DashboardSection
          icon={CalendarClock}
          title={t('dashboard.deadlines.title')}
          subtitle={t('dashboard.deadlines.subtitle')}
        >
          <DeadlineContent state={deadlines} savedCount={saved} t={t} />
        </DashboardSection>

        <DashboardSection
          icon={BellRing}
          title={t('dashboard.reminders.title')}
          subtitle={reminders.status === 'ready' && reminders.total > 0
            ? t('dashboard.reminders.pending', { count: reminders.total })
            : undefined}
          action={<PushToggle />}
        >
          <ReminderContent state={reminders} t={t} />
        </DashboardSection>

        <ProfessorUpdatesSection />

        <DashboardSection
          icon={BarChart3}
          title={t('dashboard.trackerSection.title')}
          subtitle={trackerReady && tracker.items.length > 0
            ? t('dashboard.trackerSection.count', { count: tracker.items.length })
            : undefined}
          action={(
            <Link
              href="/tracker"
              className="inline-flex items-center gap-1 text-xs font-semibold text-indigo-600 hover:text-indigo-700"
            >
              {t('dashboard.trackerSection.openBoard')}
              <ArrowRight className="h-3.5 w-3.5" aria-hidden="true" />
            </Link>
          )}
        >
          <TrackerContent state={tracker} t={t} />
        </DashboardSection>

        <section aria-labelledby="dashboard-roadmap-cta">
          <Link
            href="/roadmap"
            className="group flex items-center gap-4 rounded-3xl border border-violet-100 bg-gradient-to-br from-violet-50 via-white to-white p-5 shadow-sm transition hover:-translate-y-0.5 hover:shadow-md"
          >
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-white shadow-sm">
              <GraduationCap className="h-5 w-5 text-violet-700" aria-hidden="true" />
            </div>
            <div className="min-w-0 flex-1">
              <h2 id="dashboard-roadmap-cta" className="text-sm font-bold text-gray-950">
                {t('dashboard.roadmapCta.title')}
              </h2>
              <p className="mt-0.5 text-[13px] leading-5 text-gray-500">
                {t('dashboard.roadmapCta.body')}
              </p>
            </div>
            <ArrowRight
              className="h-4 w-4 shrink-0 text-violet-500 transition-transform group-hover:translate-x-0.5"
              aria-hidden="true"
            />
          </Link>
        </section>
      </div>
    </div>
  );
}

function StatCard({
  value,
  label,
  color,
  testId,
}: {
  value: number | null;
  label: string;
  color: string;
  testId?: string;
}) {
  return (
    <div
      data-testid={testId}
      className="rounded-2xl border border-gray-100 bg-white px-4 py-4 shadow-sm"
    >
      <p className={`text-2xl font-bold tabular-nums tracking-tight ${color}`}>
        {value ?? '—'}
      </p>
      <p className="mt-1 text-[10px] font-semibold uppercase tracking-[0.12em] text-gray-400">
        {label}
      </p>
    </div>
  );
}

function DashboardSection({
  icon: Icon,
  title,
  subtitle,
  action,
  children,
}: {
  icon: React.ElementType;
  title: string;
  subtitle?: string;
  action?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section className="overflow-hidden rounded-3xl border border-gray-100 bg-white shadow-sm">
      <div className="flex items-center gap-2.5 border-b border-gray-100 px-6 py-4">
        <Icon className="h-4 w-4 text-gray-500" aria-hidden="true" />
        <h2 className="text-sm font-semibold text-gray-900">{title}</h2>
        {subtitle && <span className="text-[11px] text-gray-400">{subtitle}</span>}
        {action && <div className="ml-auto">{action}</div>}
      </div>
      {children}
    </section>
  );
}

function LoadingRow({ label }: { label: string }) {
  return (
    <div className="flex items-center justify-center gap-2 px-6 py-10 text-xs text-gray-400">
      <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
      {label}
    </div>
  );
}

function ErrorRow({ title, body }: { title: string; body: string }) {
  return (
    <div className="px-6 py-9 text-center">
      <p className="text-sm font-semibold text-red-600">{title}</p>
      <p className="mt-1 text-xs text-gray-500">{body}</p>
    </div>
  );
}

function DeadlineContent({
  state,
  savedCount,
  t,
}: {
  state: DeadlineState;
  savedCount: SavedState;
  t: Replier;
}) {
  if (state.status === 'loading') return <LoadingRow label={t('dashboard.loading')} />;
  if (state.status === 'error') {
    return (
      <ErrorRow
        title={t('dashboard.deadlines.errorTitle')}
        body={t('dashboard.deadlines.errorBody')}
      />
    );
  }
  if (state.items.length === 0) {
    const noSaves = savedCount.status === 'ready' && savedCount.count === 0;
    return (
      <div className="px-6 py-9 text-center">
        <BookOpenCheck className="mx-auto h-7 w-7 text-gray-300" aria-hidden="true" />
        <p className="mt-3 text-sm font-semibold text-gray-700">
          {t(noSaves ? 'dashboard.deadlines.noSavesTitle' : 'dashboard.deadlines.emptyTitle')}
        </p>
        <p className="mt-1 text-xs text-gray-500">
          {t(noSaves ? 'dashboard.deadlines.noSavesBody' : 'dashboard.deadlines.emptyBody')}
        </p>
        {noSaves && (
          <Link
            href="/results"
            className="mt-4 inline-flex items-center gap-1 text-xs font-semibold text-indigo-600 hover:text-indigo-700"
          >
            {t('dashboard.deadlines.noSavesCta')}
            <ArrowRight className="h-3.5 w-3.5" aria-hidden="true" />
          </Link>
        )}
      </div>
    );
  }
  return (
    <ul className="divide-y divide-gray-50">
      {state.items.map((item) => {
        const exact = item.deadlineIsEstimate === false;
        const urgent = exact && item.daysLeft >= 0 && item.daysLeft <= 7;
        const precisionLabel = item.deadlineIsEstimate === true
          ? t('dashboard.deadlines.estimated')
          : item.deadlineIsEstimate === null
            ? t('dashboard.deadlines.verifyDate')
            : null;
        return (
          <li key={item.id}>
            <Link
              href={`/opportunities/${encodeURIComponent(item.id)}`}
              className="flex min-w-0 items-center gap-4 px-6 py-4 transition-colors hover:bg-gray-50/60 focus:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-indigo-500"
            >
              <div className={`w-20 shrink-0 text-right ${urgent ? 'text-red-600' : 'text-amber-600'}`}>
                <p className="text-xs font-bold">
                  {exact ? deadlineLabel(item.daysLeft, t) : precisionLabel}
                </p>
                <p className="mt-0.5 text-[10px] text-gray-400">{item.deadline}</p>
              </div>
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium text-gray-900">
                  {item.title ?? t('dashboard.unknownTarget')}
                </p>
                {item.organization && (
                  <p className="mt-0.5 truncate text-xs text-gray-400">{item.organization}</p>
                )}
              </div>
              <ArrowRight className="h-4 w-4 shrink-0 text-gray-300" aria-hidden="true" />
            </Link>
          </li>
        );
      })}
    </ul>
  );
}

function ReminderContent({ state, t }: { state: ReminderState; t: Replier }) {
  if (state.status === 'loading') return <LoadingRow label={t('dashboard.loading')} />;
  if (state.status === 'error') {
    return (
      <ErrorRow
        title={t('dashboard.reminders.errorTitle')}
        body={t('dashboard.reminders.errorBody')}
      />
    );
  }
  if (state.items.length === 0) {
    return (
      <div className="px-6 py-9 text-center">
        <BellRing className="mx-auto h-7 w-7 text-gray-300" aria-hidden="true" />
        <p className="mt-3 text-sm font-semibold text-gray-700">
          {t('dashboard.reminders.emptyTitle')}
        </p>
        <p className="mt-1 text-xs text-gray-500">{t('dashboard.reminders.emptyBody')}</p>
      </div>
    );
  }
  return (
    <>
      {state.detailsUnavailable && (
        <p className="border-b border-amber-100 bg-amber-50 px-6 py-2 text-[11px] text-amber-700">
          {t('dashboard.reminders.detailsUnavailable')}
        </p>
      )}
      <ul className="divide-y divide-gray-50">
        {state.items.map((item) => (
          <li key={item.opportunityId}>
            <Link
              href={`/opportunities/${encodeURIComponent(item.opportunityId)}`}
              className="flex min-w-0 items-center gap-4 px-6 py-4 transition-colors hover:bg-gray-50/60 focus:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-indigo-500"
            >
              <div className={`w-20 shrink-0 text-right ${reminderColor(item)}`}>
                <p className="text-xs font-bold">{reminderLabel(item, t)}</p>
                <p className="mt-0.5 text-[10px] text-gray-400">{item.remindAt}</p>
              </div>
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium text-gray-900">
                  {item.title ?? t('dashboard.unknownTarget')}
                </p>
                {item.notes ? (
                  <p className="mt-0.5 flex items-center gap-1 truncate text-xs text-gray-400">
                    <StickyNote className="h-3 w-3 shrink-0" aria-hidden="true" />
                    {item.notes}
                  </p>
                ) : item.organization ? (
                  <p className="mt-0.5 truncate text-xs text-gray-400">{item.organization}</p>
                ) : null}
              </div>
              <ArrowRight className="h-4 w-4 shrink-0 text-gray-300" aria-hidden="true" />
            </Link>
          </li>
        ))}
      </ul>
    </>
  );
}

function TrackerContent({ state, t }: { state: TrackerState; t: Replier }) {
  if (state.status === 'loading') return <LoadingRow label={t('dashboard.loading')} />;
  if (state.status === 'error') {
    return (
      <ErrorRow
        title={t('dashboard.trackerSection.errorTitle')}
        body={t('dashboard.trackerSection.errorBody')}
      />
    );
  }
  if (state.items.length === 0) {
    return (
      <div className="px-6 py-9 text-center">
        <BarChart3 className="mx-auto h-7 w-7 text-gray-300" aria-hidden="true" />
        <p className="mt-3 text-sm font-semibold text-gray-700">
          {t('dashboard.trackerSection.emptyTitle')}
        </p>
        <p className="mt-1 text-xs text-gray-500">{t('dashboard.trackerSection.emptyBody')}</p>
        <Link
          href="/results"
          className="mt-4 inline-flex items-center gap-1 text-xs font-semibold text-indigo-600 hover:text-indigo-700"
        >
          {t('dashboard.trackerSection.emptyCta')}
          <ArrowRight className="h-3.5 w-3.5" aria-hidden="true" />
        </Link>
      </div>
    );
  }
  return (
    <div className="divide-y divide-gray-50">
      {state.items.map((item) => {
        const cfg = STATUS_CONFIG[item.status];
        const Icon = cfg.icon;
        return (
          <Link
            key={item.id}
            href={`/opportunities/${encodeURIComponent(item.id)}`}
            className="flex items-center gap-4 px-6 py-3.5 transition-colors hover:bg-gray-50/50 focus:outline-none focus-visible:bg-gray-50"
          >
            <div className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-lg ${cfg.bg}`}>
              <Icon className={`h-4 w-4 ${cfg.color}`} aria-hidden="true" />
            </div>
            <div className="min-w-0 flex-1">
              <p className="truncate text-[14px] font-medium text-gray-900">
                {item.title ?? t('dashboard.unknownTarget')}
              </p>
              <p className="truncate text-[12px] text-gray-400">
                {[item.organization, item.opportunity_type].filter(Boolean).join(' · ')}
              </p>
            </div>
            <div className="flex shrink-0 items-center gap-2">
              {item.notes && (
                <StickyNote className="h-3.5 w-3.5 text-gray-300" aria-label={t('dashboard.trackerSection.hasNotes')} />
              )}
              {item.remind_at && (
                <BellRing className="h-3.5 w-3.5 text-amber-400" aria-label={t('dashboard.trackerSection.hasReminder')} />
              )}
              <span className={`rounded-full px-2.5 py-1 text-[11px] font-semibold ${cfg.bg} ${cfg.color}`}>
                {t(cfg.labelKey)}
              </span>
            </div>
          </Link>
        );
      })}
    </div>
  );
}

function deadlineLabel(days: number, t: Replier): string {
  if (days < 0) return t('dashboard.deadlines.past');
  if (days === 0) return t('dashboard.deadlines.today');
  if (days === 1) return t('dashboard.deadlines.tomorrow');
  return t('dashboard.deadlines.inDays', { days });
}

function reminderLabel(reminder: ReminderInfo, t: Replier): string {
  if (reminder.status === 'overdue') {
    return reminder.daysAway === -1
      ? t('dashboard.reminders.overdueSingle')
      : t('dashboard.reminders.overdue', { days: -reminder.daysAway });
  }
  if (reminder.status === 'today') return t('dashboard.reminders.today');
  if (reminder.status === 'tomorrow') return t('dashboard.reminders.tomorrow');
  return t('dashboard.reminders.inDays', { days: reminder.daysAway });
}

function reminderColor(reminder: ReminderInfo): string {
  if (reminder.status === 'overdue') return 'text-red-600';
  if (reminder.status === 'today' || reminder.status === 'tomorrow') return 'text-amber-600';
  return 'text-gray-600';
}
