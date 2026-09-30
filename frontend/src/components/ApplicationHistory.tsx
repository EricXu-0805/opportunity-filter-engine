'use client';

import { useEffect, useLayoutEffect, useRef, useState, useSyncExternalStore } from 'react';
import { getApplicationEvents } from '@/lib/supabase';
import type { ApplicationEvent, ApplicationEventCursor } from '@/lib/application-ledger';
import { captureOwnerToken, isOwnerTokenValid, onLocalOwnerStateChange } from '@/lib/identity-owner';
import { useT } from '@/i18n/client';
import ApplicationMaterials from './ApplicationMaterials';

interface Props {
  opportunityId: string;
  /** Read invalidation only, never presented as a application timestamp. */
  refreshKey?: string;
}
type History = {
  scope: string;
  identity: string;
  status: 'ready' | 'error';
  events: ApplicationEvent[];
  nextCursor: ApplicationEventCursor | null;
  more: 'idle' | 'loading' | 'error';
};

function ownerSnapshot(): string {
  const token = captureOwnerToken();
  return JSON.stringify([token.uid, token.epoch, token.generation, isOwnerTokenValid(token, token.uid)]);
}
function subscribeOwner(changed: () => void): () => void {
  const stop = onLocalOwnerStateChange(changed);
  window.addEventListener('storage', changed);
  return () => { stop(); window.removeEventListener('storage', changed); };
}

/** The record preserves the user report; submission and outcomes are not independently verified. */
export default function ApplicationHistory({ opportunityId, refreshKey }: Props) {
  const { t, locale } = useT();
  const owner = useSyncExternalStore(subscribeOwner, ownerSnapshot, () => 'server');
  const [retry, setRetry] = useState(0);
  const identity = JSON.stringify([opportunityId, owner]);
  const scope = JSON.stringify([opportunityId, owner, refreshKey, retry]);
  const scopeRef = useRef(scope);
  const pageRequestRef = useRef<object | null>(null);
  const [history, setHistory] = useState<History | null>(null);
  // A same-account refresh keeps the loaded list mounted until the new page
  // arrives: unmounting it would abort material uploads open inside it.
  const view = history?.scope === scope || (history?.identity === identity && history.status === 'ready') ? history : null;
  const refreshing = !!view && view.scope !== scope;

  useLayoutEffect(() => {
    scopeRef.current = scope;
    pageRequestRef.current = null;
    return () => { scopeRef.current = ''; pageRequestRef.current = null; };
  }, [scope]);

  useEffect(() => {
    let active = true;
    const origin = captureOwnerToken();
    void Promise.resolve().then(() => {
      if (!active || !origin.uid || !isOwnerTokenValid(origin, origin.uid)) throw new Error('owner unavailable');
      return getApplicationEvents(opportunityId);
    }).then(page => {
      if (active && isOwnerTokenValid(origin, origin.uid)) {
        setHistory({ scope, identity, status: 'ready', events: page.events, nextCursor: page.nextCursor, more: 'idle' });
      }
    }, () => {
      if (active) setHistory({ scope, identity, status: 'error', events: [], nextCursor: null, more: 'idle' });
    });
    return () => { active = false; };
  }, [opportunityId, scope, identity]);

  async function loadMore() {
    if (!view || refreshing || view.status !== 'ready' || !view.nextCursor || view.more === 'loading' || pageRequestRef.current) return;
    const origin = captureOwnerToken();
    if (!origin.uid || !isOwnerTokenValid(origin, origin.uid) || scopeRef.current !== scope) return;
    const request = {};
    pageRequestRef.current = request;
    setHistory(current => current?.scope === scope ? { ...current, more: 'loading' } : current);
    const stillCurrent = () => scopeRef.current === scope && pageRequestRef.current === request && isOwnerTokenValid(origin, origin.uid);
    try {
      const page = await getApplicationEvents(opportunityId, { cursor: view.nextCursor });
      if (!stillCurrent()) return;
      setHistory(current => {
        if (current?.scope !== scope) return current;
        const ids = new Set(current.events.map(event => event.id));
        return { ...current, events: [...current.events, ...page.events.filter(event => !ids.has(event.id))], nextCursor: page.nextCursor, more: 'idle' };
      });
    } catch {
      if (stillCurrent()) setHistory(current => current?.scope === scope ? { ...current, more: 'error' } : current);
    } finally {
      if (pageRequestRef.current === request) pageRequestRef.current = null;
    }
  }

  function dateLabel(value: string): string {
    return new Date(value).toLocaleString(locale === 'zh' ? 'zh-CN' : 'en-US', {
      year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', timeZoneName: 'short',
    });
  }
  const label = (key: string, vars?: Record<string, number | string>) => t(`applicationRecord.history.${key}`, vars);

  return <section data-testid="application-history" aria-label={label('title')} className="min-w-0 space-y-2">
    <h3 className="text-[11px] font-semibold text-gray-500 uppercase tracking-wider">{label('title')}</h3>
    <p className="text-xs text-gray-500">{label('hint')}</p>
    {(!view || refreshing) && <p role="status" className="text-xs text-gray-500">{label('loading')}</p>}
    {view?.status === 'error' && <div role="alert" className="text-xs text-amber-800">
      <p>{label('error')}</p>
      <button type="button" onClick={() => setRetry(value => value + 1)} className="mt-1 min-h-9 rounded underline underline-offset-2 focus-visible:ring-2 focus-visible:ring-indigo-500">{label('retry')}</button>
    </div>}
    {view?.status === 'ready' && view.events.length === 0 && <p className="text-xs text-gray-500">{label('empty')}</p>}
    {view?.status === 'ready' && view.events.length > 0 && <>
      <p className="text-xs text-gray-500">{label(view.nextCursor ? 'loadedMore' : 'loadedAll', { count: view.events.length })}</p>
      <ol className="space-y-2">
        {view.events.map(event => <li key={event.id}>
          <details className="min-w-0 rounded-lg border border-gray-200 bg-white p-2.5">
            <summary className="min-h-9 cursor-pointer break-words text-xs font-medium text-gray-700 [overflow-wrap:anywhere] focus-visible:ring-2 focus-visible:ring-indigo-500">
              <span>{label(`channels.${event.channel}`)}</span>
              <span className="mt-1 block font-normal text-gray-500">{event.destination}</span>
            </summary>
            <dl className="mt-2 space-y-2 break-words text-xs [overflow-wrap:anywhere]">
              <div><dt className="font-medium text-gray-600">{label('submittedAt')}</dt><dd className="text-gray-700">{event.submittedAt ? <time dateTime={event.submittedAt}>{dateLabel(event.submittedAt)}</time> : label('submittedUnknown')}</dd></div>
              <div><dt className="font-medium text-gray-600">{label('confirmedAt')}</dt><dd className="text-gray-700"><time dateTime={event.confirmedAt}>{dateLabel(event.confirmedAt)}</time></dd></div>
              {(['notes', 'resultNote', 'nextStep'] as const).map(field => event[field] && <div key={field}><dt className="font-medium text-gray-600">{label(field)}</dt><dd className="mt-1 whitespace-pre-wrap text-gray-700">{event[field]}</dd></div>)}
            </dl>
            <ApplicationMaterials opportunityId={opportunityId} applicationEventId={event.id} />
            <details className="mt-3 min-w-0 border-t border-gray-100 pt-2 text-xs text-gray-500" data-testid="application-event-details">
              <summary className="min-h-9 cursor-pointer font-medium focus-visible:ring-2 focus-visible:ring-indigo-500">{label('recordDetails')}</summary>
              <p className="mt-2 break-words [overflow-wrap:anywhere]">{label('eventId')}: <span className="font-mono">{event.id}</span></p>
            </details>
          </details>
        </li>)}
      </ol>
      {view.more === 'error' && <p role="alert" className="text-xs text-amber-800">{label('moreError')}</p>}
      {view.nextCursor && <button type="button" onClick={() => { void loadMore(); }} disabled={refreshing || view.more === 'loading'} className="min-h-10 rounded-lg border border-gray-200 px-3 py-2 text-xs font-medium text-indigo-700 focus-visible:ring-2 focus-visible:ring-indigo-500 disabled:opacity-50">
        {label(view.more === 'loading' ? 'loadingMore' : view.more === 'error' ? 'retryMore' : 'loadMore')}
      </button>}
    </>}
  </section>;
}
