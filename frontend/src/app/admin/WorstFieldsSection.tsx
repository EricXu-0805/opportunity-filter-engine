'use client';

import { X } from 'lucide-react';
import type { FieldKey, TFunc, WorstField } from './types';

export function WorstFieldsSection({
  rows,
  activeFilter,
  onClearFilter,
  t,
}: {
  rows: WorstField[];
  activeFilter: FieldKey | null;
  onClearFilter: () => void;
  t: TFunc;
}) {
  // t() resolves a path to a STRING or hands the key back; it never returns
  // a dictionary subtree, so `cols` was the literal 'admin.worstFieldsCols'
  // and every header rendered undefined.
  const col = (name: string) => t(`admin.worstFieldsCols.${name}`);
  return (
    <section>
      <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
        <h2 className="text-[15px] font-semibold text-gray-900">{t('admin.worstFields')}</h2>
        {activeFilter && (
          <button type="button" onClick={onClearFilter} className="inline-flex items-center gap-1.5 text-[12px] text-indigo-600 hover:text-indigo-800">
            <X className="w-3 h-3" />
            {t('admin.filterActive', { field: activeFilter })} · {t('admin.clearFilter')}
          </button>
        )}
      </div>
      <div className="bg-white rounded-2xl border border-gray-100 overflow-hidden overflow-x-auto">
        <table className="w-full text-sm min-w-[600px]">
          <thead className="bg-gray-50 text-xs uppercase tracking-wider text-gray-500">
            <tr>
              <th className="px-4 py-2.5 text-left">{col('title')}</th>
              <th className="px-4 py-2.5 text-left hidden md:table-cell">{col('fields')}</th>
              <th className="px-4 py-2.5 text-left">{col('source')}</th>
              <th className="px-4 py-2.5 text-right">{col('missing')}</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {rows.length === 0 ? (
              <tr>
                <td colSpan={4} className="px-4 py-8 text-center text-[13px] text-gray-400 italic">
                  No matching records.
                </td>
              </tr>
            ) : rows.map((row) => (
              <tr key={row.id} className="hover:bg-gray-50">
                <td className="px-4 py-3 text-gray-900 truncate max-w-md">
                  {row.url ? (
                    <a href={row.url} target="_blank" rel="noopener noreferrer" className="hover:underline">
                      {row.title || row.id}
                    </a>
                  ) : (row.title || row.id)}
                </td>
                <td className="px-4 py-3 hidden md:table-cell">
                  <div className="flex flex-wrap gap-1">
                    {(row.missing_fields || []).map(f => (
                      <span key={f} className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium bg-amber-100 text-amber-800">
                        {f.replace('_', ' ')}
                      </span>
                    ))}
                  </div>
                </td>
                <td className="px-4 py-3 text-gray-500">{row.source}</td>
                <td className="px-4 py-3 text-right tabular-nums font-semibold text-amber-600">{row.missing_count}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
