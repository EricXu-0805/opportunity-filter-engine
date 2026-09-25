import type { Opportunity } from '@/lib/types';

export const EMAIL_TARGET_VERSION = `wt1:${'a'.repeat(64)}`;
/** A full public target for existing tests that are about editor behavior. */
export function emailTarget(id: string): Opportunity {
  return { id, title: 'Research opportunity', organization: 'UIUC', record_kind: 'listing',
    opportunity_type: 'research', paid: 'unknown', location: 'Urbana', on_campus: true,
    description_clean: 'Research on sensors', keywords: ['sensors'],
    eligibility: { international_friendly: 'unknown', skills_required: [], preferred_year: [], majors: [], citizenship_required: null },
    application: { requires_resume: 'yes', contact_method: 'email', application_effort: 'unknown' },
    metadata: { is_active: true, confidence_score: 1 }, writing_target_version: EMAIL_TARGET_VERSION };
}
/** The service fake supplies successful receipt metadata; explicit bad fields win. */
export async function emailReceipt(result: unknown, id: string, version = EMAIL_TARGET_VERSION) {
  const value = await result;
  return value && typeof value === 'object' ? { opportunity_id: id, target_version: version, ...value } : value;
}
