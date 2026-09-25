import { afterEach, describe, expect, it, vi } from 'vitest';
import { createProfileReadTrace } from './profile-read-diagnostics';

afterEach(() => { vi.unstubAllGlobals(); });
describe('profile read phase diagnostics', () => {
  it('keeps a bounded local history of fixed phase names without a payload', () => {
    const marks: { name: string; startTime: number }[] = [];
    vi.stubGlobal('performance', {
      mark(name: string) { marks.push({ name, startTime: marks.length }); },
      getEntriesByType() { return marks; },
      clearMarks(name: string) { const i = marks.findIndex(mark => mark.name === name); if (i >= 0) marks.splice(i, 1); },
    });
    for (let i = 0; i < 90; i += 1) {
      const trace = createProfileReadTrace('home'); trace('started'); trace('session-wait'); trace('failed');
    }
    expect(marks).toHaveLength(64);
    expect(marks.every(mark => /^ofe-profile-read:home:\d+:(started|session-wait|failed)$/.test(mark.name))).toBe(true);
    expect(marks.at(-1)?.name).toMatch(/:failed$/);
  });
  it('cannot fail a read when the browser timing API is unavailable or throws', () => {
    vi.stubGlobal('performance', { mark: () => { throw new Error('unsupported'); } });
    expect(() => createProfileReadTrace('home')('started')).not.toThrow();
    vi.stubGlobal('performance', {});
    expect(() => createProfileReadTrace('home')('failed')).not.toThrow();
  });
});
