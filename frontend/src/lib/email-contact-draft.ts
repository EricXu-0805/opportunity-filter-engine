import type { EmailContactContext } from './types';
import type { EmailPaperReading } from './email-paper-reading';

/** A draft may be incomplete or invalid for application. Keep its text verbatim. */
export interface EmailContactDraftFields {
  purpose: EmailContactContext['purpose'];
  referrerName: string;
  referralNote: string;
  previousMessage: string;
  sentOn: string;
  replyStatus: 'unknown' | 'no_reply' | 'received' | 'declined' | 'do_not_contact';
  replyText: string;
  availability: string;
  paperKey: string;
  readingLevel: EmailPaperReading['level'] | '';
}

export interface EmailContactDraftConfirmations {
  referral: boolean;
  /** A statement about a previous email, never permission to send a new email. */
  sent: boolean;
  availability: boolean;
  paper: boolean;
}

export interface EmailContactDraftSnapshot {
  version: 1;
  opportunityId: string | null;
  paperSourceKey: string;
  fields: EmailContactDraftFields;
  confirmed: EmailContactDraftConfirmations;
  /** Pending answers must not replace the separately applied contact context. */
  pending: boolean;
  expanded: boolean;
}

/** Maximum serialized JSON length in UTF-16 code units. Reject, never truncate. */
export const EMAIL_CONTACT_DRAFT_MAX_LENGTH = 65_536;

const fieldKeys = ['purpose', 'referrerName', 'referralNote', 'previousMessage', 'sentOn', 'replyStatus', 'replyText', 'availability', 'paperKey', 'readingLevel'] as const;
const confirmationKeys = ['referral', 'sent', 'availability', 'paper'] as const;
const snapshotKeys = ['version', 'opportunityId', 'paperSourceKey', 'fields', 'confirmed', 'pending', 'expanded'] as const;

function exactObject(value: unknown, keys: readonly string[]): value is Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false;
  const prototype = Object.getPrototypeOf(value);
  if (prototype !== Object.prototype && prototype !== null) return false;
  return Reflect.ownKeys(value).length === keys.length && keys.every(key => Object.hasOwn(value, key));
}

/** Validate storage shape only, not whether its answers are ready to apply.
 * Return an independent copy so callers cannot mutate the panel's live input. */
export function parseEmailContactDraftSnapshot(value: unknown): EmailContactDraftSnapshot | null {
  try {
    if (!exactObject(value, snapshotKeys) || value.version !== 1
      || (value.opportunityId !== null && typeof value.opportunityId !== 'string')
      || typeof value.paperSourceKey !== 'string' || typeof value.pending !== 'boolean'
      || typeof value.expanded !== 'boolean' || !exactObject(value.fields, fieldKeys)
      || !exactObject(value.confirmed, confirmationKeys)) return null;
    const fields = value.fields;
    const confirmed = value.confirmed;
    if (!fieldKeys.every(key => typeof fields[key] === 'string' && fields[key].length <= EMAIL_CONTACT_DRAFT_MAX_LENGTH)
      || !['first_contact', 'referral', 'follow_up'].includes(fields.purpose as string)
      || !['unknown', 'no_reply', 'received', 'declined', 'do_not_contact'].includes(fields.replyStatus as string)
      || !['', 'title_only', 'abstract', 'full_text'].includes(fields.readingLevel as string)
      || !confirmationKeys.every(key => typeof confirmed[key] === 'boolean')) return null;
    const result: EmailContactDraftSnapshot = {
      version: 1,
      opportunityId: value.opportunityId as string | null,
      paperSourceKey: value.paperSourceKey,
      fields: Object.fromEntries(fieldKeys.map(key => [key, fields[key]])) as unknown as EmailContactDraftFields,
      confirmed: Object.fromEntries(confirmationKeys.map(key => [key, confirmed[key]])) as unknown as EmailContactDraftConfirmations,
      pending: value.pending,
      expanded: value.expanded,
    };
    return JSON.stringify(result).length <= EMAIL_CONTACT_DRAFT_MAX_LENGTH ? result : null;
  } catch {
    return null;
  }
}
