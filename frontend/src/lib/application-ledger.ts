import { contactRecord, contactTimestamp, validContactTarget } from './contact-ledger';

/** A user's declaration that one application was submitted, not a provider receipt. */
export interface ApplicationEventInput {
  id: string;
  channel: 'web_form' | 'email' | 'other';
  destination: string;
  submittedAt: string | null;
  notes: string | null;
  resultNote: string | null;
  nextStep: string | null;
}
export type ApplicationDraftInput = Omit<ApplicationEventInput, 'id'>;
export interface ApplicationEvent extends ApplicationEventInput {
  deviceId: string;
  opportunityId: string;
  confirmedAt: string;
  confirmationSource: 'user_reported';
}
export interface ApplicationEventCursor { confirmedAt: string; id: string }
export interface ApplicationEventsPage {
  events: ApplicationEvent[];
  nextCursor: ApplicationEventCursor | null;
  hasMore: boolean;
}
export class ApplicationEventError extends Error {
  constructor(readonly code: 'invalid_input' | 'unavailable' | 'invalid_receipt' | 'conflict') {
    super(code === 'conflict' ? 'This application identifier belongs to a different submission.'
      : code === 'invalid_input' ? 'The application record is invalid.' : 'Could not confirm whether this application was saved.');
    this.name = 'ApplicationEventError';
  }
}
export class ApplicationHistoryLoadError extends Error {
  constructor() { super('Application history could not be loaded.'); this.name = 'ApplicationHistoryLoadError'; }
}
export const APPLICATION_EVENT_UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
function exactKeys(value: Record<string, unknown>, keys: string[]): boolean {
  return Object.keys(value).length === keys.length && keys.every(key => Object.hasOwn(value, key));
}
function validText(value: unknown, max: number, singleLine = false): value is string {
  // PostgreSQL text cannot contain NUL or isolated UTF-16 surrogates. Count
  // Unicode code points, matching char_length rather than JS UTF-16 units.
  return typeof value === 'string' && !!value.trim() && !/[\u0000\ud800-\udfff]/u.test(value)
    && Array.from(value).length <= max && !(singleLine && /[\u0000-\u001f\u007f]/.test(value));
}
/** Conservative shared client/SQL URL grammar. Validate but never normalize the snapshot. */
export function validApplicationDestination(channel: ApplicationEventInput['channel'], value: unknown): value is string {
  if (!validText(value, channel === 'email' ? 320 : 2000, true)) return false;
  if (channel === 'email') return /^[^\s@,;<>"\\]+@[^\s@,;<>"\\]+\.[^\s@,;<>"\\]+$/.test(value);
  if (channel === 'other') return true;
  if (channel !== 'web_form' || /[\s\\]/.test(value)) return false;
  const match = /^https?:\/\/([^/?#]+)(?:[/?#].*)?$/i.exec(value);
  if (!match || match[1].includes('@')) return false;
  const authority = match[1];
  if (authority.startsWith('[')) {
    const ipv6 = /^\[[0-9a-fA-F:.]+\](?::([0-9]{1,5}))?$/.exec(authority);
    if (!ipv6 || (ipv6[1] !== undefined && Number(ipv6[1]) > 65535)) return false;
    try { return new URL(value).hostname.startsWith('['); } catch { return false; }
  }
  const hostPort = /^([^:]+)(?::([0-9]{1,5}))?$/.exec(authority);
  if (!hostPort || (hostPort[2] !== undefined && Number(hostPort[2]) > 65535)) return false;
  const host = hostPort[1];
  if (host.length > 253 || !host.split('.').every(label => /^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/i.test(label))) return false;
  return !/^[0-9.]+$/.test(host) || (host.split('.').length === 4 && host.split('.').every(part => /^(0|[1-9][0-9]{0,2})$/.test(part) && Number(part) <= 255));
}
export function snapshotApplicationEventInput(value: unknown): ApplicationEventInput {
  if (!contactRecord(value) || !exactKeys(value, ['id', 'channel', 'destination', 'submittedAt', 'notes', 'resultNote', 'nextStep'])
    || typeof value.id !== 'string' || !APPLICATION_EVENT_UUID.test(value.id)
    || !['web_form', 'email', 'other'].includes(value.channel as string)
    || !validApplicationDestination(value.channel as ApplicationEventInput['channel'], value.destination)
    || (value.submittedAt !== null && contactTimestamp(value.submittedAt) === null)
    || ['notes', 'resultNote', 'nextStep'].some(key => value[key] !== null && !validText(value[key], 4000))) {
    throw new ApplicationEventError('invalid_input');
  }
  return { id: value.id, channel: value.channel as ApplicationEventInput['channel'], destination: value.destination,
    submittedAt: value.submittedAt as string | null, notes: value.notes as string | null,
    resultNote: value.resultNote as string | null, nextStep: value.nextStep as string | null };
}
export function parseApplicationEvent(value: unknown, owner: string, opportunityId: string): ApplicationEvent {
  if (!validContactTarget(owner) || !validContactTarget(opportunityId) || !contactRecord(value)
    || !exactKeys(value, ['event_id', 'device_id', 'opportunity_id', 'channel', 'destination', 'actual_submitted_at', 'notes', 'result_note', 'next_step', 'confirmed_at', 'confirmation_source'])
    || value.device_id !== owner || value.opportunity_id !== opportunityId || value.confirmation_source !== 'user_reported'
    || contactTimestamp(value.confirmed_at) === null) throw new ApplicationEventError('invalid_receipt');
  let input: ApplicationEventInput;
  try { input = snapshotApplicationEventInput({ id: value.event_id, channel: value.channel, destination: value.destination,
    submittedAt: value.actual_submitted_at, notes: value.notes, resultNote: value.result_note, nextStep: value.next_step }); }
  catch { throw new ApplicationEventError('invalid_receipt'); }
  if (input.submittedAt !== null && contactTimestamp(input.submittedAt)! > contactTimestamp(value.confirmed_at)!) throw new ApplicationEventError('invalid_receipt');
  return { ...input, deviceId: owner, opportunityId, confirmedAt: value.confirmed_at as string, confirmationSource: 'user_reported' };
}
export function applicationEventMatches(event: ApplicationEventInput, input: ApplicationEventInput): boolean {
  return event.id === input.id && event.channel === input.channel && event.destination === input.destination
    && event.notes === input.notes && event.resultNote === input.resultNote && event.nextStep === input.nextStep
    && (event.submittedAt === null ? input.submittedAt === null : input.submittedAt !== null
      && contactTimestamp(event.submittedAt) === contactTimestamp(input.submittedAt));
}
export function snapshotApplicationCursor(value: unknown): ApplicationEventCursor {
  if (!contactRecord(value) || !exactKeys(value, ['confirmedAt', 'id']) || typeof value.id !== 'string' || !APPLICATION_EVENT_UUID.test(value.id)
    || contactTimestamp(value.confirmedAt) === null) throw new ApplicationHistoryLoadError();
  return { id: value.id, confirmedAt: value.confirmedAt as string };
}
export function applicationEventBefore(left: ApplicationEventCursor, right: ApplicationEventCursor): boolean {
  const a = contactTimestamp(left.confirmedAt)!; const b = contactTimestamp(right.confirmedAt)!;
  return a < b || (a === b && left.id < right.id);
}
