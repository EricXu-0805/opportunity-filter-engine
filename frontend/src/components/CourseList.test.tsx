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
import type { CourseEntry } from '@/lib/types';

const COURSES: CourseEntry[] = [
  { name: 'CS 225', status: 'unknown', source: 'resume', evidence: 'Relevant Coursework: CS 225, CS 446' },
  { name: 'CS 446', status: 'planned', source: 'resume', evidence: 'Planned: CS 446 (Spring 2027)' },
  { name: 'STAT 400', status: 'completed', source: 'manual' },
];

function Harness({ initial, onChange }: { initial: CourseEntry[]; onChange: (courses: CourseEntry[]) => void }) {
  const [courses, setCourses] = useState(initial);
  return <CourseList courses={courses} onChange={(next) => { setCourses(next); onChange(next); }} />;
}

afterEach(() => { cleanup(); i18n.locale = 'en'; });

describe('CourseList (checklist M13)', () => {
  it('shows each course with its status, the résumé line it came from, and how many are not marked', () => {
    render(<Harness initial={COURSES} onChange={vi.fn()} />);
    expect(screen.getByRole('group', { name: 'Courses' })).toBeTruthy();
    const status = screen.getByLabelText('Status of CS 225') as HTMLSelectElement;
    expect(status.value).toBe('unknown');
    expect(within(status).getAllByRole('option').map((option) => option.textContent))
      .toEqual(['Completed', 'In progress', 'Planned', 'Not marked']);
    expect((screen.getByLabelText('Status of CS 446') as HTMLSelectElement).value).toBe('planned');
    expect((screen.getByLabelText('Status of STAT 400') as HTMLSelectElement).value).toBe('completed');
    expect(screen.getByText('From your résumé: “Relevant Coursework: CS 225, CS 446”')).toBeTruthy();
    expect(screen.getByText('From your résumé: “Planned: CS 446 (Spring 2027)”')).toBeTruthy();
    // A course added on the form has no résumé line to show.
    expect(screen.getAllByText(/^From your résumé/)).toHaveLength(2);
    expect(screen.getByRole('status').textContent).toBe(
      '1 not marked yet. Until you mark them they are only listed as part of your coursework, never as completed.');
  });

  it('marks, removes and adds courses, an added one by hand', () => {
    const onChange = vi.fn();
    render(<Harness initial={COURSES} onChange={onChange} />);
    fireEvent.change(screen.getByLabelText('Status of CS 225'), { target: { value: 'completed' } });
    expect(onChange).toHaveBeenLastCalledWith([{ ...COURSES[0], status: 'completed' }, COURSES[1], COURSES[2]]);
    expect(screen.getByRole('status').textContent).toBe('');

    fireEvent.click(screen.getByRole('button', { name: 'Remove CS 446' }));
    expect(onChange).toHaveBeenLastCalledWith([{ ...COURSES[0], status: 'completed' }, COURSES[2]]);

    fireEvent.change(screen.getByLabelText('Add a course'), { target: { value: '  ECE 220 ' } });
    fireEvent.change(screen.getByLabelText('Status of the new course'), { target: { value: 'in_progress' } });
    fireEvent.click(screen.getByRole('button', { name: 'Add' }));
    expect(onChange).toHaveBeenLastCalledWith([
      { ...COURSES[0], status: 'completed' }, COURSES[2], { name: 'ECE 220', status: 'in_progress', source: 'manual' },
    ]);
    expect((screen.getByLabelText('Add a course') as HTMLInputElement).value).toBe('');
    expect((screen.getByLabelText('Status of the new course') as HTMLSelectElement).value).toBe('unknown');

    // The same course however it is spaced or cased is not added twice.
    fireEvent.change(screen.getByLabelText('Add a course'), { target: { value: 'ece220' } });
    fireEvent.keyDown(screen.getByLabelText('Add a course'), { key: 'Enter' });
    expect(onChange).toHaveBeenCalledTimes(3);
    expect(screen.getByRole('status').textContent).toBe('ECE 220 is already listed.');
  });

  it('says so when there are no courses yet', () => {
    render(<Harness initial={[]} onChange={vi.fn()} />);
    expect(screen.getByText('No courses yet. Upload your résumé, or add a course below.')).toBeTruthy();
    expect((screen.getByRole('button', { name: 'Add' }) as HTMLButtonElement).disabled).toBe(true);
  });

  it('reads in Chinese with the same four choices', () => {
    i18n.locale = 'zh';
    render(<Harness initial={COURSES} onChange={vi.fn()} />);
    expect(screen.getByRole('group', { name: '课程' })).toBeTruthy();
    const status = screen.getByLabelText('CS 225 的状态') as HTMLSelectElement;
    expect(within(status).getAllByRole('option').map((option) => option.textContent)).toEqual(['已修', '在修', '计划修', '未标']);
    expect(screen.getByText('来自你的简历：「Relevant Coursework: CS 225, CS 446」')).toBeTruthy();
    expect(screen.getByRole('status').textContent).toBe('有 1 门课还未标注。标注之前，它们只会被列为你的课程之一，不会写成已修。');
    expect(screen.getByRole('button', { name: '移除 CS 446' })).toBeTruthy();
    expect(screen.getByLabelText('添加课程')).toBeTruthy();
  });
});
