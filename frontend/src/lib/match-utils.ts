import type { MatchResult } from './types';

export type DeadlineUrgency = 'passed' | 'urgent' | 'soon' | 'later' | null;

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
    'Title', 'Organization', 'Type', 'Paid', 'Location', 'Deadline',
    'International Friendly', 'Score', 'Bucket', 'URL',
  ];
  const rows = matches.map(m => [
    m.opportunity.title,
    m.opportunity.organization ?? '',
    m.opportunity.opportunity_type,
    m.opportunity.paid,
    m.opportunity.location ?? '',
    m.opportunity.deadline ?? '',
    m.opportunity.eligibility?.international_friendly ?? '',
    m.final_score.toFixed(1),
    m.bucket,
    m.opportunity.application?.application_url || m.opportunity.url || '',
  ]);
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
  let h = 0;
  for (let i = 0; i < key.length; i++) {
    h = ((h << 5) - h + key.charCodeAt(i)) | 0;
  }
  return h.toString(36);
}
