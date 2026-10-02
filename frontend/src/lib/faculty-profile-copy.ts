type Replier = (path: string, vars?: Record<string, string | number>) => string;

interface FacultyProfileFields {
  source_type?: string;
  pi_name?: string | null;
  department?: string | null;
  organization?: string | null;
}

// The closing sentence the server picks from the profile's availability
// (src/evidence.py _faculty_profile_summary), and what to say instead.
const CLOSING_SENTENCES: Record<string, string> = {
  'The source profile states that this faculty contact is not currently accepting undergraduate students or researchers.':
    'detail.facultyProfile.notAccepting',
  'The source profile reports that this faculty member is not currently conducting active research.':
    'detail.facultyProfile.inactive',
  'Contact this faculty member to ask whether undergraduate research opportunities are currently available.':
    'detail.facultyProfile.askAvailability',
};
const AREAS_PREFIX = 'Research areas: ';

/**
 * The server writes a faculty profile's description as English product copy
 * around the source's research areas. Say that copy in the UI language and
 * keep the research areas exactly as the source gave them. Anything that is
 * not that exact text for this record returns null: show it as it is.
 * tests/test_faculty_profile_summary_contract.py pins the server side.
 */
export function localizedFacultyDescription(
  opp: FacultyProfileFields, description: string, t: Replier,
): string | null {
  if (opp.source_type !== 'faculty_research') return null;
  const name = (opp.pi_name ?? '').trim();
  const department = (opp.department ?? '').trim();
  const organization = (opp.organization ?? '').trim();
  const affiliation = department && organization ? ` in ${department} at ${organization}`
    : department ? ` in ${department}` : organization ? ` at ${organization}` : '';
  const head = `Faculty research profile for ${name || 'this faculty member'}${affiliation}. `;
  if (!description.startsWith(head)) return null;
  const rest = description.slice(head.length);
  const closing = Object.keys(CLOSING_SENTENCES).find((sentence) => rest === sentence || rest.endsWith(` ${sentence}`));
  if (!closing) return null;
  const middle = rest.slice(0, rest.length - closing.length).trimEnd();
  if (middle && !middle.startsWith(AREAS_PREFIX)) return null;
  const areas = middle.slice(AREAS_PREFIX.length);
  const headKey = department && organization ? 'headFull'
    : department ? 'headDepartment' : organization ? 'headOrganization' : 'head';
  return [
    t(`detail.facultyProfile.${headKey}`, { name: name || t('detail.facultyProfile.unnamed'), department, organization }),
    ...(areas ? [t('detail.facultyProfile.researchAreas', { areas })] : []),
    t(CLOSING_SENTENCES[closing]),
  ].join(' ');
}
