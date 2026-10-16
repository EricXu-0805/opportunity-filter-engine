import { useState } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { translate } from '@/i18n/translate';
import type { Locale } from '@/i18n/dictionaries';

const i18n = vi.hoisted(() => ({ locale: 'en' as Locale }));
vi.mock('@/i18n/client', () => ({
  useLocale: () => i18n.locale,
  useT: () => ({ locale: i18n.locale, t: (key: string, vars?: Record<string, string | number>) => translate(i18n.locale, key, vars) }),
}));

import CourseList from './CourseList';
import { courseRows } from '@/lib/course-status';
import type { ProfileData, StoredCourse } from '@/lib/types';

// The form's own read of the profile: the rows come from the stored courses
// and the current résumé text, exactly as AcademicProfileCard builds them.
const RESUME = 'Relevant Coursework: CS 225, CS 446\nCurrent courses: CS 374';
const STORED: StoredCourse[] = [
  { name: 'CS 225', source: 'resume' },
  { name: 'CS 374', source: 'resume' },
  { name: 'CS 446', source: 'resume', status: 'planned' },
  { name: 'STAT 400', source: 'manual', status: 'completed' },
];

function Harness({ initial, onChange, resume = RESUME }: {
  initial: StoredCourse[]; onChange: (courses: StoredCourse[]) => void; resume?: string;
}) {
  const [profile, setProfile] = useState<Pick<ProfileData, 'courses' | 'coursework' | 'resume_text'>>({
    courses: initial, coursework: initial.map((course) => course.name), resume_text: resume,
  });
  return (
    <CourseList
      courses={courseRows(profile)}
      onChange={(next) => {
        setProfile((prev) => ({ ...prev, courses: next, coursework: next.map((course) => course.name) }));
        onChange(next);
      }}
    />
  );
}

afterEach(() => { cleanup(); i18n.locale = 'en'; });

describe('CourseList (checklist M13)', () => {
  it('shows each course with its status, the résumé line found in the current text, and what is left to mark or check', () => {
    render(<Harness initial={STORED} onChange={vi.fn()} />);
    expect(screen.getByRole('group', { name: 'Courses' })).toBeTruthy();
    const status = screen.getByLabelText('Status of CS 225') as HTMLSelectElement;
    expect(status.value).toBe('unknown');
    expect(within(status).getAllByRole('option').map((option) => option.textContent))
      .toEqual(['Completed', 'In progress', 'Planned', 'Not marked']);
    expect((screen.getByLabelText('Status of CS 374') as HTMLSelectElement).value).toBe('in_progress');
    expect((screen.getByLabelText('Status of CS 446') as HTMLSelectElement).value).toBe('planned');
    expect((screen.getByLabelText('Status of STAT 400') as HTMLSelectElement).value).toBe('completed');
    // The same spelling as the résumé removal note.
    expect(screen.getAllByText('From your résumé: “Relevant Coursework: CS 225, CS 446”')).toHaveLength(2);
    expect(screen.getByText('From your résumé: “Current courses: CS 374”')).toBeTruthy();
    // A course added on the form has no résumé line to show.
    expect(screen.getAllByText(/^From your résumé: /)).toHaveLength(3);
    // Only the status the résumé suggests asks to be checked.
    expect(screen.getAllByText('From your résumé — please check')).toHaveLength(1);
    const left = screen.getByRole('status');
    expect(within(left).getByText('Not marked yet: 1. Until you mark a course, it is only listed as part of your coursework, never as completed.')).toBeTruthy();
    expect(within(left).getByText('Suggested by your résumé, not used until you confirm: 1.')).toBeTruthy();
  });

  it('confirms a status read from the résumé as the student\'s own, and moves focus to its status', () => {
    const onChange = vi.fn();
    render(<Harness initial={STORED} onChange={onChange} />);
    fireEvent.click(screen.getByRole('button', { name: 'Confirm In progress for CS 374' }));
    expect(onChange).toHaveBeenLastCalledWith([
      { name: 'CS 225', source: 'resume' },
      { name: 'CS 374', source: 'resume', status: 'in_progress' },
      { name: 'CS 446', source: 'resume', status: 'planned' },
      { name: 'STAT 400', source: 'manual', status: 'completed' },
    ]);
    expect(screen.queryByText('From your résumé — please check')).toBeNull();
    expect(document.activeElement).toBe(screen.getByLabelText('Status of CS 374'));
  });

  it('marks, removes and adds courses, writing back no status for a course the student has not set', () => {
    const onChange = vi.fn();
    render(<Harness initial={STORED} onChange={onChange} />);
    fireEvent.change(screen.getByLabelText('Status of CS 374'), { target: { value: 'planned' } });
    expect(onChange).toHaveBeenLastCalledWith([
      { name: 'CS 225', source: 'resume' },
      { name: 'CS 374', source: 'resume', status: 'planned' },
      { name: 'CS 446', source: 'resume', status: 'planned' },
      { name: 'STAT 400', source: 'manual', status: 'completed' },
    ]);

    fireEvent.click(screen.getByRole('button', { name: 'Remove CS 446' }));
    expect(onChange).toHaveBeenLastCalledWith([
      { name: 'CS 225', source: 'resume' },
      { name: 'CS 374', source: 'resume', status: 'planned' },
      { name: 'STAT 400', source: 'manual', status: 'completed' },
    ]);

    fireEvent.change(screen.getByLabelText('Add a course'), { target: { value: '  ECE 220 ' } });
    fireEvent.change(screen.getByLabelText('Status of the new course'), { target: { value: 'in_progress' } });
    fireEvent.click(screen.getByRole('button', { name: 'Add' }));
    expect(onChange).toHaveBeenLastCalledWith([
      { name: 'CS 225', source: 'resume' },
      { name: 'CS 374', source: 'resume', status: 'planned' },
      { name: 'STAT 400', source: 'manual', status: 'completed' },
      { name: 'ECE 220', source: 'manual', status: 'in_progress' },
    ]);
    expect((screen.getByLabelText('Add a course') as HTMLInputElement).value).toBe('');
    expect((screen.getByLabelText('Status of the new course') as HTMLSelectElement).value).toBe('unknown');

    // The same course however it is spaced or cased is not added twice.
    fireEvent.change(screen.getByLabelText('Add a course'), { target: { value: 'ece220' } });
    fireEvent.keyDown(screen.getByLabelText('Add a course'), { key: 'Enter' });
    expect(onChange).toHaveBeenCalledTimes(3);
    expect(screen.getByRole('status').textContent).toBe('ECE 220 is already listed.');
  });

  it('after Remove, moves focus to the next row\'s status, or to the add field when no row follows', () => {
    render(<Harness initial={STORED} onChange={vi.fn()} />);
    screen.getByRole('button', { name: 'Remove CS 374' }).focus();
    fireEvent.click(screen.getByRole('button', { name: 'Remove CS 374' }));
    expect(document.activeElement).toBe(screen.getByLabelText('Status of CS 446'));

    screen.getByRole('button', { name: 'Remove STAT 400' }).focus();
    fireEvent.click(screen.getByRole('button', { name: 'Remove STAT 400' }));
    expect(document.activeElement).toBe(screen.getByLabelText('Add a course'));

    fireEvent.click(screen.getByRole('button', { name: 'Remove CS 225' }));
    fireEvent.click(screen.getByRole('button', { name: 'Remove CS 446' }));
    expect(screen.getByText('No courses yet. Upload your résumé, or add a course below.')).toBeTruthy();
    expect(document.activeElement).toBe(screen.getByLabelText('Add a course'));
  });

  it('shows no résumé status for a label inside a sentence, after other words, mixing statuses, or past its field', () => {
    // review-m13fe-a round 2: each of these marked courses that are not the
    // student's current or planned ones.
    const cases: Array<[string, string[]]> = [
      ['Peer Mentor: advised 30 freshmen on courses to take: CS 124, CS 128, MATH 221', ['CS 124', 'CS 128', 'MATH 221']],
      ['Tutor for students currently taking: CS 225, CS 374', ['CS 225', 'CS 374']],
      ['Graded weekly homework for courses in progress: CS 173, CS 225', ['CS 173', 'CS 225']],
      ['Designed new labs for upcoming courses: ECE 120, ECE 220', ['ECE 120', 'ECE 220']],
      ['Course Assistant, Current courses: CS 124, CS 128', ['CS 124', 'CS 128']],
      ['Completed/Current Coursework: CS 225, CS 374', ['CS 225', 'CS 374']],
      ['Completed & Planned Courses: CS 225, CS 446', ['CS 225', 'CS 446']],
      ['Current Coursework: CS 374, CS 411 | Completed: CS 225, CS 233', ['CS 225', 'CS 233']],
      ['Currently taking: CS 374. Completed: CS 225, CS 233.', ['CS 225', 'CS 233']],
      ['Current Courses: CS 374, CS 411\tCourse Assistant, CS 124 (Fall 2025)', ['CS 124']],
      ['EDUCATION B.S. Computer Engineering, GPA 3.8 Current Coursework: CS 374 EXPERIENCE Course Assistant, CS 124', ['CS 124', 'CS 374']],
    ];
    for (const [line, names] of cases) {
      render(<Harness initial={names.map((name) => ({ name, source: 'resume' }))} onChange={vi.fn()} resume={line} />);
      for (const name of names) expect((screen.getByLabelText(`Status of ${name}`) as HTMLSelectElement).value, `${line} / ${name}`).toBe('unknown');
      expect(screen.queryByText('From your résumé — please check'), line).toBeNull();
      cleanup();
    }
  });

  it('says so when there are no courses yet', () => {
    render(<Harness initial={[]} onChange={vi.fn()} />);
    expect(screen.getByText('No courses yet. Upload your résumé, or add a course below.')).toBeTruthy();
    expect((screen.getByRole('button', { name: 'Add' }) as HTMLButtonElement).disabled).toBe(true);
  });

  it('reads in Chinese with the same four choices', () => {
    i18n.locale = 'zh';
    render(<Harness initial={STORED} onChange={vi.fn()} />);
    expect(screen.getByRole('group', { name: '课程' })).toBeTruthy();
    const status = screen.getByLabelText('CS 225 的状态') as HTMLSelectElement;
    expect(within(status).getAllByRole('option').map((option) => option.textContent)).toEqual(['已修', '在修', '计划修', '未标']);
    expect(screen.getByText('来自你的简历：「Current courses: CS 374」')).toBeTruthy();
    expect(screen.getByText('据简历推断，请确认')).toBeTruthy();
    expect(screen.getByRole('button', { name: '确认 CS 374 为「在修」' })).toBeTruthy();
    const left = screen.getByRole('status');
    // One course is not "它们".
    expect(within(left).getByText('有 1 门课还未标注。未标注的课只会被列为你的课程之一，不会写成已修。')).toBeTruthy();
    expect(within(left).getByText('有 1 门课的状态是据简历推断的，确认后才会使用。')).toBeTruthy();
    expect(screen.getByRole('button', { name: '移除 CS 446' })).toBeTruthy();
    expect((screen.getByLabelText('添加课程') as HTMLInputElement).placeholder).toBe('例如 CS 225 或数据结构');
  });
});
