'use client';

import { useEffect, useState } from 'react';
import {
  AlertTriangle,
  ArrowRight,
  BarChart3,
  BellRing,
  BookOpenCheck,
  CalendarClock,
  Database,
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
import { getShortlistOpportunities, getStats } from '@/lib/api';
import { daysUntil, opportunityRecordKind } from '@/lib/match-utils';
import { RELEASE_SCOPE } from '@/lib/release-scope';
import { targetPosture } from '@/lib/target-truth';
import { canDeliverReminder, collectReminders, type ReminderInfo } from '@/lib/reminders';
import { getFavorites, getInteractionsFull } from '@/lib/supabase';
import type { InteractionRecord, InteractionType } from '@/lib/supabase';
import { useAuthUid } from '@/lib/use-auth-uid';

import { ProfessorUpdatesSection } from './ProfessorUpdatesSection';

type Replier = (key: string, vars?: Record<string, string | number>) => string;
type LoadStatus = 'loading' | 'ready' | 'error';

/** How many reminders the preview shows. Applied AFTER the deliverability
 *  partition, never before — see loadTracker. */
const REMINDER_PREVIEW_LIMIT = 5;

/**
 * Whether a record is a listing this build still calls live.
 *
 * The batch endpoint hands back loose records, so this narrows once and both
 * consumers below read the same answer: the saved-deadline inbox, and the
 * type label on a tracked row. Both were saying things about an offer.
 */
function isCurrentListing(opportunity: Record<string, unknown>): boolean {
  const record = opportunity as Parameters<typeof targetPosture>[0];
  return opportunityRecordKind(record) === 'listing'
    && targetPosture(record) === 'actionable';
}

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
/** `unavailableCount`: saved/tracked ids the batch fetch could not resolve.
 *  Reported, never silently dropped — the same contract /favorites
 *  (use-favorites-data's `unavailableCount`) and /tracker
 *  (use-tracker-data's `unavailableItems`) already hold. A favorite that
 *  vanished from the corpus must read as "couldn't be loaded", never as
 *  "you have no deadlines". */
interface DeadlineState { status: LoadStatus; items: FavoriteDeadline[]; unavailableCount: number }
interface TrackerState { status: LoadStatus; items: TrackedOpp[]; unavailableCount: number }
interface ReminderState {
  status: LoadStatus;
  items: ReminderRow[];
  total: number;
  detailsUnavailable: boolean;
  /** Of the reminder rows actually rendered, how many point at an
   *  opportunity the corpus could not resolve. */
  unavailableCount: number;
}
/** Corpus refresh age in hours, measured once when the stats response lands
 *  (never during render — the age must not drift between re-renders).
 *  `ageHours === null` while ready means the backend itself does not know
 *  (see backend/lib/corpus_freshness.py) — rendered as an explicit unknown,
 *  never as fresh. */
interface FreshnessState { status: LoadStatus; ageHours: number | null }

function sortDeadlines(a: FavoriteDeadline, b: FavoriteDeadline): number {
  const aPast = a.daysLeft < 0;
  const bPast = b.daysLeft < 0;
  if (aPast !== bPast) return aPast ? 1 : -1;
  return aPast ? b.daysLeft - a.daysLeft : a.daysLeft - b.daysLeft;
}

export default function DashboardPage() {
  const { t } = useT();
  const [saved, setSaved] = useState<SavedState>({ status: 'loading', count: 0 });
  const [deadlines, setDeadlines] = useState<DeadlineState>({
    status: 'loading',
    items: [],
    unavailableCount: 0,
  });
  const [tracker, setTracker] = useState<TrackerState>({
    status: 'loading',
    items: [],
    unavailableCount: 0,
  });
  const [reminders, setReminders] = useState<ReminderState>({
    status: 'loading',
    items: [],
    total: 0,
    detailsUnavailable: false,
    unavailableCount: 0,
  });
  // Manual re-run of the loads below. The stat tiles and section error
  // states are dead ends without it: nothing else on this page re-triggers
  // the effect for the SAME identity.
  const [reloadNonce, setReloadNonce] = useState(0);
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
    setDeadlines({ status: 'loading', items: [], unavailableCount: 0 });
    setTracker({ status: 'loading', items: [], unavailableCount: 0 });
    setReminders({
      status: 'loading', items: [], total: 0, detailsUnavailable: false, unavailableCount: 0,
    });
    /* eslint-enable react-hooks/set-state-in-effect */

    async function loadFavorites() {
      let favoriteIds: Set<string>;
      try {
        favoriteIds = await getFavorites();
      } catch {
        if (!cancelled) {
          setSaved({ status: 'error', count: 0 });
          setDeadlines({ status: 'error', items: [], unavailableCount: 0 });
        }
        return;
      }
      if (cancelled) return;
      setSaved({ status: 'ready', count: favoriteIds.size });
      if (favoriteIds.size === 0) {
        setDeadlines({ status: 'ready', items: [], unavailableCount: 0 });
        return;
      }
      try {
        // getShortlistOpportunities — the fail-closed fetch /favorites and
        // /tracker already use — reports which requested ids the corpus
        // could not resolve, instead of silently returning a shrunk list
        // the way getOpportunitiesByIds does.
        const { opportunities, unavailableIds } =
          await getShortlistOpportunities(Array.from(favoriteIds));
        if (cancelled) return;
        // The batch endpoint should already honor the IDs, but this client-side
        // allow-list is deliberate: a global or stale record can never leak
        // into the student's saved-deadline inbox.
        const items = opportunities
          .filter((opportunity) => {
            const id = typeof opportunity.id === 'string' ? opportunity.id : '';
            // A date on this page is an instruction: act before it. Excluding
            // only faculty rows meant a listing that closed after it was saved
            // still counted down here — the one surface a student checks
            // precisely to decide what to do this week.
            return favoriteIds.has(id)
              && isCurrentListing(opportunity)
              && typeof opportunity.deadline === 'string';
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
        setDeadlines({ status: 'ready', items, unavailableCount: unavailableIds.length });
      } catch {
        if (!cancelled) setDeadlines({ status: 'error', items: [], unavailableCount: 0 });
      }
    }

    async function loadTracker() {
      let interactions: Map<string, InteractionRecord>;
      try {
        interactions = await getInteractionsFull();
      } catch {
        if (!cancelled) {
          setTracker({ status: 'error', items: [], unavailableCount: 0 });
          setReminders({
            status: 'error', items: [], total: 0, detailsUnavailable: false, unavailableCount: 0,
          });
        }
        return;
      }
      if (cancelled) return;

      const allReminders = collectReminders(interactions);
      // 'dismissed' is the hide-everywhere status: Tracker excludes it from
      // every column and collectReminders drops it. This section was the one
      // place it still appeared, rebuilt straight from the raw interactions
      // map — so a target the student explicitly put away came back on the
      // page they see first.
      const visible = Array.from(interactions.entries())
        .filter(([, record]) => record.type !== 'dismissed');
      const visibleIds = visible.map(([id]) => id);
      const visibleIdSet = new Set(visibleIds);

      if (interactions.size === 0) {
        setTracker({ status: 'ready', items: [], unavailableCount: 0 });
        setReminders({
          status: 'ready', items: [], total: 0, detailsUnavailable: false, unavailableCount: 0,
        });
        return;
      }

      try {
        const { opportunities, unavailableIds } = await getShortlistOpportunities(visibleIds);
        if (cancelled) return;
        const byId = new Map(
          opportunities
            .filter((o) => typeof o.id === 'string' && visibleIdSet.has(o.id as string))
            .map((o) => [o.id as string, o]),
        );
        // A tracked opportunity the corpus can no longer resolve still shows
        // its real status/notes below — but "Unknown opportunity" is a title
        // placeholder, not an explanation. Count them so the section can say
        // what actually happened.
        setTracker({
          status: 'ready',
          unavailableCount: unavailableIds.length,
          items: visible.map(([id, record]) => {
            const opportunity = byId.get(id);
            return {
              id,
              title: typeof opportunity?.title === 'string' ? opportunity.title : undefined,
              organization: typeof opportunity?.organization === 'string'
                ? opportunity.organization
                : undefined,
              // The record's own claim about what it is, published only where
              // it still describes something on offer. The student's status,
              // notes and reminder below are their own record of their own
              // process and travel whatever the target's posture.
              opportunity_type: opportunity && isCurrentListing(opportunity)
                && typeof opportunity.opportunity_type === 'string'
                ? opportunity.opportunity_type
                : undefined,
              status: record.type,
              notes: record.notes,
              remind_at: record.remind_at,
            };
          }),
        });
        // Partitioned over ALL reminders, then sliced. Slicing first meant
        // five undeliverable rows at the top hid the sixth, which was the
        // only one that would actually fire — the student's real next action,
        // pushed off the page by rows asserting notifications that never
        // arrive.
        //
        // The cron sends for a target it still calls actionable. Posture, not
        // current-listing: a live faculty contact is what most reminders are
        // set on, and the cron does send for those.
        const deliverableAll = allReminders.filter((item) => {
          const opportunity = byId.get(item.opportunityId);
          return canDeliverReminder(
            opportunity as Parameters<typeof canDeliverReminder>[0],
            interactions.get(item.opportunityId)?.type,
          );
        });
        const deliverable = deliverableAll.slice(0, REMINDER_PREVIEW_LIMIT);
        setReminders({
          status: 'ready',
          // "N pending" counts what will actually be delivered. Counting every
          // stored reminder told the student a number of notifications were
          // coming, some of which never would.
          total: deliverableAll.length,
          detailsUnavailable: false,
          // Every reminder that will not fire, whether its target is closed,
          // unreviewed, or could not be resolved at all. They are not "due",
          // and they are not lost either — the note points at the tracker.
          unavailableCount: allReminders.length - deliverableAll.length,
          items: deliverable.map((item) => {
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
          // The lookup failed wholesale — that is the `detailsUnavailable`
          // state below, not a claim about specific missing records.
          unavailableCount: 0,
          // `visible`, not the raw map: the same hide-everywhere rule applies
          // when the lookup fails. A failed corpus read is no reason to
          // resurrect a target the student put away.
          items: visible.map(([id, record]) => ({
            id,
            status: record.type,
            notes: record.notes,
            remind_at: record.remind_at,
          })),
        });
        setReminders({
          status: 'ready',
          // The batch lookup failed wholesale, so NO target's posture is
          // known — and the cron fails closed on exactly that. None of these
          // can be presented as due; they all need review in the tracker.
          items: [],
          total: 0,
          detailsUnavailable: true,
          unavailableCount: allReminders.length,
        });
      }
    }

    void loadFavorites();
    void loadTracker();
    return () => { cancelled = true; };
  }, [authEpoch, reloadNonce]);

  const retry = () => setReloadNonce((n) => n + 1);

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

      <CorpusFreshnessLine t={t} />

      <section aria-labelledby="dashboard-summary" className="mb-10">
        <h2 id="dashboard-summary" className="mb-4 text-sm font-semibold text-gray-900">
          {t('dashboard.summary.title')}
        </h2>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
          {/* Each tile carries its OWN load state. Before W16 every
              non-ready tile rendered the same em-dash, so "still loading",
              "the request failed", and "genuinely unknown" were
              indistinguishable — and a fabricated-looking value was one
              regression away. A real 0 must still render as 0. */}
          <StatCard
            testId="saved-summary"
            state={saved.status}
            value={saved.count}
            label={t('dashboard.summary.saved')}
            color="text-amber-600"
            t={t}
          />
          <StatCard
            testId="applied-summary"
            state={tracker.status}
            value={statusCounts.applied}
            label={t('tracker.status.applied')}
            color="text-indigo-600"
            t={t}
          />
          <StatCard
            testId="replied-summary"
            state={tracker.status}
            value={statusCounts.replied}
            label={t('tracker.status.replied')}
            color="text-emerald-600"
            t={t}
          />
          <StatCard
            testId="interviewing-summary"
            state={tracker.status}
            value={statusCounts.interviewing}
            label={t('tracker.status.interviewing')}
            color="text-violet-600"
            t={t}
          />
          <StatCard
            testId="rejected-summary"
            state={tracker.status}
            value={statusCounts.rejected}
            label={t('tracker.status.rejected')}
            color="text-red-500"
            t={t}
          />
        </div>
        <div className="mt-3 space-y-1">
          {saved.status === 'error' && (
            <p className="flex items-center gap-2 text-xs text-red-600">
              {t('dashboard.saved.errorTitle')}
              <RetryButton onClick={retry} t={t} />
            </p>
          )}
          {tracker.status === 'error' && (
            <p className="flex items-center gap-2 text-xs text-red-600">
              {t('dashboard.trackerSection.errorTitle')}
              <RetryButton onClick={retry} t={t} />
            </p>
          )}
        </div>
      </section>

      <div className="space-y-6">
        <DashboardSection
          icon={CalendarClock}
          title={t('dashboard.deadlines.title')}
          subtitle={t('dashboard.deadlines.subtitle')}
        >
          <DeadlineContent state={deadlines} savedCount={saved} onRetry={retry} t={t} />
        </DashboardSection>

        <DashboardSection
          icon={BellRing}
          title={t('dashboard.reminders.title')}
          subtitle={reminders.status === 'ready' && reminders.total > 0
            ? t('dashboard.reminders.pending', { count: reminders.total })
            : undefined}
          action={<PushToggle />}
        >
          <ReminderContent state={reminders} onRetry={retry} t={t} />
        </DashboardSection>

        {RELEASE_SCOPE.professorSignals && <ProfessorUpdatesSection />}

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
          <TrackerContent state={tracker} onRetry={retry} t={t} />
        </DashboardSection>

        {RELEASE_SCOPE.roadmap && (
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
        )}
      </div>
    </div>
  );
}

/**
 * One tile, four visually distinct states:
 *   loading → a pulsing placeholder (plus screen-reader text)
 *   error   → a red "unavailable" affordance; the section's retry sits
 *             immediately below the grid
 *   ready   → the number, INCLUDING a real 0 (the whole point of W14: a
 *             true zero is data, not an absence)
 *   unknown → '—', now reserved for exactly that: `value === null` on a
 *             load that genuinely succeeded without a figure.
 * `data-state` is part of the contract the tests pin.
 */
function StatCard({
  state,
  value,
  label,
  color,
  testId,
  t,
}: {
  state: LoadStatus;
  value: number | null;
  label: string;
  color: string;
  testId?: string;
  t: Replier;
}) {
  const resolved = state === 'ready' ? (value === null ? 'unknown' : 'ready') : state;
  return (
    <div
      data-testid={testId}
      data-state={resolved}
      className="rounded-2xl border border-gray-100 bg-white px-4 py-4 shadow-sm"
    >
      {resolved === 'loading' && (
        <div className="flex h-8 items-center">
          <span
            data-testid={testId ? `${testId}-skeleton` : undefined}
            className="block h-5 w-10 animate-pulse rounded bg-gray-100"
          />
          <span className="sr-only">{t('dashboard.loading')}</span>
        </div>
      )}
      {resolved === 'error' && (
        <p className="flex h-8 items-center gap-1.5 text-[13px] font-semibold text-red-600">
          <AlertTriangle className="h-4 w-4 shrink-0" aria-hidden="true" />
          {t('dashboard.summary.unavailable')}
        </p>
      )}
      {(resolved === 'ready' || resolved === 'unknown') && (
        <p className={`text-2xl font-bold tabular-nums tracking-tight ${color}`}>
          {resolved === 'ready' ? value : '—'}
        </p>
      )}
      <p className="mt-1 text-[10px] font-semibold uppercase tracking-[0.12em] text-gray-400">
        {label}
      </p>
    </div>
  );
}

function RetryButton({ onClick, t }: { onClick: () => void; t: Replier }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="rounded font-semibold text-indigo-600 underline-offset-2 hover:text-indigo-700 hover:underline focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500"
    >
      {t('common.retry')}
    </button>
  );
}

/**
 * "N saved/tracked items couldn't be loaded" — the dashboard's copy of the
 * contract /favorites (`unavailableCount`) and /tracker (`unavailableItems`)
 * already keep: an id the corpus cannot resolve is REPORTED, never silently
 * dropped from a list and never folded into a zero.
 */
function UnavailableNote({ count, messageKey, t }: { count: number; messageKey: string; t: Replier }) {
  return (
    <p
      data-testid="dashboard-unavailable-note"
      className="flex items-center gap-2 border-b border-amber-100 bg-amber-50 px-6 py-2 text-[11px] text-amber-700"
    >
      <AlertTriangle className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
      {t(messageKey, { count })}
    </p>
  );
}

// Same boundaries the admin banner uses (app/admin/FreshnessBanner.tsx
// ~:12-13). Deliberately the SAME numbers, not a second opinion about what
// "stale" means — the operator alert and the student-facing line must never
// disagree about whether the corpus is current.
const FRESHNESS_WARN_HOURS = 72;
const FRESHNESS_STALE_HOURS = 96;

type FreshnessLevel = 'fresh' | 'warn' | 'stale';

function freshnessLevel(ageHours: number): FreshnessLevel {
  if (ageHours >= FRESHNESS_STALE_HOURS) return 'stale';
  if (ageHours >= FRESHNESS_WARN_HOURS) return 'warn';
  return 'fresh';
}

function freshnessAge(ageHours: number, t: Replier): string {
  if (ageHours < 1 / 60) return t('dashboard.freshness.justNow');
  if (ageHours < 1) return t('dashboard.freshness.minutesAgo', { n: Math.round(ageHours * 60) });
  if (ageHours < 48) return t('dashboard.freshness.hoursAgo', { n: Math.round(ageHours) });
  return t('dashboard.freshness.daysAgo', { n: Math.round(ageHours / 24) });
}

/**
 * The only user-facing corpus-freshness signal in the product.
 *
 * `last_updated_at` was null in production until the backend read the
 * committed collector snapshot (backend/lib/corpus_freshness.py), so this
 * line is only honest if it treats null as UNKNOWN — never as "just now",
 * and never as silence that reads like everything is fine. A failed stats
 * fetch is the same claim: we do not know.
 */
function CorpusFreshnessLine({ t }: { t: Replier }) {
  const [freshness, setFreshness] = useState<FreshnessState>({ status: 'loading', ageHours: null });

  useEffect(() => {
    let cancelled = false;
    getStats()
      .then((stats) => {
        if (cancelled) return;
        const iso = typeof stats.last_updated_at === 'string' ? stats.last_updated_at : null;
        const parsed = iso === null ? NaN : new Date(iso).getTime();
        // Measured here, not in render: a re-render must not silently age
        // the line, and an unparseable timestamp is unknown, not epoch-old.
        setFreshness({
          status: 'ready',
          ageHours: Number.isNaN(parsed) ? null : (Date.now() - parsed) / (1000 * 60 * 60),
        });
      })
      .catch(() => {
        if (!cancelled) setFreshness({ status: 'error', ageHours: null });
      });
    return () => { cancelled = true; };
  }, []);

  if (freshness.status === 'loading') {
    return (
      <p
        data-testid="corpus-freshness"
        data-state="loading"
        className="mb-6 flex items-center gap-2 text-[11px] text-gray-400"
      >
        <Database className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
        {t('dashboard.freshness.checking')}
      </p>
    );
  }

  const ageHours = freshness.ageHours;
  if (freshness.status === 'error' || ageHours === null) {
    return (
      <p
        data-testid="corpus-freshness"
        data-state="unknown"
        className="mb-6 flex items-center gap-2 text-[11px] text-gray-500"
      >
        <Database className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
        <span className="font-medium text-gray-600">{t('dashboard.freshness.label')}</span>
        {t('dashboard.freshness.unknown')}
      </p>
    );
  }

  const level = freshnessLevel(ageHours);
  const tone = level === 'stale'
    ? 'text-red-600'
    : level === 'warn'
      ? 'text-amber-700'
      : 'text-emerald-700';
  return (
    <p
      data-testid="corpus-freshness"
      data-state={level}
      className={`mb-6 flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] ${tone}`}
    >
      <Database className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
      <span className="font-medium">{t('dashboard.freshness.label')}</span>
      <span>{t('dashboard.freshness.updated', { age: freshnessAge(ageHours, t) })}</span>
      {level !== 'fresh' && (
        <span className="font-medium">
          {t(level === 'stale' ? 'dashboard.freshness.staleNote' : 'dashboard.freshness.warnNote')}
        </span>
      )}
    </p>
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

function ErrorRow({
  title,
  body,
  onRetry,
  t,
}: {
  title: string;
  body: string;
  onRetry?: () => void;
  t: Replier;
}) {
  return (
    <div className="px-6 py-9 text-center">
      <p className="text-sm font-semibold text-red-600">{title}</p>
      <p className="mt-1 text-xs text-gray-500">{body}</p>
      {onRetry && (
        <p className="mt-3 text-xs">
          <RetryButton onClick={onRetry} t={t} />
        </p>
      )}
    </div>
  );
}

function DeadlineContent({
  state,
  savedCount,
  onRetry,
  t,
}: {
  state: DeadlineState;
  savedCount: SavedState;
  onRetry: () => void;
  t: Replier;
}) {
  if (state.status === 'loading') return <LoadingRow label={t('dashboard.loading')} />;
  if (state.status === 'error') {
    return (
      <ErrorRow
        title={t('dashboard.deadlines.errorTitle')}
        body={t('dashboard.deadlines.errorBody')}
        onRetry={onRetry}
        t={t}
      />
    );
  }
  if (state.items.length === 0 && state.unavailableCount > 0) {
    // Every saved item that could have shown a deadline is unresolvable.
    // Claiming "none of your saves list a deadline" here would be a
    // fabrication; say what actually happened instead.
    return (
      <>
        <UnavailableNote
          count={state.unavailableCount}
          messageKey="dashboard.unavailable.saved"
          t={t}
        />
        <div className="px-6 py-9 text-center">
          <p className="text-xs text-gray-500">{t('dashboard.unavailable.body')}</p>
          <p className="mt-3 text-xs">
            <RetryButton onClick={onRetry} t={t} />
          </p>
        </div>
      </>
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
    <>
      {state.unavailableCount > 0 && (
        <UnavailableNote
          count={state.unavailableCount}
          messageKey="dashboard.unavailable.saved"
          t={t}
        />
      )}
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
    </>
  );
}

function ReminderContent({
  state,
  onRetry,
  t,
}: {
  state: ReminderState;
  onRetry: () => void;
  t: Replier;
}) {
  if (state.status === 'loading') return <LoadingRow label={t('dashboard.loading')} />;
  if (state.status === 'error') {
    return (
      <ErrorRow
        title={t('dashboard.reminders.errorTitle')}
        body={t('dashboard.reminders.errorBody')}
        onRetry={onRetry}
        t={t}
      />
    );
  }
  {/* "No reminders set" only when that is actually true. Returning it on an
      empty item list swallowed the needs-review note in the one case it
      matters most: every reminder the student has is on a target the cron
      will skip, so the page would say they had set none. */}
  if (state.items.length === 0 && state.unavailableCount === 0) {
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
      {state.unavailableCount > 0 && (
        // Its own note, not the shared UnavailableNote. Two reasons: the copy
        // is different (these mostly resolved fine — they are closed,
        // unreviewed, or in a status the cron does not select, which is not
        // "couldn't be loaded"), and the sentence tells the student to open
        // their tracker, which has to be an actual link rather than an
        // instruction they cannot follow.
        <p
          data-testid="dashboard-reminders-needs-review"
          className="flex items-center gap-2 border-b border-amber-100 bg-amber-50 px-6 py-2 text-[11px] text-amber-700"
        >
          <AlertTriangle className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
          <span>{t('dashboard.reminders.needsReview', { count: state.unavailableCount })}</span>
          <Link href="/tracker" className="font-semibold underline underline-offset-2">
            {t('dashboard.trackerSection.openBoard')}
          </Link>
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

function TrackerContent({
  state,
  onRetry,
  t,
}: {
  state: TrackerState;
  onRetry: () => void;
  t: Replier;
}) {
  if (state.status === 'loading') return <LoadingRow label={t('dashboard.loading')} />;
  if (state.status === 'error') {
    return (
      <ErrorRow
        title={t('dashboard.trackerSection.errorTitle')}
        body={t('dashboard.trackerSection.errorBody')}
        onRetry={onRetry}
        t={t}
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
    <>
      {state.unavailableCount > 0 && (
        <UnavailableNote
          count={state.unavailableCount}
          messageKey="dashboard.unavailable.tracked"
          t={t}
        />
      )}
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
    </>
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
