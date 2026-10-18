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

/**
 * The skills once the résumé on file is replaced by one that names `found`,
 * or removed (`found` empty), and whether they are only the old ones plus the
 * new names (checklist M18).
 *
 * A skill only the résumé named, which the student never settled, loses its
 * basis with the résumé and goes. One the new résumé names again takes its
 * new line. One the student settled stays theirs, quoting no résumé that is
 * no longer on file. A skill from GitHub or typed by the student is not the
 * résumé's to take; neither is one with no source, which may be either.
 */
export function skillsWithResume(
  skills: readonly SkillWithLevel[],
  found: readonly SkillWithLevel[],
): { skills: SkillWithLevel[]; onlyAdds: boolean } {
  const byName = new Map(found.map((skill) => [skill.name, skill]));
  const kept: SkillWithLevel[] = [];
  let onlyAdds = true;
  for (const skill of skills) {
    if (skill.source !== 'resume') { kept.push(skill); continue; }
    const again = byName.get(skill.name);
    if (!again && !skillLevelIsTheStudentsOwn(skill)) { onlyAdds = false; continue; }
    const evidence = again?.evidence;
    if (evidence === skill.evidence) { kept.push(skill); continue; }
    onlyAdds = false;
    const next: SkillWithLevel = { ...skill };
    if (evidence) next.evidence = evidence;
    else delete next.evidence;
    kept.push(next);
  }
  const names = new Set(kept.map((skill) => skill.name));
  return { skills: [...kept, ...found.filter((skill) => !names.has(skill.name))], onlyAdds };
}
