// The single coordinator for the user's profile row: the ONE place that
// decides what reaches localStorage and what reaches the cloud, and the only
// caller of the CAS RPC.
//
// Why a coordinator instead of "every screen saves the profile it holds":
// every screen holds a SNAPSHOT. The /results cross-school toggle reads a
// localStorage blob that may predate the résumé the user removed on their
// phone; the school gate reads the same blob; the home form holds a whole
// document that was current when it loaded. Under the old blind upsert each
// of those wrote the WHOLE row, so whichever screen saved last silently
// restored everything the others had removed — including the résumé.
//
// The rules this module enforces:
//   1. A save carries ONLY the keys its caller actually changed (a patch),
//      never the document it happens to hold. Migration 027 shallow-merges
//      server-side, so an omitted key cannot be cleared by a stale caller.
//   2. A save carries the revision it was made against. The server applies it
//      only if that is still current; otherwise it reports the conflict and
//      writes nothing.
//   3. "Dirty" is cleared by a CLOUD CONFIRMATION, not by issuing a request.
//      Per-key mutation counters mean an edit made while a save is in flight
//      survives that save's response instead of being marked clean by it.
//   4. There is ONE outbox slot, and a new edit LAYERS onto whatever is
//      already in it — never replaces it. A response only clears the slot if
//      the slot still holds the mutation that response belongs to.
//   5. A genuine conflict LOCKS the keys it involves. Automatic retries skip
//      locked keys entirely; only an explicit user resolution unlocks them.
//      (Without the lock, moving the base to the remote value would make the
//      very next auto-retry see remote == base and overwrite the other
//      device's change — the conflict would silently resolve itself in favour
//      of whoever retried last.)
//
// Storage: the legacy raw STORAGE_KEYS.PROFILE mirror is kept verbatim (every
// other screen reads it through useLocalStorageJSON and must keep working);
// the revision + outbox live BESIDE it under STORAGE_KEYS.PROFILE_SYNC.

import type { ProfileData, SkillWithLevel } from './types';
import {
  appendJournalOp,
  getJournalOriginId,
  effectiveOpBase,
  getJournalLineageId,
  clearJournal,
  appendRebaseReceipt,
  encodeJournalValue,
  type JournalValue,
  readOutstandingOps,
  registerJournalKeyGuard,
  readRebaseReceipts,
  settleJournalOps,
  withProfileLock,
  type JournalField,
  type JournalOp,
  type JournalResult,
} from './profile-journal';
import {
  enqueuePrivateWrite,
  isOwnerScopedLoadError,
  isOwnerTokenValid,
  isTokenOwnerStillCurrent,
  OwnerNotReadyError,
  OwnerScopedLoadError,
  readUserScopedEntry,
  readUserScopedRaw,
  type OwnerToken,
} from './identity-owner';
import { STORAGE_KEYS } from './storage-keys';
import { writeLocalStorageJSON } from './use-local-storage-json';
import { commitProfilePatch, loadProfile, type LoadedProfile } from './supabase';

export type ProfileKey = keyof ProfileData;

/** The keys migration 027 requires an expected_revision=0 create to carry —
 *  a create becomes the whole stored document, so a partial one would make a
 *  mutilated profile canonical. Pinned against DEFAULT_PROFILE in
 *  profile-sync.contract.test.ts so the two cannot drift. */
export const CREATE_REQUIRED_KEYS: readonly ProfileKey[] = [
  'home_school', 'college', 'major', 'grade', 'search_weight',
];

/** Fields that are one unit as far as conflict detection goes. The résumé
 *  text and the coursework extracted FROM it are meaningless apart: keeping
 *  one and taking the other from a different device produces coursework that
 *  no résumé on file supports (the exact state "remove my résumé" exists to
 *  prevent). Staging either always stages both. */
export const RESUME_BUNDLE: readonly ProfileKey[] = ['resume_text', 'coursework'];

/** Every key the app recognises. Declared as a Record<keyof ProfileData, …>
 *  so adding a profile field without listing it here is a COMPILE error — a
 *  runtime "unknown key" filter that silently drops new fields would be worse
 *  than no filter at all. Used to reject a persisted outbox entry naming keys
 *  this build does not know about (a downgrade, a hand-edited value). */
const KNOWN_PROFILE_KEYS: Record<ProfileKey, true> = {
  institution: true, home_school: true, college: true, major: true,
  additional_majors: true, grade: true, is_international: true,
  research_interests: true, skills: true, resume_text: true, coursework: true,
  search_weight: true, exploring: true, include_cross_school: true,
  linkedin_url: true, github_url: true, scholar_url: true, seeking_types: true,
  name: true, experience_level: true, account_type: true,
};

/** EVERY persistable field, from the record TypeScript checks for
 *  exhaustiveness. Callers that need "all of them" must use this rather than
 *  the defaults or whatever the current document happens to carry: an
 *  optional key that appears for the first time mid-operation is absent from
 *  both, and a snapshot missing it treats the first edit as the baseline. */
export const PROFILE_KEYS: readonly ProfileKey[] = Object.freeze(
  Object.keys(KNOWN_PROFILE_KEYS) as ProfileKey[],
);

/** Whether a document carries everything migration 027 requires of a create
 *  (which becomes the whole stored row). */
/**
 * Whether this document can become somebody's canonical row.
 *
 * Presence is not enough. A row whose college, major and grade are blank —
 * or whitespace, which looks filled in and is not — says nothing, and once it
 * exists every later write patches onto it and the create path never runs
 * again. The server refuses the same shape (see migration 027); this is the
 * same answer without the round trip.
 */
function isCompleteDocument(profile: ProfileData): boolean {
  const rec = profile as unknown as Record<string, unknown>;
  if (!CREATE_REQUIRED_KEYS.every((k) => k in rec && rec[k] !== undefined)) return false;
  for (const key of ['college', 'major', 'grade'] as const) {
    const value = rec[key];
    if (typeof value !== 'string' || value.trim() === '') return false;
  }
  const weight = rec.search_weight;
  return typeof weight === 'number' && Number.isFinite(weight) && weight >= 0 && weight <= 100;
}

function isProfileKey(key: string): key is ProfileKey {
  return Object.prototype.hasOwnProperty.call(KNOWN_PROFILE_KEYS, key);
}

/** The journal refuses to interpret a key or bundle it has not been told
 *  about — that is its downgrade guard — so the shape's owner declares them
 *  here, at module load, before any read can happen. */
export const RESUME_BUNDLE_ID = 'resume';
registerJournalKeyGuard(isProfileKey, [RESUME_BUNDLE_ID]);

/** The résumé text and the coursework extracted from it are one unit (see
 *  RESUME_BUNDLE). A persisted outbox entry naming only half of it would send
 *  a patch that clears one and leaves the other — the exact torn state the
 *  bundle exists to prevent — so the missing half is materialised here, from
 *  the base if it has one and from the empty value if not. */
function completeResumeBundle(pending: ProfilePendingWrite): ProfilePendingWrite {
  const present = RESUME_BUNDLE.filter((k) => pending.dirtyKeys.includes(k));
  // Nothing to do only when the bundle is not involved at all. With BOTH
  // halves present the keys are already there, but the LOCKS and versions
  // still have to be normalized: one half locked and the other sendable is
  // exactly the torn write the bundle exists to prevent.
  if (present.length === 0) return pending;
  const desired = { ...pending.desiredProfile } as unknown as Record<string, unknown>;
  const base = pending.baseProfile as unknown as Record<string, unknown>;
  const dirtyKeys = [...pending.dirtyKeys];
  const lockedKeys = [...pending.lockedKeys];
  const keyVersions = { ...pending.keyVersions };
  // If either half is locked, BOTH are: sending the unlocked half alone is
  // exactly the torn state the bundle exists to prevent.
  const anyLocked = RESUME_BUNDLE.some((k) => lockedKeys.includes(k));
  for (const key of RESUME_BUNDLE) {
    if (!dirtyKeys.includes(key)) dirtyKeys.push(key);
    if (!(key in desired)) desired[key] = key in base ? base[key] : (key === 'coursework' ? [] : '');
    if (anyLocked && !lockedKeys.includes(key)) lockedKeys.push(key);
    if (!(key in keyVersions)) {
      // The half being materialised was never staged on its own; give it the
      // partner's version so a confirmation acknowledges them together.
      const partner = RESUME_BUNDLE.find((k) => k !== key);
      keyVersions[key] = (partner && keyVersions[partner]) ?? 0;
    }
  }
  return {
    ...pending,
    dirtyKeys,
    lockedKeys,
    keyVersions,
    desiredProfile: desired as unknown as ProfileData,
  };
}

export interface ProfilePendingWrite {
  mutationId: string;
  /** The revision the values in `desiredProfile` were computed against. */
  baseRevision: number;
  baseProfile: ProfileData;
  /** The full working copy: what the user believes their profile is. */
  desiredProfile: ProfileData;
  dirtyKeys: string[];
  /** The per-key mutation version each value was staged at. Frozen HERE, not
   *  read when the request is finally issued: an edit made in between would
   *  otherwise be treated as part of this write and marked saved by it. */
  keyVersions: Record<string, number>;
  /** The skills this write ADDS, as an operation rather than a whole list.
   *  A résumé/GitHub import adds names; it asserts nothing about the ones it
   *  did not mention. Merging the full desired list against the remote one
   *  would resurrect a skill the other device deleted, and would report a
   *  level the other device changed as a conflict the user never caused.
   *  Empty whenever the skills change was a manual replace. */
  skillAdditions: SkillWithLevel[];
  /** The operations that produced `skillAdditions`, by globally unique id, so
   *  a confirmation consumes exactly what it carried. */
  skillOps: SkillOp[];
  /** Sticky: the user hand-edited the list in this unsent write, so the list
   *  itself is the intent and a later import must not turn a deletion back
   *  into "add everything again". Persisted so a RELOAD cannot quietly
   *  restore additive semantics either. */
  skillsReplaced: boolean;
  additiveKeys: string[];
  /** Keys a previous attempt found in genuine conflict with another device.
   *  Never auto-sent again — see rule 5 above. */
  lockedKeys: string[];
  /** The cloud's value at the moment of that conflict, so the UI can show the
   *  user what they are choosing between. */
  conflictRemote: ProfileData | null;
  /** True for a working copy recovered from a pre-CAS raw mirror, whose base
   *  revision is genuinely UNKNOWN. Such a copy is never auto-uploaded: its
   *  differences from the cloud row cannot be attributed to either side. */
  legacy: boolean;
  /** The journal operations this write is made of. A settle acknowledges
   *  ONLY these — an operation another tab appended after this write was
   *  prepared describes a value the server has not seen. */
  journalOpIds: string[];
  /** Which operations produced each field's value. A same-origin edit chain
   *  collapses to one value, so confirming that value consumes the WHOLE
   *  chain: acknowledging only the last operation would leave the earlier
   *  ones outstanding and re-send them as if they had never landed. */
  journalPlan: Record<string, string[]>;
  /** True when the cloud CONFIRMED there is no row yet and this write is a
   *  partial one (the school gate, the tour) that cannot legally create it.
   *  It is durably staged and sent as part of the first COMPLETE create the
   *  home form makes — distinct from `legacy` (base unknown) and from
   *  local-only (no backend at all): here the backend answered, and the
   *  answer was "nothing to patch yet". */
  deferredCreate: boolean;
}

/** The row this browser knows about is GONE, and that fact has to survive a
 *  reload. Without it, a deleted row looks identical to "a brand new account"
 *  on the next mount, and the home form's create path would resurrect it. */
export interface ProfileTombstone {
  /** 'deleted' — the row was removed; only an explicit user act may recreate
   *  it. 'merged'  — this account was merged into another one; its local copy
   *  must stay quarantined, not served. */
  reason: 'deleted' | 'merged';
  /** False when the raw mirror could NOT be removed yet — the next hydrate or
   *  flush retries it rather than assuming it is gone. */
  rawQuarantined: boolean;
}

export interface ProfileSyncEnvelope {
  v: 1;
  /** The last state the CLOUD confirmed, and the revision it was at. Null
   *  until a load or a save has established one — the coordinator refuses to
   *  patch without it, which is what stops a single-field writer from
   *  creating a mutilated row. */
  confirmed: { revision: number; profile: ProfileData } | null;
  pending: ProfilePendingWrite | null;
  tombstone: ProfileTombstone | null;
}

export type ProfileSaveResult =
  | { status: 'saved'; revision: number; profile: ProfileData }
  | { status: 'already-saved'; revision: number; profile: ProfileData }
  /** Another device's edit collides with this one on `conflictKeys`. Nothing
   *  was written remotely; the working copy is kept and those keys are locked
   *  until the user resolves them. */
  | {
    status: 'conflict';
    revision: number;
    remote: ProfileData | null;
    /** The newest row the server has CONFIRMED, and the revision it is.
     *
     *  A collision does not mean nothing landed: a write whose safe half was
     *  accepted at revision 9 leaves the row at 9 with only the disputed keys
     *  outstanding. A caller that kept its old baseline would then measure
     *  every later edit against a revision that is gone, and the person's own
     *  next keystroke comes back as a conflict with themselves. Null only
     *  where this browser has never confirmed a row at all. */
    confirmed: { revision: number; profile: ProfileData } | null;
    conflictKeys: string[];
    /** The same immutable payload hydrate returns: candidate values, who
     *  wants them, and the exact operations behind each. A caller answers by
     *  handing one of these back — never by naming keys and a side, which
     *  would decide about whatever happens to be outstanding by then. */
    conflicts: ProfileConflict[];
  }
  /** Persisted on this device only — there is no cloud backend right now. */
  | { status: 'local-only' }
  /** Durably staged on this device, deliberately not sent: the cloud has no
   *  row yet and this write is too partial to create one. It goes out with
   *  the first complete profile the home form saves. */
  | { status: 'staged-local' }
  /** A newer edit replaced this one in the outbox before it was sent; the
   *  newer write carries this one's fields and owns the outcome. */
  | { status: 'superseded' }
  /** The row is gone, or this account was merged into another one. NOTHING is
   *  recreated and nothing is discarded: the working copy stays in the outbox
   *  because it is the user's own unsaved edit. */
  | { status: 'missing'; reason: 'absent' | 'merged_away' }
  /** The question this answer was about is no longer the question: the
   *  operations the prompt named are gone (resolved elsewhere, superseded,
   *  acknowledged). NOTHING was written or sent — the caller must show the
   *  current state and ask again rather than apply a decision the person made
   *  about values that are no longer in dispute. */
  | { status: 'stale-conflict' }
  /** Nothing was staged: no confirmed revision to patch against yet. */
  | { status: 'blocked' }
  /** The identity moved on. Not this user's news. */
  | { status: 'abandoned' }
  /** A local write failed (quota, private mode, a storage shim).
   *  phase 'stage'   — nothing was sent; the edit is on screen only.
   *  phase 'confirm' — the CLOUD HAS the edit, but this browser could not
   *                    record that. Retrying must redo the LOCAL write only:
   *                    re-sending the request would be a second save against
   *                    a revision that has already moved. */
  | { status: 'device-failed'; phase: 'stage' | 'confirm' }
  /** The request failed or returned something unusable. Retriable. */
  | { status: 'error'; message: string };

// ---------------------------------------------------------------------------
// Value comparison
// ---------------------------------------------------------------------------

/** Order-insensitive for object keys (the server returns jsonb, whose key
 *  order is its own), order-SENSITIVE for arrays (skills and coursework are
 *  ordered by the user). */
function stableStringify(value: unknown): string {
  if (value === null || typeof value !== 'object') return JSON.stringify(value) ?? 'null';
  if (Array.isArray(value)) return `[${value.map(stableStringify).join(',')}]`;
  const entries = Object.entries(value as Record<string, unknown>)
    .filter(([, v]) => v !== undefined)
    .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0));
  return `{${entries.map(([k, v]) => `${JSON.stringify(k)}:${stableStringify(v)}`).join(',')}}`;
}

function sameValue(a: unknown, b: unknown): boolean {
  return stableStringify(a) === stableStringify(b);
}

function pick(profile: ProfileData, keys: readonly ProfileKey[]): Partial<ProfileData> {
  const out: Record<string, unknown> = {};
  const src = profile as unknown as Record<string, unknown>;
  for (const key of keys) if (key in src) out[key as string] = src[key as string];
  return out as Partial<ProfileData>;
}

function expandBundles(keys: readonly ProfileKey[]): ProfileKey[] {
  const out = new Set<ProfileKey>(keys);
  if (RESUME_BUNDLE.some((k) => out.has(k))) for (const k of RESUME_BUNDLE) out.add(k);
  return [...out];
}

// ---------------------------------------------------------------------------
// The cloud-confirmed dirty ledger
// ---------------------------------------------------------------------------
// Deliberately NOT the home form's hydration dirty set, which answers a
// different question ("did the user type while the row was loading") and is
// cleared the moment the row lands. This one is cleared only when the CLOUD
// says the value it described is stored — and only if no newer edit to that
// same key has happened since the request went out.

// KEY OWNERSHIP MODEL
// -------------------
// Several independent writers touch this one row: the home form, the /results
// cross-school toggle, the school gate. Each owns the keys IT edited and may
// stage only those. The version counter is per KEY and global (a key is a
// single value, whoever last changed it), but "which keys am I responsible
// for re-sending" is per WRITER.
//
// Why it has to be per-writer: the school gate can leave `home_school = mit`
// unsent in the outbox while the home form still shows `uiuc` (it mounted
// before the broadcast, or the broadcast failed). If the home form then staged
// the whole GLOBAL dirty set with its own snapshot, an unrelated grade edit
// would carry `home_school: uiuc` and overwrite the campus the user just
// picked. The outbox unions across writers; no writer re-sends another's key.
interface FieldIntent {
  /** The value this field held when the edit BEGAN, and the revision that
   *  value belonged to. FROZEN at mark time — a stage that happens later may
   *  not re-read the envelope and pretend the edit was made against whatever
   *  is current by then. Two tabs on one account share the envelope: without
   *  this, tab A's "CS -> ECE" would be staged against tab B's already-saved
   *  Physics, and the CAS check would pass because the client had silently
   *  agreed the base was Physics all along. */
  baseValue: unknown;
  baseRevision: number;
  /** Bumped by every edit to this field. A confirmation only clears the
   *  intent if this has not moved since the write was staged. */
  version: number;
  /** Which writers are waiting for this field to be confirmed. */
  writers: Set<string>;
  /** Set when a stage's LOCAL write failed, so there is no outbox entry:
   *  the value has to be re-staged from here or it is lost entirely. */
  unstagedValue?: unknown;
  hasUnstaged: boolean;
  allowCreate: boolean;
}

// KEY OWNERSHIP + INTENT MODEL
// ----------------------------
// Several independent writers touch this one row: the home form, the /results
// cross-school toggle, the school gate. Each owns the keys IT edited and may
// stage only those (a writer that staged the whole global dirty set with its
// own snapshot would carry another writer's key at a stale value).
//
// And each FIELD carries its own frozen base: what it was, and at which
// revision, when the user started changing it. Staging reconstructs the base
// profile from those frozen values rather than from whatever the envelope
// holds now, so a same-field change made anywhere else — another tab, another
// device — surfaces as a real conflict instead of being overwritten.
const fieldIntents = new Map<string, FieldIntent>();
export const HOME_FORM_WRITER = 'home-form';
/** The results page's cross-school toggle. Named so its operations are
 *  attributable — and so the home form's dirty-key query does not claim them. */
export const RESULTS_WRITER = 'results';
/** The onboarding/campus gate. */
export const SCHOOL_WRITER = 'school-gate';
const DEFAULT_WRITER = 'default';
let ledgerScope: string | null = null;

function scopeOf(token: OwnerToken): string {
  return `${token.uid ?? '<null>'}:${token.epoch}`;
}

/** Drops everything staged for a previous identity. The values themselves are
 *  cleared by identity-owner's own sweep; this is the in-memory half. */
function ensureScope(token: OwnerToken): void {
  const scope = scopeOf(token);
  if (ledgerScope === scope) return;
  ledgerScope = scope;
  fieldIntents.clear();
  unwrittenConfirmation = null;
  lastLoadSource = null;
  skillOps = null;
}

function versionOf(key: string): number {
  return fieldIntents.get(key)?.version ?? 0;
}

/**
 * The one way anything outside this module changes a profile.
 *
 * Every writer — the home form, removing a résumé, confirming a campus, the
 * cross-school toggle — goes through here, and the order is the point:
 *
 *   1. the intent is made DURABLE first, before any await, so a crash or a
 *      closed tab between the click and the response still leaves the edit
 *      on disk rather than only in a React ref;
 *   2. the caller is told plainly whether that succeeded;
 *   3. nothing is sent when it did not. A write nobody recorded is a write
 *      nobody can retry, and reporting success for one is how a user is told
 *      their change is saved when it is nowhere at all.
 *
 * `observed` is what the person was LOOKING AT when they acted — the values
 * the edit was made against — not whatever the shared envelope has become
 * since another tab wrote to it.
 */
export interface ProfileActionInput {
  keys: readonly ProfileKey[];
  /**
   * The ONE view the surface displayed. The baseline, the revision, the owner
   * and the identity generation all come from here.
   *
   * There is deliberately no way to pass them separately. A shape with an
   * `observedBefore` beside a `renderedRevision` beside a `token` is a shape
   * where a caller can assemble three values that were never true at the same
   * moment — old values, a fresh revision, a currently-valid token — and that
   * combination is indistinguishable from an honest one by the time it gets
   * here.
   */
  view: ProfileViewSnapshot;
  /** What the action makes it. Built by the caller from
   *  `view.renderedProfile`, so a full-document write cannot truncate fields
   *  the base never had. */
  desiredAfter: ProfileData;
  writer: string;
  mode?: JournalOp['mode'];
  allowCreate?: boolean;
  additive?: readonly ProfileKey[];
}

export interface ProfileActionOutcome {
  /** Whether the intent reached storage. False means nothing was sent. */
  durable: boolean;
  /** Why nothing was recorded. Absent when `durable`. */
  reason?: 'stale-view' | 'record-failed';
  /** The send's own outcome, absent when nothing was sent. */
  result?: ProfileSaveResult;
}

export async function commitProfileAction(
  input: ProfileActionInput,
): Promise<ProfileActionOutcome> {
  const { keys, view, desiredAfter, writer, mode, allowCreate, additive } = input;
  // BEFORE any read of shared state. A view whose owner has moved on must
  // produce zero envelope reads, zero journal reads and zero writes — not
  // "read first, decide later", which is how a superseded view still gets to
  // observe (and be merged against) the current owner's data.
  if (!isOwnerTokenValid(view.token, view.token.uid)) {
    return { durable: false, reason: 'stale-view' };
  }
  const { token } = view;
  if (!recordProfileIntent(desiredAfter, keys, token, {
    writer,
    mode,
    // The EXACT accepted baseline, not the rendered one: a field the row
    // never had must read as absent here, or setting it to the value the UI
    // was already defaulting to looks like a no-op and the intent is dropped.
    observedBase: { profile: (view.baseProfile ?? {}) as ProfileData, revision: view.revision },
  })) {
    return { durable: false, reason: 'record-failed' };
  }
  const result = await stageProfilePatch(desiredAfter, keys, token, {
    allowCreate,
    additive: additive as ProfileKey[] | undefined,
  });
  return { durable: true, result };
}

/**
 * Records an edit DURABLY, synchronously, at the moment it is made — before
 * any debounce. One immutable journal operation per field, each carrying the
 * value and revision that field had when the edit began.
 *
 * This is the authority. The in-memory map below is a cache of it: a crash
 * inside the 1.5s autosave window, a closed tab, or a second tab reading the
 * same account all see the operation because it is on disk, not because this
 * process is still alive to remember it.
 *
 * Returns false when the operation could not be made durable — a caller must
 * treat that as "this edit was not recorded".
 */
export function recordProfileIntent(
  desired: ProfileData,
  keys: readonly ProfileKey[],
  token: OwnerToken,
  opts: {
    writer?: string;
    mode?: JournalOp['mode'];
    /** The baseline the caller's UI actually showed. Overrides the envelope:
     *  a tab that has not seen another tab's save must record what IT saw. */
    observedBase?: { profile: ProfileData; revision: number };
  } = {},
): boolean {
  // BEFORE ensureScope, and before any read. ensureScope RESETS this module's
  // ledger when the scope differs — so a superseded token reaching it wipes
  // the live owner's staged intents, their skill operations and their
  // unwritten confirmation, none of which belong to the caller. And the
  // envelope read below would hand the live owner's document to a caller the
  // authority has already retired. Neither is repairable after the fact.
  if (!isOwnerTokenValid(token, token.uid)) return false;
  ensureScope(token);
  const writer = opts.writer ?? DEFAULT_WRITER;
  const envelope = readProfileSyncEnvelopeStrict();
  // An envelope that cannot be read is not an empty one. Recording an intent
  // against a base of `{}` because the real base was unreadable is how a
  // single-field edit is sent as if every other field had always been absent.
  if (!envelope.ok) return false;
  const confirmed = envelope.value?.confirmed ?? null;
  const base = (opts.observedBase?.profile ?? confirmed?.profile ?? {}) as unknown as Record<string, unknown>;
  const desiredRec = desired as unknown as Record<string, unknown>;
  const effective = expandBundles(keys);
  if (effective.length === 0) return true;
  const inResumeBundle = effective.some((k) => RESUME_BUNDLE.includes(k));

  // ONE operation for the whole action. A college switch clears the major; a
  // résumé removal clears its coursework. Appending those as separate
  // operations lets the first land and the second fail, leaving a journal
  // that describes half an action.
  let baseRevision = opts.observedBase?.revision ?? confirmed?.revision ?? 0;
  // A field whose chain is LOCKED has already been put to the person and
  // refused by the server. A new action touching it is not that chain's
  // continuation — it supersedes it outright (see `supersedes` below) — so
  // freezing this operation to the revision that chain began at aims a brand
  // new intention at a row that is gone, and the collision repeats forever.
  // The disagreement itself stays locked until somebody answers it; only the
  // baseline of the NEW action moves.
  const locked = new Set(readProfileSyncEnvelope()?.pending?.lockedKeys ?? []);
  const fields: JournalField[] = [];
  for (const key of effective) {
    const held = fieldIntents.get(key);
    const continues = held && !locked.has(key);
    if (continues) baseRevision = Math.min(baseRevision, held.baseRevision);
    fields.push({
      key,
      // An edit chain continues from where it STARTED, not from where the row
      // has got to since — so a field already mid-edit keeps its first base.
      base: continues ? { present: true, value: held.baseValue } : encodeJournalValue(base, key),
      desired: encodeJournalValue(desiredRec, key),
    });
  }
  // Everything this edit continues: THIS LINEAGE's own still-outstanding
  // operations for the same fields, named by id.
  //
  // Only this lineage's. A reload gives the document a new origin id, so
  // without an explicit ancestry the user's next keystroke looks exactly like
  // a second tab's independent opinion — and would lock them in a conflict
  // with themselves that no amount of further editing can clear. An operation
  // from any other lineage is never claimed here, not even one this document
  // read and rendered, and not even when it arrived with a copy of this
  // window's session state: that really is a second opinion, and it stays a
  // conflict resolved locally with zero requests. When the lineage cannot be
  // proven (see getJournalLineageId) there is nothing to continue and the
  // edit conflicts — fail closed.
  const outstanding = readOutstandingOps();
  const liveOps = outstanding.ok ? outstanding.value : [];
  const mine = getJournalLineageId();
  const supersedes = liveOps
    .filter((o) => o.lineage === mine && o.fields.some((f) => effective.includes(f.key as ProfileKey)))
    .map((o) => o.opId);
  const op = appendJournalOp({
    fields,
    baseRevision,
    writer,
    mode: opts.mode ?? 'set',
    bundle: inResumeBundle ? RESUME_BUNDLE_ID : undefined,
    ...(supersedes.length > 0 ? { supersedes } : {}),
  }, token);
  if (!op) return false;
  markProfileFieldsDirty(effective, token, writer);
  return true;
}

/** In-memory bookkeeping for the same edit. NOT exported: an edit that only
 *  reaches this map is invisible to every other tab and gone after a reload,
 *  which is the whole failure the journal replaced. recordProfileIntent is
 *  the only way in, and profile-sync.contract.test.ts enforces it. */
function markProfileFieldsDirty(
  keys: readonly ProfileKey[],
  token: OwnerToken,
  writer: string = DEFAULT_WRITER,
): void {
  ensureScope(token);
  const confirmed = readProfileSyncEnvelope()?.confirmed ?? null;
  const base = (confirmed?.profile ?? {}) as unknown as Record<string, unknown>;
  for (const key of expandBundles(keys)) {
    const existing = fieldIntents.get(key);
    if (existing) {
      // An edit chain continues from where it STARTED, not from where the
      // row has got to since.
      existing.version += 1;
      existing.writers.add(writer);
      continue;
    }
    fieldIntents.set(key, {
      baseValue: base[key],
      baseRevision: confirmed?.revision ?? 0,
      version: 1,
      writers: new Set([writer]),
      hasUnstaged: false,
      allowCreate: false,
    });
  }
}

/**
 * The keys THIS writer still has to get confirmed. Never another writer's.
 *
 * Read from the DURABLE journal, with the in-memory map only as a fallback
 * for the window before the guard is registered or when enumeration fails:
 * another tab's unsent edit is not in this process's memory, and a reload
 * has no memory at all.
 */
export function getDirtyProfileKeys(
  token: OwnerToken,
  writer: string = DEFAULT_WRITER,
): JournalResult<ProfileKey[]> {
  // BEFORE ensureScope and before the journal read — same reasoning as
  // recordProfileIntent. A superseded caller must learn nothing about the
  // live owner's outstanding work, and must not reset the ledger holding it.
  if (!isOwnerTokenValid(token, token.uid)) {
    return { ok: false, reason: 'owner superseded' };
  }
  ensureScope(token);
  // The DURABLE journal, and only it. Falling back to this process's cache
  // when the journal cannot be read would mean sending a patch while another
  // tab's (or a corrupt) operation is invisible — the caller must stop
  // instead.
  const journal = readOutstandingOps();
  if (!journal.ok) return journal;
  const out = new Set<ProfileKey>();
  for (const op of journal.value) {
    if (op.writer !== writer) continue;
    for (const field of op.fields) if (isProfileKey(field.key)) out.add(field.key);
  }
  return { ok: true, value: [...out] };
}

/**
 * What the journal says one field should become, and what it was.
 *
 * Two tabs editing the SAME field are not merged by taking whichever
 * operation was read last — that is the silent overwrite this whole design
 * exists to stop. Within ONE origin, consecutive edits are a chain: the
 * latest value, the earliest base, acknowledged together. ACROSS origins,
 * identical values coalesce and skill ADDITIONS merge by name; anything else
 * is a conflict resolved locally, with zero requests, unless one operation
 * explicitly says it supersedes the other.
 */
type KeyPlan =
  | { kind: 'value'; value: unknown; baseValue: unknown; baseRevision: number; opIds: string[] }
  | { kind: 'conflict'; opIds: string[]; candidates: ProfileConflictCandidate[] };

/**
 * The outstanding operations with their bases moved forward through every
 * acknowledgement of an ancestor they explicitly continue.
 *
 * Derived on read, never written back: an append does not take the lock, so
 * an operation can appear between any scan and any decision made from it, and
 * only a lazy derivation is correct for one that was not there to be scanned.
 * Identity is untouched — same ids, same lineage, same ancestry — so every
 * settle and receipt path still names exactly what it named before.
 *
 * Null means the receipts could not be read, and the caller must fail closed:
 * planning a send from a partly-understood set of acknowledgements is how a
 * CAS ends up aimed at a revision that no longer exists.
 */
function rebasedOps(ops: readonly JournalOp[]): JournalOp[] | null {
  const receipts = readRebaseReceipts();
  if (!receipts.ok) return null;
  if (receipts.value.size === 0) return ops as JournalOp[];
  const opsById = new Map(ops.map((op) => [op.opId, op]));
  return ops.map((op) => {
    const effective = effectiveOpBase(op, receipts.value, opsById);
    if (effective.fields === op.fields && effective.baseRevision === op.baseRevision) return op;
    return { ...op, fields: effective.fields, baseRevision: effective.baseRevision };
  });
}

function planKeysFromJournal(
  ops: readonly JournalOp[],
  keys: readonly string[],
): Map<string, KeyPlan> {
  const plans = new Map<string, KeyPlan>();
  // What a person has already ANSWERED. A receipt speaks for every operation
  // it names, in every field it decides — across lineages, which is the whole
  // point of answering a disagreement between two tabs. Honoured here, before
  // any of those operations are cleaned up: the decision is the receipt, and
  // removing what it answers is housekeeping that may fail or come much later.
  const answered = new Map<string, Set<string>>();
  for (const op of ops) {
    if (op.mode !== 'resolve') continue;
    for (const id of op.resolves ?? []) {
      const forKeys = answered.get(id) ?? new Set<string>();
      for (const k of Object.keys(op.decisions ?? {})) forKeys.add(k);
      answered.set(id, forKeys);
    }
  }
  for (const key of keys) {
    // One chain per origin, in that origin's own sequence order.
    const byOrigin = new Map<string, { fields: JournalField[]; ops: JournalOp[] }>();
    for (const op of ops) {
      const field = op.fields.find((f) => f.key === key);
      if (!field) continue;
      if (answered.get(op.opId)?.has(key)) continue; // spoken for by a receipt
      // A PENDING-BOUND answer is not a generic edit. It reaches the row only
      // by matching its exact tuple in applyPendingResolutions; letting its
      // fields into the plan as an ordinary value chain means a stale one —
      // the row moved on and it was correctly refused — competes with the
      // answer to the CURRENT question, and the person can never close it.
      // PER KEY, not per operation. One receipt can legitimately answer key A
      // through the operations it acknowledges (`resolves`) and key B through
      // the pending instance (`resolvesPending.keyVersions`). Only the
      // tuple-bound key is excluded here: skipping the whole receipt would
      // drop A's perfectly good answer along with B's stale one.
      if (op.resolvesPending?.keyVersions[key] !== undefined) continue;
      // A receipt is its OWN chain, never folded into the document that wrote
      // it. Otherwise answering one disagreement would quietly swallow an
      // unrelated edit made in the same tab — later in sequence, never part
      // of the question, and never answered by anyone.
      const chainKey = op.mode === 'resolve' ? `receipt:${op.opId}` : op.originId;
      const chain = byOrigin.get(chainKey) ?? { fields: [], ops: [] };
      chain.fields.push(field);
      chain.ops.push(op);
      byOrigin.set(chainKey, chain);
    }
    if (byOrigin.size === 0) continue;

    const chains = [...byOrigin.values()].map((chain) => {
      const ordered = chain.ops
        .map((op, i) => ({ op, field: chain.fields[i] }))
        .sort((a, b) => a.op.seq - b.op.seq);
      // An operation this chain explicitly REPLACES is gone from it — not
      // merely later in it. "Keep what I typed" records a new intent against
      // what is stored today and says which operation it supersedes; letting
      // the replaced one keep contributing its base would send the answer
      // against the revision the user has already looked at and rejected, and
      // collide all over again.
      const replaced = new Set(ordered.flatMap((o) => o.op.supersedes ?? []));
      const order = ordered.filter((o) => !replaced.has(o.op.opId));
      if (order.length === 0) return null;
      return {
        // Latest desired, earliest base: the user's most recent intention,
        // resolved against where their editing actually began. Within one
        // origin the two are usually the same value anyway — recordProfileIntent
        // carries a field's first base forward through the chain — so this is
        // belt-and-braces for a chain assembled any other way (a draft
        // restored across a reload, a future writer).
        desired: order[order.length - 1].field.desired,
        baseValue: order[0].field.base.present ? order[0].field.base.value : undefined,
        baseRevision: Math.min(...order.map((o) => o.op.baseRevision)),
        // Every operation the chain OWNS, replaced ones included: they are
        // acknowledged together, so a superseded keystroke is not left behind
        // to be re-sent as if nobody had answered it.
        opIds: ordered.map((o) => o.op.opId),
        lineage: order[0].op.lineage,
        supersedes: new Set(ordered.flatMap((o) => o.op.supersedes ?? [])),
        additive: order.every((o) => o.op.mode === 'add-skills'),
      };
    }).filter((c): c is NonNullable<typeof c> => c !== null);

    const allOpIds = chains.flatMap((c) => c.opIds);
    if (chains.length === 1) {
      const only = chains[0];
      plans.set(key, {
        kind: 'value',
        value: only.desired.present ? only.desired.value : undefined,
        baseValue: only.baseValue,
        baseRevision: only.baseRevision,
        opIds: only.opIds,
      });
      continue;
    }

    // Identical intentions need no resolution at all.
    const first = chains[0];
    const firstValue = first.desired.present ? first.desired.value : undefined;
    if (chains.every((c) => sameValue(c.desired.present ? c.desired.value : undefined, firstValue))) {
      plans.set(key, {
        kind: 'value',
        value: firstValue,
        baseValue: first.baseValue,
        baseRevision: Math.min(...chains.map((c) => c.baseRevision)),
        opIds: allOpIds,
      });
      continue;
    }

    // One chain may explicitly continue the others (a draft picked up after a
    // reload records the ids it is carrying forward). Ancestry is DECLARED,
    // never inferred from enumeration order.
    const heir = chains.find((c) => chains.every(
      (other) => other === c || other.opIds.every((id) => c.supersedes.has(id)),
    ));
    if (heir) {
      plans.set(key, {
        kind: 'value',
        value: heir.desired.present ? heir.desired.value : undefined,
        baseValue: heir.baseValue,
        baseRevision: Math.min(...chains.map((c) => c.baseRevision)),
        opIds: allOpIds,
      });
      continue;
    }

    // Skill IMPORTS from two origins are additive by construction: each says
    // "also these", neither says "and nothing else".
    if (key === 'skills' && chains.every((c) => c.additive)) {
      let merged: SkillWithLevel[] | null = [];
      for (const chain of chains) {
        const value = chain.desired.present ? chain.desired.value : undefined;
        merged = merged && isSkillList(value) ? mergeSkillAdditions(merged, value) : null;
        if (!merged) break;
      }
      if (merged) {
        plans.set(key, {
          kind: 'value',
          value: merged,
          baseValue: first.baseValue,
          baseRevision: Math.min(...chains.map((c) => c.baseRevision)),
          opIds: allOpIds,
        });
        continue;
      }
    }

    // Two independent origins want different things. Nothing is sent — and
    // the caller is told exactly WHAT is in dispute, so the person can be
    // shown the actual values and the answer can name the very operations
    // they were looking at.
    plans.set(key, {
      kind: 'conflict',
      opIds: allOpIds,
      candidates: chains.map((c) => ({
        value: c.desired.present ? c.desired.value : undefined,
        lineage: c.lineage,
        opIds: c.opIds,
      })),
    });
  }

  // The résumé is one document: half of it agreeing does not make it sendable.
  if (RESUME_BUNDLE.some((k) => plans.get(k)?.kind === 'conflict')) {
    for (const k of RESUME_BUNDLE) {
      const plan = plans.get(k);
      if (plan) {
        plans.set(k, {
          kind: 'conflict',
          opIds: plan.opIds,
          candidates: plan.kind === 'conflict' ? plan.candidates : [],
        });
      }
    }
  }
  return plans;
}

/** Every operation touching one of `keys`. Failure PROPAGATES: acknowledging
 *  from a partial view would consume an edit that was never sent. */
function outstandingOpsForKeys(keys: readonly string[]): JournalResult<JournalOp[]> {
  const journal = readOutstandingOps();
  if (!journal.ok) return journal;
  const wanted = new Set(keys);
  return {
    ok: true,
    value: journal.value.filter((op) => op.fields.some((f) => wanted.has(f.key))),
  };
}

export function resetProfileDirtyLedger(): void {
  ledgerScope = null;
  fieldIntents.clear();
  unwrittenConfirmation = null;
  lastLoadSource = null;
  skillOps = null;
}

/**
 * Acknowledges the journal operations a confirmation actually landed: an
 * operation is consumed only when what it asked for is what the server now
 * holds. Runs under the cross-tab lock — it removes storage keys other tabs
 * can see — and is a no-op when the browser cannot serialize, which leaves
 * the operations outstanding rather than deleting them unsafely.
 */
/**
 * Runs a critical section over this browser's SHARED profile state — the sync
 * envelope, the raw mirror, the journal. Everything that reads those, decides
 * from what it read, and writes back must be in here: two tabs doing
 * read-decide-write concurrently is the lost update this whole slice exists to
 * remove, and the CAS revision only protects the CLOUD row, not localStorage.
 *
 * NETWORK AWAITS MUST NOT BE INSIDE. The lock is not reentrant, and holding it
 * across a request would freeze every other tab for as long as the network
 * takes. Callers prepare under the lock, release, send, and re-enter to settle.
 */
async function withSharedState<T>(
  token: OwnerToken,
  fn: () => T,
): Promise<{ ok: true; value: T } | { ok: false; result: ProfileSaveResult }> {
  const locked = await withProfileLock(token, fn);
  if (locked.ok) return { ok: true, value: locked.value };
  // SUPERSEDED is the silent one: this write belongs to an owner who is gone,
  // and nothing about it is news to whoever is signed in now.
  //
  // ABANDONED and NO-LOCK are both this user's own failure and must be
  // reported. Writing anyway in the no-lock case is exactly the concurrent
  // read-decide-write this guards against.
  return {
    ok: false,
    result: locked.reason === 'superseded'
      ? { status: 'abandoned' }
      : { status: 'device-failed', phase: 'stage' },
  };
}

/**
 * The operations inside `ids` that are FINISHED, as whole dependency
 * closures.
 *
 * A receipt and everything it answers — and an edit and everything it
 * supersedes — are one obligation. A closure is finished only when every
 * field anywhere in it is either spoken for by another member (a receipt that
 * decided it, an edit that replaced it) or already what the row holds. Half a
 * closure is never removed: deleting a receipt while an operation it names
 * survives for some other field would take the decision away and raise the
 * conflict again, and deleting an edit while its replacement is still owed
 * would lose the record of the replacement.
 */
function finishedClosures(
  /** Where to start looking. The closure itself may reach further — every
   *  operation in `byId` that is connected to one of these. */
  seeds: Iterable<string>,
  byId: ReadonlyMap<string, JournalOp>,
  stored: Record<string, unknown>,
  /** What this write actually SENT for a key, where that differs from what
   *  the operation itself asked for (a chain collapses to its latest value). */
  sentValue: (key: string) => { known: boolean; value?: unknown },
): string[] {
  const seeded = new Set([...seeds].filter((id) => byId.has(id)));
  const members = [...byId.keys()];
  const neighbours = new Map<string, Set<string>>();
  const join = (a: string, b: string) => {
    if (!byId.has(a) || !byId.has(b)) return;
    (neighbours.get(a) ?? neighbours.set(a, new Set()).get(a)!).add(b);
    (neighbours.get(b) ?? neighbours.set(b, new Set()).get(b)!).add(a);
  };
  for (const id of members) {
    const op = byId.get(id)!;
    for (const target of [...(op.supersedes ?? []), ...(op.resolves ?? [])]) join(id, target);
  }

  const seen = new Set<string>();
  const finished: string[] = [];
  for (const id of seeded) {
    if (seen.has(id)) continue;
    const closure = new Set([id]);
    const queue = [id];
    while (queue.length > 0) {
      const current = queue.pop()!;
      for (const next of neighbours.get(current) ?? []) {
        if (!closure.has(next)) { closure.add(next); queue.push(next); }
      }
    }
    for (const member of closure) seen.add(member);

    // Who speaks for which field, per field rather than per operation: a
    // descendant replaces its ancestor only where it carries the same field,
    // and a receipt only where it decided one.
    const spokenFor = new Map<string, Set<string>>();
    const claim = (target: string, claimed: Iterable<string>) => {
      if (!closure.has(target)) return;
      const taken = spokenFor.get(target) ?? new Set<string>();
      for (const k of claimed) taken.add(k);
      spokenFor.set(target, taken);
    };
    for (const member of closure) {
      const op = byId.get(member)!;
      for (const target of op.supersedes ?? []) claim(target, op.fields.map((f) => f.key));
      for (const target of op.resolves ?? []) claim(target, Object.keys(op.decisions ?? {}));
    }

    const keys = new Set<string>();
    for (const member of closure) for (const f of byId.get(member)!.fields) keys.add(f.key);
    const satisfied = [...keys].every((key) => {
      const owners = [...closure]
        .filter((m) => !spokenFor.get(m)?.has(key))
        .map((m) => byId.get(m)!)
        .filter((op) => op.fields.some((f) => f.key === key));
      // Two owners means two lineages still disagree about it.
      if (owners.length !== 1) return false;
      const field = owners[0].fields.find((f) => f.key === key)!;
      const sent = sentValue(key);
      return sameValue(
        sent.known ? sent.value : (field.desired.present ? field.desired.value : undefined),
        stored[key],
      );
    });
    if (satisfied) finished.push(...closure);
  }
  return finished;
}

/**
 * Acknowledges the journal operations THIS write was made of — the ids it
 * captured when it was prepared, never "whatever currently touches these
 * keys". An operation another tab appended while the request was in flight
 * describes a value the server has not been told about; consuming it would
 * delete an edit that was never saved.
 *
 * An operation is consumed only when EVERY field it carries matches what the
 * server now holds: it is one action, and half of it landing is not it
 * landing. Caller must already hold the shared-state lock.
 */
function ackConfirmedJournalOpsLocked(
  pending: ProfilePendingWrite,
  keys: readonly string[],
  confirmedProfile: ProfileData,
  revision: number,
  token: OwnerToken,
): boolean {
  if (pending.journalOpIds.length === 0) return true;
  const stored = confirmedProfile as unknown as Record<string, unknown>;
  const desired = pending.desiredProfile as unknown as Record<string, unknown>;
  // ONLY the operations THIS REQUEST captured. The snapshot was taken under
  // the lock before the request went out (see prepareStagedWrite, which
  // captures each planned operation's whole ancestry group), so anything
  // outside it was appended while the request was in flight and the server
  // has never seen it. Widening to whatever is outstanding NOW would let an
  // answer about one value delete the edit that replaced it — the user keeps
  // typing, and their newest keystroke disappears looking saved.
  const snapshot = new Set(pending.journalOpIds);
  const candidates = readOutstandingOps();
  if (!candidates.ok) return false;
  const byId = new Map(
    candidates.value.filter((op) => snapshot.has(op.opId)).map((op) => [op.opId, op]),
  );
  // Which of the keys this write SENT the server now actually holds. The
  // value compared is the one the plan collapsed the chain to, so an
  // intermediate keystroke counts as landed when the value it led to did.
  const confirmedKeys = new Set<string>();
  for (const key of keys) if (sameValue(desired[key], stored[key])) confirmedKeys.add(key);
  const reached = new Set<string>();
  for (const key of confirmedKeys) {
    for (const opId of pending.journalPlan[key] ?? []) {
      if (byId.has(opId)) reached.add(opId);
    }
  }
  // An operation is ONE action across every field it carries — a college
  // switch that clears the major, a résumé removal that drops its coursework.
  // Reaching it through the field that landed is not enough: it is settled
  // only when the row holds what it asked for in EVERY field, whether that
  // happened in this write or an earlier one. A field it wanted that the row
  // still disagrees about (locked, or never sent) keeps the whole operation
  // outstanding — settling anyway would delete that half of the user's action
  // with no record it existed.
  const landed = finishedClosures(
    reached,
    byId,
    stored,
    (key) => (confirmedKeys.has(key) ? { known: true, value: desired[key] } : { known: false }),
  );
  if (landed.length === 0) return true;
  // The receipts go down FIRST, before anything is settled or deleted. An
  // ancestor that disappears without its receipt is one no descendant can
  // ever rebase onto — the ancestry it names is gone and no later pass can
  // reconstruct it. A receipt that cannot be written therefore means the
  // ancestor is NOT settled: the caller retries, and nothing is half-done.
  // The WHOLE row at this revision, so a descendant carrying confirmed and
  // unconfirmed fields together still describes one coherent moment.
  const rowAtRevision: Record<string, JournalValue> = {};
  for (const key of Object.keys(stored)) rowAtRevision[key] = encodeJournalValue(stored, key);
  for (const opId of landed) {
    const op = byId.get(opId);
    if (!op) continue;
    const settledKeys = op.fields.map((f) => f.key).filter((k) => confirmedKeys.has(k));
    if (settledKeys.length === 0) continue;
    for (const key of settledKeys) {
      if (!(key in rowAtRevision)) rowAtRevision[key] = { present: false };
    }
    if (!appendRebaseReceipt({
      v: 1,
      ancestorOpId: op.opId,
      // The ancestor's OWN lineage, not this document's: the tab finishing
      // this request may not be the tab that made the edit, and only the
      // edit's own lineage may be rebased onto it.
      ancestorLineage: op.lineage,
      revision,
      profile: rowAtRevision,
      confirmedKeys: settledKeys,
    }, token)) {
      return false;
    }
  }
  // NOTHING is compacted here. Dropping a receipt requires proving no
  // descendant can still reach it, and journal appends deliberately do not
  // take this lock — so a writer that read the journal before the settle can
  // append such a descendant after any scan, at which point the receipt it
  // needs is gone and the user's own next keystroke becomes a conflict.
  //
  // Closing that needs a real writer/compactor fence: an append must commit
  // only if it observes a stable epoch before AND after its own write, and
  // the compactor must fence, rescan, delete and publish the next epoch. That
  // is the shared journal lease, which this slice does not build. Until it
  // exists the receipts are bounded by MAX_REBASE_RECEIPTS and the coordinator
  // FAILS CLOSED at the cap — a visible, retryable stop, never a silent
  // conflict manufactured out of a deleted acknowledgement.
  return settleJournalOps(landed, token);
}

async function ackConfirmedJournalOps(
  keys: readonly string[],
  confirmedProfile: ProfileData,
  token: OwnerToken,
): Promise<boolean> {
  const stored = confirmedProfile as unknown as Record<string, unknown>;
  // Nothing to acknowledge needs no serialization: taking the lock here would
  // make every save fail on a browser without Web Locks even when the journal
  // is empty. The lock guards MUTATION of shared state, and there is none.
  const preview = outstandingOpsForKeys(keys);
  if (!preview.ok) return false;
  if (preview.value.length === 0) return true;
  const locked = await withProfileLock(token, () => {
    const candidates = outstandingOpsForKeys(keys);
    if (!candidates.ok) return false;
    // ALL of an operation's fields, not some: it is one action, and half of
    // it landing is not it landing.
    const ops = candidates.value.filter((op) => op.fields.every(
      (f) => sameValue(f.desired.present ? f.desired.value : undefined, stored[f.key]),
    ));
    return ops.length === 0 || settleJournalOps(ops.map((op) => op.opId), token);
  });
  return locked.ok && locked.value;
}

function clearConfirmedKeys(
  keys: readonly string[],
  staged: Record<string, number>,
  confirmed?: ProfilePendingWrite,
): void {
  // The OPERATION ledger is consumed regardless of whether the key is still
  // dirty. A newer import bumps the version, and gating consumption on that
  // would leave the first import's names in the ledger forever — every later
  // patch would re-send them, resurrecting whatever the other device deleted
  // in between. Consuming does NOT clear the newer writer's intent.
  if (keys.includes('skills')) consumeSkillOps(confirmed);
  for (const key of keys) {
    const intent = fieldIntents.get(key);
    if (!intent) continue;
    // Only if no newer edit has moved this field since the write was staged.
    if (intent.version !== (staged[key] ?? -1)) continue;
    fieldIntents.delete(key);
  }
}

function recordUnstaged(
  desired: ProfileData,
  keys: readonly ProfileKey[],
  opts: StageOptions,
  token: OwnerToken,
): void {
  ensureScope(token);
  const rec = desired as unknown as Record<string, unknown>;
  const confirmed = readProfileSyncEnvelope()?.confirmed ?? null;
  const base = (confirmed?.profile ?? {}) as unknown as Record<string, unknown>;
  for (const key of keys) {
    if (!(key in rec)) continue;
    let intent = fieldIntents.get(key);
    if (!intent) {
      intent = {
        baseValue: base[key],
        baseRevision: confirmed?.revision ?? 0,
        version: 1,
        writers: new Set([DEFAULT_WRITER]),
        hasUnstaged: false,
        allowCreate: false,
      };
      fieldIntents.set(key, intent);
    }
    intent.unstagedValue = rec[key as string];
    intent.hasUnstaged = true;
    intent.allowCreate = intent.allowCreate || !!opts.allowCreate;
  }
}

/** A stage that DID land absorbs these keys; anything another writer left
 *  behind stays queued for its own retry. */
function consumeUnstaged(keys: readonly ProfileKey[], token: OwnerToken): void {
  ensureScope(token);
  for (const key of keys) {
    const intent = fieldIntents.get(key);
    if (!intent) continue;
    intent.hasUnstaged = false;
    delete intent.unstagedValue;
  }
}

/**
 * The base a stage must be made against: for every key it is about, the value
 * and revision frozen when that field's edit BEGAN. The revision is the OLDEST
 * of them — a write that carries an edit started at revision 7 is a write
 * against revision 7, whatever else has landed since.
 */
function stagedIntentBase(
  keys: readonly ProfileKey[],
  existing: ProfilePendingWrite | null,
  confirmed: { revision: number; profile: ProfileData } | null,
): { revision: number; profile: ProfileData | null } {
  const start = existing?.baseProfile ?? confirmed?.profile ?? null;
  const merged = start ? { ...(start as unknown as Record<string, unknown>) } : null;
  let revision = existing?.baseRevision ?? confirmed?.revision ?? 0;
  let sawIntent = existing != null;
  for (const key of keys) {
    const intent = fieldIntents.get(key as string);
    if (!intent) continue;
    if (merged) merged[key as string] = intent.baseValue;
    revision = sawIntent ? Math.min(revision, intent.baseRevision) : intent.baseRevision;
    sawIntent = true;
  }
  return { revision, profile: merged as unknown as ProfileData | null };
}

/**
 * Why a write cannot proceed, if it cannot. Two very different reasons that
 * the raw token check collapses into one:
 *   - the identity MOVED ON  -> 'abandoned'. Not this user's news; the UI has
 *     already been rebuilt for somebody else and must not report a failure.
 *   - the identity is the same, but this browser's local data is not
 *     CONFIRMED for it (a blocked clear, a deferred Flow-B grant, private
 *     mode) -> 'device-failed'. That is this user's own save not happening,
 *     and telling them nothing is worse than telling them it failed.
 */
function ownerGate(token: OwnerToken): ProfileSaveResult | null {
  if (isOwnerTokenValid(token, token.uid)) return null;
  return isTokenOwnerStillCurrent(token)
    ? { status: 'device-failed', phase: 'stage' }
    : { status: 'abandoned' };
}

function pendingUnstagedKeys(): ProfileKey[] {
  const out: ProfileKey[] = [];
  for (const [key, intent] of fieldIntents) if (intent.hasUnstaged) out.push(key as ProfileKey);
  return out;
}


// ---------------------------------------------------------------------------
// Skills: operations, identified globally
// ---------------------------------------------------------------------------
// Skills are the one field where "what changed" is not "what the list now is".
// An import ADDS names; a manual edit REPLACES the list (including deletions).
// Each operation carries a globally unique id rather than a per-tab counter:
// two tabs on the same account each start their own counter at 1, so comparing
// integers across them would let one tab's first import look "older" than the
// other's and be re-interpreted as a replace. Ids are compared by IDENTITY,
// merged as a union, and consumed exactly when the write that carried them is
// confirmed.

export interface SkillOp {
  opId: string;
  kind: 'add' | 'replace';
  /** Present for 'add'. */
  skill?: SkillWithLevel;
}

interface SkillOpsState { scope: string; ops: SkillOp[] }
let skillOps: SkillOpsState | null = null;

function skillOpsFor(token: OwnerToken): SkillOpsState {
  const scope = scopeOf(token);
  if (!skillOps || skillOps.scope !== scope) skillOps = { scope, ops: [] };
  return skillOps;
}

function newOpId(): string {
  const c = typeof crypto !== 'undefined' ? crypto : undefined;
  if (c && typeof c.randomUUID === 'function') return c.randomUUID();
  return `op-${Date.now().toString(36)}-${Math.floor(Math.random() * 1e9).toString(36)}`;
}

/** True while the most recent operation is a manual replace: the list itself
 *  is the intent, and a later import must not turn a deletion back into "add
 *  everything again". Stops being true once that replace is confirmed. */
function skillsAreReplaced(ops: readonly SkillOp[]): boolean {
  return ops.some((op) => op.kind === 'replace');
}

function additionsOf(ops: readonly SkillOp[]): SkillWithLevel[] {
  const out: SkillWithLevel[] = [];
  const names = new Set<string>();
  for (const op of ops) {
    if (op.kind !== 'add' || !op.skill) continue;
    if (names.has(op.skill.name)) continue;
    names.add(op.skill.name);
    out.push(op.skill);
  }
  return out;
}

/** A résumé parse or a GitHub import added these. Purely additive. */
export function markSkillAdditions(additions: readonly SkillWithLevel[], token: OwnerToken): void {
  // A résumé parse or GitHub import that started on a screen the browser has
  // since moved past. Both calls below reset the ledger to the caller's scope,
  // and the live owner's own pending skill operations go with it — turning
  // their additive import into a whole-list replace that deletes every skill
  // the row already had.
  if (!isOwnerTokenValid(token, token.uid)) return;
  ensureScope(token);
  const state = skillOpsFor(token);
  if (skillsAreReplaced(state.ops)) return; // sticky until the replace lands
  const known = new Set(additionsOf(state.ops).map((sk) => sk.name));
  for (const skill of additions) {
    if (known.has(skill.name)) continue;
    known.add(skill.name);
    state.ops.push({ opId: newOpId(), kind: 'add', skill });
  }
}

/** The user edited the skills list by hand — an add, a level change, or a
 *  DELETE. The whole list is the intent from here on. */
export function markSkillsReplaced(token: OwnerToken): void {
  if (!isOwnerTokenValid(token, token.uid)) return;
  ensureScope(token);
  const state = skillOpsFor(token);
  state.ops = [{ opId: newOpId(), kind: 'replace' }];
}

/** Union by op id — an entry another tab staged is adopted, and one this tab
 *  already consumed is not resurrected by it. */
function adoptSkillOps(persisted: readonly SkillOp[], token: OwnerToken): void {
  const state = skillOpsFor(token);
  const seen = new Set(state.ops.map((op) => op.opId));
  for (const op of persisted) if (!seen.has(op.opId)) state.ops.push(op);
}

/**
 * The operations this confirmation carried are now STORED — removed by ID, so
 * a second import that landed while the first request was in flight keeps its
 * own delta, and a confirmed manual replace stops being sticky.
 */
function consumeSkillOps(confirmed?: ProfilePendingWrite): void {
  if (!skillOps || !confirmed) return;
  const landed = new Set(confirmed.skillOps.map((op) => op.opId));
  skillOps = { scope: skillOps.scope, ops: skillOps.ops.filter((op) => !landed.has(op.opId)) };
}

// ---------------------------------------------------------------------------
// Envelope storage
// ---------------------------------------------------------------------------

function isProfileObject(value: unknown): value is ProfileData {
  return !!value && typeof value === 'object' && !Array.isArray(value);
}

function stringList(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((k): k is string => typeof k === 'string') : [];
}

function readKeyOpIds(value: unknown): Record<string, string[]> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return {};
  const out: Record<string, string[]> = {};
  for (const [k, v] of Object.entries(value as Record<string, unknown>)) {
    if (Array.isArray(v) && v.every((x) => typeof x === 'string')) out[k] = v as string[];
  }
  return out;
}

function readKeyVersions(value: unknown): Record<string, number> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return {};
  const out: Record<string, number> = {};
  for (const [k, v] of Object.entries(value as Record<string, unknown>)) {
    if (typeof v === 'number' && Number.isInteger(v) && v >= 0) out[k] = v;
  }
  return out;
}

function readSkillList(value: unknown): SkillWithLevel[] {
  return isSkillList(value) ? value : [];
}

function readSkillOps(value: unknown): SkillOp[] {
  if (!Array.isArray(value)) return [];
  return value.filter((op): op is SkillOp => (
    !!op && typeof op === 'object'
    && typeof (op as SkillOp).opId === 'string'
    && ((op as SkillOp).kind === 'add' || (op as SkillOp).kind === 'replace')
  ));
}

/**
 * The envelope as an AUTHORITY read: `{ok:true, value:null}` means there is
 * genuinely nothing stored, and only that licenses creating, saving, or
 * advancing a monotonic counter from zero. Everything else — a storage
 * refusal, a superseded owner, bytes that are not JSON, a schema this build
 * does not recognise — is `ok:false`, because acting on any of them means
 * writing over a document that exists and could not be read.
 *
 * `readProfileSyncEnvelope` below keeps the nullable shape for the display
 * and merge paths that genuinely have nothing to do but render blank.
 */
export function readProfileSyncEnvelopeStrict(): JournalResult<ProfileSyncEnvelope | null> {
  const entry = readUserScopedEntry(STORAGE_KEYS.PROFILE_SYNC);
  if (entry.status === 'unavailable') {
    return { ok: false, reason: `profile envelope unavailable: ${entry.reason}` };
  }
  if (entry.status === 'absent') return { ok: true, value: null };
  const parsedEnvelope = parseProfileSyncEnvelope(entry.value);
  return parsedEnvelope === null
    ? { ok: false, reason: 'profile envelope is not a shape this build understands' }
    : { ok: true, value: parsedEnvelope };
}

export function readProfileSyncEnvelope(): ProfileSyncEnvelope | null {
  const raw = readUserScopedRaw(STORAGE_KEYS.PROFILE_SYNC);
  if (!raw) return null;
  return parseProfileSyncEnvelope(raw);
}

function parseProfileSyncEnvelope(raw: string): ProfileSyncEnvelope | null {
  try {
    const parsed = JSON.parse(raw) as unknown;
    if (!parsed || typeof parsed !== 'object') return null;
    const env = parsed as Partial<ProfileSyncEnvelope>;
    if (env.v !== 1) return null; // a future/rewritten shape is not guessed at
    const c = env.confirmed;
    const confirmed = c && typeof c.revision === 'number' && Number.isInteger(c.revision)
      && c.revision >= 1 && isProfileObject(c.profile)
      ? { revision: c.revision, profile: c.profile }
      : null;
    const p = env.pending;
    const pending = p && typeof p.mutationId === 'string'
      && typeof p.baseRevision === 'number' && Number.isInteger(p.baseRevision)
      && p.baseRevision >= 0
      && isProfileObject(p.baseProfile) && isProfileObject(p.desiredProfile)
      && Array.isArray(p.dirtyKeys)
      && stringList(p.dirtyKeys).length > 0
      // ANY unrecognised key voids the whole entry. Filtering them out and
      // proceeding would send a patch this build assembled from a document it
      // does not fully understand — a downgrade, or another tab on a newer
      // build, would silently lose the fields this one cannot name.
      && stringList(p.dirtyKeys).every(isProfileKey)
      && stringList(p.lockedKeys).every(isProfileKey)
      && stringList(p.additiveKeys).every(isProfileKey)
      ? completeResumeBundle({
        mutationId: p.mutationId,
        baseRevision: p.baseRevision,
        baseProfile: p.baseProfile,
        desiredProfile: p.desiredProfile,
        dirtyKeys: stringList(p.dirtyKeys),
        keyVersions: readKeyVersions(p.keyVersions),
        skillAdditions: readSkillList(p.skillAdditions),
        skillsReplaced: p.skillsReplaced === true,
        skillOps: readSkillOps(p.skillOps),
        additiveKeys: stringList(p.additiveKeys),
        lockedKeys: stringList(p.lockedKeys),
        conflictRemote: isProfileObject(p.conflictRemote) ? p.conflictRemote : null,
        legacy: p.legacy === true,
        deferredCreate: p.deferredCreate === true,
        journalOpIds: stringList(p.journalOpIds),
        journalPlan: readKeyOpIds(p.journalPlan),
      })
      : null;
    const t = env.tombstone;
    const tombstone = t && (t.reason === 'deleted' || t.reason === 'merged')
      ? { reason: t.reason, rawQuarantined: t.rawQuarantined === true }
      : null;
    return { v: 1, confirmed, pending, tombstone };
  } catch {
    return null;
  }
}

/**
 * The confirmed revision is MONOTONIC. A slow response from revision 7 can
 * land after another tab has already recorded 9; letting it write would roll
 * every reader back to a row the server no longer has. Equal revision with a
 * DIFFERENT profile is not a race at all — it means two writers disagree
 * about what one revision contains — so it is refused rather than resolved.
 */
function writeEnvelope(envelope: ProfileSyncEnvelope, token: OwnerToken): boolean {
  const current = readProfileSyncEnvelope()?.confirmed ?? null;
  const next = envelope.confirmed;
  if (current && next) {
    if (next.revision < current.revision) return true; // stale, ignored — not a failure
    if (next.revision === current.revision
      && stableStringify(next.profile) !== stableStringify(current.profile)) {
      return false; // malformed: one revision, two contents
    }
  }
  return writeLocalStorageJSON(STORAGE_KEYS.PROFILE_SYNC, envelope, token);
}

/** The raw mirror every other screen reads. Kept in the pre-CAS shape on
 *  purpose — changing it would break /results, /favorites, /compare, the
 *  roadmap and the school gate all at once for zero benefit. */
function writeRawMirror(profile: ProfileData, token: OwnerToken): boolean {
  return writeLocalStorageJSON(STORAGE_KEYS.PROFILE, profile, token);
}

/**
 * The confirmed row and its revision, as ONE pair from ONE read.
 *
 * Not "the mirror, plus the revision from the envelope": those are two keys
 * read at two moments, and another tab can land between them — which pairs
 * this tab's old values with a revision they were never made against, exactly
 * the disguise the baseline exists to prevent. The envelope holds both
 * together, so one parse of it is the only honest snapshot.
 *
 * Null means there is no confirmed row to have rendered from, and the caller
 * must treat its baseline as unknown rather than invent one.
 */
export function readRenderedBaseline(): { profile: ProfileData; revision: number } | null {
  const confirmed = readProfileSyncEnvelope()?.confirmed ?? null;
  if (!confirmed) return null;
  return { profile: confirmed.profile, revision: confirmed.revision };
}

/**
 * What a surface is rendering, as ONE immutable value.
 *
 * A surface captures this once — when it accepts a view (a hydration landing,
 * a gate deciding which campus to display) — and then acts against THAT or
 * does not act. Three things it exists to make impossible:
 *
 *  - re-reading storage when the person clicks, which pairs the values they
 *    saw with whatever revision another tab has written since, and sends
 *    their old choice as though it had been made against the new row;
 *  - carrying a captured view across an identity switch, which hands one
 *    owner's row to another as their patch base. The token is what makes that
 *    detectable at all: a view whose owner has moved on is refused, never
 *    silently reused;
 *  - confusing what was STORED with what was SHOWN. Those are different
 *    documents and conflating them silently destroys intent — see
 *    `baseProfile` below.
 *
 * Deep-frozen on construction, so a holder cannot mutate the values it is
 * about to be judged against.
 */
export interface ProfileViewSnapshot {
  /** Identifies THIS accepted view. A new id means the screen genuinely
   *  changed; the same id means the same view, however many times it was
   *  passed down. */
  readonly viewId: string;
  /**
   * The baseline EXACTLY as it was accepted — absent fields still absent,
   * nothing defaulted, nothing normalized. Null means no row at all.
   *
   * This distinction is load-bearing, not pedantry. A row with no
   * `home_school` renders as UIUC because UIUC is the matcher's default; if
   * the default were recorded as the base, a person explicitly confirming
   * UIUC would produce base === desired, the change would look like a no-op,
   * and the confirmation they just made would never be written.
   */
  readonly baseProfile: ProfileData | null;
  /**
   * What is actually on screen: the base with defaults filled in, normalized,
   * and this device's own unsent edits applied. This is what a full-document
   * write must be built from — never the CAS base, and never a substitute for
   * it.
   */
  readonly renderedProfile: ProfileData;
  /** The revision `baseProfile` IS. 0 means no known row, and can never be
   *  sent as a CAS expectation. */
  readonly revision: number;
  readonly token: OwnerToken;
  /** The accepting surface's identity generation at acceptance. */
  readonly identityGeneration: number;
  /** Where this view came from: a hydration the UI accepted, or a direct read
   *  by a surface that owns its own decision (the school gate). */
  readonly source: 'hydration' | 'storage';
}

function deepFreeze<T>(value: T): T {
  if (!value || typeof value !== 'object') return value;
  Object.freeze(value);
  for (const v of Object.values(value as Record<string, unknown>)) deepFreeze(v);
  return value;
}

/** Deep copy that keeps the exact OWN key set, including keys whose value is
 *  `undefined`. A JSON round-trip deletes those, which turns "this row has
 *  the field, set to nothing" into "this row has never had the field" — the
 *  one distinction the baseline exists to preserve. */
function cloneOwnKeys<T>(value: T): T {
  if (!value || typeof value !== 'object') return value;
  if (Array.isArray(value)) return value.map((v) => cloneOwnKeys(v)) as unknown as T;
  const out: Record<string, unknown> = {};
  for (const k of Object.keys(value as object)) {
    out[k] = cloneOwnKeys((value as Record<string, unknown>)[k]);
  }
  return out as T;
}

function frozenCopy<T>(value: T): T {
  // The copy has to sever every alias to the caller's objects — a holder
  // mutating its own profile object would otherwise mutate the baseline it is
  // judged against. structuredClone where it exists (it is exact for anything
  // a row can hold); otherwise an own-key clone, never a JSON round-trip,
  // which silently drops own-undefined keys.
  let clone: T;
  try {
    clone = typeof structuredClone === 'function' ? structuredClone(value) : cloneOwnKeys(value);
  } catch {
    clone = cloneOwnKeys(value);
  }
  return deepFreeze(clone);
}

let viewSeq = 0;

/** The one constructor. Every snapshot is a deep, frozen copy — callers hand
 *  in their live objects and get back something nothing can mutate. */
export function makeProfileViewSnapshot(input: {
  baseProfile: ProfileData | null;
  renderedProfile: ProfileData;
  revision: number;
  token: OwnerToken;
  identityGeneration: number;
  source: ProfileViewSnapshot['source'];
}): ProfileViewSnapshot {
  viewSeq += 1;
  return deepFreeze({
    viewId: `view-${viewSeq}-${input.token.epoch}`,
    baseProfile: input.baseProfile === null ? null : frozenCopy(input.baseProfile),
    renderedProfile: frozenCopy(input.renderedProfile),
    revision: input.revision,
    // A COPY of the token too. It is plain data (uid + epoch), and freezing
    // the caller's own object as a side effect of taking a snapshot would
    // reach out of this value and change something the caller still owns.
    token: frozenCopy(input.token),
    identityGeneration: input.identityGeneration,
    source: input.source,
  });
}

/**
 * The same accepted view, showing what is on screen NOW.
 *
 * A local edit changes what the person is looking at without changing what
 * the row is: the base, the revision, the owner and the view's identity are
 * all unchanged, and only the rendered document moves. Surfaces that build a
 * full document from `renderedProfile` — the school switcher — would
 * otherwise write the values as they stood at hydration and briefly undo an
 * edit the person can still see on screen.
 *
 * The identity is deliberately preserved: this is not a new view, it is the
 * same one with the user's typing in it.
 */
export function withRenderedProfile(
  view: ProfileViewSnapshot,
  rendered: ProfileData,
): ProfileViewSnapshot {
  return deepFreeze({
    viewId: view.viewId,
    baseProfile: view.baseProfile,
    renderedProfile: frozenCopy(rendered),
    revision: view.revision,
    token: view.token,
    identityGeneration: view.identityGeneration,
    source: view.source,
  });
}

/**
 * The snapshot a surface should render and later act against, from one read.
 *
 * The confirmed row, its revision AND this device's unsent edits all come out
 * of a single envelope parse — never the mirror paired with a separately-read
 * revision, which is two keys at two moments with room for another tab in
 * between. With no confirmed row there is no base at all (`baseProfile` null,
 * revision 0) and the mirror is only what there is to SHOW; if a row gets
 * confirmed between these reads, revision 0 still refuses to pretend this
 * view was made against it.
 */
export function readProfileView(token: OwnerToken): ProfileViewSnapshot | null {
  // BEFORE the first read. A superseded token must not be able to observe the
  // current owner's envelope at all, let alone come back holding it: a
  // snapshot pairing U2's row with U1's token passes every later shape check
  // while being exactly the thing none of them can detect.
  if (!isOwnerTokenValid(token, token.uid)) return null;
  const envelope = readProfileSyncEnvelope();
  if (envelope) {
    // A fenced row has no view, whatever else the envelope still holds. A
    // deleted or merged-away account can still carry a pending entry that was
    // quarantined rather than erased, and workingCopy would happily rebuild a
    // profile out of it — which then drives the match request and shows the
    // person a profile their account no longer has. Writes are fenced
    // elsewhere; this is the display side of the same fence.
    if (envelope.tombstone?.reason === 'deleted' || envelope.tombstone?.reason === 'merged') {
      return null;
    }
    // ONE parse decides everything. The raw mirror is deliberately NOT read
    // here: it is a second key written at a second moment, and mixing it in
    // is how a document from one instant gets paired with a revision from
    // another.
    const confirmed = envelope.confirmed ?? null;
    const rendered = workingCopy(confirmed, envelope.pending ?? null, null);
    if (!rendered) return null;
    return makeProfileViewSnapshot({
      baseProfile: confirmed?.profile ?? null,
      renderedProfile: rendered,
      revision: confirmed?.revision ?? 0,
      token,
      identityGeneration: token.epoch,
      source: 'storage',
    });
  }
  // No envelope at all — a browser that predates the coordinator. The pre-CAS
  // mirror is the only thing there is to show, and revision 0 says out loud
  // that it is not a baseline anything may CAS against.
  const mirror = readRawProfileMirror();
  if (!mirror) return null;
  return makeProfileViewSnapshot({
    baseProfile: null,
    renderedProfile: mirror,
    revision: 0,
    token,
    identityGeneration: token.epoch,
    source: 'storage',
  });
}

/** Whether the cloud row for this owner has been read at least once, so a
 *  caller knows there is something to patch rather than something to create. */
export function hasConfirmedProfileRevision(): boolean {
  return (readProfileSyncEnvelope()?.confirmed?.revision ?? 0) >= 1;
}

export function readRawProfileMirror(): ProfileData | null {
  const raw = readUserScopedRaw(STORAGE_KEYS.PROFILE);
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as unknown;
    return isProfileObject(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

function newMutationId(): string {
  const c = typeof crypto !== 'undefined' ? crypto : undefined;
  if (c && typeof c.randomUUID === 'function') return c.randomUUID();
  return `m-${Date.now().toString(36)}-${Math.floor(Math.random() * 1e9).toString(36)}`;
}

/** The user's working copy: the confirmed row with every unsent edit on top. */
function workingCopy(
  confirmed: ProfileSyncEnvelope['confirmed'],
  pending: ProfilePendingWrite | null,
  fallback: ProfileData | null,
): ProfileData | null {
  const base = confirmed?.profile ?? fallback ?? pending?.baseProfile ?? null;
  if (!pending) return base;
  if (!base) return pending.desiredProfile;
  return { ...base, ...pick(pending.desiredProfile, pending.dirtyKeys as ProfileKey[]) } as ProfileData;
}

// ---------------------------------------------------------------------------
// Hydration
// ---------------------------------------------------------------------------

export interface ProfileConflictCandidate {
  value: unknown;
  /** The lineage that wants it — different tabs, or this one before a reload. */
  lineage: string;
  /** Exactly the operations asking for it. */
  opIds: string[];
}

export interface ProfileConflict {
  key: string;
  candidates: ProfileConflictCandidate[];
  /** What the row held when this question was asked, and which "use the other
   *  version" selects. Answered against THIS value, never whatever the row has
   *  become by the time the person clicks. */
  remote: unknown;
  /**
   * The exact identity of this question, so an answer can prove it is
   * answering the same one.
   *
   * A view revision is not enough: a CAS conflict reports a row NEWER than the
   * one the screen was rendered from, and that newer row is what the question
   * is about.
   */
  remoteRevision: number;
  /** The pending write instance the question belonged to, when there was one.
   *  Null for a question derived from the journal alone. */
  mutationId: string | null;
  /** This device's side, versioned — the only durable provenance a candidate
   *  has when it names no journal operations (a legacy or server-side
   *  disagreement). Null means there is none, and an answer must fail closed
   *  rather than guess. */
  keyVersion: number | null;
}

/**
 * What a conflict refresh actually did.
 *
 * NOT a list. An empty array cannot tell "the question is settled" apart from
 * "the lock was unavailable", "the journal could not be read", or "a different
 * account owns this browser now" — and a caller that reads all four as
 * "settled" retires the prompt, drops the controls, and strands a durable
 * answer nobody can reach any more.
 */
/** Everything a successful refresh knows, out of the ONE critical section
 *  that produced it. The caller renders from these fields: re-reading storage
 *  to reconstruct them would pick up whatever landed in between. */
interface ProfileRefreshState {
  /** The document every screen should show: the confirmed row with whatever
   *  is still unsent laid on top. */
  profile: ProfileData | null;
  /** The accepted baseline, and the revision that baseline IS. */
  baseProfile: ProfileData | null;
  revision: number;
  /** Still owed to the cloud after the repair. Empty means nothing is. */
  pendingKeys: string[];
  /** The flush this refresh continued once the last lock came off, if the
   *  repair left something safe to send. Null means none was needed. */
  flushed: ProfileSaveResult | null;
}

export type ProfileConflictRefresh =
  /** A real disagreement is still open. `conflicts` is never empty here. */
  | (ProfileRefreshState & { status: 'current'; conflicts: ProfileConflict[] })
  /** The question is gone: answered, repaired, or settled by another tab. A
   *  DISTINCT status rather than an empty `current` payload — the whole point
   *  of replacing the bare array was that "nothing to show" and "nothing
   *  happened" must not share a representation. */
  | (ProfileRefreshState & { status: 'settled'; conflicts: readonly [] })
  /** THIS browser could not finish. Nothing durable was lost — the receipt is
   *  still on disk — so the prompt stays up and the same click can be made
   *  again. The phase says which boundary stopped it; `settle` means the
   *  repair itself landed and only the acknowledgement did not, which is
   *  still a failure the caller has to be able to retry. */
  | {
    status: 'device-failed';
    phase: 'lock' | 'journal' | 'envelope' | 'mirror' | 'settle' | 'stage';
    retryable: true;
  }
  /** The identity that asked no longer owns this browser. Nothing may be
   *  applied to the screen, and nothing about it is news to whoever is here
   *  now. */
  | { status: 'abandoned' };

export interface ProfileHydration {
  /** What the caller should render: the cloud row with any still-unconfirmed
   *  local edits re-applied on top. NOT a baseline — it deliberately shows
   *  values that are not in the row yet. */
  profile: ProfileData | null;
  /**
   * The CONFIRMED row exactly as it stands at `revision`, with nothing merged
   * on top and nothing defaulted. Null when there is no confirmed row.
   *
   * Kept separate from `profile` because they answer different questions:
   * `profile` is what the person sees, `baseProfile` is what a write may
   * claim it was made against. Using the rendered document as a baseline
   * hides a field the row does not have behind the value the UI defaults it
   * to, and an explicit choice of that value then looks like a no-op.
   */
  baseProfile: ProfileData | null;
  revision: number;
  source: LoadedProfile['source'];
  token: OwnerToken;
  /** True when an unsent edit was found and kept. */
  hasPending: boolean;
  /** Keys that cannot be sent without the user choosing a side — a genuine
   *  conflict, or a pre-CAS working copy whose base revision is unknown. */
  conflictKeys: string[];
  /**
   * What is actually in dispute, per key: each candidate value, who wrote it,
   * and the exact operations behind it.
   *
   * The caller renders this and hands the SAME object back when the person
   * answers. That binding is the point: an answer computed from whatever is
   * outstanding at click time would also swallow an edit another tab made
   * while the dialog was open — one the person never saw and never decided
   * about.
   */
  conflicts: ProfileConflict[];
  /** A local write this hydration needed did not land: the envelope could not
   *  be recorded, or a vanished row's stale mirror could not be removed. Other
   *  screens may still be reading a profile that no longer applies, and the
   *  revision may not have been recorded — reported, never assumed away. */
  quarantineFailed: boolean;
}

/**
 * Reads the cloud row and reconciles it with this browser's envelope + legacy
 * raw mirror. Throws exactly what loadProfile throws (OwnerNotReadyError for
 * an unattributable read, Error for a failed one) — a failed read is never
 * turned into "you have no profile".
 */
export async function hydrateProfile(): Promise<ProfileHydration> {
  // The network read happens FIRST and unlocked — holding the shared-state
  // lock across it would freeze every other tab for as long as it takes.
  // What this browser held when the read was ISSUED. An answer is only news
  // if the world has not moved past it while it was in flight.
  const fenceBefore = readProfileSyncEnvelope();
  const observedBefore: LoadFence = {
    revision: fenceBefore?.confirmed?.revision ?? 0,
    tombstone: fenceBefore?.tombstone?.reason ?? null,
  };
  // The read itself is left exactly as it came back: it already knows whose
  // it was (see OwnerScopedLoadError), and an abandonment already belongs to
  // nobody. Re-interpreting either here would overwrite what the layer that
  // resolved the identity actually established.
  const loaded = await loadProfile();
  const token = loaded.token;
  try {
    return await hydrateLoadedProfile(loaded, token, observedBefore);
  } catch (err) {
    // Everything above this line ran with `token` already fixed, so a failure
    // in it is this identity's — unless the identity is gone.
    //
    // The triangle: an already-scoped failure keeps the token it was raised
    // with; an abandonment whose token has genuinely been superseded stays
    // unscoped, because it belongs to nobody; and an abandonment for an owner
    // who is STILL current — same uid, same epoch, merely a browser that can
    // no longer vouch for its own data — is their own failure and is named as
    // theirs, or the screen sits on a spinner it can never leave.
    if (isOwnerScopedLoadError(err)) throw err;
    if (!isTokenOwnerStillCurrent(token)) throw new OwnerNotReadyError();
    throw new OwnerScopedLoadError(token, err);
  }
}

async function hydrateLoadedProfile(
  loaded: LoadedProfile,
  token: OwnerToken,
  observedBefore: LoadFence,
): Promise<ProfileHydration> {
  // BEFORE ensureScope, which mutates module-global coordinator state — the
  // in-memory field intents, the unwritten-confirmation repair marker, the
  // last load source, the skill ops. Running it for a superseded owner
  // switches the coordinator's scope back and discards the CURRENT owner's
  // in-flight bookkeeping, and the lock branch below discovering the problem
  // afterwards does not put any of it back.
  if (!isTokenOwnerStillCurrent(token)) throw new OwnerNotReadyError();
  ensureScope(token);
  const reconciled = await withProfileLock(
    token,
    () => reconcileLoadedProfile(loaded, token, observedBefore),
  );
  if (reconciled.ok) return reconciled.value;
  // SUPERSEDED is not "we could not serialize" — it is "this read belongs to
  // an owner who is gone". Falling through to the snapshot below would read
  // the CURRENT envelope, which is the new owner's, and hand it back paired
  // with the old owner's token; the caller's own generation check may still
  // say U1, and it would paint U2's profile. Nothing is read and nothing is
  // returned: the caller sees a read that did not settle, which is the truth.
  // A merely-unconfirmed realm ('abandoned') keeps the snapshot fallback —
  // that is this owner's own failure and every read below returns blank for
  // it anyway.
  // BOTH owner failures terminate here, before the snapshot below reads
  // anything. 'superseded' would read the new owner's envelope on the old
  // owner's behalf; 'abandoned' would report an unconfirmed realm's storage
  // as a confirmed blank, which is how "we could not verify who you are"
  // becomes "you have no profile". Only a fully valid token that simply has
  // no Web Locks may take the one-snapshot fallback.
  if (reconciled.reason === 'superseded' || reconciled.reason === 'abandoned') {
    throw new OwnerNotReadyError();
  }
  // Without serialization there is no safe way to merge this load into shared
  // state. The row itself is still reportable — reading is not the hazard —
  // but nothing is written and the caller is told the local copy is stale.
  //
  // ONE envelope read, and every field below comes out of it. Reading it
  // repeatedly would let another tab land between the reads and hand back a
  // document from one moment beside a pending entry from another; and the
  // revision has to be the one this baseline IS, never `loaded.revision` —
  // that belongs to the row the network just returned, which is precisely the
  // row this path could not merge in.
  const unmerged = readProfileSyncEnvelope();
  return {
    profile: workingCopy(unmerged?.confirmed ?? null, unmerged?.pending ?? null, null),
    baseProfile: unmerged?.confirmed?.profile ?? null,
    revision: unmerged?.confirmed?.revision ?? 0,
    source: loaded.source,
    token,
    hasPending: !!unmerged?.pending,
    conflictKeys: unmerged?.pending?.lockedKeys ?? [],
    conflicts: [],
    quarantineFailed: true,
  };
}

/** What this device believed about the row when a read was ISSUED. An answer
 *  is only news if the world has not moved past it while it was in flight. */
interface LoadFence {
  revision: number;
  tombstone: ProfileTombstone['reason'] | null;
}

/** The read-decide-write half of a hydrate. Caller holds the lock. */
function reconcileLoadedProfile(
  loaded: LoadedProfile,
  token: OwnerToken,
  observedBefore: LoadFence = { revision: 0, tombstone: null },
): ProfileHydration {
  const journal = readOutstandingOps();
  if (!journal.ok) {
    // The authority is unreadable. Writing the cloud row into the mirror now
    // would publish it to every other screen while this browser's own
    // unsent edits are invisible — deciding they do not exist because they
    // could not be read is exactly the downgrade this fails closed on.
    const env0 = readProfileSyncEnvelope();
    return {
      profile: workingCopy(env0?.confirmed ?? null, env0?.pending ?? null, null),
      baseProfile: env0?.confirmed?.profile ?? null,
      revision: env0?.confirmed?.revision ?? 0,
      source: loaded.source,
      token,
      hasPending: !!env0?.pending,
      conflictKeys: env0?.pending?.lockedKeys ?? [],
      conflicts: [],
      quarantineFailed: true,
    };
  }
  reconcileLedgerFromJournal(token);
  lastLoadSource = { scope: scopeOf(token), source: loaded.source };
  const env = readProfileSyncEnvelope();
  if (env?.pending) adoptPendingIntoLedger(env.pending);

  if (loaded.source === 'local-only') {
    // No backend was asked, so nothing here is confirmed. The working copy is
    // still the confirmed base PLUS any unsent edit — returning the base
    // alone would show the user a profile without the change they just made.
    const fallback = (loaded.profile as unknown as ProfileData | null) ?? readRawProfileMirror();
    const pending = env?.pending ?? null;
    return {
      profile: workingCopy(env?.confirmed ?? null, pending, fallback),
      // No backend was asked, so this device has confirmed NOTHING right now.
      // Reporting the envelope's old confirmed row here while saying revision
      // 0 would pair a real baseline with "no known row" — a write built from
      // it would look like it had a base and then claim it did not. Null and
      // 0 belong together: an explicitly unknown baseline.
      baseProfile: null,
      revision: 0,
      source: 'local-only',
      token,
      hasPending: !!pending,
      conflictKeys: pending?.lockedKeys ?? [],
      conflicts: [],
      quarantineFailed: false,
    };
  }

  {
    // A "there is no row" answer that was already out of date when it
    // arrived: another tab created one while this read was in flight.
    // Applying it would erase a row that exists and tombstone a live
    // account. The read is simply not news — report what is actually here.
    const current = readProfileSyncEnvelope();
    // What this answer would have to beat to be news. For a ROW, that is its
    // own revision: another tab landing revision 9 while this request for
    // revision 8 was in flight makes 8 history, and writing it to the mirror
    // and publishing it leaves the envelope at 9 with the screen showing 8.
    // For an ABSENCE there is no revision to compare, so the fence is what
    // this device believed when the request was issued.
    const mustBeat = loaded.source === 'cloud' ? loaded.revision : observedBefore.revision;
    if (current?.confirmed && current.confirmed.revision > mustBeat) {
      return {
        profile: workingCopy(current.confirmed, current.pending ?? null, null),
        baseProfile: current.confirmed.profile,
        revision: current.confirmed.revision,
        source: 'cloud',
        token,
        hasPending: !!current.pending,
        conflictKeys: current.pending?.lockedKeys ?? [],
        conflicts: [],
        quarantineFailed: false,
      };
    }
    // The mirror image: a ROW answer that arrived after this device was told
    // the account's row is gone. Another tab received the absence and wrote
    // the fence while this request was in flight, so `confirmed` is now null
    // and a revision comparison sees nothing — but adopting the old row here
    // clears the tombstone below (`remote` truthy ⇒ tombstone null) and
    // resurrects a profile the account no longer has, into the mirror every
    // other screen matches against.
    //
    // A tombstone that APPEARED or CHANGED since this read was issued
    // dominates it. One that was already there, unchanged, is handled by the
    // deleted/merged branches further down.
    const fenceNow = current?.tombstone ?? null;
    if (fenceNow && fenceNow.reason !== observedBefore.tombstone) {
      // The other tab wrote the fence; it may not have managed to remove the
      // raw mirror. Reporting a clean fence while a legacy-readable profile
      // still sits in the slot /results and /favorites read is the one thing
      // this early return must not do — retry the removal under this owner,
      // and say so if it still will not go.
      let stillReadable = fenceNow.rawQuarantined === false;
      if (stillReadable) {
        const cleared = writeLocalStorageJSON(STORAGE_KEYS.PROFILE, null, token);
        if (cleared) {
          writeEnvelope({
            v: 1,
            confirmed: null,
            pending: current?.pending ?? null,
            tombstone: { reason: fenceNow.reason, rawQuarantined: true },
          }, token);
          stillReadable = false;
        }
      }
      return {
        profile: null,
        baseProfile: null,
        revision: 0,
        source: loaded.source,
        token,
        hasPending: false,
        conflictKeys: [],
        conflicts: [],
        quarantineFailed: stillReadable,
      };
    }
  }
  const remote = loaded.source === 'cloud' ? (loaded.profile as unknown as ProfileData) : null;
  const revision = loaded.revision;
  let pending = env?.pending ?? null;
  let quarantineFailed = false;
  // A real row answers every open question about whether this account still
  // has one: any tombstone from a previous visit is stale, and a working copy
  // that was waiting to CREATE the row now has something to merge onto.
  let tombstone: ProfileTombstone | null = remote ? null : env?.tombstone ?? null;
  if (remote && pending?.deferredCreate) {
    pending = { ...pending, deferredCreate: false, legacy: false };
  }
  if (tombstone?.reason === 'merged') {
    // Still quarantined. Retry the removal if it did not land last time —
    // the dead account's profile must stop being served to /results.
    if (!tombstone.rawQuarantined) {
      const cleared = writeLocalStorageJSON(STORAGE_KEYS.PROFILE, null, token);
      tombstone = { reason: 'merged', rawQuarantined: cleared };
      quarantineFailed = !cleared;
    }
    writeEnvelope({ v: 1, confirmed: null, pending: null, tombstone }, token);
    return {
      profile: null,
      baseProfile: null,
      revision: 0,
      source: loaded.source,
      token,
      hasPending: false,
      conflictKeys: [],
      conflicts: [],
      quarantineFailed,
    };
  }

  // A durable answer to THIS pending write is consumed here, inside the same
  // critical section that reconciles everything else. It cannot wait for a
  // flush: Home returns the moment hydration reports a conflict and never
  // reaches one, so a receipt that survived a crash would leave the person
  // looking at a question they already answered, forever.
  if (pending) {
    const answered = applyPendingResolutions(pending, journal.value);
    if (answered !== pending) pending = answered;
  }

  if (pending?.legacy && remote) {
    // An unknown-base working copy meeting a real cloud row: the differences
    // cannot be attributed to either side, so they are LOCKED for the user to
    // resolve rather than uploaded or discarded.
    const desired = pending.desiredProfile as unknown as Record<string, unknown>;
    const remoteRec = remote as unknown as Record<string, unknown>;
    const differing = pending.dirtyKeys.filter((k) => !sameValue(desired[k], remoteRec[k]));
    pending = differing.length === 0
      ? null
      : {
        ...pending,
        baseRevision: revision,
        baseProfile: remote,
        dirtyKeys: differing,
        lockedKeys: differing,
        conflictRemote: remote,
      };
  } else if (pending?.legacy && loaded.source === 'cloud-absent') {
    // Nothing in the cloud to disagree with. It can be sent — but ONLY as a
    // complete create: a partial working copy (the school gate's one field)
    // would otherwise become the entire canonical row. Same gate as
    // stageProfilePatch, applied here because this path can turn an unsendable
    // entry into a sendable one without going through it.
    pending = isCompleteDocument(pending.desiredProfile)
      ? { ...pending, baseRevision: 0, legacy: false, deferredCreate: false, lockedKeys: [], conflictRemote: null }
      : { ...pending, baseRevision: 0, legacy: false, deferredCreate: true, lockedKeys: [], conflictRemote: null };
  } else if (pending && remote) {
    // NOT a blind re-base. Moving baseProfile to the remote row without
    // looking would make every key "remote == base" on the next attempt, so a
    // plain refresh would push this device's values straight over another
    // device's — the CAS check would pass, because the client would have
    // silently agreed to the overwrite on the user's behalf. Resolve each
    // unlocked key three ways first; only the genuinely safe ones move.
    pending = rebaseAgainstRemote(pending, remote, revision);
  } else if (!remote && env?.confirmed && loaded.source === 'cloud-absent') {
    // The row this browser knew about is GONE, and the cloud said so rather
    // than failing to answer. Recorded before anything is layered back on
    // top: without it the next visit cannot tell a deleted account from a
    // brand new one, and the create path puts the whole profile back.
    // Independent of whether an outbox entry exists — a crash can leave the
    // edits in the journal alone.
    if (pending) pending = { ...pending, legacy: true, baseRevision: 0 };
    tombstone = { reason: 'deleted', rawQuarantined: false };
  } else if (pending && !remote && env?.confirmed) {
    // The row this working copy belongs to is GONE. It is not re-created and
    // not thrown away; it stops being sendable, and the deletion is recorded
    // DURABLY — otherwise the next mount cannot tell this apart from a brand
    // new account and the create path would resurrect the row.
    pending = { ...pending, legacy: true, baseRevision: 0 };
    tombstone = { reason: 'deleted', rawQuarantined: false };
  } else if (!env) {
    // A browser that predates this coordinator: a raw mirror and no envelope.
    const mirror = readRawProfileMirror();
    if (mirror && !remote) {
      // Nothing in the cloud to disagree with — the mirror is an unsynced
      // profile. Sendable only if it is a COMPLETE document; otherwise it
      // waits for the home form to finish it (deferredCreate).
      pending = {
        mutationId: newMutationId(),
        baseRevision: 0,
        baseProfile: mirror,
        desiredProfile: mirror,
        dirtyKeys: Object.keys(mirror).filter(isProfileKey),
        journalOpIds: [],
        journalPlan: {},
        keyVersions: {},
        skillAdditions: [],
        skillsReplaced: false,
        skillOps: [],
        additiveKeys: [],
        lockedKeys: [],
        conflictRemote: null,
        legacy: false,
        deferredCreate: !isCompleteDocument(mirror),
      };
    } else if (mirror && remote) {
      // Both exist and the mirror's base revision is UNKNOWN — there is no
      // way to tell "this device has unsynced edits" from "the cloud moved on
      // and this mirror is simply old". Uploading would clobber the cloud;
      // discarding would delete the user's work. Keep both, lock the
      // differences, and let the user decide.
      const differing = Object.keys(mirror).filter(isProfileKey).filter(
        (k) => !sameValue(
          (mirror as unknown as Record<string, unknown>)[k],
          (remote as unknown as Record<string, unknown>)[k],
        ),
      );
      if (differing.length > 0) {
        pending = {
          mutationId: newMutationId(),
          baseRevision: revision,
          baseProfile: remote,
          desiredProfile: { ...remote, ...pick(mirror, differing as ProfileKey[]) } as ProfileData,
          dirtyKeys: differing,
          // Versioned even though nothing recorded an operation for it. This
          // working copy predates the journal, so the pending instance plus
          // these versions is the ONLY durable identity the disagreement it
          // raises will ever have — without them the person could see the
          // conflict and never be able to answer it.
          keyVersions: Object.fromEntries(differing.map((k) => [k, versionOf(k)])),
          skillAdditions: [],
          skillsReplaced: false,
          skillOps: [],
          additiveKeys: [],
          lockedKeys: differing,
          conflictRemote: remote,
          legacy: true,
          deferredCreate: false,
          journalOpIds: [],
          journalPlan: {},
        };
      }
    }
  }

  const confirmed = remote ? { revision, profile: remote } : null;
  // Envelope FIRST and gated: a raw mirror advanced past an envelope that
  // still describes the old state is how a revision goes missing and a
  // confirmed save becomes invisible to the outbox.
  if (!writeEnvelope({ v: 1, confirmed, pending, tombstone }, token)) {
    return {
      profile: workingCopy(env?.confirmed ?? null, env?.pending ?? null, null),
      baseProfile: env?.confirmed?.profile ?? null,
      revision: env?.confirmed?.revision ?? 0,
      source: loaded.source,
      token,
      hasPending: !!env?.pending,
      conflictKeys: env?.pending?.lockedKeys ?? [],
      conflicts: [],
      quarantineFailed: true,
    };
  }
  // Everything the journal still holds — including operations that were
  // recorded but never staged (the tab closed inside the debounce, a stage
  // that could not be written). Leaving them out would show this user the
  // cloud row on top of an edit they made a moment ago, and mirror THAT to
  // /results — the reload data loss the journal exists to prevent.
  if (tombstone?.reason === 'deleted') {
    // Fenced. Nothing of the dead row is shown, nothing is sendable, and the
    // local copy comes out of the slot every other screen reads.
    const cleared = writeLocalStorageJSON(STORAGE_KEYS.PROFILE, null, token);
    const fenced: ProfileTombstone = { reason: 'deleted', rawQuarantined: cleared };
    const recorded = writeEnvelope({ v: 1, confirmed: null, pending, tombstone: fenced }, token);
    return {
      profile: null,
      baseProfile: null,
      revision: 0,
      source: loaded.source,
      token,
      hasPending: false,
      conflictKeys: [],
      conflicts: [],
      quarantineFailed: !cleared || !recorded,
    };
  }
  const staged = workingCopy(confirmed, pending, null);
  const journalKeys = [...new Set(
    journal.value.flatMap((op) => op.fields.map((f) => f.key)),
  )].filter(isProfileKey);
  // Fail closed on unreadable receipts, exactly like an unreadable journal:
  // planning from a partly-understood set of acknowledgements is how a base
  // silently reverts to a revision that is gone.
  const journalRebased = rebasedOps(journal.value);
  if (!journalRebased) {
    return {
      profile: workingCopy(env?.confirmed ?? null, env?.pending ?? null, null),
      baseProfile: env?.confirmed?.profile ?? null,
      revision: env?.confirmed?.revision ?? 0,
      source: loaded.source,
      token,
      hasPending: !!env?.pending,
      conflictKeys: env?.pending?.lockedKeys ?? [],
      conflicts: [],
      quarantineFailed: true,
    };
  }
  const journalPlan = planKeysFromJournal(journalRebased, journalKeys);
  const journalConflicts: string[] = [];
  let working = staged;
  for (const [key, plan] of journalPlan) {
    if (plan.kind === 'conflict') {
      // Two origins want different values for this field. It is not resolved
      // by whoever hydrated last; the user is asked.
      journalConflicts.push(key);
      continue;
    }
    working = { ...(working ?? ({} as ProfileData)), [key]: plan.value } as ProfileData;
  }
  const conflictKeys = [...new Set([...(pending?.lockedKeys ?? []), ...journalConflicts])];
  // What is actually in dispute, for the screen that will ask about it — and
  // for the answer, which names these very operations rather than whatever is
  // outstanding by the time the person clicks.
  const conflicts = conflictsFor(conflictKeys, journalPlan, pending, remote, revision);
  if (working) {
    quarantineFailed = !writeRawMirror(working, token);
  } else if (env?.confirmed && !remote) {
    // Recorded whether or not the removal below succeeds: a deleted row must
    // stay deleted across reloads, or the home form's create path would
    // resurrect it on the next visit.
    tombstone = { reason: 'deleted', rawQuarantined: true };
    // The cloud says the row is gone and there is no working copy to show.
    // The stale raw mirror MUST come out of the canonical slot: /results,
    // /favorites and /compare all read it, and leaving it there means they
    // keep rendering — and matching against — a profile that no longer
    // exists. An owner-gated exact removal, reported if it fails.
    quarantineFailed = !writeLocalStorageJSON(STORAGE_KEYS.PROFILE, null, token);
    if (quarantineFailed) {
      tombstone = { reason: 'deleted', rawQuarantined: false };
      writeEnvelope({ v: 1, confirmed, pending, tombstone }, token);
    }
  }
  if (pending) adoptPendingIntoLedger(pending);

  return {
    profile: working,
    baseProfile: confirmed?.profile ?? null,
    revision,
    source: loaded.source,
    // Unsent work the CALLER has to recover: a staged write, or an operation
    // left behind by a document that is gone (a closed tab, a reload inside
    // the autosave debounce). Operations this document recorded itself are
    // deliberately excluded — the live form still holds those edits and will
    // send them on its own, and flushing them here races its own save.
    // Unsent WORK, not leftover bytes: an operation whose planned value is
    // already what the row holds has nothing to send, however it got that way
    // — answered by a receipt, superseded, or landed under another mutation.
    hasPending: !!pending || journal.value.some((op) => (
      op.originId !== getJournalOriginId()
      && op.fields.some((f) => {
        const plan = journalPlan.get(f.key);
        if (plan?.kind !== 'value') return false;
        return !sameValue(plan.value, (remote as unknown as Record<string, unknown> | null)?.[f.key]);
      })
    )),
    token,
    conflictKeys,
    conflicts,
    quarantineFailed,
  };
}

/** Move a working copy onto a newer cloud row, key by key. Keys the other
 *  device also changed are LOCKED rather than silently rebased. */
function rebaseAgainstRemote(
  pending: ProfilePendingWrite,
  remote: ProfileData,
  revision: number,
): ProfilePendingWrite | null {
  const locked = new Set(pending.lockedKeys);
  const unlocked = pending.dirtyKeys.filter((k) => !locked.has(k));
  const resolution = resolveConflict({ ...pending, dirtyKeys: unlocked }, remote);
  const nextLocked = [...new Set([...pending.lockedKeys, ...resolution.conflictKeys as string[]])];
  const dirtyKeys = [...new Set([
    ...resolution.applyKeys as string[],
    ...nextLocked,
  ])];
  if (dirtyKeys.length === 0) return null; // everything already landed remotely
  const keep = pick(pending.desiredProfile, dirtyKeys as ProfileKey[]);
  return {
    ...pending,
    baseRevision: revision,
    baseProfile: remote,
    desiredProfile: { ...remote, ...keep, ...resolvedPatch(pending, resolution) } as ProfileData,
    dirtyKeys,
    lockedKeys: nextLocked,
    conflictRemote: nextLocked.length > 0 ? remote : null,
  };
}

// ---------------------------------------------------------------------------
// Staging a write
// ---------------------------------------------------------------------------

export interface StageOptions {
  /** Keys whose incoming value ADDS to the stored one rather than replacing
   *  it (only `skills` today). Without this, two devices importing different
   *  GitHub repos would each drop the other's skills. */
  additive?: readonly ProfileKey[];
  /** Set by the home form, which holds the complete canonical document and is
   *  therefore the only caller allowed to CREATE the row (expected_revision
   *  0). Every other caller holds a partial view. */
  allowCreate?: boolean;
}

/**
 * The only write path for the profile row.
 *
 * `desired` is the caller's full view of the document, but ONLY `keys` (plus
 * their bundle partners) is ever taken from it — a caller holding a stale
 * snapshot cannot clobber a field it did not touch, by construction.
 *
 * A staged edit LAYERS onto whatever is already unsent: the outbox has one
 * slot, and replacing its contents would drop the fields of an in-flight
 * write that has not been confirmed yet.
 */
export async function stageProfilePatch(
  desired: ProfileData,
  keys: readonly ProfileKey[],
  token: OwnerToken,
  opts: StageOptions = {},
): Promise<ProfileSaveResult> {
  const gate = ownerGate(token);
  if (gate) return gate;
  ensureScope(token);

  const effectiveKeys = expandBundles(keys);
  if (effectiveKeys.length === 0) return { status: 'blocked' };

  // A hydrate needs the network, so it cannot happen inside the critical
  // section below. Done first, unlocked, and its result re-read under the
  // lock like everything else.
  if (!readProfileSyncEnvelope()?.confirmed && !opts.allowCreate) {
    try {
      await hydrateProfile();
    } catch {
      return { status: 'blocked' };
    }
    if (!isOwnerTokenValid(token, token.uid)) return { status: 'abandoned' };
  }

  // EVERYTHING from here to the envelope/mirror write is one critical
  // section: it reads the shared envelope and journal, decides what to send
  // from what it read, and writes back. Two tabs interleaving those steps is
  // a lost update no server-side CAS can see.
  const prepared = await withSharedState(token, () =>
    prepareStagedWrite(desired, effectiveKeys, token, opts));
  if (!prepared.ok) return prepared.result;
  if ('result' in prepared.value) return prepared.value.result;
  return flushByMutation(prepared.value.mutationId, token);
}

type StagePrepared = { result: ProfileSaveResult } | { mutationId: string };

function prepareStagedWrite(
  desired: ProfileData,
  effectiveKeys: readonly ProfileKey[],
  token: OwnerToken,
  opts: StageOptions,
): StagePrepared {
  // The cache is rebuilt from the journal before anything reads it: another
  // tab's operations, and this tab's own from before a reload, are only there.
  if (!reconcileLedgerFromJournal(token)) {
    return { result: { status: 'device-failed', phase: 'stage' } };
  }
  let env = readProfileSyncEnvelope();
  let baseUnknown = false;
  let deferredCreate = false;
  if (!env?.confirmed && !opts.allowCreate) {
    // The hydrate already happened, unlocked, before this section.
    env = readProfileSyncEnvelope();
    if (!env?.confirmed) {
      // Still nothing confirmed. Two very different reasons:
      //   * there IS no backend (local-only). Refusing here would throw the
      //     edit away for a user who is simply offline, and the alternative —
      //     inventing revision 0 — would let the first reconnect create a row
      //     from a single field. Persist locally, mark the base as UNKNOWN,
      //     and never send it until a real load establishes one.
      //   * the backend confirmed there is no row (cloud-absent). Creating
      //     here is exactly the bug the server's incomplete-create guard also
      //     rejects: a one-field writer would make a mutilated row canonical.
      const source = lastLoadSource?.scope === scopeOf(token) ? lastLoadSource.source : null;
      if (source === 'local-only') {
        baseUnknown = true;
      } else if (source === 'cloud-absent') {
        // The backend answered: there is no row yet. A partial writer may not
        // create one (027 rejects an incomplete create, and it would make a
        // mutilated profile canonical), but refusing outright strands a brand
        // new user — the onboarding tour's campus choice would never persist
        // and the tour could never close. Stage it DURABLY, send nothing, and
        // let the first complete create carry it.
        deferredCreate = true;
      } else {
        return { result: { status: 'blocked' } };
      }
    }
  }

  const confirmed = env?.confirmed ?? null;
  // Repaired from any receipt that answered THIS pending write before it is
  // used for anything: an answer bound to the mutation has no op ids for the
  // plan to honour, so this is where it takes effect.
  const receiptOps = readOutstandingOps();
  if (!receiptOps.ok) return { result: { status: 'device-failed', phase: 'stage' } };
  const existing = applyPendingResolutions(env?.pending ?? null, receiptOps.value);
  const tombstone = env?.tombstone ?? null;
  if (existing) adoptPendingIntoLedger(existing);
  // A row this browser knows was DELETED is not recreated by an ordinary
  // save, even one that carries a complete document: the create path would
  // silently undo the deletion. Only an explicit recreate clears it.
  if (tombstone?.reason === 'deleted' && !confirmed) {
    return { result: { status: 'missing', reason: 'absent' } };
  }
  if (tombstone?.reason === 'merged') {
    return { result: { status: 'missing', reason: 'merged_away' } };
  }

  // The base is reconstructed from each field's FROZEN intent, not from
  // whatever the envelope holds now. Two tabs share this envelope: tab B may
  // already have saved `major = Physics` at revision 8 while tab A's edit
  // started from `CS` at revision 7. Taking the envelope's current values as
  // the base would send A's edit as if it had been made against Physics — the
  // server's CAS check would pass, because the CLIENT had silently agreed to
  // the overwrite. Using the frozen base makes it a conflict, which is what
  // it is.
  const frozen = stagedIntentBase(effectiveKeys, existing, confirmed);
  const baseRevision = frozen.revision;
  const baseProfile = frozen.profile ?? existing?.baseProfile ?? confirmed?.profile ?? desired;
  const working = existing?.desiredProfile ?? confirmed?.profile ?? desired;

  // A create IS the whole document (there is nothing to merge onto); every
  // other write is strictly the touched keys, layered on what is already
  // unsent.
  // A create is the whole document. When a deferred partial (the school gate
  // on a brand-new account) is already staged, the create UNIONS with it
  // rather than replacing it — the campus the user picked in the tour has to
  // reach the row the home form is about to create.
  // `baseRevision === 0` means the edit was made before this device knew of
  // any row — NOT that no row exists. If one has been confirmed since, this
  // is a patch onto it; sending the whole document would push every
  // untouched field of this form over whatever that row holds.
  const creating = !confirmed;
  const isCompleteCreate = !!opts.allowCreate && creating && baseRevision === 0 && !baseUnknown
    && isCompleteDocument(desired);
  if (opts.allowCreate && creating && baseRevision === 0 && !baseUnknown && !isCompleteCreate) {
    // Home asked to create but the document it holds is not complete. The
    // server would reject it (incomplete_create); saying so here is the same
    // answer without the round trip.
    return { result: { status: 'blocked' } };
  }
  const stagedKeys = (isCompleteCreate
    ? (Object.keys(desired).filter(isProfileKey) as ProfileKey[])
    : effectiveKeys);
  const dirtyKeys = [...new Set([...(existing?.dirtyKeys ?? []), ...stagedKeys as string[]])];
  const next = { ...working, ...pick(desired, stagedKeys) } as ProfileData;

  // Re-editing a locked key IS the user choosing their own value: it unlocks.
  // Everything they did not touch stays locked and un-sendable.
  const stagedSet = new Set(stagedKeys as string[]);
  const lockedKeys = (existing?.lockedKeys ?? []).filter((k) => !stagedSet.has(k));

  // The per-key mutation versions are frozen HERE, at stage time, and travel
  // with the write. Reading the live counters when the request is finally
  // issued would let an edit made in between be treated as part of this
  // write, and its confirmation would then mark that newer edit as saved.
  markProfileFieldsDirty(stagedKeys, token);
  const keyVersions: Record<string, number> = { ...(existing?.keyVersions ?? {}) };
  for (const key of dirtyKeys) keyVersions[key] = versionOf(key);

  // Additive semantics come from the recorded OPERATION, not from a caller
  // flag: `skills` is additive only while every change to it since the last
  // confirmation was an import. One manual edit (which includes a deletion)
  // turns the whole list back into the intent, permanently for this write.
  const opState = skillOpsFor(token);
  const stagedOps = dirtyKeys.includes('skills') ? [...opState.ops] : [];
  const skillsAdditive = stagedOps.length > 0 && !skillsAreReplaced(stagedOps);
  const skillAdditions = skillsAdditive ? additionsOf(stagedOps) : [];
  const additiveKeys = [
    ...new Set([
      ...(existing?.additiveKeys ?? []).filter((k) => k !== 'skills'),
      ...(opts.additive ?? []).filter((k) => k !== 'skills') as string[],
      ...(skillsAdditive ? ['skills'] : []),
    ]),
  ];

  // What the JOURNAL says these fields should become — resolved per key,
  // per origin. A field two tabs disagree about is locked HERE, before any
  // request: sending one tab's value while the other's operation sits
  // unacknowledged in the journal is the silent overwrite this design exists
  // to remove.
  const outstanding = outstandingOpsForKeys(dirtyKeys);
  if (!outstanding.ok) return { result: { status: 'device-failed', phase: 'stage' } };
  const outstandingRebased = rebasedOps(outstanding.value);
  if (!outstandingRebased) return { result: { status: 'device-failed', phase: 'stage' } };
  const outstandingById = new Map(outstanding.value.map((op) => [op.opId, op]));
  const plans = planKeysFromJournal(outstandingRebased, dirtyKeys);
  // A SET: one operation carrying three fields is reached once per field,
  // and every settle path (ack, abandon, survivor) treats these as the ops
  // this write owns — a duplicate id would be acknowledged twice.
  const journalOpIds = new Set<string>();
  const journalPlan: Record<string, string[]> = {};
  const journalConflicts: string[] = [];
  const planned = { ...next } as unknown as Record<string, unknown>;
  const plannedBase = { ...baseProfile } as unknown as Record<string, unknown>;
  let plannedRevision = baseRevision;
  for (const [key, plan] of plans) {
    for (const id of plan.opIds) journalOpIds.add(id);
    if (plan.kind === 'conflict') { journalConflicts.push(key); continue; }
    journalPlan[key] = plan.opIds;
    planned[key] = plan.value;
    plannedBase[key] = plan.baseValue;
    plannedRevision = Math.min(plannedRevision, plan.baseRevision);
  }

  // The ancestry group of everything planned, as it stands RIGHT NOW, under
  // the lock. An operation's ancestor may hold fields this write never
  // touches (a college switch whose major is still locked), and the answer to
  // this request can only settle what the request itself captured — so the
  // group has to be captured here rather than rebuilt from whatever is
  // outstanding when the response lands.
  const everything = readOutstandingOps();
  if (!everything.ok) return { result: { status: 'device-failed', phase: 'stage' } };
  const related = new Map<string, Set<string>>();
  for (const op of everything.value) {
    // An answer belongs with what it answers: the receipt and the operations
    // it covers are settled together or not at all.
    for (const ancestor of [...(op.supersedes ?? []), ...(op.resolves ?? [])]) {
      (related.get(op.opId) ?? related.set(op.opId, new Set()).get(op.opId)!).add(ancestor);
      (related.get(ancestor) ?? related.set(ancestor, new Set()).get(ancestor)!).add(op.opId);
    }
  }
  const knownIds = new Set(everything.value.map((op) => op.opId));

  // Ownership of any EXACT pending-resolution receipt the repair attached to
  // the entry this write replaces, seeded HERE — before the ancestry closure
  // and before the nothing-to-say short circuit below.
  //
  // Both orderings matter. A pending-only "use the other version" has desired
  // already equal to the row, so it takes the no-request path: a merge placed
  // after that never runs and the receipt stays outstanding forever. And a
  // receipt that ALSO names op-backed keys has to enter the closure as a seed,
  // or the ancestors it answers are neither captured nor settled with it, and
  // the two can diverge and revive independently.
  //
  // Only the exact tuples the repair matched, and only for keys this write is
  // staging: never a stale receipt, an unmatched key, or an unrelated op.
  const inheritedPlan: Record<string, string[]> = {};
  const inheritedIds: string[] = [];
  if (existing) {
    for (const key of dirtyKeys) {
      for (const id of existing.journalPlan[key] ?? []) {
        const op = outstandingById.get(id);
        if (!op || op.mode !== 'resolve') continue;
        if (op.resolvesPending?.keyVersions[key] === undefined) continue;
        if (!knownIds.has(id)) continue;
        (inheritedPlan[key] ??= []).push(id);
        inheritedIds.push(id);
      }
    }
  }
  for (const [key, ids] of Object.entries(inheritedPlan)) {
    journalPlan[key] = [...new Set([...(journalPlan[key] ?? []), ...ids])];
  }
  const seededIds = [...new Set([...journalOpIds, ...inheritedIds])];

  const captured = new Set(seededIds);
  const frontier = [...seededIds];
  while (frontier.length > 0) {
    const id = frontier.pop()!;
    for (const next of related.get(id) ?? []) {
      if (knownIds.has(next) && !captured.has(next)) {
        captured.add(next);
        frontier.push(next);
      }
    }
  }

  // Keys whose planned value is ALREADY what the row holds have nothing to
  // say. Sending them would be a request whose only possible answer is
  // "unchanged" — and for an answered conflict where the person took the
  // other device's version, that is every key in the write. The operations
  // behind them are still settled, right here, without a round trip.
  const lockedNow = new Set([...lockedKeys, ...journalConflicts]);
  const sendable = dirtyKeys.filter((k) => !lockedNow.has(k));
  const confirmedRec = (confirmed?.profile ?? null) as unknown as Record<string, unknown> | null;
  const nothingToSay = !!confirmed && sendable.length > 0 && sendable.every(
    (k) => sameValue((planned as Record<string, unknown>)[k], confirmedRec?.[k]),
  );
  if (nothingToSay) {
    // Only the operations that are ENTIRELY about those keys: one that also
    // touches a field still in dispute is not finished with.
    const settledKeys = new Set(sendable);
    const byIdAll = new Map(everything.value.map((op) => [op.opId, op]));
    const settleIds = finishedClosures(
      captured,
      byIdAll,
      (confirmedRec ?? {}) as Record<string, unknown>,
      (key) => (settledKeys.has(key)
        ? { known: true, value: (planned as Record<string, unknown>)[key] }
        : { known: false }),
    );
    const remainingKeys = dirtyKeys.filter((k) => !settledKeys.has(k));
    const survivor: ProfilePendingWrite | null = remainingKeys.length === 0 ? null : {
      ...(existing ?? {
        mutationId: newMutationId(),
        baseRevision,
        baseProfile: baseProfile as ProfileData,
        desiredProfile: planned as unknown as ProfileData,
        keyVersions,
        skillAdditions: [],
        skillsReplaced: false,
        skillOps: [],
        additiveKeys: [],
        conflictRemote: null,
        legacy: false,
        deferredCreate: false,
        journalPlan: {},
      }),
      dirtyKeys: remainingKeys,
      lockedKeys: [...lockedNow].filter((k) => remainingKeys.includes(k)),
      journalOpIds: [...captured].filter((id) => !settleIds.includes(id)),
    };
    // ORDER MATTERS, and this path has no network to fall back on. For a
    // pending-only "use the other version" the receipt is the ONLY durable
    // proof the person ever answered: settling it first and then failing to
    // write the envelope leaves the outbox still locked with the proof gone,
    // and the next reload asks a question that was already answered.
    //
    // So the repair lands first — envelope, then the mirror every other
    // screen reads — and only once both have verifiably stuck is the proof
    // retired. A failure before that point returns device-failed with the
    // receipt intact, which is exactly what a retry or a reload needs.
    if (!writeEnvelope({ v: 1, confirmed, pending: survivor, tombstone: env?.tombstone ?? null }, token)
      || !writeRawMirror(workingCopy(confirmed, survivor, null) ?? (planned as unknown as ProfileData), token)) {
      return { result: { status: 'device-failed', phase: 'stage' } };
    }
    if (settleIds.length > 0 && !settleJournalOps(settleIds, token)) {
      // The answer is applied and on screen; only the housekeeping failed.
      // The receipt stays outstanding and settling it again is idempotent.
      return { result: { status: 'device-failed', phase: 'confirm' } };
    }
    for (const key of sendable) fieldIntents.delete(key);
    if (survivor && survivor.lockedKeys.length > 0) {
      // Part of the question is answered and the rest is not. Reporting a
      // clean save here would take the remaining disagreement off the screen
      // while it is still unresolved and still unsent.
      return {
        result: {
          status: 'conflict',
          revision: confirmed!.revision,
          remote: survivor.conflictRemote ?? confirmed!.profile,
          confirmed: { revision: confirmed!.revision, profile: confirmed!.profile },
          conflictKeys: survivor.lockedKeys,
          conflicts: conflictPayload(
            survivor.lockedKeys,
            survivor,
            survivor.conflictRemote ?? confirmed!.profile,
            confirmed!.revision,
          ),
        },
      };
    }
    return {
      result: {
        status: 'already-saved',
        revision: confirmed!.revision,
        profile: confirmed!.profile,
      },
    };
  }

  const pending: ProfilePendingWrite = {
    mutationId: newMutationId(),
    baseRevision: plannedRevision,
    baseProfile: plannedBase as unknown as ProfileData,
    desiredProfile: planned as unknown as ProfileData,
    dirtyKeys,
    journalOpIds: [...captured],
    journalPlan,
    keyVersions,
    skillAdditions,
    skillsReplaced: skillsAreReplaced(stagedOps),
    skillOps: stagedOps,
    additiveKeys,
    lockedKeys: [...new Set([...lockedKeys, ...journalConflicts])],
    conflictRemote: lockedKeys.length > 0 ? existing?.conflictRemote ?? null : null,
    // "base unknown" survives until a real load resolves it: either it stays
    // (this device is still offline) or hydrateProfile turns it into a
    // legacy-recovery conflict against whatever the cloud actually holds.
    legacy: baseUnknown || ((existing?.legacy ?? false) && lockedKeys.length > 0),
    // Cleared the moment a COMPLETE create is staged over it: at that point
    // the deferred fields are part of a row the server will accept.
    deferredCreate: isCompleteCreate ? false : (deferredCreate || (existing?.deferredCreate ?? false)),
  };

  // The envelope FIRST, and only if it verifiably landed does the optimistic
  // mirror follow: a raw mirror showing an edit with no outbox entry behind
  // it is an edit that will never be sent and never be reported as unsent.
  if (!writeEnvelope({ v: 1, confirmed, pending, tombstone }, token)) {
    recordUnstaged(desired, stagedKeys, opts, token);
    return { result: { status: 'device-failed', phase: 'stage' } };
  }
  if (!writeRawMirror(next, token)) {
    recordUnstaged(desired, stagedKeys, opts, token);
    return { result: { status: 'device-failed', phase: 'stage' } };
  }
  consumeUnstaged(stagedKeys, token);

  return { mutationId: pending.mutationId };
}

/**
 * Explicit conflict resolution. 'local' re-stages the user's own values
 * against the CURRENT revision; 'cloud' drops them and keeps what the other
 * device wrote. Nothing else can unlock a conflicted key.
 */
/**
 * One immutable answer to one shown disagreement.
 *
 * Every part is required, and they travel together. A shape where the
 * rendered question is optional is one where a click can be resolved against
 * whatever happens to be outstanding by then — which is how a person's answer
 * about ECE-versus-Physics silently decides a third value neither of them
 * ever saw.
 */
/**
 * One published question, as one indivisible capability.
 *
 * The parts used to travel separately — the view, the rendered question and
 * the document defining "mine" were three independently supplied values — and
 * nothing checked that they described the same screen. A currently-valid U2
 * view combined with a U1 document is an answer the owner check waves through,
 * because the owner it checks IS current; it is the VALUE that belongs to
 * somebody else. Fusing them removes the mismatch from the type rather than
 * guarding against it, and the local value is derived rather than supplied.
 */
export interface ProfileConflictPrompt {
  readonly promptId: string;
  /** The view this question was published for. Its token is the origin: an
   *  answer belongs to the identity that was SHOWN the conflict, never to
   *  whoever owns the browser when the button is clicked. */
  readonly originView: ProfileViewSnapshot;
  /** The disagreement AS RENDERED — the exact candidate values, provenance
   *  and operation ids the prompt named. */
  readonly conflicts: readonly ProfileConflict[];
}

let promptSeq = 0;

/** Publishes a question against the view it is about. Frozen together. */
export function makeConflictPrompt(
  originView: ProfileViewSnapshot,
  conflicts: readonly ProfileConflict[],
): ProfileConflictPrompt {
  promptSeq += 1;
  return deepFreeze({
    promptId: `prompt-${promptSeq}-${originView.viewId}`,
    originView,
    conflicts: conflicts.map((c) => frozenCopy(c)),
  });
}

/**
 * The same question, about fewer fields — what a per-field control answers.
 *
 * Keeps the promptId and the origin view, so a narrowed answer carries exactly
 * the authority the whole one did and cannot be assembled from anything else.
 */
export function narrowConflictPrompt(
  prompt: ProfileConflictPrompt,
  keys: readonly string[],
): ProfileConflictPrompt {
  const wanted = new Set(keys);
  return deepFreeze({
    promptId: prompt.promptId,
    originView: prompt.originView,
    conflicts: prompt.conflicts.filter((c) => wanted.has(c.key)),
  });
}

/**
 * Whether an action may be taken under a prompt: the same accepted view, the
 * same identity, at the same revision.
 *
 * An ordinary edit (`withRenderedProfile`) keeps `viewId` and is therefore
 * still the same capability. A newly accepted base mints a new `viewId` and is
 * a different one — even for the same uid at a deceptively equal revision,
 * because what the answer would be measured against has changed underneath it.
 */
function sameViewAuthority(
  originView: ProfileViewSnapshot,
  actionView: ProfileViewSnapshot,
): boolean {
  return originView.viewId === actionView.viewId
    && originView.token.uid === actionView.token.uid
    && originView.token.epoch === actionView.token.epoch
    && originView.identityGeneration === actionView.identityGeneration
    && originView.revision === actionView.revision;
}

export interface ConflictAnswer {
  /** The question that was published, whole. */
  readonly prompt: ProfileConflictPrompt;
  /** The view the person was acting on when they answered — the same accepted
   *  view as the prompt's, possibly carrying a newer rendered document. What
   *  "mine" means is read from THIS, never from a caller-supplied document:
   *  the values in dispute may all belong to tabs that are gone, and the form
   *  on screen is the only place the user's own side is defined. */
  readonly actionView: ProfileViewSnapshot;
  readonly choice: 'local' | 'cloud';
}

export async function resolveProfileConflict(
  answer: ConflictAnswer,
): Promise<ProfileSaveResult> {
  const { prompt, actionView, choice } = answer;
  const rendered = prompt.conflicts;
  const token = prompt.originView.token;
  // FIRST, before the owner check and before anything reads or writes: an
  // action whose view is not the prompt's is not this question being answered,
  // whoever owns the browser. Checking the owner first would let a valid
  // current owner carry somebody else's value through.
  if (!sameViewAuthority(prompt.originView, actionView)) return { status: 'abandoned' };
  // The document the person could actually see, taken from the view that was
  // just proven to be this prompt's own.
  const observed = actionView.renderedProfile;
  // BEFORE ensureScope and before any read. A prompt retained from a previous
  // identity must not consult — let alone write — the current owner's data.
  if (!isTokenOwnerStillCurrent(token)) return { status: 'abandoned' };
  const keys = rendered.map((c) => c.key) as ProfileKey[];
  if (keys.length === 0) return { status: 'blocked' };
  const gate = ownerGate(token);
  if (gate) return gate;
  ensureScope(token);

  // The answer is written down FIRST, as one durable receipt naming every
  // operation it covers and what was decided for each field. From that moment
  // the disagreement is settled for every reader, on this tab and the next
  // one, whether or not anything else succeeds — sending the chosen value,
  // clearing the operations it answers, even this process surviving.
  //
  // Derived from the JOURNAL, not from the outbox: a tab that died before it
  // staged anything leaves conflicting operations and no pending write at
  // all, and the person still has to be able to answer them.
  const written = await withSharedState(token, () => writeResolutionReceipt(keys, choice, token, observed, rendered));
  if (!written.ok) return written.result;
  // The question moved on while it was on screen: every operation the prompt
  // named has since been answered, superseded or acknowledged. Applying the
  // choice now would send it as a clean patch against today's row — a value
  // the person chose over something that is no longer there, overwriting
  // whatever replaced it.
  if (written.value === 'stale') return { status: 'stale-conflict' };
  if (!written.value) return { status: 'device-failed', phase: 'stage' };
  const { desired } = written.value;

  // One ordinary send from here. For "use the other device's version" the
  // chosen value IS what the row already holds, so the write has nothing to
  // say and never reaches the network.
  return stageProfilePatch(desired, keys, token);
}

/**
 * Records one answer for every field asked about. Caller holds the lock.
 *
 * Returns the document the answer implies, or null if it could not be made
 * durable — in which case NOTHING has changed and the conflict still stands.
 */
/**
 * Applies any resolution receipt that answers THIS pending write.
 *
 * A conflict raised by an already-staged write lives in the outbox: the
 * operations behind it were captured into the pending entry when it went out,
 * so the answer has no op ids to name and binds itself to the mutation plus
 * the field versions it was asked about instead. Nothing else in the pipeline
 * knows how to honour that — the plan and the settle paths look for `resolves`
 * — so the pending write is repaired from the receipt here.
 *
 * Idempotent, and authoritative the moment the receipt exists: a crash between
 * appending it and updating the envelope leaves the answer on disk and the
 * outbox still locked, and the next read repairs it exactly as this one would.
 * Only the keys the receipt actually matched are touched; every other locked
 * or dirty key is left alone.
 */
/**
 * Whether `receipt` is the exact answer to `key` of `pending`.
 *
 * ONE matcher, used both to APPLY a receipt and to decide whether a prompt has
 * already been answered. Two copies of this rule drift: application rejects a
 * receipt whose recorded base does not match the row the question is about,
 * while a staleness check that compared only the tuple numbers would treat the
 * same receipt as an answer — and every legitimate click would return stale
 * forever with nothing to show for it.
 */
function receiptAnswersQuestion(
  receipt: JournalOp,
  key: string,
  question: { mutationId: string | null; keyVersion: number | null; revision: number; remote: unknown },
): boolean {
  const target = receipt.resolvesPending;
  if (!target || target.mutationId !== question.mutationId) return false;
  if (target.keyVersions[key] !== question.keyVersion) return false;
  if (receipt.baseRevision !== question.revision) return false;
  const field = receipt.fields.find((f) => f.key === key);
  if (!field) return false;
  const shownBase = field.base.present ? field.base.value : undefined;
  return sameValue(shownBase, question.remote);
}

/** The question as the CURRENT pending write defines it, for application. */
function receiptAnswersPendingKey(
  receipt: JournalOp,
  pending: ProfilePendingWrite,
  key: string,
): boolean {
  return receiptAnswersQuestion(receipt, key, {
    mutationId: pending.mutationId,
    keyVersion: pending.keyVersions[key] ?? null,
    revision: pending.baseRevision,
    remote: (pending.conflictRemote as unknown as Record<string, unknown> | null)?.[key],
  });
}

function applyPendingResolutions(
  pending: ProfilePendingWrite | null,
  ops: readonly JournalOp[],
): ProfilePendingWrite | null {
  if (!pending || pending.lockedKeys.length === 0) return pending;
  const desired = { ...(pending.desiredProfile as unknown as Record<string, unknown>) };
  const base = { ...(pending.baseProfile as unknown as Record<string, unknown>) };
  const resolved = new Set<string>();
  // The receipts that actually matched, per key. They have to travel with the
  // repaired write: the settle path acknowledges exactly the operations the
  // pending entry names, and a receipt left out of that list stays outstanding
  // after the save. The next reader then has no pending write to bind it to
  // and replays it as an ordinary value chain — resurrecting a choice that was
  // already applied and confirmed.
  const matchedReceipts = new Map<string, string[]>();
  let baseRevision = pending.baseRevision;
  for (const receipt of ops) {
    if (receipt.mode !== 'resolve') continue;
    const target = receipt.resolvesPending;
    if (!target || target.mutationId !== pending.mutationId) continue;
    for (const key of Object.keys(target.keyVersions)) {
      if (!pending.lockedKeys.includes(key)) continue;
      // The EXACT question that was asked, all of it — see the shared matcher.
      if (!receiptAnswersPendingKey(receipt, pending, key)) continue;
      const field = receipt.fields.find((f) => f.key === key)!;
      desired[key] = field.desired.present ? field.desired.value : undefined;
      // The row the person was shown, which is what the choice was made
      // against — not whatever the envelope holds by the time this runs.
      base[key] = field.base.present ? field.base.value : undefined;
      baseRevision = Math.max(baseRevision, receipt.baseRevision);
      resolved.add(key);
      const forKey = matchedReceipts.get(key) ?? [];
      if (!forKey.includes(receipt.opId)) forKey.push(receipt.opId);
      matchedReceipts.set(key, forKey);
    }
  }
  if (resolved.size === 0) return pending;
  const lockedKeys = pending.lockedKeys.filter((k) => !resolved.has(k));
  const dirtyKeys = [...new Set([...pending.dirtyKeys, ...resolved])];
  // Idempotent: repeated hydrates and flushes repair the same write, and a
  // duplicated id would be acknowledged twice.
  const journalPlan: Record<string, string[]> = { ...pending.journalPlan };
  for (const [key, ids] of matchedReceipts) {
    journalPlan[key] = [...new Set([...(journalPlan[key] ?? []), ...ids])];
  }
  const journalOpIds = [...new Set([
    ...pending.journalOpIds,
    ...[...matchedReceipts.values()].flat(),
  ])];
  return {
    ...pending,
    journalOpIds,
    journalPlan,
    desiredProfile: desired as unknown as ProfileData,
    baseProfile: base as unknown as ProfileData,
    baseRevision,
    dirtyKeys,
    lockedKeys,
    // Every disagreement answered: there is nothing left to hold a remote
    // snapshot for.
    conflictRemote: lockedKeys.length > 0 ? pending.conflictRemote : null,
    // …and the base is no longer unknown, even when only SOME fields were
    // answered. `legacy` means "these values were computed against a revision
    // nobody can name", and any exact receipt supplies exactly that: the row
    // the person was shown, at the revision it was shown at.
    //
    // It has to clear on a PARTIAL answer too. It is a whole-write flag, so
    // leaving it set while one field is still locked blocks the answered field
    // from ever being sent, and the next hydrate's legacy branch re-locks
    // every still-differing key — resurrecting the very disagreement the
    // person just settled. The fields that are still in dispute stay protected
    // by `lockedKeys`, which is per-key and is the right tool for it.
    legacy: false,
  };
}

/** Test-only view of the planner, so a mixed receipt's per-key behaviour can
 *  be asserted directly rather than inferred from a whole flush. */
export function planKeysFromJournalForTests(
  ops: readonly JournalOp[],
  keys: readonly string[],
) {
  return planKeysFromJournal(ops, keys);
}

/**
 * The current question, after applying and PERSISTING anything already
 * answered. Token-fenced, and the only refresh a UI may use.
 *
 * `readCurrentConflicts` is a plain synchronous read: it cannot take the lock,
 * so it cannot apply a resolution receipt another tab appended, and its
 * zero-op fallback will happily describe a pending write whose disagreement is
 * already settled. Refreshing through it re-renders the answered question and
 * every later click on it is stale again — the loop only breaks when some
 * unrelated hydrate happens to run.
 *
 * This takes the lock, repairs the pending write from any exact receipt,
 * writes the repair back, and then reports only what is genuinely still
 * locked. Keys with nothing behind them are simply absent.
 */
export async function refreshConflictQuestion(
  keys: readonly string[],
  token: OwnerToken,
): Promise<ProfileConflictRefresh> {
  // Before the first read, and the full gate: a retained handler from a
  // previous account must reach storage for nothing at all.
  if (!isOwnerTokenValid(token, token.uid)) return { status: 'abandoned' };
  ensureScope(token);
  type Repair =
    | { failed: 'journal' | 'envelope' | 'mirror' | 'settle' }
    | {
      failed: null;
      profile: ProfileData | null;
      baseProfile: ProfileData | null;
      revision: number;
      conflicts: ProfileConflict[];
      pendingKeys: string[];
      /** Journal-plan keys whose chosen value is not in the outbox at all —
       *  a journal-only disagreement that has been answered. They still have
       *  to be staged and sent, outside the lock. */
      planOwed: string[];
      /** This repair took the LAST lock off a write that is still owed. */
      unlocked: boolean;
    };
  /**
   * ONE owner-fenced locked snapshot: repair the journal and the mirror, then
   * describe what is durable from that same read. Called twice — once before
   * the network continuation and once after it — because the continuation can
   * change the envelope, the journal and the row underneath, and answering
   * from the pre-send read is how a settled question hides a collision the
   * send just found, and how an edit made during the round trip disappears.
   */
  const snapshot = (): Repair => {
    const env = readProfileSyncEnvelope();
    const answers = readOutstandingOps();
    if (!answers.ok) return { failed: 'journal' };
    // Fail closed on unreadable receipts exactly like an unreadable journal:
    // deciding what is finished from a partly-understood set of
    // acknowledgements is how an answer gets retired before it has landed.
    const rebased = rebasedOps(answers.value);
    if (!rebased) return { failed: 'journal' };
    const before = env?.pending ?? null;
    const applied = applyPendingResolutions(before, answers.value);
    const confirmed = env?.confirmed ?? null;
    // A key the repair moved onto the row itself has nothing left to send.
    // Leaving it dirty makes the flush below fire a patch whose only possible
    // answer is "unchanged" — and for "use the other version" that is every
    // key in the write. Only ever after a real repair: an ordinary refresh
    // must not go rewriting an outbox nobody asked it to touch.
    const outboxRow = (confirmed?.profile ?? null) as unknown as Record<string, unknown> | null;
    let repaired = applied;
    if (applied && applied !== before && outboxRow) {
      const desired = applied.desiredProfile as unknown as Record<string, unknown>;
      const owedNow = applied.dirtyKeys.filter(
        (k) => applied.lockedKeys.includes(k) || !sameValue(desired[k], outboxRow[k]),
      );
      if (owedNow.length !== applied.dirtyKeys.length) {
        repaired = owedNow.length === 0 ? null : { ...applied, dirtyKeys: owedNow };
      }
    }
    let working = workingCopy(confirmed, repaired, null);
    if (repaired !== before) {
      if (!writeEnvelope({
        v: 1,
        confirmed,
        pending: repaired,
        tombstone: env?.tombstone ?? null,
      }, token)) return { failed: 'envelope' };
    }
    const journalPlan = planKeysFromJournal(rebased, keys);
    const journalConflicts = [...journalPlan]
      .filter(([, plan]) => plan.kind === 'conflict')
      .map(([key]) => key);
    // A disagreement that lived only in the JOURNAL leaves its answer only in
    // the journal too: the winning value is in the plan, never in the outbox.
    // Reporting the confirmed row here would say the question is settled while
    // the value that won it has never left this browser — and nothing else
    // would ever come back for it.
    const confirmedRow = (confirmed?.profile ?? null) as unknown as Record<string, unknown> | null;
    const planOwed: string[] = [];
    for (const [key, plan] of journalPlan) {
      if (plan.kind !== 'value') continue;
      if (repaired?.dirtyKeys.includes(key)) continue;
      if (sameValue(plan.value, confirmedRow?.[key])) continue;
      planOwed.push(key);
      working = { ...(working ?? ({} as ProfileData)), [key]: plan.value } as ProfileData;
    }
    // The mirror is reconciled whether or not the envelope changed on THIS
    // pass. A retry after a half-finished repair finds the outbox already
    // correct and the mirror still showing the disputed value; skipping it
    // because "nothing changed here" leaves every other screen wrong for good.
    // A fenced row is left alone — its mirror is quarantined on purpose.
    if (!env?.tombstone) {
      if (working) {
        if (!sameValue(working, readRawProfileMirror())
          && !writeRawMirror(working, token)) return { failed: 'mirror' };
      } else if (readRawProfileMirror() !== null) {
        // Authoritative ABSENCE. There is no row and nothing pending, so the
        // legacy copy in the slot every other screen reads is describing a
        // profile that does not exist. Removing it is part of the answer, and
        // a removal that could not be verified is not a settled question.
        if (!writeLocalStorageJSON(STORAGE_KEYS.PROFILE, null, token)) {
          return { failed: 'mirror' };
        }
      }
    }
    // BOTH kinds. A disagreement between two tabs lives in the journal and
    // never reaches `lockedKeys`; reporting only the outbox would tell the
    // screen a live question had gone away, and the controls would come down
    // over a decision nobody made.
    const stillLocked = [...new Set([...(repaired?.lockedKeys ?? []), ...journalConflicts])]
      .filter((k) => keys.includes(k));
    const remote = (repaired?.conflictRemote ?? confirmed?.profile ?? null) as ProfileData | null;
    const revision = confirmed?.revision ?? repaired?.baseRevision ?? 0;
    // Receipts whose work is entirely reflected in what is durable now are
    // retired HERE — after both writes above have verifiably stuck, never
    // before. Envelope and mirror landing does NOT make the acknowledgement
    // land: the ids stay in the journal, they still count toward the cap, and
    // the caller is told so rather than being handed a clean success.
    const byId = new Map(rebased.map((op) => [op.opId, op]));
    const owed = new Set(repaired?.dirtyKeys ?? []);
    const confirmedRec = (confirmed?.profile ?? {}) as unknown as Record<string, unknown>;
    // The fields THIS repair confirmed, and only those. Everything else is
    // unknown to it — an edit that has not been staged into the outbox yet is
    // still owed even though no pending write names it, and treating "not in
    // dirtyKeys" as "confirmed" would settle its operation and delete the
    // person's unsent work.
    // Plan-owed keys are NOT confirmed. Their value is durable only in the
    // journal until staging lands, and retiring their closure here would
    // delete the only record of the choice before anything else holds it.
    const confirmedKeys = new Set(
      keys.filter((k) => !stillLocked.includes(k) && !owed.has(k) && !planOwed.includes(k)),
    );
    const finished = finishedClosures(
      byId.keys(),
      byId,
      confirmedRec,
      (key) => (confirmedKeys.has(key)
        ? { known: true, value: confirmedRec[key] }
        : { known: false }),
    );
    // Unconditional. An acknowledgement recorded by an earlier attempt whose
    // key removal failed is invisible to `finished` — readers already skip
    // acked ids — so nothing would ever rediscover it, and a settled prompt
    // would sit in the cap for good while every retry reported success.
    if (!settleJournalOps(finished, token)) return { failed: 'settle' };
    // A field this repair CONFIRMED is no longer an unsent edit. Leaving its
    // per-field intent behind pins the next edit on that field to the revision
    // the question was asked at — and the person's own next keystroke comes
    // back as a conflict with themselves.
    for (const key of confirmedKeys) fieldIntents.delete(key);
    return {
      failed: null,
      profile: working,
      baseProfile: (confirmed?.profile ?? null) as ProfileData | null,
      revision,
      conflicts: stillLocked.length === 0
        ? []
        : conflictsFor(stillLocked, journalPlan, repaired, remote, revision),
      pendingKeys: [...new Set([...(repaired?.dirtyKeys ?? []), ...planOwed])],
      planOwed,
      unlocked: repaired !== before
        && (before?.lockedKeys.length ?? 0) > 0
        && stillLocked.length === 0,
    };
  };
  const settled = await withSharedState(token, snapshot);
  if (!settled.ok) {
    // SUPERSEDED is somebody else's browser now; everything else is this
    // device's own failure and the caller has to be able to retry it.
    return settled.result.status === 'abandoned'
      ? { status: 'abandoned' }
      : { status: 'device-failed', phase: 'lock', retryable: true };
  }
  const repair = settled.value;
  if (repair.failed) return { status: 'device-failed', phase: repair.failed, retryable: true };
  // The repair took the last lock off a write the cloud still does not have.
  // Continuing it HERE — outside the lock, through the ordinary fenced flush —
  // is what makes an answer given in another tab actually reach the server
  // from this one. Without it the answer is applied locally and silently
  // never sent.
  // A journal-only answer has no outbox entry to flush: it is staged HERE,
  // from the working copy that came out of the lock, and its outcome is the
  // one this refresh reports. Without it the answer is applied to the screen
  // and silently never sent.
  let flushed: ProfileSaveResult | null = null;
  if (repair.planOwed.length > 0 && repair.profile) {
    flushed = await stageProfilePatch(
      repair.profile, repair.planOwed as ProfileKey[], token, { allowCreate: false },
    );
  } else if (repair.unlocked && repair.pendingKeys.length > 0) {
    flushed = await flushPendingProfileWrite(token);
  }
  // A local staging failure is not a settled question: nothing durable holds
  // the answer, and reporting 'settled' takes the controls off a decision that
  // can still be lost.
  if (flushed?.status === 'device-failed') {
    return { status: 'device-failed', phase: 'stage', retryable: true };
  }
  // THE POSTFLIGHT, and the only authority from here on. Everything the
  // caller is told — the working copy, the confirmed base, the revision, the
  // question and what is still owed — is re-derived from durable state as it
  // stands NOW, under the lock, after whatever the send did to it. `flushed`
  // survives as metadata about the send itself and is never read for any of
  // those fields.
  //
  // Continuation is deliberately NOT repeated: work this pass discovers is
  // reported as pending and belongs to the next attempt. One refresh, at most
  // one network call.
  const after = await withSharedState(token, snapshot);
  if (!after.ok) {
    return after.result.status === 'abandoned'
      ? { status: 'abandoned' }
      : { status: 'device-failed', phase: 'lock', retryable: true };
  }
  const final = after.value;
  if (final.failed) return { status: 'device-failed', phase: final.failed, retryable: true };
  const state: ProfileRefreshState = {
    profile: final.profile,
    baseProfile: final.baseProfile,
    revision: final.revision,
    pendingKeys: final.pendingKeys,
    flushed,
  };
  return final.conflicts.length === 0
    ? { status: 'settled', conflicts: [], ...state }
    : { status: 'current', conflicts: final.conflicts, ...state };
}

/**
 * The disagreement as it stands RIGHT NOW, for the given keys.
 *
 * The one place a caller can get a question it is allowed to answer: the same
 * payload the coordinator publishes, built from the same envelope and journal.
 * A UI that has been told its answer was stale calls this to show the current
 * question instead of guessing at one.
 */
export function readCurrentConflicts(
  keys: readonly string[],
  /** The identity asking. Preflighted BEFORE the first read: a retained
   *  handler from a previous account must reach storage for nothing at all,
   *  and a caller-side check is not a contract the API can rely on. */
  token: OwnerToken,
): ProfileConflict[] {
  // The FULL owner gate, not just uid/epoch currency. A token can match the
  // current owner while this browser's local realm is still blocked or
  // unconfirmed — mid account-switch, an unverifiable clear — and handing back
  // private conflict data then is a leak. Checked before the first read, so
  // the contract does not depend on every caller remembering to.
  if (!isOwnerTokenValid(token, token.uid)) return [];
  const env = readProfileSyncEnvelope();
  const pending = env?.pending ?? null;
  const remote = (pending?.conflictRemote ?? env?.confirmed?.profile ?? null) as ProfileData | null;
  // From THIS read. The row and the number that names it come out of one
  // envelope or they describe different moments.
  return conflictPayload(keys, pending, remote, env?.confirmed?.revision ?? pending?.baseRevision ?? 0);
}

/** Deep-equal for the plain values a row and a candidate hold. */
function sameCandidateSet(
  shown: readonly ProfileConflictCandidate[],
  now: readonly ProfileConflictCandidate[],
): boolean {
  if (shown.length !== now.length) return false;
  const key = (c: ProfileConflictCandidate) => JSON.stringify({
    v: c.value === undefined ? null : c.value,
    present: c.value !== undefined,
    l: c.lineage,
    // A SET: the same operations in a different enumeration order are the
    // same candidate. A different set is a different question.
    o: [...c.opIds].sort(),
  });
  const a = shown.map(key).sort();
  const b = now.map(key).sort();
  return a.every((x, i) => x === b[i]);
}

/**
 * Whether the question on screen is still the current unanswered one.
 *
 * Caller holds the lock. Everything is recomputed here — the row, the pending
 * instance, the live operations, the receipts that have already answered
 * something — and compared against what was rendered. Anything that does not
 * match exactly means the person answered a question that is gone.
 */
function sameQuestion(
  rendered: readonly ProfileConflict[],
  keys: readonly string[],
  ops: readonly JournalOp[],
  env: ProfileSyncEnvelope | null,
): boolean {
  // A caller that cannot say what it showed cannot prove anything about it.
  if (rendered.length === 0) return false;
  const shownKeys = new Set(rendered.map((c) => c.key));
  if (keys.some((k) => !shownKeys.has(k))) return false;
  const pending = env?.pending ?? null;
  const remote = (pending?.conflictRemote ?? env?.confirmed?.profile ?? {}) as unknown as Record<string, unknown>;
  const now = new Map(
    conflictPayload(
      rendered.map((c) => c.key),
      pending,
      remote as unknown as ProfileData,
      env?.confirmed?.revision ?? pending?.baseRevision ?? 0,
    ).map((c) => [c.key, c]),
  );
  // A receipt makes THIS prompt stale only when it answered THIS question —
  // the same operations, or the same pending instance. An older resolution
  // about different operations on the same field is a settled past
  // disagreement, and treating it as an answer here would make every later
  // question on that field permanently unanswerable.
  const receipts = ops.filter((op) => op.mode === 'resolve');
  const alreadyAnswered = (shown: ProfileConflict): boolean => receipts.some((receipt) => {
    if (!(shown.key in (receipt.decisions ?? {}))) return false;
    const shownOpIds = new Set(shown.candidates.flatMap((c) => c.opIds));
    if (shownOpIds.size > 0) {
      return (receipt.resolves ?? []).some((id) => shownOpIds.has(id));
    }
    // Zero-op: judged against the RENDERED question — its own mutation, key
    // version, revision and remote value — not against mutable current state.
    // Applying an answer clears `conflictRemote` once the last key is
    // settled, so a matcher that looked at current state would stop
    // recognising the very receipt that settled it, and an old tab's opposite
    // click would be accepted and overwrite the answer.
    //
    // Both sides of this comparison are frozen — the receipt on disk and the
    // question that was rendered — so nothing about the CURRENT outbox belongs
    // in it. Adding a "the pending write must still say the same numbers"
    // clause can only ever turn an answered question back into an unanswered
    // one, which is precisely the overwrite this check exists to stop; it can
    // never catch a case the exact tuple below misses. A stale receipt is
    // already refused there, on its own recorded revision and base.
    return receiptAnswersQuestion(receipt, shown.key, {
      mutationId: shown.mutationId,
      keyVersion: shown.keyVersion,
      revision: shown.remoteRevision,
      remote: shown.remote,
    });
  });
  for (const shown of rendered) {
    if (alreadyAnswered(shown)) return false;
    const current = now.get(shown.key);
    if (!current) return false;
    if (!sameValue(shown.remote, current.remote)) return false;
    if (shown.remoteRevision !== current.remoteRevision) return false;
    if (shown.mutationId !== current.mutationId) return false;
    if (!sameCandidateSet(shown.candidates, current.candidates)) return false;
    // A candidate naming no operations has no journal provenance at all — a
    // legacy working copy, a server-side disagreement. Its only durable
    // identity is the field version, and without one there is nothing to
    // prove freshness against.
    if (shown.candidates.some((c) => c.opIds.length === 0)) {
      if (shown.keyVersion === null || shown.keyVersion !== current.keyVersion) return false;
    }
  }
  return true;
}

function writeResolutionReceipt(
  keys: readonly ProfileKey[],
  choice: 'local' | 'cloud',
  token: OwnerToken,
  /** The document the person was looking at. Required: the values in dispute
   *  may all belong to tabs that are gone, and the form on screen is the only
   *  place "mine" is defined. */
  observed: ProfileData,
  /** The disagreement AS RENDERED. Required: an answer computed from whatever
   *  is outstanding at click time decides about things nobody was shown. */
  rendered: readonly ProfileConflict[],
): { desired: ProfileData } | null | 'stale' {
  const effective = expandBundles(keys);
  if (effective.length === 0) return null;
  const journal = readOutstandingOps();
  if (!journal.ok) return null;
  const env = readProfileSyncEnvelope();
  const confirmed = (env?.confirmed?.profile ?? {}) as unknown as Record<string, unknown>;
  const pendingDesired = (env?.pending?.desiredProfile ?? null) as unknown as Record<string, unknown> | null;

  // Everything still asking about these fields, whoever wrote it. A receipt
  // that named only this tab's operations would leave the other tab's asking
  // for the same field, and the disagreement would come straight back.
  const plans = planKeysFromJournal(journal.value, effective as string[]);
  const covered: string[] = [];
  const fields: JournalField[] = [];
  const decisions: Record<string, 'local' | 'cloud'> = {};
  const mine = getJournalLineageId();
  const result = { ...(env?.confirmed?.profile ?? {}) } as unknown as Record<string, unknown>;

  const live = new Set(journal.value.map((op) => op.opId));
  // Keys answered against the pending instance rather than against operations.
  const pendingVersions = new Map<string, number>();
  // ONE revision for the whole question. A prompt whose fields were read at
  // different moments cannot describe a single row, and a receipt built from
  // it would claim a state that never existed.
  const shownRevision = rendered[0]?.remoteRevision;
  if (rendered.some((c) => c.remoteRevision !== shownRevision)) return 'stale';
  // FRESHNESS, before anything is written or cleared: is this still the same
  // unanswered question? Recomputed from the envelope, the journal and the
  // resolution receipts already in it, and compared exactly.
  //
  // "One named operation still exists" is not enough. A candidate can be
  // partly replaced, another candidate can have appeared, the row can have
  // moved to a third value, the pending write can have been superseded, or
  // the question can already have been answered by a receipt whose cleanup
  // has not run. In every one of those the person is looking at a question
  // that no longer exists, and applying their choice sends it as a clean
  // patch over whatever is actually there now.
  if (!sameQuestion(rendered, effective as string[], journal.value, env)) return 'stale';
  for (const key of effective) {
    const shown = rendered.find((c) => c.key === key);
    // Required, not optional: an answer about a key nobody was shown is not
    // an answer at all.
    if (!shown) return 'stale';
    if (shown.candidates.every((c) => c.opIds.length === 0)) {
      // Zero-op question: its durable identity is the pending instance. A
      // rendered key with neither operations nor a version has no provenance
      // at all, and answering it would be a guess.
      if (shown.keyVersion === null || !env?.pending) return 'stale';
      pendingVersions.set(key, shown.keyVersion);
    }
    if (shown) {
      // Exactly what was on screen. An operation another tab appended while
      // the question was being asked was never part of it, and answering it
      // would be answering for something the person never saw.
      for (const candidate of shown.candidates) {
        for (const id of candidate.opIds) if (live.has(id)) covered.push(id);
      }
    } else {
      for (const op of journal.value) {
        if (op.fields.some((f) => f.key === key)) covered.push(op.opId);
      }
    }
    let value: unknown;
    if (choice === 'cloud') {
      // The value that was SHOWN, not whatever the row holds by the time the
      // click lands. "Use the other version" means the version they were
      // looking at; the freshness check above has already proved it is still
      // the current one, so these agree — and if they ever did not, sending
      // the click-time value would apply a decision about something else.
      // The freshness check above already proved this key was rendered, so
      // there is no click-time fallback to reach for.
      if (!shown) return 'stale';
      value = shown.remote;
    } else {
      // This device's value: what its OWN lineage last asked for, and failing
      // that (the operations came from a tab that is gone) whatever the
      // working copy on screen holds.
      const ownLatest = journal.value
        .filter((op) => op.lineage === mine && op.fields.some((f) => f.key === key))
        .sort((a, b) => a.seq - b.seq)
        .pop();
      const ownField = ownLatest?.fields.find((f) => f.key === key);
      const observedRec = observed as unknown as Record<string, unknown>;
      // The rendered action document is the authority for "mine", including
      // when the field is ABSENT from it — that is a deletion the person made,
      // not a gap to fill from somewhere else. Falling through to the journal
      // or the outbox here silently resurrects a value they removed, so the
      // only two outcomes are the document's own answer or a refusal.
      if (key in observedRec) {
        // What the person SELECTED, and it wins outright. This document's own
        // latest edit is not the same thing: they may be answering about two
        // other tabs' values, and the form they are looking at is the only
        // place "mine" is defined.
        value = observedRec[key];
      } else {
        // Absent from the document the person acted on. That is their answer:
        // the field is gone. Reaching for `ownField`, the plan or the outbox
        // here is how a deletion turns back into the value it replaced.
        void ownField;
        void plans;
        void pendingDesired;
        value = undefined;
      }
    }
    result[key] = value;
    fields.push({
      key,
      // The value that was SHOWN. Never the confirmed row read at write time:
      // the receipt is the durable record of a decision about ONE specific
      // state, and that is what the crash-repair matcher compares against.
      // `rendered` is required and freshness has already proved this key was
      // part of it, so there is nothing to fall back to — and nothing that
      // should be.
      base: { present: true, value: shown!.remote },
      desired: { present: true, value },
    });
    decisions[key] = choice;
  }

  const resolves = [...new Set(covered)];
  // Keys with no operation behind them are answered against the PENDING
  // instance instead: the conflict came from a write that was already staged,
  // so the outbox owns those operations and there are no ids to name. The
  // mutation plus the field versions it was asked about is the same durable
  // identity by another route.
  const pendingTarget = pendingVersions.size > 0 && env?.pending
    ? {
      mutationId: env.pending.mutationId,
      keyVersions: Object.fromEntries(pendingVersions),
    }
    : undefined;
  if (resolves.length === 0 && !pendingTarget) {
    // Nothing left to answer, by either route. NOT a licence to clear the
    // field intents and hand back a document — stageProfilePatch would send
    // that as a fresh, clean patch of the chosen value over whatever the row
    // has become, which is the person's old answer silently overwriting a
    // newer one.
    return 'stale';
  }
  const receipt = appendJournalOp({
    fields,
    // The revision the question was asked AT, so a replay after a crash knows
    // which row the person was looking at.
    baseRevision: shownRevision ?? env?.confirmed?.revision ?? 0,
    writer: DEFAULT_WRITER,
    mode: 'resolve',
    ...(resolves.length > 0 ? { resolves } : {}),
    ...(pendingTarget ? { resolvesPending: pendingTarget } : {}),
    decisions,
  }, token);
  if (!receipt) return null;
  for (const key of effective) fieldIntents.delete(key as string);
  return { desired: result as unknown as ProfileData };
}

/**
 * A cloud-confirmed state this browser could not record locally. Kept in
 * memory (localStorage is exactly what failed) so a retry redoes the LOCAL
 * write ONLY — the request already succeeded, and re-sending it would be a
 * save against a revision that has moved on.
 */
let unwrittenConfirmation: { scope: string; revision: number; profile: ProfileData } | null = null;




/** What the most recent load for this owner reported. 'local-only' is the one
 *  state where a partial writer may still persist: there is no server to
 *  patch against, so the alternative is silently dropping the edit. */
let lastLoadSource: { scope: string; source: LoadedProfile['source'] } | null = null;

/** Seeds the in-memory ledger from an outbox entry that outlived a reload.
 *  Without it the counters start at 0 while the entry remembers 3, and the
 *  first confirmation would compare two numbers that mean nothing to each
 *  other. Only keys the ledger has never seen are seeded — a live edit always
 *  wins over a persisted one. */
/**
 * Rebuilds the in-memory cache from the DURABLE journal. The map is never the
 * authority: a reload has no memory, and another tab's operations were never
 * in this process's. For a field several operations touch, the EARLIEST
 * frozen base wins — an edit chain is resolved against what the user started
 * from, not against the base of whichever operation happened to be read last.
 * Returns false when the journal cannot be read, which callers must treat as
 * "what is unsaved is unknown".
 */
function reconcileLedgerFromJournal(token: OwnerToken): boolean {
  ensureScope(token);
  const journal = readOutstandingOps();
  if (!journal.ok) return false;
  // Derived LAZILY, here, rather than written back into the operations: an
  // operation appended after any scan (appends do not take the lock) still
  // comes out correct, because its ancestry is followed the moment anything
  // reads it — in this document, in another tab, after a reload.
  const receipts = readRebaseReceipts();
  if (!receipts.ok) return false;
  const opsById = new Map(journal.value.map((op) => [op.opId, op]));
  // An operation another one explicitly REPLACES contributes nothing here
  // either. Rebuilding the cache from it would restore the base the user has
  // already answered — and the next send would go out against a revision they
  // have seen and rejected. Same rule as the plan; the two must agree, or the
  // cache and the journal describe different edits.
  const replaced = new Set(journal.value.flatMap((op) => op.supersedes ?? []));
  // …and an operation a receipt has ANSWERED contributes nothing for the
  // fields that were decided: its base belongs to a disagreement that is over.
  const answered = new Map<string, Set<string>>();
  for (const op of journal.value) {
    if (op.mode !== 'resolve') continue;
    for (const id of op.resolves ?? []) {
      const forKeys = answered.get(id) ?? new Set<string>();
      for (const k of Object.keys(op.decisions ?? {})) forKeys.add(k);
      answered.set(id, forKeys);
    }
  }
  for (const op of journal.value) {
    if (replaced.has(op.opId)) continue;
    const effective = effectiveOpBase(op, receipts.value, opsById);
    for (const field of effective.fields) {
      if (!isProfileKey(field.key)) continue;
      if (answered.get(op.opId)?.has(field.key)) continue;
      const existing = fieldIntents.get(field.key);
      // A receipt-derived base is the SERVER's word, not another edit's
      // opinion: it must win over a cached entry that predates it. The
      // ordinary "oldest base wins" rule below is about two local edits, and
      // applying it here is what leaves the cache at revision 1 while the plan
      // says 2 — the send then goes out expecting the lower of the two.
      const rebased = effective.baseRevision > op.baseRevision;
      if (existing && !rebased && existing.baseRevision <= effective.baseRevision) {
        existing.writers.add(op.writer);
        continue;
      }
      if (existing && rebased && existing.baseRevision > effective.baseRevision) {
        existing.writers.add(op.writer);
        continue;
      }
      fieldIntents.set(field.key, {
        baseValue: field.base.present ? field.base.value : undefined,
        baseRevision: effective.baseRevision,
        version: (existing?.version ?? 0) + 1,
        writers: new Set([...(existing?.writers ?? []), op.writer]),
        hasUnstaged: existing?.hasUnstaged ?? false,
        unstagedValue: existing?.unstagedValue,
        allowCreate: existing?.allowCreate ?? false,
      });
    }
  }
  return true;
}

function adoptPendingIntoLedger(pending: ProfilePendingWrite): void {
  // The skills OPERATION travels with the outbox entry, not just its result.
  // Without restoring it, a reload followed by an unrelated edit would re-stage
  // `skills` with additive semantics gone — and the next conflict would push
  // this device's whole list over the other one's, resurrecting whatever it
  // had deleted. The sticky `replaced` flag has to survive the same way.
  // Another tab (same uid, same epoch) may have staged an import this tab
  // never saw. Operations are merged by unique id — never by comparing two
  // per-tab counters, which have no common origin.
  if (skillOps && skillOps.scope === ledgerScope) {
    const seen = new Set(skillOps.ops.map((op) => op.opId));
    for (const op of pending.skillOps) if (!seen.has(op.opId)) skillOps.ops.push(op);
  } else {
    skillOps = { scope: ledgerScope ?? '', ops: [...pending.skillOps] };
  }
  const base = pending.baseProfile as unknown as Record<string, unknown>;
  for (const key of pending.dirtyKeys) {
    if (fieldIntents.has(key)) continue; // a LIVE edit always wins over a persisted one
    // The frozen base travels with the entry, so a recovered write is still
    // resolved three ways against what it was actually made from.
    fieldIntents.set(key, {
      baseValue: base[key],
      baseRevision: pending.baseRevision,
      version: pending.keyVersions[key] ?? 1,
      // A recovered entry has no writer of record; it belongs to whoever
      // flushes it next, which is the default lane.
      writers: new Set([DEFAULT_WRITER]),
      hasUnstaged: false,
      allowCreate: false,
    });
  }
}

/**
 * The disagreement behind a conflict RESULT, in the same shape hydrate
 * reports. A server collision has one local candidate (what this device tried
 * to send, and the operations that asked for it) against the row.
 */
function conflictPayload(
  keys: readonly string[],
  pending: ProfilePendingWrite | null,
  remote: ProfileData | null,
  /** The revision `remote` IS, from the same read or the same server outcome
   *  that produced it. Required: taking a second look at the envelope here
   *  would let a revision another tab confirmed a moment ago be stapled onto
   *  the row this payload actually describes — a pair that never existed, and
   *  the pair a receipt would go on to record as what the person was shown. */
  remoteRevision: number,
): ProfileConflict[] {
  const remoteRec = (remote ?? {}) as unknown as Record<string, unknown>;
  const journal = readOutstandingOps();
  const ops = journal.ok ? journal.value : [];
  // Operations a receipt has already decided. Only those are out of the
  // running: an old receipt about OTHER operations says nothing about this
  // question, and treating the whole key as answered would make every later
  // disagreement on it permanently unanswerable.
  // PER KEY. One operation carries every field its action changed, so a
  // receipt that answered it for `major` says nothing about the `college` half
  // of the same operation — that disagreement is still open and still has to
  // be askable.
  const answeredOps = new Map<string, Set<string>>();
  for (const op of ops) {
    if (op.mode !== 'resolve') continue;
    for (const decidedKey of Object.keys(op.decisions ?? {})) {
      const forKey = answeredOps.get(decidedKey) ?? new Set<string>();
      for (const id of op.resolves ?? []) forKey.add(id);
      answeredOps.set(decidedKey, forKey);
    }
  }
  const revision = remoteRevision;

  return keys.map((key) => {
    // Candidates come from the operations THEMSELVES: their own desired
    // values, their own lineages, and the complete set of ids asking for
    // each. Synthesizing one candidate out of the pending write's desired
    // document loses both — after a reload the value is whatever the outbox
    // collapsed to, and every operation gets relabelled with the current
    // document's lineage, which is exactly the provenance a person needs in
    // order to tell two tabs apart.
    const grouped = new Map<string, ProfileConflictCandidate>();
    for (const op of ops) {
      if (op.mode === 'resolve') continue;
      if (answeredOps.get(key)?.has(op.opId)) continue;
      const field = op.fields.find((f) => f.key === key);
      if (!field) continue;
      const value = field.desired.present ? field.desired.value : undefined;
      const groupKey = `${op.lineage}\u0000${stableStringify(value)}`;
      const held = grouped.get(groupKey);
      if (held) held.opIds.push(op.opId);
      else grouped.set(groupKey, { value, lineage: op.lineage, opIds: [op.opId] });
    }
    const candidates = [...grouped.values()];
    return {
      key,
      remote: remoteRec[key],
      remoteRevision: revision,
      mutationId: pending?.mutationId ?? null,
      // Durable provenance for a question with NO journal operations behind
      // it — a legacy working copy, a server-side disagreement. Only then;
      // otherwise the operation ids ARE the identity.
      keyVersion: candidates.length === 0 ? (pending?.keyVersions?.[key] ?? null) : null,
      candidates: candidates.length > 0
        ? candidates
        : (pending
          ? [{
            value: (pending.desiredProfile as unknown as Record<string, unknown>)[key],
            lineage: getJournalLineageId(),
            opIds: [],
          }]
          : []),
    };
  });
}

/**
 * The question for every key in dispute — whichever kind of disagreement it
 * is. Two tabs wanting different values is decided by the journal and carries
 * their candidates; this device against the row is decided by `conflictPayload`.
 *
 * ONE mapping, used by hydration and by the refresh, so the same disagreement
 * cannot be described two different ways depending on which path noticed it.
 */
function conflictsFor(
  conflictKeys: readonly string[],
  journalPlan: ReadonlyMap<string, KeyPlan>,
  pending: ProfilePendingWrite | null,
  remote: ProfileData | null,
  revision: number,
): ProfileConflict[] {
  const remoteRec = (remote ?? {}) as unknown as Record<string, unknown>;
  return conflictKeys.map((key) => {
    const plan = journalPlan.get(key);
    if (plan?.kind === 'conflict') {
      return {
        key,
        remote: remoteRec[key],
        remoteRevision: revision,
        mutationId: pending?.mutationId ?? null,
        keyVersion: fieldIntents.get(key)?.version ?? null,
        candidates: plan.candidates,
      };
    }
    // Locked by the SERVER rather than by two tabs disagreeing: this device
    // has one value and the row has another. Same shape, one candidate — and
    // it must still name the operations behind it, or an answer would cover
    // nothing and the lock would survive being answered.
    return conflictPayload([key], pending, remote, revision)[0];
  });
}

/** Re-sends the unsent working copy. Returns 'blocked' when there is nothing
 *  to flush, and never sends a locked key. */
export async function flushPendingProfileWrite(token: OwnerToken): Promise<ProfileSaveResult> {
  const gate = ownerGate(token);
  if (gate) return gate;
  ensureScope(token);
  // A row the cloud says is gone stays gone. Only an explicit recreate — a
  // person filling the form in again — may lift this, and that goes through
  // stageProfilePatch's own create path, not through a replay of whatever
  // was unsent when it vanished.
  const fence = readProfileSyncEnvelope()?.tombstone;
  if (fence?.reason === 'deleted') return { status: 'missing', reason: 'absent' };
  if (fence?.reason === 'merged') {
    // The account is dead. If its local copy is already out of the slot every
    // other screen reads, there is nothing left to do; if the removal did not
    // land last time, THIS is the repair — the fence must not short-circuit
    // past work that is still owed.
    if (fence.rawQuarantined) return { status: 'missing', reason: 'merged_away' };
    const repaired = await withSharedState(token, () => {
      const cleared = writeLocalStorageJSON(STORAGE_KEYS.PROFILE, null, token);
      return writeEnvelope({
        v: 1,
        confirmed: null,
        pending: null,
        tombstone: { reason: 'merged', rawQuarantined: cleared },
      }, token) && cleared;
    });
    if (!repaired.ok) return repaired.result;
    if (!repaired.value) return { status: 'device-failed', phase: 'confirm' };
    return { status: 'missing', reason: 'merged_away' };
  }
  // A local-write repair comes first and never goes near the network: the
  // cloud already has this state.
  if (unwrittenConfirmation && unwrittenConfirmation.scope === scopeOf(token)) {
    const { revision, profile } = unwrittenConfirmation;
    // One critical section: the outbox entry this repair writes back is read
    // INSIDE it. Reading first and writing later would let another tab stage
    // a newer edit in between, and this repair would put the older one back
    // over it. The revision is checked too — a confirmation older than what
    // is already recorded is not news.
    const repaired = await withSharedState(token, () => {
      const env = readProfileSyncEnvelope();
      const recorded = env?.confirmed;
      if (recorded && recorded.revision > revision) {
        // Something newer is already on record. The repair is moot — and the
        // CALLER must hear what is actually stored, not the stale revision
        // this repair was carrying: it is about to be shown on screen and
        // compared against by the next write.
        return { ok: true as const, revision: recorded.revision, profile: recorded.profile };
      }
      return recordConfirmed(revision, profile, env?.pending ?? null, token)
        ? { ok: true as const, revision, profile }
        : null;
    });
    if (!repaired.ok) return repaired.result;
    if (!repaired.value) return { status: 'device-failed', phase: 'confirm' };
    return {
      status: 'already-saved',
      revision: repaired.value.revision,
      profile: repaired.value.profile,
    };
  }
  // A stage that never reached storage has no outbox to flush — it has to be
  // staged again, from the per-field intents that failed. Per FIELD, so two
  // writers that both failed are both recovered: a single shared slot silently
  // dropped whichever one came first.
  const unstagedKeys = pendingUnstagedKeys();
  if (unstagedKeys.length > 0) {
    const env0 = readProfileSyncEnvelope();
    const base = env0?.pending?.desiredProfile ?? env0?.confirmed?.profile ?? readRawProfileMirror();
    const desired = { ...(base ?? {}) } as unknown as Record<string, unknown>;
    let allowCreate = false;
    for (const key of unstagedKeys) {
      const intent = fieldIntents.get(key as string);
      if (!intent) continue;
      desired[key as string] = intent.unstagedValue;
      allowCreate = allowCreate || intent.allowCreate;
    }
    return stageProfilePatch(
      desired as unknown as ProfileData,
      unstagedKeys,
      token,
      { allowCreate },
    );
  }
  const env = readProfileSyncEnvelope();
  if (!env?.pending) {
    // No outbox entry — but the journal is the authority, and it may still
    // hold an operation that never got staged (recorded, then the tab
    // closed). Send it from the values the journal itself carries rather
    // than waiting for the user to touch the field a second time.
    const journal = readOutstandingOps();
    if (!journal.ok) return { status: 'device-failed', phase: 'stage' };
    const keys = [...new Set(
      journal.value.flatMap((op) => op.fields.map((f) => f.key)),
    )].filter(isProfileKey);
    if (keys.length === 0) return { status: 'blocked' };
    const plan = planKeysFromJournal(journal.value, keys);
    const sendable = keys.filter((k) => plan.get(k)?.kind === 'value');
    if (sendable.length === 0) return { status: 'blocked' }; // all conflicted
    const base = env?.confirmed?.profile ?? readRawProfileMirror();
    const desired = { ...(base ?? {}) } as unknown as Record<string, unknown>;
    for (const key of sendable) {
      const entry = plan.get(key);
      if (entry?.kind === 'value') desired[key] = entry.value;
    }
    return stageProfilePatch(desired as unknown as ProfileData, sendable, token);
  }
  // A receipt bound to THIS pending write is authoritative the moment it
  // exists — including after a crash between appending it and updating the
  // envelope, which leaves the answer on disk and the outbox still locked.
  //
  // ONE critical section: the envelope and the receipts are read, the repair
  // is decided, and the result is written back without releasing the lock in
  // between. Reading first and writing later lets another tab rebase this
  // same mutation onto a newer row in the gap, and the repaired snapshot —
  // computed from what the envelope used to say — would be written straight
  // over it.
  const repaired = await withSharedState(token, () => {
    const now = readProfileSyncEnvelope();
    if (!now?.pending) return { ok: true as const, pending: null };
    const answers = readOutstandingOps();
    if (!answers.ok) return { ok: false as const, pending: null };
    const next = applyPendingResolutions(now.pending, answers.value);
    if (next === now.pending) return { ok: true as const, pending: now.pending };
    const written = writeEnvelope({
      v: 1,
      confirmed: now.confirmed,
      pending: next,
      tombstone: now.tombstone ?? null,
    }, token);
    return written
      ? { ok: true as const, pending: next }
      : { ok: false as const, pending: null };
  });
  if (!repaired.ok) return repaired.result;
  if (!repaired.value.ok) return { status: 'device-failed', phase: 'stage' };
  if (!repaired.value.pending) return { status: 'blocked' };
  adoptPendingIntoLedger(repaired.value.pending);
  return flushByMutation(repaired.value.pending.mutationId, token);
}

/**
 * Records a cloud-confirmed revision locally. `survivor` is whatever is still
 * unsent AFTER this confirmation — the mirror shows the confirmed row with
 * that survivor's edits back on top, so a newer edit staged while this
 * response was in flight is not wiped by it.
 *
 * Envelope first: if it does not land, the mirror is deliberately left alone.
 * A mirror advanced past an envelope that still describes the old state is
 * how a confirmed save becomes invisible to the outbox.
 */
function recordConfirmed(
  revision: number,
  profile: ProfileData,
  survivor: ProfilePendingWrite | null,
  token: OwnerToken,
): boolean {
  const confirmed = { revision, profile };
  if (!writeEnvelope({ v: 1, confirmed, pending: survivor, tombstone: null }, token)) {
    unwrittenConfirmation = { scope: scopeOf(token), revision, profile };
    return false;
  }
  const mirror = workingCopy(confirmed, survivor, null) ?? profile;
  if (!writeRawMirror(mirror, token)) {
    unwrittenConfirmation = { scope: scopeOf(token), revision, profile };
    return false;
  }
  unwrittenConfirmation = null;
  return true;
}

/** The keys still unsent after this confirmation: everything locked, plus
 *  anything a newer edit re-dirtied while the request was in flight. */
function survivorFor(
  pending: ProfilePendingWrite,
  sent: readonly string[],
  revision: number,
  profile: ProfileData,
): ProfilePendingWrite | null {
  const current = readProfileSyncEnvelope()?.pending ?? null;
  if (current && current.mutationId !== pending.mutationId) {
    // A newer edit already replaced this one in the outbox. It owns
    // everything from here; only its frame of reference moves.
    return { ...current, baseRevision: revision, baseProfile: profile };
  }
  const sentSet = new Set(sent);
  const remaining = pending.dirtyKeys.filter((k) => !sentSet.has(k));
  if (remaining.length === 0) return null;
  // The locked remainder is NOT confirmed by this response — it was never
  // sent. Dropping it here (pending: null) is how a partially-sendable write
  // loses the half the user still has to decide about.
  return {
    ...pending,
    baseRevision: revision,
    baseProfile: profile,
    desiredProfile: { ...profile, ...pick(pending.desiredProfile, remaining as ProfileKey[]) } as ProfileData,
    dirtyKeys: remaining,
  };
}

const MAX_AUTO_REBASES = 1;
const COORDINATOR_WRITE_ID = 'profile-coordinator';

/**
 * Sends whatever the outbox holds under `mutationId`. Serialized per owner:
 * a queued attempt re-reads the envelope when its turn actually comes, so a
 * closure captured before an earlier write landed can never send a patch
 * against a revision that has since moved — and an attempt that a newer edit
 * has superseded stands down instead of racing it.
 */
function flushByMutation(mutationId: string, token: OwnerToken): Promise<ProfileSaveResult> {
  return enqueuePrivateWrite(token, COORDINATOR_WRITE_ID, async () => {
    let currentId = mutationId;
    // Set when a conflict was resolved into "these collided, the rest is
    // still safe to send". The safe half goes out on the next pass; the
    // caller must still be told about the collision rather than seeing a
    // plain success.
    let deferredConflict: { keys: string[]; remote: ProfileData } | null = null;
    for (let rebases = 0; ; rebases += 1) {
      if (!isOwnerTokenValid(token, token.uid)) return { status: 'abandoned' } as ProfileSaveResult;
      const env = readProfileSyncEnvelope();
      const pending = env?.pending ?? null;
      if (!pending) return { status: 'blocked' } as ProfileSaveResult;
      if (pending.mutationId !== currentId) {
        // Superseded while queued. The newer entry has its own flush behind
        // this one and carries this write's fields (edits LAYER), so standing
        // down loses nothing and avoids sending a stale revision.
        return { status: 'superseded' } as ProfileSaveResult;
      }

      if (pending.deferredCreate) {
        // Durably staged, deliberately unsent: the cloud confirmed there is
        // no row and this write cannot legally create one. It goes out with
        // the first complete create.
        return { status: 'staged-local' };
      }
      if (pending.legacy) {
        // The revision these values were computed against is UNKNOWN — a
        // pre-CAS mirror, or an edit made before this browser ever reached
        // the backend. Sending it would be the blind write CAS exists to
        // remove. It waits for a load, or for the user.
        if (pending.lockedKeys.length > 0) {
          const revision = env?.confirmed?.revision ?? 0;
          return {
            status: 'conflict',
            revision,
            remote: pending.conflictRemote,
            confirmed: env?.confirmed ?? null,
            conflictKeys: pending.lockedKeys,
            conflicts: conflictPayload(pending.lockedKeys, pending, pending.conflictRemote, revision),
          };
        }
        return { status: 'local-only' };
      }

      const locked = new Set(pending.lockedKeys);
      const sendKeys = pending.dirtyKeys.filter((k) => !locked.has(k)) as ProfileKey[];
      if (sendKeys.length === 0) {
        const revision = env?.confirmed?.revision ?? pending.baseRevision;
        return {
          status: 'conflict',
          revision,
          remote: pending.conflictRemote,
          confirmed: env?.confirmed ?? null,
          conflictKeys: pending.lockedKeys,
          conflicts: conflictPayload(pending.lockedKeys, pending, pending.conflictRemote, revision),
        };
      }

      const outcome = await commitProfilePatch({
        expectedRevision: pending.baseRevision,
        patch: pick(pending.desiredProfile, sendKeys) as Record<string, unknown>,
        token,
        mutationId: pending.mutationId,
      });

      if (outcome.status === 'abandoned') return { status: 'abandoned' };
      if (!isOwnerTokenValid(token, token.uid)) return { status: 'abandoned' };

      if (outcome.status === 'saved' || outcome.status === 'already-saved') {
        const profile = outcome.profile as unknown as ProfileData;
        // Only the keys that were actually SENT are acknowledged — and only
        // the journal operations whose DESIRED value this response confirms.
        // An operation appended while the request was in flight names a value
        // the server has not seen, and acking it would delete an edit that
        // was never saved.
        // A failed acknowledgement means the journal still describes work the
        // cloud has already done. Reported as a local failure rather than a
        // clean save: the next flush must not re-send it as if it were new.
        // ONE critical section for the whole settle: acknowledge this write's
        // own journal operations and record the confirmed revision. Both read
        // shared state and write it back, and another tab doing the same in
        // between would decide from a half-updated view.
        const settled = await withSharedState(token, () => {
          const acked = ackConfirmedJournalOpsLocked(pending, sendKeys as string[], profile, outcome.revision, token);
          clearConfirmedKeys(sendKeys as string[], pending.keyVersions, pending);
          const survivor = survivorFor(pending, sendKeys as string[], outcome.revision, profile);
          // NOT short-circuited on `acked`: the cloud holds this revision
          // whether or not the acknowledgement could be written, and
          // recordConfirmed is what arms the local-only repair. Skipping it
          // would leave the next Retry with nothing to repair and send the
          // very same patch again.
          const recorded = recordConfirmed(outcome.revision, profile, survivor, token);
          return acked && recorded ? { survivor } : null;
        });
        if (!settled.ok) return settled.result;
        if (!settled.value) return { status: 'device-failed', phase: 'confirm' };
        // What is STILL locked after this confirmation, taken from the
        // survivor the critical section actually produced — not only from a
        // collision discovered during this very request.
        //
        // A question that was already locked before this attempt (one field of
        // a two-field disagreement answered, the other still open) survives it
        // untouched. Reporting a clean "saved" then tells the caller the whole
        // form went through, and Home retires the conflict UI while the other
        // half is still locked in storage: invisible, unanswerable, and
        // silently blocking every later save.
        const stillLocked = settled.value.survivor?.lockedKeys ?? [];
        if (stillLocked.length > 0) {
          const remote = settled.value.survivor?.conflictRemote
            ?? (deferredConflict?.remote ?? profile);
          return {
            status: 'conflict',
            revision: outcome.revision,
            remote,
            confirmed: { revision: outcome.revision, profile },
            conflictKeys: [...stillLocked],
            conflicts: conflictPayload(stillLocked, settled.value.survivor, remote, outcome.revision),
          };
        }
        return { status: outcome.status, revision: outcome.revision, profile };
      }

      if (outcome.status === 'conflict') {
        const remote = outcome.profile as unknown as ProfileData;
        const attempt: ProfilePendingWrite = { ...pending, dirtyKeys: sendKeys as string[] };
        const resolution = resolveConflict(attempt, remote);
        // Whether a newer edit owns the outbox is decided INSIDE the lock, from
        // what is there when the write happens — never from a copy read
        // beforehand. Another tab can stage between the two, and writing back
        // a pre-lock snapshot would put its edit back to what it was.
        const superseded = await withSharedState(token, () => {
          const live = readProfileSyncEnvelope()?.pending ?? null;
          if (!live || live.mutationId === pending.mutationId) return { newer: false as const };
          const written = writeEnvelope(
            { v: 1, confirmed: { revision: outcome.revision, profile: remote }, pending: live, tombstone: null },
            token,
          );
          return { newer: true as const, written };
        });
        if (!superseded.ok) return superseded.result;
        if (superseded.value.newer) {
          if (!superseded.value.written) return { status: 'device-failed', phase: 'stage' };
          return {
            status: 'conflict',
            revision: outcome.revision,
            remote,
            confirmed: { revision: outcome.revision, profile: remote },
            conflictKeys: resolution.conflictKeys as string[],
            conflicts: conflictPayload(
              resolution.conflictKeys as string[], pending, remote, outcome.revision,
            ),
          };
        }

        // "Nothing left to send" means BOTH halves are empty. Checking only
        // applyKeys would report every all-keys-collide conflict as a success
        // and drop the working copy with it.
        if (resolution.applyKeys.length === 0 && resolution.conflictKeys.length === 0) {
          const settled = await withSharedState(token, () => {
            const acked = ackConfirmedJournalOpsLocked(pending, sendKeys as string[], remote, outcome.revision, token);
            clearConfirmedKeys(sendKeys as string[], pending.keyVersions, pending);
            const survivor = survivorFor(pending, sendKeys as string[], outcome.revision, remote);
            // See the settle above: the confirmation is recorded even when
            // the acknowledgement could not be.
            const recorded = recordConfirmed(outcome.revision, remote, survivor, token);
            return acked && recorded;
          });
          if (!settled.ok) return settled.result;
          if (!settled.value) return { status: 'device-failed', phase: 'confirm' };
          return { status: 'already-saved', revision: outcome.revision, profile: remote };
        }

        if (resolution.conflictKeys.length === 0 && rebases < MAX_AUTO_REBASES) {
          // Disjoint edits: nobody touched the fields this write is about, so
          // it can be replayed onto the newer revision without asking.
          // Exactly once — a second conflict means the row is moving faster
          // than this device can follow.
          // The values come from `resolution`, not from the original desired
          // document: an additive key was resolved as a UNION with the remote
          // value, and re-picking the local one would drop what the other
          // device added.
          const resolved = resolvedPatch(pending, resolution);
          const rebasedDesired = {
            ...remote,
            ...pick(pending.desiredProfile, pending.lockedKeys as ProfileKey[]),
            ...resolved,
          } as ProfileData;
          const rebased: ProfilePendingWrite = {
            ...pending,
            mutationId: newMutationId(),
            baseRevision: outcome.revision,
            baseProfile: remote,
            desiredProfile: rebasedDesired,
            dirtyKeys: [...new Set([...resolution.applyKeys as string[], ...pending.lockedKeys])],
          };
          const rebasedWrite = await withSharedState(token, () => (
            writeEnvelope(
              { v: 1, confirmed: { revision: outcome.revision, profile: remote }, pending: rebased, tombstone: null },
              token,
            ) && writeRawMirror(rebasedDesired, token)
          ));
          if (!rebasedWrite.ok) return rebasedWrite.result;
          if (!rebasedWrite.value) return { status: 'device-failed', phase: 'stage' };
          currentId = rebased.mutationId;
          continue; // one more pass, inside this same queue slot
        }

        if (resolution.conflictKeys.length > 0 && resolution.applyKeys.length > 0
          && rebases < MAX_AUTO_REBASES) {
          // A PARTIAL disagreement. The fields nobody else touched are still
          // safe against the new revision, and holding them back because one
          // other field collided would tell the user nothing saved when most
          // of it could. Send that half; the collision stays locked for them
          // to decide, and the caller is told about it either way.
          const resolved = resolvedPatch(pending, resolution);
          const conflictKeys = resolution.conflictKeys as string[];
          const partialDesired = {
            ...remote,
            ...resolved,
            ...pick(pending.desiredProfile, conflictKeys as ProfileKey[]),
          } as ProfileData;
          const partial: ProfilePendingWrite = {
            ...pending,
            mutationId: newMutationId(),
            baseRevision: outcome.revision,
            baseProfile: remote,
            desiredProfile: partialDesired,
            dirtyKeys: [...new Set([...resolution.applyKeys as string[], ...conflictKeys])],
            lockedKeys: [...new Set([...pending.lockedKeys, ...conflictKeys])],
            conflictRemote: remote,
          };
          const partialWrite = await withSharedState(token, () => (
            writeEnvelope(
              { v: 1, confirmed: { revision: outcome.revision, profile: remote }, pending: partial, tombstone: null },
              token,
            ) && writeRawMirror(partialDesired, token)
          ));
          if (!partialWrite.ok) return partialWrite.result;
          if (!partialWrite.value) return { status: 'device-failed', phase: 'stage' };
          deferredConflict = { keys: conflictKeys, remote };
          currentId = partial.mutationId;
          continue;
        }

        // A real disagreement, OR a rebase budget that ran out while the row
        // kept moving. Either way the colliding keys are LOCKED: with the
        // base moved to the remote value, an ordinary retry would find
        // remote == base and quietly overwrite the other device. When the
        // budget is what ran out, the keys involved are the ones still
        // unsent — applyKeys — and they are locked too, or the very next
        // flush would punch straight through.
        const toLock = resolution.conflictKeys.length > 0
          ? resolution.conflictKeys as string[]
          : resolution.applyKeys as string[];
        const conflicted: ProfilePendingWrite = {
          ...pending,
          baseRevision: outcome.revision,
          baseProfile: remote,
          lockedKeys: [...new Set([...pending.lockedKeys, ...toLock])],
          conflictRemote: remote,
        };
        const lockRecorded = await withSharedState(token, () => writeEnvelope(
          { v: 1, confirmed: { revision: outcome.revision, profile: remote }, pending: conflicted, tombstone: null },
          token,
        ));
        if (!lockRecorded.ok) return lockRecorded.result;
        if (!lockRecorded.value) {
          // The lock is what stops the next automatic retry from overwriting
          // the other device. Claiming a conflict was recorded when it was
          // not would leave exactly that retry unguarded.
          return { status: 'device-failed', phase: 'stage' };
        }
        return {
          status: 'conflict',
          revision: outcome.revision,
          remote,
          confirmed: { revision: outcome.revision, profile: remote },
          conflictKeys: conflicted.lockedKeys,
          conflicts: conflictPayload(conflicted.lockedKeys, conflicted, remote, outcome.revision),
        };
      }

      if (outcome.status === 'missing') {
        if (outcome.reason === 'merged_away') {
          // This account no longer exists: Flow B moved its data under
          // another one, which now holds it. The local copy is a dead
          // identity's row — quarantine it rather than keep serving it, and
          // stop trying to write.
          // The dead account's unsent edits go with its row: replaying them
          // under the surviving account is not this user's intent.
          await withProfileLock(token, () => clearJournal(token));
          const envelopeCleared = writeEnvelope({ v: 1, confirmed: null, pending: null, tombstone: { reason: 'merged', rawQuarantined: false } }, token);
          const mirrorCleared = writeLocalStorageJSON(STORAGE_KEYS.PROFILE, null, token);
          if (!envelopeCleared || !mirrorCleared) {
            // The dead account's data is still being served here. Do NOT
            // clear the ledger and do NOT report a plain 'missing': the next
            // repair has to know there is still something to remove.
            return { status: 'device-failed', phase: 'confirm' };
          }
          for (const key of pending.dirtyKeys) fieldIntents.delete(key);
          return { status: 'missing', reason: 'merged_away' };
        }
        // The row was deleted. NOTHING is recreated — that would resurrect
        // it — and NOTHING is discarded: the working copy is the user's own
        // unsaved edit, still on screen. The deletion is recorded durably so
        // the next mount's create path cannot undo it.
        const env2 = readProfileSyncEnvelope();
        writeEnvelope(
          {
            v: 1,
            confirmed: env2?.confirmed ?? null,
            pending: env2?.pending ?? null,
            tombstone: { reason: 'deleted', rawQuarantined: true },
          },
          token,
        );
        return { status: 'missing', reason: 'absent' };
      }

      if (outcome.status === 'local-only') return { status: 'local-only' };

      // transport-error / malformed: keep the working copy for a retry. An
      // unknown response is a failure, never a silent success.
      return { status: 'error', message: outcome.message };
    }
  });
}


/** The values a rebase should actually send: the locally-desired value for a
 *  plain key, and the RESOLVED (union) value for an additive one. */
function resolvedPatch(
  pending: ProfilePendingWrite,
  resolution: ConflictResolution,
): Record<string, unknown> {
  const desired = pending.desiredProfile as unknown as Record<string, unknown>;
  const out: Record<string, unknown> = {};
  for (const key of resolution.applyKeys) {
    out[key as string] = key in resolution.resolvedValues
      ? resolution.resolvedValues[key as string]
      : desired[key as string];
  }
  return out;
}

// ---------------------------------------------------------------------------
// Three-way resolution
// ---------------------------------------------------------------------------

export interface ConflictResolution {
  /** Keys whose value should still be sent. */
  applyKeys: ProfileKey[];
  /** Keys where remote, base and desired all differ — a genuine collision. */
  conflictKeys: ProfileKey[];
  /** For keys resolved by MERGING rather than by taking the local value
   *  (additive `skills`), the merged value that must actually be sent.
   *  Without carrying it, a rebase would re-send the local list and delete
   *  whatever the other device added. */
  resolvedValues: Record<string, unknown>;
}

/**
 * For each key this write is about:
 *   remote == base    → nobody else touched it; the local edit still applies
 *   remote == desired → someone already made this exact change; drop it
 *   otherwise         → a real conflict
 * Keys the write is NOT about always keep the remote value — they are never
 * even considered, which is what makes an unrelated edit safe.
 */
export function resolveConflict(
  pending: ProfilePendingWrite,
  remote: ProfileData,
): ConflictResolution {
  const applyKeys: ProfileKey[] = [];
  const conflictKeys: ProfileKey[] = [];
  const resolvedValues: Record<string, unknown> = {};
  const base = pending.baseProfile as unknown as Record<string, unknown>;
  const desired = pending.desiredProfile as unknown as Record<string, unknown>;
  const remoteRec = remote as unknown as Record<string, unknown>;
  const additive = new Set(pending.additiveKeys);

  for (const key of pending.dirtyKeys) {
    const r = remoteRec[key];
    const b = base[key];
    const d = desired[key];
    if (sameValue(r, d)) continue;         // already landed
    if (sameValue(r, b)) { applyKeys.push(key as ProfileKey); continue; }
    if (additive.has(key) && key === 'skills' && pending.skillAdditions.length > 0) {
      // The ADDITIONS are merged into whatever the other device currently
      // has — not this device's whole list. Merging the full list would
      // resurrect a skill the other device deleted, and would flag a level
      // they changed on an untouched skill as a conflict the user never
      // caused. A name this write adds that the other device already has at
      // a DIFFERENT level is a real disagreement about one value.
      const merged = mergeSkillAdditions(r, pending.skillAdditions);
      if (merged) {
        applyKeys.push(key as ProfileKey);
        resolvedValues[key] = merged;
        continue;
      }
    }
    conflictKeys.push(key as ProfileKey);
  }

  // Bundle: if either half of the résumé collides, both do — applying only
  // the non-colliding half is how coursework outlives the résumé it came from.
  if (RESUME_BUNDLE.some((k) => conflictKeys.includes(k))) {
    for (const k of RESUME_BUNDLE) {
      if (pending.dirtyKeys.includes(k) && !conflictKeys.includes(k)) {
        conflictKeys.push(k);
        const at = applyKeys.indexOf(k);
        if (at >= 0) applyKeys.splice(at, 1);
        delete resolvedValues[k];
      }
    }
  }
  return { applyKeys, conflictKeys, resolvedValues };
}

function isSkillList(value: unknown): value is SkillWithLevel[] {
  return Array.isArray(value)
    && value.every((s) => !!s && typeof s === 'object' && typeof (s as SkillWithLevel).name === 'string');
}

/** Applies an ADD-only operation to whatever the other device currently has.
 *  Returns null when an added name already exists there at a different level —
 *  one value, two answers, which only the user can settle. */
export function mergeSkillAdditions(
  remote: unknown,
  additions: readonly SkillWithLevel[],
): SkillWithLevel[] | null {
  if (!isSkillList(remote)) return null;
  const byName = new Map<string, SkillWithLevel>();
  for (const skill of remote) byName.set(skill.name, skill);
  const out = [...remote];
  for (const skill of additions) {
    const existing = byName.get(skill.name);
    if (!existing) { out.push(skill); byName.set(skill.name, skill); continue; }
    if (existing.level !== skill.level) return null;
  }
  return out;
}
