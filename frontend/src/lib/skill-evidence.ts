import type { SkillWithLevel } from './types';

/**
 * Whether the student stands behind a skill's LEVEL, not just its name.
 *
 * Mirrors `src/student_evidence.py` — add to both or to neither. The server is
 * the one that withholds the claim; this exists so the form can say WHY a level
 * is being held back, and offer the click that settles it. A page that stays
 * silent about it would leave the student wondering why their email says
 * "exposure" about a skill their profile shows as experienced.
 *
 * `expert` with no provenance is the one legacy value that still reads as
 * theirs: nothing writes it but `cycleLevel`, the badge they click, while both
 * import sites stamped `experienced`.
 */
export function skillLevelIsTheStudentsOwn(skill: SkillWithLevel): boolean {
  if (skill.confirmed) return true;
  if (skill.source) return false;
  return skill.level === 'expert';
}

/**
 * Whether to ask the student to settle this skill.
 *
 * Two different situations, one affordance. An import at `beginner` has a
 * source and no opinion attached — worth inviting them to set it. A legacy
 * `experienced` has no source but IS being held back, and saying nothing would
 * mute it invisibly. A plain `beginner` they typed is neither: it claims
 * nothing and there is nothing to restore, so it stays quiet.
 */
export function skillNeedsConfirming(skill: SkillWithLevel): boolean {
  if (skillLevelIsTheStudentsOwn(skill)) return false;
  return !!skill.source || skill.level !== 'beginner';
}
