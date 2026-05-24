import { describe, it, expect } from 'vitest';
import { humanizeTime } from './humanize-time';

const NOW = new Date('2026-05-24T18:00:00.000Z');

function isoMinusMs(ms: number): string {
  return new Date(NOW.getTime() - ms).toISOString();
}

describe('humanizeTime', () => {
  describe('falsy / unparseable input', () => {
    it('returns null for null', () => {
      expect(humanizeTime(null, NOW)).toBeNull();
    });
    it('returns null for undefined', () => {
      expect(humanizeTime(undefined, NOW)).toBeNull();
    });
    it('returns null for empty string', () => {
      expect(humanizeTime('', NOW)).toBeNull();
    });
    it('returns null for unparseable string', () => {
      expect(humanizeTime('not a date', NOW)).toBeNull();
    });
  });

  describe('just-now bucket (<1 min)', () => {
    it('handles exact same instant', () => {
      expect(humanizeTime(NOW.toISOString(), NOW)).toEqual({ kind: 'just-now' });
    });
    it('handles 30 seconds ago', () => {
      expect(humanizeTime(isoMinusMs(30_000), NOW)).toEqual({ kind: 'just-now' });
    });
    it('handles 59 seconds ago', () => {
      expect(humanizeTime(isoMinusMs(59_000), NOW)).toEqual({ kind: 'just-now' });
    });
    it('clamps future timestamps to just-now (clock skew defense)', () => {
      const future = new Date(NOW.getTime() + 3 * 3_600_000).toISOString();
      expect(humanizeTime(future, NOW)).toEqual({ kind: 'just-now' });
    });
  });

  describe('minutes bucket (1m \u2013 59m)', () => {
    it('handles 1 minute exactly', () => {
      expect(humanizeTime(isoMinusMs(60_000), NOW)).toEqual({ kind: 'minutes', n: 1 });
    });
    it('handles 5 minutes', () => {
      expect(humanizeTime(isoMinusMs(5 * 60_000), NOW)).toEqual({ kind: 'minutes', n: 5 });
    });
    it('handles 59 minutes', () => {
      expect(humanizeTime(isoMinusMs(59 * 60_000), NOW)).toEqual({ kind: 'minutes', n: 59 });
    });
  });

  describe('hours bucket (1h \u2013 23h)', () => {
    it('handles 1 hour exactly', () => {
      expect(humanizeTime(isoMinusMs(3_600_000), NOW)).toEqual({ kind: 'hours', n: 1 });
    });
    it('handles 3 hours', () => {
      expect(humanizeTime(isoMinusMs(3 * 3_600_000), NOW)).toEqual({ kind: 'hours', n: 3 });
    });
    it('handles 23 hours', () => {
      expect(humanizeTime(isoMinusMs(23 * 3_600_000), NOW)).toEqual({ kind: 'hours', n: 23 });
    });
  });

  describe('days bucket (1d \u2013 6d)', () => {
    it('handles 1 day exactly', () => {
      expect(humanizeTime(isoMinusMs(86_400_000), NOW)).toEqual({ kind: 'days', n: 1 });
    });
    it('handles 3 days', () => {
      expect(humanizeTime(isoMinusMs(3 * 86_400_000), NOW)).toEqual({ kind: 'days', n: 3 });
    });
    it('handles 6 days', () => {
      expect(humanizeTime(isoMinusMs(6 * 86_400_000), NOW)).toEqual({ kind: 'days', n: 6 });
    });
  });

  describe('date bucket (\u2265 7 days)', () => {
    it('returns date for 7 days ago', () => {
      const seven = isoMinusMs(7 * 86_400_000);
      const result = humanizeTime(seven, NOW);
      expect(result).toEqual({ kind: 'date', iso: seven.slice(0, 10) });
    });
    it('returns date for 30 days ago', () => {
      const thirty = isoMinusMs(30 * 86_400_000);
      expect(humanizeTime(thirty, NOW)).toEqual({ kind: 'date', iso: thirty.slice(0, 10) });
    });
    it('returns date for 365 days ago', () => {
      const year = isoMinusMs(365 * 86_400_000);
      expect(humanizeTime(year, NOW)).toEqual({ kind: 'date', iso: year.slice(0, 10) });
    });
  });

  describe('round-trip with real ISO from the backend', () => {
    it('preserves the YYYY-MM-DD slice for a literal UTC ISO', () => {
      const result = humanizeTime('2026-05-01T12:34:56.789Z', NOW);
      expect(result).toEqual({ kind: 'date', iso: '2026-05-01' });
    });
  });
});
