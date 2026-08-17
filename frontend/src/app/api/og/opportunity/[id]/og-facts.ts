import type { Opportunity } from '@/lib/types';
import { opportunityRecordKind } from '@/lib/match-utils';

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
  const isFacultyContact = recordKind === 'faculty_contact';
  const isListing = recordKind === 'listing';
  const deadlineDays = isListing ? daysUntil(opportunity.deadline, nowMs) : null;

  return {
    title: opportunity.title,
    organization: opportunity.organization ?? '',
    location: opportunity.location ?? '',
    locationPrefix: isFacultyContact ? 'Faculty affiliation' : '',
    typeLabel: isFacultyContact
      ? 'Faculty contact'
      : isListing
        ? (opportunity.opportunity_type ?? '').replace(/_/g, ' ')
        : 'Record type unconfirmed',
    showPaid: isListing
      && (opportunity.paid === 'yes' || opportunity.paid === 'stipend'),
    showOnCampus: isListing && opportunity.on_campus === true,
    showInternational: isListing
      && opportunity.eligibility?.international_friendly === 'yes',
    daysUntilDeadline: deadlineDays,
    deadlineLabel: isListing && opportunity.deadline
      ? `Deadline: ${opportunity.deadline}`
      : null,
    footer: isFacultyContact
      ? 'Explore research and faculty contacts'
      : isListing
        ? 'Find research & internships that fit you'
        : 'Check the original source for current details',
  };
}
