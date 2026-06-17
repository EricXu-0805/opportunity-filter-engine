'use client';

import { useState, useEffect, useRef, useMemo, useCallback } from 'react';
import {
  X,
  Copy,
  Loader2,
  AlertCircle,
  Sparkles,
  CheckCircle,
  RefreshCw,
  Info,
} from 'lucide-react';
import { tailorResume, getTailorStatus, extractResumeBullets } from '@/lib/api';
import { STORAGE_KEYS } from '@/lib/storage-keys';
import type { ProfileData, TailorResponse, TailoredBullet } from '@/lib/types';
import { useT } from '@/i18n/client';
import { diffWords, isWhitespace } from '@/lib/word-diff';

// R71-F: persist the textarea draft per-opportunity so the user doesn't
// lose typed bullets if they close the modal accidentally. Keying by
// opportunity id keeps drafts isolated — opening the modal on opp A then
// opp B shows two distinct prefills, not the same leaked text.
const DRAFT_STORAGE_PREFIX = STORAGE_KEYS.TAILOR_DRAFT_PREFIX;

function draftStorageKey(opportunityId: string): string {
  return `${DRAFT_STORAGE_PREFIX}${opportunityId}`;
}

function loadSavedDraft(opportunityId: string): string | null {
  if (typeof window === 'undefined') return null;
  try {
    return window.localStorage.getItem(draftStorageKey(opportunityId));
  } catch {
    // localStorage can throw in private-mode Safari and embedded webviews.
    // Swallow — persistence is a UX nicety, not a correctness requirement.
    return null;
  }
}

function saveDraft(opportunityId: string, value: string): void {
  if (typeof window === 'undefined') return;
  try {
    if (value.trim().length === 0) {
      window.localStorage.removeItem(draftStorageKey(opportunityId));
    } else {
      window.localStorage.setItem(draftStorageKey(opportunityId), value);
    }
  } catch {
    // Same rationale as loadSavedDraft — never crash the modal on quota
    // / private-mode failures.
  }
}

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

  // R71-F: initial draft = saved draft for THIS opportunity (if any)
  // over heuristic prefill over empty. Computed once per modal open;
  // see the open-effect below for the actual loading.
  const [draft, setDraft] = useState('');
  const [draftRestored, setDraftRestored] = useState(false);
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

  const modalRef = useRef<HTMLDivElement>(null);
  const previouslyFocusedRef = useRef<HTMLElement | null>(null);

  // Reset modal-local state every time the modal opens. Splitting this
  // into two effects would race a stale `resp` against the next open's
  // setDraft, so we batch it here.
  useEffect(() => {
    /* eslint-disable react-hooks/set-state-in-effect --
       Modal-lifecycle effect mirroring ColdEmailModal — reset every
       internal slice on open so the next render starts from a known
       state and clears any leftover AI result. */
    if (isOpen) {
      // R71-F: prefer saved-per-opportunity draft over heuristic
      // prefill so the user's last typed bullets survive across
      // close→reopen cycles. Empty heuristic + no saved draft → "".
      const saved = loadSavedDraft(opportunityId);
      setDraft(saved ?? heuristicPrefill);
      setDraftRestored(saved !== null && saved.length > 0);
      setResp(null);
      setError(null);
      setCopied(false);
      setCopiedBulletIdx(null);
      setLoading(false);
      setSubmittedBullets([]);
    }
    /* eslint-enable react-hooks/set-state-in-effect */
  }, [isOpen, heuristicPrefill, opportunityId]);

  // R71-F: persist draft to localStorage as the user types. localStorage
  // is synchronous and cheap enough that per-keystroke writes are fine —
  // no debouncing needed for typical resume-bullet inputs (<3KB). The
  // helper swallows quota/private-mode errors so persistence failures
  // never break the modal.
  useEffect(() => {
    if (!isOpen) return;
    saveDraft(opportunityId, draft);
  }, [isOpen, opportunityId, draft]);

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
    saveDraft(opportunityId, '');
  }, [opportunityId]);

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
        onClose();
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
  }, [isOpen, onClose]);

  // R71-G: LLM-extract bullets from the saved resume text and load them
  // into the draft. Backend degrades to the glyph heuristic on any LLM
  // issue, so this always returns *some* bullets when the resume has them.
  // No-op silently if extraction yields nothing (keeps whatever's typed).
  async function handleExtractFromResume() {
    if (!profile.resume_text || extracting) return;
    setExtracting(true);
    try {
      const data = await extractResumeBullets(profile.resume_text);
      if (data.bullets.length > 0) {
        const next = data.bullets.join('\n');
        setDraft(next);
        saveDraft(opportunityId, next);
        setDraftRestored(false);
      }
    } catch {
      // Extraction is a convenience; on failure the user still has the
      // heuristic prefill / their own typing. Don't surface an error.
    } finally {
      setExtracting(false);
    }
  }

  async function handleGenerate() {
    const bullets = parseBullets(draft);
    if (bullets.length === 0) {
      setError(t('tailor.fillBulletsFirst'));
      return;
    }
    setLoading(true);
    setError(null);
    setCopied(false);
    // R71-E: snapshot before the await so a textarea edit during the
    // request can't desync the rendered pairing.
    setSubmittedBullets(bullets);
    try {
      const data = await tailorResume(profile, opportunityId, bullets, { locale });
      setResp(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : t('tailor.failedToTailor'));
    } finally {
      setLoading(false);
    }
  }

  // R71-G: promote the AI rewrite back into the draft so the user can
  // iterate (tweak a bullet, re-tailor) without retyping. Clearing the
  // result resets the right panel to the empty prompt and flips the CTA
  // back to "Tailor with AI" — the originals are now the rewritten text.
  function handleUseAsOriginals() {
    if (!resp || resp.tailored_bullets.length === 0) return;
    const next = resp.tailored_bullets.map((b) => b.text).join('\n');
    setDraft(next);
    saveDraft(opportunityId, next);
    setDraftRestored(false);
    setResp(null);
    setSubmittedBullets([]);
    setError(null);
    setCopied(false);
  }

  async function handleCopyAll() {
    if (!resp || resp.tailored_bullets.length === 0) return;
    const text = resp.tailored_bullets.map((b) => `• ${b.text}`).join('\n');
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

  return (
    <div
      className="fixed inset-0 z-50 flex sm:items-center sm:justify-center"
      role="dialog"
      aria-modal="true"
      aria-labelledby="tailor-modal-title"
    >
      <div
        className="absolute inset-0 bg-gray-900/60 backdrop-blur-sm"
        onClick={onClose}
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
            onClick={onClose}
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
              </div>
              <p className="text-xs text-gray-400 mb-2">
                {t('tailor.bulletsHint')}
              </p>
              {profile.resume_text && (
                <button
                  type="button"
                  onClick={handleExtractFromResume}
                  disabled={extracting}
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
                    const sameAsOriginal =
                      isFallbackBullet || original.trim() === b.text.trim();

                    return (
                      <li
                        key={i}
                        className="bg-white border border-gray-200 rounded-xl shadow-sm overflow-hidden"
                      >
                        {/* Original (R71-E side-by-side). Hidden when the
                            backend echoed the original verbatim — showing
                            the same text twice adds noise without value. */}
                        {original && !sameAsOriginal && (
                          <div className="px-4 py-2.5 bg-gray-50/80 border-b border-gray-100">
                            <p className="text-[10px] font-semibold uppercase tracking-wider text-gray-400 mb-1">
                              {t('tailor.originalRowLabel')}
                            </p>
                            <p className="text-[12.5px] text-gray-500 leading-relaxed">
                              <DiffLine original={original} tailored={b.text} side="original" />
                            </p>
                          </div>
                        )}
                        <div className="px-4 py-3 relative">
                          <div className="flex items-start justify-between gap-2">
                            {!sameAsOriginal && (
                              <p className="text-[10px] font-semibold uppercase tracking-wider text-indigo-500">
                                {t('tailor.tailoredRowLabel')}
                              </p>
                            )}
                            {/* R71-F per-bullet copy. Sits in the top-
                                right of each card so the user can grab
                                just the bullet they like without taking
                                everything via Copy All. */}
                            <button
                              type="button"
                              onClick={() => handleCopyBullet(i, b.text)}
                              className={`ml-auto inline-flex items-center gap-1 text-[10.5px] font-medium px-1.5 py-0.5 rounded-md transition-colors ${
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
                          </div>
                          <p className="mt-1 text-[13.5px] text-gray-800 leading-relaxed">
                            {sameAsOriginal ? (
                              b.text
                            ) : (
                              <DiffLine original={original} tailored={b.text} side="tailored" />
                            )}
                          </p>
                          {b.source_evidence && (
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
              className="inline-flex items-center gap-2 px-4 py-2 text-sm font-medium text-indigo-700 bg-indigo-50 border border-indigo-100 rounded-xl hover:bg-indigo-100 transition-colors mr-auto"
            >
              <RefreshCw className="w-4 h-4" aria-hidden="true" />
              {t('tailor.useAsOriginals')}
            </button>
          )}
          {resp && hasResults && (
            <button
              type="button"
              onClick={handleCopyAll}
              className="inline-flex items-center gap-2 px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-200 rounded-xl hover:bg-gray-50 transition-colors"
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
            disabled={loading || draft.trim().length === 0}
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
