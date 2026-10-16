'use client';

import { useEffect, useId, useRef, useState } from 'react';
import { Plus, X } from 'lucide-react';
import type { CourseStatus, StoredCourse } from '@/lib/types';
import { courseKey, storedCourse, type CourseRow } from '@/lib/course-status';
import { useT } from '@/i18n/client';

/** The order the student reads the choices in. */
const STATUS_CHOICES: readonly CourseStatus[] = ['completed', 'in_progress', 'planned', 'unknown'];
/** The profile's course limit (lib/profile-input.ts). */
const COURSE_LIMIT = 512;
const COURSE_TEXT_LIMIT = 1000;

/** Where focus goes once the list is drawn again after an action that takes
 *  the focused control away. */
type PendingFocus = { after: 'remove'; removed: string; index: number } | { after: 'confirm'; course: string };

/** What the course's select shows: the student's status, else the one the
 *  résumé suggests, else not marked. */
const shown = (course: CourseRow): CourseStatus => course.marked ?? course.suggested ?? 'unknown';

/**
 * The student's courses, one row each, with the status they give it.
 *
 * A row per course rather than a chip: four statuses do not fit inside a chip
 * on a phone, and a native select is a full-size control there. A course read
 * from the résumé shows the line it sits on, so the student can see why it is
 * listed. A status that line suggests is shown as one to check: until the
 * student confirms or changes it, it is not stored and the course goes out as
 * not marked.
 */
export default function CourseList({ courses, onChange }: {
  courses: CourseRow[];
  onChange: (courses: StoredCourse[]) => void;
}) {
  const { t } = useT();
  const id = useId();
  const [name, setName] = useState('');
  const [status, setStatus] = useState<CourseStatus>('unknown');
  const [notice, setNotice] = useState<string | null>(null);
  const pendingFocus = useRef<PendingFocus | null>(null);
  const unmarked = courses.filter((course) => course.status === 'unknown' && !course.suggested).length;
  const toCheck = courses.filter((course) => course.suggested).length;

  useEffect(() => {
    const focus = pendingFocus.current;
    if (!focus) return;
    pendingFocus.current = null;
    const at = (key: string) => courses.findIndex((course) => courseKey(course.name) === key);
    if (focus.after === 'remove') {
      // Not removed after all (the form did not take the edit): focus stays.
      if (at(focus.removed) >= 0) return;
      document.getElementById(focus.index < courses.length ? `${id}-status-${focus.index}` : `${id}-add`)?.focus();
      return;
    }
    const index = at(focus.course);
    if (index >= 0 && courses[index].marked !== undefined) document.getElementById(`${id}-status-${index}`)?.focus();
  }, [courses, id]);

  const mark = (index: number, value: CourseStatus) => {
    onChange(courses.map((course, at) => storedCourse(at === index ? { ...course, marked: value } : course)));
  };

  const add = () => {
    const trimmed = name.trim();
    if (!courseKey(trimmed)) return;
    const existing = courses.find((course) => courseKey(course.name) === courseKey(trimmed));
    if (existing) { setNotice(t('courses.duplicate', { course: existing.name })); return; }
    if (courses.length >= COURSE_LIMIT) { setNotice(t('courses.full', { limit: COURSE_LIMIT })); return; }
    onChange([...courses.map(storedCourse), { name: trimmed, source: 'manual', status }]);
    setName('');
    setStatus('unknown');
    setNotice(null);
  };

  return (
    // min-w-0: a fieldset is otherwise as wide as its widest line, and one
    // long résumé line pushed the rows past a phone's edge and under the next
    // card on a desktop.
    <fieldset aria-describedby={`${id}-hint`} className="min-w-0">
      <legend className="block text-sm font-medium text-gray-700 mb-2">{t('courses.label')}</legend>
      <p id={`${id}-hint`} className="mb-3 text-xs leading-relaxed text-gray-500">{t('courses.hint')}</p>
      {courses.length === 0 ? (
        <p className="mb-3 text-sm text-gray-500">{t('courses.empty')}</p>
      ) : (
        <ul className="mb-3 space-y-2">
          {courses.map((course, index) => {
            const selectId = `${id}-status-${index}`;
            const { suggested } = course;
            return (
              <li key={courseKey(course.name)} className="rounded-xl border border-gray-200 bg-white px-3 py-2">
                <div className="flex items-center gap-2">
                  <span className="min-w-0 flex-1 text-sm font-medium text-gray-800 [overflow-wrap:anywhere]">{course.name}</span>
                  <label htmlFor={selectId} className="sr-only">{t('courses.statusOf', { course: course.name })}</label>
                  <select
                    id={selectId}
                    value={shown(course)}
                    onChange={(e) => mark(index, e.target.value as CourseStatus)}
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
                    onClick={() => {
                      pendingFocus.current = { after: 'remove', removed: courseKey(course.name), index };
                      onChange(courses.filter((_, at) => at !== index).map(storedCourse));
                    }}
                    aria-label={t('courses.remove', { course: course.name })}
                    className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg text-gray-400 hover:bg-black/5 hover:text-gray-600 transition-colors"
                  >
                    <X className="h-4 w-4" />
                  </button>
                </div>
                {suggested ? (
                  <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] leading-snug text-amber-800">
                    <span>{t('courses.inferred')}</span>
                    <button
                      type="button"
                      onClick={() => {
                        pendingFocus.current = { after: 'confirm', course: courseKey(course.name) };
                        mark(index, suggested);
                      }}
                      aria-label={t('courses.confirmLabel', { course: course.name, status: t(`courses.status.${suggested}`) })}
                      className="rounded-md border border-amber-300 px-2 py-0.5 font-medium hover:bg-amber-50 transition-colors"
                    >
                      {t('courses.confirm')}
                    </button>
                  </div>
                ) : null}
                {course.source === 'resume' && course.line ? (
                  // One line on a phone; opening it wraps the whole quote, as
                  // a skill's source line does. At least 24 px tall, a target
                  // a finger can hit.
                  <details className="group/source mt-1 min-w-0 text-[11px] leading-snug text-gray-600">
                    <summary className="min-h-6 cursor-pointer truncate py-1 group-open/source:whitespace-normal group-open/source:[overflow-wrap:anywhere]">
                      {t('courses.fromResume', { line: course.line })}
                    </summary>
                  </details>
                ) : null}
              </li>
            );
          })}
        </ul>
      )}
      <p role="status" aria-live="polite" className={`mb-3 text-xs ${unmarked > 0 || toCheck > 0 || notice ? 'text-amber-700' : 'sr-only'}`}>
        {notice ?? (
          <>
            {unmarked > 0 ? <span className="block">{t('courses.unmarked', { count: unmarked })}</span> : null}
            {toCheck > 0 ? <span className="block">{t('courses.toCheck', { count: toCheck })}</span> : null}
          </>
        )}
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
