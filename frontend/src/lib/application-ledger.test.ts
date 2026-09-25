import { describe, expect, it } from 'vitest';
import { applicationEventBefore, applicationEventMatches, parseApplicationEvent, snapshotApplicationCursor,
  snapshotApplicationEventInput, validApplicationDestination } from './application-ledger';
const input = () => ({ id: '11111111-1111-4111-8111-111111111111', channel: 'web_form' as const,
  destination: 'https://University.edu/apply?track=abc#form', submittedAt: null,
  notes: ' Exact note\r\nwith lines.  ', resultNote: null, nextStep: 'Follow up next week' });
const row = () => ({ event_id: input().id, device_id: 'owner-a', opportunity_id: 'opp-1', channel: input().channel,
  destination: input().destination, actual_submitted_at: null, notes: input().notes, result_note: null, next_step: input().nextStep,
  confirmed_at: '2026-09-25T12:00:00.123456+00:00', confirmation_source: 'user_reported' });
it('copies the complete exact user declaration without inventing time or materials', () => {
  const value = input(); const snapshot = snapshotApplicationEventInput(value); value.notes = 'changed';
  expect(snapshot.notes).toBe(input().notes); expect(snapshot.submittedAt).toBeNull();
  expect(snapshot.destination).toBe(input().destination); expect(snapshot).not.toHaveProperty('materials');
});
it.each([
  { id: 'wrong' }, { channel: 'auto' }, { notes: '' }, { nextStep: '  ' }, { resultNote: 2 },
  { notes: 'a'.repeat(4001) }, { notes: '\ud800' }, { notes: 'a\0b' }, { submittedAt: '2026-02-30T00:00:00Z' },
  { submittedAt: '2026-09-25' }, { unknown: true }, { destination: 'https://example.edu/\n' },
])('rejects invalid snapshots %#', patch => expect(() => snapshotApplicationEventInput({ ...input(), ...patch })).toThrow());
it('counts Unicode codepoints consistently with PostgreSQL and retains newline notes', () => {
  expect(snapshotApplicationEventInput({ ...input(), notes: '🎓'.repeat(4000) }).notes?.length).toBe(8000);
  expect(() => snapshotApplicationEventInput({ ...input(), notes: '🎓'.repeat(4001) })).toThrow();
});
describe('shared conservative application URL contract', () => {
  it.each(['https://example.edu/apply', 'HTTP://LOCALHOST:0/form', 'https://a-b.example.edu:65535/?a=1#b',
    'https://127.0.0.1/apply', 'https://0x7f.1', 'https://[2001:db8::1]:8443/apply', 'https://[::ffff:192.0.2.1]/a',
    'https://example.edu/学生?ref=a%20b'])('accepts exact URL %s', url => expect(validApplicationDestination('web_form', url)).toBe(true));
  it.each(['javascript:alert(1)', 'ftp://example.edu', 'https://user:pass@example.edu', 'https://user@example.edu',
    'https://example.edu\\evil', 'https://example.edu/with space', 'https://example.edu/\t', 'https://example.edu/\u007f',
    'https://', 'https:///example.edu', 'https://-a.edu', 'https://a-.edu', 'https://a..edu',
    `https://${'x'.repeat(64)}.edu`, 'https://256.1.1.1', 'https://127.1', 'https://127.000.0.1',
    'https://example.edu:65536', 'https://example.edu:', 'https://[bad::ip]/', 'https://[1:2:3]/',
    'https://[::1]@example.edu', 'https://[::1]:65536/', 'https://%65xample.edu'])('rejects URL %s', url => {
    expect(validApplicationDestination('web_form', url)).toBe(false);
  });
});
it('supports one exact safe email address or a human destination label', () => {
  expect(validApplicationDestination('email', 'PI@example.edu')).toBe(true);
  expect(validApplicationDestination('email', 'a@example.edu,b@example.edu')).toBe(false);
  expect(validApplicationDestination('email', 'a@example.edu\n')).toBe(false);
  expect(validApplicationDestination('other', ' In person — department office ')).toBe(true);
  expect(validApplicationDestination('other', 'a'.repeat(2001))).toBe(false);
});
it.each([{ device_id: 'other' }, { opportunity_id: 'other' }, { confirmation_source: 'provider' },
  { actual_submitted_at: '2026-09-26T00:00:00Z' }, { confirmed_at: '2026-02-30T00:00:00Z' }, { notes: undefined },
])('rejects malformed/foreign receipts %#', patch => expect(() => parseApplicationEvent({ ...row(), ...patch }, 'owner-a', 'opp-1')).toThrow());
it('accepts microseconds and compares offset-equivalent submission times without losing snapshot identity', () => {
  const receipt = parseApplicationEvent({ ...row(), actual_submitted_at: '2026-09-25T07:00:00.123456-05:00' }, 'owner-a', 'opp-1');
  expect(applicationEventMatches(receipt, { ...input(), submittedAt: '2026-09-25T12:00:00.123456Z' })).toBe(true);
  expect(applicationEventMatches(receipt, { ...input(), submittedAt: '2026-09-25T12:00:00.123455Z' })).toBe(false);
});
it('keeps repeated submissions distinct by explicit attempt ID', () => {
  expect(applicationEventMatches(input(), { ...input(), id: '22222222-2222-4222-8222-222222222222' })).toBe(false);
});
it('rejects injected cursors and compares microseconds before UUIDs', () => {
  expect(() => snapshotApplicationCursor({ id: input().id, confirmedAt: '2026-09-25T00:00:00Z,device_id.eq.other' })).toThrow();
  expect(applicationEventBefore({ id: input().id, confirmedAt: '2026-09-25T12:00:00.123455Z' }, { id: input().id, confirmedAt: row().confirmed_at })).toBe(true);
});
