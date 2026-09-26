import { describe, expect, it } from 'vitest';
import { EMAIL_CONTACT_DRAFT_MAX_LENGTH, parseEmailContactDraftSnapshot, type EmailContactDraftSnapshot } from './email-contact-draft';

function draft(): EmailContactDraftSnapshot {
  return { version: 1, opportunityId: 'target-a', paperSourceKey: '["target-a","v1",[]]',
    fields: { purpose: 'follow_up', referrerName: '', referralNote: '', previousMessage: 'Original email',
      sentOn: 'not yet a date', replyStatus: 'received', replyText: '', availability: '', paperKey: '', readingLevel: '' },
    confirmed: { referral: false, sent: true, availability: false, paper: false }, pending: true, expanded: true };
}

describe('email contact draft snapshot storage contract', () => {
  it('round-trips incomplete, over-application-limit and invalid original text without applying, trimming or truncating it', () => {
    const input = draft();
    input.fields.referralNote = '  研究😀'.repeat(600) + '\nEND\u0000\uD800  ';
    const parsed = parseEmailContactDraftSnapshot(JSON.parse(JSON.stringify(input)));
    expect(parsed).toEqual(input);
    expect(parsed?.fields.sentOn).toBe('not yet a date');
    expect(parsed?.fields.replyText).toBe('');
    expect(parsed?.pending).toBe(true);
    expect(parsed).not.toBe(input);
    expect(parsed?.fields).not.toBe(input.fields);
    expect(parsed?.confirmed).not.toBe(input.confirmed);
    parsed!.fields.previousMessage = 'Changed copy';
    parsed!.confirmed.sent = false;
    expect(input.fields.previousMessage).toBe('Original email');
    expect(input.confirmed.sent).toBe(true);
  });

  it.each(['declined', 'do_not_contact'] as const)('preserves the UI-only blocked status %s without normalizing it into an applied context', replyStatus => {
    const input = draft(); input.fields.replyStatus = replyStatus;
    expect(parseEmailContactDraftSnapshot(input)).toEqual(input);
  });

  it('accepts the exact serialized storage bound and refuses one extra character instead of truncating', () => {
    const input = draft();
    input.fields.referralNote = 'x'.repeat(EMAIL_CONTACT_DRAFT_MAX_LENGTH - JSON.stringify(input).length);
    expect(JSON.stringify(input)).toHaveLength(EMAIL_CONTACT_DRAFT_MAX_LENGTH);
    expect(parseEmailContactDraftSnapshot(input)).toEqual(input);
    input.fields.referralNote += '界';
    expect(parseEmailContactDraftSnapshot(input)).toBeNull();
    expect(input.fields.referralNote.endsWith('界')).toBe(true);
  });

  it.each([
    null, [], {}, { ...draft(), version: 2 }, { ...draft(), sent: true },
    { ...draft(), pending: 'false' }, { ...draft(), opportunityId: 5 },
    { ...draft(), fields: { ...draft().fields, generatedEmail: 'not panel input' } },
    { ...draft(), fields: { ...draft().fields, purpose: 'send' } },
    { ...draft(), fields: { ...draft().fields, replyStatus: 'sent' } },
    { ...draft(), fields: { ...draft().fields, readingLevel: 'understood' } },
    { ...draft(), fields: { ...draft().fields, sentOn: 2026 } },
    { ...draft(), confirmed: { ...draft().confirmed, paper: 'yes' } },
    { ...draft(), confirmed: { ...draft().confirmed, verifiedRecipient: true } },
    Object.assign(Object.create({ owner: 'other' }), draft()),
    { ...draft(), [Symbol('hidden')]: true },
  ])('rejects a malformed or extended snapshot %#', input => {
    expect(parseEmailContactDraftSnapshot(input)).toBeNull();
  });
});
