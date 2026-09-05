'use client';

import { HandHeart } from 'lucide-react';
import type { ConciergeQueue, TFunc } from './types';

/**
 * The concierge queue: students who asked us to handle one specific
 * opportunity for them.
 *
 * This is the operator half of a Wizard-of-Oz funnel — every row is work a
 * person does by hand, so the panel shows what the job IS (who, which
 * professor, where to read them) rather than a count. A request nobody can see
 * is the same as a button that does nothing.
 */
export function ConciergeQueueSection({
  queue,
  t,
}: {
  queue: ConciergeQueue | null;
  t: TFunc;
}) {
  if (!queue) return null;

  return (
    <section className="mt-10">
      <h2 className="text-[15px] font-semibold text-gray-900 mb-3 flex items-center gap-2">
        <HandHeart className="w-4 h-4 text-indigo-600" />
        {t('admin.concierge.title')}
        {queue.status === 'ok' && (
          <span className="text-[12px] font-normal text-gray-400">
            ({queue.requests.length})
          </span>
        )}
      </h2>

      {queue.status !== 'ok' ? (
        <p className="text-[13px] text-gray-400 italic">
          {t('admin.concierge.unconfigured')}
        </p>
      ) : queue.requests.length === 0 ? (
        <p className="text-[13px] text-gray-400 italic">{t('admin.concierge.empty')}</p>
      ) : (
        <ul className="space-y-2" data-testid="concierge-queue">
          {queue.requests.map((request) => (
            <li
              key={request.id}
              className="rounded-xl border border-gray-100 bg-white px-4 py-3"
            >
              <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
                <span className="text-[14px] font-medium text-gray-900">
                  {request.target?.pi_name
                    || request.target?.title
                    /* The target is gone from the corpus; naming the id is the
                       honest fallback — it is still what the student asked
                       for, and it is still resolvable by hand. */
                    || request.opportunity_id
                    /* No target at all: the /account and /results cards both
                       take a request for general application help, which has no
                       opportunity. Those rows used to be filtered out of this
                       queue entirely. */
                    || t('admin.concierge.untargeted')}
                </span>
                <span className="text-[11px] text-gray-400">
                  {new Date(request.created_at).toLocaleString()}
                </span>
              </div>
              <div className="mt-0.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-[12px] text-gray-500">
                {request.target?.department && <span>{request.target.department}</span>}
                {request.target?.organization && <span>{request.target.organization}</span>}
                {request.target?.url && (
                  <a
                    href={request.target.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-indigo-600 hover:underline"
                  >
                    {t('admin.concierge.openTarget')}
                  </a>
                )}
              </div>
              <p className="mt-1 text-[12px] text-gray-600">
                {request.email || t('admin.concierge.noEmail')}
              </p>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
