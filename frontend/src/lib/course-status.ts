import type { CourseEntry, CourseSource, CourseStatus, ProfileData, StoredCourse } from './types';

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
/** The statuses that say something of a course. A course the student marked
 *  with one is their statement, and outlives the résumé. */
const MARKS: readonly CourseStatus[] = ['completed', 'in_progress', 'planned'];

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
  // Python's casefold where it differs from lower-casing in a course name:
  // "ß" is "ss", and a final sigma is a sigma.
  const folded = name.normalize('NFKC').toLowerCase().replace(/ß/gu, 'ss').replace(/ς/gu, 'σ');
  return Array.from(folded).filter((ch) => /[\p{L}\p{N}]/u.test(ch)).join('');
}

function known<T extends string>(values: readonly T[], value: unknown): T | undefined {
  return typeof value === 'string' && (values as readonly string[]).includes(value) ? value as T : undefined;
}

const said = (status: CourseStatus | undefined) => status !== undefined && MARKS.includes(status);

// ── What a résumé text says of its courses ─────────────────────────────
// The parser finds a résumé's courses with these (pdf-parser.ts), and the form
// and every request read each course's status and line from the stored text
// with them, so the two never disagree about where a list is.

const COURSE_CODE = /\b([A-Z]{2,4})\s+(\d{3,4})\b/g;
// A résumé's address block and grant citations have the same shape as a course
// code, so "Urbana IL 61801 / APT 402" was reaching a student's profile as
// coursework and from there into the sentence a cold email makes about what
// they have studied. These prefixes are never a department.
const NOT_A_DEPARTMENT = new Set([
  'APT', 'STE', 'RM', 'BOX', 'PO', 'POB', 'FL', 'UNIT', 'NO', 'BLDG', 'DEPT',
  'EXT', 'TEL', 'FAX', 'ISBN', 'DOI', 'GPA', 'ID', 'SSN', 'ZIP',
]);

/** Every course code ("CS 225") in `text`, with where it starts. */
export function courseCodes(text: string): Array<{ name: string; index: number }> {
  const codes: Array<{ name: string; index: number }> = [];
  for (const m of text.matchAll(COURSE_CODE)) {
    // A number in the calendar band is a venue or a date ("CVPR 2026",
    // "MAY 2027"), not a catalog number — publications and graduation dates
    // share the course-code shape, and a venue cited as coursework becomes a
    // false claim in generated emails. Catalog numbers in the band ("CS 2050")
    // are sacrificed; a labeled "Coursework:" line still captures them.
    const num = Number(m[2]);
    if (num >= 1950 && num <= 2049) continue;
    if (NOT_A_DEPARTMENT.has(m[1].toUpperCase())) continue;
    codes.push({ name: `${m[1]} ${m[2]}`, index: m.index });
  }
  return codes;
}

type ResumeMark = 'in_progress' | 'planned';

// A label that says what every course of its list is (checklist M13). It has
// to open its field — the start of the line, or right after a column break
// the page kept (a tab, "|" or "•") — and be followed by ":", "-" or "—". Said
// inside a sentence ("advised freshmen on courses to take:"), after other words
// ("Course Assistant, Current courses:"), or mixed with another status
// ("Completed/Current Coursework:", "Current and Planned Courses:"), it is not
// one; nor is anything else on a line ("Currently a teaching assistant for
// CS 225", "Current Topics in AI", "expected May 2027").
const STATUS_LABEL = new RegExp(String.raw`(?:^|(?<=[\t|•]))[ \t]*(?:${[
  String.raw`(?<in_progress>current\s+course\s?work|current\s+courses|courses\s+in[\s-]progress|in[\s-]progress\s+courses|currently\s+taking)`,
  String.raw`(?<planned>planned\s+course\s?work|planned\s+courses|future\s+course\s?work|future\s+courses|courses\s+to\s+take|upcoming\s+courses)`,
].join('|')})\s*[:\-—]\s*`, 'giu');
// A coursework label, anywhere on a line: its list is the student's courses,
// with no status.
const LIST_LABEL = /\b(?:relevant\s+)?(?:course\s?work|courses)\b\s*[:\-—]\s*/giu;
// Any other label ("Completed:", "Skills:"): where a list stops. Its last
// word is enough to stop at, and more could take in the course before it.
const ANY_LABEL = /(?<![\p{L}\p{N}])\p{Lu}[\p{L}'’]*[ \t]*:/gu;
const FIELD_BREAK = /[\t|]/gu;

/** The course lists on one line of résumé text. Each starts after a label
 *  ("Coursework:", "Relevant Courses -", "Current courses:") and runs to the
 *  next label, a "|" or a tab, or the end of the line; a status label's list
 *  carries its status. */
export function courseLists(line: string): Array<{ start: number; end: number; status?: ResumeMark }> {
  const opened: Array<{ at: number; start: number; status?: ResumeMark }> = Array.from(line.matchAll(STATUS_LABEL), (m) => ({
    at: m.index, start: m.index + m[0].length, status: m.groups?.in_progress ? 'in_progress' as const : 'planned' as const,
  }));
  for (const m of line.matchAll(LIST_LABEL)) {
    if (!opened.some((label) => m.index >= label.at && m.index < label.start)) opened.push({ at: m.index, start: m.index + m[0].length });
  }
  opened.sort((a, b) => a.at - b.at);
  const stops = [
    ...opened.map((label) => label.at),
    ...Array.from(line.matchAll(ANY_LABEL), (m) => m.index),
    ...Array.from(line.matchAll(FIELD_BREAK), (m) => m.index),
  ];
  return opened.map(({ start, status }) => ({
    start,
    end: Math.min(line.length, ...stops.filter((stop) => stop >= start)),
    ...(status ? { status } : {}),
  }));
}

export function trimCourse(s: string): string {
  return s.replace(/^[ .\t]+/, '').replace(/[ .\t]+$/, '');
}

/** The named courses of a list ("Data Structures, Linear Algebra; Operating
 *  Systems"), each with where it starts in the list. */
export function listedCourses(list: string): Array<{ name: string; index: number }> {
  const named: Array<{ name: string; index: number }> = [];
  for (const item of list.matchAll(/[^;,]+/gu)) {
    const name = trimCourse(item[0]);
    if (name && /[A-Za-z]/.test(name) && name.length >= 3 && name.length <= 40) {
      named.push({ name, index: item.index + item[0].indexOf(name) });
    }
  }
  return named;
}

/** The longest excerpt of a line shown with a course, as for a skill. */
const LINE_CAP = 200;

function excerpt(line: string, at: number, length: number): string {
  if (line.trim().length <= LINE_CAP) return line.trim();
  // Centred on the course, or one near the end of a long line would be cut
  // out of its own excerpt.
  const from = Math.floor(Math.max(0, Math.min(at - (LINE_CAP - length) / 2, line.length - LINE_CAP)));
  return line.slice(from, from + LINE_CAP).trim();
}

interface ResumeCourse { line: string; status?: ResumeMark }
let lastRead: { text: string; courses: Map<string, ResumeCourse> } | null = null;

/** What a résumé text says of each course it names, by courseKey: the status
 *  every status list naming it agrees on (none when they disagree, or when no
 *  status list names it) — a suggestion for the form only — and the line it
 *  sits on: the status label's line if it has a status, else the first. */
function readResume(text: string): Map<string, ResumeCourse> {
  if (lastRead?.text === text) return lastRead.courses;
  const found = new Map<string, Array<{ line: string; at: number; length: number; status?: ResumeMark }>>();
  const add = (name: string, line: string, at: number, status: ResumeMark | undefined) => {
    const key = courseKey(name);
    if (!key) return;
    const seen = found.get(key);
    if (seen) seen.push({ line, at, length: name.length, status });
    else found.set(key, [{ line, at, length: name.length, status }]);
  };
  for (const line of text.split('\n')) {
    const lists = courseLists(line);
    for (const code of courseCodes(line)) {
      add(code.name, line, code.index, lists.find((list) => code.index >= list.start && code.index < list.end)?.status);
    }
    for (const list of lists) {
      for (const item of listedCourses(line.slice(list.start, list.end))) add(item.name, line, list.start + item.index, list.status);
    }
  }
  const courses = new Map<string, ResumeCourse>();
  for (const [key, seen] of found) {
    const marks = new Set(seen.flatMap((item) => (item.status ? [item.status] : [])));
    const status = marks.size === 1 ? [...marks][0] : undefined;
    const shown = (status && seen.find((item) => item.status === status)) || seen[0];
    courses.set(key, { line: excerpt(shown.line, shown.at, shown.length), ...(status ? { status } : {}) });
  }
  lastRead = { text, courses };
  return courses;
}

// ── The profile's courses ──────────────────────────────────────────────

type CourseProfile = Pick<ProfileData, 'courses' | 'coursework' | 'resume_text'>;

/** A course as the form shows it. */
export interface CourseRow extends CourseEntry {
  /** The status the student set, which is `status`. */
  marked?: CourseStatus;
  /** For a résumé course the student has not set: the status its line in the
   *  current résumé text suggests. Shown on the form only, for the student to
   *  confirm or change; `status` stays not marked until they do. */
  suggested?: ResumeMark;
  /** A résumé course's line, found in the current résumé text. */
  line?: string;
}

/**
 * Every course the profile lists, as the form shows it.
 *
 * `courses` entries come first, the first of one name winning; a legacy
 * `coursework` name `courses` lacks is a résumé course not marked, so a
 * profile saved before statuses never reads as completed. A status is the one
 * the student set, and every other course is not marked. A résumé course
 * without one gets the status the current résumé text suggests (courseLists),
 * read every time and never stored or sent, so a removed or replaced résumé
 * leaves none behind. A résumé course the student has not marked counts only
 * while `coursework` still names it: an older client removes or replaces the
 * résumé by writing `coursework` and the text, and must not leave this build
 * showing the old résumé's courses.
 */
export function courseRows(profile: CourseProfile): CourseRow[] {
  const resume = readResume(typeof profile.resume_text === 'string' ? profile.resume_text : '');
  const named = new Set((Array.isArray(profile.coursework) ? profile.coursework : []).map(courseKey));
  const rows: CourseRow[] = [];
  const seen = new Set<string>();
  const add = (name: string, source: CourseSource, marked: CourseStatus | undefined) => {
    const key = courseKey(name);
    if (!key || seen.has(key) || (source === 'resume' && !said(marked) && !named.has(key))) return;
    seen.add(key);
    if (source === 'manual') {
      rows.push({ name, status: marked ?? 'unknown', source, marked: marked ?? 'unknown' });
      return;
    }
    const found = resume.get(key);
    rows.push({
      name, status: marked ?? 'unknown', source,
      ...(marked ? { marked } : found?.status ? { suggested: found.status } : {}),
      ...(found ? { line: found.line } : {}),
    });
  };
  for (const raw of Array.isArray(profile.courses) ? profile.courses : []) {
    if (!raw || typeof raw !== 'object') continue;
    add(typeof raw.name === 'string' ? raw.name.trim() : '', known(COURSE_SOURCES, raw.source) ?? 'resume', known(COURSE_STATUSES, raw.status));
  }
  for (const raw of Array.isArray(profile.coursework) ? profile.coursework : []) {
    add(typeof raw === 'string' ? raw.trim() : '', 'resume', undefined);
  }
  return rows;
}

/** Every course the profile lists, each with the status the student set or
 *  not marked: what every request, email and quick action says (courseRows). */
export function courseEntries(profile: CourseProfile): CourseEntry[] {
  return courseRows(profile).map(({ name, status, source }) => ({ name, status, source }));
}

/** A course as the profile stores it: a status only if the student set one. */
export function storedCourse(row: Pick<CourseRow, 'name' | 'source' | 'marked'>): StoredCourse {
  return { name: row.name, source: row.source, ...(row.marked ? { status: row.marked } : {}) };
}

/** The two profile keys a course edit writes, always together: the courses as
 *  the student set them, and their names for clients that read only
 *  `coursework`. Nothing read from the résumé is written. */
export function courseFields(courses: readonly StoredCourse[]): Pick<ProfileData, 'courses' | 'coursework'> {
  const stored: StoredCourse[] = [];
  const seen = new Set<string>();
  for (const course of courses) {
    const name = typeof course?.name === 'string' ? course.name.trim() : '';
    const key = courseKey(name);
    if (!key || seen.has(key)) continue;
    seen.add(key);
    const status = known(COURSE_STATUSES, course.status);
    stored.push({ name, source: known(COURSE_SOURCES, course.source) ?? 'resume', ...(status ? { status } : {}) });
  }
  return { courses: stored, coursework: stored.map((course) => course.name) };
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
    // A function, so a "$" in a course name is written as it is.
    .map((names, index) => (names.length > 0 ? COURSE_STATEMENTS[order[index]].replace('{courses}', () => joined(names)) : ''))
    .filter(Boolean)
    .join(' ');
}

/**
 * The courses after a résumé import, as the profile stores them. A course the
 * new résumé lists again keeps the status the student set, and one they never
 * set stays without one, the form suggesting one from the new text. A résumé course the
 * student has not marked goes with the old résumé when the new one no longer
 * lists it; one they marked stays. Courses added on the form are left as they
 * are. New courses follow, in the order found.
 */
export function importResumeCourses(profile: CourseProfile, found: readonly string[]): StoredCourse[] {
  const names = new Map<string, string>();
  for (const name of found) {
    const key = courseKey(name);
    if (key && !names.has(key)) names.set(key, name.trim());
  }
  const out: StoredCourse[] = [];
  for (const course of courseRows(profile).map(storedCourse)) {
    const again = names.delete(courseKey(course.name));
    if (course.source === 'manual' || again || said(course.status)) out.push(course);
  }
  for (const name of names.values()) out.push({ name, source: 'resume' });
  return out;
}

/** The courses once the résumé is removed: the ones added on the form and the
 *  ones the student marked. A status the résumé only suggested goes with it. */
export function coursesWithoutResume(profile: CourseProfile): StoredCourse[] {
  return courseRows(profile).map(storedCourse).filter((course) => course.source === 'manual' || said(course.status));
}

/** Whether a stored `courses` value has the shape a course list has. */
export function isCourseList(value: unknown): value is StoredCourse[] {
  return Array.isArray(value) && value.every((item) => !!item && typeof item === 'object' && !Array.isArray(item)
    && typeof (item as StoredCourse).name === 'string'
    && ['status', 'source'].every((key) => {
      const field = (item as unknown as Record<string, unknown>)[key];
      return field === undefined || typeof field === 'string';
    }));
}
