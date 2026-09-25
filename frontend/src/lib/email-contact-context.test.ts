import { createHash, webcrypto } from 'node:crypto';
import golden from '../../../tests/fixtures/email-contact-context-v1.json';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { defaultEmailContactContext, emailContactContextSignature, normalizeEmailContactContext, requireEmailContactContextReceipt, serializeEmailContactContext } from './email-contact-context';
const followUp = () => ({ version: 1, purpose: 'follow_up', follow_up: { sent_confirmed: true, previous_message: 'I reviewed the parser.\r\n\n你好 🧪', sent_on: '2024-02-29', reply_status: 'received', reply_text: 'Please describe your own contribution.' }, availability: { text: '5 hours/week', confirmed: true } });
const referral = () => ({ version: 1, purpose: 'referral', referral: { referrer_name: '陈老师', referral_note: 'Suggested I contact the lab.', confirmed: true } });
beforeEach(() => { vi.stubGlobal('crypto', webcrypto); });
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });

describe('confirmed email context', () => {
  it('defaults only absent/null context and returns independent objects', () => {
    expect(normalizeEmailContactContext()).toEqual({ version: 1, purpose: 'first_contact' });
    expect(normalizeEmailContactContext(null)).toEqual(defaultEmailContactContext());
    const a = defaultEmailContactContext(); a.purpose = 'referral';
    expect(defaultEmailContactContext().purpose).toBe('first_contact');
  });
  it('normalizes outer whitespace without modifying internal prose or the caller', () => {
    const input = followUp(); input.follow_up.previous_message = '  I reviewed the parser.\r\n\n你好 🧪\t';
    const actual = normalizeEmailContactContext(input);
    expect(actual.follow_up?.previous_message).toBe('I reviewed the parser.\r\n\n你好 🧪');
    expect(input.follow_up.previous_message).toMatch(/^  /);
    input.follow_up.reply_text = 'Later mutation';
    expect(actual.follow_up?.reply_text).toBe('Please describe your own contribution.');
  });
  it.each(['I won a Nobel Prize', 'Dr Lee. I led a team of 12', '李老师。我获得诺贝尔奖', '我们已经训练模型'])('does not let a name or availability establish a work claim: %s', claim => {
    expect(() => normalizeEmailContactContext({ ...referral(), referral: { ...referral().referral, referrer_name: claim } })).toThrow();
    expect(() => normalizeEmailContactContext({ version: 1, purpose: 'first_contact', availability: { text: claim, confirmed: true } })).toThrow();
    // The actual message may contain past claims, but is never competence evidence.
    const input = followUp(); input.follow_up.previous_message = claim;
    expect(normalizeEmailContactContext(input).follow_up?.previous_message).toBe(claim);
    expect(normalizeEmailContactContext({ ...referral(), referral: { ...referral().referral, referral_note: claim } }).referral?.referral_note).toBe(claim);
  });
  it.each([
    'Dr Lee. I have attached my resume',
    'I have read your paper',
    'I included my CV as an attachment',
    'I can send my resume, but I have attached my transcript',
    'I will read your paper, but I have already reviewed your research',
  ])('rejects unsupported rendered attachment/reading claims: %s', claim => {
    expect(() => normalizeEmailContactContext({ ...referral(), referral: { ...referral().referral, referrer_name: claim } })).toThrow(expect.objectContaining({ code: 'INVALID_CONTACT_CONTEXT', field: 'referral.referrer_name' }));
    expect(() => normalizeEmailContactContext({ version: 1, purpose: 'first_contact', availability: { text: claim, confirmed: true } })).toThrow(expect.objectContaining({ code: 'INVALID_CONTACT_CONTEXT', field: 'availability.text' }));
    const input = followUp(); input.follow_up.previous_message = claim; input.follow_up.reply_text = claim;
    expect(normalizeEmailContactContext(input).follow_up).toMatchObject({ previous_message: claim, reply_text: claim });
    expect(normalizeEmailContactContext({ ...referral(), referral: { ...referral().referral, referral_note: claim } }).referral?.referral_note).toBe(claim);
  });
  it.each([
    'I can send my resume on request',
    'I will read your paper before we meet',
    'If I read your paper, I can discuss it next week',
    'I will write after reading your paper',
    'After reading your paper, I will write next week',
    'No attached resume is required for our meeting',
  ])('preserves future/conditional/non-claim availability: %s', value => {
    expect(normalizeEmailContactContext({ version: 1, purpose: 'first_contact', availability: { text: value, confirmed: true } }).availability?.text).toBe(value);
  });
  it.each(["Dr. O'Neil", '王老师'])('keeps normal referral names %s and real availability', referrer_name => {
    expect(normalizeEmailContactContext({ ...referral(), referral: { ...referral().referral, referrer_name }, availability: { text: 'I am available 5 hours/week. 周二下午有空。', confirmed: true } }).referral?.referrer_name).toBe(referrer_name);
  });
  it('uses ECMAScript whitespace boundaries, without stripping Python-only whitespace', () => {
    const input = referral(); input.referral.referral_note = '\ufeffNote\ufeff';
    expect(normalizeEmailContactContext(input).referral?.referral_note).toBe('Note');
    input.referral.referral_note = '\u0085Note\u001c';
    expect(normalizeEmailContactContext(input).referral?.referral_note).toBe('\u0085Note\u001c');
  });
  it('omits optional nulls recursively but preserves explicit unknown reply status', () => {
    expect(normalizeEmailContactContext({ version: 1, purpose: 'follow_up', referral: null, availability: null, follow_up: { sent_confirmed: true, previous_message: 'Earlier note', sent_on: null, reply_status: 'unknown', reply_text: null } })).toEqual({ version: 1, purpose: 'follow_up', follow_up: { sent_confirmed: true, previous_message: 'Earlier note', reply_status: 'unknown' } });
  });
  it.each([undefined, null, false, 1, 'true'])('requires explicit true referral confirmation (%j)', confirmed => {
    expect(() => normalizeEmailContactContext({ ...referral(), referral: { ...referral().referral, confirmed } })).toThrow();
  });
  it.each([undefined, null, false, 1])('requires explicit sent confirmation (%j)', sent_confirmed => {
    const input = followUp(); expect(() => normalizeEmailContactContext({ ...input, follow_up: { ...input.follow_up, sent_confirmed } })).toThrow();
  });
  it.each([{}, [], '', 1, { version: '1', purpose: 'first_contact' }, { version: 1, purpose: 'unknown' }, { version: 1, purpose: ['first_contact'] }, { version: 1, purpose: 'first_contact', extra: undefined }, { version: 1, purpose: 'first_contact', referral: referral().referral }, { version: 1, purpose: 'referral' }, { version: 1, purpose: 'first_contact', follow_up: followUp().follow_up }])('rejects malformed/contradictory shape %#', value => {
    expect(() => normalizeEmailContactContext(value)).toThrow();
  });
  it('rejects unknown nested fields and unconfirmed availability', () => {
    expect(() => normalizeEmailContactContext({ ...referral(), referral: { ...referral().referral, private_note: 'not requested' } })).toThrow();
    expect(() => normalizeEmailContactContext({ version: 1, purpose: 'first_contact', availability: { text: '5 hours', confirmed: false } })).toThrow();
  });
  it.each(['\n', '\r', '\u2028', '\u2029'])('rejects referrer newline %j even on the outside', newline => {
    expect(() => normalizeEmailContactContext({ ...referral(), referral: { ...referral().referral, referrer_name: `${newline}Name` } })).toThrow();
  });
  it.each(['\u0000', '\ud800', '\udc00'])('rejects invalid Unicode without replacement %j', bad => {
    expect(() => normalizeEmailContactContext({ ...referral(), referral: { ...referral().referral, referral_note: `Note${bad}` } })).toThrow();
  });
  it.each(['2026-02-30', '2025-02-29', '2026-13-01', '0000-01-01', '26-01-01', '2026-1-01', '2026-01-01T00:00:00Z'])('rejects invalid sent date %s', sent_on => {
    const input = followUp(); expect(() => normalizeEmailContactContext({ ...input, follow_up: { ...input.follow_up, sent_on } })).toThrow();
  });
  it.each(['unknown', 'no_reply'])('does not manufacture a received reply from status %s', reply_status => {
    const input = followUp(); expect(() => normalizeEmailContactContext({ ...input, follow_up: { ...input.follow_up, reply_status } })).toThrow();
  });
  it.each([null, undefined, '', '  '])('received requires nonblank reply text %j', reply_text => {
    const input = followUp(); expect(() => normalizeEmailContactContext({ ...input, follow_up: { ...input.follow_up, reply_text } })).toThrow();
  });
  it('counts Unicode codepoints without silently truncating a maximum message', () => {
    const input = followUp(); input.follow_up.previous_message = '🧪'.repeat(4000);
    expect(normalizeEmailContactContext(input).follow_up?.previous_message).toBe(input.follow_up.previous_message);
    input.follow_up.previous_message += 'x'; expect(() => normalizeEmailContactContext(input)).toThrow();
  });
  it.each([['referrer_name', 120], ['referral_note', 1500]] as const)('enforces %s whole-text capacity', (field, max) => {
    const input = referral(); input.referral[field] = '中'.repeat(max);
    expect(normalizeEmailContactContext(input).referral?.[field]).toBe(input.referral[field]);
    input.referral[field] += 'x'; expect(() => normalizeEmailContactContext(input)).toThrow();
  });
  it('checks total canonical JSON size including escapes instead of only prose lengths', () => {
    const input = followUp(); input.follow_up.previous_message = '\u0001'.repeat(2000);
    expect(() => normalizeEmailContactContext(input)).toThrow(expect.objectContaining({ code: 'CONTACT_CONTEXT_TOO_LARGE' }));
    expect(input.follow_up.previous_message).toHaveLength(2000);
  });
  it('enforces reply and availability capacity rather than truncating', () => {
    const input = followUp(); input.follow_up.reply_text = 'r'.repeat(2000); input.availability.text = '中'.repeat(500);
    expect(normalizeEmailContactContext(input).availability?.text).toBe(input.availability.text);
    input.follow_up.reply_text += 'x'; expect(() => normalizeEmailContactContext(input)).toThrow();
    input.follow_up.reply_text = 'reply'; input.availability.text += 'x'; expect(() => normalizeEmailContactContext(input)).toThrow();
  });
});

describe('canonical receipt', () => {
  // These values were independently produced by the real Python schema + receipt helper.
  it('matches backend SHA-256 vectors for all three purposes', async () => {
    expect(await emailContactContextSignature()).toBe('a1d6520d73d08cfd865ed3c6647c6b85f09ba8d99b59b4d990cff308e87dd15f');
    expect(await emailContactContextSignature(referral())).toBe('266fab4f101a805f681845850fe8ecc36fdd919f969d9289e122051d5737ec7e');
    expect(await emailContactContextSignature(followUp())).toBe('8c4bb381022549c954a027f765d642f48a55651cb42b8dada3781a30e2d8c1c8');
  });
  it('hashes recursive sorted compact Unicode JSON and keeps internal CR/LF', async () => {
    const input = followUp(); const canonical = '{"availability":{"confirmed":true,"text":"5 hours/week"},"follow_up":{"previous_message":"I reviewed the parser.\\r\\n\\n你好 🧪","reply_status":"received","reply_text":"Please describe your own contribution.","sent_confirmed":true,"sent_on":"2024-02-29"},"purpose":"follow_up","version":1}';
    expect(serializeEmailContactContext(input)).toBe(canonical);
    const digest = createHash('sha256').update(canonical, 'utf8').digest('hex');
    expect(await emailContactContextSignature(input)).toBe(digest);
    expect(await emailContactContextSignature({ purpose: input.purpose, follow_up: { reply_text: input.follow_up.reply_text, reply_status: 'received', sent_on: '2024-02-29', previous_message: input.follow_up.previous_message, sent_confirmed: true }, availability: { confirmed: true, text: '5 hours/week' }, version: 1 })).toBe(digest);
  });
  it('snapshots before an asynchronous digest and has no insecure crypto fallback', async () => {
    const input = followUp(); const expected = createHash('sha256').update(serializeEmailContactContext(input)).digest('hex');
    const promise = emailContactContextSignature(input); input.follow_up.previous_message = 'Changed afterwards';
    expect(await promise).toBe(expected);
    vi.stubGlobal('crypto', {}); await expect(emailContactContextSignature(input)).rejects.toMatchObject({ code: 'CONTACT_CONTEXT_SIGNATURE_UNAVAILABLE' });
  });
  it('requires exact purpose/signature for the top-level or an individual variant', async () => {
    const expected = { purpose: 'follow_up' as const, context_sig: await emailContactContextSignature(followUp()) };
    const receipt = { version: 1, ...expected };
    expect(requireEmailContactContextReceipt({ contact_context_receipt: receipt }, expected)).toEqual(receipt);
    for (const value of [undefined, null, [], {}, { ...receipt, version: '1' }, { ...receipt, purpose: 'referral' }, { ...receipt, context_sig: '0'.repeat(64) }, { ...receipt, context_sig: `${expected.context_sig}\n` }, { ...receipt, extra: 1 }]) expect(() => requireEmailContactContextReceipt({ contact_context_receipt: value }, expected)).toThrow();
    expect(() => requireEmailContactContextReceipt({}, expected)).toThrow();
  });
});

// The backend requires already-normalized wire strings; this UI helper also
// prepares user input by trimming its outer whitespace before it is submitted.
describe('shared backend contact-context fixture', () => {
  it.each(golden.valid)('matches canonical UTF-8 and receipt: $id', async sample => {
    expect(serializeEmailContactContext(sample.wire)).toBe(sample.canonical);
    expect(await emailContactContextSignature(sample.wire)).toBe(sample.context_sig);
  });
  it.each(golden.invalid.filter(sample => sample.id !== 'bom-not-trimmed'))('rejects the same invalid material: $id', sample => {
    expect(() => normalizeEmailContactContext(sample.wire)).toThrow();
  });
  it('normalizes UI boundary whitespace before the backend strict wire validator', () => {
    const sample = golden.invalid.find(sample => sample.id === 'bom-not-trimmed')!;
    const normalized = normalizeEmailContactContext(sample.wire);
    expect(normalized.referral?.referral_note).toBe('My advisor suggested contacting this group.');
    expect(serializeEmailContactContext(normalized)).not.toContain('\ufeff');
  });
});
