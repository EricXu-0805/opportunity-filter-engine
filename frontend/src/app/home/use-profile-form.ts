'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import type { ProfileData, ResumeParseResponse, SkillWithLevel } from '@/lib/types';
import { getStats, parseGitHubProfile } from '@/lib/api';
import {
  captureOwnerToken,
  isOwnerScopedLoadError,
  isOwnerTokenValid,
  isTokenOwnerStillCurrent,
  type OwnerToken,
} from '@/lib/identity-owner';
import { clearMatchCache } from '@/lib/match-cache';
import { normalizeProfileForRelease } from '@/lib/release-scope';
import { STORAGE_KEYS, HOME_SCHOOL_EVENT } from '@/lib/storage-keys';
import { bySlug } from '@/lib/schools';
import { onAuthChange } from '@/lib/supabase';
import {
  flushPendingProfileWrite,
  resolveProfileConflict,
  makeConflictPrompt,
  narrowConflictPrompt,
  getDirtyProfileKeys,
  hasConfirmedProfileRevision,
  HOME_FORM_WRITER,
  recordProfileIntent,
  hydrateProfile,
  markSkillAdditions,
  refreshConflictQuestion,
  markSkillsReplaced,
  PROFILE_KEYS,
  stageProfilePatch,
  type ProfileConflict,
  type ProfileConflictRefresh,
  type ProfileHydration,
  makeProfileViewSnapshot,
  withRenderedProfile,
  type ProfileSaveResult,
  type ProfileViewSnapshot,
  type ProfileConflictPrompt,
} from '@/lib/profile-sync';
import { decodeProfileWithKeys, buildShareUrl } from '@/lib/profile-share';
import { DEFAULT_PROFILE, SEEKING_TYPES, type HydrationState, type SaveStatus, type TFunc } from './types';

/** Who a rendered screen belongs to: the owner it was issued for and the
 *  identity generation it was built under. Immutable — an action carries the
 *  one its screen already had, never one captured at click time. */
type ScreenOrigin = { token: OwnerToken; generation: number };

/**
 * What a save result was DECIDED to be at the moment it was handled.
 *
 * Taken once and never revisited. The alternative — re-checking conditions in
 * the caller's own await continuation — is how a browser that was refused
 * because it could not vouch for its own data gets to clear a cache and
 * navigate half a millisecond later, when the marker happens to have been
 * repaired. Whether that repair happened is irrelevant: the result was
 * refused when it was read, and refused is what it stays.
 */
type ProfileDisposition = 'adopted' | 'device-failed' | 'stale';
const ADOPTED: ProfileDisposition = 'adopted';
const DEVICE_FAILED: ProfileDisposition = 'device-failed';
const STALE: ProfileDisposition = 'stale';

const VALID_GRADES = new Set(['Freshman', 'Sophomore', 'Junior', 'Senior', 'Masters', 'PhD']);
const VALID_SEEKING = new Set<string>(SEEKING_TYPES);
const DEFAULT_SEARCH_WEIGHT = 50;

/** Pure: returns `base` itself when the query carries no applicable prefill,
 *  so callers can tell "nothing changed" by reference and keep treating the
 *  value as the hydrated (not user-edited) profile. */
function applyPrefill(
  params: URLSearchParams | ReadonlyURLSearchParams,
  base: ProfileData,
): ProfileData {
  const grade = params.get('prefill_year');
  const seeking = params.get('prefill_seeking');
  if (!grade && !seeking) return base;

  const next = { ...base };
  let changed = false;
  if (grade && VALID_GRADES.has(grade) && !base.grade) {
    next.grade = grade;
    changed = true;
  }
  if (seeking && VALID_SEEKING.has(seeking)) {
    const existing = base.seeking_types ?? [];
    if (!existing.includes(seeking)) {
      next.seeking_types = [...existing, seeking];
      changed = true;
    }
  }
  return changed ? next : base;
}

type ReadonlyURLSearchParams = ReturnType<typeof useSearchParams>;

export interface UseProfileFormResult {
  profile: ProfileData;
  setProfile: React.Dispatch<React.SetStateAction<ProfileData>>;
  searchWeight: number;
  setSearchWeight: (v: number) => void;
  oppCount: number | null;
  lastUpdated: string | null;
  ghLoading: boolean;
  ghStatus: string | null;
  sharedBanner: string | null;
  dismissSharedBanner: () => void;
  shareCopied: boolean;
  saveStatus: SaveStatus;
  /** Replays the last save that did not fully land (see 'cloud-failed',
   *  'device-failed' and 'error'). Deliberately CANNOT resolve a conflict:
   *  a locked key is never re-sent by an automatic retry. */
  retryCloudSave: () => void;
  /** Whether `retryCloudSave` currently has a write to replay. False means
   *  there is nothing behind the button, so the button must not be drawn —
   *  a failure with no armed retry is reported without one. */
  canRetrySync: boolean;
  /** The fields another device changed underneath this form. Non-empty only
   *  while saveStatus is 'conflict'. */
  conflictKeys: string[];
  /** What is actually in dispute, per field: each candidate value, the tab
   *  that wants it, and what the stored row holds. Render this — the answer
   *  is bound to it. */
  conflicts: ProfileConflict[];
  /** "Keep what I typed", for the given fields (all of them by default) —
   *  re-sent against the revision that is current now. */
  keepMyChanges: (keys?: readonly string[]) => void;
  /** "Use the other device's version", for the given fields (all of them by
   *  default). */
  useCloudVersion: (keys?: readonly string[]) => void;
  /** A generate-matches submit is in flight; the action is unavailable
   *  until it settles (it navigates on success). */
  isSubmitting: boolean;
  /** Whether this identity's stored row has been read yet. Nothing on the
   *  form is persisted — not by the autosave, not by submit — until it is
   *  'ready', so the UI must not offer to generate matches before then. */
  hydrationState: HydrationState;
  isValid: boolean;
  /** Increments on every identity transition this form observes. Mount it as
   *  a React `key` on any subtree holding identity-private local state of its
   *  own (the resume uploader's filename + "on file" badge) so the previous
   *  account's state is discarded rather than re-labelled. */
  identityGeneration: number;
  /**
   * The hydration this form is DISPLAYING, as one immutable value: the row,
   * the revision it is, and the identity it was accepted for. Replaced only
   * when a new hydration is accepted (or cleared, on an identity transition)
   * — never refreshed from storage underneath the screen.
   *
   * Surfaces that write a field on a click (the school switcher) act against
   * this and nothing else. A pair they re-read at click time would carry
   * whatever another tab has written since; a pair they captured at mount
   * would still be the previous account's after a switch.
   *
   * Null means no view has been accepted yet — there is nothing to write
   * against, and callers must fail closed rather than invent a base.
   */
  viewSnapshot: ProfileViewSnapshot | null;
  update: <K extends keyof ProfileData>(key: K, value: ProfileData[K]) => void;
  handleSubmit: () => void;
  handleShare: () => Promise<void>;
  handleResumeParsed: (data: ResumeParseResponse) => void;
  /** The user removed the résumé on file: its text and the coursework
   *  extracted from it stop being part of the profile (and therefore of
   *  every match request). Skills and interests it contributed STAY —
   *  they are indistinguishable from ones typed or imported from GitHub,
   *  and silently deleting those would destroy the user's own work. */
  handleResumeRemoved: () => void;
  handleGitHubImport: () => Promise<void>;
}

/** Append skills whose names aren't already present (case-sensitive match,
 * mirroring the existing import handlers). Pure — defined at module scope so it
 * isn't a hook dependency. */
function mergeSkills(existing: SkillWithLevel[], incoming: SkillWithLevel[]): SkillWithLevel[] {
  const names = new Set(existing.map((s) => s.name));
  return [...existing, ...incoming.filter((s) => !names.has(s.name))];
}

// Free-text fields where a person TYPES, one keystroke at a time. Every other
// field changes in one action — a select, a chip, a slider, a pasted URL —
// and records one operation per action as it always has.
const TYPED_KEYS: ReadonlySet<keyof ProfileData> = new Set<keyof ProfileData>(['research_interests']);
// How long the typing has to pause before the burst's final value is written
// down. Shorter than the 1.5 s autosave debounce by design: the journal is
// the crash record, the autosave is the send.
const TYPING_BURST_MS = 400;

export function useProfileForm(t: TFunc): UseProfileFormResult {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [profile, setProfile] = useState<ProfileData>(DEFAULT_PROFILE);
  const [searchWeight, setSearchWeight] = useState(DEFAULT_SEARCH_WEIGHT);
  const [oppCount, setOppCount] = useState<number | null>(null);
  const [lastUpdated, setLastUpdated] = useState<string | null>(null);
  const [ghLoading, setGhLoading] = useState(false);
  const [ghStatus, setGhStatus] = useState<string | null>(null);
  const [sharedBannerVisible, setSharedBannerVisible] = useState(false);
  const [shareCopied, setShareCopied] = useState(false);
  // Which share this screen is currently showing the result of, and that
  // share's own timer. Both retired by an identity transition and by unmount.
  const shareRequestRef = useRef(0);
  const shareTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [saveStatus, publishSaveStatus] = useState<SaveStatus>('idle');
  // How many times the status line has been said.
  //
  // A delayed callback that only re-checks the identity, the intent and the
  // edit clock cannot tell "the statement I published is still up" from "the
  // same operation has since replaced it": a submit whose write landed and
  // whose cache invalidation then failed moves saved → error under one
  // unchanged intent, and a partial answer's remainder rebuild moves saved →
  // conflict the same way. Every publication advances this, so a delayed
  // callback can name the exact statement it was armed for.
  const saveStatusVersionRef = useRef(0);
  /** The ONLY way this form's status line moves. */
  const setSaveStatus = useCallback((status: SaveStatus) => {
    saveStatusVersionRef.current += 1;
    publishSaveStatus(status);
  }, []);
  const [isSubmitting, setIsSubmitting] = useState(false);
  // Synchronous companion to isSubmitting: two clicks in the same tick both
  // see the old state, and the second submit's own GitHub request would
  // invalidate the first's import while the first still went on to write,
  // clear the cache and navigate with no skills merged.
  const submittingRef = useRef(false);
  const [hydrationState, setHydrationState] = useState<HydrationState>('loading');
  // The synchronous companion: a submit landing in the same tick as a failed
  // read must see the failure, not the state React has yet to commit.
  const hydrationStateRef = useRef<HydrationState>('loading');
  const [viewSnapshot, setViewSnapshot] = useState<ProfileViewSnapshot | null>(null);
  // The view that was on screen when the CURRENT conflict question was
  // published. An answer belongs to it and to nothing else.
  /**
   * How many times the person has TOUCHED each field, and the form as a whole.
   *
   * Value equality cannot stand in for this: a field typed away and typed
   * back holds what it held, and an answer older than those keystrokes would
   * be drawn over the person's own last word as though nothing had happened.
   * Bumped synchronously at the edit, so a response landing in the same tick
   * still sees it.
   */
  const fieldEpochRef = useRef<Map<string, number>>(new Map());
  const editEpochRef = useRef(0);
  /** Every listed field's edit count, RIGHT NOW. Taken when an async read is
   *  issued, so what comes back can be told apart from what the person typed
   *  while it was running. */
  // While a shared draft is on screen, NOTHING about it is persisted: the
  // banner promises the visitor's own saved profile stays untouched until
  // they press Generate, and an autosave (or an unmount flush) of their
  // tweaks to someone else's profile would break that promise in the one
  // place they cannot see. Cleared by the Generate that deliberately saves
  // the draft, and by any real identity transition.
  const shareDraftActiveRef = useRef(false);
  // Fields the visitor changed WHILE a shared draft was on screen. Memory
  // only: a draft is somebody else's profile, and recording it in this
  // account's journal would make it durable, flushable and — after a reload
  // that finds a foreign origin — savable to their row without them ever
  // pressing Generate. Generate is what converts these into one intent.
  const draftTouchedRef = useRef<Set<keyof ProfileData>>(new Set());
  // An edit is not an edit until it is DURABLE. When the journal write fails
  // — private mode, a full quota — the KEYS are remembered here (not the
  // values: the form on screen still holds those), so the next attempt can
  // record them again. Without this the edit is silently nowhere: not in the
  // journal, not in the cloud, and not replayable by Retry.
  const unrecordedRef = useRef<Set<keyof ProfileData>>(new Set());
  /** Fields no coordinator read can account for: a shared draft's edits never
   *  reach the journal, and a key whose journal write failed is not in it
   *  either. */
  const unrepresentedNow = useCallback(() => new Set<string>([
    ...(shareDraftActiveRef.current ? draftTouchedRef.current : []),
    ...unrecordedRef.current,
  ] as string[]), []);
  const epochsNow = useCallback(
    (keys: readonly string[]) => new Map(
      keys.map((k) => [k, fieldEpochRef.current.get(k) ?? 0] as const),
    ),
    [],
  );
  const bumpEditEpochs = useCallback((keys: Iterable<string>) => {
    let any = false;
    for (const key of keys) {
      fieldEpochRef.current.set(key, (fieldEpochRef.current.get(key) ?? 0) + 1);
      any = true;
    }
    if (any) editEpochRef.current += 1;
  }, []);
  /** THE published question, whole: the view it was asked from and the exact
   *  disagreement, frozen together. Home used to keep the origin and the list
   *  as two independently mutable pieces, which is a timing window in which an
   *  answer can be assembled from one screen's view and another's values. The
   *  list and keys below are DERIVED from this and written nowhere else. */
  const conflictPromptRef = useRef<ProfileConflictPrompt | null>(null);
  /** The published list, synchronously. React state is committed later, and
   *  a per-field answer landing in between must act on what is really on
   *  screen. */
  const conflictsRef = useRef<ProfileConflict[]>([]);
  /** `applySaveResult` rebuilds a conflict through the refresh handler, and
   *  that handler reports its continued flush back through `applySaveResult`.
   *  One of the two has to be reached indirectly; this is it. */
  const applyConflictRefreshRef = useRef<
    | ((
      refreshed: ProfileConflictRefresh,
      asked: readonly string[],
      token: OwnerToken,
      generation: number,
      intent: number,
      fence: {
        atOperation: ReadonlyMap<string, number>;
        atIssue: ReadonlyMap<string, number>;
        unrepresented: ReadonlySet<string>;
        editEpochAtOperation: number;
      },
      ownsStatus: boolean,
    ) => void | ProfileDisposition | Promise<void | ProfileDisposition>)
    | null
  >(null);
  // The keys the question on screen covers, readable synchronously by a
  // handler that has to refresh it.
  const conflictKeysRef = useRef<string[]>([]);
  // Held from the click until its own result lands, with its OWN id.
  //
  // Deliberately not the global save intent: an ordinary edit or autosave
  // while a resolution is in flight advances that counter, so an
  // intent-keyed release never fires and every future conflict button stays
  // dead until the identity changes. A resolution's ownership is its own
  // sequence, which nothing but another resolution (or an identity reset)
  // can advance.
  const resolveSeqRef = useRef(0);
  const activeResolveRef = useRef<number | null>(null);
  // Keys another device changed underneath this one. Surfaced so the person
  // is told WHICH fields did not save, not just that something did not.
  const [conflictKeys, setConflictKeys] = useState<string[]>([]);
  // The disagreement AS RENDERED — candidate values, who wants them, and the
  // exact operations behind each. Answering hands this very object back, so
  // an edit another tab makes while the question is on screen is not decided
  // by a click that never saw it.
  const [conflicts, setConflicts] = useState<ProfileConflict[]>([]);
  /** Publishes a conflict question together with the view it was asked from.
   *  The two are one thing: an answer that cannot say which view showed it
   *  cannot prove it belongs to that identity or that state. */
  const publishConflicts = useCallback((
    list: ProfileConflict[],
    origin: ProfileViewSnapshot | null,
  ) => {
    // No view to ask from is no question: an answer would have nothing to
    // prove it belongs to this identity or this state, so showing controls
    // for it would be showing controls with nothing behind them.
    const prompt = list.length > 0 && origin ? makeConflictPrompt(origin, list) : null;
    conflictPromptRef.current = prompt;
    conflictsRef.current = prompt ? [...prompt.conflicts] : [];
    conflictKeysRef.current = conflictsRef.current.map((c) => c.key);
    setConflicts(conflictsRef.current);
    setConflictKeys(conflictKeysRef.current);
  }, []);

  /** Retires the question on screen and its origin together. One helper, so
   *  no path can clear the list while leaving the buttons bound to a view
   *  that is gone. */
  const retireConflictQuestion = useCallback(() => {
    conflictPromptRef.current = null;
    conflictsRef.current = [];
    conflictKeysRef.current = [];
    setConflicts([]);
    setConflictKeys([]);
  }, []);

  /** Retires exactly the fields an answer covered, and nothing else.
   *
   *  Two disagreements can be open at once — the person answers one of them.
   *  Clearing the whole list then takes the other one off the screen without
   *  anybody deciding it, and it stays locked in storage with no way back to
   *  it. */
  const retireConflictKeys = useCallback((answeredKeys: readonly string[]) => {
    // Computed from the synchronous list, not inside a state updater. An
    // updater is not the place to move refs or start another render — React
    // may run it twice, and a click landing in the same tick would read refs
    // that disagree with what was just published.
    const done = new Set(answeredKeys);
    const left = conflictsRef.current.filter((c) => !done.has(c.key));
    conflictsRef.current = left;
    conflictKeysRef.current = left.map((c) => c.key);
    // The prompt narrows with the list — same promptId, same origin view, so
    // what is left keeps exactly the authority the whole question had.
    const held = conflictPromptRef.current;
    conflictPromptRef.current = left.length > 0 && held
      ? narrowConflictPrompt(held, conflictKeysRef.current)
      : null;
    setConflicts(left);
    setConflictKeys(conflictKeysRef.current);
  }, []);
  // The synchronous companion: React state is committed later, and a click
  // landing in between must not act on a view this hook has already retired.
  const viewSnapshotRef = useRef<ProfileViewSnapshot | null>(null);
  // Who the screen belongs to BEFORE its row has landed. Captured when the
  // load is issued, never at the moment of a keystroke: another auth
  // subscriber can advance the global owner to U2 before this hook's own
  // callback runs, and the still-mounted U1 screen can take a click in that
  // window. Capturing then would hand U1's edit a perfectly valid U2 token
  // and write it into U2's journal.
  const loadingOriginRef = useRef<ScreenOrigin | null>(null);
  const saveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // A typing burst in a free-text field: the operation that opened it is
  // already on disk, the keystrokes since are owed in `unrecordedRef`, and
  // this timer writes them down when the typing pauses. See TYPED_KEYS.
  const textBurstRef = useRef<{ timer: ReturnType<typeof setTimeout> | null; origin: ScreenOrigin | null }>(
    { timer: null, origin: null },
  );
  const pendingSaveRef = useRef<ProfileData & { search_weight: number } | null>(null);
  // Captured at the moment a save intent is CREATED (the debounce timer's
  // creation, or handleSubmit's own start) — never re-captured just before
  // the save actually fires — so a stale identity's save always no-ops
  // against saveProfile's own re-verification instead of silently landing
  // under whichever identity happens to be current when the timer elapses.
  const pendingSaveOriginRef = useRef<ScreenOrigin | null>(null);
  /** The capability of the edit that is arming the debounced save. The passive
   *  effect binds to THIS rather than deriving its own: an edit made under U1
   *  must not be re-authorized as U2 merely because the effect runs later. */
  const editOriginRef = useRef<ScreenOrigin | null>(null);

  // Identity generation. Bumped by every identity TRANSITION this hook
  // observes (see the onAuthChange effect). Gates which async result may
  // still write React state — deliberately NOT the owner epoch: that epoch
  // legitimately advances during this browser's FIRST identity resolution
  // (inside loadProfile's own ensureAnonSession), so gating on it would
  // cancel the very first legitimate load. The owner token stays the gate
  // for STORAGE writes, where binding to that first resolution is exactly
  // what must not happen opportunistically.
  //
  // The ref is the always-current value every async closure compares
  // against; the state exists so callbacks handed to child components
  // (handleResumeParsed) get a NEW identity per generation, which is what
  // makes a child's in-flight work call the generation it started under.
  const identityGenerationRef = useRef(0);
  const [identityGeneration, setIdentityGeneration] = useState(0);

  // Together these answer one question — could anything on this screen belong
  // to somebody other than the person at the keyboard? It can only be someone
  // else's if a row was once accepted onto it, or if it once belonged to a
  // real account. Until then the screen is the visitor's own — defaults plus
  // whatever they typed. Read at the identity choke point (the onAuthChange
  // effect) and by editingOrigin below, which is why they live up here.
  //
  // Both are monotonic on purpose. Once either turns true it never returns,
  // so `null -> U1 -> sign out -> U2` gets the full reset the same as any
  // other switch: the exemption is available to a screen exactly once, at
  // the very beginning of its life.
  const everHadRealUidRef = useRef(false);
  const rowEverAcceptedRef = useRef(false);
  // A keystroke landed in the beat between the owner primitive advancing to
  // the browser's FIRST identity and this hook's own observation of it (the
  // onAuthChange adapter awaits the exclusive-lock owner sync between the
  // two). Such an edit is painted and buffered — dirty keys + unrecorded —
  // but authorized under NOBODY: no capability is issued, no journal entry
  // is written, no private storage is touched. The identity choke point
  // adopts the buffer when the observation arrives (the same carry branch
  // that keeps ordinary pre-auth typing), or discards it with the reset on
  // any real switch.
  const gapCarriedRef = useRef(false);

  /**
   * The immutable capability the screen on display was issued for: the view
   * this form ACCEPTED, or — before a row has landed — the origin its load
   * (or its shared draft) was issued for.
   *
   * Never a fresh capture. The global owner can already be U2 while this hook
   * still renders U1's row and still takes clicks, and a token captured in
   * that window is a perfectly valid U2 token carrying U1's intent: every
   * preflight downstream lets it through, and U1's document lands in U2's
   * journal and U2's row.
   */
  const screenOrigin = useCallback((): ScreenOrigin | null => {
    const view = viewSnapshotRef.current;
    if (view) return { token: view.token, generation: view.identityGeneration };
    return loadingOriginRef.current;
  }, []);

  /**
   * Whether `origin` still speaks for this form AND still owns the browser.
   *
   * Deliberately NOT isOwnerTokenValid: an owner whose own local realm is
   * merely unconfirmed (signed out mid-flight, a clear that could not be
   * verified) still owns their own failed action, and that is REPORTED
   * further down rather than dropped as somebody else's. Only the owner
   * actually moving on is somebody else's — uid and epoch both, since the
   * same person across a sign-out cycle is a different capability.
   */
  const ownsScreen = useCallback((origin: ScreenOrigin): boolean => (
    origin.generation === identityGenerationRef.current
    && isTokenOwnerStillCurrent(origin.token)
  ), []);

  /** The capability an action may act under, or null — the single gate every
   *  private read, durable write, stage, cache clear and navigation is
   *  behind. */
  const actingOrigin = useCallback((): ScreenOrigin | null => {
    const origin = screenOrigin();
    return origin && ownsScreen(origin) ? origin : null;
  }, [screenOrigin, ownsScreen]);

  /**
   * The capability a keystroke acts under. Same rule as every other action,
   * with one addition: before this screen has EVER been issued an origin —
   * no accepted view, no load, no adopted draft — the edit belongs to whoever
   * is current, because there is no older rendered document to speak for.
   * That window closes as soon as a load is issued and is the one place a
   * capture is legitimate (see recordIntent, which has always said so).
   */
  const editingOrigin = useCallback((): ScreenOrigin | null => {
    const held = screenOrigin();
    if (held) return ownsScreen(held) ? held : null;
    const fresh = { token: captureOwnerToken(), generation: identityGenerationRef.current };
    if (!ownsScreen(fresh)) return null;
    // FROZEN, synchronously. Capturing once for a screen that has never been
    // issued an origin is legitimate; capturing again is not. Without this
    // write-back the very next keystroke on the same screen would capture
    // afresh, and if the owner moved in between it would be the NEW owner's
    // token carrying this screen's document.
    loadingOriginRef.current = fresh;
    return fresh;
  }, [screenOrigin, ownsScreen]);
  // Bumped by every hydration. The autosave effect depends on it so a
  // hydration that carries edits still arms a save even when the merge
  // happens to leave profile/searchWeight referentially unchanged (the
  // user edited only the weight, say, and the row was empty).
  const [hydrationTick, setHydrationTick] = useState(0);
  // Set by the first live auth observation. The snapshot load below is a
  // FALLBACK for an environment where that stream never fires at all; the
  // live stream owns profile loading whenever it exists.
  const liveIdentityObservedRef = useRef(false);
  const fallbackLoadTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // A ?share= profile is content the visitor pasted into THIS tab, not the
  // previous account's private data — the first identity observation must
  // not wipe it (see the onAuthChange effect).
  const shareImportedRef = useRef(false);
  // The exact ?share= value already imported. A one-shot receipt: the
  // import effect re-runs whenever its inputs change (a locale switch used
  // to be enough), and re-decoding the same link would overwrite whatever
  // the visitor has edited since, re-raise the banner and re-arm the draft
  // gate — including after they generated from it, or after a real account
  // switch.
  const shareImportedParamRef = useRef<string | null>(null);
  // Exactly the fields the share link carried. Generate persists THESE and
  // nothing else: a shared payload has no résumé, no profile URLs and no
  // school, and writing the whole draft would blank the visitor's own.
  const shareKeysRef = useRef<(keyof ProfileData)[]>([]);
  // Tracks the GitHub URL whose skills were already imported, so submit
  // does not re-import them. Declared with the identity state (not next to
  // importGitHubSkills) because an identity transition has to clear it: the
  // receipt belongs to the identity that ran the import.
  const githubImportedUrlRef = useRef<string | null>(null);
  // Monotonic id of the import whose result is still allowed to write.
  // Bumped by each new import AND by every identity transition, so it is the
  // single answer to both "a slower earlier import must not overwrite a
  // later one" and "a previous identity's import must not write here at
  // all" — including the spinner, which a stale finally would otherwise
  // switch off underneath a newer import.
  const ghRequestRef = useRef(0);
  // Monotonic id of the save intent whose outcome may still touch the save
  // status. Saves are serialized (see PROFILE_WRITE_ID), so a slower
  // earlier one can settle while a newer edit is queued behind it — its
  // "saved" (or "error", or its 2s reset to idle) would describe work the
  // user has already superseded, on a form that is correctly still saying
  // "saving".
  const saveIntentRef = useRef(0);
  // The payload of a save whose LOCAL write landed but whose cloud write
  // threw. Kept so the user has a real retry: until it succeeds, the cloud
  // still holds the previous row, and the next load would bring it back —
  // most visibly for a résumé the user just removed.
  // The identity+token a retry would belong to, recorded when a save did not
  // fully land. The PAYLOAD is not kept here any more — the coordinator's
  // outbox owns it, so a retry replays exactly what is still unsent rather
  // than a snapshot this hook happened to hold.
  const retryableRef = useRef<{ generation: number; token: OwnerToken } | null>(null);
  // Whether a retry is actually armed, as something the UI can render.
  //
  // The affordance used to be inferred from the status word alone, so every
  // failure wording drew a button whether or not there was a write behind it
  // — a rejected conflict answer, a recovery whose payload had been dropped,
  // a retry disowned by an identity move. Clicking those returned silently.
  // The button exists exactly when the thing it would do exists.
  const [canRetrySync, setCanRetrySync] = useState(false);
  /** The ONLY way the retry affordance is armed or disarmed. */
  const armRetryable = useCallback(
    (value: { generation: number; token: OwnerToken } | null) => {
      retryableRef.current = value;
      setCanRetrySync(value !== null);
    },
    [],
  );

  // The profile/weight pair the form was last HYDRATED with (a load, the
  // share import, or an identity reset) — as opposed to edited into by the
  // user. Compared by reference, so the autosave effect below can tell the
  // two apart exactly, with no time window: the previous "ignore everything
  // for 500ms after a load" rule both re-saved hydrated data when a load
  // landed late and silently swallowed a real edit made inside the window.
  const hydratedProfileRef = useRef<ProfileData | null>(DEFAULT_PROFILE);
  const hydratedWeightRef = useRef<number | null>(DEFAULT_SEARCH_WEIGHT);
  // Edits made BEFORE this identity's row has finished loading, recorded
  // per field. Until the load settles nothing is persisted at all: writing
  // the form as it stands would push DEFAULT_PROFILE plus the one edited
  // field over a cloud row whose major/grade/skills/resume simply had not
  // arrived yet. When the row does land it becomes the base and only these
  // fields are re-applied on top of it, so the user's edit survives and
  // everything they never touched keeps the server's value.
  const dirtyKeysRef = useRef<Set<keyof ProfileData>>(new Set());
  const weightDirtyRef = useRef(false);
  const hydrationReadyRef = useRef(false);
  const profileRef = useRef(profile);
  const weightRef = useRef(searchWeight);
  const searchParamsRef = useRef(searchParams);
  useEffect(() => {
    profileRef.current = profile;
    weightRef.current = searchWeight;
  });
  useEffect(() => { searchParamsRef.current = searchParams; }, [searchParams]);

  /** Clears the form for an identity whose row has NOT loaded yet: the
   *  previous identity's values and buffered edits go immediately, but
   *  persistence stays locked (hydrationReady is deliberately left false)
   *  until that identity's own load settles. Without the split, an edit
   *  made during a slow load would be debounced straight into storage as
   *  DEFAULT_PROFILE plus that one field — over a row still in flight. */
  const resetForPendingLoad = useCallback(() => {
    // Synchronously, first: the published view described the row this form is
    // about to stop showing. Any surface still holding it (the school
    // switcher is not keyed by identity) must have nothing to act against
    // until this load is accepted — a view that outlives its own row is how
    // a write claims a base that is no longer on screen.
    setViewSnapshot(null);
    viewSnapshotRef.current = null;
    loadingOriginRef.current = null;
    // U1's un-journalled keys must not survive into U2: a later U2 autosave
    // or retry would record them as an intent U2 never made.
    unrecordedRef.current.clear();
    if (textBurstRef.current.timer !== null) clearTimeout(textBurstRef.current.timer);
    textBurstRef.current = { timer: null, origin: null };
    dirtyKeysRef.current = new Set();
    weightDirtyRef.current = false;
    shareDraftActiveRef.current = false;
    draftTouchedRef.current.clear();
    hydrationReadyRef.current = false;
    hydrationStateRef.current = 'loading';
    setHydrationState('loading');
    profileRef.current = DEFAULT_PROFILE;
    weightRef.current = DEFAULT_SEARCH_WEIGHT;
    hydratedProfileRef.current = DEFAULT_PROFILE;
    hydratedWeightRef.current = DEFAULT_SEARCH_WEIGHT;
    setProfile(DEFAULT_PROFILE);
    setSearchWeight(DEFAULT_SEARCH_WEIGHT);
  }, []);

  /**
   * Records an edit against the view this form ACCEPTED — the row the person
   * is looking at, the revision it is, and the identity it belongs to, all
   * from one moment.
   *
   * Deliberately takes no token and no baseline. Capturing a token here would
   * capture whoever owns the browser at keystroke time, not the owner whose
   * row is on screen; and letting the coordinator fall back to the newest
   * shared envelope means a second tab's save silently becomes the base of an
   * edit made against the value it replaced — the operation then claims the
   * user was editing a value they never saw, and CASes cleanly over it.
   *
   * With no accepted view there is nothing to record against. The keys are
   * remembered instead and re-recorded once a hydration lands, which is the
   * same path a failed journal write already takes.
   */
  const recordIntent = useCallback((
    next: ProfileData,
    keys: readonly (keyof ProfileData)[],
    opts: {
      mode?: 'set' | 'add-skills' | 'replace-skills';
      /** The view being accepted RIGHT NOW, for the one caller inside
       *  hydrate() that runs before it has been published. */
      view?: ProfileViewSnapshot;
      /** The capability the ACTION was admitted under. Passed by every UI
       *  entry point so one capability covers the whole action rather than
       *  each step deriving its own. */
      origin?: ScreenOrigin;
    } = {},
  ): boolean => {
    const view = opts.view ?? viewSnapshotRef.current;
    // Pre-hydration this form has observed NO row for this identity, so the
    // edit's baseline is explicitly unknown — empty at revision 0. What it
    // must never be is the shared envelope: that can be another tab's newer
    // save, and adopting it makes this edit claim it was made against a value
    // the person never saw. The edit is still recorded durably; only what it
    // says it was based on changes.
    //
    // Its OWNER is the one the loading screen was issued for, captured then.
    // Not captured here: the global owner can already be U2 while this hook
    // still shows U1 and still takes clicks, and a token captured at that
    // moment is a valid U2 token carrying U1's intent.
    // Null only before this screen's very first load has been issued — the
    // window the vulnerability cannot occur in, because it requires an
    // in-flight load whose origin is a now-superseded owner. Every identity
    // transition repopulates it (resetForPendingLoad then startLoad, in that
    // order), so after mount it always describes the screen on display.
    const origin = opts.origin ?? (view
      ? null
      : (loadingOriginRef.current
        ?? { token: captureOwnerToken(), generation: identityGenerationRef.current }));
    // A load issued for a generation this hook has already moved past: that
    // screen is gone and its edit is not this owner's news.
    if (origin && origin.generation !== identityGenerationRef.current) return false;
    const token = opts.origin ? opts.origin.token : (view ? view.token : origin!.token);
    // BEFORE anything reads storage — and only for a SUPERSEDED origin.
    //
    // recordProfileIntent begins with ensureScope and an envelope read, and
    // in the window where the shared owner primitive is already U2 while this
    // hook still holds U1's accepted view, that read is U2's data being
    // consulted on U1's behalf. Such an edit produces zero reads, zero
    // durable writes, zero network — and nothing in the unrecorded buffer
    // either, or the keys come back later as an intent U2 never made.
    //
    // Deliberately NOT isOwnerTokenValid, which also fails when this owner's
    // own local realm is merely unconfirmed (signed out mid-flight, a clear
    // that could not be verified). That is this user's own failed edit: it
    // must be remembered and REPORTED, not silently dropped as somebody
    // else's. Only the owner actually moving on is somebody else's.
    if (!isTokenOwnerStillCurrent(token)) return false;
    const observedBase = view
      ? { profile: (view.baseProfile ?? {}) as ProfileData, revision: view.revision }
      : { profile: {} as ProfileData, revision: 0 };
    const ok = recordProfileIntent(next, keys, token, {
      writer: HOME_FORM_WRITER,
      mode: opts.mode,
      observedBase,
    });
    if (!ok) for (const key of keys) unrecordedRef.current.add(key);
    return ok;
  }, []);

  /** Records whatever an earlier edit could not, from the values on screen
   *  NOW. Nothing may be sent while this returns false: a patch built from a
   *  form whose edits are not in the journal is exactly the lost update the
   *  journal exists to prevent. */
  const recordOutstandingIntents = useCallback((live: ProfileData): boolean => {
    if (unrecordedRef.current.size === 0) return true;
    if (!recordIntent(live, [...unrecordedRef.current])) return false;
    unrecordedRef.current.clear();
    return true;
  }, [recordIntent]);

  /** Settles this identity's row onto the form: the loaded row (or the
   *  defaults, for a confirmed-empty row / a failed load) is the base, and
   *  the fields the user edited while it was in flight are re-applied on
   *  top. Unlocks persistence — everything before this point was buffered
   *  in the UI only. */
  const hydrate = useCallback((hydration: ProfileHydration) => {
    const generationAtAcceptance = identityGenerationRef.current;
    // A COPY. The legacy skills upgrade below rewrites `skills` in place, and
    // the object handed in belongs to the coordinator — mutating it would
    // rewrite the confirmed row this hydration also reports as its baseline,
    // so the baseline would silently acquire a shape the row never had.
    const raw = hydration.profile
      ? { ...(hydration.profile as unknown as Record<string, unknown>) }
      : null;
    let base = DEFAULT_PROFILE;
    if (raw) {
      // A row — somebody's stored document — is now on screen. From here the
      // screen is no longer the visitor's own blank page, whoever loaded it.
      rowEverAcceptedRef.current = true;
      if (Array.isArray(raw.skills) && raw.skills.length > 0 && typeof raw.skills[0] === 'string') {
        raw.skills = (raw.skills as string[]).map((name) => ({ name, level: 'beginner' as const }));
      }
      // DEFAULT_PROFILE, never the current state: a merge over `prev` would
      // let any field this identity's own row does not define stay visible
      // from the previous one's.
      base = normalizeProfileForRelease({ ...DEFAULT_PROFILE, ...raw } as ProfileData);
    }
    const prefilled = applyPrefill(searchParamsRef.current, base);
    // A ?prefill_year=/?prefill_seeking= value is an explicit field the URL
    // asked us to set, not a default the loader produced. Before the patch
    // model it reached the row anyway (the whole document was written); now
    // it has to enter the cloud dirty ledger or it would show on screen and
    // never be saved.
    //
    // The CLOUD ledger only. dirtyKeysRef is the HYDRATION buffer — "the user
    // typed this before the row landed" — and adding a prefill to it would
    // make the merge below overwrite the prefilled value with the empty one
    // the form had a moment ago.
    const prefilledKeys: (keyof ProfileData)[] = [];
    if (prefilled !== base) {
      if (prefilled.grade !== base.grade) prefilledKeys.push('grade');
      if (prefilled.seeking_types !== base.seeking_types) prefilledKeys.push('seeking_types');
    }
    base = prefilled;
    let weight = typeof raw?.search_weight === 'number' ? raw.search_weight : DEFAULT_SEARCH_WEIGHT;

    const dirtyKeys = dirtyKeysRef.current;
    const weightDirty = weightDirtyRef.current;
    let next = base;
    if (dirtyKeys.size > 0) {
      const merged = { ...base } as Record<string, unknown>;
      const edited = profileRef.current as unknown as Record<string, unknown>;
      for (const key of dirtyKeys) merged[key as string] = edited[key as string];
      next = merged as unknown as ProfileData;
    }
    if (weightDirty) weight = weightRef.current;
    // ONE document, from here on. The weight also lives beside the profile in
    // its own state (the slider reads it there), and while the two were
    // assembled separately every consumer that took `profileRef` alone — an
    // unrelated edit republishing the view, an acknowledgement rebuilding its
    // rendered half — carried whatever the ROW said back onto a screen the
    // person had already moved. The mirror is kept in lockstep below; this
    // object is what "the profile" means.
    const live = { ...next, search_weight: weight } as ProfileData;

    // Edits carried over are NOT hydrated data — they still have to reach
    // storage, now as a complete row rather than the half-empty form they
    // were made on. A null marker means "nothing on this form counts as
    // already-persisted", which is what arms the autosave effect below.
    const carriedEdits = dirtyKeys.size > 0 || weightDirty;
    hydratedProfileRef.current = carriedEdits ? null : live;
    hydratedWeightRef.current = carriedEdits ? null : weight;
    dirtyKeysRef.current = new Set();
    weightDirtyRef.current = false;
    hydrationReadyRef.current = true;
    hydrationStateRef.current = 'ready';
    setHydrationState('ready');
    // A read that failed and then succeeded must stop saying it failed. With
    // carried edits the save this hydration arms takes the status over
    // (saving → saved/error) a moment later; without them nothing else ever
    // would, and the form would keep claiming it is not being saved.
    if (!carriedEdits) setSaveStatus('idle');
    // Synchronously, not via the passive effect below: a second hydration
    // (or an edit) can be processed before React has committed this one,
    // and a merge that read a stale ref would clone the PREVIOUS identity's
    // field values onto the new one's row.
    profileRef.current = live;
    weightRef.current = weight;
    setProfile(live);
    setSearchWeight(weight);
    setHydrationTick((n) => n + 1);
    // THE acceptance, and the ONLY place a view is published. Everything
    // downstream that needs "which row, at which revision, for which identity
    // was on screen" reads this and never storage: this is the one moment the
    // answer is known without pairing two reads taken at two times.
    //
    // `baseProfile` is the row exactly as it arrived — a field the row does
    // not have stays missing, so choosing the value the UI was already
    // defaulting to still registers as a real change. `renderedProfile` is
    // what the person can actually see: defaults filled in, prefill applied,
    // this device's unsent edits merged back on top.
    //
    // Gated twice, because a late result from a superseded identity must
    // publish NOTHING: the caller already dropped stale generations before
    // calling, and the token check catches an owner that moved on while this
    // was resolving.
    if (identityGenerationRef.current === generationAtAcceptance
      && isOwnerTokenValid(hydration.token, hydration.token.uid)) {
      // The SAME `live` the form itself was just settled onto — the published
      // view and the operations recorded against it describe one screen, not
      // two reassembled halves.
      const accepted = makeProfileViewSnapshot({
        // The CONFIRMED row, not `hydration.profile` — that one already has
        // this device's unsent edits merged in, and a baseline containing
        // unsent values would let a write claim the row already held them.
        // The CONFIRMED row, untouched: the live weight belongs to what is
        // rendered, never to what the server is said to hold.
        baseProfile: hydration.baseProfile,
        renderedProfile: live,
        revision: hydration.revision,
        token: hydration.token,
        identityGeneration: generationAtAcceptance,
        source: 'hydration',
      });
      viewSnapshotRef.current = accepted;
      setViewSnapshot(accepted);
      // Recorded HERE, against the view being accepted — not earlier against
      // whatever the shared envelope happened to hold. A prefill is an edit
      // to this row like any other and needs the same baseline.
      if (prefilledKeys.length > 0) recordIntent(prefilled, prefilledKeys, { view: accepted });
      // And anything an edit could NOT write down — a read that failed, so
      // there was no baseline to record against; a journal write that was
      // refused — finally has one. Written down HERE, synchronously, in the
      // same tick the row is accepted: this is the last moment before an
      // effect, a timer or the page being left can happen, and every one of
      // those can fail to happen at all.
      //
      // AFTER the prefill above, deliberately: a URL asked for a value, the
      // person then chose one, and the person's is the later word.
      if (unrecordedRef.current.size > 0) {
        const owed = [...unrecordedRef.current];
        // The same live document the view was published from — an INPUT to
        // the operation, never the confirmed base: that stays `accepted`.
        if (recordIntent(live, owed, { view: accepted })) {
          // Only what was actually written, and only this batch: a key added
          // to the buffer in the meantime is still owed.
          for (const key of owed) unrecordedRef.current.delete(key);
        }
      }
    }
  }, [recordIntent, setSaveStatus]);

  /** Every user-originated profile write goes through here, so "did the
   *  user touch this form while a load was in flight" is one counter rather
   *  than an inference from timers. */
  /** `intentKeys` are fields the caller DELIBERATELY set, even to a value
   *  they already had — a college switch clearing the cascaded major, for
   *  instance. Without them a shallow diff would miss the clear (the field
   *  was already empty on a not-yet-loaded form) and the row landing later
   *  would restore the major the user just invalidated. */
  /** Keeps the published view showing what is actually on screen. The base,
   *  the revision, the owner and the view's identity do not move — only a real
   *  acknowledgement advances those. Without this, a surface that builds a
   *  full document from `renderedProfile` (the school switcher) writes the
   *  values as they stood at hydration and briefly undoes an edit the person
   *  can still see. */
  const republishRendered = useCallback((rendered: ProfileData) => {
    const held = viewSnapshotRef.current;
    if (!held) return;
    const next = withRenderedProfile(held, rendered);
    viewSnapshotRef.current = next;
    setViewSnapshot(next);
  }, []);

  const editProfile = useCallback((
    value: React.SetStateAction<ProfileData>,
    intentKeys?: readonly (keyof ProfileData)[],
    /** The capability a CALLER already admitted this action under, so one
     *  capability covers the whole action. Omitted by the public alias,
     *  which admits itself. */
    actionOrigin?: ScreenOrigin,
  ) => {
    // Before the dirty set, the edit clocks, the journal and the screen: an
    // edit made on a form whose owner has moved on belongs to nobody. It is
    // not this browser's to paint, to remember, or to write down — and a
    // token captured at the keystroke would be the NEW owner's, which is how
    // one person's typing lands in another's row.
    const origin = actionOrigin ?? editingOrigin();
    // ONE exception, and it is paint-only: the first-identity gap (see
    // gapCarriedRef). The keystroke is the visitor's own on a screen that
    // has never shown anyone's row and never belonged to a real account, so
    // it stays on screen and in the buffers — but with NO capability, it may
    // not reach the journal or any private storage. The choke point settles
    // its fate moments later.
    const gapCarry = !origin
      && !everHadRealUidRef.current
      && !rowEverAcceptedRef.current
      && (screenOrigin()?.token.uid ?? null) === null;
    if (!origin && !gapCarry) return;
    if (origin) editOriginRef.current = origin;
    // Computed against the ref, not inside a state updater: an updater that
    // records dirty keys and moves refs is not a pure function (React may
    // run it twice, and a load resolving before React commits would read a
    // ref that disagrees with the keys already marked dirty). The ref is
    // this hook's synchronous source of truth; the state follows it.
    const prev = profileRef.current;
    const next = typeof value === 'function'
      ? (value as (p: ProfileData) => ProfileData)(prev)
      : value;
    const touched = new Set<keyof ProfileData>(intentKeys ?? []);
    if (next !== prev) {
      const before = prev as unknown as Record<string, unknown>;
      const after = next as unknown as Record<string, unknown>;
      for (const key of new Set([...Object.keys(before), ...Object.keys(after)])) {
        if (before[key] !== after[key]) touched.add(key as keyof ProfileData);
      }
    }
    for (const key of touched) dirtyKeysRef.current.add(key);
    bumpEditEpochs(touched as Iterable<string>);
    // DURABLE, and now — not at the debounce. The journal write happens
    // before this function returns, so a crash inside the 1.5s autosave
    // window (or a closed tab, or a second tab reading the same account) still
    // finds the edit. It also freezes the base this edit was made against, so
    // a save issued later is resolved three ways against what the user
    // actually started from rather than against whatever the row has become.
    if (touched.size > 0) {
      if (gapCarry) {
        // Remembered as owed, not journalled: recordIntent would be a
        // private write under an owner this keystroke was never made by.
        for (const key of touched) unrecordedRef.current.add(key);
        gapCarriedRef.current = true;
      } else if (shareDraftActiveRef.current) {
        for (const key of touched) draftTouchedRef.current.add(key);
      } else if (hydrationStateRef.current === 'failed') {
        // A read that FAILED means a row may well exist and this device could
        // not fetch it. Recording an operation now would freeze it against a
        // baseline nobody has seen, over a row that is really there. It stays
        // in the form and in memory until a hydration or a retry produces the
        // real one — which is what the unrecorded buffer is for.
        //
        // Deliberately NOT every not-yet-ready state: an edit made while a
        // load is still IN FLIGHT is recorded durably against an explicitly
        // unknown base, and has been since the journal existed. That survives
        // a crash; downgrading it here would trade one contract for another.
        for (const key of touched) unrecordedRef.current.add(key);
      } else if ([...touched].every((key) => TYPED_KEYS.has(key))) {
        // One operation opens the burst, synchronously — a crash a moment
        // later still finds that the edit exists and where it began. The
        // keystrokes after it are owed, not appended: each would otherwise be
        // its own immutable operation, and MAX_OUTSTANDING_OPS is 500. For a
        // visitor who has not signed in nothing ever acknowledges an
        // operation, so 500 was a LIFETIME budget of keystrokes across every
        // free-text field, and a paragraph typed past it came back truncated
        // to exactly 500 characters on reload (production, 2026-08-31 — the
        // matcher's one free-text field). The pause timer writes the burst's
        // final value down; the 1.5 s autosave and the unmount flush both
        // drain `unrecordedRef` first anyway, so nothing here can be lost to
        // either of them.
        const burst = textBurstRef.current;
        if (burst.timer !== null && burst.origin !== null && ownsScreen(burst.origin)) {
          for (const key of touched) unrecordedRef.current.add(key);
          clearTimeout(burst.timer);
        } else {
          recordIntent(next, [...touched], { origin: origin! });
        }
        burst.origin = origin!;
        burst.timer = setTimeout(() => {
          const current = textBurstRef.current;
          const owner = current.origin;
          current.timer = null;
          current.origin = null;
          // A screen that changed hands mid-burst: resetForPendingLoad has
          // already emptied the buffer, and the new owner's row is nobody
          // else's to write into.
          if (!owner || !ownsScreen(owner)) return;
          const owed = [...unrecordedRef.current].filter((key) => TYPED_KEYS.has(key));
          if (owed.length === 0) return;
          if (recordIntent(profileRef.current, owed, { origin: owner })) {
            for (const key of owed) unrecordedRef.current.delete(key);
          }
        }, TYPING_BURST_MS);
      } else {
        recordIntent(next, [...touched], { origin: origin! });
      }
    }
    if (next === prev) return;
    profileRef.current = next;
    setProfile(next);
    if (!shareDraftActiveRef.current) republishRendered(next);
  }, [bumpEditEpochs, recordIntent, republishRendered, editingOrigin, screenOrigin, ownsScreen]);

  const editSearchWeight = useCallback((value: number) => {
    // Its own entry, so its own gate: a generic-edit gate that forgot the
    // slider would leave one control writing under whoever owns the browser.
    const origin = editingOrigin();
    // Same first-identity-gap exception as editProfile: paint + buffer,
    // never journal (see gapCarriedRef).
    const gapCarry = !origin
      && !everHadRealUidRef.current
      && !rowEverAcceptedRef.current
      && (screenOrigin()?.token.uid ?? null) === null;
    if (!origin && !gapCarry) return;
    if (origin) editOriginRef.current = origin;
    weightDirtyRef.current = true;
    bumpEditEpochs(['search_weight']);
    // The LIVE document moves, exactly as it does for every other field —
    // not a mirror beside it. A weight kept only in `weightRef` left
    // `profileRef` holding the row's value, and the next unrelated edit (or
    // any acknowledgement rebuilding its rendered half from `profileRef`)
    // republished that stale value over the one the person is looking at.
    // Same object when the value did not actually move, exactly as an edit to
    // any other field is: a same-value touch is a real intent (it is recorded
    // below) but it is not a change, and handing React a fresh document for it
    // would arm a write for a slider nobody moved.
    const prev = profileRef.current;
    const next = prev.search_weight === value
      ? prev
      : ({ ...prev, search_weight: value } as ProfileData);
    weightRef.current = value;
    profileRef.current = next;
    if (gapCarry) {
      unrecordedRef.current.add('search_weight');
      gapCarriedRef.current = true;
    } else if (shareDraftActiveRef.current) {
      draftTouchedRef.current.add('search_weight');
    } else if (hydrationStateRef.current === 'failed') {
      // Same rule as every other field, and only for a read that FAILED.
      unrecordedRef.current.add('search_weight');
    } else {
      recordIntent(next, ['search_weight'], { origin: origin! });
      republishRendered(next);
    }
    if (next !== prev) setProfile(next);
    setSearchWeight(value);
  }, [recordIntent, republishRendered, editingOrigin, screenOrigin]);

  // R67 problem #4 (cross-device sync, code-side portion) + C1-R2B:
  //
  // Without this effect, the home form snapshots whatever the database
  // returned at mount time. If the user then signs in on this browser
  // (anon → permanent) or switches to a different account on the same
  // device, the form keeps showing the OLD profile until they hard-
  // reload the page. The same is true if a different device has saved
  // updates to the user's profile after this tab opened.
  //
  // LIVE-FIRST, and subscribed BEFORE the fallback snapshot load below is
  // even scheduled: every auth observation is real, including the VERY
  // FIRST one and including a first event that reports null. The previous
  // "skip the first event, the mount effect already handled this uid" rule
  // was never something this hook could know — a load started before any
  // identity is confirmed belongs to whatever resolved inside it, not to
  // the identity this event is announcing.
  //
  // A same-uid re-observation (TOKEN_REFRESHED, INITIAL_SESSION repeating
  // the identity we already hold) is deliberately NOT a transition:
  // resetting the form on every hourly token refresh would discard
  // whatever the user is typing.
  //
  // On a real transition everything this hook holds for the previous
  // identity is dropped SYNCHRONOUSLY, in the event's own tick, before any
  // await can carry it into the new identity's session: the debounced save
  // intent and its token, the GitHub import receipt and spinner, the shared
  // -profile banner, the profile on screen, the search weight, and both
  // status lines.
  /** Turns a coordinator outcome into what the person is told, and into
   *  whether a Retry is offered at all. Nothing here says "saved" for a write
   *  the cloud did not confirm. */
  /**
   * Moves the accepted baseline forward onto a row the server has confirmed.
   *
   * Atomic by construction: base, revision and owner all come from the ONE
   * acknowledgement, and the rendered half is taken from the live form at
   * this instant so a keystroke made during the round trip survives it.
   * Refused outright when the identity has moved on — a superseded owner's
   * acknowledgement is not news about the row now on screen.
   */
  /**
   * Adopts a baseline read AUTHORITATIVELY — under the shared lock, from the
   * same snapshot that produced the profile being displayed beside it.
   *
   * Deliberately not forward-only. `advanceAcceptedBase` refuses a lower
   * revision because an ACKNOWLEDGEMENT can arrive out of order and must never
   * roll the baseline back. A canonical read cannot: it is awaited in its own
   * chain, fenced on identity and intent, and describes the envelope as it
   * stands. Refusing it is how the screen ends up showing one snapshot while
   * the baseline holds another — and the next edit is then measured against a
   * row this account no longer has.
   */
  const adoptAuthoritativeBase = useCallback((
    profile: ProfileData | null,
    revision: number,
    token: OwnerToken,
    generation: number,
  ) => {
    if (generation !== identityGenerationRef.current) return;
    if (!isOwnerTokenValid(token, token.uid)) return;
    const adopted = makeProfileViewSnapshot({
      baseProfile: profile,
      renderedProfile: profileRef.current,
      revision,
      token,
      identityGeneration: generation,
      source: 'hydration',
    });
    viewSnapshotRef.current = adopted;
    setViewSnapshot(adopted);
  }, []);

  const advanceAcceptedBase = useCallback((
    profile: ProfileData | null,
    revision: number,
    token: OwnerToken,
    generation: number,
  ) => {
    if (generation !== identityGenerationRef.current) return;
    if (!isOwnerTokenValid(token, token.uid)) return;
    // Forward only. A baseline that can move backwards is one an out-of-order
    // acknowledgement can use to re-open a conflict the user already settled.
    const held = viewSnapshotRef.current;
    if (held && revision < held.revision) return;
    const advanced = makeProfileViewSnapshot({
      baseProfile: profile,
      renderedProfile: profileRef.current,
      revision,
      token,
      identityGeneration: generation,
      source: 'hydration',
    });
    viewSnapshotRef.current = advanced;
    setViewSnapshot(advanced);
  }, []);

  const applySaveResult = useCallback((
    result: ProfileSaveResult,
    token: OwnerToken,
    generation: number,
    intent: number,
    /** False for a locally-fabricated outcome (a Generate with nothing to
     *  send). Such a result carries no revision the server ever issued, so it
     *  may report status but must never move the accepted baseline. */
    fromCoordinator = true,
    /** Whether this result still owns the STATUS text and the retry button.
     *
     *  False when a newer edit has armed since — but only the wording is
     *  theirs. What the server said about the row is a fact, and the accepted
     *  baseline and the conflict list are built from it either way: dropping
     *  them because the spinner belongs to somebody else leaves the form
     *  measuring the next edit against a revision that is gone and hides a
     *  disagreement that is locked in storage. Identity is still fail-closed
     *  above; this is only about which intent gets to speak. */
    ownsStatus = true,
    /** Each involved field's edit count when the whole OPERATION began — the
     *  stage, the submit, the answer — not when some later read was issued.
     *  An edit made during the write is already in place by the time a rebuild
     *  starts, and a snapshot taken then would call it untouched. */
    epochsAtStart?: ReadonlyMap<string, number>,
    /** The form's edit count when the operation began. */
    editEpochAtStart?: number,
  ): ProfileDisposition | Promise<ProfileDisposition> => {
    // Same entry fence as the refresh handler: nothing below this line may
    // touch a screen that belongs to a different identity.
    if (generation !== identityGenerationRef.current) return STALE;
    // Split, and decided ONCE, here. Owner-currentness says whether this
    // person may be told anything at all; realm validity says whether what
    // the cloud reported may be adopted as fact. A browser that cannot vouch
    // for its own data can still be told its write did not land — leaving it
    // on 'saving' forever is the one answer that is never true — but nothing
    // it reported may move a baseline, publish a question, or license a cache
    // clear and a navigation.
    if (!isTokenOwnerStillCurrent(token)) return STALE;
    if (!isOwnerTokenValid(token, token.uid)) {
      if (ownsStatus && (editEpochAtStart === undefined
        || editEpochAtStart === editEpochRef.current)) {
        armRetryable({ generation, token });
        setSaveStatus('device-failed');
      }
      return DEVICE_FAILED;
    }
    // LIVE. `ownsStatus` was decided before this result came back; an edit
    // made since bumps the form's edit count immediately, while the save
    // intent only moves when a debounce fires 1.5s later. In that window an
    // old result would still take the wording.
    const ownsNow = ownsStatus
      && (editEpochAtStart === undefined || editEpochAtStart === editEpochRef.current);
    const say = (status: SaveStatus) => { if (ownsNow) setSaveStatus(status); };
    const armRetry = (value: { generation: number; token: OwnerToken } | null) => {
      if (ownsNow) armRetryable(value);
    };
    switch (result.status) {
      case 'saved':
      case 'already-saved':
        // The server just told us what the row IS. Advance the accepted base
        // to it, or the NEXT edit is recorded against the revision this one
        // replaced and the coordinator manufactures a conflict out of the
        // user's own consecutive keystrokes.
        //
        // Only the base half moves. `renderedProfile` is re-read from the
        // live form, so an edit made while this acknowledgement was in flight
        // stays in the document a later write builds from — an ack must not
        // roll the screen back to what it confirmed.
        if (fromCoordinator) advanceAcceptedBase(result.profile, result.revision, token, generation);
        armRetry(null);
        // The question on screen is NOT retired here. A successful write says
        // what the row now holds for the keys IT sent; it says nothing about
        // a disagreement nobody has answered, and a revision comparison
        // cannot stand in for that — a clean save at revision 9 is no verdict
        // on an unresolved question about revision 8. Retirement belongs to
        // the paths that own the exact lifecycle: the explicit resolution, an
        // authoritative hydration, and the same-snapshot refresh.
        say('saved');
        // The exact statement this badge is for. Two seconds is a long time
        // for ONE operation as well as for the owner: the submit that just
        // saved can still fail to clear its cache, and a partial answer's
        // remainder can still come back a conflict — both under this very
        // intent and edit clock. Clearing then would retire a failure the
        // person is being shown.
        //
        // The version is the whole test, and a separate "is it still 'saved'"
        // re-read would add nothing: this is captured immediately after the
        // publish above, so an unchanged version means nothing has been said
        // since — and if `say` declined to publish at all, the intent and
        // edit-epoch checks below have already returned.
        const armedAtVersion = saveStatusVersionRef.current;
        setTimeout(() => {
          if (generation !== identityGenerationRef.current) return;
          // Two seconds is long enough for the owner to change. This badge
          // belongs to the screen that saved, and clearing it on a screen
          // that is no longer theirs is still a write onto it.
          if (!isTokenOwnerStillCurrent(token)) return;
          if (intent !== saveIntentRef.current) return;
          if (editEpochAtStart !== undefined && editEpochAtStart !== editEpochRef.current) return;
          // Something has spoken since — including this same operation.
          if (saveStatusVersionRef.current !== armedAtVersion) return;
          setSaveStatus('idle');
        }, 2000);
        return ADOPTED;
      case 'local-only':
      case 'staged-local':
        // Durably on this device, and honestly labelled as such: there is
        // either no backend right now, or no row to patch yet.
        armRetry(null);
        say('device-only');
        return ADOPTED;
      case 'conflict': {
        // NOT published as it arrived, and the baseline is NOT moved from it.
        //
        // A conflict payload describes the row as it looked to ONE attempt.
        // Putting it straight on screen lets a late answer replace a question
        // about a newer row, and lets a payload about one key evict a live
        // question about another. Neither is something a revision comparison
        // can sort out: the only thing that knows what is actually in dispute
        // is the canonical locked state.
        //
        // So this asks for exactly that, about the UNION of what is already
        // being shown and what has just arrived — dropping either side is how
        // a disagreement goes invisible — and the rebuilt answer is what
        // reaches the screen.
        armRetry({ generation, token });
        say('conflict');
        const union = [...new Set([
          ...conflictKeysRef.current,
          ...result.conflicts.map((c) => c.key),
        ])];
        // Operation-start where we have it, read-start for anything the
        // operation did not name.
        const atIssue = epochsNow(union);
        const atOperation = new Map([...atIssue, ...(epochsAtStart ?? new Map())]);
        const unrepresented = unrepresentedNow();
        const editEpochAtOperation = editEpochAtStart ?? editEpochRef.current;
        return refreshConflictQuestion(union, token).then((refreshed) => {
          // The full gate AFTER the await, not before it: the identity can
          // move while the rebuild runs, and applying then belongs to an
          // account that is no longer looking at this screen.
          if (generation !== identityGenerationRef.current) return;
          if (!isOwnerTokenValid(token, token.uid)) return;
          return applyConflictRefreshRef.current?.(
            refreshed, union, token, generation, intent,
            { atOperation, atIssue, unrepresented, editEpochAtOperation }, ownsNow,
          );
        }).then(() => STALE);
      }
      case 'missing':
        // The row is gone. Retrying would recreate a profile the account no
        // longer has, so no Retry is offered — a reload is the way out.
        armRetry(null);
        say('stale');
        return STALE;
      case 'device-failed':
        // phase 'confirm' means the CLOUD has it and this browser does not;
        // phase 'stage' means nothing was sent at all.
        armRetry({ generation, token });
        say(result.phase === 'confirm' ? 'device-failed' : 'error');
        return DEVICE_FAILED;
      case 'blocked':
        armRetry({ generation, token });
        say('error');
        return DEVICE_FAILED;
      case 'superseded':
        // A newer save owns the status; this one has nothing to say.
        return STALE;
      case 'abandoned':
        // NOT the same thing. `abandoned` is this write reporting that the
        // device never confirmed it — true whatever the marker looks like by
        // now, so a realm that recovered in the meantime does not turn it
        // into a success. Said out loud, and retryable.
        armRetry({ generation, token });
        say('device-failed');
        return DEVICE_FAILED;
      default:
        armRetry({ generation, token });
        say('cloud-failed');
        return DEVICE_FAILED;
    }
  }, [advanceAcceptedBase, epochsNow, publishConflicts, retireConflictQuestion, unrepresentedNow, armRetryable, setSaveStatus]);

  /**
   * Everything Home does with a conflict refresh, taken FROM the refresh.
   *
   * No storage read: the result already carries the row, the accepted base,
   * the revision and the question, all out of the one critical section that
   * produced them. Reconstructing any of it here would pair a value from that
   * moment with a value from this one.
   *
   * Every variant is handled explicitly. The bare array this replaced could
   * not distinguish "settled" from "the lock was unavailable", and reading
   * both as settled retires a prompt whose answer is still owed.
   */
  const applyConflictRefresh = useCallback((
    refreshed: ProfileConflictRefresh,
    /** The fields the question was about. Only these are taken from the
     *  refreshed row: anything else on the form was typed after the prompt
     *  went up and is nobody's business but the person who typed it. */
    asked: readonly string[],
    token: OwnerToken,
    generation: number,
    intent: number,
    /**
     * TWO clocks, because two different things go stale at different moments.
     *
     * `atOperation` is each field's edit count when the whole operation began
     * — the stage, the submit, the answer. It decides what may be PAINTED and
     * what stays dirty: anything typed after the operation started is newer
     * than everything the operation can produce.
     *
     * `atIssue` is the count when this particular READ went out. It decides
     * whether the QUESTION that came back is still about the value on screen.
     * An edit that reached the journal BEFORE the read is one the coordinator
     * saw, so the question it returned already accounts for it.
     *
     * `unrepresented` are fields the coordinator cannot see at all — a shared
     * draft's untracked edits, keys whose journal write failed. Their
     * questions are stale however the counts compare, because the read never
     * had them.
     */
    fence: {
      atOperation: ReadonlyMap<string, number>;
      atIssue: ReadonlyMap<string, number>;
      unrepresented: ReadonlySet<string>;
      /** The form's edit count when the operation began, compared LIVE here.
       *  A frozen boolean was decided before the rebuild ran; an edit made
       *  during it bumps no save intent on a shared draft, and the old chain
       *  would take the wording back. */
      editEpochAtOperation: number;
    },
    /** Whether the OPERATION this rebuild belongs to still speaks for the
     *  form. Passed in rather than recomputed: an edit that bumps no save
     *  intent — a shared draft — would otherwise let an old submit take the
     *  wording back. */
    ownsOperation: boolean,
  ) => {
    // The helper's OWN fence, before any ref, state or status moves. A caller
    // that forgot one is not a contract; this is the last point at which a
    // result belonging to an identity that is gone can be stopped.
    if (generation !== identityGenerationRef.current) return;
    if (!isOwnerTokenValid(token, token.uid)) return;
    if (refreshed.status === 'abandoned') {
      // Somebody else owns this browser now. Nothing is applied, and nothing
      // is said either — an error banner here belongs to an account that is
      // no longer looking at this screen.
      return;
    }
    // The STATUS text belongs to whichever intent is current; the facts below
    // do not. A newer edit silences the wording and nothing else.
    const owns = ownsOperation
      && intent === saveIntentRef.current
      && fence.editEpochAtOperation === editEpochRef.current;
    const tell = (status: SaveStatus) => { if (owns) setSaveStatus(status); };
    if (refreshed.status === 'device-failed') {
      // The durable proof is intact and the question is exactly what it was.
      // The controls and the retry both stay: this is the case the empty
      // array used to swallow.
      // The retry slot belongs to whoever owns the status. An older rebuild
      // claiming it points Retry at a write that has already been superseded,
      // and the newer failure loses its own way back.
      if (owns) armRetryable({ generation, token });
      tell('error');
      return;
    }
    // The row this refresh actually read, applied to the fields it is about
    // and to nothing else. A field the row does NOT have is authoritatively
    // absent — deleted here rather than left showing the value the question
    // was about.
    //
    // EVERY asked field, including ones still owed to the cloud. Another tab
    // may have answered "keep mine" with ITS value, which this tab has never
    // seen: the returned working copy is what the person must be looking at,
    // and whether it still has to be SENT is a separate question answered
    // just below.
    const owed = new Set(refreshed.pendingKeys);
    // Dirtiness FIRST, and decided by the refresh rather than by whether the
    // display moved. Still owed means it has to reach the cloud and must
    // survive the next load; confirmed means the opposite, and leaving it in
    // the buffer lets that load re-apply the value the person answered away.
    const epochOf = (key: string) => fieldEpochRef.current.get(key) ?? 0;
    /** Typed since the operation began: never paint over it, never undirty it. */
    const movedSince = (key: string) => epochOf(key) !== fence.atOperation.get(key);
    /** The returned question cannot be about what is on screen now. */
    const questionStale = (key: string) => (
      fence.unrepresented.has(key) || epochOf(key) !== fence.atIssue.get(key)
    );
    for (const key of asked) {
      // A field typed during the read stays dirty whatever the read says: its
      // current value has not been anywhere near the cloud.
      if (owed.has(key) || movedSince(key)) dirtyKeysRef.current.add(key as keyof ProfileData);
      else dirtyKeysRef.current.delete(key as keyof ProfileData);
    }
    {
      // A NULL profile is authoritative absence, not "no news". The asked
      // fields are emptied — every other field on the form was typed by the
      // person and is none of this answer's business. Substituting defaults
      // here would put a value on screen that no row has ever held.
      const row = (refreshed.profile ?? null) as unknown as Record<string, unknown> | null;
      const merged = { ...(profileRef.current as unknown as Record<string, unknown>) };
      let changed = false;
      for (const key of asked) {
        if (movedSince(key)) continue;
        if (!row || !(key in row)) {
          if (key in merged) { delete merged[key]; changed = true; }
        } else if (JSON.stringify(merged[key] ?? null) !== JSON.stringify(row[key] ?? null)) {
          merged[key] = row[key];
          changed = true;
        }
      }
      {
        const next = changed ? (merged as unknown as ProfileData) : profileRef.current;
        // Applied values are not an edit of the person's. Marking them
        // already-persisted is what stops the autosave from arming and
        // sending the answer straight back.
        //
        // Decided from the DIRTY STATE that now stands, never from whether
        // the document object changed: the answered edit necessarily made it
        // differ, so identity would say "unclean" for the one case that is
        // certainly clean. Nothing owed, nothing else edited, and a weight
        // that was never touched — then this snapshot is the persisted truth.
        // Anything less and the marker is left alone, so the unrelated edit
        // still autosaves.
        // Decided from the DIRTY STATE that now stands rather than from
        // whether the displayed object moved. This is an invariant, not the
        // thing that stops a duplicate send: what rules that out is the
        // fire-time dirty read, which finds the operation already settled.
        if (owed.size === 0 && dirtyKeysRef.current.size === 0 && !weightDirtyRef.current
          && !asked.some(movedSince)) {
          hydratedProfileRef.current = next;
          hydratedWeightRef.current = weightRef.current;
        }
        if (changed) {
          profileRef.current = next;
          setProfile(next);
          republishRendered(next);
        }
      }
    }
    // The baseline moves with it, out of the same locked read that produced
    // the document above. Both halves of the snapshot or neither: a display
    // showing absence beside a baseline still holding the old row is how the
    // next edit gets measured against a row that is gone.
    adoptAuthoritativeBase(refreshed.baseProfile, refreshed.revision, token, generation);
    if (refreshed.status === 'settled') {
      // Everything this rebuild was asked about. Callers ask about the WHOLE
      // question that is on screen, so a settled answer really does mean
      // there is nothing left — keeping a stale entry beside it would show a
      // disagreement the canonical state says is gone.
      retireConflictKeys(asked);
      // Only the owner may disarm Retry. An older rebuild clearing it takes
      // away the newer failure's only way back.
      if (owns) armRetryable(null);
      // A flush this refresh continued owns the outcome — it is the only part
      // that talked to the server.
      if (refreshed.flushed) {
        // Reported as ALREADY canonical: it came out of the rebuild, so it is
        // the answer rather than another payload to rebuild from. RETURNED,
        // so whoever is holding this chain keeps holding it.
        return applySaveResult(
          refreshed.flushed, token, generation, intent, true, owns,
          fence.atOperation, fence.editEpochAtOperation,
        );
      }
      tell('conflict-stale');
      return;
    }
    // A question about a field the person has since typed into describes a
    // value that is no longer theirs — its candidates and provenance are from
    // before the keystroke. It is hidden rather than patched up; the write
    // this edit arms will produce a fresh one if the disagreement survives.
    publishConflicts(
      refreshed.conflicts.filter((c) => !questionStale(c.key)),
      viewSnapshotRef.current,
    );
    tell('conflict');
  }, [
    adoptAuthoritativeBase, applySaveResult, publishConflicts,
    republishRendered, retireConflictKeys,
    armRetryable, setSaveStatus,
  ]);
  // Same-tick latest-ref, deliberately written during render: the reader
  // sits behind an await in the save/refresh chain, and a save that resolves
  // between this render and its effects must still find the CURRENT handler
  // — an effect-assigned ref is undefined for exactly that window on the
  // first render, silently skipping the refresh (the retry suites catch it
  // as intermittent dead Retry buttons). The write is idempotent per render
  // and read by nothing during render, so the rule's tearing concern does
  // not apply.
  // eslint-disable-next-line react-hooks/refs
  applyConflictRefreshRef.current = applyConflictRefresh;

  const lastUidRef = useRef<string | null | undefined>(undefined);
  // Which generation currently has a read in flight — NOT a bare boolean:
  // a new identity must be able to start its own read while the previous
  // one's is still hanging, or a slow U1 read would leave U2 with a form
  // that never loads and never unlocks.
  const inFlightGenerationRef = useRef<number | null>(null);
  // Generations whose recovered outbox has already been retried once. A
  // same-uid re-observation re-runs startLoad; without this it would fire a
  // second attempt behind the first.
  const flushedGenerationsRef = useRef<Set<number>>(new Set());
  const startLoad = useCallback((generation: number) => {
    if (inFlightGenerationRef.current === generation) return;
    inFlightGenerationRef.current = generation;
    // The origin of the screen this load is for. An edit made before the row
    // lands is that screen's edit, and belongs to this owner or to nobody.
    //
    // Only INITIALIZED here, never replaced: an edit made before this load was
    // issued has already frozen this screen's origin, and overwriting it would
    // let a queued load re-authorize that screen for whoever owns the browser
    // by the time the timer fired.
    const held = loadingOriginRef.current;
    const origin = held && held.generation === generation
      ? held
      : { token: captureOwnerToken(), generation };
    loadingOriginRef.current = origin;
    // Before hydrateProfile touches anything private. A screen whose owner has
    // moved on has no row to read: the real identity transition will issue its
    // own load under its own generation, and merging this screen's buffered
    // edits into that row is exactly what must not happen.
    if (!ownsScreen(origin)) {
      inFlightGenerationRef.current = null;
      return;
    }
    hydrateProfile().then((hydration) => {
      if (generation !== identityGenerationRef.current) return;
      // The owner can move while a load is in flight without this hook
      // hearing about it, which leaves the generation intact. Checked BEFORE
      // hydrate(), which moves refs and paints the row: publishing the view
      // is gated further down, but the row itself must not be drawn either.
      //
      // ONE exception, and it is not a loophole: a load issued before this
      // browser had any identity at all resolves the first one INSIDE itself
      // (see loadProfile's first-resolution branch), so the token it answers
      // with is the only capability this screen has ever had. Requiring the
      // unresolved null to still be current would mean a first visit never
      // hydrates. That token is accepted only if it is genuinely current and
      // valid now, and it is frozen as this screen's origin before anything
      // is painted — after which the ordinary rule applies to everything.
      let accepted = origin;
      if (origin.token.uid === null) {
        if (!isOwnerTokenValid(hydration.token, hydration.token.uid)) return;
        accepted = { token: hydration.token, generation };
        loadingOriginRef.current = accepted;
      } else if (!ownsScreen(accepted)) return;
      // Only a RESOLVED result — a row, or a confirmed-absent row —
      // settles the form. `hydration.profile` already carries this
      // browser's own unsent edits back on top of the cloud row.
      hydrate(hydration);
      setConflictKeys(hydration.conflictKeys);
      publishConflicts(hydration.conflicts, viewSnapshotRef.current);
      if (hydration.conflictKeys.length > 0) {
        setSaveStatus('conflict');
        return;
      }
      // An edit from a PREVIOUS visit that never reached the cloud (the tab
      // was closed, the network was down). Without this, a transport failure
      // left the user's change sitting in the outbox forever unless they
      // happened to edit something else — the form would just say 'idle'.
      // Exactly once per identity generation: a same-uid re-observation must
      // not fire a second attempt behind the first.
      if (!hydration.hasPending) return;
      if (flushedGenerationsRef.current.has(generation)) return;
      flushedGenerationsRef.current.add(generation);
      saveIntentRef.current += 1;
      const intent = saveIntentRef.current;
      setSaveStatus('saving');
      const recoveryEpochs = epochsNow(PROFILE_KEYS as readonly string[]);
      const recoveryEditEpoch = editEpochRef.current;
      return flushPendingProfileWrite(hydration.token).then((result) => {
        if (generation !== identityGenerationRef.current) return;
        if (!ownsScreen(accepted)) return;
        // Facts always; the wording only if this intent still owns it.
        return applySaveResult(
          result, hydration.token, generation, intent, true, intent === saveIntentRef.current,
          recoveryEpochs, recoveryEditEpoch,
        );
      }).catch(() => {
        if (generation !== identityGenerationRef.current) return;
        if (!ownsScreen(accepted)) return;
        if (intent !== saveIntentRef.current) return;
        if (recoveryEditEpoch !== editEpochRef.current) return;
        // The write is still in the outbox — a second flush is a real way
        // out, so the offer of one is real too. Without this the recovery
        // drew a Retry with nothing behind it.
        armRetryable({ generation, token: hydration.token });
        setSaveStatus('cloud-failed');
      });
    }).catch((err: unknown) => {
      if (generation !== identityGenerationRef.current) return;
      if (!ownsScreen(origin)) {
        // A load issued before this browser had ANY identity is the one case
        // where the read itself resolved who it was for. Only a genuine
        // capability from the layer that did the resolving may say so — an
        // object merely SHAPED like one grants nothing, or anybody who can
        // reject a promise could hand this screen an identity.
        if (origin.token.uid !== null) return;
        if (!isOwnerScopedLoadError(err)) return;
        const resolved = err.ownerToken;
        if (!isTokenOwnerStillCurrent(resolved)) return;
        if (!isOwnerTokenValid(resolved, resolved.uid)) return;
        // Frozen before anything is reported, so the edit that follows this
        // failure belongs to the identity the read actually resolved.
        loadingOriginRef.current = { token: resolved, generation };
      }
      // A read that FAILED is not "you have no profile": treating it as
      // one would let the next edit persist DEFAULT_PROFILE plus that
      // field over a row that still exists and simply could not be read.
      // Stay locked, keep buffering, and say so.
      hydrationStateRef.current = 'failed';
      setHydrationState('failed');
    }).finally(() => {
      // Only clear our OWN claim: a newer generation's read may already
      // have replaced it.
      if (inFlightGenerationRef.current === generation) inFlightGenerationRef.current = null;
    });
  }, [hydrate, applySaveResult, epochsNow, ownsScreen, armRetryable, setSaveStatus]);

  useEffect(() => {
    const unsub = onAuthChange((s) => {
      const uid = s.user?.id ?? null;
      const firstObservation = lastUidRef.current === undefined;
      if (!firstObservation && uid === lastUidRef.current) {
        // Same identity re-observed (TOKEN_REFRESHED, INITIAL_SESSION).
        // Not a transition — but if this identity's row never loaded, it is
        // a free retry: same identity, same buffered edits, no reset.
        if (!hydrationReadyRef.current) startLoad(identityGenerationRef.current);
        return;
      }
      lastUidRef.current = uid;
      // Read BEFORE this observation is folded in: the question is what the
      // screen was up to the instant before, not after.
      //
      // The two flags say what THIS hook has seen; the third condition says
      // who the browser belonged to when the typing happened. They can
      // disagree: another tab can claim the browser for a real account
      // without this hook's callback ever firing, and typing done under that
      // claim is that account's — carrying it into the next identity is the
      // leak W-identity-owed pins. A genuine first-visit edit's frozen token
      // names nobody; that is what makes it the visitor's own.
      const virginScreen = !everHadRealUidRef.current && !rowEverAcceptedRef.current;
      // Gap-buffered keystrokes (see gapCarriedRef) carry no origin at all —
      // they were made under nobody by construction, which is exactly the
      // same claim.
      const editsBelongToNobody = gapCarriedRef.current || (
        editOriginRef.current !== null && editOriginRef.current.token.uid === null
      );
      gapCarriedRef.current = false;
      if (uid) everHadRealUidRef.current = true;
      liveIdentityObservedRef.current = true;
      if (fallbackLoadTimerRef.current) {
        clearTimeout(fallbackLoadTimerRef.current);
        fallbackLoadTimerRef.current = null;
      }
      // Bumped BEFORE the reset below, so every async result still in
      // flight (the fallback load, a GitHub import, a resume parse) is
      // already stale by the time any of them can resolve.
      identityGenerationRef.current += 1;
      ghRequestRef.current += 1;
      const generation = identityGenerationRef.current;
      setIdentityGeneration(generation);
      if (saveTimerRef.current) {
        clearTimeout(saveTimerRef.current);
        saveTimerRef.current = null;
      }
      pendingSaveRef.current = null;
      pendingSaveOriginRef.current = null;
      armRetryable(null);
      // Immediately, synchronously, before anything can render: the view this
      // form published belonged to the identity that just left. Any surface
      // still holding it (the school switcher lives straight through a
      // switch — it is not keyed by identity) must have nothing to act on
      // until THIS identity's own hydration is accepted.
      setViewSnapshot(null);
      viewSnapshotRef.current = null;
      loadingOriginRef.current = null;
      conflictPromptRef.current = null;
      conflictKeysRef.current = [];
      // Cancels whatever is in flight and frees the control for the new owner.
      resolveSeqRef.current += 1;
      activeResolveRef.current = null;
      unrecordedRef.current.clear();
      setConflictKeys([]);
      setConflicts([]);
      githubImportedUrlRef.current = null;
      // The previous identity's share — the request still in flight and the
      // timer that would clear its badge — belongs to a screen that is gone.
      shareRequestRef.current += 1;
      if (shareTimerRef.current) {
        clearTimeout(shareTimerRef.current);
        shareTimerRef.current = null;
      }
      setShareCopied(false);
      // Transient UI belonging to the previous identity's in-flight work.
      // Cleared even on the share-link path below: the request-id bump
      // above already told any running import to write nothing, so its
      // `finally` will not switch this spinner off — leaving it on forever.
      setSaveStatus('idle');
      setGhStatus(null);
      setGhLoading(false);
      submittingRef.current = false;
      setIsSubmitting(false);
      if (virginScreen && shareImportedRef.current) {
        // The visitor's own ?share= import, applied moments ago by the
        // snapshot effect below, which deliberately does not load over it
        // either. The draft stays on screen, so the screen keeps an origin —
        // this observation's, since no account has ever owned this screen.
        // Captured at the choke point itself, which has already advanced the
        // shared owner before calling us.
        //
        // NOT `firstObservation`: anonymous sign-in satisfies that once, and
        // the second observation would fall through and load the visitor's
        // own empty row over the draft. A share draft is marked hydrated
        // rather than edited, so it carries no dirty keys and the merge below
        // would have had nothing to put back.
        loadingOriginRef.current = { token: captureOwnerToken(), generation };
        return;
      }
      if (virginScreen && editsBelongToNobody) {
        // The browser's FIRST identity landing on a screen that has never
        // shown anyone's row, carrying edits that were made while the browser
        // belonged to nobody. Anonymous sign-in arrives as two observations
        // (INITIAL_SESSION with no user, then SIGNED_IN), and the school
        // catalog opens the dropdowns before either — so what is on screen
        // here is what the visitor typed in that window. Wiping it is not
        // isolation from a previous account; there was none. It is throwing
        // away the first thing they did.
        //
        // Locked for the load all the same, and WITHOUT clearing the dirty
        // ledger: hydrate() re-applies those keys over the row it loads, the
        // same treatment an edit made during any other load already gets.
        // The capability those carried edits were made under was frozen
        // before this browser had an identity at all. `ownsScreen` refuses it
        // the moment the epoch advances, and the autosave — which fires under
        // the EDIT's capability, not one taken at save time — would return
        // before it ever reached 'saving'. The edit would stay on screen and
        // never be written, which is worse than visibly losing it: the
        // student cannot tell. Re-issue it under this identity. Safe for the
        // same reason the branch itself is: no other account has ever owned
        // this screen, so nobody else's capability is being handed out.
        editOriginRef.current = { token: captureOwnerToken(), generation };
        // Their journal entries went the same way: recorded under the
        // anonymous namespace, which nothing will ever read again — so at
        // fire time the save would find zero dirty keys and stage a patch of
        // nothing ({status:'blocked'}, silently). Marking them unrecorded is
        // the truth: recordOutstandingIntents re-journals them at fire time
        // under the accepted view's token, the identity the write belongs to.
        for (const key of dirtyKeysRef.current) unrecordedRef.current.add(key);
        if (weightDirtyRef.current) unrecordedRef.current.add('search_weight');
        // No banner to clear here: it is only ever raised together with the
        // share import, and that case returned above.
        hydrationReadyRef.current = false;
        hydrationStateRef.current = 'loading';
        setHydrationState('loading');
        startLoad(generation);
        return;
      }
      // Defaults now, still locked: only the load below settles this form.
      resetForPendingLoad();
      setSharedBannerVisible(false);
      startLoad(generation);
    });
    return () => unsub();
  }, [startLoad, resetForPendingLoad, armRetryable, setSaveStatus]);

  useEffect(() => {
    getStats().then((s) => {
      setOppCount(s.total);
      setLastUpdated(s.last_updated_at ?? null);
    }).catch(() => {});

    const shareParam = searchParams.get('share');
    if (shareParam) {
      if (shareImportedParamRef.current === shareParam) {
        // Already imported once. Never again for this link — and never a
        // load over it either; the auth stream owns loading from here.
        return;
      }
      const decoded = decodeProfileWithKeys(shareParam);
      if (decoded) {
        const shared = decoded.profile;
        shareImportedRef.current = true;
        shareImportedParamRef.current = shareParam;
        // Whatever the visitor's OWN profile had pending stops here: the
        // draft gate below blocks new saves, but a save already armed
        // would still be flushed on unmount — writing a pre-share snapshot
        // the banner promised not to touch.
        if (saveTimerRef.current) {
          clearTimeout(saveTimerRef.current);
          saveTimerRef.current = null;
        }
        pendingSaveRef.current = null;
        pendingSaveOriginRef.current = null;
        // A save already in flight cannot be recalled, but its OUTCOME
        // belongs to the profile that is no longer on screen: bumping the
        // intent makes its "saved"/"failed" land nowhere, and the stale
        // retry payload is dropped rather than offered to a visitor
        // looking at someone else's shared profile.
        saveIntentRef.current += 1;
        const imported = normalizeProfileForRelease(
          { ...DEFAULT_PROFILE, ...shared } as ProfileData,
        );
        const weight = typeof shared.search_weight === 'number'
          ? shared.search_weight
          : DEFAULT_SEARCH_WEIGHT;
        /* eslint-disable react-hooks/set-state-in-effect --
           One-shot URL-share import on mount. setProfile + setSearchWeight
           + setSharedBanner (and the retry affordance the stale payload
           leaves behind) must all flush in the same effect tick so the
           form renders pre-filled from the share link before any user
           interaction; otherwise the home page would flash empty fields. */
        armRetryable(null);
        // Marked hydrated, not edited: the banner promises the visitor's
        // OWN saved profile stays untouched until they hit generate, so
        // importing a link must not arm the autosave.
        hydratedProfileRef.current = imported;
        hydratedWeightRef.current = weight;
        hydrationReadyRef.current = true; // the draft itself needs no load
        shareDraftActiveRef.current = true;
        // This screen never loads a row, so nothing else would ever give it an
        // origin — and Generate, which DOES read the visitor's own row and
        // stage against it, would have no capability to act under. The draft
        // is adopted here, so here is where the screen it becomes belongs to
        // somebody.
        loadingOriginRef.current = {
          token: captureOwnerToken(),
          generation: identityGenerationRef.current,
        };
        // The WIRE fields, not Object.keys(shared): the decoder injects a
        // constant `institution` so the draft renders, and treating that as
        // shared content would write it over the visitor's own school. Every
        // field the payload never carried — résumé, profile URLs, home_school,
        // name — is likewise absent here and therefore never patched.
        shareKeysRef.current = decoded.keys;
        setHydrationState('ready');
        setProfile(imported);
        setSearchWeight(weight);
        setSharedBannerVisible(true);
        setSaveStatus('idle');
        /* eslint-enable react-hooks/set-state-in-effect */
        // The visitor's own row is deliberately NOT loaded here. Viewing
        // someone else's link touches nothing of theirs: no read, no local
        // mirror, no envelope. Generate is what needs a base revision to
        // patch onto, so Generate is where that load happens (see
        // handleSubmit) — one round trip when they commit, instead of one
        // every time a link is opened.
        return;
      }
    }

    if (liveIdentityObservedRef.current) {
      // The live stream already owns this form; only the query prefill
      // still has to be applied for a same-session params change.
      const next = applyPrefill(searchParams, profileRef.current);
      if (next !== profileRef.current) {
        profileRef.current = next;
        setProfile(next);
      }
      return;
    }
    // Fallback snapshot: scheduled, not fired, so a live observation
    // arriving in the same tick cancels it outright instead of racing it.
    // Without a live auth stream (Supabase unconfigured) this is the only
    // load there will ever be.
    const generation = identityGenerationRef.current;
    fallbackLoadTimerRef.current = setTimeout(() => {
      fallbackLoadTimerRef.current = null;
      if (liveIdentityObservedRef.current) return;
      startLoad(generation);
    }, 0);
    return () => {
      if (fallbackLoadTimerRef.current) {
        clearTimeout(fallbackLoadTimerRef.current);
        fallbackLoadTimerRef.current = null;
      }
    };
  }, [searchParams, startLoad, armRetryable, setSaveStatus]);

  // The onboarding school gate (a layout-level overlay) finishes *after* this
  // form has already mounted and loaded its profile, so its localStorage write
  // alone would never be reflected here. It also broadcasts the chosen campus on
  // a window event; apply it live so the Institution field updates immediately.
  // The form's own auto-save then persists the full profile.
  useEffect(() => {
    const onHomeSchool = (e: Event) => {
      const slug = (e as CustomEvent<string>).detail;
      if (typeof slug !== 'string' || !slug) return;
      editProfile((prev) => (prev.home_school === slug ? prev : { ...prev, home_school: slug }));
    };
    window.addEventListener(HOME_SCHOOL_EVENT, onHomeSchool);
    return () => window.removeEventListener(HOME_SCHOOL_EVENT, onHomeSchool);
  }, [editProfile]);

  const handleShare = useCallback(async () => {
    // FIRST. Sharing puts this screen's profile on the system clipboard, or
    // in front of the person in a prompt — both disclosures outside this
    // browser's account boundary. A screen whose owner has moved on may not
    // make either, and may not disturb the badge or timer of the screen that
    // replaced it: nothing below this line runs for it at all.
    const origin = actingOrigin();
    if (!origin) return;
    shareRequestRef.current += 1;
    const request = shareRequestRef.current;
    // The previous share's result stops being the answer the moment a new
    // question is asked — badge and timer together, or the old timer clears
    // the new share's success two seconds later.
    if (shareTimerRef.current) {
      clearTimeout(shareTimerRef.current);
      shareTimerRef.current = null;
    }
    setShareCopied(false);
    const url = buildShareUrl(
      normalizeProfileForRelease({ ...profile, search_weight: searchWeight }),
    );
    try {
      await navigator.clipboard.writeText(url);
      // The copy itself cannot be recalled. Saying "copied" on a screen that
      // now belongs to somebody else can be, and so can a superseded share
      // claiming the badge of the one that replaced it.
      if (request !== shareRequestRef.current) return;
      if (!ownsScreen(origin)) return;
      setShareCopied(true);
      shareTimerRef.current = setTimeout(() => {
        shareTimerRef.current = null;
        if (request !== shareRequestRef.current) return;
        if (!ownsScreen(origin)) return;
        setShareCopied(false);
      }, 2000);
    } catch {
      if (request !== shareRequestRef.current) return;
      // A URL built from one account's profile, put in front of whoever is at
      // the keyboard now, is the plainest disclosure of the lot.
      if (!ownsScreen(origin)) return;
      window.prompt('Copy this share URL:', url);
    }
  }, [profile, searchWeight, actingOrigin, ownsScreen]);

  /**
   * The one place this form persists a profile. It hands a PATCH — the keys
   * whose values the cloud has not confirmed — to the profile coordinator,
   * which owns the revision check, the outbox and the local mirror. The form
   * never writes storage itself any more: doing so from here is exactly how a
   * screen-local snapshot used to overwrite another device's row.
   */
  const commitSave = useCallback((
    toSave: ProfileData & { search_weight: number },
    keys: readonly (keyof ProfileData)[],
    /** The capability this write belongs to, immutable from the action that
     *  started it. Its token is what goes to the coordinator and its owner is
     *  what decides whether the outcome may be spoken about at all. */
    origin: ScreenOrigin,
    intent: number,
  ) => {
    const token = origin.token;
    const generation = origin.generation;
    // The FULL universe, not just this patch's keys. A generic conflict's
    // rebuild asks about the union with whatever else is already in dispute,
    // and a field first touched while this write was open — with its journal
    // entry failed, so nothing else records it — would otherwise have its own
    // keystroke taken as the baseline.
    const epochsAtStart = epochsNow(PROFILE_KEYS as readonly string[]);
    const editEpochAtEntry = editEpochRef.current;
    return stageProfilePatch(toSave, keys, token, { allowCreate: true })
      .then((result) => {
        if (generation !== identityGenerationRef.current) return;
        if (!ownsScreen(origin)) return;
        // A newer save owns the STATUS — not the server's account of the row.
        // The baseline and the conflict list are applied either way; dropping
        // them here leaves the next edit measured against a revision that is
        // gone and a locked disagreement invisible until something else
        // happens to look.
        return applySaveResult(
          result, token, generation, intent, true, intent === saveIntentRef.current,
          epochsAtStart, editEpochAtEntry,
        );
      })
      .catch(() => {
        if (generation !== identityGenerationRef.current) return;
        // BEFORE the retry is armed and before the wording: a rejection that
        // arrives once the owner has moved belongs to a screen that is gone,
        // and arming a retry on it would offer the new owner a button that
        // replays somebody else's write.
        if (!ownsScreen(origin)) return;
        if (intent !== saveIntentRef.current) return;
        if (editEpochAtEntry !== editEpochRef.current) return;
        armRetryable({ generation, token });
        setSaveStatus('cloud-failed');
      });
  }, [applySaveResult, epochsNow, ownsScreen, armRetryable, setSaveStatus]);

  useEffect(() => {
    // Nothing is persisted until this identity's row has settled: see
    // dirtyKeysRef. Edits made before then are visible immediately and
    // merged onto the row when it lands, which is what arms this effect.
    //
    // A read that FAILED is not "wait": nothing can be persisted until it
    // succeeds, and an edit that silently goes nowhere is worse than one that
    // says so out loud.
    if (!hydrationReadyRef.current) {
      // Whose read failed. This branch WRITES to the screen, so it answers to
      // the same rule as every other write: the edit that caused this effect
      // has a frozen origin, and a null one is not a current one — an effect
      // with nothing to act on behalf of says nothing.
      const armedForFailure = editOriginRef.current;
      if (hydrationStateRef.current === 'failed'
        && armedForFailure && ownsScreen(armedForFailure)) setSaveStatus('error');
      return;
    }
    // A shared draft is explicitly not the visitor's own profile — see
    // shareDraftActiveRef. Their tweaks stay on screen; only Generate
    // commits them.
    if (shareDraftActiveRef.current) return;
    // Hydrated data is not an edit: re-saving what a load (or the identity
    // reset) just put on screen would write one identity's row from
    // another's response ordering.
    if (profile === hydratedProfileRef.current && searchWeight === hydratedWeightRef.current) return;
    if (saveTimerRef.current) clearTimeout(saveTimerRef.current);

    const toSave = normalizeProfileForRelease({
      ...profile,
      search_weight: searchWeight,
    });
    // The capability of the EDIT that armed this, carried in rather than
    // taken here. Between the keystroke and this effect the shared owner can
    // move, and a capture at this point would hand one person's typing to
    // whoever owns the browser by the time React got round to it.
    const armed = editOriginRef.current;
    if (!armed || !ownsScreen(armed)) return;
    pendingSaveRef.current = toSave;
    pendingSaveOriginRef.current = armed;
    // The identity this save intent belongs to. Every UI commit below —
    // including the ones that only run after saveProfile settles, and the
    // 2s "back to idle" timer — is checked against it, so a late resolution
    // can never label a DIFFERENT identity's form as saved or failed.
    const armedGeneration = armed.generation;
    saveIntentRef.current += 1;
    const intent = saveIntentRef.current;
    setSaveStatus('saving');

    saveTimerRef.current = setTimeout(() => {
      const origin = pendingSaveOriginRef.current;
      pendingSaveRef.current = null;
      pendingSaveOriginRef.current = null;
      if (!origin) return;
      // BEFORE the journal is read. An old token is not a defence: the reads
      // below go to whatever this browser holds NOW, and the new owner's
      // dirty set would be answered with the old screen's document.
      if (!ownsScreen(origin)) return;
      const token = origin.token;
      // The keys the CLOUD has not confirmed — read at fire time, so an edit
      // made during the debounce is included. Never the whole document. A
      // journal this browser cannot read is a hard stop: sending a patch
      // while another tab's operation is invisible is the lost update the
      // journal exists to prevent.
      if (!recordOutstandingIntents(toSave)) {
        // An earlier edit never reached the journal and still cannot. Sending
        // now would patch some of this form's fields and quietly drop the
        // rest.
        armRetryable({ generation: armedGeneration, token });
        setSaveStatus('error');
        return;
      }
      const dirty = getDirtyProfileKeys(token, HOME_FORM_WRITER);
      if (!dirty.ok) {
        armRetryable({ generation: armedGeneration, token });
        setSaveStatus('error');
        return;
      }
      commitSave(toSave, dirty.value, origin, intent);
    }, 1500);

    return () => {
      if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
    };
  }, [profile, searchWeight, hydrationTick, commitSave, recordOutstandingIntents, ownsScreen, armRetryable, setSaveStatus]);

  useEffect(() => {
    return () => {
      // The burst timer must not fire into an unmounted form. Its value is
      // not lost: an armed burst always has a pending save, and the flush
      // below drains `unrecordedRef` before anything is sent.
      if (textBurstRef.current.timer !== null) clearTimeout(textBurstRef.current.timer);
      textBurstRef.current = { timer: null, origin: null };
      // A shared draft is never flushed: the banner promises the visitor's
      // own profile stays untouched until they generate.
      const pending = shareDraftActiveRef.current ? null : pendingSaveRef.current;
      const origin = pendingSaveOriginRef.current;
      // Same rule on the way out. Leaving the page is not a reason to send an
      // old screen's document under whoever owns the browser now, and the
      // journal read below would consult exactly their data to build it.
      const token = origin && ownsScreen(origin) ? origin.token : null;
      if (pending && token) {
        // What is synchronous here is the JOURNAL: recordOutstandingIntents
        // below writes any edit that is not yet down before this cleanup
        // returns, so a crash at this instant still has it and the next mount
        // finishes the job. Staging, the request and the local mirror are
        // async continuations of that — stageProfilePatch awaits its own
        // shared-state lock — and may not survive the unload. That is the
        // point of writing the journal first rather than relying on them.
        // A conflict discovered afterwards has nowhere to render, and is
        // deliberately left in the outbox rather than swallowed.
        // The same rule as every other send path: an edit that is not in the
        // journal may not go out. `unrecordedRef` holds keys whose journal
        // write FAILED (private mode, a full quota), and this is the last
        // chance to write them down — skipping it would send a patch built
        // from a dirty set that does not include them, and the edit would be
        // gone with the screen.
        const dirty = recordOutstandingIntents(pending)
          ? getDirtyProfileKeys(token, HOME_FORM_WRITER)
          : { ok: false } as const;
        if (dirty.ok) {
          void stageProfilePatch(pending, dirty.value, token, { allowCreate: true }).catch(() => {});
        }
        pendingSaveRef.current = null;
        pendingSaveOriginRef.current = null;
      }
      // Everything else this form instance still has in flight — a submit
      // waiting on GitHub, an import, a load — belongs to a screen that no
      // longer exists. Advancing the generation (and the import request)
      // is what stops their completion handlers from writing, clearing the
      // match cache or navigating after the user has left.
      identityGenerationRef.current += 1;
      ghRequestRef.current += 1;
      shareRequestRef.current += 1;
      if (shareTimerRef.current) {
        clearTimeout(shareTimerRef.current);
        shareTimerRef.current = null;
      }
    };
  }, [recordOutstandingIntents, ownsScreen]);

  const update = useCallback(<K extends keyof ProfileData>(key: K, value: ProfileData[K]) => {
    // BEFORE the skill ledger. The replace marker is sticky — it suppresses
    // every later addition until it lands — so a stale screen marking it is
    // not a cosmetic slip: it silently swallows the NEW owner's own imports.
    const origin = editingOrigin();
    // The first-identity gap (see gapCarriedRef): the keystroke is admitted
    // for paint-and-buffer, with no capability. editProfile makes the same
    // determination itself when handed no origin.
    const gapCarry = !origin
      && !everHadRealUidRef.current
      && !rowEverAcceptedRef.current
      && (screenOrigin()?.token.uid ?? null) === null;
    if (!origin && !gapCarry) return;
    // A hand-edit of the skills list can DELETE. From here on the list itself
    // is the intent, and a later import must not turn that deletion back into
    // "add everything again" (see markSkillsReplaced's sticky rule). Skipped
    // in the gap — the marker is a private-storage write and this keystroke
    // holds no capability; a skills DELETION in the ~ms gap can thus be
    // re-added by a later import, a notch accepted over granting a write.
    if (origin && key === 'skills') markSkillsReplaced(origin.token);
    // Picking a different college from a school's catalog invalidates the
    // major (the cascading dropdown). Schools without a catalog edit
    // college as free text, where clearing the major on every keystroke
    // would wipe the user's input.
    const clearMajor =
      key === 'college' && bySlug(profileRef.current.home_school ?? 'uiuc')?.catalog != null;
    editProfile(
      (prev) => ({
        ...prev,
        [key]: value,
        // Additional majors are catalog-scoped like the primary, so a college
        // switch invalidates them too.
        ...(clearMajor ? { major: '', additional_majors: [] } : {}),
      }),
      // The cascade is an intent even when the fields are already empty:
      // the row still loading must not put its own major back afterwards.
      clearMajor ? [key, 'major', 'additional_majors'] : [key],
      origin ?? undefined,
    );
  }, [editProfile, editingOrigin, screenOrigin]);

  // Rebuilt on every identity transition (identityGeneration is a dep), so
  // a resume parse that started under the previous identity calls the
  // handler it captured THEN — which refuses — instead of the current one.
  // The uploader subtree is separately remounted by the same generation
  // (see page.tsx), which is what clears its own filename/"on file" badge.
  const handleResumeParsed = useCallback((data: ResumeParseResponse) => {
    if (identityGeneration !== identityGenerationRef.current) return;
    // A parse that started on this screen finishes on this screen or nowhere.
    // Taken BEFORE the ledger below: a fresh token here would file an old
    // screen's extracted skills as the current owner's own additions.
    const origin = editingOrigin();
    if (!origin) return;
    // `beginner`, not `experienced`. The extractor is a bare presence test over
    // a fixed list (pdf-parser.ts extractSkills), so "Relevant coursework:
    // Introduction to Python" and "hoping to learn PyTorch" both matched — and
    // `experienced` reached professors as "I have hands-on experience with X".
    // A skill the student TYPES starts at `beginner` too; a regex hit has no
    // business outranking their own statement about themselves. `source` is
    // what lets the form offer to raise it and what keeps the claim withheld
    // until they do.
    // Each skill carries the line it was found on, so the form can show the
    // student WHERE it came from. That is the whole defence against a bare
    // presence match: they can see "hoping to learn PyTorch" and decline it.
    const evidenceFor = new Map(
      (data.skill_evidence ?? []).map((e) => [e.skill, e.line]),
    );
    const newSkills: SkillWithLevel[] = data.extracted_skills.map((name) => ({
      name,
      level: 'beginner' as const,
      source: 'resume' as const,
      ...(evidenceFor.get(name) ? { evidence: evidenceFor.get(name) } : {}),
    }));
    // An import ADDS names; it says nothing about the ones already there.
    // Recorded as an operation so a conflict merges these into whatever the
    // other device holds instead of pushing this whole list over it.
    markSkillAdditions(newSkills, origin.token);
    editProfile((prev) => {
      return {
        ...prev,
        skills: mergeSkills(prev.skills, newSkills),
        resume_text: data.raw_text,
        coursework: data.extracted_coursework,
        // Seed the interests box (the only semantic-match lever the form sends)
        // from the resume when the user hasn't typed their own — never overwrite.
        research_interests: prev.research_interests?.trim()
          ? prev.research_interests
          : (data.suggested_interests ?? ''),
      };
    }, undefined, origin);
  }, [identityGeneration, editProfile, editingOrigin]);

  const handleResumeRemoved = useCallback(() => {
    // PREFLIGHT. This action edits the form, takes the status line and sends
    // immediately, so a check further down would already have painted a dead
    // screen and built a document from it.
    const origin = editingOrigin();
    if (!origin) return;
    editProfile(
      (prev) => (
        (prev.resume_text ?? '') === '' && (prev.coursework?.length ?? 0) === 0
          ? prev
          : { ...prev, resume_text: '', coursework: [] }
      ),
      // Explicit intent, not a diff: on a form whose row has not landed yet
      // both fields are already empty, so there is nothing for a diff to
      // see — and the row landing afterwards would put the résumé back.
      ['resume_text', 'coursework'],
      origin,
    );
    // Removal does not wait for the 1.5s debounce: until it is persisted,
    // every match request, tailored draft and cold email still runs on the
    // résumé the user just deleted. It supersedes any pending save (this
    // snapshot is strictly newer) and goes through the same token and the
    // same profile-row queue as every other write.
    if (!hydrationReadyRef.current || shareDraftActiveRef.current) return;
    if (saveTimerRef.current) {
      clearTimeout(saveTimerRef.current);
      saveTimerRef.current = null;
    }
    pendingSaveRef.current = null;
    pendingSaveOriginRef.current = null;
    const cleansed = normalizeProfileForRelease({
      ...profileRef.current,
      resume_text: '',
      coursework: [],
      search_weight: weightRef.current,
    }) as ProfileData & { search_weight: number };
    // This exact form state is now being persisted by an explicit action,
    // so the autosave effect must not treat the same edit as a second,
    // newer change: it would re-save the identical snapshot 1.5s later,
    // append a duplicate profile_versions row, and — because a newer save
    // intent owns the status — hide the cloud failure this one is about to
    // report. Marking it persisted uses the same "already persisted"
    // mechanism as a hydration; the next REAL edit produces a new object
    // and arms normally.
    hydratedProfileRef.current = profileRef.current;
    hydratedWeightRef.current = weightRef.current;
    saveIntentRef.current += 1;
    setSaveStatus('saving');
    // The capability this action was admitted under — the same one the edit
    // above carries. Not a fresh capture: the document being sent was built
    // from a form that belongs to `origin`, and sending it under anyone else
    // is exactly the cross-account write this whole path is gated for.
    // Exactly the résumé bundle, not every dirty key: this is a specific
    // action with a specific meaning, and folding an unrelated half-typed
    // field into it would make the removal fail for a reason the user cannot
    // connect to what they clicked.
    commitSave(cleansed, ['resume_text', 'coursework'], origin, saveIntentRef.current);
  }, [editProfile, commitSave, editingOrigin, setSaveStatus]);

  // Imports GitHub-derived skills and returns them (without mutating profile),
  // so both the manual button and submit-time auto-import can reuse it without a
  // stale-state race. Tracks the imported URL so submit won't re-import.
  /** `origin` is the capability the INVOCATION was made under — the caller's
   *  own, threaded through so the import, its receipt and whatever the caller
   *  does with the result all belong to one screen. */
  const importGitHubSkills = useCallback(async (
    origin: ScreenOrigin,
  ): Promise<SkillWithLevel[] | null> => {
    const url = profile.github_url?.trim();
    if (!url) return null;
    // Before the spinner, before the status line, before the request itself.
    // A screen whose owner has moved on may not turn on a spinner the new
    // owner would see, clear a status line that is not its own, or spend a
    // request on a link nobody current pasted.
    if (!ownsScreen(origin)) return null;
    const match = url.match(/github\.com\/([^/\s?#]+)/);
    const username = match ? match[1] : url;
    ghRequestRef.current += 1;
    const request = ghRequestRef.current;
    setGhLoading(true);
    setGhStatus(null);
    try {
      const data = await parseGitHubProfile(username);
      // A superseded import writes NOTHING: not the skills it resolved, not
      // the status line, not the "already imported this URL" receipt (which
      // would suppress the current identity's own import of the same URL),
      // and not the spinner — the newer import still owns it.
      if (request !== ghRequestRef.current) return null;
      // Superseded by an OWNER move, which the request id cannot see: the
      // shared owner can go to U2 while this fetch is open without this hook
      // receiving its auth callback, so the request id still matches and the
      // generation has not moved. The same three writes are equally not this
      // browser's to make.
      if (!ownsScreen(origin)) return null;
      // The user retyped the URL while this was in flight: these skills,
      // this status line and this receipt all describe an account they are
      // no longer pointing at.
      if (profileRef.current.github_url?.trim() !== url) return null;
      githubImportedUrlRef.current = url;
      setGhStatus(t('home.form.githubImportSuccess', { skills: data.extracted_skills.length, repos: data.repo_count }));
      // Inferred from a repo's language field, which says the code exists, not
      // that the student wrote it or understands it. Marked and unclaimed until
      // they raise the level themselves.
      return data.extracted_skills.map(
        (name) => ({ name, level: 'beginner' as const, source: 'github' as const }),
      );
    } catch {
      if (request !== ghRequestRef.current) return null;
      if (!ownsScreen(origin)) return null;
      if (profileRef.current.github_url?.trim() !== url) return null;
      setGhStatus('__fail__' + t('home.form.githubImportFail'));
      return null;
    } finally {
      // The spinner is state on a screen, and a screen whose owner has moved
      // on is not this import's to change either. It stays on for a dead
      // identity's form — the identity transition clears it (see the auth
      // effect), and until then that form takes no further action anyway.
      if (request === ghRequestRef.current && ownsScreen(origin)) setGhLoading(false);
    }
  }, [profile.github_url, ownsScreen, t]);

  const handleGitHubImport = useCallback(async () => {
    // ONE capability, taken at the click and carried through the request, the
    // skill ledger and the edit alike. Re-capturing after the await would
    // mark an addition for whoever owns the browser by then — which is the
    // whole hole this unit closes, and the ledger is durable enough to carry
    // it into that owner's next write.
    const origin = actingOrigin();
    if (!origin) return;
    const newSkills = await importGitHubSkills(origin);
    if (!newSkills) return;
    if (!ownsScreen(origin)) return;
    markSkillAdditions(newSkills, origin.token);
    editProfile(
      (prev) => ({ ...prev, skills: mergeSkills(prev.skills, newSkills) }),
      undefined,
      origin,
    );
  }, [importGitHubSkills, actingOrigin, ownsScreen, editProfile]);

  /** Re-attempts a save that did not fully land — either half, or both.
   *  A fresh owner token, captured at THIS click: it is a new user intent,
   *  made by whoever is signed in now. A payload left behind by a previous
   *  identity is dropped, never re-sent. */
  const retryCloudSave = useCallback(() => {
    const failed = retryableRef.current;
    if (!failed) return;
    const token = captureOwnerToken();
    if (
      failed.generation !== identityGenerationRef.current
      || token.uid !== failed.token.uid
      || token.epoch !== failed.token.epoch
      || !isOwnerTokenValid(token, token.uid)
    ) {
      // A different account (or the same one across a sign-out cycle) is
      // active now, or this browser's data is not confirmed for it. The
      // unsent write belongs to neither — drop the affordance rather than
      // replay it anywhere.
      armRetryable(null);
      return;
    }
    saveIntentRef.current += 1;
    const intent = saveIntentRef.current;
    const generation = identityGenerationRef.current;
    // Retry is a NEW intent by whoever is signed in now — but once made, it is
    // as bound to that identity as any other action, including while its own
    // request is in flight.
    const origin: ScreenOrigin = { token, generation };
    setSaveStatus('saving');
    if (unrecordedRef.current.size > 0) {
      // The failure being retried happened BEFORE the journal — there is no
      // pending write to flush, only an edit still on screen that never
      // became durable. Record it now and send it the ordinary way.
      const live = normalizeProfileForRelease({
        ...profileRef.current,
        search_weight: weightRef.current,
      });
      if (!recordOutstandingIntents(live)) {
        setSaveStatus('error');
        return;
      }
      const dirty = getDirtyProfileKeys(token, HOME_FORM_WRITER);
      if (!dirty.ok) {
        setSaveStatus('error');
        return;
      }
      commitSave(live, dirty.value, origin, intent);
      return;
    }
    // Whatever is STILL unsent, not a snapshot this hook remembers: the
    // coordinator may have rebased it, layered a newer edit onto it, or
    // recorded that the cloud already has it and only the local mirror
    // failed — all of which a replayed payload would get wrong.
    const retryEpochs = epochsNow(PROFILE_KEYS as readonly string[]);
    const retryEditEpoch = editEpochRef.current;
    return flushPendingProfileWrite(token)
      .then((result) => {
        if (generation !== identityGenerationRef.current) return;
        if (!ownsScreen(origin)) return;
        // Facts always; the wording only if this intent still owns it.
        return applySaveResult(
          result, token, generation, intent, true, intent === saveIntentRef.current,
          retryEpochs, retryEditEpoch,
        );
      })
      .catch(() => {
        if (generation !== identityGenerationRef.current) return;
        if (!ownsScreen(origin)) return;
        if (intent !== saveIntentRef.current) return;
        if (retryEditEpoch !== editEpochRef.current) return;
        setSaveStatus('cloud-failed');
      });
  }, [applySaveResult, commitSave, epochsNow, recordOutstandingIntents, ownsScreen, armRetryable, setSaveStatus]);

  /** The two halves of a conflict, as explicit user choices. Nothing else
   *  unlocks a conflicted field — see the coordinator's lock rule. */
  const resolveConflictAs = useCallback((
    choice: 'local' | 'cloud',
    /** Which fields this click answers. Defaults to all of them, which is
     *  what the two blanket buttons do; a per-field control passes one. */
    only?: readonly string[],
  ) => {
    // From the PUBLISHED prompt, not from React state: the two can disagree
    // for a tick, and a click landing in that window would answer a question
    // that is no longer the one on screen.
    const published = conflictPromptRef.current;
    if (!published) return;
    const asking = only ? narrowConflictPrompt(published, only) : published;
    const answering = [...asking.conflicts];
    if (answering.length === 0) return;
    // The view that was on screen when this question was PUBLISHED, captured
    // then. Not a fresh token: a prompt retained across an identity switch
    // would otherwise hand U1's answer a currently-valid U2 token, and every
    // preflight downstream would let it through.
    const origin = asking.originView;
    // The screen being acted ON. Same accepted view as the prompt's, carrying
    // whatever has been typed since — which is what makes it what "mine"
    // means. A newly accepted base mints a new viewId and the coordinator
    // refuses; that is the point, so it is not papered over here.
    const actionView = viewSnapshotRef.current;
    if (!actionView) return;
    // BEFORE the latch, before the save intent, before the screen is told it
    // is saving, and before the coordinator reads or writes a single private
    // byte. The question was published for a screen that belonged to somebody;
    // once the shared owner has moved on, that answer is not an action this
    // browser may take on their behalf — and a fresh token would say it is.
    if (!isTokenOwnerStillCurrent(origin.token)) return;
    // Synchronous latch, taken BEFORE anything async. `saveStatus` is state:
    // Keep Mine and Use Cloud clicked in the same tick both read the old value
    // and both run, the second intent suppresses the first's result, and the
    // stale refresh that follows can put a phantom question back on screen.
    if (activeResolveRef.current !== null) return;
    resolveSeqRef.current += 1;
    const resolveId = resolveSeqRef.current;
    activeResolveRef.current = resolveId;
    saveIntentRef.current += 1;
    const intent = saveIntentRef.current;
    const generation = identityGenerationRef.current;
    const token = origin.token;
    setSaveStatus('saving');
    // What each answered field's edit count was WHEN THE BUTTON WAS PRESSED.
    // Anything typed after this — including typing a value away and back —
    // is newer than the answer, and the answer may not be drawn over it.
    const editEpochAtClick = editEpochRef.current;
    const epochsAtClick = new Map(
      answering.map((c) => [c.key, fieldEpochRef.current.get(c.key) ?? 0]),
    );
    resolveProfileConflict({
      prompt: asking, actionView, choice,
    }).then((result) => {
      if (generation !== identityGenerationRef.current) return;
      // The owner can move without this hook hearing about it, which leaves
      // the generation intact. Checked before the form is redrawn, before the
      // question is retired and before any baseline is taken: what this answer
      // resolved to describes a row the person at the keyboard does not own.
      if (!isTokenOwnerStillCurrent(token)) return;
      const ownsResolve = intent === saveIntentRef.current;
      if (result.status === 'stale-conflict') {
        // Handled HERE, where `answering` is still the immutable question this
        // click was about. Reading the keys from a ref inside the generic
        // result handler would let a conflict published in the meantime decide
        // which keys get re-asked.
        //
        // The question on screen is NOT retired first. Only the refresh knows
        // whether it is gone: a lock this browser could not take, or a journal
        // it could not read, leaves the disagreement exactly where it was, and
        // a screen already stripped of its controls has no way back to it.
        // The WHOLE question on screen, not just the fields this click named.
        // A rebuild told only about `grade` can say nothing about `major`,
        // and publishing its answer would decide a disagreement it never
        // looked at.
        const asked = [...new Set([
          ...answering.map((c) => c.key),
          ...conflictKeysRef.current,
        ])];
        // RETURNED into the chain, never detached. The resolution latch is
        // released in the `finally` below; firing the refresh off on its own
        // frees the latch while it is still running, and a second click would
        // then own a resolution that this one is about to publish over.
        //
        // Through the coordinator, under the lock — and fully gated there: a
        // continuation retained across an identity switch reaches storage for
        // nothing at all and comes back 'abandoned'. The synchronous read
        // cannot apply a receipt another tab appended, and its fallback will
        // describe a pending write whose question is already settled, so
        // refreshing through it re-renders an answered question and every
        // later click on it is stale again.
        const atIssue = epochsNow(asked);
        const atOperation = new Map([...atIssue, ...epochsAtClick]);
        const unrepresented = unrepresentedNow();
        return refreshConflictQuestion(asked, origin.token).then((refreshed) => {
          // INTENT sequencing only. Identity is not re-checked here: one gate
          // owns that, and it is the one inside the application helper — a
          // second copy out here means two places have to stay right, and the
          // one that is easy to forget is the one that matters.
          // No intent early-return: the canonical state this rebuild read is a
          // fact whoever is typing now does not get to erase. The helper
          // applies it and decides for itself which parts belong to the
          // intent that no longer owns the wording.
          return applyConflictRefresh(
            refreshed, asked, origin.token, generation, intent,
            { atOperation, atIssue, unrepresented, editEpochAtOperation: editEpochAtClick },
            ownsResolve,
          );
        });
      }
      if (result.status === 'already-saved' || result.status === 'saved') {
        // The answered fields become what the server confirmed — and ONLY
        // those. Rebuilding the whole form from this row would overwrite the
        // other disagreement's working value and every unrelated edit made
        // since the prompt went up.
        const row = result.profile as unknown as Record<string, unknown>;
        const seen = actionView.renderedProfile as unknown as Record<string, unknown>;
        const merged = { ...(profileRef.current as unknown as Record<string, unknown>) };
        let moved = false;
        for (const c of answering) {
          if (!(c.key in row)) continue;
          // Only where the person has not touched the field since pressing
          // the button. Comparing VALUES instead would miss a field typed
          // away and typed back — it reads as untouched, and the answer is
          // drawn over an intention that came after it.
          if ((fieldEpochRef.current.get(c.key) ?? 0) !== epochsAtClick.get(c.key)) continue;
          if (JSON.stringify(merged[c.key] ?? null) !== JSON.stringify(seen[c.key] ?? null)) continue;
          if (JSON.stringify(merged[c.key] ?? null) === JSON.stringify(row[c.key] ?? null)) continue;
          merged[c.key] = row[c.key];
          moved = true;
        }
        if (moved) {
          const next = merged as unknown as ProfileData;
          profileRef.current = next;
          setProfile(next);
          republishRendered(next);
        }
        advanceAcceptedBase(result.profile, result.revision, token, generation);
      }
      const settledHere = result.status === 'saved' || result.status === 'already-saved'
        || result.status === 'local-only' || result.status === 'staged-local';
      let remaining: string[] = [];
      if (settledHere) {
        // Answered — and only the fields this click was about. The list, the
        // origin and the key set go together, so a path that cleared just the
        // React array would leave the buttons bound to a settled question;
        // one that cleared ALL of them would silently retire a disagreement
        // nobody has answered.
        const done = new Set(answering.map((c) => c.key));
        remaining = conflictKeysRef.current.filter((k) => !done.has(k));
        retireConflictKeys([...done]);
      }
      // RETURNED: a conflict result starts a canonical rebuild, and the
      // resolution latch below is released in `finally`. Dropping the promise
      // here frees the latch while the rebuild is still running.
      const applied = applySaveResult(
        result, token, generation, intent, true, ownsResolve,
        epochsAtClick, editEpochAtClick,
      );
      if (remaining.length === 0) return applied;
      // What is LEFT is not the leftovers of the old list. This answer moved
      // the row, so the other disagreement is now about a different revision
      // and a different base; publishing the stale entry would ask about a
      // row that is gone. Rebuilt canonically, under the same fence, and
      // still inside this chain so the latch covers it.
      const remainderAtIssue = epochsNow(remaining);
      const remainderFence = {
        atOperation: new Map([...remainderAtIssue, ...epochsAtClick]),
        atIssue: remainderAtIssue,
        unrepresented: unrepresentedNow(),
        editEpochAtOperation: editEpochAtClick,
      };
      return Promise.resolve(applied).then(() => (
        refreshConflictQuestion(remaining, token).then((refreshed) => {
          if (generation !== identityGenerationRef.current) return undefined;
          if (!isOwnerTokenValid(token, token.uid)) return undefined;
          return applyConflictRefresh(
            refreshed, remaining, token, generation, intent, remainderFence, ownsResolve,
          );
        })
      ));
    }).catch(() => {
      // Whose failure this is, in full. The success and rebuild paths above
      // already answer it this way; a rejection that answered it with less
      // would label a screen the answer no longer owns.
      if (generation !== identityGenerationRef.current) return;
      // The IMMUTABLE origin token, epoch included — not merely a current
      // one. An owner that moved before this hook's auth callback ran leaves
      // the generation intact and this token dead.
      // Owner-currentness, NOT realm validity: the same person whose local
      // marker has become temporarily unconfirmed still owns their own failed
      // answer and must be told about it, exactly as Submit does.
      if (!isTokenOwnerStillCurrent(token)) return;
      if (intent !== saveIntentRef.current) return;
      // A same-value touch moves this and takes no save intent, so the intent
      // check above cannot stand in for it.
      if (editEpochAtClick !== editEpochRef.current) return;
      setSaveStatus('cloud-failed');
    }).finally(() => {
      // Only the attempt that still holds the latch may release it: an older
      // resolution completing must not unlatch a newer one, and an unrelated
      // form save advancing the global intent must not strand it forever.
      if (activeResolveRef.current === resolveId) activeResolveRef.current = null;
    });
  }, [
    conflicts, advanceAcceptedBase, applyConflictRefresh, applySaveResult,
    republishRendered, retireConflictKeys,
    setSaveStatus,
  ]);

  const keepMyChanges = useCallback(
    (keys?: readonly string[]) => resolveConflictAs('local', keys),
    [resolveConflictAs],
  );
  const useCloudVersion = useCallback(
    (keys?: readonly string[]) => resolveConflictAs('cloud', keys),
    [resolveConflictAs],
  );

  const handleSubmit = useCallback(async () => {
    // Re-entrancy first, synchronously: a double click starts a second
    // submit whose own GitHub request invalidates the first's import, and
    // the first would still write, clear the cache and navigate — with the
    // skills it was told to drop missing from the row it just saved.
    if (submittingRef.current) return;
    // The capability this SCREEN was issued for — before the GitHub fetch,
    // before the own-row read, before anything is marked, recorded, staged,
    // cleared or navigated to. A fresh capture here would be the bug: the
    // shared owner can already be U2 while this hook still renders U1's row,
    // and the U2 token it would hand this submit is valid everywhere
    // downstream, so U1's document would land in U2's journal and U2's row.
    //
    // Null means this screen has no origin at all — no accepted view, no
    // issued load, no adopted draft — and there is nothing to act on behalf
    // of. Dropped in silence: the screen belongs to an identity that has
    // moved on, and its failure is not the current owner's news.
    const origin = actingOrigin();
    if (!origin) return;
    const token = origin.token;
    // The React-side companion to `token`: it is what makes a superseded
    // submit commit NOTHING to the screen either — not even the failure
    // its own (correctly rejected) write produced, which belongs to the
    // identity that pressed the button, not the one now looking at it.
    const submitGeneration = origin.generation;
    // Submit persists the WHOLE row, so it is gated on hydration exactly
    // like the autosave: generating matches from a form whose stored
    // profile has not arrived yet would write DEFAULT_PROFILE plus
    // whatever was typed over that row's skills, resume and coursework.
    // Backstop for the disabled Generate button (see SubmitRow): the row
    // this submit would overwrite has not been read yet.
    //
    // A read that FAILED is reported rather than swallowed. Nothing is
    // written and nothing is navigated to either way, but "we could not read
    // your profile, so nothing was saved" is something the person has to be
    // able to see — a Generate that silently does nothing reads as a broken
    // button.
    if (!hydrationReadyRef.current) {
      if (hydrationStateRef.current === 'failed') setSaveStatus('error');
      return;
    }
    submittingRef.current = true;
    setIsSubmitting(true);
    // The save intent as it stands BEFORE any await. Used only to decide
    // whether a failure along the way is still this submit's news; the write's
    // own intent is taken after every await, below.
    const submitIntentSoFar = saveIntentRef.current;
    // Declared out here so the catch below can see them: a failure AFTER the
    // write's own clocks were taken belongs to that write, and one before
    // them belongs to the intent this submit started with.
    let submitIntent = submitIntentSoFar;
    let submitEditEpoch = editEpochRef.current;
    try {
    if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
    // Auto-import GitHub when a URL is present but its skills weren't imported
    // yet, so a pasted-but-not-imported URL isn't silently dropped. Bounded by a
    // short timeout so a slow GitHub API can never block reaching the results.
    const url = profile.github_url?.trim();
    let importedSkills: SkillWithLevel[] | null = null;
    if (url && githubImportedUrlRef.current !== url) {
      importedSkills = await Promise.race([
        importGitHubSkills(origin),
        new Promise<null>((resolve) => setTimeout(() => resolve(null), 3500)),
      ]);
    }
    // The form may have been rebuilt for a different identity while GitHub
    // was being fetched. Checked HERE, before anything is recorded or
    // staged: the owner token can still be perfectly valid (a first live
    // observation of the same null owner), so nothing further down would
    // catch it, and this submit belongs to a form that is no longer there.
    if (submitGeneration !== identityGenerationRef.current) return;
    // …and the shared owner may have moved DURING the fetch, which the
    // generation cannot see. Checked here, ahead of the visitor's own-row
    // read, the skill ledger, the journal and the stage: from this line down
    // everything either reads private data or writes it.
    if (!ownsScreen(origin)) return;
    // Built from the LIVE form, after the await — the user keeps typing
    // while GitHub is being fetched, and persisting the snapshot this
    // handler closed over would silently roll those edits back (and then
    // navigate away from the form that still showed them).
    const liveUrl = profileRef.current.github_url?.trim() ?? '';
    if (liveUrl !== (url ?? '') && liveUrl && githubImportedUrlRef.current !== liveUrl) {
      // The link on the form is not the one that was imported. Saving now
      // would ship a profile whose GitHub skills were never imported at
      // all — exactly what the auto-import above exists to prevent. Say so
      // and leave everything (including the edit's own pending save) alone;
      // pressing Generate again imports the new link.
      setGhStatus('__fail__' + t('home.form.githubUrlChanged'));
      return;
    }
    // A shared draft carries only the fields the link had. Persisting the
    // whole document would write empty strings over the visitor's own résumé,
    // profile URLs and campus — fields the shared payload never contained.
    // Their own edits since the import are in the dirty ledger and join it.
    if (shareDraftActiveRef.current && !hasConfirmedProfileRevision()) {
      // The share branch never read this account's row (opening a link must
      // not touch it). Generate does, and must: without the visitor's own
      // revision, the patch below could only be sent as a create, which the
      // server rejects for anyone who already has a row — and the visitor
      // would be unable to generate at all. Nothing is painted from it; the
      // draft on screen still wins.
      //
      // This read is an AWAIT like the GitHub one above, and everything
      // downstream is recomputed after it for the same reason: the person
      // keeps typing while it runs.
      const waitEditEpoch = editEpochRef.current;
      let ownRow: ProfileHydration;
      try {
        ownRow = await hydrateProfile();
      } catch {
        // Whose failure this is: the identity that asked, still current, its
        // realm still confirmed, its submit still the newest, and the form
        // untouched since. Anything else and the message would belong to
        // somebody — or something — else.
        if (submitGeneration !== identityGenerationRef.current) return;
        if (!isOwnerTokenValid(token, token.uid)) return;
        if (submitIntentSoFar !== saveIntentRef.current) return;
        if (waitEditEpoch !== editEpochRef.current) return;
        setSaveStatus('error');
        return;
      }
      if (submitGeneration !== identityGenerationRef.current) return;
      if (!ownsScreen(origin)) return;
      if (!isOwnerTokenValid(token, token.uid)) return;
      // A row attributed to a capability this screen does not hold. The
      // coordinator only ever answers with the current owner's token, so this
      // is an impossible state rather than a race — and an impossible state
      // is exactly what must not be accepted as a baseline, recorded against,
      // or staged onto. Reported like the failed read above: the person
      // pressed Generate and nothing was saved.
      if (ownRow.token.uid !== token.uid || ownRow.token.epoch !== token.epoch) {
        if (submitIntentSoFar !== saveIntentRef.current) return;
        if (waitEditEpoch !== editEpochRef.current) return;
        setSaveStatus('error');
        return;
      }
      // This read IS an acceptance of the visitor's own baseline — of the
      // BASE half only. Nothing is painted from it (the draft on screen still
      // wins), but the claim recorded below has to say it was made against
      // the row that actually exists. Without this the operation carries
      // revision 0 while a row sits at revision 1, the coordinator treats it
      // as an unknown-base working copy, and one Generate goes out as a
      // create AND a patch.
      advanceAcceptedBase(ownRow.baseProfile, ownRow.revision, ownRow.token, submitGeneration);
    }
    // EVERYTHING below is computed from the LIVE form, after every await.
    // The person kept typing while GitHub and their own row were being read;
    // persisting the document this handler built before them would roll those
    // edits back and then navigate away from the form that still shows them.
    let profileToSave = normalizeProfileForRelease({
      ...profileRef.current,
      search_weight: weightRef.current,
    });
    // The form was valid when Generate was pressed; the user may have
    // emptied a required field since. Matching on an incomplete profile —
    // and saving that row — is worse than doing nothing: Generate becomes
    // available again the moment they finish it.
    if (!(
      profileToSave.college?.trim()
      && profileToSave.major?.trim()
      && profileToSave.grade?.trim()
    )) return;
    // The link, re-confirmed against the form as it stands NOW. It may have
    // been replaced while the row was being read, and skills imported for the
    // old one are not this profile's.
    const settledUrl = profileRef.current.github_url?.trim() ?? '';
    if (settledUrl && githubImportedUrlRef.current !== settledUrl) {
      setGhStatus('__fail__' + t('home.form.githubUrlChanged'));
      return;
    }
    if (importedSkills?.length && settledUrl && settledUrl === (url ?? '')) {
      profileToSave = { ...profileToSave, skills: mergeSkills(profileToSave.skills, importedSkills) };
      // Durable ONLY here — after the baseline is accepted and the link is
      // re-confirmed. Recording it before the await would freeze a skills
      // operation against an unknown revision and a link the person has
      // since replaced.
      //
      // BEFORE saveKeys is computed: an import that only reached
      // `profileToSave` would be in the payload but not in the dirty set, so
      // the patch built from that set would leave `skills` out entirely.
      markSkillAdditions(importedSkills, token);
      recordIntent(profileToSave, ['skills'], { mode: 'add-skills' });
    }
    // /results reads the profile back out of this exact slot, and the match
    // cache it renders is keyed to the PREVIOUS profile until it is cleared.
    // A write that did not land (identity moved on during the GitHub await,
    // quota, private mode) must therefore not be followed by ANY of the
    // three side effects that assume it did — no remote save, no cache
    // invalidation, no navigation to a results page with nothing to match
    // against. The pending debounced save goes too: this submit superseded
    // it, and the unmount flush must not resurrect a snapshot the user has
    // already been told was not saved.
    // Checked BEFORE the first side effect, not after: a submit that is no
    // longer this form's commits nothing at all. The hook's generation
    // catches an identity event the owner token cannot (a first live
    // observation resolving null on a local-only device leaves the token
    // itself perfectly valid), and the token catches a global owner move
    // this hook never saw.
    if (submitGeneration !== identityGenerationRef.current) return;
    // Same form, but this browser's local data is no longer confirmed for
    // the identity that pressed the button (signed out mid-flight, an
    // unverifiable clear). That is this user's own failed submit, not a
    // superseded one, so it is reported rather than dropped silently.
    if (!isOwnerTokenValid(token, token.uid)) {
      pendingSaveRef.current = null;
      pendingSaveOriginRef.current = null;
      setSaveStatus('error');
      return;
    }
    // Generate WAITS for the save. /results reads this profile back out and
    // ranks against it, so navigating on an unconfirmed write is how a user
    // ends up looking at matches for a profile the cloud rejected — and, on
    // a conflict, for fields another device has already changed. The only
    // outcomes that may proceed are the ones where the profile on screen IS
    // what will be matched: confirmed by the cloud, or durably local on a
    // device with no cloud to confirm it.

    if (!recordOutstandingIntents(profileToSave)) {
      setSaveStatus('error');
      return;
    }
    const outstanding = getDirtyProfileKeys(token, HOME_FORM_WRITER);
    if (!outstanding.ok) {
      // The journal cannot be read, so what is unsaved is unknown. Generating
      // from a profile that may not be what gets stored is exactly the thing
      // this whole path refuses to do.
      setSaveStatus('error');
      return;
    }
    let dirty = outstanding.value;
    if (shareDraftActiveRef.current) {
      // The visitor deliberately committed the draft. NOW it becomes their
      // own edit: the fields the link carried, plus whatever they changed on
      // top of it, recorded once — not field by field as they browsed.
      const claimed = [...new Set([
        ...shareKeysRef.current,
        ...draftTouchedRef.current,
      ])] as (keyof ProfileData)[];
      if (claimed.length > 0 && !recordIntent(profileToSave, claimed)) {
        setSaveStatus('error');
        return;
      }
      draftTouchedRef.current.clear();
      dirty = [...new Set([...claimed, ...outstanding.value])];
    }
    // Nothing this form owns is unconfirmed AND the cloud already holds a
    // row: there is genuinely nothing to send, and Generate should not be
    // blocked on a save that has no content. With no confirmed row, the same
    // press is what CREATES it, so the whole document goes.
    // The clocks for THIS write, taken now that every await is behind us.
    // Anything captured earlier belongs to a document that has since been
    // rebuilt.
    saveIntentRef.current += 1;
    submitIntent = saveIntentRef.current;
    submitEditEpoch = editEpochRef.current;
    // EVERY persistable field, not just the ones DEFAULT_PROFILE happens to
    // define. `coursework`, `seeking_types` and the rest are optional and
    // absent from the defaults, and leaving them out of the snapshot is how an
    // edit to one of them is lost to a response that predates it.
    const submitFieldEpochs = epochsNow(PROFILE_KEYS as readonly string[]);
    setSaveStatus('saving');
    const saveKeys = dirty.length > 0
      ? dirty
      : (hasConfirmedProfileRevision() ? [] : (Object.keys(profileToSave) as (keyof ProfileData)[]));
    // There is genuinely nothing to send. This is a LOCAL statement, not the
    // server's — flagged as such so it cannot be mistaken for an
    // acknowledgement and roll the accepted baseline back to revision 0.
    const noop = saveKeys.length === 0;
    const saveResult: ProfileSaveResult = noop
      ? { status: 'already-saved', revision: 0, profile: profileToSave }
      : await stageProfilePatch(profileToSave, saveKeys, token, { allowCreate: true });
    if (submitGeneration !== identityGenerationRef.current) return;
    const proceed = saveResult.status === 'saved'
      || saveResult.status === 'already-saved'
      || saveResult.status === 'local-only'
      || saveResult.status === 'staged-local';
    // Whether this submit still speaks for the form. The server's account of
    // the row lands either way; the WORDING and the side effects do not.
    const ownsSubmit = submitIntent === saveIntentRef.current
      && submitEditEpoch === editEpochRef.current;
    if (!proceed) {
      // Stay on the form, say why, clear NOTHING and navigate NOWHERE.
      await applySaveResult(
        saveResult, token, submitGeneration, submitIntent, !noop, ownsSubmit,
        submitFieldEpochs, submitEditEpoch,
      );
      return;
    }
    // AWAITED before anything is decided from it: a conflict result rebuilds
    // canonically, and navigating away from a form whose real question has
    // not been established yet is how it goes unanswered.
    //
    // And what comes back is the DISPOSITION taken when the result was
    // handled, not a fresh reading of the world. Re-deciding here would let a
    // browser that was refused the moment its answer arrived clear the cache
    // and navigate anyway, because the thing that refused it happened to be
    // repaired while this line was waiting its turn.
    const disposition = await applySaveResult(
      saveResult, token, submitGeneration, submitIntent, !noop, ownsSubmit,
      submitFieldEpochs, submitEditEpoch,
    );
    if (disposition !== ADOPTED) return;
    // Re-read, not the snapshot taken before the await above: applying the
    // result can itself await, and an edit made during THAT is just as newer
    // as one made during the write. Its facts are kept — they are the row —
    // but clearing the cache and navigating would take the person to matches
    // generated from a profile they have already changed.
    if (submitIntent !== saveIntentRef.current) return;
    if (submitEditEpoch !== editEpochRef.current) return;
    // The owner may have moved while the write was open. Its outcome is not
    // this browser's news, and the cache invalidation below would fail for
    // that reason alone — reporting THAT as a storage error would put a fresh
    // failure on a screen whose action was correctly rejected.
    if (!ownsScreen(origin)) return;
    // The cache is keyed by the profile hash (see useResultsData), so an
    // entry left behind here could only ever be served back for the SAME
    // profile it was generated from. It is still a gate: the save above just
    // landed under this very token, so the only remaining way to fail is
    // storage itself failing — and a browser that cannot remove a key it can
    // write is not one to hand a "your matches are ready" navigation to.
    if (!clearMatchCache(token)) {
      pendingSaveRef.current = null;
      pendingSaveOriginRef.current = null;
      setSaveStatus('error');
      return;
    }
    // This save supersedes any debounced one still pending — including one
    // armed by an edit made DURING the import above, which the payload just
    // built from the live form already contains. Both the timer and the
    // refs go, so nothing re-saves an older snapshot behind it.
    if (saveTimerRef.current) {
      clearTimeout(saveTimerRef.current);
      saveTimerRef.current = null;
    }
    pendingSaveRef.current = null;
    pendingSaveOriginRef.current = null;
    // The visitor deliberately generated from the shared draft: it is
    // their own profile from here on.
    shareDraftActiveRef.current = false;
    router.push('/results');
    } catch {
      // The coordinator REJECTED — a transport failure thrown out of the
      // write rather than a result it returned. React is handed this
      // handler's promise by an onClick and drops it, so without this the
      // rejection escapes into the page as an unhandled error, the form goes
      // on saying it is saving forever, and the write sitting in the outbox
      // is offered no Retry.
      //
      // Whose failure it is, in full — the same fences the resolve rejection
      // answers with. The token is this screen's own immutable origin, so a
      // shared owner that moved while the write was open fails it here too.
      if (submitGeneration !== identityGenerationRef.current) return;
      // Owner-currentness, NOT realm validity: an owner whose own local realm
      // is merely unconfirmed still owns their failed write and must be told
      // about it. Only the owner having moved on makes it somebody else's.
      if (!ownsScreen(origin)) return;
      if (submitIntent !== saveIntentRef.current) return;
      if (submitEditEpoch !== editEpochRef.current) return;
      armRetryable({ generation: submitGeneration, token });
      setSaveStatus('cloud-failed');
    } finally {
      // Only release our OWN claim: an identity transition already released
      // it (and belongs to a different form now), so a late stale submit
      // must not unlock the new owner's button. An owner-only move leaves the
      // generation untouched, which is why the origin decides and not it.
      if (ownsScreen(origin)) {
        submittingRef.current = false;
        setIsSubmitting(false);
      }
    }
  }, [recordIntent, profile, router, importGitHubSkills, applySaveResult, recordOutstandingIntents,
    advanceAcceptedBase, actingOrigin, ownsScreen, t, armRetryable, setSaveStatus]);

  const isValid = !!(profile.college?.trim() && profile.major?.trim() && profile.grade?.trim());

  useEffect(() => {
    if (isValid) router.prefetch('/results');
  }, [isValid, router]);

  const dismissSharedBanner = useCallback(() => setSharedBannerVisible(false), []);

  return {
    profile,
    setProfile: editProfile,
    searchWeight,
    setSearchWeight: editSearchWeight,
    oppCount,
    lastUpdated,
    ghLoading,
    ghStatus,
    sharedBanner: sharedBannerVisible ? t('home.sharedBanner') : null,
    dismissSharedBanner,
    shareCopied,
    saveStatus,
    isSubmitting,
    retryCloudSave,
    canRetrySync,
    conflictKeys,
    conflicts,
    keepMyChanges,
    useCloudVersion,
    hydrationState,
    isValid,
    identityGeneration,
    viewSnapshot,
    update,
    handleSubmit,
    handleShare,
    handleResumeParsed,
    handleResumeRemoved,
    handleGitHubImport,
  };
}
