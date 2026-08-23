import type { Opportunity } from '@/lib/types';
import { opportunityRecordKind } from '@/lib/match-utils';
import { targetPosture, targetStatusReason } from '@/lib/target-truth';

// The card is an image: nothing on it can be qualified, hovered, or clicked
// through to a caveat, and it is cached by whatever chat app rendered it long
// after the record changes. So each status gets its own words, and none of
// them implies the target is open.
const STATUS_TYPE_LABEL = {
  listing_closed: 'Closed listing',
  reference_only: 'Reference record',
  faculty_not_accepting: 'Not accepting undergraduates',
  inactive: 'Inactive record',
  record_kind_unverified: 'Record type unverified',
  status_unverified: 'Status unverified',
} as const;

const STATUS_FOOTER = {
  listing_closed: 'This listing has closed — check the source for current openings',
  reference_only: 'Kept for reference — not an open listing',
  faculty_not_accepting: 'Source profile states they are not accepting undergraduates',
  inactive: 'No longer active — check the original source',
  record_kind_unverified: 'Not presented as an open listing — check the source',
  status_unverified: 'Check the original source for current details',
} as const;

export interface OpportunityOgFacts {
  title: string;
  organization: string;
  location: string;
  locationPrefix: string;
  typeLabel: string;
  showPaid: boolean;
  showOnCampus: boolean;
  showInternational: boolean;
  daysUntilDeadline: number | null;
  deadlineLabel: string | null;
  footer: string;
}

function daysUntil(deadline: string | undefined, nowMs: number): number | null {
  if (!deadline) return null;
  const deadlineMs = Date.parse(`${deadline}T00:00:00Z`);
  if (Number.isNaN(deadlineMs)) return null;
  return Math.ceil((deadlineMs - nowMs) / 86_400_000);
}

/**
 * Keep the social preview on the same truth boundary as the detail page.
 * Faculty directory rows are contact profiles, so a stale pay/location/
 * deadline default must not be promoted into a shareable opening claim.
 */
export function buildOpportunityOgFacts(
  opportunity: Opportunity,
  nowMs: number = Date.now(),
): OpportunityOgFacts {
  const recordKind = opportunityRecordKind(opportunity);
  const actionable = targetPosture(opportunity) === 'actionable';
  const isFacultyContact = recordKind === 'faculty_contact' && actionable;
  // Kind alone, deliberately NOT gated on posture. A person's institution is
  // an identity fact, not a term of an offer: it stays true when they stop
  // taking students, when the row is deactivated, and when the truth envelope
  // is unreadable. What it must never do is appear WITHOUT its label — see
  // `locationPrefix` below, which is bound to this same flag so the two can
  // never drift apart and render an affiliation in the job-site slot.
  const isFacultyRecord = recordKind === 'faculty_contact';
  // Both facts, together. Record kind alone says "this is shaped like a
  // listing"; the truth says "and it is still one". Every opening-shaped
  // field below gates on this, because each of them — paid, on-campus,
  // international-friendly, a deadline, a countdown — reads as a term of an
  // offer, and a closed record has no terms.
  const isOpenListing = recordKind === 'listing' && actionable;
  const statusReason = targetStatusReason(opportunity);
  // Three states, not two. `false` is a judgement someone recorded: this date
  // came from the source. `true` is our own derived estimate — every other
  // surface greys it out and refuses an urgency countdown, and a card saying
  // "Due in 2d" about a date we inferred makes the same claim without the
  // caveat. `null`/`undefined` is neither: nobody has judged it. Reading
  // "not an estimate" as "confirmed" promoted every unjudged date straight
  // into a countdown, which is the majority of them.
  const deadlineConfirmed = opportunity.deadline_is_estimate === false;
  const deadlineIsEstimate = opportunity.deadline_is_estimate === true;
  const deadlineDays = isOpenListing && deadlineConfirmed
    ? daysUntil(opportunity.deadline, nowMs)
    : null;

  return {
    title: opportunity.title,
    organization: opportunity.organization ?? '',
    // Two different meanings sharing one slot, so each earns it separately.
    // On a LISTING the location is where the job is — an offer term, gone the
    // moment the listing is not open, exactly like paid/on-campus/deadline.
    // On a FACULTY row it is the person's affiliation and survives any
    // posture. On an unreviewed kind we know neither, so nothing is shown.
    location: isFacultyRecord || isOpenListing ? (opportunity.location ?? '') : '',
    locationPrefix: isFacultyRecord ? 'Faculty affiliation' : '',
    typeLabel: statusReason
      ? STATUS_TYPE_LABEL[statusReason]
      : isFacultyContact
        ? 'Faculty contact'
        : isOpenListing
          ? (opportunity.opportunity_type ?? '').replace(/_/g, ' ')
          : 'Record type unconfirmed',
    showPaid: isOpenListing
      && (opportunity.paid === 'yes' || opportunity.paid === 'stipend'),
    showOnCampus: isOpenListing && opportunity.on_campus === true,
    showInternational: isOpenListing
      && opportunity.eligibility?.international_friendly === 'yes',
    daysUntilDeadline: deadlineDays,
    deadlineLabel: isOpenListing && opportunity.deadline
      ? deadlineConfirmed
        ? `Deadline: ${opportunity.deadline}`
        : deadlineIsEstimate
          ? `Estimated deadline: ${opportunity.deadline}`
          : `Listed deadline: ${opportunity.deadline} — verify with source`
      : null,
    footer: statusReason
      ? STATUS_FOOTER[statusReason]
      : isFacultyContact
        ? 'Explore research and faculty contacts'
        : isOpenListing
          ? 'Find research & internships that fit you'
          : 'Check the original source for current details',
  };
}
