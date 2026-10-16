'use client';

import { useId, useState } from 'react';
import { Plus, X } from 'lucide-react';
import type { CourseEntry, CourseStatus } from '@/lib/types';
import { courseKey } from '@/lib/course-status';
import { useT } from '@/i18n/client';

/** The order the student reads the choices in. */
const STATUS_CHOICES: readonly CourseStatus[] = ['completed', 'in_progress', 'planned', 'unknown'];
/** The profile's course limit (lib/profile-input.ts). */
const COURSE_LIMIT = 512;
const COURSE_TEXT_LIMIT = 1000;

/**
 * The student's courses, one row each, with the status they give it.
 *
 * A row per course rather than a chip: four statuses do not fit inside a chip
 * on a phone, and a native select is a full-size control there. A course read
 * from the résumé shows the line it was found on, so the student can see why
 * it is listed, and why it is marked planned or in progress if it is.
 */
export default function CourseList({ courses, onChange }: {
  courses: CourseEntry[];
  onChange: (courses: CourseEntry[]) => void;
}) {
  const { t } = useT();
  const id = useId();
  const [name, setName] = useState('');
  const [status, setStatus] = useState<CourseStatus>('unknown');
  const [notice, setNotice] = useState<string | null>(null);
  const unmarked = courses.filter((course) => course.status === 'unknown').length;

  const add = () => {
    const trimmed = name.trim();
    if (!courseKey(trimmed)) return;
    const existing = courses.find((course) => courseKey(course.name) === courseKey(trimmed));
    if (existing) { setNotice(t('courses.duplicate', { course: existing.name })); return; }
    if (courses.length >= COURSE_LIMIT) { setNotice(t('courses.full', { limit: COURSE_LIMIT })); return; }
    onChange([...courses, { name: trimmed, status, source: 'manual' }]);
    setName('');
    setStatus('unknown');
    setNotice(null);
  };

  return (
    <fieldset aria-describedby={`${id}-hint`}>
      <legend className="block text-sm font-medium text-gray-700 mb-2">{t('courses.label')}</legend>
      <p id={`${id}-hint`} className="mb-3 text-xs leading-relaxed text-gray-500">{t('courses.hint')}</p>
      {courses.length === 0 ? (
        <p className="mb-3 text-sm text-gray-500">{t('courses.empty')}</p>
      ) : (
        <ul className="mb-3 space-y-2">
          {courses.map((course, index) => {
            const selectId = `${id}-status-${index}`;
            return (
              <li key={courseKey(course.name)} className="rounded-xl border border-gray-200 bg-white px-3 py-2">
                <div className="flex items-center gap-2">
                  <span className="min-w-0 flex-1 text-sm font-medium text-gray-800 [overflow-wrap:anywhere]">{course.name}</span>
                  <label htmlFor={selectId} className="sr-only">{t('courses.statusOf', { course: course.name })}</label>
                  <select
                    id={selectId}
                    value={course.status}
                    onChange={(e) => onChange(courses.map((item, at) => (
                      at === index ? { ...item, status: e.target.value as CourseStatus } : item
                    )))}
                    className={`h-9 shrink-0 rounded-lg border px-2 text-[13px] outline-none focus:ring-2 focus:ring-indigo-500/20 ${
                      course.status === 'unknown' ? 'border-dashed border-amber-300 text-amber-800' : 'border-gray-200 text-gray-700'
                    }`}
                  >
                    {STATUS_CHOICES.map((choice) => (
                      <option key={choice} value={choice}>{t(`courses.status.${choice}`)}</option>
                    ))}
                  </select>
                  <button
                    type="button"
                    onClick={() => onChange(courses.filter((_, at) => at !== index))}
                    aria-label={t('courses.remove', { course: course.name })}
                    className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg text-gray-400 hover:bg-black/5 hover:text-gray-600 transition-colors"
                  >
                    <X className="h-4 w-4" />
                  </button>
                </div>
                {course.source === 'resume' && course.evidence ? (
                  // One line on a phone; opening it wraps the whole quote, as
                  // a skill's source line does.
                  <details className="group/source mt-1 min-w-0 text-[11px] leading-snug text-gray-600">
                    <summary className="cursor-pointer truncate group-open/source:whitespace-normal group-open/source:[overflow-wrap:anywhere]">
                      {t('courses.fromResume', { line: course.evidence })}
                    </summary>
                  </details>
                ) : null}
              </li>
            );
          })}
        </ul>
      )}
      <p role="status" aria-live="polite" className={`mb-3 text-xs ${unmarked > 0 || notice ? 'text-amber-700' : 'sr-only'}`}>
        {notice ?? (unmarked > 0 ? t('courses.unmarked', { count: unmarked }) : '')}
      </p>
      <div className="flex flex-wrap items-center gap-2">
        <label htmlFor={`${id}-add`} className="sr-only">{t('courses.addLabel')}</label>
        <input
          id={`${id}-add`}
          type="text"
          value={name}
          maxLength={COURSE_TEXT_LIMIT}
          onChange={(e) => { setName(e.target.value); setNotice(null); }}
          onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); add(); } }}
          placeholder={t('courses.addPlaceholder')}
          className="h-10 min-w-0 flex-1 basis-40 rounded-xl border border-gray-200 px-3 text-sm text-gray-700 placeholder:text-gray-400 outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-300"
        />
        <label htmlFor={`${id}-add-status`} className="sr-only">{t('courses.addStatus')}</label>
        <select
          id={`${id}-add-status`}
          value={status}
          onChange={(e) => setStatus(e.target.value as CourseStatus)}
          className="h-10 shrink-0 rounded-xl border border-gray-200 px-2 text-[13px] text-gray-700 outline-none focus:ring-2 focus:ring-indigo-500/20"
        >
          {STATUS_CHOICES.map((choice) => (
            <option key={choice} value={choice}>{t(`courses.status.${choice}`)}</option>
          ))}
        </select>
        <button
          type="button"
          onClick={add}
          disabled={!courseKey(name.trim())}
          className="inline-flex h-10 shrink-0 items-center gap-1 rounded-xl bg-indigo-600 px-3 text-[13px] font-medium text-white transition-colors hover:bg-indigo-700 disabled:cursor-not-allowed disabled:bg-gray-300"
        >
          <Plus className="h-4 w-4" />
          {t('courses.add')}
        </button>
      </div>
    </fieldset>
  );
}
