/**
 * What kind of thing a corpus record is, decided from its source type alone.
 *
 * Its own module so `match-utils` and `target-truth` share ONE list. A second
 * copy would drift, and the direction it drifts is unsafe: a source type
 * present in one list and absent from the other means one surface treats a
 * record as a real opening while another does not.
 *
 * Imports nothing — both consumers can depend on it without a cycle.
 */
export type OpportunityRecordKind = 'faculty_contact' | 'listing' | 'unknown';

// Every value currently emitted by the canonical collectors for a real
// listing. New collector kinds must be reviewed and added explicitly; a
// missing, stale, or unfamiliar source type cannot prove that a job/program
// opening exists.
export const LISTING_SOURCE_TYPES = new Set([
  'campus_announcement',
  'campus_career',
  'campus_department',
  'campus_lab',
  'campus_program',
  'external',
  'external_reu',
  'internship',
  'job',
  'manual',
  'rss',
  'summer_program',
  'ucb_announcement',
  'ucb_career',
  'ucb_department',
  'ucb_lab',
  'ucb_program',
  'uiuc_research',
]);

export function opportunityRecordKind(
  opp: { source_type?: string | null },
): OpportunityRecordKind {
  if (opp?.source_type === 'faculty_research') return 'faculty_contact';
  if (typeof opp?.source_type === 'string' && LISTING_SOURCE_TYPES.has(opp.source_type)) {
    return 'listing';
  }
  return 'unknown';
}
