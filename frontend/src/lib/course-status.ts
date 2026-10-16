import type { CourseEntry, CourseSource, CourseStatus, ProfileData, ResumeCourseEvidence, ResumeParseResponse } from './types';

/**
 * What may be said of a course, by its status (checklist M13).
 *
 * Mirrors the course rules of `src/student_evidence.py` (COURSE_STATEMENTS,
 * course_key, course_entries, course_sentences) — add to both or to neither.
 * The server checks what a draft says; this is what lets the form and the
 * email editor's own insertions say it the same way.
 */
export const COURSE_STATUSES: readonly CourseStatus[] = ['completed', 'in_progress', 'planned', 'unknown'];
const COURSE_SOURCES: readonly CourseSource[] = ['resume', 'manual'];
const IMPORT_STATUSES: readonly ResumeCourseEvidence['status'][] = ['in_progress', 'planned', 'unknown'];

/** How a course of each status may be stated in the student's voice. Unknown
 *  is every course not marked: named, never said to be done. */
export const COURSE_STATEMENTS: Readonly<Record<CourseStatus, string>> = {
  completed: 'I have completed {courses}.',
  in_progress: 'I am currently taking {courses}.',
  planned: 'I plan to take {courses}.',
  unknown: 'My coursework includes {courses}.',
};

/** One identity for a course however it is spaced or cased: "CS 225" is "cs225". */
export function courseKey(name: unknown): string {
  if (typeof name !== 'string') return '';
  return Array.from(name.normalize('NFKC').toLowerCase()).filter((ch) => /[\p{L}\p{N}]/u.test(ch)).join('');
}

function known<T extends string>(values: readonly T[], value: unknown, fallback: T): T {
  return typeof value === 'string' && (values as readonly string[]).includes(value) ? value as T : fallback;
}

/**
 * Every course the profile lists, each with exactly one status.
 *
 * `courses` entries come first, the first of one name winning. A legacy
 * `coursework` string becomes an `unknown` résumé course unless `courses`
 * names the same course, so a profile saved before statuses existed reads as
 * courses not marked, never as completed. Unlike the server, a legacy name
 * repeated is one course here; the server reads the list this produces, so it
 * sees it once too.
 */
export function courseEntries(profile: Pick<ProfileData, 'courses' | 'coursework'>): CourseEntry[] {
  const entries: CourseEntry[] = [];
  const seen = new Set<string>();
  for (const raw of Array.isArray(profile.courses) ? profile.courses : []) {
    if (!raw || typeof raw !== 'object') continue;
    const name = typeof raw.name === 'string' ? raw.name.trim() : '';
    const key = courseKey(name);
    if (!key || seen.has(key)) continue;
    seen.add(key);
    const entry: CourseEntry = {
      name,
      status: known(COURSE_STATUSES, raw.status, 'unknown'),
      source: known(COURSE_SOURCES, raw.source, 'resume'),
    };
    const evidence = typeof raw.evidence === 'string' ? raw.evidence.trim() : '';
    if (evidence) entry.evidence = evidence;
    entries.push(entry);
  }
  for (const raw of Array.isArray(profile.coursework) ? profile.coursework : []) {
    const name = typeof raw === 'string' ? raw.trim() : '';
    const key = courseKey(name);
    if (!key || seen.has(key)) continue;
    seen.add(key);
    entries.push({ name, status: 'unknown', source: 'resume' });
  }
  return entries;
}

/** The two profile keys a course edit writes: the courses, and their names for
 *  clients that read only `coursework`. Always written together. */
export function courseFields(courses: readonly CourseEntry[]): Pick<ProfileData, 'courses' | 'coursework'> {
  const entries = courseEntries({ courses: [...courses] });
  return { courses: entries, coursework: entries.map((entry) => entry.name) };
}

function joined(names: string[]): string {
  return names.length === 1 ? names[0] : `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}`;
}

/** At most `limit` courses, each stated only as its status allows. */
export function courseSentences(entries: readonly CourseEntry[], limit = 3): string {
  const order: CourseStatus[] = ['completed', 'in_progress', 'unknown', 'planned'];
  const chosen = [...entries].sort((a, b) => order.indexOf(a.status) - order.indexOf(b.status)).slice(0, limit);
  return order
    .map((status) => chosen.filter((entry) => entry.status === status).map((entry) => entry.name))
    .map((names, index) => (names.length > 0 ? COURSE_STATEMENTS[order[index]].replace('{courses}', joined(names)) : ''))
    .filter(Boolean)
    .join(' ');
}

function withoutEvidence(entry: CourseEntry): CourseEntry {
  return { name: entry.name, status: entry.status, source: entry.source };
}

/** The courses a parse found, each with its line and status. A parse without
 *  them (an older response) gives names only, not marked. */
export function resumeCourses(
  data: Pick<ResumeParseResponse, 'extracted_coursework' | 'course_evidence'>,
): ResumeCourseEvidence[] {
  const found = new Map((data.course_evidence ?? []).map((item) => [item.course, item]));
  return (data.extracted_coursework ?? []).map((course) => {
    const item = found.get(course);
    // Never completed from a parse, whatever the response says.
    return { course, line: item?.line ?? '', status: known(IMPORT_STATUSES, item?.status, 'unknown') };
  });
}

/**
 * The courses after a résumé import. A course found again keeps the status
 * the student set and takes the new résumé's line; one still not marked takes
 * the status its new line gives. A résumé course not marked that the new
 * résumé no longer lists goes with the old résumé; one the student marked
 * stays, without the old résumé's line. Courses added on the form are left as
 * they are. New courses follow, in the order found.
 */
export function importResumeCourses(
  profile: Pick<ProfileData, 'courses' | 'coursework'>,
  found: readonly ResumeCourseEvidence[],
): CourseEntry[] {
  const byKey = new Map<string, ResumeCourseEvidence>();
  for (const item of found) {
    const key = courseKey(item.course);
    if (key && !byKey.has(key)) byKey.set(key, item);
  }
  const out: CourseEntry[] = [];
  const kept = new Set<string>();
  for (const entry of courseEntries(profile)) {
    const key = courseKey(entry.name);
    const hit = byKey.get(key);
    if (entry.source === 'manual') out.push(entry);
    else if (hit) {
      out.push({
        name: entry.name,
        status: entry.status !== 'unknown' ? entry.status : hit.status,
        source: 'resume',
        ...(hit.line.trim() ? { evidence: hit.line.trim() } : {}),
      });
    } else if (entry.status !== 'unknown') out.push(withoutEvidence(entry));
    else continue;
    kept.add(key);
  }
  for (const [key, item] of byKey) {
    if (kept.has(key)) continue;
    kept.add(key);
    out.push({
      name: item.course.trim(), status: item.status, source: 'resume',
      ...(item.line.trim() ? { evidence: item.line.trim() } : {}),
    });
  }
  return out;
}

/** The courses once the résumé is removed: the ones added on the form and the
 *  ones the student marked. None keeps a line quoted from the removed résumé. */
export function coursesWithoutResume(profile: Pick<ProfileData, 'courses' | 'coursework'>): CourseEntry[] {
  return courseEntries(profile)
    .filter((entry) => entry.source === 'manual' || entry.status !== 'unknown')
    .map(withoutEvidence);
}

/** Whether a stored `courses` value has the shape a course list has. */
export function isCourseList(value: unknown): value is CourseEntry[] {
  return Array.isArray(value) && value.every((item) => !!item && typeof item === 'object' && !Array.isArray(item)
    && typeof (item as CourseEntry).name === 'string'
    && ['status', 'source', 'evidence'].every((key) => {
      const field = (item as unknown as Record<string, unknown>)[key];
      return field === undefined || typeof field === 'string';
    }));
}
