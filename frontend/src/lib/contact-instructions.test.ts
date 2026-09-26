import { describe, expect, it } from 'vitest';
import { contactEmailBlock, isContactInstructions, readContactInstructions, requiredContactSubject } from './contact-instructions';

const rule = { kind: 'subject', quote: 'Use the subject "Undergraduate research inquiry".', source_url: 'https://example.edu/join', checked_at: '2026-09-25T10:00:00Z', subject: 'Undergraduate research inquiry' };
const policy = { version: 1, status: 'known', email_policy: 'unknown', rules: [rule] };

describe('source contact requirements', () => {
  it('keeps unknown distinct from permission and rejects a malformed current contract', () => {
    expect(readContactInstructions({})?.email_policy).toBe('unknown');
    expect(contactEmailBlock({})).toBeNull();
    expect(contactEmailBlock({ contact_instructions: null })).toBe('unavailable');
    expect(isContactInstructions({ ...policy, status: 'unknown' })).toBe(false);
  });
  it.each(['not_accepted', 'form_only', 'conflicting'] as const)('blocks new composition for %s', email_policy => {
    const value = { ...policy, email_policy, status: email_policy === 'conflicting' ? 'conflicting' : 'known' };
    expect(contactEmailBlock({ contact_instructions: value })).toBe(email_policy);
  });
  it('requires the exact declared subject only for the composition check', () => {
    const target = { contact_instructions: policy };
    expect(requiredContactSubject(target)).toBe(rule.subject);
    expect(contactEmailBlock(target)).toBeNull();
    expect(contactEmailBlock(target, rule.subject)).toBeNull();
    expect(contactEmailBlock(target, 'A different subject')).toBe('subject');
  });
  it.each([
    { ...rule, source_url: 'javascript:alert(1)' },
    { ...rule, source_url: 'https://name:secret@example.edu/join' },
    { ...rule, checked_at: 'not-a-date' },
    { ...rule, subject: 'A subject\nBcc: someone' },
    { ...rule, kind: 'no_email' },
  ])('rejects unsafe or inconsistent rule data', bad => {
    expect(isContactInstructions({ ...policy, rules: [bad] })).toBe(false);
  });
  it('does not reuse requirements after a source update or removal', () => {
    expect(requiredContactSubject({ contact_instructions: policy })).toBe(rule.subject);
    expect(requiredContactSubject({ contact_instructions: { version: 1, status: 'unknown', email_policy: 'unknown', rules: [] } })).toBeNull();
  });
});


describe('source subject formats', () => {
  const target = { contact_instructions: { ...policy, rules: [{ ...rule, subject: undefined, subject_template: 'Research inquiry — [Your Last Name]' }] } };
  // Omit the field entirely: a present undefined field is an invalid contract.
  delete target.contact_instructions.rules[0].subject;
  it('keeps format review separate from a required static subject', () => {
    expect(isContactInstructions(target.contact_instructions)).toBe(true);
    expect(requiredContactSubject(target)).toBeNull();
    expect(contactEmailBlock(target)).toBeNull();
    expect(contactEmailBlock(target, 'Research inquiry — Xu')).toBe('subject_format');
    expect(contactEmailBlock(target, 'Research inquiry — Xu', { subjectFormatConfirmed: true })).toBeNull();
  });
  it.each(['', 'Research inquiry — [Your Last Name]', 'Research inquiry — {surname}', 'Research inquiry — <Full Name>'])(
    'does not accept an empty or unfilled subject: %s', subject => {
      expect(contactEmailBlock(target, subject, { subjectFormatConfirmed: true })).toBe('subject_format');
    });
  it('requires review when the source specifies a format that could not be parsed', () => {
    const unparsed = { contact_instructions: { ...policy, rules: [{ kind: rule.kind, quote: 'Include your program and surname in the subject.', source_url: rule.source_url, checked_at: rule.checked_at }] } };
    expect(contactEmailBlock(unparsed, 'Research inquiry')).toBe('subject_format');
    expect(contactEmailBlock(unparsed, 'CS inquiry — Xu', { subjectFormatConfirmed: true })).toBeNull();
  });
});


it('blocks an explicitly incomplete source review without inventing a conflict', () => {
  const contact_instructions = { ...policy, review_required: true, reason: 'too_many_requirements' };
  expect(isContactInstructions(contact_instructions)).toBe(true);
  expect(contactEmailBlock({ contact_instructions })).toBe('too_many_requirements');
  expect(isContactInstructions({ ...policy, review_required: false, reason: 'too_many_requirements' })).toBe(false);
  expect(isContactInstructions({ ...policy, reason: 'too_many_requirements' })).toBe(false);
});
