'use client';

import { useState, useEffect, useLayoutEffect, useRef, useMemo, useCallback } from 'react';
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
import { tailorResume, getTailorStatus, extractResumeBullets } from '@/lib/api';
import { STORAGE_KEYS } from '@/lib/storage-keys';
import { hashString } from '@/lib/match-utils';
import type { ProfileData, TailorResponse, TailoredBullet } from '@/lib/types';
import { useT } from '@/i18n/client';
import { diffWords, isWhitespace } from '@/lib/word-diff';

// R71-F: persist the textarea draft per-opportunity so the user doesn't
// lose typed bullets if they close the modal accidentally.
//
// C1-R2B: keying by opportunity id ALONE is not enough to isolate drafts
// between different accounts on the same browser — a deferred write (e.g.
// smart-extract resolving after a U1->U2 switch) could repopulate the slot
// U2 reads from when opening the SAME opportunity. Every key is now
// owner-scoped too (ownerScopeKey:opportunityId). The prefix itself is
// unchanged (STORAGE_KEYS.TAILOR_DRAFT_PREFIX), so the existing
// USER_SCOPED_PREFIXES sweep in identity-owner.ts already covers every new
// key without any change there — it matches by startsWith(prefix), and the
// owner segment lives entirely AFTER the prefix.
const DRAFT_STORAGE_PREFIX = STORAGE_KEYS.TAILOR_DRAFT_PREFIX;

function draftStorageKey(ownerScopeKey: string, opportunityId: string): string {
  return `${DRAFT_STORAGE_PREFIX}${ownerScopeKey}:${opportunityId}`;
}

// A null ownerScopeKey means no confirmed, safe scope exists (identity
// unresolved, or the transient window between a sign-out and its
// replacement anon session) — persisting anything there would land under a
// bare, ownerless slot the NEXT identity to open this opportunity could
// read. Draft state stays purely in-memory (React state) for that window;
// these two functions simply no-op instead.
//
// W13: drafts carry a fingerprint of profile.resume_text at save time so a
// restored draft built against a since-edited résumé is flagged, not
// silently preferred. Legacy plain-string drafts have no sig — unknown, so
// no staleness claim is made for them.
interface StoredDraft {
  text: string;
  sig: string | null;
}

function loadSavedDraft(ownerScopeKey: string | null, opportunityId: string): StoredDraft | null {
  if (typeof window === 'undefined' || !ownerScopeKey) return null;
  try {
    const raw = window.localStorage.getItem(draftStorageKey(ownerScopeKey, opportunityId));
    if (raw === null) return null;
    try {
      const parsed = JSON.parse(raw) as { t?: unknown; s?: unknown };
      if (parsed && typeof parsed.t === 'string') {
        return { text: parsed.t, sig: typeof parsed.s === 'string' ? parsed.s : null };
      }
    } catch { /* legacy plain-string draft */ }
    return { text: raw, sig: null };
  } catch {
    // localStorage can throw in private-mode Safari and embedded webviews.
    // Swallow — persistence is a UX nicety, not a correctness requirement.
    return null;
  }
}

function saveDraft(
  ownerScopeKey: string | null,
  opportunityId: string,
  value: string,
  resumeSig: string | null,
): void {
  if (typeof window === 'undefined' || !ownerScopeKey) return;
  try {
    const key = draftStorageKey(ownerScopeKey, opportunityId);
    if (value.trim().length === 0) {
      window.localStorage.removeItem(key);
    } else {
      window.localStorage.setItem(key, JSON.stringify({ t: value, s: resumeSig }));
    }
  } catch {
    // Same rationale as loadSavedDraft — never crash the modal on quota
    // / private-mode failures.
  }
}

// C1-R2B: an earlier version of this file attempted a one-time forward
// migration of the pre-owner-scoping (opportunity-only) draft key into the
// new owner-scoped one, gated on the browser's LOCAL_IDENTITY_OWNER marker
// matching. That marker is NOT unforgeable proof of current ownership —
// identity-owner.ts's own doc comment calls out multi-tab races and
// delayed writes as accepted residual risk: a stale U1 browser tab can
// still write the OLD opp-only key AFTER the marker has already moved on
// to U2, and a "does the marker match" check has no way to tell that write
// apart from a genuinely-U2 one. Migrating on that basis would hand U1's
// content to U2. Privacy wins over convenience here: the legacy key is
// never read, never migrated, and never deleted by this component — it is
// simply ignored. (It remains subject to identity-owner.ts's own
// USER_SCOPED_PREFIXES sweep on a real owner switch, same as every
// owner-scoped key.)

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
}

// Heuristic to pre-fill bullets from a parsed resume's `raw_text`. We
// don't want to invoke an LLM here — just look for lines that look
// resume-bullet-shaped (start with •, -, *, –, —, +, or a digit).
// Keeps the bar low: any string with a leading bullet glyph counts.
const BULLET_PREFIX_RE = /^\s*([•\-*–—+]|\d+[.)])\s+(.+)$/;

function extractBulletLines(resumeText: string | undefined, limit = 12): string[] {
  if (!resumeText) return [];
  const out: string[] = [];
  for (const raw of resumeText.split(/\r?\n/)) {
    const m = raw.match(BULLET_PREFIX_RE);
    if (m) {
      const cleaned = m[2].trim();
      if (cleaned.length >= 10) out.push(cleaned);
    }
    if (out.length >= limit) break;
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
}: TailorModalProps) {
  // R71-D: `locale` flows from the i18n context all the way down to the
  // backend so the LLM returns bullets in the user's current display
  // language. The backend tolerates unknown / region-tagged values by
  // falling back to 'en', so we can pipe `useT().locale` through raw.
  const { t, locale } = useT();

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
  // different one, exactly like an owner or opportunity change. A content
  // fingerprint (not the object reference — a parent re-fetch resolving to
  // identical data must NOT count as a change) is what both the reset
  // effect and sessionEpochRef below key off, so any real profile change
  // invalidates in-flight work even when resume_text itself didn't move.
  const profileFingerprint = useMemo(() => canonicalFingerprint(profile), [profile]);

  // R71-F: initial draft = saved draft for THIS opportunity (if any)
  // over heuristic prefill over empty. Computed once per modal open;
  // see the open-effect below for the actual loading.
  const [draft, setDraft] = useState('');
  const [draftRestored, setDraftRestored] = useState(false);
  const [draftStale, setDraftStale] = useState(false);
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
  // R73: per-bullet review — `rejected` indices are excluded from copy /
  // use-as-originals; `edits` override a bullet's text in place; `editingIdx`
  // is the card currently in inline-edit mode. Reset on every new result so
  // a prior round's decisions don't bleed into the next tailor.
  const [rejected, setRejected] = useState<Set<number>>(new Set());
  const [edits, setEdits] = useState<Record<number, string>>({});
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
  const sessionEpochRef = useRef(0);
  useLayoutEffect(() => {
    const changed =
      isOpen !== isOpenRef.current ||
      opportunityId !== opportunityIdRef.current ||
      ownerScopeKey !== ownerScopeKeyRef.current ||
      ownerReady !== ownerReadyRef.current ||
      profileFingerprint !== profileFingerprintRef.current;
    isOpenRef.current = isOpen;
    opportunityIdRef.current = opportunityId;
    ownerScopeKeyRef.current = ownerScopeKey;
    ownerReadyRef.current = ownerReady;
    profileFingerprintRef.current = profileFingerprint;
    if (changed) sessionEpochRef.current += 1;
  });
  const generateAttemptRef = useRef(0);
  const extractAttemptRef = useRef(0);

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
    onClose();
  }, [onClose]);

  // Reset modal-local state every time the modal opens. Splitting this
  // into two effects would race a stale `resp` against the next open's
  // setDraft, so we batch it here.
  //
  // C1-R2B: keyed off `profileFingerprint`, not `heuristicPrefill` — the
  // latter only reacts to profile.resume_text specifically, but a
  // Generate/Extract in flight is invalidated (via sessionEpochRef above)
  // on ANY profile content change, so the visible reset (loading/extracting
  // clearing, resp/error clearing) needs to fire on the same trigger or
  // it'd desync from what stillCurrent() is actually guarding against.
  useEffect(() => {
    /* eslint-disable react-hooks/set-state-in-effect --
       Modal-lifecycle effect mirroring ColdEmailModal — reset every
       internal slice on open so the next render starts from a known
       state and clears any leftover AI result. */
    if (isOpen) {
      // R71-F: prefer saved-per-opportunity draft over heuristic
      // prefill so the user's last typed bullets survive across
      // close→reopen cycles. Empty heuristic + no saved draft → "".
      const saved = loadSavedDraft(ownerScopeKey, opportunityId);
      setDraft(saved?.text ?? heuristicPrefill);
      setDraftRestored(saved !== null && saved.text.length > 0);
      setDraftStale(
        !!saved?.sig && !!profile.resume_text &&
        saved.sig !== hashString(profile.resume_text),
      );
      setResp(null);
      setError(null);
      setCopied(false);
      setCopiedBulletIdx(null);
      setLoading(false);
      setExtracting(false);
      setSubmittedBullets([]);
      setRejected(new Set());
      setEdits({});
      setEditingIdx(null);
      setEditDraft('');
    }
    /* eslint-enable react-hooks/set-state-in-effect */
  // profile.resume_text feeds the draft-staleness comparison.
  }, [isOpen, profileFingerprint, heuristicPrefill, opportunityId, ownerReady, ownerScopeKey, profile.resume_text]);

  // Tracks the (ownerScopeKey, opportunityId) the persist effect below last
  // ACTUALLY wrote under. Guards against a real cross-owner leak: if
  // ownerScopeKey/opportunityId change on an ALREADY-OPEN modal (isOpen
  // never flips false — e.g. a caller that doesn't remount/close on
  // identity change, unlike MatchList's key-based one), the reset-on-open
  // effect above and this persist effect BOTH have those props in their
  // dependency arrays and so BOTH fire in the SAME commit; React runs them
  // in declaration order (reset first), but the reset effect's own
  // setDraft(...) does not retroactively update the `draft` CLOSURE this
  // persist effect already captured for the CURRENT render — that only
  // takes effect on the NEXT render. Without this guard, this effect would
  // still fire with the OLD owner's `draft` text and the NEW ownerScopeKey,
  // writing it under the NEW owner's key. Relying on isOpen alone is not
  // enough — it only helps on the (currently, but not necessarily always)
  // common case where a caller closes the modal in the exact same batch as
  // the identity reset.
  const lastPersistedContextRef = useRef<{ ownerScopeKey: string | null; opportunityId: string } | null>(null);

  // R71-F: persist draft to localStorage as the user types. localStorage
  // is synchronous and cheap enough that per-keystroke writes are fine —
  // no debouncing needed for typical resume-bullet inputs (<3KB). The
  // helper swallows quota/private-mode errors so persistence failures
  // never break the modal. No-ops (ephemeral, in-memory only) when
  // ownerScopeKey is null — see saveDraft's own doc comment.
  useEffect(() => {
    if (!isOpen) return;
    const prevCtx = lastPersistedContextRef.current;
    const contextChanged =
      !prevCtx || prevCtx.ownerScopeKey !== ownerScopeKey || prevCtx.opportunityId !== opportunityId;
    lastPersistedContextRef.current = { ownerScopeKey, opportunityId };
    // The render where a context change is FIRST observed is exactly the
    // one whose `draft` closure might still belong to the OLD context (see
    // the ref's doc comment above) — skip writing on it. The very next
    // render (once the reset effect's setDraft has actually propagated,
    // giving `draft` the new context's real value) has contextChanged ===
    // false and persists normally.
    if (contextChanged) return;
    saveDraft(ownerScopeKey, opportunityId, draft,
      profile.resume_text ? hashString(profile.resume_text) : null);
  }, [isOpen, ownerScopeKey, opportunityId, draft, profile.resume_text]);

  // R71-G: probe server AI availability each time the modal opens so the
  // banner reflects current config (a Render env-var change shouldn't need
  // a page reload to surface). setState runs in the async callback, not
  // synchronously in the effect body, so it's outside the
  // react-hooks/set-state-in-effect rule's scope.
  useEffect(() => {
    if (!isOpen) return;
    let ignore = false;
    getTailorStatus()
      .then((s) => {
        if (!ignore) setAiAvailable(s.ai_available);
      })
      .catch(() => {
        if (!ignore) setAiAvailable(null);
      });
    return () => {
      ignore = true;
    };
  }, [isOpen]);

  const handleClearDraft = useCallback(() => {
    setDraft('');
    setDraftRestored(false);
    saveDraft(ownerScopeKey, opportunityId, '', null);
    // See the textarea onChange handler below — a manual draft mutation of
    // any kind invalidates a still-pending Extract. setExtracting(false)
    // right here, synchronously, rather than only bumping the attempt
    // counter: the invalidated extract's own guarded `finally` will now
    // correctly see itself as superseded and skip its setExtracting(false)
    // call, so without this the spinner/disabled state would otherwise be
    // stuck true forever with nothing left to clear it.
    extractAttemptRef.current += 1;
    setExtracting(false);
  }, [ownerScopeKey, opportunityId]);

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
    if (!profile.resume_text || extracting || !ownerReady) return;
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
      extractAttemptRef.current === attempt;

    setExtracting(true);
    try {
      const data = await extractResumeBullets(profile.resume_text);
      if (!stillCurrent()) return; // closed/unmounted/switched/superseded — drop silently, no write
      if (data.bullets.length > 0) {
        const next = data.bullets.join('\n');
        setDraft(next);
        saveDraft(ctx.ownerScopeKey, ctx.opportunityId, next,
          profile.resume_text ? hashString(profile.resume_text) : null);
        setDraftRestored(false);
      }
    } catch {
      // Extraction is a convenience; on failure the user still has the
      // heuristic prefill / their own typing. Don't surface an error.
    } finally {
      // An old, superseded attempt's finally must never clear a NEWER
      // attempt's `extracting` spinner.
      if (stillCurrent()) setExtracting(false);
    }
  }

  async function handleGenerate() {
    if (!ownerReady) return;
    const bullets = parseBullets(draft);
    if (bullets.length === 0) {
      setError(t('tailor.fillBulletsFirst'));
      return;
    }
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
      generateAttemptRef.current === attempt;

    setLoading(true);
    setError(null);
    setCopied(false);
    // R73: a fresh tailor clears the previous round's review decisions.
    setRejected(new Set());
    setEdits({});
    setEditingIdx(null);
    // R71-E: snapshot before the await so a textarea edit during the
    // request can't desync the rendered pairing.
    setSubmittedBullets(bullets);
    try {
      const data = await tailorResume(profile, ctx.opportunityId, bullets, { locale });
      if (!stillCurrent()) return; // superseded — N1's result must never appear as N2's
      // W13: a response the backend stamped for a DIFFERENT target than the
      // one this call was made for is dropped outright.
      if (data.opportunity_id && data.opportunity_id !== ctx.opportunityId) return;
      setResp(data);
    } catch (err) {
      if (!stillCurrent()) return;
      setError(err instanceof Error ? err.message : t('tailor.failedToTailor'));
    } finally {
      // Old finally blocks must not clear a NEWER request's loading state.
      if (stillCurrent()) setLoading(false);
    }
  }

  // R73: a bullet's effective text = the user's inline edit if present,
  // else the model's rewrite. The kept set excludes rejected indices.
  const effectiveText = useCallback(
    (i: number, fallback: string) => edits[i] ?? fallback,
    [edits],
  );

  const keptTexts = useCallback((): string[] => {
    if (!resp) return [];
    return resp.tailored_bullets
      .map((b, i) => ({ i, text: effectiveText(i, b.text) }))
      .filter(({ i }) => !rejected.has(i))
      .map(({ text }) => text);
  }, [resp, rejected, effectiveText]);

  function toggleReject(i: number) {
    setRejected((prev) => {
      const next = new Set(prev);
      if (next.has(i)) next.delete(i);
      else next.add(i);
      return next;
    });
    if (editingIdx === i) setEditingIdx(null);
  }

  function startEdit(i: number, current: string) {
    setEditingIdx(i);
    setEditDraft(current);
  }

  function saveEdit(i: number) {
    const trimmed = editDraft.trim();
    setEdits((prev) => ({
      ...prev,
      [i]: trimmed || (resp?.tailored_bullets[i]?.text ?? ''),
    }));
    setEditingIdx(null);
    setEditDraft('');
  }

  function cancelEdit() {
    setEditingIdx(null);
    setEditDraft('');
  }

  // R71-G: promote the (kept + edited) AI rewrite back into the draft so the
  // user can iterate without retyping. Clearing the result resets the right
  // panel to the empty prompt and flips the CTA back to "Tailor with AI".
  function handleUseAsOriginals() {
    const kept = keptTexts();
    if (kept.length === 0) return;
    const next = kept.join('\n');
    setDraft(next);
    saveDraft(ownerScopeKey, opportunityId, next,
      profile.resume_text ? hashString(profile.resume_text) : null);
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
    setEditingIdx(null);
    setError(null);
    setCopied(false);
  }

  async function handleCopyAll() {
    const kept = keptTexts();
    if (kept.length === 0) return;
    const text = kept.map((b) => `• ${b}`).join('\n');
    await navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  // R71-F: per-bullet copy. Idx-keyed confirmation state so two
  // adjacent cards' "Copied" flashes can't collide when the user
  // clicks them in rapid succession.
  async function handleCopyBullet(idx: number, text: string) {
    try {
      await navigator.clipboard.writeText(text);
      setCopiedBulletIdx(idx);
      setTimeout(() => setCopiedBulletIdx((cur) => (cur === idx ? null : cur)), 1800);
    } catch {
      // navigator.clipboard.writeText can reject in insecure contexts
      // (HTTP, sandboxed iframes). Swallow — the global Copy All button
      // is the documented path, this is just a shortcut.
    }
  }

  if (!isOpen) return null;

  const warningMessage = resp ? pickWarningMessage(resp.warnings, t) : null;
  const isFallback = resp?.method === 'fallback';
  const hasResults = resp !== null && resp.tailored_bullets.length > 0;
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

        {/* R71-G: up-front AI-unavailable banner. Only on explicit false
            (not on a failed/loading probe) so we never falsely warn. */}
        {aiAvailable === false && (
          <div className="flex items-start gap-2 px-4 sm:px-6 py-2.5 bg-amber-50 border-b border-amber-200 text-[12.5px] text-amber-800 shrink-0">
            <AlertCircle className="w-4 h-4 text-amber-500 shrink-0 mt-0.5" aria-hidden="true" />
            <span>{t('tailor.aiUnavailableBanner')}</span>
          </div>
        )}

        {/* Body — two panel layout */}
        <div className="flex-1 flex flex-col lg:flex-row min-h-0">
          {/* Left panel — originals */}
          <div className="flex-1 flex flex-col lg:border-r border-gray-100 min-w-0">
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
              {profile.resume_text && (
                <button
                  type="button"
                  onClick={handleExtractFromResume}
                  disabled={extracting || !ownerReady}
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
            <div className="flex-1 px-5 pb-4 min-h-0">
              <textarea
                id="tailor-bullets-input"
                value={draft}
                onChange={(e) => {
                  setDraft(e.target.value);
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
                  if (draftStale) setDraftStale(false);
                }}
                placeholder={t('tailor.bulletsPlaceholder')}
                rows={12}
                className="w-full h-full min-h-[200px] px-3.5 py-2.5 border border-gray-200 rounded-xl text-sm text-gray-700 leading-relaxed focus:ring-2 focus:ring-indigo-500/30 focus:border-indigo-400 outline-none transition-all resize-none"
              />
            </div>
          </div>

          {/* Right panel — tailored output */}
          <div className="w-full lg:w-[480px] flex flex-col bg-gray-50/60 min-w-0 border-t lg:border-t-0 border-gray-100">
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
                    onClick={handleGenerate}
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

              {/* R71-G: partial-result coverage. When the anti-fabrication
                  validator drops some (not all) bullets, method stays "ai"
                  but fewer cards render — this line makes the gap explicit
                  instead of leaving the user wondering where a bullet went. */}
              {!loading && !error && resp?.method === 'ai' && hasResults &&
                resp.tailored_bullets.length < submittedBullets.length && (
                  <p className="text-xs text-amber-700 px-1">
                    {t('tailor.coverage', {
                      n: resp.tailored_bullets.length,
                      total: submittedBullets.length,
                    })}
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
                    const isFallbackBullet = b.source_evidence === 'original';
                    // R73: render the effective text — the user's inline edit
                    // wins over the model's rewrite.
                    const current = effectiveText(i, b.text);
                    const isEdited = edits[i] !== undefined;
                    const isRejected = rejected.has(i);
                    const isEditing = editingIdx === i;
                    const sameAsOriginal =
                      isFallbackBullet || original.trim() === current.trim();
                    // Review controls only on a real AI rewrite, never on a
                    // fallback echo of the user's own originals.
                    const canReview = reviewable && !isFallbackBullet;

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
                                onChange={(e) => setEditDraft(e.target.value)}
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

                          {b.source_evidence && !isEditing && (
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
        <div className="flex items-center justify-end gap-3 px-6 py-3 border-t border-gray-100 bg-gray-50/50 shrink-0">
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
            onClick={handleGenerate}
            disabled={loading || draft.trim().length === 0 || !ownerReady}
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
