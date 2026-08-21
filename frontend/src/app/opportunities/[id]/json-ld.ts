import type { Opportunity } from '@/lib/types';

/**
 * No opportunity publishes structured data today. Always null.
 *
 * WHY THIS IS OFF, not merely narrowed
 * ------------------------------------
 * Every record here was being emitted as a Schema.org `JobPosting` — a
 * machine-readable assertion that a specific employer is hiring for a specific
 * job on specific terms. `record_kind === 'listing'` does not support that
 * claim. It says a record is an opportunity posting; it says nothing about
 * whether the thing on offer is EMPLOYMENT. The corpus contains reviewed,
 * actionable listings that are summer programs, fellowships and events —
 * `rss-our-7b7684c6` is an undergraduate research SYMPOSIUM. That record
 * carries no employment or job evidence of any kind, so there is nothing to
 * support a JobPosting for it; it was nonetheless shipping as one, with
 * `employmentType: 'INTERN'`.
 *
 * The load-bearing employment, compensation, location and organization
 * claims were inferred or guessed rather than read from the source:
 *   • employmentType   — INTERN/PART_TIME chosen from `opportunity_type`,
 *                        which is our own taxonomy, not the source's terms.
 *   • baseSalary       — currency USD and unitText HOUR asserted for any
 *                        `paid: yes|stipend`. `paid` is a three-state flag,
 *                        not an amount, so the currency and the unit are
 *                        pure invention. `compensation_details` was then
 *                        placed in schema.org's NUMERIC `value` slot: on the
 *                        current corpus that field is an EMPTY STRING for
 *                        2,116 of the 2,662 paid records this function saw,
 *                        so the published figure was `''` at USD/HOUR. Where
 *                        it is prose, a per-term stipend became an hourly
 *                        USD rate. (The `?? 'See description'` fallback is
 *                        nullish-only and fires on no current record — a
 *                        synthetic/future risk, not an observed one.)
 *   • addressCountry   — hardcoded 'US' for every record, including sources
 *                        outside the US.
 *   • hiringOrganization — `?? 'Host institution'` is likewise nullish-only.
 *                        No current record has a null organization (279 are
 *                        empty strings, which pass straight through), so this
 *                        fallback is a synthetic/future risk rather than
 *                        something the live corpus triggers today.
 *
 * Structured data outlives the page: it is cached, indexed, and surfaced in
 * result pages long after anyone could check it, which is the one place an
 * invented employment claim does the most damage. So this fails closed.
 *
 * REOPEN PREREQUISITES — all three, from the source, none inferred:
 *   1. An explicit, source-backed employment classification. Not derived from
 *      `opportunity_type`, `source_type`, or the title.
 *   2. Structured numeric compensation: an amount, a currency, and a unit as
 *      separate machine-readable fields. Not `compensation_details` prose,
 *      and not a placeholder string in a numeric slot.
 *   3. A source-backed hiring organization with address and country. Not a
 *      fallback label, and not an assumed country.
 *
 * Emitting a different schema type in the meantime — Event, Program,
 * EducationalOccupationalProgram — is NOT the smaller step it looks like:
 * each carries its own unverified assertions (dates, venue, provider), so
 * swapping one invented type for another is not a fail-closed boundary.
 *
 * The function is kept as the page's single seam. `page.tsx` still guards on
 * `jsonLd && <script>`, so the page stays fully readable and crawlable and
 * simply injects no `application/ld+json` block.
 */
export function buildOpportunityJsonLd(_opp: Opportunity): Record<string, unknown> | null {
  return null;
}
