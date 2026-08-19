import type { Opportunity } from '@/lib/types';
import { opportunityRecordKind } from '@/lib/match-utils';

/**
 * Only confirmed listing-shaped records may be published as Schema.org jobs.
 * A faculty directory row is a contact/research profile, not evidence that a
 * position exists; emitting JobPosting would turn our own unknowns into a
 * machine-readable opening claim for search engines.
 */
export function buildOpportunityJsonLd(opp: Opportunity): Record<string, unknown> | null {
  if (opportunityRecordKind(opp) !== 'listing') return null;

  return {
    '@context': 'https://schema.org',
    '@type': 'JobPosting',
    title: opp.title,
    description: opp.description_clean || opp.description_raw || '',
    datePosted: opp.posted_date,
    // validThrough is a machine-readable assertion to search engines that the
    // posting closes on this date. Our NSF REU dates are derived from the award
    // start month, so publishing one as validThrough turns our estimate into
    // someone else's fact.
    ...(opp.deadline && opp.deadline_is_estimate !== true
      ? { validThrough: opp.deadline }
      : {}),
    employmentType: opp.opportunity_type === 'research' ? 'PART_TIME' : 'INTERN',
    hiringOrganization: {
      '@type': 'Organization',
      name: opp.organization ?? 'Host institution',
    },
    jobLocation: {
      '@type': 'Place',
      address: {
        '@type': 'PostalAddress',
        addressLocality: opp.location,
        addressCountry: 'US',
      },
    },
    baseSalary: opp.paid === 'yes' || opp.paid === 'stipend' ? {
      '@type': 'MonetaryAmount',
      currency: 'USD',
      value: {
        '@type': 'QuantitativeValue',
        value: opp.compensation_details ?? 'See description',
        unitText: 'HOUR',
      },
    } : undefined,
  };
}
