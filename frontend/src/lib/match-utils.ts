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
): DeadlineUrgency {
  const days = daysUntil(deadline, now);
  if (days === null) return null;
  if (days < 0) return 'passed';
  if (days <= 7) return 'urgent';
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
  const escape = (v: string) => `"${v.replace(/"/g, '""')}"`;
  return [header, ...rows].map(r => r.map(escape).join(',')).join('\n');
}

export function hashProfile(profile: {
  major: string;
  college: string;
  grade: string;
  is_international: boolean;
  skills: Array<{ name: string; level: string }>;
  research_interests: string;
  seeking_types?: string[];
  search_weight?: number;
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
  });
  let h = 0;
  for (let i = 0; i < key.length; i++) {
    h = ((h << 5) - h + key.charCodeAt(i)) | 0;
  }
  return h.toString(36);
}
