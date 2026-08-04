'use client';

import { useEffect, useState } from 'react';
import {
  ArrowRight,
  ExternalLink,
  GraduationCap,
  Loader2,
  Sparkles,
} from 'lucide-react';
import Link from 'next/link';

import { useT } from '@/i18n/client';
import { getProfessorUpdates } from '@/lib/api';
import {
  getProfessorUpdateReads,
  listProfessorFollows,
  markProfessorUpdatesRead,
} from '@/lib/supabase';
import type { ProfessorUpdateEvent } from '@/lib/types';

type LoadStatus = 'loading' | 'ready' | 'error';

interface UpdatesState {
  status: LoadStatus;
  followCount: number;
  available: boolean;
  events: ProfessorUpdateEvent[];
  reads: Map<string, string>;
}

/**
 * Which of the fetched events are unread, per professor: everything strictly
 * newer than the professor's read-cursor event. A cursor that is not in the
 * fetched window (or was never set) leaves all fetched events unread — the
 * safe direction, since an update can only re-appear as unread, never vanish.
 */
export function unreadEventIds(
  events: ProfessorUpdateEvent[],
  reads: Map<string, string>,
): Set<string> {
  const unread = new Set<string>();
  const byProfessor = new Map<string, ProfessorUpdateEvent[]>();
  for (const event of events) {
    const list = byProfessor.get(event.professor_id) ?? [];
    list.push(event);
    byProfessor.set(event.professor_id, list);
  }
  for (const [professorId, list] of byProfessor) {
    const cursor = reads.get(professorId);
    // Events arrive newest-first; stop at the cursor.
    for (const event of list) {
      if (cursor !== undefined && event.event_id === cursor) break;
      unread.add(event.event_id);
    }
  }
  return unread;
}

export function ProfessorUpdatesSection() {
  const { t } = useT();
  const [state, setState] = useState<UpdatesState>({
    status: 'loading',
    followCount: 0,
    available: true,
    events: [],
    reads: new Map(),
  });
  const [marking, setMarking] = useState(false);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const follows = await listProfessorFollows();
        if (cancelled) return;
        if (follows.length === 0) {
          setState({
            status: 'ready',
            followCount: 0,
            available: true,
            events: [],
            reads: new Map(),
          });
          return;
        }
        const [updates, reads] = await Promise.all([
          getProfessorUpdates(follows.map((f) => f.professorId)),
          getProfessorUpdateReads(),
        ]);
        if (cancelled) return;
        setState({
          status: 'ready',
          followCount: follows.length,
          available: updates.available,
          events: updates.events,
          reads,
        });
      } catch {
        if (!cancelled) {
          setState({
            status: 'error',
            followCount: 0,
            available: true,
            events: [],
            reads: new Map(),
          });
        }
      }
    }

    void load();
    return () => { cancelled = true; };
  }, []);

  const unread = unreadEventIds(state.events, state.reads);

  async function markAllRead() {
    if (marking || unread.size === 0) return;
    setMarking(true);
    // Newest fetched event per professor becomes the cursor.
    const newestByProfessor = new Map<string, string>();
    for (const event of state.events) {
      if (!newestByProfessor.has(event.professor_id)) {
        newestByProfessor.set(event.professor_id, event.event_id);
      }
    }
    const entries = Array.from(newestByProfessor, ([professorId, lastReadEventId]) => ({
      professorId,
      lastReadEventId,
    }));
    try {
      await markProfessorUpdatesRead(entries);
      setState((prev) => {
        const reads = new Map(prev.reads);
        for (const entry of entries) reads.set(entry.professorId, entry.lastReadEventId);
        return { ...prev, reads };
      });
    } finally {
      setMarking(false);
    }
  }

  return (
    <section
      aria-labelledby="dashboard-professor-updates"
      className="overflow-hidden rounded-3xl border border-gray-100 bg-white shadow-sm"
    >
      <div className="flex items-center gap-2.5 border-b border-gray-100 px-6 py-4">
        <GraduationCap className="h-4 w-4 text-gray-500" aria-hidden="true" />
        <h2 id="dashboard-professor-updates" className="text-sm font-semibold text-gray-900">
          {t('dashboard.professorUpdates.title')}
        </h2>
        {state.status === 'ready' && state.followCount > 0 && (
          <span className="text-[11px] text-gray-400">
            {t('dashboard.professorUpdates.count', { count: state.followCount })}
          </span>
        )}
        {unread.size > 0 && (
          <span className="rounded-full bg-indigo-50 px-2 py-0.5 text-[11px] font-semibold text-indigo-600">
            {t('dashboard.professorUpdates.unread', { count: unread.size })}
          </span>
        )}
        {unread.size > 0 && (
          <button
            type="button"
            onClick={() => { void markAllRead(); }}
            disabled={marking}
            className="ml-auto text-xs font-semibold text-indigo-600 hover:text-indigo-700 disabled:opacity-60"
          >
            {t('dashboard.professorUpdates.markAllRead')}
          </button>
        )}
      </div>
      <SectionContent
        state={state}
        unread={unread}
        t={t}
      />
    </section>
  );
}

function SectionContent({
  state,
  unread,
  t,
}: {
  state: UpdatesState;
  unread: Set<string>;
  t: (key: string, vars?: Record<string, string | number>) => string;
}) {
  if (state.status === 'loading') {
    return (
      <div className="flex items-center justify-center gap-2 px-6 py-10 text-xs text-gray-400">
        <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
        {t('dashboard.loading')}
      </div>
    );
  }
  if (state.status === 'error') {
    return (
      <div className="px-6 py-9 text-center">
        <p className="text-sm font-semibold text-red-600">
          {t('dashboard.professorUpdates.errorTitle')}
        </p>
        <p className="mt-1 text-xs text-gray-500">
          {t('dashboard.professorUpdates.errorBody')}
        </p>
      </div>
    );
  }
  if (state.followCount === 0) {
    return (
      <div className="px-6 py-9 text-center">
        <GraduationCap className="mx-auto h-7 w-7 text-gray-300" aria-hidden="true" />
        <p className="mt-3 text-sm font-semibold text-gray-700">
          {t('dashboard.professorUpdates.emptyTitle')}
        </p>
        <p className="mt-1 text-xs text-gray-500">
          {t('dashboard.professorUpdates.emptyBody')}
        </p>
        <Link
          href="/results"
          className="mt-4 inline-flex items-center gap-1 text-xs font-semibold text-indigo-600 hover:text-indigo-700"
        >
          {t('dashboard.professorUpdates.emptyCta')}
          <ArrowRight className="h-3.5 w-3.5" aria-hidden="true" />
        </Link>
      </div>
    );
  }
  if (!state.available) {
    // W14 truthful zero states: the updates feed itself is unavailable
    // (artifact absent/unpublished) — say so instead of claiming "no
    // verified updates yet", which would assert a freshness we don't have.
    return (
      <div data-testid="professor-updates-unavailable" className="px-6 py-9 text-center">
        <GraduationCap className="mx-auto h-7 w-7 text-gray-300" aria-hidden="true" />
        <p className="mt-3 text-sm font-semibold text-gray-700">
          {t('dashboard.professorUpdates.unavailableTitle')}
        </p>
        <p className="mt-1 text-xs text-gray-500">
          {t('dashboard.professorUpdates.unavailableBody')}
        </p>
      </div>
    );
  }
  if (state.events.length === 0) {
    return (
      <div className="px-6 py-9 text-center">
        <GraduationCap className="mx-auto h-7 w-7 text-gray-300" aria-hidden="true" />
        <p className="mt-3 text-sm font-semibold text-gray-700">
          {t('dashboard.professorUpdates.noUpdatesTitle')}
        </p>
        <p className="mt-1 text-xs text-gray-500">
          {t('dashboard.professorUpdates.noUpdatesBody')}
        </p>
      </div>
    );
  }
  return (
    <ul className="divide-y divide-gray-50">
      {state.events.map((event) => (
        <li key={event.event_id}>
          <div className="flex min-w-0 items-start gap-3 px-6 py-4">
            <span
              className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${
                unread.has(event.event_id) ? 'bg-indigo-500' : 'bg-gray-200'
              }`}
              aria-label={unread.has(event.event_id)
                ? t('dashboard.professorUpdates.unreadDot')
                : undefined}
            />
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-medium text-gray-900">
                {event.professor_name}
                <span className="ml-2 text-[11px] font-normal uppercase tracking-wide text-gray-400">
                  {event.school}
                </span>
              </p>
              <p className="mt-0.5 text-xs text-gray-500">
                {event.change_types
                  .map((change) => t(`dashboard.professorUpdates.change.${change}`))
                  .join(' · ')}
              </p>
              {event.project_became_available && (
                <p className="mt-1 inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2 py-0.5 text-[11px] font-semibold text-emerald-600">
                  <Sparkles className="h-3 w-3" aria-hidden="true" />
                  {t('dashboard.professorUpdates.becameAvailable')}
                </p>
              )}
            </div>
            <div className="shrink-0 text-right">
              <p className="text-[10px] text-gray-400">{event.verified_at.slice(0, 10)}</p>
              <a
                href={event.source_url}
                target="_blank"
                rel="noopener noreferrer"
                className="mt-1 inline-flex items-center gap-1 text-[11px] font-semibold text-indigo-600 hover:text-indigo-700"
              >
                {t('dashboard.professorUpdates.viewSource')}
                <ExternalLink className="h-3 w-3" aria-hidden="true" />
              </a>
            </div>
          </div>
        </li>
      ))}
    </ul>
  );
}
