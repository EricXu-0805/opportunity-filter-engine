import { opportunityRecordKind } from './record-kind';
import type { Opportunity, PublicTargetTruth } from './types';

/**
 * What this client may offer for a target.
 *
 *   actionable — everything is on the table.
 *   historical — readable, linkable, cite-able; no action of any kind.
 *   unknown    — we cannot prove either, so actions are suspended.
 *
 * `unknown` exists because the alternative is guessing, and one direction of
 * guess is much worse than the other: rendering Apply on a closed listing
 * sends a student to a dead form, while withholding it on a live one costs
 * them one click through to the source. Absent, malformed and self-
 * contradicting payloads all land here.
 */
export type TargetPosture = 'actionable' | 'historical' | 'unknown';

const LISTING_STATES = new Set(['open', 'closed', 'unknown']);
const ACCEPTING_STATES = new Set(['accepting', 'not_accepting', 'unknown']);
// Every reason the backend contract can emit. A code missing here is not
// degraded gracefully — the whole payload fails to parse and the target falls
// back to `unknown`, so adding a backend reason without adding it here would
// silently suspend actions on records that are merely explained differently.
const REASON_CODES = new Set([
  'listing_closed',
  'reference_only',
  'faculty_not_accepting',
  'inactive',
  'record_kind_unverified',
]);

function isNullableString(value: unknown): boolean {
  return value === null || typeof value === 'string';
}

/** Whether a wire value is a complete, self-consistent target truth. */
function parseTargetTruth(value: unknown): PublicTargetTruth | null {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return null;
  const truth = value as Record<string, unknown>;
  if (typeof truth.actionable !== 'boolean') return null;
  if (typeof truth.reference_only !== 'boolean') return null;
  if (typeof truth.listing_state !== 'string' || !LISTING_STATES.has(truth.listing_state)) {
    return null;
  }
  if (typeof truth.accepting_state !== 'string' || !ACCEPTING_STATES.has(truth.accepting_state)) {
    return null;
  }
  if (truth.reason_code !== null
    && (typeof truth.reason_code !== 'string' || !REASON_CODES.has(truth.reason_code))) {
    return null;
  }
  // Only a string or an explicit null. A number or object here means the
  // payload came from something other than the contract we serve.
  if (!isNullableString(truth.verified_at)) return null;
  if (!isNullableString(truth.expires_at)) return null;

  // Internal disagreement: the optimistic half must never win. A payload that
  // says "act on this" while also saying the listing closed, that it is
  // reference material, that a refusal reason applies, or that the target is
  // not accepting, is not a green light with noise attached — it is a payload
  // we cannot read, and reading it optimistically is how a dead target gets an
  // Apply button.
  if (truth.actionable && (
    truth.listing_state === 'closed'
    || truth.reference_only
    || truth.reason_code !== null
    || truth.accepting_state === 'not_accepting'
  )) {
    return null;
  }
  // The live side, held to the same exact table as the refusals. The checks
  // above only rule out the obviously self-contradicting shapes; they still
  // accepted a payload reporting a stated-open listing whose accepting_state
  // was `unknown`, or an unstamped record claiming to be `accepting`. The
  // backend emits neither, so both mean something wrote this envelope that
  // was not the contract — and every CTA on the page unlocks off `actionable`.
  if (truth.actionable && !(
    (truth.listing_state === 'open' && truth.accepting_state === 'accepting')
    || (truth.listing_state === 'unknown' && truth.accepting_state === 'unknown')
  )) {
    return null;
  }
  if (!truth.actionable && truth.reason_code === null) return null;
  // The refusal side, checked as strictly as the optimistic side. Until now a
  // `false` truth was accepted whatever else it said, so a payload claiming
  // "closed" while reporting listing_state `open`, or "reference material"
  // with the reference flag clear, still reached the UI — and every surface
  // then rendered copy asserting the specific thing the payload contradicted.
  //
  // The table is the backend contract, derived from src/evidence.target_truth
  // and nothing else. A reason that does not match its own fields is not a
  // weaker signal to be shown cautiously; it is a payload we cannot read, and
  // it lands in `unknown` with the rest of them.
  if (!truth.actionable && !reasonAgreesWithFields(truth)) return null;

  return truth as unknown as PublicTargetTruth;
}

/** Whether a stated reason matches the fields the backend emits with it. */
function reasonAgreesWithFields(truth: Record<string, unknown>): boolean {
  switch (truth.reason_code) {
    // A closed posting. `reference_only` is deliberately unconstrained: the
    // 861 UCB URAP rows are closed AND published as reference material, and
    // both facts are true at once.
    case 'listing_closed':
      return truth.listing_state === 'closed'
        && truth.accepting_state === 'not_accepting';
    // Never a listing, so it cannot be a closed one.
    case 'reference_only':
      return truth.reference_only === true
        && truth.listing_state !== 'closed'
        && truth.accepting_state === 'unknown';
    // A statement about a person. It says nothing about any posting, which is
    // why listing_state stays unknown rather than closed.
    case 'faculty_not_accepting':
      return truth.listing_state === 'unknown'
        && truth.reference_only === false
        && truth.accepting_state === 'not_accepting';
    // The vague fallback: a deactivated row that states nothing more precise.
    // If it were closed or reference material, the backend would have said so.
    case 'inactive':
      return truth.listing_state !== 'closed'
        && truth.reference_only === false
        && truth.accepting_state === 'unknown';
    // Asserts nothing about any posting, because we do not know there is one.
    // Reference material is a claim the source makes; this is our own silence.
    case 'record_kind_unverified':
      return truth.listing_state === 'unknown'
        && truth.reference_only === false
        && truth.accepting_state === 'unknown';
    default:
      return false;
  }
}

/** What the truth envelope says, once it has been checked against the record. */
type TruthSubject = Pick<Opportunity, 'target_truth' | 'source_type'> & {
  record_kind?: string;
};

/**
 * Cross-check the envelope against the record it claims to describe.
 *
 * Parsing the envelope alone leaves two holes. A payload can claim
 * `actionable` on a row whose `source_type` nobody has reviewed — and every
 * CTA unlocks off `actionable`. And it can carry `record_kind_unverified` on a
 * confirmed listing, which would hide a real opening behind copy about our
 * review queue. The kind and the truth have to agree, or neither is usable.
 */
function readTruth(opp: TruthSubject) {
  const truth = parseTargetTruth(opp?.target_truth);
  if (truth === null) return null;
  const kind = opportunityRecordKind(opp ?? {});
  // The wire may carry the server's own normalization. Where it does, it must
  // match what this build derives from the same field — a mismatch means one
  // of the two allowlists moved, and trusting either one alone is how a
  // renamed source type silently becomes a listing.
  // Absent is fine — an older backend simply does not send it. Present but
  // unreadable is not: a number, a null or an object here means something
  // wrote this envelope that was not the contract, and skipping the check
  // because the value has the wrong type is how the mismatch gets through.
  const wireKind = opp?.record_kind;
  if (wireKind !== undefined && wireKind !== kind) return null;
  // One-way, not an equivalence. An unreviewed row can also state something
  // more specific — closed, reference material, deactivated — and that fact
  // is the better thing to tell a student, so it keeps the reason. What must
  // hold is only:
  //   • an unreviewed kind is never actionable, whatever the envelope says;
  //   • `record_kind_unverified` is claimed ONLY by an unreviewed kind, so a
  //     confirmed listing can never be hidden behind copy about our own
  //     review queue;
  //   • `faculty_not_accepting` is claimed ONLY by a faculty contact.
  //
  // The last one exists because that reason is not a fact about a record —
  // it is a quotation. Every surface renders it as a named person's own
  // written refusal ("this faculty member is not currently accepting
  // undergraduate students"), and on a listing or an unreviewed row there is
  // no person who said it. The backend already constrains it the same way
  // (src/evidence.target_truth reaches that branch only through
  // faculty_availability_status, which returns `unknown` for anything whose
  // source_type is not `faculty_research`), so a payload arriving otherwise
  // did not come from the contract we serve and is not read at all.
  if (kind === 'unknown' && truth.actionable) return null;
  if (truth.reason_code === 'record_kind_unverified' && kind !== 'unknown') return null;
  if (truth.reason_code === 'faculty_not_accepting' && kind !== 'faculty_contact') return null;
  return truth;
}

export function targetPosture(opp: TruthSubject): TargetPosture {
  const truth = readTruth(opp);
  if (truth === null) return 'unknown';
  return truth.actionable ? 'actionable' : 'historical';
}

/** Reason codes a surface may key copy off, plus the unreadable case. */
export type TargetStatusReason =
  | 'listing_closed'
  | 'reference_only'
  | 'faculty_not_accepting'
  | 'inactive'
  | 'record_kind_unverified'
  | 'status_unverified';

/**
 * Which sentence a non-actionable target gets, in one place.
 *
 * Three surfaces (compare cards, page metadata, the share image) each need to
 * say why a target is not open, and each was one edit away from saying
 * "closed" for all four reasons. A reason the parser cannot read is
 * `status_unverified` rather than a guess: "we could not confirm this" and
 * "the source says it ended" are different claims.
 *
 * Returns null for an actionable target — there is nothing to explain.
 */
export function targetStatusReason(opp: TruthSubject): TargetStatusReason | null {
  const truth = readTruth(opp);
  if (truth === null) return 'status_unverified';
  if (truth.actionable) return null;
  return truth.reason_code ?? 'status_unverified';
}

/**
 * The URL an Apply control may point at — and nothing else.
 *
 * Kept separate from {@link opportunitySourceUrl} on purpose. The previous
 * single resolver fell back from `application.application_url` through `url`
 * and `source_url`, so clearing the application URL server-side still left
 * callers a string to render under an Apply label — a reference page dressed
 * as an application form. There is no fallback here: no application URL, no
 * Apply control.
 */
type ApplicationUrlSource = Pick<Opportunity, 'target_truth' | 'source_type'> & {
  application?: { application_url?: string | null };
};

export function opportunityApplicationUrl(opp: ApplicationUrlSource): string | undefined {
  if (targetPosture(opp) !== 'actionable') return undefined;
  // Two independent facts, both required. Truth says the record is live;
  // record-kind says it is a listing at all. A faculty profile's
  // application_url is a directory page, and an unrecognised source type is
  // not evidence that an opening exists — a stale URL on either is not an
  // application form just because it parses as a link.
  if (opportunityRecordKind(opp) !== 'listing') return undefined;
  return opp.application?.application_url || undefined;
}

/**
 * Whether a whole result page is safe to render as matches.
 *
 * All-or-nothing on purpose. Silently dropping the bad rows would leave the
 * totals, bucket counts and facet numbers describing a page that no longer
 * exists — "142 matches" above 141 cards, with the missing one unexplained.
 * A page that cannot be shown honestly is refused and re-fetched instead.
 */
export function everyResultActionable(
  results: readonly { opportunity: Pick<Opportunity, 'target_truth'> }[],
): boolean {
  return results.every((result) => targetPosture(result.opportunity) === 'actionable');
}

/**
 * Where to read the record at its source. Always allowed, whatever the posture.
 *
 * `source_url` first: it is the page the collector actually read, while `url`
 * is a display link that some collectors rewrite. When they differ the source
 * page is the citable one.
 */
export function opportunitySourceUrl(
  opp: { source_url?: string | null; url?: string | null },
): string | undefined {
  return opp.source_url || opp.url || undefined;
}
