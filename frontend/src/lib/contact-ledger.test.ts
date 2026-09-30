import { createHash, webcrypto } from 'node:crypto';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { contactEventBefore, contactMaterialVersion, contactTimestamp, createContactEventInput, parseContactEvent,
  snapshotContactEventInput, snapshotContactCursor } from './contact-ledger';
const draft = () => ({ recipient: 'prof@example.edu', subject: ' Research request ', body: 'Dear professor,\r\n\nMy exact draft.  ',
  materialRefs: [{ kind: 'profile' as const, version: 'profile-v1' }], actualSentAt: null });
const input = () => ({ ...draft(), id: 'd501e1bf-3e60-89f2-9a09-18e9402a91c0' });
const row = () => ({ event_id: input().id, device_id: 'owner-a', opportunity_id: 'opp-1', recipient: draft().recipient,
  subject: draft().subject, body: draft().body, materials: draft().materialRefs, actual_sent_at: null,
  confirmed_at: '2026-09-25T12:00:00.123456+00:00', confirmation_source: 'user_reported' });
afterEach(() => vi.unstubAllGlobals());
describe('immutable contact snapshot validation', () => {
  it('preserves whitespace/line endings and copies material references', () => {
    const value = input(); const saved = snapshotContactEventInput(value);
    expect(saved).toEqual(value); value.materialRefs[0].version = 'mutated';
    expect(saved.materialRefs[0].version).toBe('profile-v1');
    expect(saved.body).toBe('Dear professor,\r\n\nMy exact draft.  ');
  });
  it.each([
    { id: 'not-a-uuid' }, { recipient: 'a@example.edu,b@example.edu' }, { recipient: 'a@example.edu\nb@example.edu' },
    { subject: 'header\ninjection' }, { subject: 'header\tinjection' }, { subject: 'header\u007finjection' }, { subject: 'header\u0085injection' }, { subject: 'header\u2029injection' }, { recipient: 'a@example.edu\u0085' }, { subject: '' }, { body: '   ' }, { body: '\ud800' },
    { actualSentAt: '2026-02-30T12:00:00Z' }, { actualSentAt: '2026-01-01' },
    { materialRefs: [{ kind: 'attachment', version: 'uploaded' }] },
    { materialRefs: [{ kind: 'profile', version: '' }] },
    { materialRefs: [{ kind: 'profile', version: 'v1', attached: true }] },
    { materialRefs: [{ kind: 'profile', version: 'v1' }, { kind: 'profile', version: 'v1' }] },
    { materialRefs: Array.from({ length: 33 }, (_, n) => ({ kind: 'profile', version: String(n) })) },
    { extra: 'unexpected data' },
  ])('rejects invalid content rather than silently modifying it: %#', patch => {
    expect(() => snapshotContactEventInput({ ...input(), ...patch })).toThrow();
  });
  it('counts unicode code points and allows full multiline body', () => {
    expect(snapshotContactEventInput({ ...input(), body: '🎓'.repeat(100000) }).body.length).toBe(200000);
    expect(() => snapshotContactEventInput({ ...input(), body: '🎓'.repeat(100001) })).toThrow();
  });
  it('accepts context versions without claiming an attachment', () => {
    expect(snapshotContactEventInput({ ...input(), materialRefs: [{ kind: 'contact_context', version: 'a'.repeat(64) }] }).materialRefs).toEqual([{ kind: 'contact_context', version: 'a'.repeat(64) }]);
  });
  it.each(['2026-02-29T00:00:00Z', '2026-13-01T00:00:00Z', '2026-09-25T24:00:00Z', '2026-09-25T00:00:00+14:01', '2026-09-25T00:00:60Z', '2026-09-25T00:00:00.1234567Z'])('rejects invalid timestamps %s', value => expect(contactTimestamp(value)).toBeNull());
  it('keeps microseconds and equivalent offsets for comparisons', () => {
    const a = { id: input().id, confirmedAt: '2026-09-25T12:00:00.123455Z' };
    const b = { ...a, confirmedAt: '2026-09-25T07:00:00.123456-05:00' };
    expect(contactEventBefore(a, b)).toBe(true);
    expect(contactTimestamp('2024-02-29T00:00:00Z')).not.toBeNull();
    expect(contactTimestamp(b.confirmedAt)).toBe(contactTimestamp('2026-09-25T12:00:00.123456Z'));
  });
  it('cursor validation excludes PostgREST filter injection', () => {
    expect(() => snapshotContactCursor({ id: input().id, confirmedAt: '2026-09-25T00:00:00Z,device_id.eq.other' })).toThrow();
    expect(() => snapshotContactCursor({ id: `${input().id},device_id.eq.other`, confirmedAt: row().confirmed_at })).toThrow();
  });
  it.each([
    { device_id: 'other' }, { opportunity_id: 'wrong' }, { confirmed_at: '2026-02-30T00:00:00Z' },
    { confirmation_source: 'delivered' }, { actual_sent_at: '2026-09-26T00:00:00Z' }, { body: undefined },
  ])('rejects malformed or unrelated receipts %#', patch => expect(() => parseContactEvent({ ...row(), ...patch }, 'owner-a', 'opp-1')).toThrow());
});
describe('stable version-8 contact IDs', () => {
  it('uses the documented SHA256 versioned identity and is stable across calls', async () => {
    vi.stubGlobal('crypto', webcrypto);
    const a = await createContactEventInput('owner-a', 'opp-1', draft());
    const hash = createHash('sha256').update(JSON.stringify(['ofe-contact-event-v1', 'opp-1', draft().recipient, draft().subject, draft().body, null])).digest();
    hash[6] = (hash[6] & 15) | 128; hash[8] = (hash[8] & 63) | 128;
    const h = hash.subarray(0, 16).toString('hex');
    expect(a.id).toBe(`${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`);
    expect(a).toEqual(await createContactEventInput('owner-a', 'opp-1', draft()));
    expect(a.id).toMatch(/^[0-9a-f-]{14}8/);
  });
  it('binds target and exact content but excludes changed provenance', async () => {
    vi.stubGlobal('crypto', webcrypto);
    const original = await createContactEventInput('owner-a', 'opp-1', draft());
    for (const args of [ ['owner-a', 'opp-2', draft()],
      ['owner-a', 'opp-1', { ...draft(), subject: draft().subject.trim() }],
      ['owner-a', 'opp-1', { ...draft(), body: `${draft().body}\n` }],
      ['owner-a', 'opp-1', { ...draft(), recipient: 'other@example.edu' }],
      ['owner-a', 'opp-1', { ...draft(), actualSentAt: '2026-09-25T10:00:00Z' }],
    ] as const) expect((await createContactEventInput(args[0], args[1], args[2])).id).not.toBe(original.id);
    expect((await createContactEventInput('owner-a', 'opp-1', { ...draft(), materialRefs: [{ kind: 'profile', version: 'v2' }] })).id).toBe(original.id);
  });
  it('keeps an exact retry ID after ownership transfer while still validating the caller owner', async () => {
    vi.stubGlobal('crypto', webcrypto);
    const beforeMerge = await createContactEventInput('anonymous-owner', 'opp-1', draft());
    const afterMerge = await createContactEventInput('account-owner', 'opp-1', draft());
    expect(afterMerge.id).toBe(beforeMerge.id);
    expect(afterMerge).toEqual(beforeMerge);
    await expect(createContactEventInput('', 'opp-1', draft())).rejects.toMatchObject({ code: 'invalid_input' });
  });
  it('treats equivalent actual send instants as one event', async () => {
    vi.stubGlobal('crypto', webcrypto);
    const a = await createContactEventInput('owner-a', 'opp-1', { ...draft(), actualSentAt: '2026-09-25T10:00:00.123456Z' });
    const b = await createContactEventInput('owner-a', 'opp-1', { ...draft(), actualSentAt: '2026-09-25T05:00:00.123456-05:00' });
    expect(a.id).toBe(b.id);
  });
  it('copies before a digest await, not after the caller mutates its content', async () => {
    vi.stubGlobal('crypto', webcrypto);
    const value = draft(); const saving = createContactEventInput('owner-a', 'opp-1', value);
    value.body = 'changed'; value.materialRefs[0].version = 'changed';
    expect(await saving).toMatchObject({ body: draft().body, materialRefs: draft().materialRefs });
  });
  it('does not fall back to random IDs if hashing is unavailable', async () => {
    vi.stubGlobal('crypto', {});
    await expect(createContactEventInput('owner-a', 'opp-1', draft())).rejects.toMatchObject({ code: 'unavailable' });
  });
});

describe('complete material SHA256 versions', () => {
  it('hashes a complete profile beyond the 60000-character resume-only cap without truncating it', async () => {
    vi.stubGlobal('crypto', webcrypto);
    const fullProfile = JSON.stringify({ resume_text: 'x'.repeat(60000), experiences: [{ description: 'project'.repeat(5000) }] });
    expect(fullProfile.length).toBeGreaterThan(60000);
    expect(await contactMaterialVersion(fullProfile)).toBe(createHash('sha256').update(fullProfile).digest('hex'));
    expect(await contactMaterialVersion(fullProfile)).not.toBe(await contactMaterialVersion(fullProfile.slice(0, 60000)));
  });
  it('hashes exact JSON serialization, whitespace and Unicode without normalization', async () => {
    vi.stubGlobal('crypto', webcrypto);
    const a = '{"name":"学生 🎓","skills":["Python"]}';
    const b = '{"skills":["Python"],"name":"学生 🎓"}';
    expect(await contactMaterialVersion(a)).toBe(createHash('sha256').update(a).digest('hex'));
    expect(await contactMaterialVersion(a)).not.toBe(await contactMaterialVersion(b));
    expect(await contactMaterialVersion(a)).not.toBe(await contactMaterialVersion(`${a} `));
    expect(await contactMaterialVersion(JSON.stringify({ note: '\0' }))).toBe(createHash('sha256').update(JSON.stringify({ note: '\0' })).digest('hex'));
  });
  it.each([null, undefined, 1, {}, '\ud800', '\udc00', 'text\0'])('rejects invalid hash input %#', async value => {
    vi.stubGlobal('crypto', webcrypto);
    await expect(contactMaterialVersion(value as string)).rejects.toMatchObject({ code: 'invalid_input' });
  });
  it('has no weak or truncated fallback when SHA256 is unavailable', async () => {
    vi.stubGlobal('crypto', {});
    await expect(contactMaterialVersion('{}')).rejects.toMatchObject({ code: 'unavailable' });
  });
});
