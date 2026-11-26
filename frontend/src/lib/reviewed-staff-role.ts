import { targetStatusReason } from './target-truth';
import type { Opportunity } from './types';
import type { Locale } from '@/i18n/translate';

export function reviewedStaffRole(opp: Opportunity, locale: Locale): string | null {
  if (opp.source_type !== 'campus_department' || targetStatusReason(opp) !== 'inactive') return null;
  const role = opp.verified_department_staff_role?.[locale];
  return typeof role === 'string' && role.trim() ? role : null;
}
