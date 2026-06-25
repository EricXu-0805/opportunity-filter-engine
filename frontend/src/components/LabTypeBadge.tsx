'use client';

import { FlaskConical, Cpu, BookOpen } from 'lucide-react';
import type { LabType } from '@/lib/types';
import { useT } from '@/i18n/client';

const STYLE_BY_TYPE: Record<LabType, { icon: typeof FlaskConical; ring: string; text: string; bg: string }> = {
  wet: {
    icon: FlaskConical,
    ring: 'ring-emerald-200',
    text: 'text-emerald-700',
    bg: 'bg-emerald-50',
  },
  dry: {
    icon: Cpu,
    ring: 'ring-indigo-200',
    text: 'text-indigo-700',
    bg: 'bg-indigo-50',
  },
  humanities: {
    icon: BookOpen,
    ring: 'ring-amber-200',
    text: 'text-amber-700',
    bg: 'bg-amber-50',
  },
};

interface LabTypeBadgeProps {
  labType: LabType | null | undefined;
  size?: 'sm' | 'md';
}

export default function LabTypeBadge({ labType, size = 'sm' }: LabTypeBadgeProps) {
  const { t } = useT();
  if (!labType) return null;
  const style = STYLE_BY_TYPE[labType];
  const Icon = style.icon;
  const padding = size === 'sm' ? 'px-2 py-0.5 text-[11px]' : 'px-2.5 py-1 text-xs';
  const iconSize = size === 'sm' ? 'w-3 h-3' : 'w-3.5 h-3.5';
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full font-medium ring-1 ring-inset ${style.bg} ${style.text} ${style.ring} ${padding}`}
      title={t('coldEmail.labType.tooltip')}
    >
      <Icon className={iconSize} aria-hidden="true" />
      {t(`coldEmail.labType.${labType}` as const)}
    </span>
  );
}
