'use client';

import { AlertTriangle, CheckCircle2 } from 'lucide-react';
import type { CollectorStatus, TFunc } from './types';

export function CollectorStatusSection({ status, t }: { status: CollectorStatus | null; t: TFunc }) {
  // t() resolves a path to a STRING or hands the key back; it never returns
  // a dictionary subtree, so `cols` was the literal 'admin.collectorStatusCols'
  // and every header rendered undefined.
  const col = (name: string) => t(`admin.collectorStatusCols.${name}`);
  return (
    <section className="mt-10">
      <h2 className="text-[15px] font-semibold text-gray-900 mb-3">{t('admin.collectorStatusTitle')}</h2>
      {!status || !status.last_run_at || status.sources.length === 0 ? (
        <p className="text-[13px] text-gray-400 italic">{t('admin.collectorStatusEmpty')}</p>
      ) : (
        <div className="bg-white rounded-2xl border border-gray-100 overflow-hidden overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 text-xs uppercase tracking-wider text-gray-500">
              <tr>
                <th className="px-4 py-2.5 text-left">{col('source')}</th>
                <th className="px-4 py-2.5 text-left">{col('status')}</th>
                <th className="px-4 py-2.5 text-right">{col('fetched')}</th>
                <th className="px-4 py-2.5 text-right">{col('new')}</th>
                <th className="px-4 py-2.5 text-right">{col('updated')}</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {status.sources.map(s => (
                <tr key={s.source} className="hover:bg-gray-50">
                  <td className="px-4 py-3 font-medium text-gray-900">
                    {s.source}
                    {s.deep && <span className="ml-2 text-[10px] text-indigo-600 font-medium">DEEP</span>}
                  </td>
                  <td className="px-4 py-3">
                    {s.status === 'ok' ? (
                      <span className="inline-flex items-center gap-1 text-emerald-700 text-[12px] font-medium">
                        <CheckCircle2 className="w-3 h-3" /> ok
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1 text-red-700 text-[12px] font-medium" title={s.error || ''}>
                        <AlertTriangle className="w-3 h-3" /> {s.status}
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-right tabular-nums text-gray-600">{s.fetched ?? '—'}</td>
                  <td className="px-4 py-3 text-right tabular-nums text-emerald-700">{s.new ?? '—'}</td>
                  <td className="px-4 py-3 text-right tabular-nums text-gray-500">{s.updated ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {status?.last_run_at && (
        <p className="mt-2 text-[11px] text-gray-400">
          Last run: {new Date(status.last_run_at).toLocaleString()}
          {status.duration_seconds && ` · ${status.duration_seconds.toFixed(0)}s`}
          {typeof status.total_in_file === 'number' && ` · ${status.total_in_file.toLocaleString()} records`}
        </p>
      )}
    </section>
  );
}
