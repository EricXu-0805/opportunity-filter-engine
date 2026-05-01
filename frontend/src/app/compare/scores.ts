import type { Opportunity, ProfileData } from '@/lib/types';

export interface AxisScores {
  skill_match: number;
  eligibility: number;
  effort: number;
  compensation: number;
  deadline_runway: number;
  intl_friendly: number;
}

export interface OppScore {
  axes: AxisScores;
  overall: number;
}

const AXIS_KEYS: (keyof AxisScores)[] = [
  'skill_match',
  'eligibility',
  'effort',
  'compensation',
  'deadline_runway',
  'intl_friendly',
];

function tokens(s: string): string[] {
  return s.toLowerCase().split(/[^a-z0-9]+/).filter(Boolean);
}

function majorMatchScore(userMajor: string, oppMajors: string[] | undefined): number {
  if (!oppMajors || oppMajors.length === 0) return 70;
  const userTokArr = tokens(userMajor);
  const userTok = new Set(userTokArr);
  if (userTok.size === 0) return 50;
  const userInitials = userTokArr.map((t) => t[0]).join('');

  for (const m of oppMajors) {
    const lower = m.toLowerCase();
    if (lower === userMajor.toLowerCase()) return 100;

    const mTok = tokens(m);
    if (mTok.length === 0) continue;

    if (mTok.every((t) => userTok.has(t)) || mTok.some((t) => userTok.has(t) && t.length > 2)) {
      return 80;
    }

    if (mTok.length === 1 && mTok[0].length >= 2 && mTok[0].length <= 5) {
      const abbrev = mTok[0];
      if (abbrev === userInitials.slice(0, abbrev.length)) return 90;
    }
  }
  return 35;
}

function yearMatchScore(userYear: string, oppYears: string[] | undefined): number {
  if (!oppYears || oppYears.length === 0) return 80;
  const u = userYear.toLowerCase();
  if (oppYears.some((y) => y.toLowerCase() === u)) return 100;
  return 50;
}

function intlEligibilityScore(userIsIntl: boolean, oppIntlFriendly: string | undefined): number {
  if (!userIsIntl) return 100;
  switch (oppIntlFriendly) {
    case 'yes': return 100;
    case 'no': return 0;
    case 'unknown': return 50;
    default: return 50;
  }
}

function effortScore(effort: string | undefined): number {
  switch (effort) {
    case 'low': return 100;
    case 'medium': return 60;
    case 'high': return 30;
    default: return 55;
  }
}

function compensationScore(paid: string | undefined): number {
  switch (paid) {
    case 'yes':
    case 'stipend':
    case 'paid':
      return 100;
    case 'unpaid':
      return 30;
    default:
      return 50;
  }
}

function deadlineRunwayScore(deadline: string | undefined | null, isRolling: boolean | undefined): number {
  if (isRolling) return 85;
  if (!deadline) return 55;
  const dl = new Date(deadline + 'T00:00:00');
  if (Number.isNaN(dl.getTime())) return 55;
  const days = Math.ceil((dl.getTime() - Date.now()) / 86_400_000);
  if (days < 0) return 0;
  if (days >= 60) return 100;
  return Math.round((days / 60) * 100);
}

export function computeScores(profile: ProfileData, opp: Opportunity): OppScore {
  const userSkillSet = new Set(profile.skills.map((s) => s.name.toLowerCase()));
  const required = opp.eligibility?.skills_required ?? [];
  const skill_match = required.length === 0
    ? 80
    : Math.round(
        (required.filter((s) => userSkillSet.has(s.toLowerCase())).length / required.length) * 100,
      );

  const major = majorMatchScore(profile.major || '', opp.eligibility?.majors);
  const year = yearMatchScore(profile.grade || '', opp.eligibility?.preferred_year);
  const intlElig = intlEligibilityScore(profile.is_international, opp.eligibility?.international_friendly);
  const eligibility = Math.round(0.5 * major + 0.3 * year + 0.2 * intlElig);

  const effort = effortScore(opp.application?.application_effort);
  const compensation = compensationScore(opp.paid);
  const deadline_runway = deadlineRunwayScore(opp.deadline, opp.is_rolling);
  const intl_friendly = intlEligibilityScore(profile.is_international, opp.eligibility?.international_friendly);

  const axes: AxisScores = {
    skill_match,
    eligibility,
    effort,
    compensation,
    deadline_runway,
    intl_friendly,
  };
  const overall = Math.round(AXIS_KEYS.reduce((sum, k) => sum + axes[k], 0) / AXIS_KEYS.length);
  return { axes, overall };
}

export type CompareBucket = 'top' | 'backup' | 'reach';

export function rankAndBucket(
  opps: Opportunity[],
  profile: ProfileData,
): Array<{ opp: Opportunity; score: OppScore; bucket: CompareBucket; index: number }> {
  const scored = opps.map((opp) => ({ opp, score: computeScores(profile, opp) }));
  scored.sort((a, b) => b.score.overall - a.score.overall);
  return scored.map((s, i) => ({
    opp: s.opp,
    score: s.score,
    bucket: i === 0 ? 'top' : i === scored.length - 1 && scored.length >= 3 ? 'reach' : 'backup',
    index: i,
  }));
}

export const RADAR_AXES: { key: keyof AxisScores; labelKey: string }[] = [
  { key: 'skill_match', labelKey: 'compare.radar.skill' },
  { key: 'eligibility', labelKey: 'compare.radar.eligibility' },
  { key: 'effort', labelKey: 'compare.radar.effort' },
  { key: 'compensation', labelKey: 'compare.radar.compensation' },
  { key: 'deadline_runway', labelKey: 'compare.radar.deadline' },
  { key: 'intl_friendly', labelKey: 'compare.radar.intl' },
];

function skillsRequiredScore(profile: ProfileData, opp: Opportunity): number {
  const required = opp.eligibility?.skills_required ?? [];
  if (required.length === 0) return 70;
  const userSet = new Set(profile.skills.map((s) => s.name.toLowerCase()));
  return Math.round((required.filter((s) => userSet.has(s.toLowerCase())).length / required.length) * 100);
}

function requirementBoolScore(v: string | undefined): number {
  if (v === 'no') return 100;
  if (v === 'yes') return 30;
  return 55;
}

export const FIELD_SCORERS: Record<string, (opp: Opportunity, profile: ProfileData) => number> = {
  paid: (o) => compensationScore(o.paid),
  compensation: (o) => compensationScore(o.paid),
  international: (o, p) => intlEligibilityScore(p.is_international, o.eligibility?.international_friendly),
  citizenship: (o, p) => (o.eligibility?.citizenship_required && p.is_international) ? 0 : 100,
  deadline: (o) => deadlineRunwayScore(o.deadline, o.is_rolling),
  effort: (o) => effortScore(o.application?.application_effort),
  skills: (o, p) => skillsRequiredScore(p, o),
  majors: (o, p) => majorMatchScore(p.major || '', o.eligibility?.majors),
  preferredYear: (o, p) => yearMatchScore(p.grade || '', o.eligibility?.preferred_year),
  onCampus: (o, p) => {
    if (o.on_campus) return 100;
    return p.is_international ? 40 : 60;
  },
  requiresResume: (o) => requirementBoolScore(o.application?.requires_resume),
  requiresCoverLetter: (o) => requirementBoolScore(o.application?.requires_cover_letter),
  requiresRecommendation: (o) => requirementBoolScore(o.application?.requires_recommendation),
};
