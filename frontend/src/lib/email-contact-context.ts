import type { EmailContactContext, EmailContactContextReceipt } from './types';

export const EMAIL_CONTACT_CONTEXT_LIMITS = {
  referrerName: 120, referralNote: 1500, previousMessage: 4000,
  replyText: 2000, availability: 500, total: 9000,
} as const;

// Mirrors the backend bounded claim exclusion; this is not semantic fact verification.
const CONTACT_WORK_CLAIM = new RegExp("\\b(?:i|we)(?:['’]ve|\\s+have|\\s+am|\\s+are)?\\s+(?:(?:was|were|personally|previously|already|independently|successfully)\\s+){0,3}(?:won|earned|led|managed|built|developed|trained|published|achieved|improved|awarded|an?\\s+expert|proficient|experienced|expert|experience|expertise)\\b|\\b(?:my|our)\\s+(?:achievements?|awards?|publications?|expertise)\\b|(?:我|我们)(?:曾经|已经|曾|已|独立)?(?:获得|获奖|带领|领导|训练|发表|开发|精通)", 'i');

// Mirrors email_claims.unsupported_action_claims for directly rendered fields.
// These bounded English checks do not prove arbitrary prose is factually true.
const CONTACT_CLAUSES = new RegExp("[!?;\\n]+|\\.(?=\\s|$)|\\b(?:but|however|whereas)\\b|\\b(?:and|which|that|while)(?=\\s+(?:i\\b|my\\b|your\\b|you\\b|we\\b|our\\b|hope\\b|want\\b|plan\\b|would\\b|can\\b))", 'i');
const CONTACT_ATTACHMENT = new RegExp("\\b(?:i(?:\\s+have|['’]ve)?\\s+(?:already\\s+)?(?:attached|enclosed)|i(?:\\s+am|['’]m)\\s+(?:also\\s+)?(?:attaching|enclosing))\\s+(?:(?:my|the|an?|updated)\\s+){0,2}(?:r[eé]sum[eé]|cv|curriculum\\s+vitae|transcript|portfolio|cover\\s+letter|documents?|files?)\\b|\\b(?:please\\s+)?(?:find|see)\\s+(?:(?:my|the)\\s+)?(?:attached|enclosed)\\s+(?:(?:my|the)\\s+)?(?:r[eé]sum[eé]|cv|curriculum\\s+vitae|transcript|portfolio|cover\\s+letter|documents?|files?)\\b|\\b(?:attached|enclosed)\\s+(?:is|are)\\s+(?:(?:my|the)\\s+)?(?:r[eé]sum[eé]|cv|curriculum\\s+vitae|transcript|portfolio|cover\\s+letter|documents?|files?)\\b|\\b(?:my\\s+)?(?:r[eé]sum[eé]|cv|curriculum\\s+vitae|transcript|portfolio|cover\\s+letter|documents?|files?)\\s+(?:(?:is|are|has\\s+been|have\\s+been)\\s+)?(?:attached|enclosed)\\b|\\bi(?:\\s+have|['’]ve)?\\s+included\\s+(?:(?:my|the)\\s+)?(?:r[eé]sum[eé]|cv|curriculum\\s+vitae|transcript|portfolio|cover\\s+letter|documents?|files?)\\s+(?:as\\s+an?\\s+attachment|with\\s+this\\s+email)\\b|\\b(?:my\\s+)?(?:r[eé]sum[eé]|cv|curriculum\\s+vitae|transcript|portfolio|cover\\s+letter|documents?|files?)\\s+(?:is|are|has\\s+been|have\\s+been)\\s+included\\s+with\\s+this\\s+email\\b", 'i');
const CONTACT_READING = new RegExp("\\b(?:i(?:\\s+have|['’]ve)?\\s+(?:(?:carefully|thoroughly|closely|recently|already)\\s+)?(?:(?:finished|completed)\\s+reading|read|reviewed|studied)|(?:after|having)\\s+(?:(?:carefully|thoroughly|closely)\\s+)?(?:read|reading|reviewed|reviewing|studied|studying))\\s+(?:through\\s+)?(?:(?:all\\s+of|the\\s+full\\s+text\\s+of)\\s+)?(?:(?:your|the|this|a)\\s+)?(?:(?:recent|latest|full|entire|published)\\s+){0,2}(?:papers?|articles?|publications?|manuscripts?|stud(?:y|ies)|work|research)\\b", 'i');

function containsUnsupportedActionClaim(value: string): boolean {
  for (const clause of value.split(CONTACT_CLAUSES)) {
    const attachment = CONTACT_ATTACHMENT.exec(clause);
    if (attachment && !/\b(?:no|not|without)\s+(?:(?:a|any|my|the)\s+)?$/i.test(clause.slice(0, attachment.index))) return true;
    const reading = CONTACT_READING.exec(clause);
    if (!reading) continue;
    const prefix = clause.slice(0, reading.index);
    if (/\b(?:if|when|once|unless)\s*$/i.test(prefix)) continue;
    if (/\bi\s+(?:will|would|can|could|plan\s+to|hope\s+to)\b/i.test(prefix)) continue;
    if (/^after\b/i.test(reading[0]) && /\bi\s+(?:will|plan\s+to)\b/i.test(clause.slice(reading.index + reading[0].length))) continue;
    return true;
  }
  return false;
}

type ContextErrorCode = 'INVALID_CONTACT_CONTEXT' | 'CONTACT_CONTEXT_TOO_LARGE'
  | 'CONTACT_CONTEXT_SIGNATURE_UNAVAILABLE' | 'INVALID_CONTACT_CONTEXT_RECEIPT';
export class EmailContactContextError extends Error {
  constructor(public readonly code: ContextErrorCode, public readonly field?: string) {
    super(code === 'INVALID_CONTACT_CONTEXT_RECEIPT'
      ? 'The draft does not match the confirmed email context. Your draft is kept.'
      : code === 'CONTACT_CONTEXT_SIGNATURE_UNAVAILABLE'
        ? 'The email context could not be checked. Please try again.'
        : 'Check the email context and confirm the required information.');
    this.name = 'EmailContactContextError';
  }
}
function invalid(field: string): never { throw new EmailContactContextError('INVALID_CONTACT_CONTEXT', field); }
function record(value: unknown, field: string): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return invalid(field);
  return value as Record<string, unknown>;
}
function keys(value: Record<string, unknown>, allowed: readonly string[], field: string) {
  if (Reflect.ownKeys(value).some(key => typeof key !== 'string' || !allowed.includes(key))) invalid(field);
}
function text(value: unknown, limit: number, field: string, singleLine = false): string {
  if (typeof value !== 'string') return invalid(field);
  // Reject invalid UTF-16 before TextEncoder can silently replace it with U+FFFD.
  for (const ch of value) {
    const point = ch.codePointAt(0)!;
    if (point === 0 || (point >= 0xd800 && point <= 0xdfff)) return invalid(field);
  }
  if (singleLine && /[\r\n\u2028\u2029]/u.test(value)) return invalid(field);
  const normalized = value.trim();
  if (!normalized || [...normalized].length > limit) return invalid(field);
  return normalized;
}
function confirmed(value: unknown, field: string): true {
  if (value !== true) return invalid(field);
  return true;
}
function canonical(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonical).join(',')}]`;
  if (value && typeof value === 'object') {
    const item = value as Record<string, unknown>;
    return `{${Object.keys(item).sort().map(key => `${JSON.stringify(key)}:${canonical(item[key])}`).join(',')}}`;
  }
  return JSON.stringify(value);
}
export function defaultEmailContactContext(): EmailContactContext { return { version: 1, purpose: 'first_contact' }; }

/** Normalize only outer whitespace; never infer facts, truncate text or import Tracker data.
 * Optional null means omitted. The returned object shares no nested references with input. */
export function normalizeEmailContactContext(value?: unknown): EmailContactContext {
  if (value == null) return defaultEmailContactContext();
  const item = record(value, 'context');
  keys(item, ['version', 'purpose', 'referral', 'follow_up', 'availability'], 'context');
  if (item.version !== 1 || !['first_contact', 'referral', 'follow_up'].includes(item.purpose as string)) return invalid('context');
  const result: EmailContactContext = { version: 1, purpose: item.purpose as EmailContactContext['purpose'] };
  if (item.purpose === 'referral') {
    const referral = record(item.referral, 'referral');
    keys(referral, ['referrer_name', 'referral_note', 'confirmed'], 'referral');
    result.referral = {
      referrer_name: text(referral.referrer_name, EMAIL_CONTACT_CONTEXT_LIMITS.referrerName, 'referral.referrer_name', true),
      referral_note: text(referral.referral_note, EMAIL_CONTACT_CONTEXT_LIMITS.referralNote, 'referral.referral_note'),
      confirmed: confirmed(referral.confirmed, 'referral.confirmed'),
    };
    if (CONTACT_WORK_CLAIM.test(result.referral.referrer_name) || containsUnsupportedActionClaim(result.referral.referrer_name)) return invalid('referral.referrer_name');
  } else if (item.referral != null) return invalid('referral');
  if (item.purpose === 'follow_up') {
    const followUp = record(item.follow_up, 'follow_up');
    keys(followUp, ['sent_confirmed', 'previous_message', 'sent_on', 'reply_status', 'reply_text'], 'follow_up');
    if (!['unknown', 'no_reply', 'received'].includes(followUp.reply_status as string)) return invalid('follow_up.reply_status');
    result.follow_up = {
      sent_confirmed: confirmed(followUp.sent_confirmed, 'follow_up.sent_confirmed'),
      previous_message: text(followUp.previous_message, EMAIL_CONTACT_CONTEXT_LIMITS.previousMessage, 'follow_up.previous_message'),
      reply_status: followUp.reply_status as NonNullable<EmailContactContext['follow_up']>['reply_status'],
    };
    if (followUp.sent_on != null) {
      const date = text(followUp.sent_on, 10, 'follow_up.sent_on');
      if (!/^\d{4}-\d{2}-\d{2}$/.test(date) || date.startsWith('0000')
        || !Number.isFinite(Date.parse(`${date}T00:00:00Z`))
        || new Date(`${date}T00:00:00Z`).toISOString().slice(0, 10) !== date) return invalid('follow_up.sent_on');
      result.follow_up.sent_on = date;
    }
    if (followUp.reply_status === 'received') result.follow_up.reply_text = text(followUp.reply_text, EMAIL_CONTACT_CONTEXT_LIMITS.replyText, 'follow_up.reply_text');
    else if (followUp.reply_text != null) return invalid('follow_up.reply_text');
  } else if (item.follow_up != null) return invalid('follow_up');
  if (item.availability != null) {
    const availability = record(item.availability, 'availability');
    keys(availability, ['text', 'confirmed'], 'availability');
    result.availability = { text: text(availability.text, EMAIL_CONTACT_CONTEXT_LIMITS.availability, 'availability.text'), confirmed: confirmed(availability.confirmed, 'availability.confirmed') };
    if (CONTACT_WORK_CLAIM.test(result.availability.text) || containsUnsupportedActionClaim(result.availability.text)) return invalid('availability.text');
  }
  if ([...canonical(result)].length > EMAIL_CONTACT_CONTEXT_LIMITS.total) throw new EmailContactContextError('CONTACT_CONTEXT_TOO_LARGE');
  return result;
}

export function serializeEmailContactContext(value?: unknown): string { return canonical(normalizeEmailContactContext(value)); }

/** Snapshot synchronously, then hash exact canonical UTF-8. No weak-hash fallback. */
export async function emailContactContextSignature(value?: unknown): Promise<string> {
  const serialized = serializeEmailContactContext(value);
  try {
    const digest = await globalThis.crypto.subtle.digest('SHA-256', new TextEncoder().encode(serialized));
    return Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, '0')).join('');
  } catch { throw new EmailContactContextError('CONTACT_CONTEXT_SIGNATURE_UNAVAILABLE'); }
}

/** Validate before applying/caching any draft or any template variant. */
export function requireEmailContactContextReceipt(payload: unknown, expected: Pick<EmailContactContextReceipt, 'purpose' | 'context_sig'>): EmailContactContextReceipt {
  const receipt = payload && typeof payload === 'object' && !Array.isArray(payload)
    ? (payload as Record<string, unknown>).contact_context_receipt : null;
  if (!receipt || typeof receipt !== 'object' || Array.isArray(receipt)) throw new EmailContactContextError('INVALID_CONTACT_CONTEXT_RECEIPT');
  const item = receipt as Record<string, unknown>;
  if (!['first_contact', 'referral', 'follow_up'].includes(expected.purpose)
    || Object.keys(item).length !== 3 || item.version !== 1 || item.purpose !== expected.purpose
    || typeof item.context_sig !== 'string' || !/^[0-9a-f]{64}$/.test(item.context_sig)
    || !/^[0-9a-f]{64}$/.test(expected.context_sig) || item.context_sig !== expected.context_sig) {
    throw new EmailContactContextError('INVALID_CONTACT_CONTEXT_RECEIPT');
  }
  return { version: 1, purpose: expected.purpose, context_sig: item.context_sig };
}
