import type { Opportunity, ProfileData } from '@/lib/types';
import { daysUntil, facultySafeInternational } from '@/lib/match-utils';

/**
 * These values are transparent, local decision-factor estimates. They help a
 * student inspect trade-offs, but they are deliberately not averaged into a
 * second match score. `final_score`, bucket and reasons only come from the
 * canonical matcher response represented by CanonicalMatchSummary below.
 */
export type AxisKey =
  | 'skill_match'
  | 'eligibility'
  | 'ease'
  | 'compensation'
  | 'deadline_runway'
  | 'intl_friendly';

/** null means the public listing does not provide enough evidence. Unknown
 * inputs are never replaced with a reassuring midpoint on the chart. */
export type AxisScores = Record<AxisKey, number | null>;

/** Canonical matcher verdict for one opportunity (from /matches/:id/explain). */
export interface CanonicalMatchSummary {
  final_score: number;
  bucket: string;
  reasons_fit: string[];
  reasons_gap: string[];
  explanation: string;
  method: 'llm' | 'local';
}

export interface CompareRow {
  opp: Opportunity;
  factors: AxisScores;
  match: CanonicalMatchSummary | null;
  status: 'ready' | 'error';
  /** Original selection order, used only to keep unavailable rows stable. */
  inputIndex: number;
}

function tokens(s: string): string[] {
  return s.toLowerCase().split(/[^a-z0-9]+/).filter(Boolean);
}

function majorMatchScore(userMajor: string, oppMajors: string[] | undefined): number | null {
  if (!oppMajors || oppMajors.length === 0) return null;
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

function yearMatchScore(userYear: string, oppYears: string[] | undefined): number | null {
  if (!oppYears || oppYears.length === 0) return null;
  const statedYears = oppYears.filter((year) => year.toLowerCase() !== 'unknown');
  if (statedYears.length === 0) return null;
  return statedYears.some((year) => year.toLowerCase() === userYear.toLowerCase()) ? 100 : 50;
}

function intlEligibilityScore(
  userIsIntl: boolean,
  oppIntlFriendly: string | undefined,
): number | null {
  if (!userIsIntl) return 100;
  if (oppIntlFriendly === 'yes') return 100;
  if (oppIntlFriendly === 'no') return 0;
  return null;
}

/** Ease is intentionally the inverse of effort: higher means less work. */
function easeScore(effort: string | undefined): number | null {
  if (effort === 'low') return 100;
  if (effort === 'medium') return 60;
  if (effort === 'high') return 30;
  return null;
}

function compensationScore(paid: string | undefined): number | null {
  if (paid === 'yes' || paid === 'stipend' || paid === 'paid') return 100;
  if (paid === 'no' || paid === 'unpaid') return 30;
  return null;
}

function deadlineRunwayScore(
  deadline: string | undefined | null,
  isRolling: boolean | null | undefined,
  isEstimate: boolean | null | undefined,
): number | null {
  if (isRolling === true) return 85;
  // An estimated (or unverified) date cannot honestly be scored as exact runway.
  if (!deadline || isEstimate !== false) return null;
  const days = daysUntil(deadline);
  if (days === null) return null;
  if (days < 0) return 0;
  if (days >= 60) return 100;
  return Math.round((days / 60) * 100);
}

export function computeDecisionFactors(profile: ProfileData, opp: Opportunity): AxisScores {
  const isFaculty = opp.source_type === 'faculty_research';
  const userSkillSet = new Set(profile.skills.map((skill) => skill.name.toLowerCase()));
  const required = opp.eligibility?.skills_required ?? [];
  const skill_match = isFaculty || required.length === 0
    ? null
    : Math.round(
        (required.filter((skill) => userSkillSet.has(skill.toLowerCase())).length / required.length) * 100,
      );

  const major = majorMatchScore(profile.major || '', opp.eligibility?.majors);
  const year = yearMatchScore(profile.grade || '', opp.eligibility?.preferred_year);
  const intl_friendly = intlEligibilityScore(
    profile.is_international,
    facultySafeInternational(opp),
  );
  const eligibility = !isFaculty && major !== null && year !== null && intl_friendly !== null
    ? Math.round(0.5 * major + 0.3 * year + 0.2 * intl_friendly)
    : null;

  return {
    skill_match,
    eligibility,
    ease: isFaculty ? null : easeScore(opp.application?.application_effort),
    compensation: isFaculty ? null : compensationScore(opp.paid),
    deadline_runway: isFaculty
      ? null
      : deadlineRunwayScore(
          opp.deadline,
          opp.is_rolling,
          opp.deadline_is_estimate,
        ),
    intl_friendly: isFaculty ? null : intl_friendly,
  };
}

/**
 * Canonical results always lead. A failed explanation never receives a local
 * substitute score; unavailable rows remain in the user's original order.
 */
export function sortByCanonicalScore(rows: CompareRow[]): CompareRow[] {
  return [...rows].sort((a, b) => {
    if (a.match && b.match) {
      const scoreGap = b.match.final_score - a.match.final_score;
      return scoreGap || a.inputIndex - b.inputIndex;
    }
    if (a.match) return -1;
    if (b.match) return 1;
    return a.inputIndex - b.inputIndex;
  });
}

export const RADAR_AXES: Array<{ key: AxisKey; labelKey: string }> = [
  { key: 'skill_match', labelKey: 'compare.radar.skill' },
  { key: 'eligibility', labelKey: 'compare.radar.eligibility' },
  { key: 'ease', labelKey: 'compare.radar.ease' },
  { key: 'compensation', labelKey: 'compare.radar.compensation' },
  { key: 'deadline_runway', labelKey: 'compare.radar.deadline' },
  { key: 'intl_friendly', labelKey: 'compare.radar.intl' },
];
