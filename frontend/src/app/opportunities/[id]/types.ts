import type { InteractionType } from '@/lib/supabase';
import type { useT } from '@/i18n/client';

export type TFunc = ReturnType<typeof useT>['t'];

export const INTERACTION_PILL: Record<InteractionType, string> = {
  contacted: 'bg-sky-50 text-sky-700 border-sky-200',
  applied: 'bg-indigo-50 text-indigo-700 border-indigo-200',
  replied: 'bg-emerald-50 text-emerald-700 border-emerald-200',
  interviewing: 'bg-violet-50 text-violet-700 border-violet-200',
  rejected: 'bg-gray-100 text-gray-500 border-gray-200',
  dismissed: 'bg-gray-100 text-gray-400 border-gray-200',
};

export const INTERACTION_OPTIONS: InteractionType[] = [
  'contacted',
  'applied',
  'replied',
  'interviewing',
  'rejected',
  'dismissed',
];
