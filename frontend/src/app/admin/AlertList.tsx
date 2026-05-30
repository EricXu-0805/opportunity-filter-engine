'use client';

import { AlertTriangle } from 'lucide-react';
import type { HealthResponse, TFunc } from './types';

export function AlertList({ health, t }: { health: HealthResponse; t: TFunc }) {
  return (
    <section className="mb-6 bg-amber-50 border border-amber-200 rounded-2xl p-4">
      <h2 className="flex items-center gap-2 text-[14px] font-semibold text-amber-900 mb-2">
        <AlertTriangle className="w-4 h-4" />
        {t('admin.healthAlertsTitle')}
      </h2>
      <ul className="space-y-1.5 text-[13px] text-amber-900">
        {health.alerts.map((a, i) => (
          <li key={i} className="flex items-start gap-2">
            <span className={`mt-0.5 shrink-0 inline-flex items-center justify-center px-1.5 py-0.5 text-[10px] font-bold rounded ${a.level === 'alert' ? 'bg-red-200 text-red-900' : 'bg-amber-200 text-amber-900'}`}>
              {a.level.toUpperCase()}
            </span>
            <span>{a.message}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}
