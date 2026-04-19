'use client';

import { useState, useEffect, useMemo } from 'react';
import {
  AlertCircle,
  Send,
  MessageSquare,
  XCircle,
  Users,
  BarChart3,
  ArrowRight,
  Clock,
  ExternalLink,
  BellRing,
  StickyNote,
} from 'lucide-react';
import { useRouter } from 'next/navigation';
import { getStats, getUpcomingDeadlines, getOpportunitiesByIds } from '@/lib/api';
import { useT } from '@/i18n/client';
import type { UpcomingDeadline } from '@/lib/api';
import { getFavorites, getInteractionsFull } from '@/lib/supabase';
import type { InteractionType, InteractionRecord } from '@/lib/supabase';
import type { StatsResponse } from '@/lib/types';
import { collectReminders, formatReminderLabel, type ReminderInfo } from '@/lib/reminders';
import PushToggle from '@/components/PushToggle';

const STATUS_CONFIG: Record<InteractionType, { label: string; icon: React.ElementType; color: string; bg: string }> = {
  applied: { label: 'Applied', icon: Send, color: 'text-blue-600', bg: 'bg-blue-50' },
  replied: { label: 'Replied', icon: MessageSquare, color: 'text-emerald-600', bg: 'bg-emerald-50' },
  rejected: { label: 'Rejected', icon: XCircle, color: 'text-red-500', bg: 'bg-red-50' },
  interviewing: { label: 'Interviewing', icon: Users, color: 'text-violet-600', bg: 'bg-violet-50' },
  dismissed: { label: 'Dismissed', icon: XCircle, color: 'text-gray-400', bg: 'bg-gray-50' },
};

interface TrackedOpp {
  id: string;
  title: string;
  organization?: string;
  opportunity_type?: string;
  status: InteractionType;
  notes?: string;
  remind_at?: string;
}

export default function DashboardPage() {
  const router = useRouter();
  const { t: tr } = useT();
  const [stats, setStats] = useState<StatsResponse | null>(null);
  const [tracked, setTracked] = useState<TrackedOpp[]>([]);
  const [favCount, setFavCount] = useState(0);
  const [upcoming, setUpcoming] = useState<UpcomingDeadline[]>([]);
  const [reminders, setReminders] = useState<ReminderInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const [statsData, interactionsFull, favSet, upcomingData] = await Promise.all([
          getStats(),
          getInteractionsFull(),
          getFavorites(),
          getUpcomingDeadlines(30).catch(() => ({ opportunities: [], total: 0, days: 30 })),
        ]);
        if (cancelled) return;
        setStats(statsData);
        setFavCount(favSet.size);
        setUpcoming(upcomingData.opportunities.slice(0, 8));
        setReminders(collectReminders(interactionsFull).slice(0, 5));

        if (interactionsFull.size > 0) {
          const ids = Array.from(interactionsFull.keys());
          const opps = await getOpportunitiesByIds(ids);
          if (cancelled) return;
          setTracked(
            opps.map((o) => {
              const rec: InteractionRecord | undefined = interactionsFull.get(o.id as string);
              return {
                id: o.id as string,
                title: o.title as string,
                organization: o.organization as string | undefined,
                opportunity_type: o.opportunity_type as string | undefined,
                status: rec!.type,
                notes: rec?.notes,
                remind_at: rec?.remind_at,
              };
            }),
          );
        }
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : 'Failed to load');
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    return () => { cancelled = true; };
  }, []);

  const statusCounts = useMemo(() => {
    const counts: Record<string, number> = { applied: 0, replied: 0, rejected: 0, interviewing: 0 };
    for (const t of tracked) counts[t.status] = (counts[t.status] || 0) + 1;
    return counts;
  }, [tracked]);

  if (loading) {
    return <DashboardSkeleton />;
  }

  if (error || !stats) {
    return (
      <div className="flex flex-col items-center justify-center min-h-[60vh] gap-4">
        <AlertCircle className="w-8 h-8 text-red-400" />
        <p className="text-gray-600 font-medium">{error || 'No data'}</p>
        <button type="button" onClick={() => window.location.reload()} className="text-[13px] text-blue-600 hover:underline">
          Retry
        </button>
      </div>
    );
  }

  const typeEntries = Object.entries(stats.by_type).sort(([, a], [, b]) => b - a);
  const maxType = Math.max(...typeEntries.map(([, v]) => v), 1);

  return (
    <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-10 sm:py-16">
      <div className="mb-8 sm:mb-12">
        <h1 className="text-2xl sm:text-4xl font-bold text-gray-900 tracking-tight">{tr('dashboard.title')}</h1>
        <p className="mt-1.5 sm:mt-2 text-[13px] sm:text-[15px] text-gray-400">{tr('dashboard.subtitle')}</p>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-12">
        <StatCard value={statusCounts.applied} label="Applied" color="text-blue-600" />
        <StatCard value={statusCounts.replied} label="Replied" color="text-emerald-600" />
        <StatCard value={statusCounts.interviewing} label="Interviewing" color="text-violet-600" />
        <StatCard value={favCount} label="Saved" color="text-amber-500" />
      </div>

      {tracked.length > 0 && (
        <div className="bg-white rounded-2xl shadow-[0_1px_8px_rgba(0,0,0,0.05)] mb-12 overflow-hidden">
          <div className="flex items-center gap-2 px-6 py-4 border-b border-gray-100">
            <BarChart3 className="w-4 h-4 text-gray-400" />
            <h2 className="text-[15px] font-semibold text-gray-900">{tr('dashboard.tracker.title')}</h2>
            <span className="text-[12px] text-gray-400 ml-auto">{tr('dashboard.tracker.count', { count: tracked.length })}</span>
          </div>
          <div className="divide-y divide-gray-50">
            {tracked.map((t) => {
              const cfg = STATUS_CONFIG[t.status];
              const Icon = cfg.icon;
              return (
                <a
                  key={t.id}
                  href={`/opportunities/${encodeURIComponent(t.id)}`}
                  className="flex items-center gap-4 px-6 py-3.5 hover:bg-gray-50/50 transition-colors focus:outline-none focus-visible:bg-gray-50"
                >
                  <div className={`w-8 h-8 rounded-lg ${cfg.bg} flex items-center justify-center shrink-0`}>
                    <Icon className={`w-4 h-4 ${cfg.color}`} aria-hidden="true" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-[14px] font-medium text-gray-900 truncate">{t.title}</p>
                    <p className="text-[12px] text-gray-400 truncate">
                      {t.organization}{t.opportunity_type ? ` · ${t.opportunity_type}` : ''}
                    </p>
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    {t.notes && (
                      <StickyNote className="w-3.5 h-3.5 text-gray-300" aria-label="Has notes" />
                    )}
                    {t.remind_at && (
                      <BellRing className="w-3.5 h-3.5 text-amber-400" aria-label={`Reminder: ${t.remind_at}`} />
                    )}
                    <span className={`px-2.5 py-1 rounded-full text-[11px] font-semibold ${cfg.bg} ${cfg.color}`}>
                      {cfg.label}
                    </span>
                  </div>
                </a>
              );
            })}
          </div>
        </div>
      )}

      {tracked.length === 0 && (
        <div className="bg-white rounded-2xl shadow-[0_1px_8px_rgba(0,0,0,0.05)] p-8 mb-12 text-center">
          <BarChart3 className="w-8 h-8 text-gray-200 mx-auto mb-3" />
          <p className="text-[15px] text-gray-500 mb-1">No applications tracked yet.</p>
          <p className="text-[13px] text-gray-400 mb-4">Mark opportunities as Applied, Replied, or Interviewing from the results page.</p>
          <button
            type="button"
            onClick={() => router.push('/')}
            className="inline-flex items-center gap-2 px-4 py-2 text-[13px] font-medium text-blue-600 bg-blue-50 rounded-xl hover:bg-blue-100 transition-colors"
          >
            Find Matches <ArrowRight className="w-3.5 h-3.5" />
          </button>
        </div>
      )}

      {reminders.length > 0 && (
        <div className="bg-white rounded-2xl shadow-[0_1px_8px_rgba(0,0,0,0.05)] mb-8 overflow-hidden">
          <div className="flex items-center gap-2 px-6 py-4 border-b border-gray-100">
            <BellRing className="w-4 h-4 text-amber-500" aria-hidden="true" />
            <h2 className="text-[15px] font-semibold text-gray-900">{tr('dashboard.reminders.title')}</h2>
            <span className="text-[12px] text-gray-400">{tr('dashboard.reminders.pending', { count: reminders.length })}</span>
            <div className="ml-auto"><PushToggle /></div>
          </div>
          <ul className="divide-y divide-gray-50">
            {reminders.map(r => {
              const tracked_opp = tracked.find(t => t.id === r.opportunityId);
              const statusColor =
                r.status === 'overdue' ? 'text-red-600' :
                r.status === 'today' ? 'text-amber-600' :
                r.status === 'tomorrow' ? 'text-amber-500' :
                'text-gray-500';
              return (
                <li key={r.opportunityId}>
                  <a
                    href={`/opportunities/${encodeURIComponent(r.opportunityId)}`}
                    className="flex items-center gap-4 px-6 py-3.5 hover:bg-gray-50/50 transition-colors focus:outline-none focus-visible:bg-gray-50"
                  >
                    <div className={`shrink-0 w-24 text-right ${statusColor}`}>
                      <p className="text-[12px] font-semibold">{formatReminderLabel(r)}</p>
                      <p className="text-[10px] text-gray-400 mt-0.5">{r.remindAt}</p>
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="text-[14px] font-medium text-gray-900 truncate">
                        {tracked_opp?.title ?? r.opportunityId}
                      </p>
                      {r.notes && (
                        <p className="text-[12px] text-gray-400 truncate mt-0.5 flex items-center gap-1">
                          <StickyNote className="w-3 h-3" aria-hidden="true" />
                          {r.notes}
                        </p>
                      )}
                    </div>
                    <ArrowRight className="w-4 h-4 text-gray-300 shrink-0" aria-hidden="true" />
                  </a>
                </li>
              );
            })}
          </ul>
        </div>
      )}

      {upcoming.length > 0 && (
        <div className="bg-white rounded-2xl shadow-[0_1px_8px_rgba(0,0,0,0.05)] mb-12 overflow-hidden">
          <div className="flex items-center gap-2 px-6 py-4 border-b border-gray-100">
            <Clock className="w-4 h-4 text-amber-500" />
            <h2 className="text-[15px] font-semibold text-gray-900">{tr('dashboard.upcoming.title')}</h2>
            <span className="text-[12px] text-gray-400 ml-auto">{tr('dashboard.upcoming.next30')}</span>
          </div>
          <div className="divide-y divide-gray-50">
            {upcoming.map(u => {
              const urgent = u.days_left <= 7;
              return (
                <a
                  key={u.id}
                  href={u.url || '#'}
                  target={u.url ? '_blank' : undefined}
                  rel="noopener noreferrer"
                  className="flex items-center gap-4 px-6 py-3.5 hover:bg-gray-50/50 transition-colors"
                >
                  <div className={`shrink-0 w-12 text-center ${urgent ? 'text-red-500' : 'text-amber-500'}`}>
                    <p className="text-xl font-bold tabular-nums leading-none">{u.days_left}</p>
                    <p className="text-[9px] font-medium uppercase tracking-wider mt-0.5">
                      {u.days_left === 1 ? 'day' : 'days'}
                    </p>
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-[14px] font-medium text-gray-900 truncate">{u.title}</p>
                    <p className="text-[12px] text-gray-400 truncate">
                      {u.organization || 'Unknown org'} · due {u.deadline}
                    </p>
                  </div>
                  {u.url && <ExternalLink className="w-3.5 h-3.5 text-gray-300 shrink-0" />}
                </a>
              );
            })}
          </div>
        </div>
      )}

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-10">
        <StatCard value={stats.total} label={tr('dashboard.stats.total')} />
        <StatCard value={stats.active} label={tr('dashboard.stats.active')} color="text-emerald-600" />
        <StatCard value={stats.paid_total} label={tr('dashboard.stats.paid')} color="text-blue-600" />
        <StatCard value={stats.international_friendly_total} label={tr('dashboard.stats.intl')} color="text-indigo-600" />
      </div>

      <div className="bg-white rounded-2xl shadow-[0_1px_8px_rgba(0,0,0,0.05)] p-8">
        <h2 className="text-[15px] font-semibold text-gray-900 mb-6">{tr('dashboard.distribution.title')}</h2>
        <div className="space-y-3">
          {typeEntries.map(([type, count]) => {
            const pct = (count / maxType) * 100;
            return (
              <div key={type} className="flex items-center gap-4">
                <span className="text-[13px] text-gray-500 w-36 truncate shrink-0">{type}</span>
                <div className="flex-1 h-2 bg-black/[0.04] rounded-full overflow-hidden">
                  <div
                    className="h-full bg-blue-400 rounded-full transition-all duration-700"
                    style={{ width: `${Math.max(pct, 2)}%` }}
                  />
                </div>
                <span className="text-[13px] font-semibold text-gray-400 tabular-nums w-8 text-right">{count}</span>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

function StatCard({ value, label, color }: { value: number; label: string; color?: string }) {
  return (
    <div className="bg-white rounded-2xl shadow-[0_1px_6px_rgba(0,0,0,0.04)] px-5 py-5">
      <p className={`text-3xl font-bold tabular-nums tracking-tight ${color || 'text-gray-900'}`}>{value}</p>
      <p className="text-[11px] font-medium text-gray-400 mt-1 uppercase tracking-wider">{label}</p>
    </div>
  );
}

function DashboardSkeleton() {
  return (
    <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-10 sm:py-16" aria-busy="true" aria-live="polite">
      <div className="mb-8 sm:mb-12">
        <div className="skeleton h-10 w-48 mb-3" />
        <div className="skeleton h-5 w-80" />
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-12">
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="bg-white rounded-2xl shadow-[0_1px_6px_rgba(0,0,0,0.04)] px-5 py-5">
            <div className="skeleton h-9 w-16 mb-2" />
            <div className="skeleton h-3 w-20" />
          </div>
        ))}
      </div>
      <div className="bg-white rounded-2xl shadow-[0_1px_8px_rgba(0,0,0,0.05)] mb-12 overflow-hidden">
        <div className="h-[57px] border-b border-gray-100 px-6 flex items-center gap-2">
          <div className="skeleton h-4 w-4 rounded" />
          <div className="skeleton h-4 w-40" />
        </div>
        {Array.from({ length: 3 }).map((_, i) => (
          <div key={i} className="flex items-center gap-4 px-6 py-3.5 border-b border-gray-50 last:border-b-0">
            <div className="skeleton h-8 w-8 rounded-lg" />
            <div className="flex-1 space-y-2">
              <div className="skeleton h-4 w-3/5" />
              <div className="skeleton h-3 w-2/5" />
            </div>
            <div className="skeleton h-6 w-20 rounded-full" />
          </div>
        ))}
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-10">
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="bg-white rounded-2xl shadow-[0_1px_6px_rgba(0,0,0,0.04)] px-5 py-5">
            <div className="skeleton h-9 w-16 mb-2" />
            <div className="skeleton h-3 w-20" />
          </div>
        ))}
      </div>
      <div className="bg-white rounded-2xl shadow-[0_1px_8px_rgba(0,0,0,0.05)] p-8">
        <div className="skeleton h-5 w-32 mb-6" />
        <div className="space-y-3">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="flex items-center gap-4">
              <div className="skeleton h-3 w-36" />
              <div className="skeleton flex-1 h-2" />
              <div className="skeleton h-3 w-8" />
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
