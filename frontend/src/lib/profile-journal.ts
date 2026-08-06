// The durable intent journal for profile edits.
//
// THE PROBLEM IT SOLVES
// Two tabs on one account share localStorage. Any design where an edit is
// recorded by reading a shared value, changing it, and writing it back loses
// data: tab A reads, tab B reads, A writes, B writes — A's operation is gone,
// and nothing anywhere knows it existed. The previous in-memory version was
// worse still: an edit made inside the 1.5s autosave window did not exist on
// disk at all, so a crash or a closed tab lost it silently.
//
// THE MODEL: ONE STORAGE KEY PER OPERATION
//   * APPEND = a single setItem to a key nobody else will ever write:
//     `ofe_profile_journal_v1_op_<uuid>`. Synchronous, at edit/action time,
//     before any debounce. There is NO read-modify-write anywhere on this
//     path, so there is nothing for two tabs to interleave. A per-tab ARRAY
//     lane would not be enough: the consolidating tab reads [A], the owning
//     tab appends [A,B] without a lock, and the consolidator then writes back
//     its filtered [A] — deleting B. Appends deliberately do not take the
//     lock, so no rewrite of another tab's storage can ever be safe.
//   * Each operation carries the base it was made against (value + revision),
//     frozen at that moment, so a later save is resolved three ways against
//     what the user actually started from.
//   * ACK IS TWO-PHASE, under the lock: write the acknowledged ids to
//     `ofe_profile_journal_v1_ack` FIRST, then delete those op keys. A crash
//     between the two leaves acked-but-present operations, which readers skip
//     — never the reverse, which would re-send a write that already landed.
//   * NO GLOBAL ORDER. `seq` orders one tab's own operations and nothing
//     else. Two tabs editing the same field are resolved by their frozen
//     bases, never by which key happened to enumerate first.
//   * ONE LOCK, SHARED BY EVERY ACCOUNT. The raw storage keys are NOT
//     uid-scoped — they are fixed names holding whichever identity currently
//     owns this browser — so a lock named per-uid would let U1 and U2 mutate
//     the same keys concurrently. Identity is re-checked before taking the
//     lock, after acquiring it, and after the body returns.
//   * NETWORK WAITS ARE OUTSIDE THE LOCK. The request is issued unlocked; the
//     response re-acquires, re-reads everything, and applies the monotonic
//     revision check before writing anything.
//   * FAIL CLOSED, NEVER FILTER. An operation this build cannot fully
//     understand — malformed, an unknown key or mode — makes every cross-tab
//     pass refuse to act. Skipping what it cannot read is how a downgraded tab
//     silently deletes a newer one's edits.
//
// The in-memory maps in profile-sync.ts are a CACHE. This file is the
// authority.

import { STORAGE_KEYS } from './storage-keys';
import {
  enumerateUserScopedKeys,
  isOwnerTokenValid,
  hasSerializationBackend,
  isTokenOwnerStillCurrent,
  PRIVATE_STORAGE_LOCK,
  readUserScopedEntry,
  readUserScopedRaw,
  removeUserScopedRaw,
  writeUserScopedRaw,
  type OwnerToken,
} from './identity-owner';

/** How an operation changes its field. */
export type JournalOpMode =
  /** Replace the field's value outright (every ordinary edit). */
  | 'set'
  /** Add these skills without asserting anything about the others. */
  | 'add-skills'
  /** The skills list itself is the intent, deletions included. */
  | 'replace-skills'
  /** A person's answer to a conflict — see `resolves`/`decisions`. */
  | 'resolve';

const OP_MODES: readonly JournalOpMode[] = ['set', 'add-skills', 'replace-skills', 'resolve'];

/**
 * A field value, with its PRESENCE recorded separately. `JSON.stringify` drops
 * an `undefined` property entirely, which would make "this field had no value
 * when the edit began" and "this operation forgot to record the base" the same
 * bytes — and the three-way resolution would then treat a first-ever value as
 * an unchanged one.
 */
export interface JournalValue {
  present: boolean;
  value?: unknown;
}

export function encodeJournalValue(source: Record<string, unknown>, key: string): JournalValue {
  const value = source[key];
  // A key that exists with an `undefined` value is absent as far as this app
  // is concerned: the patch omits it either way, and the server keeps what it
  // has. Collapsing them here keeps the two representations from diverging.
  return value === undefined ? { present: false } : { present: true, value };
}

export function decodeJournalValue(v: JournalValue): unknown {
  return v.present ? v.value : undefined;
}

export interface JournalField {
  /** The ProfileData key. */
  key: string;
  /** What it held when the edit BEGAN. */
  base: JournalValue;
  /** What the user wants it to be. */
  desired: JournalValue;
}

export interface JournalOp {
  opId: string;
  /** WHICH tab wrote it. `seq` orders operations within one origin and means
   *  nothing across origins — two tabs both start at 1. Without the origin,
   *  "this is the user's next keystroke" and "this is somebody else's
   *  independent edit" look identical. */
  originId: string;
  /** The LINEAGE that wrote it: that document and its reloads. Only the same
   *  lineage may declare that it continues this operation. */
  lineage: string;
  /** Operations this one explicitly continues, by id. A same-origin edit
   *  chain records it; anything else must be resolved, not guessed at from
   *  storage order. */
  supersedes?: string[];
  /**
   * EVERY field this one action changed, in ONE operation. A college switch
   * clears the major; removing a résumé clears its coursework. Writing those
   * as separate operations means the first can land and the second fail,
   * leaving a journal that describes half an action — a résumé removed with
   * its coursework still attached. One operation is one setItem, so it either
   * exists in full or not at all.
   */
  fields: JournalField[];
  /** The revision every field's base belongs to. */
  baseRevision: number;
  /** Which screen made it — see the key-ownership rule in profile-sync. */
  writer: string;
  mode: JournalOpMode;
  /** Names an atomic group (the résumé bundle) for locking/acknowledgement. */
  bundle?: string;
  /**
   * A RESOLUTION RECEIPT (`mode: 'resolve'`) — the durable record of a person
   * answering a conflict.
   *
   * `resolves` names every operation the answer covers, and `decisions` says
   * what was chosen for each field. Unlike `supersedes`, this may name
   * operations of OTHER lineages: answering a disagreement between two tabs
   * is exactly the act of speaking for both, and it is the only thing allowed
   * to. Ordinary edits may never make that claim.
   *
   * Readers honour a receipt the moment it exists. Removing the operations it
   * answers is cleanup that can fail, be interrupted, or happen much later —
   * the decision does not wait for it.
   */
  resolves?: string[];
  /**
   * The PENDING write this answer settles, when the disagreement has no
   * outstanding operations to name.
   *
   * A conflict raised by a write that was already staged lives in the outbox,
   * not the journal: the operations behind it were captured into the pending
   * entry when it went out. The question is entirely real and the answer is
   * entirely valid — it simply has no op ids, and binding it to the mutation
   * instance plus the field versions it was asked about is what makes it as
   * durable and as replayable as an op-backed one.
   */
  resolvesPending?: { mutationId: string; keyVersions: Record<string, number> };
  decisions?: Record<string, 'local' | 'cloud'>;
  /** Monotonic within this tab; orders its own operations and nothing else. */
  seq: number;
}

export type JournalResult<T> = { ok: true; value: T } | { ok: false; reason: string };

const PREFIX = STORAGE_KEYS.PROFILE_JOURNAL_PREFIX;
const OP_PREFIX = `${PREFIX}op_`;
const ACK_KEY = `${PREFIX}ack`;
// sessionStorage: per document tree, and gone when the tab closes. Only ever
// READ on a reload — see getJournalLineageId.
const LINEAGE_KEY = `${PREFIX}lineage`;
const LINEAGE_SEQ_KEY = `${PREFIX}lineage_seq`;

/** Cap on outstanding operations. A pathological writer (a stuck retry loop, a
 *  script) must not be able to fill the origin's quota and take every other
 *  key down with it. Reaching it REPORTS failure — the oldest operations are
 *  the ones still unsent, so silently dropping them is the one thing that
 *  cannot happen here. */
const MAX_OUTSTANDING_OPS = 500;

/** Orders THIS tab's own operations. Deliberately not a global sequence: two
 *  tabs cannot agree on one without the coordination this design removes.
 *  Persisted with the lineage (see LINEAGE_SEQ_KEY) so it keeps rising across
 *  a reload —
 *  otherwise two of the same tab's operations could share a seq and their
 *  order would come down to enumeration order, which means nothing. */
let laneSeq: number | null = null;
/** Identifies this DOCUMENT. A reload makes a new one; so does a new tab. */
let originId: string | null = null;
/** Identifies this document's LINEAGE — itself plus the documents it is a
 *  reload of. Never inherited any other way. */
let lineageId: string | null = null;

/** How this document came to exist. Only a reload continues a lineage. */
export type NavigationKind = 'reload' | 'other';
let navigationKindForTests: NavigationKind | null = null;

/** Test seam. Sets the NAVIGATION KIND and nothing else — no lineage, no
 *  operation ids, no ancestry. A test that could hand the module an identity
 *  directly would be proving its own premise. */
export function setNavigationKindForTests(kind: NavigationKind | null): void {
  navigationKindForTests = kind;
}

function navigationKind(): NavigationKind {
  if (navigationKindForTests) return navigationKindForTests;
  try {
    const [nav] = performance.getEntriesByType('navigation') as PerformanceNavigationTiming[];
    // 'navigate', 'back_forward', 'prerender', or anything unrecognised: not
    // a reload. Unknown is not "probably fine" here — it is the answer that
    // refuses continuity.
    return nav && nav.type === 'reload' ? 'reload' : 'other';
  } catch {
    return 'other';
  }
}

export function getJournalOriginId(): string {
  if (!originId) originId = newId();
  return originId;
}

/**
 * The lineage this document belongs to: itself, plus every document it is a
 * reload of. An operation may only ever be continued by its own lineage.
 *
 * Stored state alone cannot establish this. A window opened from another gets
 * a COPY of its sessionStorage; "Duplicate tab" does the same; localStorage
 * is shared outright. To a second window, every stored mark of identity looks
 * exactly like a reload's — so a lineage carried in storage would let it
 * claim the first window's unsent edits and overwrite them, which is the
 * failure this whole design exists to remove.
 *
 * What actually separates the two is how the document came to exist. The
 * stored lineage is therefore READ only when the browser reports a reload;
 * any other navigation mints a fresh one and overwrites what was stored, so
 * an inherited copy is discarded the first time it is looked at.
 *
 * Fails closed everywhere it cannot be sure: navigation kind unavailable or
 * unrecognised, sessionStorage unusable, a write that does not read back —
 * all produce a per-document lineage, which continues nothing.
 */
export function getJournalLineageId(): string {
  if (lineageId) return lineageId;
  try {
    if (navigationKind() === 'reload') {
      const existing = sessionStorage.getItem(LINEAGE_KEY);
      if (existing) {
        lineageId = existing;
        return lineageId;
      }
    }
    const fresh = newId();
    sessionStorage.setItem(LINEAGE_KEY, fresh);
    sessionStorage.setItem(LINEAGE_SEQ_KEY, '0');
    // Read back: storage that accepts a write and keeps nothing would hand
    // out a lineage that does not survive the very reload it exists for.
    lineageId = sessionStorage.getItem(LINEAGE_KEY) === fresh ? fresh : newId();
    return lineageId;
  } catch {
    lineageId = newId();
    return lineageId;
  }
}

// Settled when the document LOADS, not when it first writes. A window opened
// from another one may never write at all — the user opens the form, reads
// it, and closes it — and the inherited copy of sessionStorage would sit
// there untouched for that window's own reload to pick up and claim the other
// window's unsent edits with. Discarding it has to happen on arrival.
getJournalLineageId();

/**
 * The next sequence number for this lineage, or null when one cannot be
 * issued safely.
 *
 * `seq` orders a lineage's own operations, so re-issuing one it has already
 * used makes that order depend on storage enumeration instead. A missing or
 * corrupt counter therefore does NOT fall back to zero: the highest seq this
 * lineage still has outstanding is the floor, and if that cannot be read —
 * or the next value would leave the safe integer range — the append is
 * refused before any key is written.
 */
function nextSeq(): number | null {
  if (laneSeq === null) {
    let restored: number | null = null;
    try {
      const raw = sessionStorage.getItem(LINEAGE_SEQ_KEY);
      const parsed = raw === null ? 0 : Number(raw);
      if (Number.isSafeInteger(parsed) && parsed >= 0) restored = parsed;
    } catch {
      restored = null;
    }
    // ALWAYS reconciled against what is actually stored, not only when the
    // counter is missing. A positive counter can be stale on its own: the
    // lineage id persisted, an op was appended, and only the LATER counter
    // write silently no-opped. A new document then trusts the old value and
    // issues a sequence this lineage has already used.
    const stored = readOutstandingOps();
    // Unreadable while recovery is exactly what is needed: fail closed.
    if (!stored.ok) return null;
    const mine = getJournalLineageId();
    let floor = restored ?? 0;
    for (const op of stored.value) {
      if (op.lineage === mine && op.seq > floor) floor = op.seq;
    }
    laneSeq = floor;
  }
  if (!Number.isSafeInteger(laneSeq + 1)) return null;
  laneSeq += 1;
  try {
    sessionStorage.setItem(LINEAGE_SEQ_KEY, String(laneSeq));
  } catch {
    // In-memory only. The tab id fell back to per-document for the same
    // reason, so nothing is claiming continuity across a reload anyway.
  }
  return laneSeq;
}

function newId(): string {
  const c = typeof crypto !== 'undefined' ? crypto : undefined;
  if (c && typeof c.randomUUID === 'function') return c.randomUUID();
  return `${Date.now().toString(36)}-${Math.floor(Math.random() * 1e12).toString(36)}`;
}

/** Test seam: a separate tab opened independently — fresh document globals
 *  and none of this one's session state. */
export function resetJournalLaneForTests(): void {
  // Session state goes FIRST: starting the document settles a lineage and
  // stores it, so clearing afterwards would leave this module holding an id
  // that storage no longer has — and the next reload would mint a different
  // one for no reason the test asked for.
  try {
    sessionStorage.removeItem(LINEAGE_KEY);
    sessionStorage.removeItem(LINEAGE_SEQ_KEY);
  } catch {
    // Nothing to clear.
  }
  startDocumentForTests('other');
}

/** Test seam: a NEW DOCUMENT over whatever storage is currently there, of the
 *  given navigation kind. Storage is left exactly as the test arranged it —
 *  that is the point: 'reload' and a duplicated window differ ONLY in this
 *  argument, and the module has to reach the right answer from that alone.
 *  `null` removes the override entirely, so the module classifies the
 *  navigation itself — which is what the browser tests below exercise. */
export function startDocumentForTests(kind: NavigationKind | null): void {
  laneSeq = null;
  originId = null;
  lineageId = null;
  setNavigationKindForTests(kind);
}

/**
 * `isKnownKey` is injected rather than imported so this module does not depend
 * on the profile shape; profile-sync passes its own compile-time-exhaustive
 * registry. UNREGISTERED MEANS EVERYTHING FAILS: a journal read before the
 * owner of the shape has declared itself cannot tell a valid key from a
 * corrupt one, and guessing "probably fine" is exactly the downgrade hazard
 * this guard exists for.
 */
let isKnownKey: ((key: string) => boolean) | null = null;
/** Bundles group operations that must be sent, locked and acknowledged
 *  together. An unknown one DOES change semantics — it would be ungrouped —
 *  so it fails closed like an unknown key. */
let knownBundles: ReadonlySet<string> = new Set();
export function registerJournalKeyGuard(
  guard: (key: string) => boolean,
  bundles: readonly string[] = [],
): void {
  isKnownKey = guard;
  knownBundles = new Set(bundles);
}
export function clearJournalKeyGuardForTests(): void {
  isKnownKey = null;
  knownBundles = new Set();
}

function parseValue(value: unknown): JournalValue | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
  const v = value as JournalValue;
  if (typeof v.present !== 'boolean') return null;
  return v.present ? { present: true, value: v.value } : { present: false };
}

function parseOp(raw: string | null, storageKey: string): JournalResult<JournalOp> {
  if (raw === null) return { ok: false, reason: `${storageKey} disappeared mid-read` };
  if (!isKnownKey) return { ok: false, reason: 'no profile-key guard registered' };
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return { ok: false, reason: `${storageKey} is not valid JSON` };
  }
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
    return { ok: false, reason: `${storageKey} is not an operation` };
  }
  const op = parsed as JournalOp;
  if (
    typeof op.opId !== 'string' || !op.opId
    // `writer` decides which screen re-sends an operation; it never changes
    // WHAT is sent. Required to be a non-empty string and otherwise opaque.
    || typeof op.writer !== 'string' || !op.writer
    || typeof op.originId !== 'string' || !op.originId
    || typeof op.lineage !== 'string' || !op.lineage
    || (op.supersedes !== undefined
      && (!Array.isArray(op.supersedes)
        || op.supersedes.some((v) => typeof v !== 'string')
        // Its own ancestor: not a mistake this code can make, so a journal
        // that contains one has been written by something else.
        || op.supersedes.includes(op.opId as string)))
    // SAFE integers throughout: `seq` orders a lineage's own operations and
    // `baseRevision` is compared for exact equality, and two distinct JSON
    // values past 2^53 parse to the same double — which would silently make
    // one operation's identity equal another's.
    || typeof op.seq !== 'number' || !Number.isSafeInteger(op.seq) || op.seq < 0
    || typeof op.baseRevision !== 'number' || !Number.isSafeInteger(op.baseRevision)
    || op.baseRevision < 0
    || !Array.isArray(op.fields) || op.fields.length === 0
    || !resolutionIsWellFormed(op)
  ) {
    return { ok: false, reason: `${storageKey} is malformed` };
  }
  const fields: JournalField[] = [];
  for (const raw2 of op.fields) {
    if (!raw2 || typeof raw2 !== 'object') {
      return { ok: false, reason: `${storageKey} has a malformed field` };
    }
    const f = raw2 as JournalField;
    const base = parseValue(f.base);
    const desired = parseValue(f.desired);
    if (typeof f.key !== 'string' || !base || !desired) {
      return { ok: false, reason: `${storageKey} has a malformed field` };
    }
    if (!isKnownKey(f.key)) return { ok: false, reason: `unknown profile key ${f.key}` };
    fields.push({ key: f.key, base, desired });
  }
  // The KEY must name the operation inside it. Without this binding, a
  // hand-written (or half-written) key whose body claims a different opId
  // would let settleJournalOps delete a completely different, real operation
  // — the id it acks is the one it deletes.
  if (storageKey !== `${OP_PREFIX}${op.opId}`) {
    return { ok: false, reason: `${storageKey} does not match its own opId` };
  }
  if (op.bundle !== undefined && (typeof op.bundle !== 'string' || !knownBundles.has(op.bundle))) {
    return { ok: false, reason: `unknown operation bundle ${String(op.bundle)}` };
  }
  if (!OP_MODES.includes(op.mode)) {
    // A newer build wrote a mode this one cannot honour. Acting on the rest
    // would drop it.
    return { ok: false, reason: `unknown operation mode ${String(op.mode)}` };
  }
  return {
    ok: true,
    value: {
      opId: op.opId,
      originId: op.originId,
      lineage: op.lineage,
      resolves: op.resolves ? [...op.resolves] : undefined,
      resolvesPending: op.resolvesPending
        ? {
          mutationId: op.resolvesPending.mutationId,
          keyVersions: { ...op.resolvesPending.keyVersions },
        }
        : undefined,
      decisions: op.decisions ? { ...op.decisions } : undefined,
      supersedes: op.supersedes ? [...op.supersedes] : undefined,
      fields,
      baseRevision: op.baseRevision,
      writer: op.writer,
      mode: op.mode,
      bundle: typeof op.bundle === 'string' ? op.bundle : undefined,
      seq: op.seq,
    },
  };
}

/** Every operation key currently present IN THIS OWNER'S NAMESPACE.
 *  Enumeration, not an index — an index would itself be a shared value
 *  needing a read-modify-write. Delegated to the authority so a key belonging
 *  to a generation this owner has moved past is not merely ignored downstream
 *  but never seen at all. */
function scopedKeys(prefix: string): JournalResult<string[]> {
  if (typeof window === 'undefined') return { ok: true, value: [] };
  const found = enumerateUserScopedKeys(prefix);
  if (found.status !== 'present') {
    // An entry may exist and be invisible. Every cross-tab decision below
    // would be made on a partial view.
    return { ok: false, reason: `journal enumeration failed: ${found.reason}` };
  }
  return { ok: true, value: found.keys };
}

function opKeys(): JournalResult<string[]> {
  return scopedKeys(OP_PREFIX);
}

function isJournalValue(value: unknown): value is JournalValue {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false;
  const v = value as Partial<JournalValue>;
  if (typeof v.present !== 'boolean') return false;
  return v.present ? 'value' in v : !('value' in v) || v.value === undefined;
}

export function readAckedOpIds(): JournalResult<Set<string>> {
  // Tri-state, deliberately. "There are no acknowledgements" licenses treating
  // every operation on disk as still outstanding; "I could not read the
  // acknowledgements" does not, and it is the same null downstream. Reading an
  // acknowledged operation back as outstanding resurrects an edit the user
  // already saw land.
  const entry = readUserScopedEntry(ACK_KEY);
  if (entry.status === 'unavailable') {
    return { ok: false, reason: `ack set unavailable: ${entry.reason}` };
  }
  if (entry.status === 'absent') return { ok: true, value: new Set() };
  const raw = entry.value;
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return { ok: false, reason: 'ack set is not valid JSON' };
  }
  if (!Array.isArray(parsed) || parsed.some((v) => typeof v !== 'string')) {
    return { ok: false, reason: 'ack set is not a list of ids' };
  }
  return { ok: true, value: new Set(parsed as string[]) };
}

/**
 * Appends ONE immutable operation, synchronously, as its OWN storage key.
 * Lock-free and race-free by construction: the key did not exist a moment ago
 * and nothing else will ever write it. Returns null when the operation is NOT
 * durable — a storage write that did not read back, a stale owner, the cap —
 * and a caller must treat that as "this edit was not recorded", never as
 * success.
 */
export function appendJournalOp(
  // `originId`/`lineage` are overridable for ONE purpose: narrowing an
  // operation that is being partly abandoned (see the coordinator's
  // "use the other device's version" path). The replacement is the original's
  // own continuation and must keep its identity, or it would be claiming
  // ancestry across lineages — the thing the read guard rejects.
  op: Omit<JournalOp, 'opId' | 'seq' | 'originId' | 'lineage'>
    & { originId?: string; lineage?: string },
  token: OwnerToken,
): JournalOp | null {
  if (!isOwnerTokenValid(token, token.uid)) return null;
  // Validated HERE, not only when it is read back. A malformed receipt that
  // reaches storage occupies a key that every subsequent read then fails
  // closed on — the whole journal becomes unreadable because of one bad
  // write, and the writer that made it is long gone.
  if (!resolutionIsWellFormed(op)) return null;
  const keys = opKeys();
  if (!keys.ok || keys.value.length >= MAX_OUTSTANDING_OPS) return null;
  // Before any key is written: an operation that cannot be given a safe,
  // unused sequence must not exist at all.
  const seq = nextSeq();
  if (seq === null) return null;
  const full: JournalOp = {
    ...op,
    originId: op.originId || getJournalOriginId(),
    lineage: op.lineage || getJournalLineageId(),
    opId: newId(),
    seq,
  };
  const storageKey = `${OP_PREFIX}${full.opId}`;
  return writeUserScopedRaw(storageKey, JSON.stringify(full), token) ? full : null;
}

/**
 * A REBASE RECEIPT: the durable record that one operation landed, and what the
 * row held for its fields at that moment.
 *
 * Why a receipt and not an edit to the surviving operation. The user typed
 * ECE, the request went out, they typed Physics, and ECE landed at revision 2.
 * Physics still says it was based on CS at revision 1 — the truth when it was
 * made — and sending it now would expect revision 1 against a revision 2 row
 * and come back as a conflict between the user and themselves.
 *
 * Rewriting Physics in place is not an option. Operation keys are append-only
 * for a reason that survives every clever exception: appends deliberately do
 * NOT take the lock, so an operation can be written between any scan and any
 * decision made from it, and a rewrite pass simply will not see it. It is also
 * the wrong shape — the tab that finishes A's request may not be the tab that
 * wrote it, and only A's OWN lineage may be rebased onto A.
 *
 * So the receipt is keyed by the ancestor and written BEFORE the ancestor is
 * settled. Descendants derive their effective base by following their explicit
 * `supersedes` ancestry through these receipts, LAZILY — which is what makes a
 * descendant appended after the scan, or read after a reload by a different
 * document, come out correct anyway.
 */
export interface RebaseReceipt {
  v: 1;
  ancestorOpId: string;
  /** The ancestor's OWN lineage. A descendant is rebased only when it shares
   *  it — another tab's independent opinion of the same field superseded
   *  nothing of ours and is a real disagreement. Deliberately not the lineage
   *  of whichever document happens to be doing the recovery. */
  ancestorLineage: string;
  revision: number;
  /**
   * The WHOLE row at `revision`, not just the fields that landed.
   *
   * A descendant carrying one confirmed field and one unconfirmed field has to
   * describe a single coherent moment: saying "base revision 2" while some of
   * its bases are values from revision 1 is a lie that the three-way
   * resolution will believe.
   */
  profile: Record<string, JournalValue>;
  /** The keys this ancestor's landing actually confirmed. Everything else in
   *  `profile` is context for coherence, not something this receipt settles. */
  confirmedKeys: string[];
}

const REBASE_PREFIX = `${PREFIX}rebase_`;
/** Receipts are bounded by the same cap as operations: one per landed
 *  ancestor, and a pathological writer must not be able to fill the origin's
 *  quota. Reaching it REPORTS failure — an ancestor whose receipt cannot be
 *  written is not settled, so nothing is lost, it simply stops. Normal
 *  compaction is deliberately deferred: a scan that sees no descendant cannot
 *  prove one is not being appended at that very moment, so the only safe
 *  bulk removal is a verified identity reset (see clearJournal). */
const MAX_REBASE_RECEIPTS = MAX_OUTSTANDING_OPS;

/**
 * Append-only, one key per landed ancestor, never mutated.
 *
 * An existing key is accepted ONLY as a byte-identical replay — the same
 * acknowledgement being recorded twice after a crash. Anything else means two
 * different answers claim the same ancestor, and overwriting would silently
 * pick one.
 */
export function appendRebaseReceipt(receipt: RebaseReceipt, token: OwnerToken): boolean {
  if (!isOwnerTokenValid(token, token.uid)) return false;
  const key = `${REBASE_PREFIX}${receipt.ancestorOpId}`;
  const serialized = JSON.stringify(receipt);
  // "Nothing is filed here" is what permits this write. A failed read is not
  // that, and treating it as that overwrites an acknowledgement that already
  // exists — the exact silent pick-one this append-only key was built to stop.
  const existing = readUserScopedEntry(key);
  if (existing.status === 'unavailable') return false;
  if (existing.status === 'present') return existing.value === serialized;
  const keys = scopedKeys(REBASE_PREFIX);
  if (!keys.ok || keys.value.length >= MAX_REBASE_RECEIPTS) return false;
  return writeUserScopedRaw(key, serialized, token);
}

function isRebaseReceipt(value: unknown): value is RebaseReceipt {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false;
  const r = value as Partial<RebaseReceipt>;
  // An unrecognised version is not something to guess at: a newer build's
  // receipt may mean something this one would apply wrongly.
  if (r.v !== 1) return false;
  if (typeof r.ancestorOpId !== 'string' || !r.ancestorOpId) return false;
  if (typeof r.ancestorLineage !== 'string' || !r.ancestorLineage) return false;
  if (typeof r.revision !== 'number' || !Number.isSafeInteger(r.revision) || r.revision < 0) return false;
  if (!Array.isArray(r.confirmedKeys) || r.confirmedKeys.some((k) => typeof k !== 'string')) return false;
  if (!r.profile || typeof r.profile !== 'object' || Array.isArray(r.profile)) return false;
  const profile = r.profile as Record<string, unknown>;
  if (Object.keys(profile).some((k) => !k)) return false;
  if (!Object.values(profile).every(isJournalValue)) return false;
  // Every key it claims to have confirmed must be one it describes.
  return (r.confirmedKeys as string[]).every((k) => k in profile);
}

/** Every rebase receipt, by ancestor id. Fails closed on ANY unreadable,
 *  unrecognised, misfiled or duplicated entry: planning a send from a
 *  partially-understood set of acknowledgements is how a base silently
 *  reverts to a revision that is gone. */
export function readRebaseReceipts(): JournalResult<Map<string, RebaseReceipt>> {
  const keys = scopedKeys(REBASE_PREFIX);
  if (!keys.ok) return keys;
  const out = new Map<string, RebaseReceipt>();
  for (const key of keys.value) {
    const raw = readUserScopedRaw(key);
    if (raw === null) return { ok: false, reason: `${key} disappeared mid-read` };
    let parsed: unknown;
    try {
      parsed = JSON.parse(raw);
    } catch {
      return { ok: false, reason: `${key} is not JSON` };
    }
    if (!isRebaseReceipt(parsed)) return { ok: false, reason: `${key} is not a rebase receipt` };
    // The key IS the identity. A receipt filed under a different ancestor's
    // name would rebase the wrong chain, and "last one enumerated wins" is not
    // a decision anything here is allowed to make.
    if (key !== `${REBASE_PREFIX}${parsed.ancestorOpId}`) {
      return { ok: false, reason: `${key} names ${parsed.ancestorOpId}` };
    }
    if (out.has(parsed.ancestorOpId)) {
      return { ok: false, reason: `duplicate receipt for ${parsed.ancestorOpId}` };
    }
    out.set(parsed.ancestorOpId, parsed);
  }
  return { ok: true, value: out };
}

/**
 * The base an operation should actually be sent against: its own frozen base,
 * moved forward onto the row a receipt confirmed for an ancestor it continues.
 *
 * The ancestry is walked through LIVE operations as well as receipts: A lands
 * and leaves a receipt, B (still outstanding) supersedes A, C supersedes only
 * B — and C has to reach A's receipt through B. Following the ancestry rather
 * than trusting a rewritten record is what makes this correct for an operation
 * appended after any scan, read by any document, after any number of reloads.
 */
export function effectiveOpBase(
  op: JournalOp,
  receipts: ReadonlyMap<string, RebaseReceipt>,
  opsById: ReadonlyMap<string, JournalOp> = new Map(),
): { fields: JournalField[]; baseRevision: number } {
  if (receipts.size === 0 || (op.supersedes ?? []).length === 0) {
    return { fields: op.fields, baseRevision: op.baseRevision };
  }
  // The NEWEST acknowledgement reachable through this operation's own
  // ancestry. One receipt, one coherent snapshot — not a field-by-field mix
  // of several, which is how a base ends up describing a moment that never
  // existed.
  let newest: RebaseReceipt | null = null;
  const seen = new Set<string>();
  const queue = [...(op.supersedes ?? [])];
  while (queue.length > 0) {
    const id = queue.shift()!;
    if (seen.has(id)) continue; // also the cycle guard
    seen.add(id);
    const receipt = receipts.get(id);
    // Only this operation's own lineage. A receipt for somebody else's
    // operation says nothing about what THIS edit was continuing.
    if (receipt && receipt.ancestorLineage === op.lineage) {
      if (!newest || receipt.revision > newest.revision) newest = receipt;
    }
    // Keep walking through an ancestor that is still outstanding: it may
    // itself continue one that has landed.
    const live = opsById.get(id);
    if (live && live.lineage === op.lineage) queue.push(...(live.supersedes ?? []));
  }
  if (!newest || newest.revision <= op.baseRevision) {
    return { fields: op.fields, baseRevision: op.baseRevision };
  }
  const snapshot = newest;
  return {
    // EVERY field this operation carries takes its base from that one
    // snapshot, confirmed or not — a field the row did not have at that
    // revision correctly becomes absent.
    fields: op.fields.map((f) => ({
      ...f,
      base: snapshot.profile[f.key] ?? { present: false },
    })),
    baseRevision: snapshot.revision,
  };
}

/** Removes every rebase receipt. Called where the whole journal is being
 *  cleared for a verified identity reset. */
function clearRebaseReceipts(token: OwnerToken): boolean {
  const keys = scopedKeys(REBASE_PREFIX);
  if (!keys.ok) return false;
  let ok = true;
  for (const key of keys.value) if (!removeUserScopedRaw(key, token)) ok = false;
  return ok;
}

/**
 * Every unacknowledged operation. Fails closed if ANY of them is unreadable —
 * a partial view is what makes one tab overwrite another's edit.
 *
 * The order is enumeration order, which is NOT a happens-before relation
 * across tabs. Callers must resolve same-field operations by their frozen
 * bases, never by taking the last one they happened to read.
 */
/**
 * Ancestry has to be something the writer could honestly have written.
 *
 * An operation may only continue operations of its OWN lineage, and the
 * relation has to be a history — a cycle is not one. Neither shape can be
 * produced by this module, so finding one means the journal has been written
 * by something else, and every decision downstream (which value survives,
 * which operation is settled) would be taken from a forgery. It is refused
 * whole rather than repaired.
 */
/**
 * A receipt says what it answers and what was decided, for exactly the fields
 * it carries; anything else says neither. A half-formed one — an answer with
 * no decision, a decision for a field that is not there, an ordinary edit
 * carrying `resolves` — would let a reader believe a conflict was settled
 * that nobody settled.
 */
function resolutionIsWellFormed(op: {
  mode?: unknown; resolves?: unknown; resolvesPending?: unknown;
  decisions?: unknown; fields?: unknown;
}): boolean {
  const isReceipt = op.mode === 'resolve';
  const resolves = op.resolves;
  const pendingTarget = op.resolvesPending;
  const decisions = op.decisions;
  // Only a receipt may name operations it did not write — answering a
  // disagreement between two tabs is exactly that act. An ordinary edit
  // carrying any of these is corrupt or forged, and is refused here (which is
  // why ancestryIsHonest does not repeat the check).
  if (!isReceipt) {
    return resolves === undefined && decisions === undefined && pendingTarget === undefined;
  }
  // At least one target form, and every form present must be well shaped. A
  // receipt that names nothing settles nothing and would read as an answer to
  // whatever question happens to be open.
  const hasOps = Array.isArray(resolves) && resolves.length > 0;
  if (resolves !== undefined && !Array.isArray(resolves)) return false;
  if (Array.isArray(resolves) && resolves.some((v) => typeof v !== 'string' || !v)) return false;
  let pendingKeys: string[] = [];
  if (pendingTarget !== undefined) {
    if (!pendingTarget || typeof pendingTarget !== 'object' || Array.isArray(pendingTarget)) return false;
    const t = pendingTarget as { mutationId?: unknown; keyVersions?: unknown };
    if (typeof t.mutationId !== 'string' || !t.mutationId) return false;
    if (!t.keyVersions || typeof t.keyVersions !== 'object' || Array.isArray(t.keyVersions)) return false;
    // Only the schema's own properties. Silently stripping an unknown one
    // during parse means acting on a target a newer build wrote and this one
    // does not fully understand.
    if (Object.keys(t).some((k) => k !== 'mutationId' && k !== 'keyVersions')) return false;
    const versions = t.keyVersions as Record<string, unknown>;
    pendingKeys = Object.keys(versions);
    if (pendingKeys.length === 0) return false;
    if (pendingKeys.some((k) => !k)) return false;
    // SAFE integers: two distinct JSON values beyond 2^53 parse to the same
    // double, and these numbers exist to make an exact tuple comparison mean
    // something. Aliasing here would let one question's answer match another.
    if (pendingKeys.some((k) => {
      const v = versions[k];
      return typeof v !== 'number' || !Number.isSafeInteger(v) || v < 0;
    })) return false;
  }
  if (!hasOps && pendingKeys.length === 0) return false;
  if (!decisions || typeof decisions !== 'object' || Array.isArray(decisions)) return false;
  const decided = decisions as Record<string, unknown>;
  // The field list is validated in its own right further down, but this runs
  // first and must not trip over a shape that has not been checked yet: a
  // receipt whose "fields" are nulls has to be refused, not thrown on.
  const fields = op.fields;
  if (!Array.isArray(fields)) return false;
  if (fields.some((f) => !f || typeof f !== 'object' || typeof (f as { key?: unknown }).key !== 'string')) {
    return false;
  }
  const fieldKeys = (fields as Array<{ key: string }>).map((f) => f.key);
  const keys = new Set(fieldKeys);
  // A field listed twice makes "what did this receipt decide for that key"
  // ambiguous, and set-size equality below would happily accept it against a
  // decisions map that names it once.
  if (fieldKeys.length !== keys.size) return false;
  const decidedKeys = Object.keys(decided);
  if (decidedKeys.length !== keys.size) return false;
  if (!decidedKeys.every((k) => keys.has(k) && (decided[k] === 'local' || decided[k] === 'cloud'))) {
    return false;
  }
  if (pendingKeys.length === 0) return true;
  // Every pending-named key must be one this receipt decides.
  if (!pendingKeys.every((k) => keys.has(k))) return false;
  // And with NO operation ids to fall back on, the pending target must cover
  // the whole receipt exactly. A field left unbound by either route is one
  // nothing can match later, and it becomes an independent value chain the
  // next reader replays as an ordinary edit.
  return hasOps || pendingKeys.length === keys.size;
}

function ancestryIsHonest(ops: readonly JournalOp[]): boolean {
  const byId = new Map(ops.map((op) => [op.opId, op]));
  for (const op of ops) {
    for (const ancestorId of op.supersedes ?? []) {
      const ancestor = byId.get(ancestorId);
      // Already acknowledged and gone: nothing to check, and nothing wrong.
      if (!ancestor) continue;
      if (ancestor.lineage !== op.lineage) return false;
    }
  }
  // No cycles. Depth-first with an explicit path: revisiting a node that is
  // NOT on the current path is an ordinary diamond — two later edits both
  // continuing the same ancestor, which this module writes routinely — while
  // revisiting one that IS on the path is an operation that descends from
  // itself.
  const finished = new Set<string>();
  const onPath = new Set<string>();
  const visit = (start: string): boolean => {
    const stack: Array<{ id: string; entering: boolean }> = [{ id: start, entering: true }];
    while (stack.length > 0) {
      const frame = stack.pop()!;
      if (!frame.entering) {
        onPath.delete(frame.id);
        finished.add(frame.id);
        continue;
      }
      if (onPath.has(frame.id)) return false;
      if (finished.has(frame.id)) continue;
      onPath.add(frame.id);
      stack.push({ id: frame.id, entering: false });
      const node = byId.get(frame.id);
      for (const next of [...(node?.supersedes ?? []), ...(node?.resolves ?? [])]) {
        stack.push({ id: next, entering: true });
      }
    }
    return true;
  };
  for (const op of ops) if (!finished.has(op.opId) && !visit(op.opId)) return false;
  return true;
}

export function readOutstandingOps(): JournalResult<JournalOp[]> {
  // Settles this document's lineage on the way past, so a window that only
  // ever READS the journal — the user opens the form, changes nothing —
  // still discards the lineage it inherited from the window that opened it.
  // Otherwise that inherited id survives for this document's own reload to
  // pick up, and the reload would claim the other window's unsent edits.
  getJournalLineageId();
  const keys = opKeys();
  if (!keys.ok) return keys;
  const acked = readAckedOpIds();
  if (!acked.ok) return acked;
  // A REBASE RECEIPT is an acknowledgement too. It is written before the
  // ancestor is settled precisely so a crash in between cannot lose the
  // ancestry; the cost is that the ancestor's key may still be sitting there.
  // It has already landed in the cloud — re-sending it would be a second write
  // of a value the row already holds, aimed at a revision that has moved.
  const receipts = readRebaseReceipts();
  if (!receipts.ok) return receipts;
  const out: JournalOp[] = [];
  for (const storageKey of keys.value) {
    const parsedOp = parseOp(readUserScopedRaw(storageKey), storageKey);
    if (!parsedOp.ok) return parsedOp;
    const id = parsedOp.value.opId;
    if (!acked.value.has(id) && !receipts.value.has(id)) out.push(parsedOp.value);
  }
  if (!ancestryIsHonest(out)) {
    return { ok: false, reason: 'journal ancestry is not a history this writer could have produced' };
  }
  return { ok: true, value: out };
}

/**
 * Marks operations as consumed. MUST be called inside withProfileLock.
 *
 * Two phases, in this order: record the ids, THEN delete their keys. A crash
 * in between leaves an operation that is present but acked — readers skip it,
 * and the next settle removes it. The reverse order would lose the ack and
 * re-send a write that already landed.
 *
 * It only ever touches the keys it was given, so an operation another tab
 * appended a microsecond ago — a different key entirely — is untouched.
 */
export function settleJournalOps(opIds: readonly string[], token: OwnerToken): boolean {
  if (!isOwnerTokenValid(token, token.uid)) return false;
  const acked = readAckedOpIds();
  // An ack set this browser could not READ is not an empty one. Reporting
  // success here would tell the caller the cleanup is finished while the ids
  // it names are still on disk.
  if (!acked.ok) return false;
  // Called with nothing new, and nothing left over from a previous attempt:
  // genuinely finished.
  //
  // An EMPTY id list with a surviving ack is the other case, and it is not
  // nothing to do. Phase one records the ids and phase two removes their
  // keys; a crash or a failed removal in between leaves ids that readers
  // already skip — so they can never be rediscovered as "finished" work — and
  // whose keys nobody is left to delete. This is the resume for exactly that,
  // and it is why callers may hand over an empty list.
  if (opIds.length === 0 && acked.value.size === 0) return true;
  const merged = new Set([...acked.value, ...opIds]);
  if (merged.size !== acked.value.size
    && !writeUserScopedRaw(ACK_KEY, JSON.stringify([...merged]), token)) return false;

  // Phase two: remove the operations themselves. removeUserScopedRaw reads
  // back, so its `true` means "verifiably gone" and covers the already-absent
  // case — deciding by `readUserScopedRaw(...) === null` would not, because
  // null is also what a blocked owner and a throwing read return, and this
  // would then drop the ack for an operation still sitting on disk.
  const stillPresent = new Set<string>();
  for (const id of merged) {
    if (!removeUserScopedRaw(`${OP_PREFIX}${id}`, token)) stillPresent.add(id);
  }
  // The ack is kept for exactly the operations that are still there; it is
  // only cleared once every one of them is verifiably gone.
  if (stillPresent.size === 0) return removeUserScopedRaw(ACK_KEY, token);
  // Narrowed to what is left, so the next attempt knows exactly what it owes
  // — and REPORTED AS UNFINISHED. Returning the success of that bookkeeping
  // write would say the settlement is done while the operations it names are
  // still on disk, counting toward the cap, invisible to every reader
  // (acked ids are skipped) and therefore impossible to rediscover.
  writeUserScopedRaw(ACK_KEY, JSON.stringify([...stillPresent]), token);
  return false;
}

/** Drops every operation and the ack set. MUST be called inside
 *  withProfileLock. Used when an account's local data is deliberately
 *  abandoned (a merged-away identity). */
export function clearJournal(token: OwnerToken): boolean {
  const keys = opKeys();
  if (!keys.ok) return false;
  let ok = true;
  for (const storageKey of [...keys.value, ACK_KEY]) {
    if (!removeUserScopedRaw(storageKey, token)) ok = false;
  }
  // The receipts go with it. This is the ONLY safe bulk removal: a scan that
  // sees no descendant cannot prove one is not being appended at that instant,
  // so nothing narrower than a verified identity reset may drop them.
  if (!clearRebaseReceipts(token)) ok = false;
  return ok;
}

// ---------------------------------------------------------------------------
// Cross-tab serialization
// ---------------------------------------------------------------------------

type LockManager = {
  request: (name: string, opts: { mode: 'exclusive' }, fn: () => Promise<unknown>) => Promise<unknown>;
};

/** ONE name for every account, and the SAME name the identity transition
 *  takes — see PRIVATE_STORAGE_LOCK in identity-owner.ts. A transition that
 *  used its own lock would serialize against nothing: the whole point is that
 *  a tab holding private state cannot have the browser change hands underneath
 *  it mid-critical-section. */
const PROFILE_STORAGE_LOCK = PRIVATE_STORAGE_LOCK;

function lockManager(): LockManager | null {
  if (typeof navigator === 'undefined') return null;
  const locks = (navigator as unknown as { locks?: LockManager }).locks;
  return locks && typeof locks.request === 'function' ? locks : null;
}

export function hasCrossTabLock(): boolean {
  return lockManager() !== null;
}

export type LockedOutcome<T> =
  | { ok: true; value: T }
  /** The browser cannot serialize across tabs at all. */
  | { ok: false; reason: 'no-lock' }
  /** THIS owner's local realm is not confirmed (signed out mid-flight, a
   *  clear that could not be verified). The caller's own failure — report it. */
  | { ok: false; reason: 'abandoned' }
  /** Somebody else owns the browser now. The caller's news is nobody's:
   *  discard it silently, and do not read the new owner's state on its
   *  behalf. */
  | { ok: false; reason: 'superseded' };

/**
 * Runs `fn` with exclusive access to this browser's profile storage, across
 * tabs. The lock is held ONLY for reading the journal + envelope and writing
 * the result — a network round-trip must happen outside it and re-enter
 * through another call, because holding a lock across an unbounded await is
 * how one offline tab freezes every other one.
 *
 * Identity is checked twice: once before asking (cheap) and once after the
 * wait (necessary — the wait is unbounded, and a sign-out during it means
 * every fixed-name key below now belongs to somebody else).
 */
/**
 * Why this token may not act, or null when it may.
 *
 * The two failures are not interchangeable. 'superseded' means somebody else
 * owns the browser now: the caller's news is nobody's, and it must be dropped
 * in silence. 'abandoned' means THIS owner is still current but its local
 * realm is unconfirmed — the caller's own failure, which it has to be told
 * about. Collapsing them either shows one user an error about another's
 * account, or swallows a real failure as if it belonged to somebody else.
 */
function ownerFailure(token: OwnerToken): 'superseded' | 'abandoned' | 'no-lock' | null {
  if (!isTokenOwnerStillCurrent(token)) return 'superseded';
  // Between the two: a browser with no lock manager cannot serialize, which
  // the authority reports by refusing every token. That is the ENVIRONMENT,
  // not this owner's realm — and telling a user their data could not be
  // confirmed when the truth is that their browser has no Web Locks sends
  // them looking for a problem with their account.
  if (!hasSerializationBackend()) return 'no-lock';
  if (!isOwnerTokenValid(token, token.uid)) return 'abandoned';
  return null;
}

export async function withProfileLock<T>(
  token: OwnerToken,
  fn: () => Promise<T> | T,
): Promise<LockedOutcome<T>> {
  // Owner currency FIRST, before the lock-manager probe. A browser without
  // Web Locks would otherwise classify a SUPERSEDED token as 'no-lock', and
  // every caller's no-lock fallback reads the current owner's state on the
  // old owner's behalf — the availability of a lock API has nothing to do
  // with whether this caller still exists.
  //
  // 'superseded' and 'abandoned' are different failures: the first means
  // somebody else owns the browser now (the caller's news is nobody's), the
  // second means THIS owner's local realm is not confirmed (the caller's own
  // failure, which it must be told about).
  const before = ownerFailure(token);
  if (before) return { ok: false, reason: before };
  const locks = lockManager();
  /* c8 ignore next -- ownerFailure already reported 'no-lock' above */
  if (!locks) return { ok: false, reason: 'no-lock' };
  // Not a default of 'abandoned': waiting for the lock is exactly when the
  // owner is most likely to move, and mislabelling that as this user's own
  // failure surfaces an error banner for an account that is no longer here.
  let result: LockedOutcome<T> = { ok: false, reason: 'superseded' };
  await locks.request(PROFILE_STORAGE_LOCK, { mode: 'exclusive' }, async () => {
    // Re-classified after the WAIT — which can be arbitrarily long.
    const waited = ownerFailure(token);
    if (waited) { result = { ok: false, reason: waited }; return; }
    const value = await fn();
    // And AGAIN after the body: `fn` may itself await, and an identity change
    // during it makes whatever it produced the wrong account's news.
    const after = ownerFailure(token);
    if (after) { result = { ok: false, reason: after }; return; }
    result = { ok: true, value };
  });
  return result;
}
