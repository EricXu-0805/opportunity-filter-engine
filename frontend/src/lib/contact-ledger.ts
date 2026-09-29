/** Immutable snapshots of user-reported contact. These are not provider delivery receipts. */
export interface ContactMaterialRef {
  kind: 'profile' | 'target' | 'contact_context' | 'resume';
  version: string;
}
export interface ContactEventInput {
  id: string;
  recipient: string;
  subject: string;
  body: string;
  materialRefs: ContactMaterialRef[];
  actualSentAt: string | null;
}
export interface ContactEvent extends ContactEventInput {
  deviceId: string;
  opportunityId: string;
  confirmedAt: string;
  confirmationSource: 'user_reported';
}
export interface ContactEventsCursor { confirmedAt: string; id: string }
export type ContactEventCursor = ContactEventsCursor;
export interface ContactEventsPage {
  events: ContactEvent[];
  nextCursor: ContactEventsCursor | null;
  hasMore: boolean;
}
export type ContactEventFailure = 'invalid_input' | 'unavailable' | 'invalid_receipt' | 'conflict';
export class ContactEventError extends Error {
  constructor(readonly code: ContactEventFailure) {
    super(code === 'conflict' ? 'This contact identifier already belongs to a different snapshot.'
      : code === 'invalid_input' ? 'The contact snapshot is invalid.'
        : 'Could not confirm whether this contact was saved.');
    this.name = 'ContactEventError';
  }
}
export class ContactHistoryLoadError extends Error {
  constructor() { super('Contact history could not be loaded.'); this.name = 'ContactHistoryLoadError'; }
}
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const MATERIAL_KINDS = new Set(['profile', 'target', 'contact_context', 'resume']);
export function contactRecord(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === 'object' && !Array.isArray(value);
}
function exactKeys(value: Record<string, unknown>, keys: string[]): boolean {
  return Object.keys(value).length === keys.length && keys.every(key => Object.hasOwn(value, key));
}
function wellFormedText(value: unknown): value is string {
  if (typeof value !== 'string' || value.includes('\0')) return false;
  for (let i = 0; i < value.length; i += 1) {
    const unit = value.charCodeAt(i);
    if (unit >= 0xd800 && unit <= 0xdbff) {
      const low = value.charCodeAt(++i);
      if (!(low >= 0xdc00 && low <= 0xdfff)) return false;
    } else if (unit >= 0xdc00 && unit <= 0xdfff) return false;
  }
  return true;
}
function validText(value: unknown, max: number, singleLine = false): value is string {
  return wellFormedText(value) && !!value.trim() && Array.from(value).length <= max
    && !(singleLine && /[\u0000-\u001f\u007f]/.test(value));
}
/** SHA-256 of the full exact serialized material. A complete profile includes
 * more than its resume, so this has no resume-text size cap or truncation. */
export async function contactMaterialVersion(value: string): Promise<string> {
  if (!wellFormedText(value)) throw new ContactEventError('invalid_input');
  try {
    const bytes = new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(value)));
    return Array.from(bytes, byte => byte.toString(16).padStart(2, '0')).join('');
  } catch { throw new ContactEventError('unavailable'); }
}
/** A single bare address, shared by composition and immutable contact history. */
export function validContactRecipient(value: unknown): value is string {
  return validText(value, 320, true) && /^[^\s@,;<>"\\]+@[^\s@,;<>"\\]+\.[^\s@,;<>"\\]+$/.test(value);
}
export function validContactTarget(value: unknown): value is string { return validText(value, 200); }
/** Keep PostgreSQL's microseconds: rounding them can skip a pagination boundary. */
export function contactTimestamp(value: unknown): bigint | null {
  if (typeof value !== 'string') return null;
  const m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,6}))?(Z|([+-])(\d{2}):(\d{2}))$/.exec(value);
  if (!m) return null;
  const [year, month, day, hour, minute, second] = m.slice(1, 7).map(Number);
  const days = new Date(Date.UTC(year, month, 0)).getUTCDate();
  if (year < 1000 || month < 1 || month > 12 || day < 1 || day > days || hour > 23 || minute > 59 || second > 59
    || (m[8] !== 'Z' && (Number(m[10]) > 14 || Number(m[11]) > 59 || (Number(m[10]) === 14 && Number(m[11]) !== 0)))) return null;
  const millis = Date.parse(`${m[1]}-${m[2]}-${m[3]}T${m[4]}:${m[5]}:${m[6]}${m[8]}`);
  return Number.isFinite(millis) ? BigInt(millis) * BigInt(1000) + BigInt((m[7] ?? '').padEnd(6, '0')) : null;
}
function materials(value: unknown): ContactMaterialRef[] {
  if (!Array.isArray(value) || value.length > 32) throw new ContactEventError('invalid_input');
  const result = value.map(item => {
    if (!contactRecord(item) || !exactKeys(item, ['kind', 'version']) || !MATERIAL_KINDS.has(item.kind as string)
      || !validText(item.version, 200)) throw new ContactEventError('invalid_input');
    return { kind: item.kind as ContactMaterialRef['kind'], version: item.version };
  });
  if (new Set(result.map(item => JSON.stringify([item.kind, item.version]))).size !== result.length
    || new TextEncoder().encode(JSON.stringify(result)).byteLength > 32768) throw new ContactEventError('invalid_input');
  return result;
}
/** Copy before any await/queued write, preserving exact content and line endings. */
export function snapshotContactEventInput(value: unknown): ContactEventInput {
  if (!contactRecord(value) || !exactKeys(value, ['id', 'recipient', 'subject', 'body', 'materialRefs', 'actualSentAt'])
    || typeof value.id !== 'string' || !UUID.test(value.id)
    || !validContactRecipient(value.recipient)
    || !validText(value.subject, 1000, true) || !validText(value.body, 100000)
    || (value.actualSentAt !== null && contactTimestamp(value.actualSentAt) === null)) throw new ContactEventError('invalid_input');
  return { id: value.id, recipient: value.recipient, subject: value.subject, body: value.body,
    materialRefs: materials(value.materialRefs), actualSentAt: value.actualSentAt as string | null };
}
/** Same target/exact email/declared send time gives the same UUID across
 * refreshes, devices and an ownership transfer. The database owner/event
 * primary key and owner checks provide isolation; the owner is validated here
 * but excluded from the digest so a transferred event remains retryable.
 * Two accounts may have the same ID in separate private rows. Merging those
 * rows must report a collision, never guess which confirmation to preserve.
 * Provenance is deliberately excluded so a changed
 * source conflicts with an uncertain earlier save instead of adding a row.
 * A genuine repeat of identical content needs a distinct declared send time.
 * This is a version-8 UUID from the first 128 bits of a SHA-256 digest. */
export async function createContactEventInput(ownerId: string, opportunityId: string,
  value: Omit<ContactEventInput, 'id'>): Promise<ContactEventInput> {
  if (!validContactTarget(ownerId) || !validContactTarget(opportunityId)) throw new ContactEventError('invalid_input');
  const snapshot = snapshotContactEventInput({ ...value, id: '00000000-0000-0000-0000-000000000000' });
  const identity = JSON.stringify(['ofe-contact-event-v1', opportunityId, snapshot.recipient,
    snapshot.subject, snapshot.body, snapshot.actualSentAt === null ? null : contactTimestamp(snapshot.actualSentAt)!.toString()]);
  try {
    const hash = new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(identity)));
    hash[6] = (hash[6] & 0x0f) | 0x80;
    hash[8] = (hash[8] & 0x3f) | 0x80;
    const hex = Array.from(hash.slice(0, 16), byte => byte.toString(16).padStart(2, '0')).join('');
    return { ...snapshot, id: `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}` };
  } catch { throw new ContactEventError('unavailable'); }
}
export function parseContactEvent(value: unknown, owner: string, opportunityId: string): ContactEvent {
  if (!contactRecord(value) || !exactKeys(value, ['event_id', 'device_id', 'opportunity_id', 'recipient', 'subject', 'body', 'materials', 'actual_sent_at', 'confirmed_at', 'confirmation_source'])
    || value.device_id !== owner || value.opportunity_id !== opportunityId || value.confirmation_source !== 'user_reported'
    || contactTimestamp(value.confirmed_at) === null) throw new ContactEventError('invalid_receipt');
  let input: ContactEventInput;
  try { input = snapshotContactEventInput({ id: value.event_id, recipient: value.recipient, subject: value.subject,
    body: value.body, materialRefs: value.materials, actualSentAt: value.actual_sent_at }); }
  catch { throw new ContactEventError('invalid_receipt'); }
  if (input.actualSentAt !== null && contactTimestamp(input.actualSentAt)! > contactTimestamp(value.confirmed_at)!) throw new ContactEventError('invalid_receipt');
  return { ...input, deviceId: owner, opportunityId, confirmedAt: value.confirmed_at as string, confirmationSource: 'user_reported' };
}
export function contactEventMatches(event: ContactEvent, input: ContactEventInput): boolean {
  return event.id === input.id && event.recipient === input.recipient && event.subject === input.subject && event.body === input.body
    && JSON.stringify(event.materialRefs) === JSON.stringify(input.materialRefs)
    && (event.actualSentAt === null ? input.actualSentAt === null : input.actualSentAt !== null
      && contactTimestamp(event.actualSentAt) === contactTimestamp(input.actualSentAt));
}
export function snapshotContactCursor(value: unknown): ContactEventsCursor {
  if (!contactRecord(value) || !exactKeys(value, ['confirmedAt', 'id']) || typeof value.id !== 'string' || !UUID.test(value.id)
    || contactTimestamp(value.confirmedAt) === null) throw new ContactHistoryLoadError();
  return { id: value.id, confirmedAt: value.confirmedAt as string };
}
export function contactEventBefore(left: ContactEventsCursor, right: ContactEventsCursor): boolean {
  const a = contactTimestamp(left.confirmedAt)!; const b = contactTimestamp(right.confirmedAt)!;
  return a < b || (a === b && left.id < right.id);
}
