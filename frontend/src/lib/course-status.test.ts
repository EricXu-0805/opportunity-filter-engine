import { describe, expect, it } from 'vitest';
import {
  COURSE_STATEMENTS, courseEntries, courseFields, courseKey, courseSentences, coursesWithoutResume,
  importResumeCourses, isCourseList, resumeCourses,
} from './course-status';
import type { CourseEntry } from './types';

const completed = (name: string, source: CourseEntry['source'] = 'resume'): CourseEntry => ({ name, status: 'completed', source });

describe('one course rule, mirrored from src/student_evidence.py', () => {
  it('words each status as the server does', () => {
    expect(COURSE_STATEMENTS).toEqual({
      completed: 'I have completed {courses}.',
      in_progress: 'I am currently taking {courses}.',
      planned: 'I plan to take {courses}.',
      unknown: 'My coursework includes {courses}.',
    });
  });

  it('reads a course however it is spaced or cased', () => {
    expect(courseKey('CS 225')).toBe('cs225');
    expect(courseKey(' cs-225 ')).toBe('cs225');
    expect(courseKey('ＣＳ２２５')).toBe('cs225');
    expect(courseKey('-')).toBe('');
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
    ] as unknown as CourseEntry[];
    expect(courseEntries({ courses: stored })).toEqual([
      { name: 'CS 225', status: 'unknown', source: 'resume', evidence: 'CS 225 line' },
    ]);
  });

  it('writes the names next to the courses for clients that read only coursework', () => {
    expect(courseFields([completed('CS 225'), completed('cs225'), { name: 'CS 446', status: 'planned', source: 'manual' }])).toEqual({
      courses: [completed('CS 225'), { name: 'CS 446', status: 'planned', source: 'manual' }],
      coursework: ['CS 225', 'CS 446'],
    });
  });

  it('knows a course list from anything else in storage', () => {
    expect(isCourseList([completed('CS 225')])).toBe(true);
    expect(isCourseList([])).toBe(true);
    expect(isCourseList(['CS 225'])).toBe(false);
    expect(isCourseList([{ name: 'CS 225', status: 1 }])).toBe(false);
    expect(isCourseList(null)).toBe(false);
  });
});

describe('a résumé import and a résumé removal', () => {
  const found = (course: string, status: 'planned' | 'in_progress' | 'unknown' = 'unknown', line = `Coursework: ${course}`) => ({ course, status, line });

  it('marks a new course only as its line says, and never as completed', () => {
    expect(resumeCourses({
      extracted_coursework: ['CS 225', 'CS 446'],
      course_evidence: [found('CS 225'), { course: 'CS 446', status: 'completed' as 'unknown', line: 'CS 446' }],
    })).toEqual([found('CS 225'), { course: 'CS 446', status: 'unknown', line: 'CS 446' }]);
    // An older parse response: names only.
    expect(resumeCourses({ extracted_coursework: ['CS 225'] })).toEqual([{ course: 'CS 225', status: 'unknown', line: '' }]);
  });

  it('keeps a status the student set on a re-import, and the new résumé line', () => {
    const profile = { courses: [
      { name: 'CS 225', status: 'completed' as const, source: 'resume' as const, evidence: 'old line' },
      { name: 'CS 446', status: 'unknown' as const, source: 'resume' as const, evidence: 'old line' },
    ] };
    expect(importResumeCourses(profile, [found('cs 225'), found('CS 446', 'planned', 'Planned: CS 446'), found('CS 374', 'in_progress')])).toEqual([
      { name: 'CS 225', status: 'completed', source: 'resume', evidence: 'Coursework: cs 225' },
      { name: 'CS 446', status: 'planned', source: 'resume', evidence: 'Planned: CS 446' },
      { name: 'CS 374', status: 'in_progress', source: 'resume', evidence: 'Coursework: CS 374' },
    ]);
  });

  it('drops an unmarked course the new résumé no longer lists, keeps a marked one without the old line, and leaves added courses alone', () => {
    const profile = {
      courses: [
        { name: 'CS 125', status: 'unknown' as const, source: 'resume' as const, evidence: 'old' },
        { name: 'CS 173', status: 'completed' as const, source: 'resume' as const, evidence: 'old' },
        { name: 'STAT 400', status: 'unknown' as const, source: 'manual' as const },
      ],
      coursework: ['CS 125', 'CS 173', 'STAT 400', 'ECE 110'],
    };
    expect(importResumeCourses(profile, [found('STAT 400', 'planned')])).toEqual([
      { name: 'CS 173', status: 'completed', source: 'resume' },
      { name: 'STAT 400', status: 'unknown', source: 'manual' },
    ]);
  });

  it('removing the résumé drops only the résumé courses nobody marked', () => {
    const profile = {
      courses: [
        { name: 'CS 125', status: 'unknown' as const, source: 'resume' as const, evidence: 'Coursework: CS 125' },
        { name: 'CS 446', status: 'planned' as const, source: 'resume' as const, evidence: 'Planned: CS 446' },
        { name: 'STAT 400', status: 'unknown' as const, source: 'manual' as const },
      ],
      coursework: ['CS 125', 'CS 446', 'STAT 400', 'ECE 110'],
    };
    expect(coursesWithoutResume(profile)).toEqual([
      { name: 'CS 446', status: 'planned', source: 'resume' },
      { name: 'STAT 400', status: 'unknown', source: 'manual' },
    ]);
    // A profile saved before statuses: every course came from the résumé.
    expect(coursesWithoutResume({ coursework: ['CS 225'] })).toEqual([]);
  });
});
