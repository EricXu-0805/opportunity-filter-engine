type Replier = (path: string, vars?: Record<string, string | number>) => string;

type Availability = 'unknown' | 'not_accepting_undergraduates' | 'research_inactive';

/** The parts the server writes a faculty description from (src/evidence.py faculty_profile_summary_fields). */
interface FacultyProfileSummary {
  name: string | null;
  department: string | null;
  organization: string | null;
  research_areas: string | null;
  availability: Availability;
}

interface FacultyProfileFields {
  source_type?: string;
  pi_name?: string | null;
  department?: string | null;
  organization?: string | null;
  faculty_profile_summary?: unknown;
}

const CLOSING_KEYS: Record<Availability, string> = {
  not_accepting_undergraduates: 'detail.facultyProfile.notAccepting',
  research_inactive: 'detail.facultyProfile.inactive',
  unknown: 'detail.facultyProfile.askAvailability',
};

// The closing sentences a backend older than `faculty_profile_summary` wrote,
// and the availability each one states.
const CLOSING_SENTENCES: Record<string, Availability> = {
  'The source profile states that this faculty contact is not currently accepting undergraduate students or researchers.':
    'not_accepting_undergraduates',
  'The source profile reports that this faculty member is not currently conducting active research.':
    'research_inactive',
  'Contact this faculty member to ask whether undergraduate research opportunities are currently available.':
    'unknown',
};
const AREAS_PREFIX = 'Research areas: ';
const OPTIONAL_PARTS = ['name', 'department', 'organization', 'research_areas'] as const;

function readSummary(value: unknown): FacultyProfileSummary | null {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return null;
  const fields = value as Record<string, unknown>;
  if (fields.version !== 1) return null;
  if (typeof fields.availability !== 'string'
    || !Object.prototype.hasOwnProperty.call(CLOSING_KEYS, fields.availability)) return null;
  // Absent is null; "" would pick a different head sentence than the server's.
  const wellFormed = OPTIONAL_PARTS.every((part) => fields[part] === null
    || (typeof fields[part] === 'string' && (fields[part] as string).trim() !== ''));
  return wellFormed ? (fields as unknown as FacultyProfileSummary) : null;
}

/** The parts of the exact English an older backend wrote for this record, or null. */
function summaryFromSentence(opp: FacultyProfileFields, description: string): FacultyProfileSummary | null {
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
  return {
    name: name || null,
    department: department || null,
    organization: organization || null,
    research_areas: middle.slice(AREAS_PREFIX.length) || null,
    availability: CLOSING_SENTENCES[closing],
  };
}

/**
 * The server writes a faculty profile's description as English product copy
 * around the source's research areas, and sends the parts it wrote it from in
 * `faculty_profile_summary`. Say those parts in the UI language and keep the
 * research areas exactly as the source gave them. Without the parts, only the
 * exact English an older backend wrote is recognised. Anything else returns
 * null: show it as it is. tests/test_faculty_profile_summary_contract.py pins
 * the server side.
 */
export function localizedFacultyDescription(
  opp: FacultyProfileFields, description: string, t: Replier,
): string | null {
  if (opp.source_type !== 'faculty_research' || !description.trim()) return null;
  const summary = readSummary(opp.faculty_profile_summary) ?? summaryFromSentence(opp, description);
  if (!summary) return null;
  const { name, department, organization, research_areas: areas } = summary;
  const headKey = department && organization ? 'headFull'
    : department ? 'headDepartment' : organization ? 'headOrganization' : 'head';
  return [
    t(`detail.facultyProfile.${headKey}`, {
      name: name ?? t('detail.facultyProfile.unnamed'), department: department ?? '', organization: organization ?? '',
    }),
    ...(areas ? [t('detail.facultyProfile.researchAreas', { areas })] : []),
    t(CLOSING_KEYS[summary.availability]),
  ].join(' ');
}
