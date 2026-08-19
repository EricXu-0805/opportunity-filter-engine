import type { MatchResult } from './types';

export type DeadlineUrgency = 'passed' | 'urgent' | 'soon' | 'later' | null;
export type OpportunityRecordKind = 'faculty_contact' | 'listing' | 'unknown';

// Every value currently emitted by the canonical collectors for a real
// listing. New collector kinds must be reviewed and added explicitly; a
// missing, stale, or unfamiliar source type cannot prove that a job/program
// opening exists.
const LISTING_SOURCE_TYPES = new Set([
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
  if (opp.source_type === 'faculty_research') return 'faculty_contact';
  if (typeof opp.source_type === 'string' && LISTING_SOURCE_TYPES.has(opp.source_type)) {
    return 'listing';
  }
  return 'unknown';
}

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
export function opportunityDestination(
  opp: {
    source_type?: string;
    application?: { application_url?: string | null };
    url?: string;
    source_url?: string;
  },
): string | undefined {
  if (opportunityRecordKind(opp) !== 'listing') {
    return opp.url || opp.source_url;
  }
  return opp.application?.application_url || opp.url || opp.source_url;
}

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

export function matchesToCSV(matches: MatchResult[]): string {
  const header = [
    'Title', 'Organization', 'Type', 'Paid', 'Location / faculty affiliation', 'Deadline',
    'International Friendly', 'Score', 'Bucket', 'URL',
  ];
  const rows = matches.map((m) => {
    const recordKind = opportunityRecordKind(m.opportunity);
    const listing = recordKind === 'listing';
    return [
      m.opportunity.title,
      m.opportunity.organization ?? '',
      listing ? m.opportunity.opportunity_type : recordKind,
      listing ? m.opportunity.paid : '',
      m.opportunity.location ?? '',
      listing ? m.opportunity.deadline ?? '' : '',
      facultySafeInternational(m.opportunity) ?? '',
      m.final_score.toFixed(1),
      m.bucket,
      opportunityDestination(m.opportunity) || '',
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
