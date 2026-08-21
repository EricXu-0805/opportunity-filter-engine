'use client';

import { QUALITY_SCOPE } from './types';
import type { SourceRow, TFunc } from './types';

function Cell({
  v, listingTotal, currentScope,
}: { v: number; listingTotal?: number; currentScope: boolean }) {
  if (v === 0) return <span className="text-gray-300">0</span>;
  // Two conditions, both required. A legacy response carries `listing_total`
  // as well — it just counted unreviewed records inside it — so the field's
  // presence proves nothing. Out of scope: show the count, no percentage.
  // Recreating the rate over the wrong denominator is the exact lie this
  // batch removes from the global figures.
  const pct = currentScope && typeof listingTotal === 'number' && listingTotal > 0
    ? (v / listingTotal * 100)
    : null;
  const cls = pct !== null && pct > 30
    ? 'text-amber-700 font-semibold'
    : 'text-gray-700';
  return (
    <span className={cls}>
      {v}
      {pct !== null && (
        <> <span className="text-[10px] opacity-60">({pct.toFixed(0)}%)</span></>
      )}
    </span>
  );
}

/**
 * An unreviewed count is shown only when this build can vouch for what it
 * counts. Not sent at all, or sent under a scope this build does not know:
 * an em dash. Printing 0 would report an empty review queue nobody measured;
 * printing a number from another scope would report a queue counted by rules
 * we cannot see.
 */
function UnreviewedCell({ v, currentScope }: { v?: number; currentScope: boolean }) {
  if (!currentScope || typeof v !== 'number') return <span className="text-gray-300">—</span>;
  if (v === 0) return <span className="text-gray-300">0</span>;
  return <span className="text-indigo-700 font-medium">{v}</span>;
}

export function SourceTable(
  { rows, qualityScope, t }:
  { rows: SourceRow[]; qualityScope?: string; t: TFunc },
) {
  const cols = t('admin.bySourceCols') as unknown as Record<string, string>;
  const currentScope = qualityScope === QUALITY_SCOPE;
  return (
    <section className="mb-10">
      <h2 className="text-[15px] font-semibold text-gray-900 mb-3">{t('admin.bySource')}</h2>
      <div className="hidden sm:block bg-white rounded-2xl border border-gray-100 overflow-hidden overflow-x-auto">
        <table className="w-full text-sm min-w-[700px]">
          <thead className="bg-gray-50 text-xs uppercase tracking-wider text-gray-500">
            <tr>
              <th className="px-4 py-2.5 text-left">{cols.source}</th>
              <th className="px-4 py-2.5 text-right">{cols.total}</th>
              <th className="px-4 py-2.5 text-right">{cols.emptyMajors}</th>
              <th className="px-4 py-2.5 text-right">{cols.emptyKeywords}</th>
              <th className="px-4 py-2.5 text-right">{cols.rolling}</th>
              <th className="px-4 py-2.5 text-right">{cols.missingDeadline}</th>
              <th className="px-4 py-2.5 text-right">{cols.past}</th>
              <th className="px-4 py-2.5 text-right">{cols.inactive}</th>
              <th className="px-4 py-2.5 text-right">{cols.unreviewedRecordKind}</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {rows.map((row) => (
              <tr key={row.source} className="hover:bg-gray-50">
                <td className="px-4 py-3 font-medium text-gray-900">{row.source}</td>
                <td className="px-4 py-3 text-right tabular-nums text-gray-600">{row.total}</td>
                <td className="px-4 py-3 text-right tabular-nums"><Cell v={row.empty_majors || 0} listingTotal={row.listing_total} currentScope={currentScope} /></td>
                <td className="px-4 py-3 text-right tabular-nums"><Cell v={row.empty_keywords || 0} listingTotal={row.listing_total} currentScope={currentScope} /></td>
                <td className="px-4 py-3 text-right tabular-nums text-emerald-600">{row.rolling_deadline || 0}</td>
                <td className="px-4 py-3 text-right tabular-nums"><Cell v={row.missing_deadline || 0} listingTotal={row.listing_total} currentScope={currentScope} /></td>
                <td className="px-4 py-3 text-right tabular-nums text-gray-500">{row.past_deadline || 0}</td>
                <td className="px-4 py-3 text-right tabular-nums text-gray-500">{row.flagged_inactive || 0}</td>
                <td className="px-4 py-3 text-right tabular-nums">
                  <UnreviewedCell v={row.unreviewed_record_kind} currentScope={currentScope} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="sm:hidden grid gap-3">
        {rows.map(row => (
          <div key={row.source} className="bg-white rounded-2xl border border-gray-100 p-4">
            <div className="flex items-center justify-between mb-3">
              <p className="font-semibold text-gray-900">{row.source}</p>
              <p className="text-[12px] tabular-nums text-gray-500">{cols.total}: <span className="font-medium text-gray-700">{row.total}</span></p>
            </div>
            <dl className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-[12px]">
              <dt className="text-gray-500">{cols.emptyMajors}</dt>
              <dd className="text-right tabular-nums"><Cell v={row.empty_majors || 0} listingTotal={row.listing_total} currentScope={currentScope} /></dd>
              <dt className="text-gray-500">{cols.emptyKeywords}</dt>
              <dd className="text-right tabular-nums"><Cell v={row.empty_keywords || 0} listingTotal={row.listing_total} currentScope={currentScope} /></dd>
              <dt className="text-gray-500">{cols.rolling}</dt>
              <dd className="text-right tabular-nums text-emerald-600">{row.rolling_deadline || 0}</dd>
              <dt className="text-gray-500">{cols.missingDeadline}</dt>
              <dd className="text-right tabular-nums"><Cell v={row.missing_deadline || 0} listingTotal={row.listing_total} currentScope={currentScope} /></dd>
              <dt className="text-gray-500">{cols.past}</dt>
              <dd className="text-right tabular-nums text-gray-500">{row.past_deadline || 0}</dd>
              <dt className="text-gray-500">{cols.inactive}</dt>
              <dd className="text-right tabular-nums text-gray-500">{row.flagged_inactive || 0}</dd>
              <dt className="text-gray-500">{cols.unreviewedRecordKind}</dt>
              <dd className="text-right tabular-nums"><UnreviewedCell v={row.unreviewed_record_kind} currentScope={currentScope} /></dd>
            </dl>
          </div>
        ))}
      </div>
    </section>
  );
}
