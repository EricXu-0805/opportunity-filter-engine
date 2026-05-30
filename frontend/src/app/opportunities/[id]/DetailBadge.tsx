'use client';

import type { ReactNode } from 'react';

export function DetailBadge({
  tone,
  icon,
  children,
}: {
  tone: 'blue' | 'emerald' | 'amber' | 'red' | 'gray' | 'indigo';
  icon?: ReactNode;
  children: ReactNode;
}) {
  const cls = {
    blue: 'bg-blue-50 text-blue-700',
    emerald: 'bg-emerald-50 text-emerald-700',
    amber: 'bg-amber-50 text-amber-700',
    red: 'bg-red-50 text-red-700',
    gray: 'bg-gray-100 text-gray-600',
    indigo: 'bg-indigo-50 text-indigo-700',
  }[tone];
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium ${cls}`}>
      {icon}
      {children}
    </span>
  );
}
