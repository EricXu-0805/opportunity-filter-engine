import type { StoredCourse } from './types';

/** Whether a stored `courses` value has the shape a course list has. */
export function isCourseList(value: unknown): value is StoredCourse[] {
  return Array.isArray(value) && value.every((item) => !!item && typeof item === 'object' && !Array.isArray(item)
    && typeof (item as StoredCourse).name === 'string'
    && ['status', 'source'].every((key) => {
      const field = (item as unknown as Record<string, unknown>)[key];
      return field === undefined || typeof field === 'string';
    }));
}
