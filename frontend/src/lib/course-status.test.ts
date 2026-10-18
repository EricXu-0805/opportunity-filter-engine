import { describe, expect, it } from 'vitest';
import {
  COURSE_STATEMENTS, courseEntries, courseFields, courseKey, courseRows, courseSentences, coursesWithoutResume,
  importResumeCourses, isCourseList, storedCourse,
} from './course-status';
import type { CourseEntry, ProfileData, StoredCourse } from './types';
import repeats from '../../../tests/fixtures/course_repeats_cases.json';

type CourseProfile = Pick<ProfileData, 'courses' | 'coursework' | 'resume_text'>;
/** What leaves the form: every request, email and quick action. */
const statuses = (profile: CourseProfile) => Object.fromEntries(courseEntries(profile).map((course) => [course.name, course.status]));
/** What the form only suggests, from the current résumé text. */
const suggested = (profile: CourseProfile) => Object.fromEntries(courseRows(profile).map((row) => [row.name, row.suggested ?? null]));
/** Each name as an import stores it: from the résumé, no status. */
const imported = (text: string, names: string[]): CourseProfile => ({
  resume_text: text, courses: names.map((name) => ({ name, source: 'resume' as const })), coursework: names,
});

describe('one course rule, mirrored from src/student_evidence.py', () => {
  it('words each status as the server does', () => {
    expect(COURSE_STATEMENTS).toEqual({
      completed: 'I have completed {courses}.',
      in_progress: 'I am currently taking {courses}.',
      planned: 'I plan to take {courses}.',
      unknown: 'My coursework includes {courses}.',
    });
  });

  it('reads a course however it is spaced or cased, folding case as the server does', () => {
    expect(courseKey('CS 225')).toBe('cs225');
    expect(courseKey(' cs-225 ')).toBe('cs225');
    expect(courseKey('ＣＳ２２５')).toBe('cs225');
    expect(courseKey('-')).toBe('');
    // course_key's casefold, as Python computes it.
    expect(courseKey('Straße 101')).toBe('strasse101');
    expect(courseKey('STRASSE 101')).toBe('strasse101');
    expect(courseKey('ẞ 101')).toBe('ss101');
    expect(courseKey('ΣΊΣΥΦΟΣ 1')).toBe('σίσυφοσ1');
    expect(courseKey('Σίσυφος 1')).toBe('σίσυφοσ1');
    expect(courseKey('Ǆ 1')).toBe('dž1');
    expect(courseKey('ﬁnance 101')).toBe('finance101');
    expect(courseKey('İstanbul 101')).toBe('istanbul101');
    expect(courseKey('café 1')).toBe('café1');
  });

  it('states completed, in-progress, unmarked and planned courses in that order, each by its status', () => {
    const entries: CourseEntry[] = [
      { name: 'CS 446', status: 'planned', source: 'resume' },
      { name: 'CS 225', status: 'completed', source: 'manual' },
      { name: 'CS 374', status: 'in_progress', source: 'resume' },
      { name: 'MATH 241', status: 'unknown', source: 'resume' },
      { name: 'CS 173', status: 'completed', source: 'resume' },
    ];
    expect(courseSentences(entries, entries.length)).toBe(
      'I have completed CS 225 and CS 173. I am currently taking CS 374. '
      + 'My coursework includes MATH 241. I plan to take CS 446.',
    );
    // The server's template default: three courses, the planned one last to go.
    expect(courseSentences(entries)).toBe('I have completed CS 225 and CS 173. I am currently taking CS 374.');
    expect(courseSentences([])).toBe('');
  });

  it('keeps a "$" in a course name as written, as the server does', () => {
    expect(courseSentences([
      { name: "Econ $' Policy", status: 'completed', source: 'manual' },
      { name: 'Intro to $$ Finance', status: 'in_progress', source: 'manual' },
      { name: 'Law $& Order', status: 'unknown', source: 'manual' },
    ])).toBe("I have completed Econ $' Policy. I am currently taking Intro to $$ Finance. My coursework includes Law $& Order.");
  });
});

describe('courseEntries', () => {
  it('reads a profile saved before statuses as courses not marked, never completed', () => {
    expect(courseEntries({ coursework: ['CS 225', ' ECE 220 '] })).toEqual([
      { name: 'CS 225', status: 'unknown', source: 'resume' },
      { name: 'ECE 220', status: 'unknown', source: 'resume' },
    ]);
  });

  it('lets a course with a status win over the legacy name of the same course', () => {
    expect(courseEntries({
      courses: [{ name: 'CS 225', status: 'completed', source: 'manual' }],
      coursework: ['cs225', 'CS 446'],
    })).toEqual([
      { name: 'CS 225', status: 'completed', source: 'manual' },
      { name: 'CS 446', status: 'unknown', source: 'resume' },
    ]);
  });

  it('reads an unknown status or source as unknown / resume, and keeps the first of one course', () => {
    const stored = [
      { name: 'CS 225', status: 'done', source: 'friend', evidence: '  CS 225 line ' },
      { name: 'cs 225', status: 'completed', source: 'manual' },
      { name: '  ', status: 'completed', source: 'manual' },
    ] as unknown as StoredCourse[];
    expect(courseEntries({ courses: stored, coursework: ['CS 225'] })).toEqual([
      { name: 'CS 225', status: 'unknown', source: 'resume' },
    ]);
  });

  it('writes the courses as the student set them, with their names for clients that read only coursework', () => {
    expect(courseFields([
      { name: 'CS 225', source: 'resume', status: 'completed', evidence: 'Relevant Coursework: CS 225' } as StoredCourse,
      { name: 'cs225', source: 'manual', status: 'planned' },
      { name: ' CS 374 ', source: 'resume' },
      { name: 'CS 446', source: 'manual', status: 'planned' },
    ])).toEqual({
      // No résumé line is stored, and a course the student has not set has no status.
      courses: [
        { name: 'CS 225', source: 'resume', status: 'completed' },
        { name: 'CS 374', source: 'resume' },
        { name: 'CS 446', source: 'manual', status: 'planned' },
      ],
      coursework: ['CS 225', 'CS 374', 'CS 446'],
    });
  });

  it('knows a course list from anything else in storage', () => {
    expect(isCourseList([{ name: 'CS 225', source: 'resume', status: 'completed' }])).toBe(true);
    expect(isCourseList([{ name: 'CS 225', source: 'resume' }])).toBe(true);
    expect(isCourseList([])).toBe(true);
    expect(isCourseList(['CS 225'])).toBe(false);
    expect(isCourseList([{ name: 'CS 225', status: 1 }])).toBe(false);
    expect(isCourseList(null)).toBe(false);
  });
});

describe('a résumé code nobody marked is not listed again beside a résumé course that opens with it (checklist M130)', () => {
  // The cases tests/test_student_course_status.py reads too.
  it.each(repeats.cases.map((item) => [item.why, item] as const))('as the server reads it: %s', (_why, item) => {
    expect(courseEntries(item.profile as unknown as CourseProfile).map(({ name, status, source }) => [name, status, source]))
      .toEqual(item.entries);
  });

  // What the résumé parser stored before it stopped storing the code again.
  const text = 'Relevant Coursework: CS 173 Discrete Structures, MATH 241 Calculus III\nCurrent courses: CS 374 Algorithms';
  const names = ['CS 173', 'CS 173 Discrete Structures', 'CS 374', 'CS 374 Algorithms', 'MATH 241', 'MATH 241 Calculus III'];

  it('shows one row for the course, with its line and suggestion', () => {
    for (const profile of [{ resume_text: text, coursework: names }, imported(text, names)]) {
      expect(courseRows(profile)).toEqual([
        { name: 'CS 173 Discrete Structures', status: 'unknown', source: 'resume', line: text.split('\n')[0] },
        { name: 'CS 374 Algorithms', status: 'unknown', source: 'resume', suggested: 'in_progress', line: 'Current courses: CS 374 Algorithms' },
        { name: 'MATH 241 Calculus III', status: 'unknown', source: 'resume', line: text.split('\n')[0] },
      ]);
    }
  });

  it('keeps a code the student marked, with the course beside it', () => {
    const profile: CourseProfile = { resume_text: text, coursework: names, courses: [
      { name: 'CS 173', source: 'resume', status: 'completed' },
      { name: 'CS 374', source: 'resume', status: 'unknown' },
    ] };
    expect(statuses(profile)).toEqual({
      'CS 173': 'completed', 'CS 173 Discrete Structures': 'unknown', 'CS 374 Algorithms': 'unknown', 'MATH 241 Calculus III': 'unknown',
    });
  });

  it('writes the list without the code on the next course edit, and nothing brings it back', () => {
    const profile = imported(text, names);
    const rows = courseRows(profile);
    // A status click writes the course list alone; the names keep the code.
    const clicked = { ...profile, courses: courseFields(rows.map((row, at) => storedCourse(at === 0 ? { ...row, marked: 'completed' } : row))).courses };
    expect(clicked.courses).toEqual([
      { name: 'CS 173 Discrete Structures', source: 'resume', status: 'completed' },
      { name: 'CS 374 Algorithms', source: 'resume' },
      { name: 'MATH 241 Calculus III', source: 'resume' },
    ]);
    expect(courseEntries(clicked).map((entry) => entry.name)).toEqual(['CS 173 Discrete Structures', 'CS 374 Algorithms', 'MATH 241 Calculus III']);
    // Removing the course removes it, code and all.
    expect(courseFields(rows.slice(1).map(storedCourse)).coursework).toEqual(['CS 374 Algorithms', 'MATH 241 Calculus III']);
    expect(importResumeCourses(clicked, ['CS 173 Discrete Structures', 'MATH 241 Calculus III'])).toEqual([
      { name: 'CS 173 Discrete Structures', source: 'resume', status: 'completed' },
      { name: 'MATH 241 Calculus III', source: 'resume' },
    ]);
    expect(coursesWithoutResume(clicked)).toEqual([{ name: 'CS 173 Discrete Structures', source: 'resume', status: 'completed' }]);
  });
});

describe('the résumé suggests a status only after a label that opens its line or a column (R2)', () => {
  const names = ['CS 374', 'MATH 415'];
  it('suggests in progress for every course of a list after an in-progress label', () => {
    for (const line of [
      'Current coursework: CS 374, MATH 415',
      '  Current Courses - CS 374, MATH 415',
      'CURRENT COURSES — CS 374, MATH 415',
      'Courses in progress: CS 374, MATH 415',
      'In-progress courses - CS 374, MATH 415',
      'Currently taking: CS 374, MATH 415',
      // After a column break the page kept: a tab, "|" or "•".
      'B.S. Computer Science, expected May 2027 | Current courses: CS 374, MATH 415',
      'EDUCATION\tCurrent courses: CS 374, MATH 415',
      '• Currently taking: CS 374, MATH 415',
    ]) {
      expect(suggested(imported(line, names)), line).toEqual({ 'CS 374': 'in_progress', 'MATH 415': 'in_progress' });
      // Only a suggestion: nothing leaves the form with it.
      expect(statuses(imported(line, names)), line).toEqual({ 'CS 374': 'unknown', 'MATH 415': 'unknown' });
    }
    expect(suggested(imported('Courses in progress - Machine Learning, Data Mining', ['Data Mining', 'Machine Learning'])))
      .toEqual({ 'Data Mining': 'in_progress', 'Machine Learning': 'in_progress' });
  });

  it('suggests planned for every course of a list after a planned label', () => {
    for (const line of [
      'Planned coursework: CS 446, CS 411',
      'Planned Courses — CS 446, CS 411',
      'Future coursework - CS 446, CS 411',
      'Future courses: CS 446, CS 411',
      'Courses to take: CS 446, CS 411',
      'Upcoming courses: CS 446, CS 411',
    ]) {
      expect(suggested(imported(line, ['CS 411', 'CS 446'])), line).toEqual({ 'CS 411': 'planned', 'CS 446': 'planned' });
    }
  });

  it('ends a list at "|", a tab or the next label, and with its line', () => {
    const cases: Array<[string, Record<string, string | null>]> = [
      ['Current Coursework: CS 374, CS 411 | Completed: CS 225, CS 233', { 'CS 225': null, 'CS 233': null, 'CS 374': 'in_progress', 'CS 411': 'in_progress' }],
      ['Currently taking: CS 374. Completed: CS 225, CS 233.', { 'CS 225': null, 'CS 233': null, 'CS 374': 'in_progress' }],
      ['Planned courses: CS 446 | Taken: CS 225, CS 233', { 'CS 225': null, 'CS 233': null, 'CS 446': 'planned' }],
      ['Current Coursework: CS 374, MATH 415. Skills: Python, Java', { 'CS 374': 'in_progress', Java: null, 'MATH 415': 'in_progress' }],
      // A two-column row: the page keeps the column gap as a tab.
      ['Current Courses: CS 374, CS 411\tCourse Assistant, CS 124 (Fall 2025)', { 'CS 124': null, 'CS 374': 'in_progress', 'CS 411': 'in_progress' }],
      ['Relevant Coursework: CS 225, CS 233 Current courses: CS 374', { 'CS 225': null, 'CS 233': null, 'CS 374': null }],
      ['Current courses: CS 374 Relevant Coursework: CS 225', { 'CS 225': null, 'CS 374': 'in_progress' }],
      ['Current courses: CS 374\nTA for CS 225', { 'CS 225': null, 'CS 374': 'in_progress' }],
    ];
    for (const [text, expected] of cases) {
      expect(suggested(imported(text, Object.keys(expected))), text).toEqual(expected);
    }
  });

  it('suggests nothing for a label inside a sentence or after other words, or one that mixes statuses', () => {
    const lines: Array<[string, string[]]> = [
      ['Peer Mentor: advised 30 freshmen on courses to take: CS 124, CS 128, MATH 221', ['CS 124', 'CS 128', 'MATH 221']],
      ['Wrote a four-year planning guide of courses to take: CS 124, CS 128, CS 173', ['CS 124', 'CS 128', 'CS 173']],
      ['Tutor for students currently taking: CS 225, CS 374', ['CS 225', 'CS 374']],
      ['Graded weekly homework for courses in progress: CS 173, CS 225', ['CS 173', 'CS 225']],
      ['Designed new labs for upcoming courses: ECE 120, ECE 220', ['ECE 120', 'ECE 220']],
      ['Led a survey of students on their planned courses: CS 411, CS 412', ['CS 411', 'CS 412']],
      ['Course Assistant, Current courses: CS 124, CS 128', ['CS 124', 'CS 128']],
      ['Grader — current courses: CS 173', ['CS 173']],
      ['Completed/Current Coursework: CS 225, CS 374', ['CS 225', 'CS 374']],
      ['Past and Current Courses: CS 225, CS 374', ['CS 225', 'CS 374']],
      ['Current and Planned Courses: CS 374, CS 446', ['CS 374', 'CS 446']],
      ['Completed & Planned Courses: CS 225, CS 446', ['CS 225', 'CS 446']],
      ['Relevant Completed and Upcoming Courses: CS 225, CS 411', ['CS 225', 'CS 411']],
      // A résumé read as one run of text: the label opens no line.
      ['EDUCATION University of Illinois Urbana-Champaign, B.S. Computer Engineering, GPA 3.8 Current Coursework: CS 374, MATH 415 '
        + 'EXPERIENCE Course Assistant, CS 124, Aug 2025 - Present. Undergraduate Researcher, used CS 446 models', ['CS 124', 'CS 374', 'CS 446', 'MATH 415']],
    ];
    for (const [line, names] of lines) {
      expect(Object.values(suggested(imported(line, names))), line).toEqual(names.map(() => null));
    }
  });

  it('suggests nothing else on a line', () => {
    const lines: Array<[string, string[]]> = [
      ['Currently a teaching assistant for CS 225', ['CS 225']],
      ['Course Assistant, CS 124 (Current)', ['CS 124']],
      ['Teaching Assistant (Current): CS 225, CS 374', ['CS 225', 'CS 374']],
      ['Current Role: TA for CS 225', ['CS 225']],
      ['Current Projects: Built a compiler for CS 426', ['CS 426']],
      ['Coursework: CS 225, Current Topics in AI (CS 498)', ['CS 225', 'CS 498', 'Current Topics in AI (CS 498)']],
      ['Relevant Coursework: ECE 598 - Current Topics in Machine Learning', ['ECE 598 - Current Topics in Machine Learning']],
      ['CS 598 - Current Research in NLP', ['CS 598']],
      ['Ongoing research: applying CS 446 methods to robot grasping', ['CS 446']],
      ['Grader for CS 173 (current semester)', ['CS 173']],
      ['GPA: 3.9/4.0 (current) Relevant Coursework: CS 225, CS 357', ['CS 225', 'CS 357']],
      ['Class of 2027 (expected) Relevant Courses: CS 225, CS 374', ['CS 225', 'CS 374']],
      ['B.S. CS Expected 2028 Relevant Coursework: CS 225', ['CS 225']],
      ['University of Illinois, B.S. Computer Engineering (expected May 2027) Coursework: ECE 220, ECE 385', ['ECE 220', 'ECE 385']],
      ['Coursework: CS 225 (expected grade A)', ['CS 225']],
      ['Research on future robotics using CS 446', ['CS 446']],
      ['Coursework: CS 225 — Summer 2027 internship applied it', ['CS 225']],
      ['Expected Value and Probability (STAT 400)', ['STAT 400']],
      ['Spring 2027: CS 446, CS 411', ['CS 411', 'CS 446']],
      ["Coursework: CS 446 (Spring '27)", ['CS 446']],
      ['Coursework (in progress): CS 374, CS 411', ['CS 374', 'CS 411']],
      ['Planned: Machine Learning, CS 446', ['CS 446']],
      ['Will take CS 446 next semester', ['CS 446']],
      ['Current courses (Fall 2026): CS 374', ['CS 374']],
      ['Concurrent courses: CS 374', ['CS 374']],
    ];
    for (const [line, names] of lines) {
      expect(Object.values(suggested(imported(line, names))), line).toEqual(names.map(() => null));
    }
  });

  it('suggests nothing where the lines disagree, and reads only status lists among the lines that name a course', () => {
    expect(suggested(imported('Current courses: CS 374\nPlanned courses: CS 374', ['CS 374']))).toEqual({ 'CS 374': null });
    expect(suggested(imported('Relevant Coursework: CS 225, CS 374, MATH 241\nCourse Assistant, CS 225 (Current)\nCurrent coursework: CS 374',
      ['CS 225', 'CS 374', 'MATH 241']))).toEqual({ 'CS 225': null, 'CS 374': 'in_progress', 'MATH 241': null });
  });
});

describe('a status read from the résumé is only a suggestion on the form (R1)', () => {
  const text = 'Current coursework: CS 374\nRelevant Coursework: CS 225';

  it('sends a résumé course as not marked until the student sets it; the suggestion follows the current text', () => {
    const profile = imported(text, ['CS 225', 'CS 374']);
    expect(statuses(profile)).toEqual({ 'CS 225': 'unknown', 'CS 374': 'unknown' });
    expect(suggested(profile)).toEqual({ 'CS 225': null, 'CS 374': 'in_progress' });
    // The same stored courses under another résumé text: another suggestion.
    expect(suggested({ ...profile, resume_text: 'Relevant Coursework: CS 225, CS 374' })).toEqual({ 'CS 225': null, 'CS 374': null });
    expect(suggested({ ...profile, resume_text: 'Planned courses: CS 374' })).toEqual({ 'CS 225': null, 'CS 374': 'planned' });
    // Legacy names are résumé courses nobody set.
    expect(suggested({ coursework: ['CS 374'], resume_text: text })).toEqual({ 'CS 374': 'in_progress' });
    expect(statuses({ coursework: ['CS 374'], resume_text: text })).toEqual({ 'CS 374': 'unknown' });
    // Once confirmed, it is the student's status.
    expect(statuses({ ...profile, courses: [{ name: 'CS 225', source: 'resume' }, { name: 'CS 374', source: 'resume', status: 'in_progress' }] }))
      .toEqual({ 'CS 225': 'unknown', 'CS 374': 'in_progress' });
  });

  it('a status the student set always wins, "not marked" included; a course they added gets no suggestion', () => {
    const profile: CourseProfile = { resume_text: text, coursework: ['CS 374', 'CS 225', 'STAT 400'], courses: [
      { name: 'CS 374', source: 'resume', status: 'unknown' },
      { name: 'CS 225', source: 'resume', status: 'completed' },
      { name: 'STAT 400', source: 'manual', status: 'unknown' },
    ] };
    expect(statuses(profile)).toEqual({ 'CS 374': 'unknown', 'CS 225': 'completed', 'STAT 400': 'unknown' });
    expect(suggested(profile)).toEqual({ 'CS 374': null, 'CS 225': null, 'STAT 400': null });
    expect(suggested({ resume_text: 'Current courses: STAT 400', courses: [{ name: 'STAT 400', source: 'manual', status: 'unknown' }] }))
      .toEqual({ 'STAT 400': null });
  });

  it('shows the status the student set, the suggestion, and the line found in the current text (R3)', () => {
    const rows = courseRows({ resume_text: text, coursework: ['CS 374', 'CS 225', 'STAT 400'], courses: [
      { name: 'CS 374', source: 'resume' },
      { name: 'CS 225', source: 'resume', status: 'completed' },
      { name: 'STAT 400', source: 'manual', status: 'planned' },
    ] });
    expect(rows).toEqual([
      { name: 'CS 374', status: 'unknown', source: 'resume', suggested: 'in_progress', line: 'Current coursework: CS 374' },
      { name: 'CS 225', status: 'completed', source: 'resume', marked: 'completed', line: 'Relevant Coursework: CS 225' },
      { name: 'STAT 400', status: 'planned', source: 'manual', marked: 'planned' },
    ]);
    // A line the current text no longer has is not shown.
    expect(courseRows({ resume_text: '', courses: [{ name: 'CS 225', source: 'resume', status: 'completed' }] }))
      .toEqual([{ name: 'CS 225', status: 'completed', source: 'resume', marked: 'completed' }]);
  });

  it('shows at most 200 characters of a long line, around the course', () => {
    const long = `Relevant Coursework: ${Array.from({ length: 40 }, (_, i) => `ABC ${100 + i}`).join(', ')}, CS 374`;
    const [row] = courseRows({ resume_text: long, coursework: ['CS 374'] });
    expect(row.line!.length).toBeLessThanOrEqual(200);
    expect(row.line).toContain('CS 374');
    expect(long).toContain(row.line!);
  });

  it('an import stores each course found without a status, keeps what the student set and drops what the new résumé no longer lists', () => {
    const profile: CourseProfile = {
      resume_text: 'old',
      courses: [
        { name: 'CS 125', source: 'resume' },
        { name: 'CS 173', source: 'resume', status: 'completed' },
        { name: 'CS 233', source: 'resume', status: 'unknown' },
        { name: 'CS 225', source: 'resume', status: 'planned' },
        { name: 'STAT 400', source: 'manual', status: 'unknown' },
      ],
      coursework: ['CS 125', 'CS 173', 'CS 233', 'CS 225', 'STAT 400', 'ECE 110'],
    };
    expect(importResumeCourses(profile, ['cs 225', 'STAT 400', 'CS 374', 'CS 374'])).toEqual([
      { name: 'CS 173', source: 'resume', status: 'completed' },
      { name: 'CS 225', source: 'resume', status: 'planned' },
      { name: 'STAT 400', source: 'manual', status: 'unknown' },
      { name: 'CS 374', source: 'resume' },
    ]);
    expect(importResumeCourses({}, ['CS 374'])).toEqual([{ name: 'CS 374', source: 'resume' }]);
  });

  it('removing the résumé keeps only courses the student added or marked, so no suggestion stays', () => {
    const profile: CourseProfile = {
      resume_text: 'Current coursework: CS 374, CS 446\nRelevant Coursework: CS 125',
      courses: [
        { name: 'CS 125', source: 'resume' },
        { name: 'CS 374', source: 'resume' },
        { name: 'CS 446', source: 'resume', status: 'planned' },
        { name: 'CS 233', source: 'resume', status: 'unknown' },
        { name: 'STAT 400', source: 'manual', status: 'unknown' },
      ],
      coursework: ['CS 125', 'CS 374', 'CS 446', 'CS 233', 'STAT 400', 'ECE 110'],
    };
    expect(suggested(profile)['CS 374']).toBe('in_progress');
    expect(coursesWithoutResume(profile)).toEqual([
      { name: 'CS 446', source: 'resume', status: 'planned' },
      { name: 'STAT 400', source: 'manual', status: 'unknown' },
    ]);
    expect(coursesWithoutResume({ coursework: ['CS 225'] })).toEqual([]);
  });
});

describe('a résumé course nobody marked counts only while the stored coursework names it (R4)', () => {
  // What this build stores after importing a résumé, with one course marked
  // and one added on the form.
  const stored: CourseProfile = {
    resume_text: 'Relevant Coursework: CS 225, CS 233, MATH 257\nCurrent courses: CS 374',
    courses: [
      { name: 'CS 225', source: 'resume' },
      { name: 'CS 233', source: 'resume', status: 'unknown' },
      { name: 'CS 374', source: 'resume' },
      { name: 'MATH 257', source: 'resume', status: 'completed' },
      { name: 'STAT 400', source: 'manual', status: 'unknown' },
    ],
    coursework: ['CS 225', 'CS 233', 'CS 374', 'MATH 257', 'STAT 400'],
  };

  it('honours a removal by a tab on the previous build, which clears only coursework and the text', () => {
    expect(courseEntries({ ...stored, resume_text: '', coursework: [] })).toEqual([
      { name: 'MATH 257', status: 'completed', source: 'resume' },
      { name: 'STAT 400', status: 'unknown', source: 'manual' },
    ]);
    expect(courseRows({ ...stored, resume_text: '', coursework: [] }).some((row) => row.line || row.suggested)).toBe(false);
  });

  it('honours a re-import by a tab on the previous build, which writes the new names and text', () => {
    const reimported = { ...stored, resume_text: 'Relevant Coursework: CS 225\nPlanned courses: CS 411, CS 374', coursework: ['CS 225', 'CS 374', 'CS 411'] };
    expect(courseEntries(reimported)).toEqual([
      { name: 'CS 225', status: 'unknown', source: 'resume' },
      { name: 'CS 374', status: 'unknown', source: 'resume' },
      { name: 'MATH 257', status: 'completed', source: 'resume' },
      { name: 'STAT 400', status: 'unknown', source: 'manual' },
      { name: 'CS 411', status: 'unknown', source: 'resume' },
    ]);
    expect(suggested(reimported)).toEqual({ 'CS 225': null, 'CS 374': 'planned', 'MATH 257': null, 'STAT 400': null, 'CS 411': 'planned' });
  });
});
