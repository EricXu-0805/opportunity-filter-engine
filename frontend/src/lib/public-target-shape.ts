import { isResearchContext } from './research-context';
import { opportunityRecordKind } from './record-kind';
import { isWritingTargetVersion } from './writing-target-version';
import { isContactInstructions } from './contact-instructions';
import type { Opportunity } from './types';

const record = (value: unknown): value is Record<string, unknown> =>
  value !== null && typeof value === 'object' && !Array.isArray(value);
const strings = (value: unknown): value is string[] =>
  Array.isArray(value) && value.every(item => typeof item === 'string');
const nullableBoolean = (value: unknown) => value === null || typeof value === 'boolean';
const optional = (value: Record<string, unknown>, key: string, valid: (item: unknown) => boolean) =>
  !(key in value) || valid(value[key]);
const string = (value: unknown) => typeof value === 'string';
const nullableString = (value: unknown) => value === null || string(value);

/** Validate the full anonymous detail projection, not a match/list card.
 * Public metadata deliberately omits is_active. Unreviewed record kinds also
 * omit offer fields and empty application/eligibility (public_projection.py).
 * Truth/actionability is a separate, fail-closed targetPosture decision; an
 * unfamiliar or missing truth envelope must never be upgraded here. */
export function isPublicDetail(value: unknown, id: string): value is Opportunity {
  if (!record(value) || value.id !== id || !string(value.title) || !string(value.organization)
    || !strings(value.keywords) || !record(value.metadata)
    || !record(value.eligibility) || !record(value.application)) return false;
  if ('contact_email' in value || 'pi_email' in value || value.contact_email_status === 'revealed') return false;
  if (!optional(value, 'writing_target_version', isWritingTargetVersion)
    || !optional(value, 'contact_instructions', isContactInstructions)
    || !optional(value, 'research_context', isResearchContext)) return false;
  if (!optional(value, 'source_type', nullableString)
    || !optional(value, 'record_kind', item => typeof item === 'string' && ['listing', 'faculty_contact', 'unknown'].includes(item))) return false;
  const unreviewed = value.record_kind === 'unknown'
    && opportunityRecordKind(value as { source_type?: string | null }) === 'unknown';
  for (const key of ['opportunity_type', 'paid', 'location', 'description_clean']) {
    if (!(unreviewed ? optional(value, key, string) : string(value[key]))) return false;
  }
  if (!(unreviewed ? optional(value, 'on_campus', nullableBoolean) : nullableBoolean(value.on_campus))) return false;
  for (const key of ['department', 'lab_or_program', 'pi_name', 'school', 'url', 'source', 'source_url',
    'description_raw', 'deadline', 'compensation_details', 'duration', 'start_date', 'posted_date', 'remote_option']) {
    if (!optional(value, key, nullableString)) return false;
  }
  if (!optional(value, 'is_rolling', item => typeof item === 'boolean')
    || !optional(value, 'deadline_is_estimate', nullableBoolean)) return false;
  const { eligibility, application, metadata } = value;
  for (const key of ['preferred_year', 'majors', 'skills_required']) {
    if (!(unreviewed ? optional(eligibility, key, strings) : strings(eligibility[key]))) return false;
  }
  if (!(unreviewed ? optional(eligibility, 'international_friendly', string) : string(eligibility.international_friendly))
    || !(unreviewed ? optional(eligibility, 'citizenship_required', nullableBoolean) : nullableBoolean(eligibility.citizenship_required))) return false;
  for (const key of ['application_effort', 'requires_resume', 'contact_method']) {
    if (!(unreviewed ? optional(application, key, string) : string(application[key]))) return false;
  }
  for (const key of ['requires_recommendation', 'requires_cover_letter', 'application_url']) {
    if (!optional(application, key, nullableString)) return false;
  }
  return optional(metadata, 'is_active', item => typeof item === 'boolean')
    && optional(metadata, 'confidence_score', item => typeof item === 'number' && Number.isFinite(item))
    && optional(metadata, 'recent_works', item => Array.isArray(item) && item.every(work => record(work)
      && string(work.title) && optional(work, 'year', year => year === null || (typeof year === 'number' && Number.isFinite(year)))));
}
