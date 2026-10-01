'use client';

import { profileInputMessage } from '@/lib/profile-input';

import { useState, useEffect, useLayoutEffect, useRef, useMemo, useCallback, useSyncExternalStore } from 'react';
import {
  X,
  Copy,
  Loader2,
  AlertCircle,
  Sparkles,
  CheckCircle,
  RefreshCw,
  Info,
  Pencil,
  Trash2,
  RotateCcw,
} from 'lucide-react';
import { tailorResume, getTailorStatus, extractResumeBullets, type ExtractBulletsResponse } from '@/lib/api';
import ResumeProcessingNotice from './ResumeProcessingNotice';
import ProfileRefreshBanner, { profileRefreshReady } from './ProfileRefreshBanner';
import { useProfileAction } from '@/lib/use-profile-action';
import type { ProfileRefreshState } from '@/lib/use-profile-refresh';
import type { WritingTargetState } from '@/lib/use-writing-target';
import { captureOwnerToken, isOwnerTokenValid, onLocalOwnerStateChange, readUserScopedEntry, writeUserScopedRaw, type OwnerToken } from '@/lib/identity-owner';
import { createBinding, createDraft, draftLineSources, editDraft as editTailorDraft, reviewDraft, compareDraft, decodeDraft, encodeDraft, type TailorDraft, type TailorDraftBinding } from '@/lib/tailor-draft';
import RewriteWhy, { keptExplanation } from './RewriteWhy';

function subscribeOwner(changed: () => void): () => void {
  const unsubscribe = onLocalOwnerStateChange(changed);
  window.addEventListener('storage', changed);
  return () => { unsubscribe(); window.removeEventListener('storage', changed); };
}
const ownerSnapshot = () => {
  const token = captureOwnerToken();
  return JSON.stringify([token.uid, token.epoch, token.generation]);
};

import { STORAGE_KEYS } from '@/lib/storage-keys';
import { storedWraps, wrapJoin } from '@/lib/resume-input';
import { writingTargetVersion } from '@/lib/writing-target-version';
import type { Opportunity, ProfileData, TailorResponse, TailoredBullet } from '@/lib/types';
import { useT } from '@/i18n/client';
import { diffWords, isWhitespace } from '@/lib/word-diff';

// Only UID-scoped old drafts may be read for compatibility. Ownerless drafts
// cannot establish ownership and are never read, migrated, or deleted here.
function draftStorageKey(owner: string, opportunity: string): string {
  return `${STORAGE_KEYS.TAILOR_DRAFT_PREFIX}${owner}:${opportunity}`;
}
function loadSavedDraft(owner: OwnerToken, ownerId: string | null, opportunity: string):
  { status: 'found'; draft: TailorDraft } | { status: 'absent' | 'unavailable' | 'invalid' } {
  if (!ownerId || owner.uid !== ownerId || !isOwnerTokenValid(owner, ownerId)) return { status: 'unavailable' };
  const key = draftStorageKey(ownerId, opportunity);
  const entry = readUserScopedEntry(key);
  if (entry.status === 'unavailable') return { status: 'unavailable' };
  let raw = entry.status === 'present' ? entry.value : null;
  // Previous versions wrote this UID-specific slot outside the generation
  // namespace. A namespaced record (including empty text) always wins.
  if (raw === null) {
    try { raw = window.localStorage.getItem(key); }
    catch { return { status: 'unavailable' }; }
  }
  if (!isOwnerTokenValid(owner, ownerId)) return { status: 'unavailable' };
  if (raw === null) return { status: 'absent' };
  const decoded = decodeDraft(raw, ownerId, opportunity);
  return decoded.status === 'stored' || decoded.status === 'legacy'
    ? { status: 'found', draft: decoded.draft } : { status: 'invalid' };
}
const hasRuleVersion = (value: unknown): value is string =>
  typeof value === 'string' && /^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$/.test(value);
const hasReceipt = (data: { pipeline_version?: string | null; generated_at?: string | null }, binding: TailorDraftBinding) =>
  data.pipeline_version === binding.pipeline_version && typeof data.generated_at === 'string' && Number.isFinite(Date.parse(data.generated_at));

/**
 * R71 resume-tailor modal — side-by-side originals vs AI rewrite.
 *
 * Contract:
 *  - User pastes bullets into the left textarea (auto-prefilled from
 *    `profile.resume_text` via bullet-line heuristic if present).
 *  - Clicking "Tailor with AI" calls POST /api/tailor. The backend
 *    NEVER raises 5xx for LLM issues — it returns `method: "fallback"`
 *    plus warnings on every failure mode (no provider, malformed JSON,
 *    anti-fabrication catch). The UI translates each warning into a
 *    user-facing message via i18n.
 *  - When `method === "ai"`, the right panel renders each AI bullet
 *    with its `source_evidence` quote.
 *  - When `method === "fallback"`, the right panel renders the user's
 *    own originals with a "showing originals" chip + the relevant
 *    warning hint.
 *
 * State lives in this component (modal-local). Parent only owns the
 * open/close boolean — mirrors ColdEmailModal's pattern.
 */
interface TailorModalProps {
  isOpen: boolean;
  onClose: () => void;
  profile: ProfileData;
  opportunityId: string;
  opportunityTitle: string;
  /** False until the shared owner primitive is primed for the CURRENT
   *  identity — see ownerReady in use-results-interactions.ts. Fail-closed
   *  gate for Generate/Extract: neither may run while this is false, even
   *  if somehow reached (the caller already disables the CTA that opens
   *  this modal in that state — this is defense-in-depth, not the primary
   *  gate). */
  ownerReady: boolean;
  /** The exact current resolved uid, or null — see ownerScopeKey in
   *  use-results-interactions.ts. Draft persistence is keyed by this; null
   *  means no safe scope exists, so the draft stays in-memory only. */
  ownerScopeKey: string | null;
  profileRefresh?: ProfileRefreshState;
  target?: Opportunity | null;
  targetRefresh?: WritingTargetState;
  targetMembershipReady?: boolean;
  profileAvailable?: boolean;
  targetReady?: boolean;
  targetChecking?: boolean;
  targetKey?: string;
}

// Heuristic to pre-fill bullets from a parsed resume's `raw_text`. We
// don't want to invoke an LLM here — just look for lines that look
// resume-bullet-shaped (start with •, -, *, –, —, +, or a digit).
// Keeps the bar low: any string with a leading bullet glyph counts. Text
// stored before the PDF reflow keeps a bullet's wrapped lines as rows of
// their own; a row whose words show that it only wraps the bullet is joined
// back, as the experience library reads it.
const BULLET_PREFIX_RE = /^\s*([•\-*–—+]|\d+[.)])\s+(.+)$/;

function extractBulletLines(resumeText: string | undefined, limit = 12): string[] {
  if (!resumeText) return [];
  const rows = resumeText.split(/\r?\n/);
  const wraps = storedWraps(rows);
  const out: string[] = [];
  for (let index = 0; index < rows.length && out.length < limit; index++) {
    const m = rows[index].match(BULLET_PREFIX_RE);
    if (!m) continue;
    let bullet = m[2].trim();
    while (wraps[index + 1]) {
      index += 1;
      const row = rows[index].trim();
      bullet += wrapJoin(bullet, row) + row;
    }
    if (bullet.length >= 10) out.push(bullet);
  }
  return out;
}

function parseBullets(text: string): string[] {
  return text
    .split(/\r?\n/)
    .map((l) => l.trim())
    .map((l) => {
      // Tolerate user pasting raw "• " or "- " prefixes — strip them.
      const m = l.match(BULLET_PREFIX_RE);
      return m ? m[2].trim() : l;
    })
    .filter((l) => l.length > 0);
}

// C1-R2B: a stable content fingerprint for `profile` (JSON-safe plain
// data), used to detect a genuine profile change vs. a same-content
// re-render — see profileFingerprint's own doc comment below. Plain
// `JSON.stringify` is NOT canonical: two objects with identical key/value
// pairs but different property insertion order (plausible from a backend
// re-fetch or a merge step) serialize to different strings, which would
// falsely invalidate in-flight work. Object keys are sorted recursively;
// array order is preserved since arrays are ordered data, not key sets.
function canonicalFingerprint(value: unknown): string {
  if (Array.isArray(value)) {
    return `[${value.map((v) => canonicalFingerprint(v)).join(',')}]`;
  }
  if (value !== null && typeof value === 'object') {
    const keys = Object.keys(value as Record<string, unknown>).sort();
    return `{${keys
      .map((k) => `${JSON.stringify(k)}:${canonicalFingerprint((value as Record<string, unknown>)[k])}`)
      .join(',')}}`;
  }
  return JSON.stringify(value);
}

type Replier = (path: string, vars?: Record<string, string | number>) => string;

// /api/tailor refuses more than 12 bullets or a bullet over 500 characters
// (Python len: code points) instead of cutting them. Checking here names the
// exact bullet before any request; the server's refusal stays the authority.
const TAILOR_MAX_BULLETS = 12;
const TAILOR_MAX_BULLET_CHARACTERS = 500;

function tailorLimitIssue(
  bullets: string[], t: Replier, maxBullets = TAILOR_MAX_BULLETS, maxCharacters = TAILOR_MAX_BULLET_CHARACTERS,
): string | null {
  const issues: string[] = [];
  if (bullets.length > maxBullets) issues.push(t('tailor.limits.tooMany', { count: bullets.length, max: maxBullets }));
  const long = bullets.map((b, i) => ({ n: i + 1, actual: [...b].length })).filter((b) => b.actual > maxCharacters);
  if (long.length === 1) issues.push(t('tailor.limits.tooLongOne', { n: long[0].n, actual: long[0].actual, max: maxCharacters }));
  if (long.length > 1) issues.push(t('tailor.limits.tooLongMany', { items: long.map((b) => b.n).join(', '), max: maxCharacters }));
  return issues.length > 0 ? issues.join(' ') : null;
}

/** The bullet limits a TAILOR_INPUT_TOO_LARGE refusal names, or null for the
 *  combined-prompt refusal that shares the code but carries no limits. */
function refusedTailorLimits(err: unknown): [number, number] | null {
  if (!err || typeof err !== 'object' || !('code' in err) || err.code !== 'TAILOR_INPUT_TOO_LARGE' || !('detail' in err)) return null;
  const detail = err.detail as Record<string, unknown> | null;
  const bullets = detail?.max_bullets;
  const characters = detail?.max_characters_per_bullet;
  return Number.isSafeInteger(bullets) && Number.isSafeInteger(characters) ? [Number(bullets), Number(characters)] : null;
}

/**
 * Map a backend `warnings[]` entry to a user-facing i18n key. Order
 * matters — we return the first match because the route appends
 * `bullet_<i>_rejected_fabrication: ...` warnings BEFORE the catch-all
 * `all_bullets_rejected`, and the more-specific "fabrication caught"
 * message gives the user actionable info.
 */
function pickWarningMessage(warnings: string[], t: Replier): string | null {
  if (warnings.length === 0) return null;
  if (warnings.some((w) => w.startsWith('bullet_') && w.includes('rejected_fabrication'))) {
    return t('tailor.warnings.fabricationCaught');
  }
  if (warnings.includes('all_bullets_rejected')) {
    return t('tailor.warnings.allRejected');
  }
  if (warnings.includes('llm_not_configured')) {
    return t('tailor.warnings.llmUnavailable');
  }
  if (warnings.includes('llm_failed_or_invalid_json')) {
    return t('tailor.warnings.llmFailed');
  }
  if (warnings.includes('target_has_no_text')) {
    return t('tailor.warnings.targetHasNoText');
  }
  if (warnings.some((w) => w.startsWith('bullet_') && w.endsWith('review_unavailable'))) {
    return t('tailor.warnings.reviewUnavailable');
  }
  if (warnings.includes('no_bullets_provided')) {
    return t('tailor.warnings.noBullets');
  }
  return null;
}

/**
 * R71-G: render one side of a word-level diff. Removed words (original
 * side) get a struck red `<del>`; added words (tailored side) get an
 * emerald `<ins>`; equal words and whitespace render plain. textContent
 * stays the full original/tailored string so screen readers and text
 * queries see uninterrupted prose.
 */
function DiffLine({
  original,
  tailored,
  side,
}: {
  original: string;
  tailored: string;
  side: 'original' | 'tailored';
}) {
  const segments = diffWords(original, tailored);
  const skip = side === 'original' ? 'added' : 'removed';
  return (
    <>
      {segments
        .filter((s) => s.type !== skip)
        .map((s, idx) => {
          if (s.type === 'equal' || isWhitespace(s.value)) {
            return <span key={idx}>{s.value}</span>;
          }
          if (s.type === 'removed') {
            return (
              <del key={idx} className="text-red-400/90 decoration-red-300">
                {s.value}
              </del>
            );
          }
          return (
            <ins
              key={idx}
              className="no-underline bg-emerald-100 text-emerald-800 rounded px-0.5"
            >
              {s.value}
            </ins>
          );
        })}
    </>
  );
}

export default function TailorModal({
  isOpen,
  onClose,
  profile,
  opportunityId,
  opportunityTitle,
  ownerReady,
  ownerScopeKey,
  profileRefresh,
  target,
  targetRefresh,
  targetMembershipReady,
  profileAvailable = true,
  targetReady = true,
  targetChecking = false,
  targetKey,
}: TailorModalProps) {
  // R71-D: `locale` flows from the i18n context all the way down to the
  // backend so the LLM returns bullets in the user's current display
  // language. The backend tolerates unknown / region-tagged values by
  // falling back to 'en', so we can pipe `useT().locale` through raw.
  const { t, locale } = useT();
  const currentOwner = useSyncExternalStore(subscribeOwner, ownerSnapshot, () => 'server');
  const [ownerLifetime, setOwnerLifetime] = useState({ open: isOpen, key: currentOwner, retired: false });
  let retired = ownerLifetime.retired;
  if (ownerLifetime.open !== isOpen) {
    retired = false;
    setOwnerLifetime({ open: isOpen, key: currentOwner, retired: false });
  } else if (isOpen && currentOwner !== ownerLifetime.key && !retired) {
    retired = true;
    setOwnerLifetime({ ...ownerLifetime, retired: true });
  }
  const targetFingerprint = JSON.stringify([targetKey ?? null, canonicalFingerprint(target ?? { id: opportunityId, title: opportunityTitle })]);
  const sourceReady = !retired && ownerReady && profileAvailable && targetReady && !targetChecking && profileRefreshReady(profileRefresh) && (!targetRefresh || targetRefresh.status === 'ready');
  // A failed previous read must still allow an explicit fresh attempt.
  const canRequest = !retired && ownerReady && profileAvailable && (targetReady || targetChecking);
  const [userEditRevision, setUserEditRevision] = useState(0);
  const [sourceChanged, setSourceChanged] = useState(false);
  const [pipelineVersion, setPipelineVersion] = useState<string | null>(null);
  const [record, setRecord] = useState<TailorDraft | null>(null);
  const draft = record?.text ?? '';
  const limitIssue = useMemo(() => tailorLimitIssue(parseBullets(draft), t), [draft, t]);
  const [draftStatus, setDraftStatus] = useState<'checking' | 'current' | 'stale' | 'unknown'>('checking');
  const [bindingState, setBindingState] = useState<{ key: string; binding: TailorDraftBinding } | null>(null);
  const [storageRead, setStorageRead] = useState<'ready' | 'unavailable' | 'invalid'>('unavailable');
  const [saveFailed, setSaveFailed] = useState(false);
  const [inputRejected, setInputRejected] = useState(false);
  const [reviewing, setReviewing] = useState(false);
  const [rulesNeedReview, setRulesNeedReview] = useState(false);
  const outputBindingRef = useRef<TailorDraftBinding | null>(null);
  const draftOwnerRef = useRef<OwnerToken | null>(null);
  const freshDraftRef = useRef<{ profile: string; target: string | null } | null>(null);
  const statusAttemptRef = useRef(0);
  const skipPersistRef = useRef(false);
  const [rulesUnavailable, setRulesUnavailable] = useState(false);


  // Heuristic prefill from `profile.resume_text` — used when no saved
  // draft exists for this opportunity. `useMemo` so the extraction is
  // stable per profile.
  const heuristicPrefill = useMemo(
    () => extractBulletLines(profile.resume_text).join('\n'),
    [profile.resume_text],
  );

  // C1-R2B: `profile` (the WHOLE object, not just resume_text) is a direct
  // input to tailorResume() and to the extract heuristic — a Generate/
  // Extract already in flight is computing a result against THIS profile,
  // and that result becomes stale the instant the modal moves on to a
  // different one. A content fingerprint (not the object reference — a
  // same-content refetch must NOT count as a change) retires network work
  // while preserving the existing editor, so any real profile change
  // invalidates in-flight work even when resume_text itself didn't move.
  const profileFingerprint = useMemo(() => canonicalFingerprint(profile), [profile]);

  // R71-F: initial draft = saved draft for THIS opportunity (if any)
  // over heuristic prefill over empty. Computed once per modal open;
  // see the open-effect below for the actual loading.
  const [draftRestored, setDraftRestored] = useState(false);
  const bindingKey = JSON.stringify([profileFingerprint, targetFingerprint, pipelineVersion]);
  const currentBinding = bindingState?.key === bindingKey ? bindingState.binding : null;
  const draftStale = rulesNeedReview || draftStatus === 'stale';
  const needsReview = rulesNeedReview || draftStatus === 'stale' || draftStatus === 'unknown';
  const [loading, setLoading] = useState(false);
  const [resp, setResp] = useState<TailorResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  // R71-G: per-bullet copy-confirmation state. Keyed by bullet index
  // so two cards' "Copied!" states can't collide if the user spams
  // copy buttons quickly.
  const [copiedBulletIdx, setCopiedBulletIdx] = useState<number | null>(null);
  // R71-E: snapshot the bullets actually submitted to the backend so
  // we can render each tailored bullet next to its source. We can't
  // just re-parse `draft` because the user might edit the textarea
  // *after* clicking Generate and we'd then pair the wrong originals.
  const [submittedBullets, setSubmittedBullets] = useState<string[]>([]);
  // R71-G: server-side AI availability, probed on open. `null` = unknown
  // (loading or probe failed), so we only show the "AI unavailable" banner
  // on an explicit `false` — a failed probe shouldn't scare the user when
  // the generate path might still work.
  const [aiAvailable, setAiAvailable] = useState<boolean | null>(null);
  // R71-G: smart-extract (LLM resume → bullets) loading state.
  const [extracting, setExtracting] = useState(false);
  const [extractionResult, setExtractionResult] = useState<ExtractBulletsResponse | null>(null);
  const [extractionError, setExtractionError] = useState(false);
  // R73: per-bullet review — `rejected` indices are excluded from copy /
  // use-as-originals; `edits` override a bullet's text in place; `editingIdx`
  // is the card currently in inline-edit mode. Reset on every new result so
  // a prior round's decisions don't bleed into the next tailor.
  const [rejected, setRejected] = useState<Set<number>>(new Set());
  const [edits, setEdits] = useState<Record<number, string>>({});
  // Rewrites the student chose to use without the posting's terms.
  const [plain, setPlain] = useState<Set<number>>(new Set());
  const [editingIdx, setEditingIdx] = useState<number | null>(null);
  const [editDraft, setEditDraft] = useState('');

  const modalRef = useRef<HTMLDivElement>(null);
  const previouslyFocusedRef = useRef<HTMLElement | null>(null);
  // W13 target isolation: one TailorModal instance serves many opportunities
  // on the favorites page. A slow /tailor response from target A must never
  // render under target B after a close→reopen — every open/target change
  // bumps the generation, and a landing response is dropped unless it
  // belongs to the current generation AND (when the backend echoes it) the
  // current target.

  // C1-R2B: every async Generate/Extract continuation must confirm, AFTER
  // its own await, that the context it started under is STILL current —
  // component still mounted, and still the LATEST "session": nothing about
  // the modal's open/close lifecycle, opportunity, owner scope, owner
  // readiness, or profile CONTENT has changed since invocation.
  // sessionEpochRef is the single source of truth for that: it is bumped on
  // ANY of isOpen/opportunityId/ownerScopeKey/ownerReady/profileFingerprint
  // changing — including a CLOSE with no follow-up reopen, a mid-session
  // ownerReady drop (e.g. a background load hiccup) even without a close,
  // and a profile refetch landing with genuinely different content while
  // Generate/Extract is still in flight (profile is a direct input to both
  // — see profileFingerprint's own doc comment). This is the fix for the
  // gap a plain per-kind attempt counter has on its own: "N1 pending ->
  // close -> reopen -> user never issues N2" would otherwise still pass a
  // bare attempt-number check (nothing ever bumped it), letting N1's stale
  // result apply into the reopened modal as though it were current. Every
  // Generate/Extract call ALSO bumps its own kind's attempt counter, so a
  // NEWER same-kind call within the SAME session still correctly
  // supersedes an older one too.
  const mountedRef = useRef(true);
  useEffect(() => {
    mountedRef.current = true;
    return () => { mountedRef.current = false; };
  }, []);
  // Mirrors of the isOpen/opportunityId/ownerScopeKey/ownerReady/
  // profileFingerprint PROPS, updated via useLayoutEffect (not useEffect/
  // "passive effect") so the update is committed SYNCHRONOUSLY right after
  // the DOM mutation, before the browser can paint or process anything else
  // — no window where a continuation's stillCurrent() check could read a
  // stale value that hasn't caught up yet. Layout effects are the standard
  // React escape hatch for "this ref write must happen synchronously
  // relative to the render that caused it"; a plain useEffect is deferred
  // and could in principle interleave with an already-queued microtask from
  // an in-flight fetch's own .then chain.
  const isOpenRef = useRef(isOpen);
  const opportunityIdRef = useRef(opportunityId);
  const ownerScopeKeyRef = useRef(ownerScopeKey);
  const ownerReadyRef = useRef(ownerReady);
  const profileFingerprintRef = useRef(profileFingerprint);
  const targetFingerprintRef = useRef(targetFingerprint);
  const sessionEpochRef = useRef(0);
  const sourceReadyRef = useRef(sourceReady);
  useLayoutEffect(() => {
    const changed =
      isOpen !== isOpenRef.current ||
      opportunityId !== opportunityIdRef.current ||
      ownerScopeKey !== ownerScopeKeyRef.current ||
      ownerReady !== ownerReadyRef.current ||
      profileFingerprint !== profileFingerprintRef.current || targetFingerprint !== targetFingerprintRef.current || sourceReady !== sourceReadyRef.current || retired;
    isOpenRef.current = isOpen;
    opportunityIdRef.current = opportunityId;
    ownerScopeKeyRef.current = ownerScopeKey;
    ownerReadyRef.current = ownerReady;
    const changedProfile = profileFingerprint !== profileFingerprintRef.current;
    targetFingerprintRef.current = targetFingerprint;
    profileFingerprintRef.current = profileFingerprint;
    sourceReadyRef.current = sourceReady;
    if (changed) {
      sessionEpochRef.current += 1;
      // Retire network callbacks without taking ownership of the editor.
      setLoading(false); setExtracting(false); setReviewing(false);
      if (changedProfile) setSourceChanged(true);
    }
  }, [isOpen, opportunityId, ownerScopeKey, ownerReady, profileFingerprint, targetFingerprint, sourceReady, retired]);
  const generateAttemptRef = useRef(0);
  const extractAttemptRef = useRef(0);

  const action = useProfileAction<'generate' | 'extract' | 'review'>({
    isOpen: isOpen && !retired, profile, profileAvailable,
    scopeKey: JSON.stringify([ownerScopeKey, opportunityId, targetFingerprint]), editRevision: userEditRevision,
    refresh: profileRefresh, target, targetRefresh,
    readiness: sourceReady ? 'ready'
      : canRequest && (targetChecking || profileRefresh?.status === 'checking') ? 'waiting' : 'blocked',
    execute: (intent) => { if (intent === 'extract') void handleExtractFromResume(); else if (intent === 'review') void handleReviewDraft(); else void handleGenerate(); },
  });
  const { request: requestAction, cancel: cancelAction } = action;
  const markUserEdit = () => {
    cancelAction(); setUserEditRevision((value) => value + 1);
    generateAttemptRef.current += 1; extractAttemptRef.current += 1;
    setLoading(false); setExtracting(false); setReviewing(false);
  };
  const requestGeneration = () => { if (canRequest && !loading && !extracting && !reviewing) requestAction('generate'); };
  const requestReview = () => { if (canRequest && !loading && !extracting && !reviewing) requestAction('review'); };
  const requestExtraction = () => { if (canRequest && !loading && !extracting && !reviewing) requestAction('extract'); };

  // Every close path (the X button, the backdrop click, Escape) routes
  // through here instead of calling the `onClose` prop directly.
  // Invalidation happens IMMEDIATELY, synchronously, inside the SAME
  // click/keydown handler that initiates the close — not by waiting for
  // `onClose` to update the PARENT's state and for that to flow back down
  // as a new `isOpen` prop, which the useLayoutEffect above would only
  // then notice on the NEXT render. That round-trip is fast in practice,
  // but this removes the dependency on it entirely: the epoch is stale the
  // instant the user clicks close, full stop. isOpenRef is pre-emptively
  // set to false too, so the layout effect's own (now redundant) detection
  // on the next render is a no-op rather than a harmless-but-confusing
  // double bump.
  const invalidateAndClose = useCallback(() => {
    sessionEpochRef.current += 1;
    isOpenRef.current = false;
    cancelAction();
    onClose();
  }, [onClose, cancelAction]);

  // Preserve the editor across material refreshes; initialize only on open or
  // a target change. A failed read never licenses overwriting an unread draft.
  const initializedRef = useRef<string | null>(null);
  useEffect(() => {
    if (!isOpen) { initializedRef.current = null; return; }
    if (retired) return;
    const key = JSON.stringify([ownerScopeKey, opportunityId]);
    if (initializedRef.current === key) return;
    initializedRef.current = key;
    skipPersistRef.current = true;
    const owner = captureOwnerToken();
    draftOwnerRef.current = owner;
    const saved = loadSavedDraft(owner, ownerScopeKey, opportunityId);
    const absent = saved.status === 'absent';
    freshDraftRef.current = absent ? { profile: profileFingerprint,
      target: targetReady && !targetChecking && (!targetRefresh || targetRefresh.status === 'ready') ? targetFingerprint : null } : null;
    setRecord(saved.status === 'found' ? saved.draft : createDraft(ownerScopeKey ?? 'unresolved', opportunityId,
      absent ? heuristicPrefill : '', absent ? (heuristicPrefill ? 'heuristic' : 'manual') : 'unknown', null));
    setStorageRead(saved.status === 'invalid' ? 'invalid' : saved.status === 'unavailable' ? 'unavailable' : 'ready');
    setPipelineVersion(null); setRulesUnavailable(false);
    setSaveFailed(false); setInputRejected(false); setDraftStatus('checking'); setBindingState(null); setRulesNeedReview(false);
    setDraftRestored(saved.status === 'found' && saved.draft.text.length > 0);
    setSourceChanged(false); outputBindingRef.current = null;
    setResp(null); setError(null); setCopied(false); setCopiedBulletIdx(null);
    setLoading(false); setExtracting(false); setReviewing(false); setExtractionResult(null); setExtractionError(false);
    setSubmittedBullets([]); setRejected(new Set()); setEdits({}); setPlain(new Set()); setEditingIdx(null); setEditDraft('');
  }, [isOpen, retired, heuristicPrefill, opportunityId, ownerScopeKey, profileFingerprint, targetFingerprint, targetReady, targetChecking, targetRefresh]);

  const persistRecord = useCallback((value: TailorDraft) => {
    const owner = draftOwnerRef.current;
    if (!isOpen || !isOpenRef.current || retired || !profileAvailable || storageRead !== 'ready' || !owner
      || value.owner_id !== ownerScopeKey || value.opportunity_id !== opportunityId || owner.uid !== ownerScopeKey) return;
    setSaveFailed(!writeUserScopedRaw(draftStorageKey(value.owner_id, value.opportunity_id), encodeDraft(value), owner));
  }, [isOpen, retired, profileAvailable, storageRead, ownerScopeKey, opportunityId, setSaveFailed]);
  useEffect(() => {
    if (skipPersistRef.current) { skipPersistRef.current = false; return; }
    if (record) persistRecord(record);
  }, [record, persistRecord]);

  // A newly typed draft can bind to this open's original material snapshot.
  // Saved unknown/stale drafts never acquire new provenance through typing.
  const anchorFreshTarget = useCallback(() => {
    const fresh = freshDraftRef.current;
    // Initial cards are not source receipts. Attach a new, unsaved draft to
    // the first verified full target only; later target changes stay stale.
    if (fresh && fresh.target === null && fresh.profile === profileFingerprint) fresh.target = targetFingerprint;
  }, [profileFingerprint, targetFingerprint]);
  const bindFresh = useCallback((value: TailorDraft, binding: TailorDraftBinding): TailorDraft => {
    const fresh = freshDraftRef.current;
    return fresh && fresh.profile === profileFingerprint && fresh.target === targetFingerprint && value.origin.binding === null
      && value.owner_id === ownerScopeKey && value.opportunity_id === opportunityId
      ? { ...value, origin: { ...value.origin, binding } } : value;
  }, [profileFingerprint, targetFingerprint, ownerScopeKey, opportunityId]);

  useEffect(() => {
    if (!isOpen || retired) return;
    const owner = captureOwnerToken(); const attempt = ++statusAttemptRef.current;
    let ignore = false;
    getTailorStatus().then((status) => {
      if (ignore || !mountedRef.current || !isOpenRef.current || opportunityIdRef.current !== opportunityId || statusAttemptRef.current !== attempt || !isOwnerTokenValid(owner, owner.uid)) return;
      if (!hasRuleVersion(status.pipeline_version)) throw new Error('Invalid rule version');
      setAiAvailable(status.ai_available); setPipelineVersion(status.pipeline_version);
    }).catch(() => {
      if (!ignore && mountedRef.current && isOpenRef.current && opportunityIdRef.current === opportunityId && statusAttemptRef.current === attempt && isOwnerTokenValid(owner, owner.uid)) {
        setAiAvailable(null); setPipelineVersion(null); setRulesUnavailable(true);
      }
    });
    return () => { ignore = true; };
  }, [isOpen, retired, ownerScopeKey, opportunityId]);

  useEffect(() => {
    if (!isOpen || !sourceReady || !pipelineVersion) return;
    const owner = captureOwnerToken(); const epoch = sessionEpochRef.current; let ignore = false;
    createBinding(profile, target?.id === opportunityId ? target : null, pipelineVersion).then(binding => {
      if (ignore || !mountedRef.current || !isOpenRef.current || sessionEpochRef.current !== epoch || !isOwnerTokenValid(owner, owner.uid)) return;
      anchorFreshTarget();
      setBindingState({ key: bindingKey, binding }); setRulesUnavailable(false);
      setRecord(previous => previous ? bindFresh(previous, binding) : previous);
    }).catch(() => { if (!ignore) { setBindingState(null); setRulesUnavailable(true); } });
    return () => { ignore = true; };
  }, [isOpen, sourceReady, pipelineVersion, bindingKey, profile, target, opportunityId, bindFresh, anchorFreshTarget]);

  useEffect(() => {
    let ignore = false;
    if (!record || !currentBinding) return;
    compareDraft(record, currentBinding).then(status => { if (!ignore) setDraftStatus(status); })
      .catch(() => { if (!ignore) setDraftStatus('unknown'); });
    return () => { ignore = true; };
  }, [record, currentBinding]);

  // Every explicit action checks current server rules, then sends that exact
  // version. The backend refuses a deploy between this check and the POST.
  async function checkedBinding(stillCurrent: () => boolean): Promise<TailorDraftBinding | null> {
    const attempt = ++statusAttemptRef.current;
    const status = await getTailorStatus();
    if (!stillCurrent() || attempt !== statusAttemptRef.current) return null;
    if (!hasRuleVersion(status.pipeline_version)) throw new Error(t('tailor.rulesUnavailable'));
    setPipelineVersion(status.pipeline_version); setAiAvailable(status.ai_available); setRulesUnavailable(false);
    const binding = await createBinding(profile, target?.id === opportunityId ? target : null, status.pipeline_version);
    if (!stillCurrent() || attempt !== statusAttemptRef.current) return null;
    anchorFreshTarget();
    setBindingState({ key: JSON.stringify([profileFingerprint, targetFingerprint, status.pipeline_version]), binding });
    return binding;
  }
  function handleRuleFailure(error: unknown) {
    if (error && typeof error === 'object' && 'code' in error && error.code === 'TAILOR_PIPELINE_CHANGED') {
      setRulesNeedReview(true); setPipelineVersion(null); setError(t('tailor.rulesChanged'));
    }
  }
  async function handleReviewDraft() {
    if (!sourceReadyRef.current || !record) return;
    const owner = captureOwnerToken(), epoch = sessionEpochRef.current, attempt = ++generateAttemptRef.current;
    const stillCurrent = () => mountedRef.current && sessionEpochRef.current === epoch
      && generateAttemptRef.current === attempt && isOwnerTokenValid(owner, owner.uid);
    setReviewing(true); setError(null);
    try {
      const binding = await checkedBinding(stillCurrent);
      if (!binding) return;
      const reviewed = await reviewDraft(record, binding);
      if (!stillCurrent()) return;
      freshDraftRef.current = null;
      setRecord(reviewed); setRulesNeedReview(false); setDraftStatus('current'); setSourceChanged(false);
    } catch { if (stillCurrent()) setError(t('tailor.rulesUnavailable')); }
    finally { if (stillCurrent()) setReviewing(false); }
  }
  const handleClearDraft = () => {
    markUserEdit();
    freshDraftRef.current = { profile: profileFingerprint, target: targetFingerprint };
    setRecord(createDraft(ownerScopeKey ?? 'unresolved', opportunityId, '', 'manual', currentBinding));
    setDraftRestored(false); setRulesNeedReview(false);
  };

  // Focus trap + escape + body-overflow lock. Lifted verbatim from
  // ColdEmailModal so the two modals feel identical to keyboard users.
  useEffect(() => {
    if (!isOpen) return;
    previouslyFocusedRef.current = document.activeElement as HTMLElement;

    const modal = modalRef.current;
    if (modal) {
      const focusable = modal.querySelector<HTMLElement>(
        'button, [href], input, textarea, select, [tabindex]:not([tabindex="-1"])',
      );
      focusable?.focus();
    }

    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';

    function onKeyDown(e: KeyboardEvent) {
      if (e.key === 'Escape') {
        e.preventDefault();
        invalidateAndClose();
        return;
      }
      if (e.key !== 'Tab' || !modalRef.current) return;
      const focusables = modalRef.current.querySelectorAll<HTMLElement>(
        'button, [href], input:not([disabled]), textarea:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])',
      );
      if (focusables.length === 0) return;
      const first = focusables[0];
      const last = focusables[focusables.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    }

    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('keydown', onKeyDown);
      document.body.style.overflow = prevOverflow;
      previouslyFocusedRef.current?.focus();
    };
  }, [isOpen, invalidateAndClose]);

  // R71-G: LLM-extract bullets from the saved resume text and load them
  // into the draft. Backend degrades to the glyph heuristic on any LLM
  // issue, so this always returns *some* bullets when the resume has them.
  // No-op silently if extraction yields nothing (keeps whatever's typed).
  //
  // C1-R2B (P0-A): this is the exact call site the reported leak came
  // through — a deferred extract that resolves AFTER the user has moved on
  // (closed, switched identity, unmounted) used to still call saveDraft
  // unconditionally, repopulating whatever slot the CURRENT reader would
  // see. stillCurrent() below is checked BEFORE every post-await side
  // effect, including the setDraft (React state — harmless post-unmount on
  // its own, since React 18 no-ops it) but critically before the raw
  // saveDraft localStorage write, which is NOT mount-aware by itself.
  async function handleExtractFromResume() {
    if (!profile.resume_text || extracting || !sourceReadyRef.current) return;
    const owner = captureOwnerToken();
    if (!isOwnerTokenValid(owner, owner.uid)) return;
    const attempt = ++extractAttemptRef.current;
    const sessionEpoch = sessionEpochRef.current;
    const ctx = { opportunityId, ownerScopeKey };
    // sessionEpoch covers close (with or without a reopen), an owner
    // switch, or an opportunity change — ANY of those invalidates this
    // attempt outright. extractAttemptRef additionally covers a NEWER
    // extract issued within the SAME still-open session (a manual draft
    // edit ALSO bumps it — see the textarea onChange handler below, so a
    // late extract can never clobber fresher typing either).
    const stillCurrent = () =>
      mountedRef.current &&
      sessionEpochRef.current === sessionEpoch &&
      extractAttemptRef.current === attempt && isOwnerTokenValid(owner, owner.uid);

    setExtracting(true);
    setExtractionResult(null);
    setExtractionError(false);
    try {
      const binding = await checkedBinding(stillCurrent);
      if (!binding) return;
      const data = await extractResumeBullets(profile.resume_text, { expectedPipelineVersion: binding.pipeline_version });
      if (!stillCurrent()) return; // closed/unmounted/switched/superseded — drop silently, no write
      if (!hasReceipt(data, binding)) throw new Error('Invalid extraction receipt');
      setExtractionResult(data);
      if (data.bullets.length > 0) {
        freshDraftRef.current = null;
        setRecord(createDraft(ctx.ownerScopeKey ?? 'unresolved', ctx.opportunityId, data.bullets.join('\n'), 'extract', binding, data.processing));
        setSourceChanged(false); setRulesNeedReview(false); setDraftStatus('current');
        setDraftRestored(false);
      }
    } catch (error) {
      // Failed or mismatched extraction never replaces the user's text.
      if (stillCurrent()) { setExtractionError(true); handleRuleFailure(error); }
    } finally {
      // An old, superseded attempt's finally must never clear a NEWER
      // attempt's `extracting` spinner.
      if (stillCurrent()) setExtracting(false);
    }
  }

  async function handleGenerate() {
    if (!sourceReadyRef.current) return;
    // Only the server-issued receipt from this exact checked target can
    // authorize target-conditioned generation; local review cannot create it.
    const expectedTargetVersion = writingTargetVersion(target);
    if (!expectedTargetVersion) { setError(t('tailor.targetVersionUnavailable')); return; }
    const owner = captureOwnerToken();
    if (!isOwnerTokenValid(owner, owner.uid)) return;
    const bullets = parseBullets(draft);
    if (bullets.length === 0) {
      setError(t('tailor.fillBulletsFirst'));
      return;
    }
    const overLimit = tailorLimitIssue(bullets, t);
    if (overLimit) { setError(overLimit); return; }
    const attempt = ++generateAttemptRef.current;
    const sessionEpoch = sessionEpochRef.current;
    const ctx = { opportunityId, ownerScopeKey };
    // C1-R2B (P1): a close/reopen cycle with NO follow-up N2 must still
    // invalidate N1 — that's sessionEpoch's job (bumped synchronously by
    // the close itself, in the useLayoutEffect above, independent of
    // whether a new Generate is ever issued). generateAttemptRef
    // additionally covers N1 -> close/reopen -> N2 (a genuine newer
    // same-session invocation): N2 always bumps it before N1's
    // continuation can check it, so N1's stillCurrent() reads false either
    // way — via the epoch if nothing replaced it, via the attempt number
    // if something did.
    const stillCurrent = () =>
      mountedRef.current &&
      sessionEpochRef.current === sessionEpoch &&
      generateAttemptRef.current === attempt && isOwnerTokenValid(owner, owner.uid);

    setLoading(true);
    setError(null);
    setCopied(false);
    // Keep the previous reviewed output until a new result actually succeeds.
    try {
      const binding = await checkedBinding(stillCurrent);
      if (!binding || !record) return;
      const bound = bindFresh(record, binding);
      const status = await compareDraft(bound, binding);
      if (!stillCurrent()) return;
      setDraftStatus(status);
      if (bound !== record) setRecord(bound);
      if (status !== 'current' || rulesNeedReview) return;
      // A promoted line's evidence is still the student's own bullet it came from.
      const sources = draftLineSources(bound, bullets);
      const data = await tailorResume(profile, ctx.opportunityId, bullets, { locale, expectedPipelineVersion: binding.pipeline_version, expectedTargetVersion,
        ...(sources.some((source, i) => source !== bullets[i]) ? { sourceBullets: sources } : {}) });
      if (!stillCurrent()) return; // superseded — N1's result must never appear as N2's
      // W13: a response the backend stamped for a DIFFERENT target than the
      // one this call was made for is dropped outright.
      if (data.opportunity_id !== ctx.opportunityId || !hasReceipt(data, binding)) throw new Error(t('tailor.rulesUnavailable'));
      if (data.target_version !== expectedTargetVersion) throw new Error(t('tailor.targetVersionUnavailable'));
      outputBindingRef.current = binding;
      setSubmittedBullets(bullets);
      setRejected(new Set()); setEdits({}); setPlain(new Set()); setEditingIdx(null);
      setSourceChanged(false);
      setResp(data);
    } catch (err) {
      if (!stillCurrent()) return;
      if (err && typeof err === 'object' && 'code' in err && err.code === 'WRITING_TARGET_CHANGED') {
        setError(t('tailor.targetVersionChanged'));
      } else {
        const limits = refusedTailorLimits(err);
        setError(limits
          ? tailorLimitIssue(bullets, t, ...limits) ?? t('tailor.limits.server', { bullets: limits[0], characters: limits[1] })
          : profileInputMessage(err, t) ?? (err instanceof Error ? err.message : t('tailor.failedToTailor')));
        handleRuleFailure(err);
      }
    } finally {
      // Old finally blocks must not clear a NEWER request's loading state.
      if (stillCurrent()) setLoading(false);
    }
  }

  // R73: a bullet's effective text = the user's inline edit if present,
  // else the rewrite (without the posting's terms when the student chose
  // that). The kept set excludes rejected indices.
  const effectiveText = useCallback(
    (i: number, b: TailoredBullet) => edits[i] ?? (plain.has(i) && b.alternative ? b.alternative : b.text),
    [edits, plain],
  );

  // Each kept line with its evidence: the bullet the server checked it against.
  const keptLines = useCallback((): { text: string; source: string }[] => {
    if (!resp) return [];
    return resp.tailored_bullets
      .map((b, i) => ({ i, text: effectiveText(i, b), source: b.status && b.source_evidence ? b.source_evidence : submittedBullets[b.source_index] ?? '' }))
      .filter(({ i }) => !rejected.has(i))
      .map(({ text, source }) => ({ text, source: source || text }));
  }, [resp, rejected, effectiveText, submittedBullets]);
  const keptTexts = useCallback(() => keptLines().map(({ text }) => text), [keptLines]);

  function toggleReject(i: number) {
    markUserEdit();
    setRejected((prev) => {
      const next = new Set(prev);
      if (next.has(i)) next.delete(i);
      else next.add(i);
      return next;
    });
    if (editingIdx === i) setEditingIdx(null);
  }

  function startEdit(i: number, current: string) {
    markUserEdit();
    setEditingIdx(i);
    setEditDraft(current);
  }

  function togglePlain(i: number) {
    markUserEdit();
    setPlain((prev) => {
      const next = new Set(prev);
      if (next.has(i)) next.delete(i);
      else next.add(i);
      return next;
    });
  }

  function saveEdit(i: number) {
    markUserEdit();
    const trimmed = editDraft.trim();
    setEdits((prev) => ({
      ...prev,
      [i]: trimmed || (resp?.tailored_bullets[i]?.text ?? ''),
    }));
    setEditingIdx(null);
    setEditDraft('');
  }

  function cancelEdit() {
    markUserEdit();
    setEditingIdx(null);
    setEditDraft('');
  }

  // R71-G: promote the (kept + edited) AI rewrite back into the draft so the
  // user can iterate without retyping. Clearing the result resets the right
  // panel to the empty prompt and flips the CTA back to "Tailor with AI".
  function handleUseAsOriginals() {
    const kept = keptLines();
    if (kept.length === 0) return;
    const next = kept.map(({ text }) => text).join('\n');
    let promoted: TailorDraft;
    try {
      promoted = createDraft(ownerScopeKey ?? 'unresolved', opportunityId, next, 'reviewed_output', outputBindingRef.current, undefined,
        kept.map(({ text, source }) => ({ line: text, source })));
    } catch { setInputRejected(true); return; }
    markUserEdit(); setInputRejected(false);
    freshDraftRef.current = null;
    setRecord(promoted);
    setDraftRestored(false);
    // See the textarea onChange handler below — a manual draft mutation of
    // any kind invalidates a still-pending Extract; setExtracting(false)
    // synchronously too, so an invalidated extract's own guarded finally
    // (now correctly skipped) leaves nothing else to clear the spinner.
    extractAttemptRef.current += 1;
    setExtracting(false);
    setResp(null);
    setSubmittedBullets([]);
    setRejected(new Set());
    setEdits({});
    setPlain(new Set());
    setEditingIdx(null);
    setError(null);
    setCopied(false);
  }

  // The "Copied" flashes are the one delayed UI in this modal that was not
  // owner/session-scoped: their timers ran to completion regardless of what
  // happened to the modal in between. Same guard the Extract/Generate
  // continuations use — the epoch covers close, an owner switch, an
  // opportunity change and a profile change; mountedRef covers unmount.
  const captureCopySession = () => {
    const epoch = sessionEpochRef.current;
    return () => mountedRef.current && sessionEpochRef.current === epoch;
  };

  async function handleCopyAll() {
    const kept = keptTexts();
    if (kept.length === 0) return;
    const current = captureCopySession();
    const text = kept.map((b) => `• ${b}`).join('\n');
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      // Rejects in insecure contexts and unfocused documents. Nothing was
      // copied, so nothing may say it was; the per-bullet handler already
      // swallowed this, Copy All let it surface as an unhandled rejection.
      return;
    }
    if (!current()) return;
    setCopied(true);
    setTimeout(() => { if (current()) setCopied(false); }, 2000);
  }

  // R71-F: per-bullet copy. Idx-keyed confirmation state so two
  // adjacent cards' "Copied" flashes can't collide when the user
  // clicks them in rapid succession.
  async function handleCopyBullet(idx: number, text: string) {
    const current = captureCopySession();
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      // navigator.clipboard.writeText can reject in insecure contexts
      // (HTTP, sandboxed iframes). Swallow — the global Copy All button
      // is the documented path, this is just a shortcut.
      return;
    }
    if (!current()) return;
    setCopiedBulletIdx(idx);
    setTimeout(() => {
      if (current()) setCopiedBulletIdx((cur) => (cur === idx ? null : cur));
    }, 1800);
  }

  if (!isOpen || retired) return null;

  const warningMessage = resp ? pickWarningMessage(resp.warnings, t) : null;
  const isFallback = resp?.method === 'fallback';
  const hasResults = resp !== null && resp.tailored_bullets.length > 0;
  // w14.0 returns every bullet with a status; older responses dropped refused ones.
  const statused = hasResults && resp.tailored_bullets.every((b) => b.status !== undefined);
  const rewrittenCount = resp?.tailored_bullets.filter((b) => b.status === 'rewritten').length ?? 0;
  // R73: review is offered only on a genuine AI rewrite (fallback echoes the
  // user's own originals — nothing to accept/reject there).
  const reviewable = resp?.method === 'ai' && hasResults;
  const keptCount = keptTexts().length;

  return (
    <div
      className="fixed inset-0 z-[55] flex sm:items-center sm:justify-center"
      role="dialog"
      aria-modal="true"
      aria-labelledby="tailor-modal-title"
    >
      <div
        className="absolute inset-0 bg-gray-900/60 backdrop-blur-sm"
        onClick={invalidateAndClose}
        aria-hidden="true"
      />

      <div
        ref={modalRef}
        className="relative w-full sm:max-w-5xl sm:mx-4 bg-white sm:rounded-2xl shadow-2xl h-full sm:h-auto sm:max-h-[90vh] flex flex-col overflow-hidden"
      >
        {/* Header */}
        <div className="flex items-start justify-between px-4 sm:px-6 py-3 sm:py-4 border-b border-gray-100 shrink-0">
          <div className="flex items-start gap-3 min-w-0">
            <div className="w-9 h-9 rounded-xl bg-indigo-50 flex items-center justify-center shrink-0" aria-hidden="true">
              <Sparkles className="w-5 h-5 text-indigo-600" />
            </div>
            <div className="min-w-0">
              <h2
                id="tailor-modal-title"
                className="text-lg font-bold text-gray-900"
              >
                {t('tailor.title')}
              </h2>
              <p className="text-sm text-gray-500 truncate max-w-md">
                {opportunityTitle}
              </p>
              <p className="text-xs text-gray-400 mt-1 max-w-md hidden sm:block">
                {t('tailor.subtitle')}
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={invalidateAndClose}
            className="p-2 rounded-lg hover:bg-gray-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 transition-colors shrink-0"
            aria-label={t('tailor.closeAria')}
          >
            <X className="w-5 h-5 text-gray-400" aria-hidden="true" />
          </button>
        </div>

        <ProfileRefreshBanner refresh={profileRefresh} targetRefresh={targetRefresh} targetReady={targetMembershipReady ?? targetReady} profileAvailable={profileAvailable} locale={locale}
          onBeforeReview={() => window.confirm(locale === 'zh' ? '离开会丢弃尚未保存的右侧编辑。确定核对资料？' : 'Leaving will discard unsaved output edits. Review your profile?')} />
        {action.busy && <p role="status" className="shrink-0 px-5 py-2 text-sm text-gray-600">{locale === 'zh' ? (targetRefresh ? '正在核对本次操作的最新资料及机会…' : '正在核对本次操作的最新资料…') : (targetRefresh ? 'Checking the latest profile and opportunity for this action…' : 'Checking the latest profile for this action…')}</p>}
        {action.error && <p role="alert" className="shrink-0 border-b border-amber-200 bg-amber-50 px-5 py-2 text-sm text-amber-950">{locale === 'zh' ? (targetRefresh ? '本次操作未执行。草稿仍保留，请核对资料及机会后重试。' : '本次操作未执行。草稿仍保留，请核对资料后重试。') : (targetRefresh ? 'This action did not run. Your draft is kept. Review your profile and opportunity and try again.' : 'This action did not run. Your draft is kept. Review your profile and try again.')}</p>}
        {sourceChanged && <p role="status" className="shrink-0 px-5 py-2 text-sm text-amber-800">{locale === 'zh' ? '资料已更新；现有文字和编辑仍保留。重新提取或改写前请核对。' : 'Your profile changed. Existing text and edits are kept; review them before extracting or tailoring again.'}</p>}

        {/* R71-G: up-front AI-unavailable banner. Only on explicit false
            (not on a failed/loading probe) so we never falsely warn. */}
        {aiAvailable === false && (
          <div className="flex items-start gap-2 px-4 sm:px-6 py-2.5 bg-amber-50 border-b border-amber-200 text-[12.5px] text-amber-800 shrink-0">
            <AlertCircle className="w-4 h-4 text-amber-500 shrink-0 mt-0.5" aria-hidden="true" />
            <span>{t('tailor.aiUnavailableBanner')}</span>
          </div>
        )}

        {/* Body — two panel layout */}
        <div className="flex-1 flex flex-col lg:flex-row min-h-0 overflow-y-auto lg:overflow-hidden">
          {/* Left panel — originals */}
          <div className="flex-1 flex flex-col lg:border-r border-gray-100 min-w-0 shrink-0 lg:min-h-0 lg:overflow-y-auto">
            <div className="px-5 pt-4 pb-2 shrink-0">
              <div className="flex items-center justify-between gap-2 mb-1.5">
                <label
                  htmlFor="tailor-bullets-input"
                  className="block text-xs font-semibold text-gray-500 uppercase tracking-wider"
                >
                  {t('tailor.originalHeading')}
                </label>
                {/* R71-F: "Restored from your last edit" chip with one-
                    click clear. Sticks around as a non-blocking hint
                    rather than auto-dismissing on the first keystroke
                    so the user actually notices their last session
                    was restored — auto-clear would feel like the chip
                    flickered and vanished before being read. */}
                {draftRestored && (
                  <span className="inline-flex items-center gap-1.5 text-[10px] font-medium text-indigo-700 bg-indigo-50 px-2 py-0.5 rounded-full">
                    {t('tailor.draftRestored')}
                    <button
                      type="button"
                      onClick={handleClearDraft}
                      className="text-indigo-500 hover:text-indigo-700 underline underline-offset-2"
                      aria-label={t('tailor.clearDraftAria')}
                    >
                      {t('tailor.clearDraft')}
                    </button>
                  </span>
                )}
                {draftStale && (
                  <span className="inline-flex items-center gap-1.5 text-[10px] font-medium text-amber-700 bg-amber-50 px-2 py-0.5 rounded-full" data-testid="tailor-stale-draft">
                    {t('tailor.staleDraft')}
                  </span>
                )}
              </div>
              <p className="text-xs text-gray-400 mb-2">
                {t('tailor.bulletsHint')}
              </p>
              {sourceReady && target && !writingTargetVersion(target) && !error && <p role="alert" className="mb-2 text-xs text-amber-800">{t('tailor.targetVersionUnavailable')}</p>}
              {inputRejected && <p role="alert" className="mb-2 text-xs text-amber-800">{t('tailor.invalidDraftText')}</p>}
              {limitIssue && <p role="alert" data-testid="tailor-limit-issue" className="mb-2 text-xs text-amber-800">{limitIssue}</p>}
              {record && needsReview && (
                <div className="mb-2 rounded-lg border border-amber-200 bg-amber-50 p-2 text-xs text-amber-900" data-testid="tailor-draft-review">
                  <p>{t(draftStale ? 'tailor.draftChanged' : 'tailor.draftUnknown')}</p>
                  <button type="button" onClick={requestReview} disabled={reviewing || loading || extracting || action.busy || !canRequest}
                    className="mt-2 font-semibold underline underline-offset-2 disabled:opacity-50">{t('tailor.reviewDraft')}</button>
                </div>
              )}
              {(!pipelineVersion || (pipelineVersion && !currentBinding)) && <p className="mb-2 text-xs text-gray-500">{t(rulesUnavailable ? 'tailor.rulesUnavailable' : 'tailor.rulesChecking')}</p>}
              {storageRead !== 'ready' && <p role="alert" className="mb-2 text-xs text-amber-800">{t(storageRead === 'invalid' ? 'tailor.draftUnreadable' : 'tailor.draftReadFailed')}</p>}
              {saveFailed && <p role="alert" className="mb-2 text-xs text-amber-800">{t('tailor.draftSaveFailed')}{' '}
                <button type="button" className="underline" onClick={() => { if (record) persistRecord(record); }}>{t('tailor.retrySave')}</button></p>}
              {profile.resume_text && (
                <ResumeProcessingNotice text={profile.resume_text} processing={extractionResult?.processing} warnings={extractionResult?.warnings} />
              )}
              {extractionError && <p role="alert" className="text-xs text-amber-700">{t('resume.extractionFailed')}</p>}
              {profile.resume_text && (
                <button
                  type="button"
                  onClick={requestExtraction}
                  disabled={extracting || loading || reviewing || action.busy || !canRequest}
                  className="inline-flex items-center gap-1.5 text-xs font-medium text-indigo-600 hover:text-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed mb-2"
                >
                  {extracting ? (
                    <>
                      <Loader2 className="w-3.5 h-3.5 animate-spin" aria-hidden="true" />
                      {t('tailor.extracting')}
                    </>
                  ) : (
                    <>
                      <Sparkles className="w-3.5 h-3.5" aria-hidden="true" />
                      {t('tailor.extractFromResume')}
                    </>
                  )}
                </button>
              )}
            </div>
            <div className="flex-1 px-5 pb-4 min-h-[220px]">
              <textarea
                id="tailor-bullets-input"
                value={draft}
                onChange={(e) => {
                  if (!record) return;
                  let next: TailorDraft;
                  try { next = editTailorDraft(record, e.target.value); }
                  catch { setInputRejected(true); return; }
                  markUserEdit(); setInputRejected(false); setRecord(next);
                  // Any user edit clears the "restored" indicator since
                  // the draft is no longer purely the restored copy.
                  if (draftRestored) setDraftRestored(false);
                  // C1-R2B: manual typing is the newest, most authoritative
                  // draft intent there is — a pending Extract that resolves
                  // AFTER this must never overwrite it. Bumping the
                  // attempt counter (not sessionEpoch, which is reserved
                  // for open/close/owner/opp transitions) invalidates any
                  // in-flight extract exactly like a newer extract call
                  // would, without touching Generate's own tracking.
                  // setExtracting(false) synchronously too — the
                  // invalidated extract's own guarded finally will now
                  // correctly skip its setExtracting(false), so nothing
                  // else would ever clear the spinner otherwise.
                  extractAttemptRef.current += 1;
                  setExtracting(false);
                }}
                placeholder={t('tailor.bulletsPlaceholder')}
                rows={12}
                className="w-full h-full min-h-[200px] px-3.5 py-2.5 border border-gray-200 rounded-xl text-sm text-gray-700 leading-relaxed focus:ring-2 focus:ring-indigo-500/30 focus:border-indigo-400 outline-none transition-all resize-none"
              />
            </div>
          </div>

          {/* Right panel — tailored output */}
          <div className="w-full lg:w-[480px] flex flex-col bg-gray-50/60 min-w-0 min-h-[240px] lg:min-h-0 shrink-0 border-t lg:border-t-0 border-gray-100">
            <div className="flex items-center justify-between gap-2 px-5 pt-4 pb-2 shrink-0">
              <label
                className="block text-xs font-semibold text-gray-500 uppercase tracking-wider"
              >
                {t('tailor.tailoredHeading')}
              </label>
              <div className="flex items-center gap-1.5">
                {reviewable && rejected.size > 0 && (
                  <span className="text-[10px] font-semibold px-2 py-0.5 rounded-full uppercase tracking-wider bg-gray-100 text-gray-500">
                    {t('tailor.keptCount', { kept: keptCount, total: resp!.tailored_bullets.length })}
                  </span>
                )}
                {resp && (
                  <span
                    className={`text-[10px] font-semibold px-2 py-0.5 rounded-full uppercase tracking-wider ${
                      isFallback
                        ? 'bg-amber-50 text-amber-700'
                        : 'bg-indigo-100 text-indigo-700'
                    }`}
                  >
                    {isFallback ? t('tailor.methodFallback') : t('tailor.methodAi')}
                  </span>
                )}
              </div>
            </div>

            <div className="flex-1 overflow-y-auto px-5 pb-4 space-y-3">
              {loading && (
                <div className="flex flex-col items-center justify-center py-16 gap-3">
                  <Loader2 className="w-7 h-7 text-indigo-500 animate-spin" />
                  <p className="text-sm text-gray-500">
                    {t('tailor.generating')}
                  </p>
                </div>
              )}

              {!loading && error && (
                <div className="flex flex-col items-center justify-center py-12 gap-3">
                  <AlertCircle className="w-7 h-7 text-red-500" />
                  <p className="text-sm text-red-600 text-center">{error}</p>
                  <button
                    type="button"
                    onClick={requestGeneration}
                    disabled={action.busy || !canRequest}
                    className="text-sm text-indigo-600 underline hover:text-indigo-700"
                  >
                    {t('tailor.tryAgain')}
                  </button>
                </div>
              )}

              {!loading && !error && !resp && (
                <div className="flex flex-col items-center justify-center py-16 gap-3 text-center">
                  <Sparkles className="w-7 h-7 text-indigo-300" />
                  <p className="text-sm text-gray-500 max-w-xs">
                    {t('tailor.noBulletsYet')}
                  </p>
                </div>
              )}

              {!loading && !error && resp && warningMessage && (
                <div className="flex items-start gap-2 px-3 py-2 rounded-lg bg-amber-50 border border-amber-200 text-[12.5px] text-amber-800">
                  <Info className="w-4 h-4 text-amber-500 shrink-0 mt-0.5" aria-hidden="true" />
                  <span>{warningMessage}</span>
                </div>
              )}

              {!loading && !error && resp && isFallback && (
                <p className="text-xs text-gray-500 px-1">
                  {t('tailor.fallbackHint')}
                </p>
              )}

              {/* Coverage: every bullet comes back, either with a reviewed
                  rewrite or as written with its reason. */}
              {!loading && !error && resp?.method === 'ai' && statused && (
                <p className="text-xs text-gray-600 px-1">
                  {t('tailor.coverage', { n: rewrittenCount, kept: resp.tailored_bullets.length - rewrittenCount })}
                </p>
              )}

              {/* R73: one-line nudge that this is a review surface — edit or
                  reject any bullet before copying. */}
              {!loading && !error && reviewable && (
                <p className="text-[11.5px] text-gray-400 px-1">
                  {keptCount === 0 ? t('tailor.allRejectedHint') : t('tailor.reviewHint')}
                </p>
              )}

              {!loading && !error && hasResults && (
                <ul className="space-y-3">
                  {resp.tailored_bullets.map((b: TailoredBullet, i: number) => {
                    // R71-E: pair each tailored bullet with its source.
                    // `source_index` is set by the backend and clamped to
                    // the submitted-bullets length, so this access is
                    // always safe; the `??` is a defensive belt-and-
                    // suspenders for stale snapshots.
                    const original = submittedBullets[b.source_index] ?? '';
                    // A kept bullet is shown as written, with the reason.
                    const isFallbackBullet = b.status === 'kept' || b.source_evidence === 'original';
                    const kept = b.status === 'kept' ? keptExplanation(b.reason_code, t) : null;
                    // R73: render the effective text — the user's inline edit
                    // wins over the model's rewrite.
                    const current = effectiveText(i, b);
                    const isEdited = edits[i] !== undefined;
                    const isRejected = rejected.has(i);
                    const isEditing = editingIdx === i;
                    const sameAsOriginal =
                      isFallbackBullet || original.trim() === current.trim();
                    // Review controls on every line of an AI result, never on a
                    // fallback echo of the user's own originals.
                    const canReview = reviewable && (b.status === 'kept' || !isFallbackBullet);

                    return (
                      <li
                        key={i}
                        className={`bg-white border rounded-xl shadow-sm overflow-hidden transition-opacity ${
                          isRejected ? 'opacity-50 border-dashed border-gray-300' : 'border-gray-200'
                        }`}
                      >
                        {/* Original (R71-E side-by-side). Hidden when the
                            backend echoed the original verbatim — showing
                            the same text twice adds noise without value. */}
                        {original && !sameAsOriginal && !isEditing && (
                          <div className="px-4 py-2.5 bg-gray-50/80 border-b border-gray-100">
                            <p className="text-[10px] font-semibold uppercase tracking-wider text-gray-400 mb-1">
                              {t('tailor.originalRowLabel')}
                            </p>
                            <p className="text-[12.5px] text-gray-500 leading-relaxed">
                              <DiffLine original={original} tailored={current} side="original" />
                            </p>
                          </div>
                        )}
                        <div className="px-4 py-3 relative">
                          <div className="flex items-center justify-between gap-2">
                            <div className="flex items-center gap-1.5 min-w-0">
                              {!sameAsOriginal && !isEditing && (
                                <p className="text-[10px] font-semibold uppercase tracking-wider text-indigo-500">
                                  {t('tailor.tailoredRowLabel')}
                                </p>
                              )}
                              {isEdited && !isEditing && (
                                <span className="text-[9px] font-semibold uppercase tracking-wide px-1 py-px rounded bg-amber-50 text-amber-600">
                                  {t('tailor.edited')}
                                </span>
                              )}
                            </div>
                            {/* R73 review controls: edit / reject (or restore),
                                plus the R71-F per-bullet copy. */}
                            {!isEditing && (
                              <div className="ml-auto flex items-center gap-0.5 shrink-0">
                                {canReview && !isRejected && (
                                  <>
                                    <button
                                      type="button"
                                      onClick={() => startEdit(i, current)}
                                      className="inline-flex items-center gap-1 text-[10.5px] font-medium px-1.5 py-0.5 rounded-md text-gray-400 hover:text-indigo-600 hover:bg-indigo-50 transition-colors"
                                      aria-label={t('tailor.editBulletAria')}
                                    >
                                      <Pencil className="w-3 h-3" aria-hidden="true" />
                                      {t('tailor.edit')}
                                    </button>
                                    <button
                                      type="button"
                                      onClick={() => toggleReject(i)}
                                      className="inline-flex items-center gap-1 text-[10.5px] font-medium px-1.5 py-0.5 rounded-md text-gray-400 hover:text-red-600 hover:bg-red-50 transition-colors"
                                      aria-label={t('tailor.rejectBulletAria')}
                                    >
                                      <Trash2 className="w-3 h-3" aria-hidden="true" />
                                      {t('tailor.reject')}
                                    </button>
                                  </>
                                )}
                                {canReview && isRejected && (
                                  <button
                                    type="button"
                                    onClick={() => toggleReject(i)}
                                    className="inline-flex items-center gap-1 text-[10.5px] font-medium px-1.5 py-0.5 rounded-md text-gray-500 hover:text-indigo-600 hover:bg-indigo-50 transition-colors"
                                    aria-label={t('tailor.restoreBulletAria')}
                                  >
                                    <RotateCcw className="w-3 h-3" aria-hidden="true" />
                                    {t('tailor.restore')}
                                  </button>
                                )}
                                {!isRejected && (
                                  <button
                                    type="button"
                                    onClick={() => handleCopyBullet(i, current)}
                                    className={`inline-flex items-center gap-1 text-[10.5px] font-medium px-1.5 py-0.5 rounded-md transition-colors ${
                                      copiedBulletIdx === i
                                        ? 'text-emerald-600 bg-emerald-50'
                                        : 'text-gray-400 hover:text-indigo-600 hover:bg-indigo-50'
                                    }`}
                                    aria-label={t('tailor.copyBulletAria')}
                                  >
                                    {copiedBulletIdx === i ? (
                                      <>
                                        <CheckCircle className="w-3 h-3" aria-hidden="true" />
                                        {t('tailor.copyBulletCopied')}
                                      </>
                                    ) : (
                                      <Copy className="w-3 h-3" aria-hidden="true" />
                                    )}
                                  </button>
                                )}
                              </div>
                            )}
                          </div>

                          {isEditing ? (
                            <div className="mt-1.5">
                              <textarea
                                value={editDraft}
                                onChange={(e) => { markUserEdit(); setEditDraft(e.target.value); }}
                                rows={3}
                                className="w-full px-3 py-2 border border-indigo-300 rounded-lg text-[13.5px] text-gray-800 leading-relaxed focus:ring-2 focus:ring-indigo-500/30 outline-none resize-y"
                                aria-label={t('tailor.editBulletAria')}
                              />
                              <div className="flex items-center gap-2 mt-1.5">
                                <button
                                  type="button"
                                  onClick={() => saveEdit(i)}
                                  className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md text-[11.5px] font-semibold text-white bg-indigo-600 hover:bg-indigo-700 transition-colors"
                                >
                                  <CheckCircle className="w-3 h-3" aria-hidden="true" />
                                  {t('tailor.save')}
                                </button>
                                <button
                                  type="button"
                                  onClick={cancelEdit}
                                  className="px-2.5 py-1 rounded-md text-[11.5px] font-medium text-gray-500 hover:bg-gray-100 transition-colors"
                                >
                                  {t('tailor.cancelEdit')}
                                </button>
                              </div>
                            </div>
                          ) : (
                            <p
                              className={`mt-1 text-[13.5px] leading-relaxed ${
                                isRejected ? 'line-through text-gray-400' : 'text-gray-800'
                              }`}
                            >
                              {sameAsOriginal || isEdited ? (
                                current
                              ) : (
                                <DiffLine original={original} tailored={current} side="tailored" />
                              )}
                            </p>
                          )}

                          {kept && !isEditing && (
                            <p className="mt-2 text-[11.5px]" data-testid="tailor-kept-reason">
                              <span className={`font-semibold uppercase tracking-wide text-[9.5px] px-1.5 py-px rounded ${kept.neutral ? 'bg-gray-100 text-gray-600' : 'bg-amber-50 text-amber-700'}`}>
                                {kept.label}
                              </span>{' '}
                              <span className="text-gray-500">{kept.reason}</span>
                            </p>
                          )}
                          {b.status === 'rewritten' && !isEditing && (
                            <>
                              <RewriteWhy links={b.links} t={t}
                                ops={plain.has(i) && b.alternative ? (b.ops ?? []).filter((op) => op !== 'relabel') : b.ops} />
                              {b.alternative && !isEdited && !isRejected && (
                                <button
                                  type="button"
                                  onClick={() => togglePlain(i)}
                                  className="mt-1.5 text-[11px] font-medium text-indigo-600 underline underline-offset-2 hover:text-indigo-700"
                                >
                                  {plain.has(i) ? t('tailor.useWithTerms') : t('tailor.useWithoutTerms')}
                                </button>
                              )}
                            </>
                          )}
                          {b.source_evidence && !isEditing && (b.status === undefined || b.source_evidence !== original) && !kept && (
                            <p className="mt-2 text-[11.5px] text-gray-500 italic">
                              <span className="font-medium not-italic uppercase tracking-wider text-[10px] text-gray-400">
                                {t('tailor.sourceLabel')}:
                              </span>{' '}
                              {isFallbackBullet
                                ? t('tailor.sourceOriginal')
                                : `"${b.source_evidence}"`}
                            </p>
                          )}
                        </div>
                      </li>
                    );
                  })}
                </ul>
              )}
            </div>
          </div>
        </div>

        {/* Footer */}
        <div className="flex flex-wrap items-center justify-end gap-3 px-4 sm:px-6 py-3 border-t border-gray-100 bg-gray-50/50 shrink-0">
          {resp?.method === 'ai' && hasResults && (
            <button
              type="button"
              onClick={handleUseAsOriginals}
              disabled={keptCount === 0}
              className="inline-flex items-center gap-2 px-4 py-2 text-sm font-medium text-indigo-700 bg-indigo-50 border border-indigo-100 rounded-xl hover:bg-indigo-100 disabled:opacity-50 disabled:cursor-not-allowed transition-colors mr-auto"
            >
              <RefreshCw className="w-4 h-4" aria-hidden="true" />
              {t('tailor.useAsOriginals')}
            </button>
          )}
          {resp && hasResults && (
            <button
              type="button"
              onClick={handleCopyAll}
              disabled={keptCount === 0}
              className="inline-flex items-center gap-2 px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-200 rounded-xl hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              {copied ? (
                <>
                  <CheckCircle className="w-4 h-4 text-emerald-500" />
                  {t('tailor.copied')}
                </>
              ) : (
                <>
                  <Copy className="w-4 h-4" />
                  {t('tailor.copyAll')}
                </>
              )}
            </button>
          )}
          <button
            type="button"
            onClick={requestGeneration}
            disabled={loading || extracting || reviewing || action.busy || draft.trim().length === 0 || limitIssue !== null || !canRequest}
            className="inline-flex items-center gap-2 px-5 py-2.5 text-sm font-semibold text-white bg-gradient-to-r from-indigo-600 to-fuchsia-500 rounded-xl hover:from-indigo-700 hover:to-fuchsia-600 disabled:opacity-50 disabled:cursor-not-allowed shadow-sm transition-all"
          >
            {resp ? (
              <>
                <RefreshCw className="w-4 h-4" />
                {t('tailor.regenerate')}
              </>
            ) : (
              <>
                <Sparkles className="w-4 h-4" />
                {t('tailor.generate')}
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
