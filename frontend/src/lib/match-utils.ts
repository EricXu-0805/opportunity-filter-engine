import { opportunityRecordKind } from './record-kind';
import {
  opportunityApplicationUrl,
  opportunitySourceUrl,
  targetPosture,
  targetStatusReason,
} from './target-truth';
import type { MatchResult, Opportunity } from './types';

// One line per reason, none of them implying the others. A closed listing was
// open once; a reference record never was; a professor not taking
// undergraduates said nothing about any posting; a deactivated row states
// only that we stopped carrying it.
const CSV_STATUS = {
  listing_closed: 'Closed listing — no longer accepting applications',
  reference_only: 'Reference record — not an open listing',
  faculty_not_accepting: 'Faculty profile states not accepting undergraduates',
  inactive: 'Inactive — no longer carried in the catalog',
  record_kind_unverified: 'Record type unverified — not presented as an open listing',
  status_unverified: 'Status unverified — check the source',
} as const;

export type DeadlineUrgency = 'passed' | 'urgent' | 'soon' | 'later' | null;

// Record-kind lives in its own module so target-truth can share the single
// listing-source list without importing this one. Re-exported because the
// existing callers import it from here.
export type { OpportunityRecordKind } from './record-kind';
export { opportunityRecordKind };

export function daysUntil(deadline: string | undefined, now: Date = new Date()): number | null {
  if (!deadline) return null;
  const dl = new Date(deadline + 'T00:00:00');
  if (isNaN(dl.getTime())) return null;
  return Math.ceil((dl.getTime() - now.getTime()) / 86400000);
}

export function getDeadlineUrgency(
  deadline: string | undefined,
  now: Date = new Date(),
  isEstimate?: boolean,
): DeadlineUrgency {
  const days = daysUntil(deadline, now);
  if (days === null) return null;
  // An estimated deadline (NSF projected dates) must never produce a
  // confident 'passed' verdict or a red 'urgent' band: past estimates carry
  // no urgency at all, near estimates cap at the amber 'soon' band.
  if (days < 0) return isEstimate ? null : 'passed';
  if (days <= 7) return isEstimate ? 'soon' : 'urgent';
  if (days <= 30) return 'soon';
  return 'later';
}

/**
 * Faculty-directory rows are contact profiles, not verified openings. Legacy
 * payloads can still carry a guessed `international_friendly=yes`; never let
 * that stale opening claim reach a user-facing surface. An explicit negative
 * restriction remains useful, while every other faculty value fails closed to
 * "unknown / verify".
 */
export function facultySafeInternational(
  opp: {
    source_type?: string;
    eligibility?: {
      international_friendly?: string;
      citizenship_required?: boolean | null;
    };
  },
): string | undefined {
  const eligibility = opp.eligibility;
  const kind = opportunityRecordKind(opp);
  if (kind === 'listing') {
    return eligibility?.international_friendly;
  }
  if (kind === 'unknown') return 'unknown';
  return eligibility?.international_friendly === 'no'
    || eligibility?.citizenship_required === true
    ? 'no'
    : 'unknown';
}

/**
 * Return the only honest external destination for an opportunity. Faculty
 * rows are directory/contact profiles, so a stale `application_url` must
 * never outrank their canonical profile URL at any client boundary.
 */
// opportunityDestination used to live here. It resolved one URL for every
// purpose by falling back from application_url through url/source_url, which
// meant a reference page could be rendered under an Apply label. It is
// replaced by the deliberately fallback-free pair in ./target-truth:
// opportunityApplicationUrl (Apply, or nothing) and opportunitySourceUrl
// (always readable). Do not reintroduce a combined resolver.

const SEARCH_ALIASES: Record<string, string[]> = {
  ml: ['machine learning'],
  ai: ['artificial intelligence'],
  nlp: ['natural language processing'],
  cv: ['computer vision'],
  dl: ['deep learning'],
  hci: ['human computer interaction', 'human-computer interaction'],
  rl: ['reinforcement learning'],
  ds: ['data science'],
  se: ['software engineering'],
  pl: ['programming languages'],
  os: ['operating systems'],
  db: ['database'],
  ece: ['electrical', 'computer engineering'],
  cs: ['computer science'],
  ee: ['electrical engineering'],
  me: ['mechanical engineering'],
  ce: ['civil engineering'],
  cheme: ['chemical engineering'],
  matsci: ['materials science'],
  neuro: ['neuroscience'],
  bioinfo: ['bioinformatics'],
};

export function expandSearchAliases(query: string): string[] {
  const q = query.toLowerCase();
  const terms = [q];
  const aliases = SEARCH_ALIASES[q];
  if (aliases) terms.push(...aliases);
  const tokens = q.split(/\s+/);
  for (const [abbr, expansions] of Object.entries(SEARCH_ALIASES)) {
    if (abbr === q) continue;
    if (tokens.includes(abbr)) {
      for (const exp of expansions) {
        terms.push(q.replace(new RegExp(`\\b${abbr}\\b`, 'g'), exp));
      }
    }
  }
  return terms;
}

function deadlineCell(opportunity: Opportunity): string {
  const deadline = opportunity.deadline ?? '';
  if (!deadline) return '';
  return opportunity.deadline_is_estimate ? `${deadline} (estimated)` : deadline;
}

export function matchesToCSV(matches: MatchResult[]): string {
  const header = [
    'Title', 'Organization', 'Type', 'Paid', 'Location / faculty affiliation', 'Deadline',
    'International Friendly', 'Score', 'Bucket', 'Status', 'URL',
  ];
  const rows = matches.map((m) => {
    const recordKind = opportunityRecordKind(m.opportunity);
    const posture = targetPosture(m.opportunity);
    // A spreadsheet is read months later with none of the page's context, so
    // every opening-shaped column is blanked unless the row is a listing we
    // still call actionable, and the Status column says why it was blanked.
    const openListing = recordKind === 'listing' && posture === 'actionable';
    // A spreadsheet column is read as fact months later, so this one says what
    // is actually known. "Open" for anything actionable called a faculty
    // directory row an opening; "Historical — no longer open" said all four
    // refusals were once open, which is false for a reference record and for a
    // professor who simply is not taking undergraduates.
    const status = posture === 'actionable'
      ? openListing
        ? 'Open listing'
        : recordKind === 'faculty_contact'
          ? 'Faculty contact — opening not confirmed'
          : 'Record type unconfirmed — check the source'
      : CSV_STATUS[targetStatusReason(m.opportunity) ?? 'status_unverified'];
    return [
      m.opportunity.title,
      m.opportunity.organization ?? '',
      openListing ? m.opportunity.opportunity_type : recordKind,
      openListing ? m.opportunity.paid : '',
      m.opportunity.location ?? '',
      // A spreadsheet column is read as fact months later, and this date can
      // be a guess derived from an NSF award start. The card says
      // "2025-02-15 · estimated" and refuses to call it passed; the CSV said
      // Deadline=2025-02-15 with Status=Open listing on the same row.
      openListing ? deadlineCell(m.opportunity) : '',
      facultySafeInternational(m.opportunity) ?? '',
      m.final_score.toFixed(1),
      m.bucket,
      status,
      // Apply link when there is one to give, otherwise the source page. An
      // exported spreadsheet outlives the session, so a row must not hand
      // someone a reference page under a column they read as "where to apply".
      opportunityApplicationUrl(m.opportunity)
        || opportunitySourceUrl(m.opportunity)
        || '',
    ];
  });
  const escape = (v: string) => {
    // CSV quoting prevents delimiter injection, but spreadsheet programs may
    // still execute an imported cell as a formula (=HYPERLINK, @SUM, +cmd…).
    // Titles/organizations come from scraped third-party pages, so neutralize
    // formula markers at the export boundary with a leading apostrophe —
    // without changing what the application displays or stores.
    const formulaSafe = (
      /^[\t\r\n]/.test(v)
      || /^[\u0000-\u0020]*[=+\-@]/.test(v)
    ) ? `'${v}` : v;
    return `"${formulaSafe.replace(/"/g, '""')}"`;
  };
  return [header, ...rows].map(r => r.map(escape).join(',')).join('\n');
}

// EVERY profile field toProfileRequest sends to the matcher must participate
// here (api.ts toProfileRequest is the source of truth): a field the matcher
// scores but the hash omits means editing it silently serves the stale cached
// match set. The 2026-07 consistency audit found five such omissions
// (additional_majors, coursework, experience_level, resume presence,
// exploring) — exploring alone reorders the whole top band.
export function hashProfile(profile: {
  major: string;
  college: string;
  grade: string;
  is_international: boolean;
  skills: Array<{ name: string; level: string }>;
  research_interests: string;
  seeking_types?: string[];
  search_weight?: number;
  home_school?: string;
  include_cross_school?: boolean;
  additional_majors?: string[];
  coursework?: string[];
  experience_level?: string;
  resume_text?: string;
  exploring?: boolean;
}): string {
  const key = JSON.stringify({
    major: profile.major,
    college: profile.college,
    grade: profile.grade,
    intl: profile.is_international,
    skills: profile.skills.map(s => `${s.name}:${s.level}`).sort(),
    interests: profile.research_interests,
    seeking: profile.seeking_types ?? [],
    weight: profile.search_weight ?? 50,
    // Switching home school changes the backend's candidate pool — the
    // cached match set must miss, not serve the previous school's results.
    home: profile.home_school ?? 'uiuc',
    // Same reason: flipping the cross-school toggle changes the pool.
    cross: profile.include_cross_school ?? false,
    // → secondary_interests: secondary-major + keyword matching signal.
    addl: profile.additional_majors ?? [],
    // → coursework: scored in the readiness layer.
    courses: profile.coursework ?? [],
    // → experience_level: scored in the readiness layer.
    exp: profile.experience_level ?? 'beginner',
    // → resume_ready (only presence matters to the matcher, so hash presence —
    // resume text edits that keep it non-empty don't need a re-match).
    resume: !!profile.resume_text,
    // → exploring: widens matching + diversity-samples the top buckets.
    exploring: profile.exploring ?? false,
  });
  return hashString(key);
}

/** Tiny stable string fingerprint (djb2-style). Not cryptographic — used for
 *  cache keys and staleness signals (W13 résumé sigs), never for security. */
export function hashString(key: string): string {
  let h = 0;
  for (let i = 0; i < key.length; i++) {
    h = ((h << 5) - h + key.charCodeAt(i)) | 0;
  }
  return h.toString(36);
}
