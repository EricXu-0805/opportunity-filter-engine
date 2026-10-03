'use client';

import { profileInputMessage } from '@/lib/profile-input';

import { useState, useEffect, useLayoutEffect, useRef, useCallback, useMemo } from 'react';
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
  RotateCcw,
  Wand2,
  ArrowUpRight,
  ArrowDownRight,
  FileText,
} from 'lucide-react';
import type { ProfileRefreshState } from '@/lib/use-profile-refresh';
import type { WritingTargetState } from '@/lib/use-writing-target';
import { useProfileAction } from '@/lib/use-profile-action';
import { isPublicDetail } from '@/lib/public-target-shape';
import { writingTargetVersion } from '@/lib/writing-target-version';
import ProfileRefreshBanner, { profileRefreshReady } from './ProfileRefreshBanner';
import { structureResume, renovateResume, optimizeBullet } from '@/lib/api';
import ResumeProcessingNotice from './ResumeProcessingNotice';
import RewriteWhy, { keptExplanation } from './RewriteWhy';
import { isReviewedRules, isReviewedVariant, reviewedRenovation, reviewedSections } from '@/lib/renovation-review';
import { saveRenovation, loadRenovation, type RenovationPayload, type StoredRenovation } from '@/lib/supabase';
import { RenovationSaveQueue, type RenovationQueueState } from '@/lib/renovation-save-queue';
import RenovationHistory from './RenovationHistory';
import type {
  Opportunity,
  ProfileData,
  ResumeSectionInput,
  StructureResumeResponse,
  RenovationDoc,
  RenovatedBullet,
  RenovatedSection,
} from '@/lib/types';
import { useT } from '@/i18n/client';
import { diffWords, isWhitespace } from '@/lib/word-diff';
import { hashString } from '@/lib/match-utils';
import {
  captureOwnerToken,
  isTokenOwnerStillCurrent,
  isOwnerTokenValid,
  onLocalOwnerStateChange,
  type OwnerToken,
} from '@/lib/identity-owner';

interface RenovationScope {
  active: boolean;
  owner: OwnerToken;
  saveRevision: number;
  workRevision: number;
  profileFingerprint: string;
  queue?: RenovationSaveQueue;
  material: Omit<RenovationPayload, 'doc'>;
}


/**
 * Legacy bullet editing toward ONE opportunity (per-professor by
 * construction — the opportunity record carries pi/org/keywords).
 *
 * Flow: structure (résumé text → sections+bullets, verbatim) → renovate
 * (macro plan: reorder + foreground/keep/demote + grounded rewrites) →
 * per-bullet review on the variant chain:
 *   - Rollback  = move `current` back one step (-1 == the student's own
 *     base_text). Pure pointer move, no LLM → can never fabricate.
 *   - Edit      = append a `user` variant.
 *   - Re-optimize = POST /tailor/bullet; appends a validated `ai` variant
 *     only when the backend accepted it (changed=true).
 * The doc persists per (device, opportunity) via supabase; reopening the
 * modal restores the saved doc instead of re-billing the pipeline.
 */
interface ResumeRenovationModalProps {
  isOpen: boolean;
  targetReady?: boolean;
  targetChecking?: boolean;
  /** Current public target payload (detail or match-card projection). */
  targetKey?: string;
  /** False keeps the open draft; the retained profile is not current material. */
  profileAvailable?: boolean;
  profileRefresh?: ProfileRefreshState;
  target?: Opportunity | null;
  targetRefresh?: WritingTargetState;
  targetMembershipReady?: boolean;
  onClose: () => void;
  onCloseRequestChange?: (request: (() => boolean) | null) => void;
  profile: ProfileData;
  opportunityId: string;
  opportunityTitle: string;
  onOpenFull?: () => void;
}

// Compare complete JSON-safe content synchronously; key insertion order is not
// a profile change. Only a SHA-256 digest, never this content, is stored in docs.
function canonicalProfile(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map((item) => canonicalProfile(item)).join(',')}]`;
  if (value !== null && typeof value === 'object') {
    const record = value as Record<string, unknown>;
    return `{${Object.keys(record).filter((key) => record[key] !== undefined).sort()
      .map((key) => `${JSON.stringify(key)}:${canonicalProfile(record[key])}`).join(',')}}`;
  }
  return JSON.stringify(value) ?? 'null';
}

// The workspace supplies the current public target payload (detail or
// match-card projection), not the full server record. ID/title alone cannot
// establish saved provenance; malformed/mismatched input stays unknown.
function targetFingerprintFor(key: string | undefined, opportunityId: string): string | null {
  if (!key) return null;
  try {
    const value: unknown = JSON.parse(key);
    const record = (item: unknown): item is Record<string, unknown> => !!item && typeof item === 'object' && !Array.isArray(item);
    const strings = (item: unknown): item is string[] => Array.isArray(item) && item.every((entry) => typeof entry === 'string');
    const nullableBoolean = (item: unknown) => item === null || typeof item === 'boolean';
    if (!record(value) || value.id !== opportunityId ||
        !['title', 'organization', 'opportunity_type', 'paid', 'location', 'description_clean'].every((field) => typeof value[field] === 'string') ||
        !strings(value.keywords) || !nullableBoolean(value.on_campus)) return null;
    const { eligibility, application, metadata } = value;
    if (!record(eligibility) || typeof eligibility.international_friendly !== 'string' ||
        !strings(eligibility.skills_required) ||
        ('preferred_year' in eligibility && !strings(eligibility.preferred_year)) ||
        ('majors' in eligibility && !strings(eligibility.majors)) ||
        ('citizenship_required' in eligibility && !nullableBoolean(eligibility.citizenship_required)) ||
        !record(application) || typeof application.requires_resume !== 'string' || typeof application.contact_method !== 'string' ||
        ('application_effort' in application && typeof application.application_effort !== 'string')) return null;
    // Public projection strips internal is_active; match cards also omit all
    // metadata and detail-only eligibility/application fields. Missing is not
    // malformed. If supplied, known fields must still have their declared type.
    if ('metadata' in value && (!record(metadata) ||
        ('is_active' in metadata && typeof metadata.is_active !== 'boolean') ||
        ('confidence_score' in metadata && (typeof metadata.confidence_score !== 'number' || !Number.isFinite(metadata.confidence_score))))) return null;
    // Validate the required public shape without projecting: optional/new
    // fields also participate in the digest. Actionability is a separate gate.
    return canonicalProfile(value);
  } catch {
    return null;
  }
}

async function profileSignature(fingerprint: string): Promise<string | undefined> {
  try {
    const digest = await globalThis.crypto.subtle.digest('SHA-256', new TextEncoder().encode(fingerprint));
    return `v1:sha256:${Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, '0')).join('')}`;
  } catch {
    // Unavailable crypto means unknown provenance, never a weak-hash match.
    return undefined;
  }
}

type Replier = (path: string, vars?: Record<string, string | number>) => string;

// The server rewrites a bullet of up to 500 characters (Python len: code
// points) in renovation and re-optimize alike, and refuses rather than cuts.
const REWRITE_MAX_BULLET_CHARACTERS = 500;
const characterCount = (text: string) => [...text].length;

/** The limit a BULLET_TOO_LONG_TO_OPTIMIZE refusal names, else null. */
function refusedOptimizeLimit(err: unknown): number | null {
  if (!err || typeof err !== 'object' || !('code' in err) || err.code !== 'BULLET_TOO_LONG_TO_OPTIMIZE') return null;
  const detail = 'detail' in err ? err.detail as Record<string, unknown> | null : null;
  const max = detail?.max_characters_per_bullet;
  return Number.isSafeInteger(max) ? Number(max) : REWRITE_MAX_BULLET_CHARACTERS;
}

// A fabrication catch leads; a bullet left as written because it was too long
// is named alongside it, since the two can happen in the same pass.
function pickRenovationWarnings(warnings: string[], t: Replier): string[] {
  const tooLong = warnings.some((w) => /^bullet_.+_too_long_to_rewrite$/.test(w))
    ? [t('renovate.warnings.tooLongToRewrite', { max: REWRITE_MAX_BULLET_CHARACTERS })] : [];
  if (warnings.some((w) => w.includes('rejected_fabrication'))) {
    return [t('renovate.warnings.fabricationCaught'), ...tooLong];
  }
  if (warnings.includes('llm_not_configured')) {
    return [t('renovate.warnings.llmUnavailable')];
  }
  if (warnings.some((w) => w.startsWith('plan_') || w === 'macro_plan_failed')) {
    return [t('renovate.warnings.planFailed')];
  }
  return tooLong;
}

/** The text a bullet currently shows: its selected variant, or the base. */
function bulletCurrentText(b: RenovatedBullet): string {
  if (b.current >= 0 && b.current < b.variants.length) {
    return b.variants[b.current].text;
  }
  return b.base_text;
}

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
            <ins key={idx} className="no-underline bg-emerald-100 text-emerald-800 rounded px-0.5">
              {s.value}
            </ins>
          );
        })}
    </>
  );
}

const SOURCE_CHIP_STYLES: Record<string, string> = {
  base: 'bg-gray-100 text-gray-500',
  macro: 'bg-indigo-50 text-indigo-600',
  ai: 'bg-fuchsia-50 text-fuchsia-600',
  user: 'bg-amber-50 text-amber-700',
};

const ACTION_CHIP: Record<string, { className: string; icon: 'up' | 'down' | null }> = {
  foreground: { className: 'bg-emerald-50 text-emerald-700', icon: 'up' },
  demote: { className: 'bg-gray-100 text-gray-500', icon: 'down' },
  keep: { className: '', icon: null },
};

export default function ResumeRenovationModal({
  isOpen,
  onClose,
  onCloseRequestChange,
  profile,
  opportunityId,
  opportunityTitle,
  onOpenFull,
  targetReady = true,
  targetChecking = false,
  targetKey,
  profileAvailable = true,
  profileRefresh,
  target,
  targetRefresh,
  targetMembershipReady,
}: ResumeRenovationModalProps) {
  const { t, locale } = useT();
  const targetFingerprint = useMemo(() => targetFingerprintFor(targetKey, opportunityId), [targetKey, opportunityId]);
  // Only a verified detail receipt can authorize model work. The legacy
  // provenance key must describe that same target, never a seed/list card.
  const expectedTargetVersion = isPublicDetail(target, opportunityId) && canonicalProfile(target) === targetFingerprint
    ? writingTargetVersion(target) : null;
  const [targetVersionIssue, setTargetVersionIssue] = useState<'changed' | 'unavailable' | null>(null);
  const [targetVersionChecking, setTargetVersionChecking] = useState(false);
  const sourceReady = profileAvailable && targetReady && !targetChecking && !!expectedTargetVersion
    && !targetVersionIssue && !targetVersionChecking && profileRefreshReady(profileRefresh) && (!targetRefresh || targetRefresh.status === 'ready');
  const targetBinding = canonicalProfile([targetFingerprint ?? targetKey ?? { opportunityId, opportunityTitle }, expectedTargetVersion]);
  const targetBindingRef = useRef(targetBinding);
  const sourceRef = useRef({ ready: sourceReady, epoch: 0 });
  const profileFingerprint = canonicalProfile(profile);
  const profileRevisionRef = useRef(0);
  const profileSnapshot = useMemo<ProfileData>(() => JSON.parse(profileFingerprint), [profileFingerprint]);
  const [currentSignature, setCurrentSignature] = useState<{ fingerprint: string; signature?: string } | null>(null);
  useEffect(() => {
    let active = true;
    void profileSignature(profileFingerprint).then((signature) => {
      if (active) setCurrentSignature({ fingerprint: profileFingerprint, signature });
    });
    return () => { active = false; };
  }, [profileFingerprint]);

  // Phase machine: 'idle' (no doc yet, offer to renovate) → 'working'
  // (structure+renovate in flight) → 'doc' (variant-chain review surface).
  // 'restoring' covers the initial saved-doc lookup so the CTA doesn't
  // flash before we know whether a doc exists.
  const [ownerRevision, setOwnerRevision] = useState(0);
  const [restoreRevision, setRestoreRevision] = useState(0);
  const [currentTargetSignature, setCurrentTargetSignature] = useState<{ fingerprint: string; signature?: string } | null>(null);
  useEffect(() => {
    if (!isOpen || targetFingerprint === null) return;
    let active = true;
    const owner = captureOwnerToken();
    void profileSignature(targetFingerprint).then((signature) => {
      if (active && isOwnerTokenValid(owner, owner.uid)) setCurrentTargetSignature({ fingerprint: targetFingerprint, signature });
    });
    return () => { active = false; };
  }, [isOpen, ownerRevision, targetFingerprint]);
  const targetSignaturePending = targetFingerprint !== null && currentTargetSignature?.fingerprint !== targetFingerprint;
  const comparableTargetSignature = currentTargetSignature?.fingerprint === targetFingerprint ? currentTargetSignature.signature : undefined;
  const targetBindingUnavailable = targetFingerprint === null || (!targetSignaturePending && !comparableTargetSignature);
  const [profileChanged, setProfileChanged] = useState(false);
  const [targetChanged, setTargetChanged] = useState(false);
  const [phase, setPhase] = useState<'restoring' | 'restore-error' | 'idle' | 'working' | 'doc'>('restoring');
  const [workingStep, setWorkingStep] = useState<'structuring' | 'renovating'>('structuring');
  const [doc, setDoc] = useState<RenovationDoc | null>(null);
  const [baseSections, setBaseSections] = useState<ResumeSectionInput[]>([]);
  const [structureResult, setStructureResult] = useState<StructureResumeResponse | null>(null);
  const [restoredFromSave, setRestoredFromSave] = useState(false);
  const staleResume = !!doc && typeof doc.resume_sig === 'string' &&
    doc.resume_sig !== hashString(profile.resume_text ?? '');
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [saving, setSaving] = useState(false);
  const [savedFlash, setSavedFlash] = useState(false);
  const [saveFailed, setSaveFailed] = useState(false);
  const [saveState, setSaveState] = useState<RenovationQueueState>({ status: 'idle' });
  const [historyOwner, setHistoryOwner] = useState<OwnerToken | null>(null);
  // Per-bullet UI state, keyed by bullet id (ids are unique doc-wide — the
  // backend 422s duplicate ids).
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editDraft, setEditDraft] = useState('');
  const [optimizingId, setOptimizingId] = useState<string | null>(null);
  const [bulletNotices, setBulletNotices] = useState<Record<string, string>>({});
  const [userEditRevision, setUserEditRevision] = useState(0);
  const userEditRef = useRef(0);
  const [actionChanged, setActionChanged] = useState(false);
  const markUserEdit = () => {
    userEditRef.current += 1;
    setUserEditRevision(userEditRef.current);
    setOptimizingId(null);
  };

  const modalRef = useRef<HTMLDivElement>(null);
  const previouslyFocusedRef = useRef<HTMLElement | null>(null);

  const closeRef = useRef(onClose);
  const exitRequestedRef = useRef(false);
  const leaveStateRef = useRef({ editingId, saving, saveFailed, locale, onOpenFull });
  useLayoutEffect(() => {
    closeRef.current = onClose;
    leaveStateRef.current = { editingId, saving, saveFailed, locale, onOpenFull };
  }, [onClose, editingId, saving, saveFailed, locale, onOpenFull]);
  const scopeRef = useRef<RenovationScope | null>(null);
  // Invalidate before paint/microtasks when the parent closes or replaces
  // the target/source, even if the passive restore effect has not run yet.
  useLayoutEffect(() => () => {
    if (scopeRef.current) { scopeRef.current.active = false; scopeRef.current.queue?.retire(); }
  }, [isOpen, opportunityId]);
  // Keep this callback stable so editing never reinstalls the focus trap.
  // Only user-requested exits consult dirty state; owner invalidation below
  // clears private work immediately and never asks to retain it.
  const requestLeave = useCallback((destination: 'close' | 'full') => {
    if (exitRequestedRef.current || (scopeRef.current && !scopeRef.current.active)) return true;
    const state = leaveStateRef.current;
    if ((state.editingId || state.saving || state.saveFailed) && !window.confirm(state.locale === 'zh'
      ? '还有未保存的改动。离开会丢弃尚未保存的编辑；已经发出的保存仍可能完成。确定离开？'
      : 'There are unsaved changes. Leaving discards unsaved edits; a save already in progress may still finish. Leave bullet editing?')) return false;
    exitRequestedRef.current = true;
    if (scopeRef.current) { scopeRef.current.active = false; scopeRef.current.queue?.retire(); }
    if (destination === 'full') state.onOpenFull?.();
    else closeRef.current();
    return true;
  }, []);
  useLayoutEffect(() => {
    if (!isOpen) return;
    onCloseRequestChange?.(() => requestLeave('close'));
    return () => onCloseRequestChange?.(null);
  }, [isOpen, onCloseRequestChange, requestLeave]);
  const docRef = useRef<RenovationDoc | null>(null);
  const setCurrentDoc = useCallback((next: RenovationDoc | null) => {
    docRef.current = next;
    setDoc(next);
  }, []);
  const isCurrentScope = useCallback((scope: RenovationScope | null): scope is RenovationScope => (
    !!scope && scope.active && scopeRef.current === scope && isTokenOwnerStillCurrent(scope.owner)
  ), []);

  const isCurrentWork = useCallback((scope: RenovationScope | null, revision: number): scope is RenovationScope => (
    isCurrentScope(scope) && isOwnerTokenValid(scope.owner, scope.owner.uid) && scope.workRevision === revision
  ), [isCurrentScope]);

  // Retire work before any old continuation can run, while preserving the doc,
  // base source, variant history, and even an unsaved inline edit. A profile
  // change is not a new owner/target and must never re-load over that work.
  useLayoutEffect(() => {
    const scope = scopeRef.current;
    if (!isOpen || !scope?.active || scope.profileFingerprint === profileFingerprint) return;
    scope.profileFingerprint = profileFingerprint;
    profileRevisionRef.current += 1;
    scope.workRevision += 1;
    setProfileChanged(true);
    setStructureResult(null);
    setOptimizingId(null);
    setBulletNotices({});
    setError(null);
    setSavedFlash(false);
    setCopied(false);
    setPhase((previous) => previous === 'working' ? (docRef.current ? 'doc' : 'idle') : previous);
  }, [isOpen, profileFingerprint]);

  useLayoutEffect(() => {
    const didTargetChange = targetBindingRef.current !== targetBinding;
    targetBindingRef.current = targetBinding;
    if (sourceRef.current.ready !== sourceReady || didTargetChange) sourceRef.current.epoch += 1;
    sourceRef.current.ready = sourceReady;
    if ((sourceReady && !didTargetChange) || !isOpen) return;
    if (didTargetChange) { setActionChanged(true); setTargetChanged(true); }
    // Retire the visible pending action before paint; keep the editor buffer.
    setOptimizingId(null);
    setPhase((previous) => previous === 'working' ? (docRef.current ? 'doc' : 'idle') : previous);
  }, [isOpen, sourceReady, targetBinding]);

  // Reset + restore on every open: a saved doc for this opportunity wins
  // over the empty CTA. setState runs in the async callback.
  useEffect(() => {
    if (!isOpen) return;
    const scope: RenovationScope = { active: true, owner: captureOwnerToken(), saveRevision: 0, workRevision: 0, profileFingerprint, material: { base_snapshot: {}, method: null, warnings: [] } };
    scopeRef.current = scope;
    exitRequestedRef.current = false;
    /* eslint-disable react-hooks/set-state-in-effect --
       Modal-lifecycle reset mirroring TailorModal: every slice returns to a
       known state on open before the async restore resolves. */
    setPhase('restoring');
    setSaveState({ status: 'idle' });
    setHistoryOwner(null);
    setProfileChanged(false);
    setTargetChanged(false);
    setActionChanged(false);
    setTargetVersionIssue(null);
    setTargetVersionChecking(false);
    setCurrentDoc(null);
    setBaseSections([]);
    setStructureResult(null);
    setRestoredFromSave(false);
    setError(null);
    setCopied(false);
    setSaving(false);
    setSavedFlash(false);
    setSaveFailed(false);
    setEditingId(null);
    setEditDraft('');
    setOptimizingId(null);
    setBulletNotices({});
    /* eslint-enable react-hooks/set-state-in-effect */
    const unsubscribe = onLocalOwnerStateChange(() => {
      if (!scope.active) return;
      if (isTokenOwnerStillCurrent(scope.owner)) {
        const readyOwner = captureOwnerToken();
        if (readyOwner.generation !== scope.owner.generation && isOwnerTokenValid(readyOwner, readyOwner.uid)) {
          // Initial readiness is a new capability, not permission to upgrade
          // an already-running action. Restart restore with a fresh scope.
          scope.active = false;
          scope.queue?.retire();
          setOwnerRevision((revision) => revision + 1);
        }
        return;
      }
      // Invalidate synchronously, before React has rendered the next account.
      scope.active = false;
      scope.queue?.retire();
      exitRequestedRef.current = true;
      setHistoryOwner(null);
      setSaveState({ status: 'idle' });
      setCurrentDoc(null);
      setBaseSections([]);
      setStructureResult(null);
      setPhase('restoring');
      setEditingId(null);
      setEditDraft('');
      setOptimizingId(null);
      setBulletNotices({});
      setError(null);
      setSaving(false);
      setSavedFlash(false);
      setSaveFailed(false);
      setCopied(false);
      closeRef.current();
    });
    loadRenovation(opportunityId, scope.owner)
      .then((stored) => {
        if (!isCurrentScope(scope)) return;
        scope.queue = new RenovationSaveQueue(stored?.revision ?? 0,
          (payload, revision) => saveRenovation(opportunityId, payload.doc, payload.base_snapshot, payload.method, payload.warnings, scope.owner, revision),
          (state) => {
            if (!isCurrentScope(scope)) return;
            const sequence = ++scope.saveRevision;
            setSaveState(state);
            setSaving(state.status === 'saving');
            setSaveFailed(!['idle', 'saving', 'saved'].includes(state.status));
            setSavedFlash(state.status === 'saved');
            if (state.status === 'saved') setTimeout(() => {
              if (isCurrentScope(scope) && scope.saveRevision === sequence) setSavedFlash(false);
            }, 2000);
          });
        if (stored) scope.material = { base_snapshot: stored.base_snapshot, method: stored.method, warnings: stored.warnings };
        const storedDoc = stored?.doc as unknown as RenovationDoc | undefined;
        if (storedDoc && Array.isArray(storedDoc.sections) && storedDoc.sections.length > 0) {
          // Keep the original source signature, including after source removal. Wording no
          // review accepted (saved before w14, or in another language) does not open as current.
          setCurrentDoc(reviewedRenovation(storedDoc));
          setBaseSections(
            Array.isArray((stored?.base_snapshot as { sections?: ResumeSectionInput[] })?.sections)
              ? (stored!.base_snapshot as { sections: ResumeSectionInput[] }).sections
              : [],
          );
          setRestoredFromSave(true);
          setPhase('doc');
        } else {
          setPhase(stored === null ? 'idle' : 'restore-error');
        }
      })
      .catch(() => {
        if (isCurrentScope(scope)) setPhase('restore-error');
      });
    return () => {
      scope.active = false;
      scope.queue?.retire();
      unsubscribe();
    };
    // Profile-only changes are handled above without replacing local edits.
    // The new lifecycle captures the content current at this render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOpen, opportunityId, ownerRevision, restoreRevision, isCurrentScope, setCurrentDoc]);

  // Focus trap + escape + body-overflow lock, lifted from TailorModal so the
  // renovation modal feels identical to keyboard users.
  useEffect(() => {
    if (!isOpen) return;
    previouslyFocusedRef.current = document.activeElement as HTMLElement;
    const modal = modalRef.current;
    if (modal) {
      modal
        .querySelector<HTMLElement>(
          'button, [href], input, textarea, select, [tabindex]:not([tabindex="-1"])',
        )
        ?.focus();
    }
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === 'Escape') {
        e.preventDefault();
        requestLeave('close');
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
  }, [isOpen, requestLeave]);

  const persist = useCallback(
    (nextDoc: RenovationDoc, _sections: ResumeSectionInput[], scope: RenovationScope, workRevision = scope.workRevision) => {
      if (!isCurrentWork(scope, workRevision)) return;
      // Keep the entire original envelope, including unknown extension fields.
      scope.queue?.enqueue({ doc: nextDoc as unknown as Record<string, unknown>, ...scope.material });
    }, [isCurrentWork],
  );

  function adoptSaved(current: StoredRenovation) {
    const scope = scopeRef.current;
    if (!isCurrentScope(scope) || editingId || saving) return;
    if (!window.confirm(locale === 'zh' ? '使用已保存版本会丢弃当前本地改动。确定继续？' : 'Using the saved version discards your local edits. Continue?')) return;
    markUserEdit();
    setStructureResult(null);
    setProfileChanged(false);
    setTargetChanged(false);
    setActionChanged(false);
    setCopied(false);
    scope.queue?.resolveConflict();
    scope.material = { base_snapshot: current.base_snapshot, method: current.method, warnings: current.warnings };
    setCurrentDoc(reviewedRenovation(current.doc as unknown as RenovationDoc));
    setBaseSections(Array.isArray(current.base_snapshot.sections) ? current.base_snapshot.sections as ResumeSectionInput[] : []);
    setRestoredFromSave(true);
    setHistoryOwner(null);
    // markUserEdit retires any in-flight rerun, and a retired rerun never restores the phase itself.
    setPhase('doc');
  }

  function restoreHistory(payload: RenovationPayload) {
    const scope = scopeRef.current;
    if (!isCurrentScope(scope) || editingId || saving || saveFailed || phase !== 'doc') return;
    markUserEdit();
    setStructureResult(null);
    setProfileChanged(false);
    setTargetChanged(false);
    setActionChanged(false);
    setCopied(false);
    scope.material = { base_snapshot: payload.base_snapshot, method: payload.method, warnings: payload.warnings };
    const restored = reviewedRenovation(payload.doc as unknown as RenovationDoc);
    const sections = Array.isArray(payload.base_snapshot.sections) ? payload.base_snapshot.sections as ResumeSectionInput[] : [];
    setCurrentDoc(restored);
    setBaseSections(sections);
    setRestoredFromSave(false);
    setHistoryOwner(null);
    persist(restored, sections, scope);
  }

  // A mismatch is terminal for this attempt. Rechecking never replays it.
  async function recheckTargetVersion() {
    const scope = scopeRef.current;
    if (!isCurrentScope(scope) || !targetRefresh || targetVersionChecking) return;
    setTargetVersionChecking(true);
    try {
      const accepted = await targetRefresh.refresh();
      if (isCurrentScope(scope) && accepted) setTargetVersionIssue(null);
    } catch {
      // The reader owns its failure notice. Keep the mismatch fence and draft.
    } finally {
      if (isCurrentScope(scope)) setTargetVersionChecking(false);
    }
  }

  async function handleRenovate() {
    const scope = scopeRef.current;
    if (!sourceRef.current.ready || !expectedTargetVersion || !comparableTargetSignature || !profileSnapshot.resume_text || !['idle', 'doc'].includes(phase) || !isCurrentScope(scope)) return;
    const workRevision = ++scope.workRevision;
    const epoch = sourceRef.current.epoch;
    const editRevision = userEditRef.current;
    const current = () => sourceRef.current.ready && sourceRef.current.epoch === epoch && userEditRef.current === editRevision && isCurrentWork(scope, workRevision);
    const resumeSignature = hashString(profileSnapshot.resume_text);
    const originalDoc = docRef.current;
    setSavedFlash(false);
    setOptimizingId(null);
    setBulletNotices({});
    setPhase('working');
    setWorkingStep('structuring');
    setStructureResult(null);
    setError(null);
    try {
      const [signature, targetSignature] = await Promise.all([
        profileSignature(profileFingerprint),
        targetFingerprint === null ? Promise.resolve(undefined) : profileSignature(targetFingerprint),
      ]);
      if (!current()) return;
      if (!targetSignature) {
        setError(locale === 'zh' ? '未能核对目标来源。草稿已保留，请重新打开后重试。' : 'Could not verify the target source. Your draft is kept. Reopen and try again.');
        setPhase(originalDoc ? 'doc' : 'idle');
        return;
      }
      const structured = await structureResume(profileSnapshot.resume_text, { locale });
      if (!current()) return;
      if (structured.sections.length === 0) {
        setError(t('renovate.noSections'));
        if (originalDoc) setStructureResult(null);
        setPhase(originalDoc ? 'doc' : 'idle');
        return;
      }
      setWorkingStep('renovating');
      const renovated = await renovateResume(profileSnapshot, opportunityId, structured.sections, {
        locale, expectedTargetVersion,
      });
      if (!current()) return;
      if (renovated?.opportunity_id !== opportunityId || renovated.target_version !== expectedTargetVersion) {
        setTargetVersionIssue('unavailable');
        setPhase(originalDoc ? 'doc' : 'idle');
        return;
      }
      setStructureResult(structured);
      setRestoredFromSave(false);
      const nextDoc: RenovationDoc = {
        resume_sig: resumeSignature,
        ...(signature ? { profile_sig: signature } : {}),
        target_sig: targetSignature,
        sections: reviewedSections(renovated.sections, renovated.pipeline_version),
        method: renovated.method,
        warnings: [...new Set([...(structured.warnings ?? []), ...renovated.warnings])],
        processing: structured.processing,
      };
      scope.material = { base_snapshot: { sections: structured.sections }, method: nextDoc.method, warnings: nextDoc.warnings };
      setCurrentDoc(nextDoc);
      setProfileChanged(false);
      setTargetChanged(false);
      setEditingId(null);
      setEditDraft('');
      setBaseSections(structured.sections);
      setPhase('doc');
      void persist(nextDoc, structured.sections, scope, workRevision);
    } catch (err) {
      if (!current()) return;
      if (err && typeof err === 'object' && 'status' in err && err.status === 409 && 'code' in err && err.code === 'WRITING_TARGET_CHANGED') setTargetVersionIssue('changed');
      else setError(profileInputMessage(err, t) ?? (err instanceof Error ? err.message : t('renovate.failed')));
      if (originalDoc) setStructureResult(null);
      setPhase(originalDoc ? 'doc' : 'idle');
    }
  }

  // Immutable per-bullet doc update; persists the whole doc after each change
  // (the doc IS the rollback history, so every mutation is worth saving).
  const updateBullet = useCallback(
    (bulletId: string, updater: (b: RenovatedBullet) => RenovatedBullet) => {
      const scope = scopeRef.current;
      const prev = docRef.current;
      if (!prev || !isCurrentScope(scope)) return;
      const next: RenovationDoc = {
        ...prev,
        sections: prev.sections.map((s) => ({
          ...s,
          bullets: s.bullets.map((b) => (b.id === bulletId ? updater(b) : b)),
        })),
      };
      // Keep persistence outside React state updaters (which may be replayed).
      setCurrentDoc(next);
      void persist(next, baseSections, scope);
    },
    [persist, baseSections, isCurrentScope, setCurrentDoc],
  );

  function handleRollback(b: RenovatedBullet) {
    if (b.current < 0) return;
    markUserEdit();
    updateBullet(b.id, (cur) => ({ ...cur, current: cur.current - 1 }));
  }

  function handleRollForward(b: RenovatedBullet) {
    if (b.current >= b.variants.length - 1) return;
    markUserEdit();
    updateBullet(b.id, (cur) => ({ ...cur, current: cur.current + 1 }));
  }

  // The shown rewrite without the posting's terms becomes the next variant; rollback returns to it.
  function applyWithoutTerms(b: RenovatedBullet) {
    const shown = b.current >= 0 ? b.variants[b.current] : null;
    if (!shown?.alternative) return;
    markUserEdit();
    updateBullet(b.id, (cur) => ({
      ...cur,
      variants: [...cur.variants, { source: shown.source, text: shown.alternative!, source_evidence: shown.source_evidence,
        ops: (shown.ops ?? []).filter((op) => op !== 'relabel'), links: shown.links ?? [], alternative: null,
        ...(shown.reviewed ? { reviewed: shown.reviewed } : {}) }],
      current: cur.variants.length,
    }));
  }

  function startEdit(b: RenovatedBullet) {
    markUserEdit();
    setEditingId(b.id);
    setEditDraft(bulletCurrentText(b));
  }

  function saveEdit(b: RenovatedBullet) {
    markUserEdit();
    const trimmed = editDraft.trim();
    setEditingId(null);
    setEditDraft('');
    if (!trimmed || trimmed === bulletCurrentText(b)) return;
    updateBullet(b.id, (cur) => ({
      ...cur,
      variants: [...cur.variants, { source: 'user', text: trimmed, source_evidence: '' }],
      current: cur.variants.length,
    }));
  }

  async function handleReoptimize(b: RenovatedBullet) {
    const scope = scopeRef.current;
    if (!sourceRef.current.ready || !expectedTargetVersion || !docSourceCurrent || optimizingId || !isCurrentScope(scope)) return;
    const workRevision = scope.workRevision;
    const epoch = sourceRef.current.epoch;
    const editRevision = userEditRef.current;
    const current = () => sourceRef.current.ready && sourceRef.current.epoch === epoch && userEditRef.current === editRevision && isCurrentWork(scope, workRevision);
    const isSameBullet = () => docRef.current?.sections.some((s) => s.bullets.some((cur) => cur === b));
    const text = bulletCurrentText(b);
    if (characterCount(text) > REWRITE_MAX_BULLET_CHARACTERS) return;
    setOptimizingId(b.id);
    setBulletNotices((prev) => ({ ...prev, [b.id]: '' }));
    try {
      const resp = await optimizeBullet(
        profileSnapshot,
        opportunityId,
        text,
        b.base_text,
        { locale, expectedTargetVersion },
      );
      if (!current() || !isSameBullet()) return;
      if (resp?.opportunity_id !== opportunityId || resp.target_version !== expectedTargetVersion) {
        setTargetVersionIssue('unavailable');
        return;
      }
      // Only a reviewed rewrite becomes a variant; an older backend's unreviewed one is kept out.
      if (resp.status === 'rewritten' && resp.changed && resp.text.trim()) {
        updateBullet(b.id, (cur) => ({
          ...cur,
          variants: [
            ...cur.variants,
            { source: 'ai', text: resp.text, source_evidence: resp.source_evidence, ops: resp.ops ?? [], links: resp.links ?? [],
              alternative: resp.alternative ?? null, ...(isReviewedRules(resp.pipeline_version) ? { reviewed: resp.pipeline_version } : {}) },
          ],
          current: cur.variants.length,
        }));
      } else {
        // Backend declined (validation or no improvement) — honest no-op, with the reason when it gave one.
        const kept = keptExplanation(resp.changed && resp.status !== 'rewritten' ? 'review_unavailable' : resp.reason_code, t);
        setBulletNotices((prev) => ({ ...prev, [b.id]: kept ? `${kept.label} — ${kept.reason}` : t('renovate.bulletUnchanged') }));
      }
    } catch (err) {
      if (!current() || !isSameBullet()) return;
      const refusedLimit = refusedOptimizeLimit(err);
      if (err && typeof err === 'object' && 'status' in err && err.status === 409 && 'code' in err && err.code === 'WRITING_TARGET_CHANGED') setTargetVersionIssue('changed');
      else if (refusedLimit !== null) {
        setBulletNotices((prev) => ({ ...prev, [b.id]: t('renovate.limits.tooLongToOptimize', { actual: characterCount(text), max: refusedLimit }) }));
      } else setBulletNotices((prev) => ({ ...prev, [b.id]: profileInputMessage(err, t) ?? t('renovate.bulletFailed') }));
    } finally {
      if (current()) setOptimizingId(null);
    }
  }

  const knownSignature = typeof doc?.profile_sig === 'string' && /^v1:sha256:[a-f0-9]{64}$/.test(doc.profile_sig);
  const comparableSignature = currentSignature?.fingerprint === profileFingerprint ? currentSignature.signature : undefined;
  const staleProfile = profileChanged || (!!knownSignature && !!comparableSignature && doc?.profile_sig !== comparableSignature);
  const unknownProfile = !!doc && (!knownSignature || !comparableSignature);
  const knownTargetSignature = typeof doc?.target_sig === 'string' && /^v1:sha256:[a-f0-9]{64}$/.test(doc.target_sig);
  const unknownTarget = !!doc && !knownTargetSignature;
  const staleTarget = !!knownTargetSignature && !!comparableTargetSignature && doc?.target_sig !== comparableTargetSignature;
  const docSourceCurrent = !!knownSignature && !!comparableSignature && doc?.profile_sig === comparableSignature
    && !staleProfile && !staleResume && !targetChanged && !!knownTargetSignature
    && !!comparableTargetSignature && doc?.target_sig === comparableTargetSignature;

  const profileAction = useProfileAction<{ kind: 'generate' } | { kind: 'optimize'; bulletId: string; profileFingerprint: string; sourceRevision: number }>({
    isOpen,
    profile,
    profileAvailable,
    scopeKey: canonicalProfile([opportunityId, targetBinding]),
    editRevision: userEditRevision,
    refresh: profileRefresh, target, targetRefresh,
    readiness: profileAvailable && (targetChecking || profileRefresh?.status === 'checking' || currentSignature?.fingerprint !== profileFingerprint || targetSignaturePending)
      ? 'waiting' : sourceReady && !targetBindingUnavailable && ['idle', 'doc'].includes(phase) ? 'ready' : 'blocked',
    execute: (intent) => {
      if (intent.kind === 'generate') {
        // The committed executor sees the checked profile, never the click's
        // captured profile. Existing drafts change only after a full success.
        void handleRenovate();
        return;
      }
      // A single-bullet request belongs to its original material. Checking a
      // newer profile must not silently rebind an old bullet to that source.
      if (!docSourceCurrent || intent.profileFingerprint !== profileFingerprint || intent.sourceRevision !== profileRevisionRef.current) { setActionChanged(true); return; }
      const bullet = docRef.current?.sections.flatMap((section) => section.bullets).find((item) => item.id === intent.bulletId);
      if (bullet) void handleReoptimize(bullet);
    },
  });
  const requestGeneration = () => { setActionChanged(false); profileAction.request({ kind: 'generate' }); };
  const requestOptimization = (bullet: RenovatedBullet) => {
    if (!docSourceCurrent) return;
    setActionChanged(false);
    profileAction.request({ kind: 'optimize', bulletId: bullet.id, profileFingerprint, sourceRevision: profileRevisionRef.current });
  };

  async function handleCopyAll() {
    const scope = scopeRef.current;
    if (!doc || !isCurrentScope(scope)) return;
    const workRevision = scope.workRevision;
    const lines: string[] = [];
    for (const s of doc.sections) {
      // A section with no bullets has nothing to paste under its heading.
      if (s.bullets.length === 0) continue;
      if (s.heading) lines.push(s.heading.toUpperCase());
      // "demote" is defined for the model as "kept but de-emphasized (placed
      // lower)", and the chip a student reads says "De-emphasized". This used
      // to drop those bullets, so clicking "Copy renovated résumé" silently
      // deleted the student's own experience from what they pasted back. Order
      // by rank instead, which is what the plan actually asked for.
      const rank = (action: string) =>
        action === 'foreground' ? 0 : action === 'demote' ? 2 : 1;
      for (const b of [...s.bullets].sort((a, c) => rank(a.action) - rank(c.action))) {
        lines.push(`• ${bulletCurrentText(b)}`);
      }
      lines.push('');
    }
    await navigator.clipboard.writeText(lines.join('\n').trim());
    if (!isCurrentWork(scope, workRevision)) return;
    setCopied(true);
    setTimeout(() => { if (isCurrentWork(scope, workRevision)) setCopied(false); }, 2000);
  }

  if (!isOpen) return null;

  const warningMessages = doc ? pickRenovationWarnings(doc.warnings, t) : [];
  const hasResume = !!profileSnapshot.resume_text;
  // One provenance/action notice: a stale draft is stronger than unknown
  // provenance or a stopped intent. The shared banner owns read-error retry.
  const draftStale = !!doc && (staleProfile || staleResume || targetChanged || staleTarget);
  const sharedReadFailure = profileRefresh?.status === 'failed';
  const readUnavailable = profileAction.error === 'unavailable';
  const provenanceNotice = !draftStale && (targetBindingUnavailable || unknownTarget)
    ? targetBindingUnavailable
      ? (locale === 'zh' ? '未能核对机会资料。草稿已保留，请重新打开机会后重试。' : 'Could not verify the opportunity information. Your draft is kept. Reopen the opportunity and try again.')
      : (locale === 'zh' ? '旧稿的目标来源未知。草稿和手改已保留，请重新生成后再优化条目。' : 'This draft’s saved target is unknown. Your draft and edits are kept. Re-renovate before optimizing bullets.')
    : null;
  const actionNotice = draftStale || (!sharedReadFailure && (profileAction.error || actionChanged || profileChanged))
    ? sharedReadFailure
      ? (locale === 'zh' ? '重新生成后再优化条目。' : 'Re-renovate before optimizing bullets.')
      : readUnavailable
        ? (locale === 'zh'
          ? `未能核对${targetRefresh ? '资料或机会' : '资料'}，草稿已保留。${draftStale ? '请重试核对，再重新生成后优化条目。' : '请重试核对后再操作。'}`
          : `Could not check your ${targetRefresh ? 'profile or opportunity' : 'profile'}. Your draft is kept. ${draftStale ? 'Retry the check, then re-renovate before optimizing bullets.' : 'Retry the check before continuing.'}`)
        : draftStale
          ? (locale === 'zh' ? '资料或目标已变。草稿和手改已保留，请重新生成后再优化条目。' : 'Profile or target changed. Your draft and edits are kept. Re-renovate before optimizing bullets.')
          : profileChanged && !doc
            ? (locale === 'zh' ? '资料已变，请核对当前资料后重试。' : 'Your profile changed. Review the current information and try again.')
            : (locale === 'zh' ? '资料、目标或编辑内容已变。草稿已保留，请核对后重试。' : 'The profile, target or edits changed. Your draft is kept. Review it and try again.')
    : provenanceNotice;

  return (
    <div
      className="fixed inset-0 z-[55] flex sm:items-center sm:justify-center"
      role="dialog"
      aria-modal="true"
      aria-labelledby="renovation-modal-title"
    >
      <div
        className="absolute inset-0 bg-gray-900/60 backdrop-blur-sm"
        onClick={() => requestLeave('close')}
        aria-hidden="true"
      />

      <div
        ref={modalRef}
        className="relative w-full sm:max-w-4xl sm:mx-4 bg-white sm:rounded-2xl shadow-2xl h-full sm:h-auto sm:max-h-[90vh] flex flex-col overflow-hidden"
      >
        {/* Header */}
        <div className="flex items-start justify-between px-4 sm:px-6 py-3 sm:py-4 border-b border-gray-100 shrink-0">
          <div className="flex items-start gap-3 min-w-0">
            <div className="w-9 h-9 rounded-xl bg-indigo-50 flex items-center justify-center shrink-0" aria-hidden="true">
              <FileText className="w-5 h-5 text-indigo-600" />
            </div>
            <div className="min-w-0">
              <h2 id="renovation-modal-title" className="text-lg font-bold text-gray-900">
                {onOpenFull ? (locale === 'zh' ? '经历条目编辑' : 'Résumé bullets') : t('renovate.title')}
              </h2>
              <p className="text-sm text-gray-500 truncate max-w-md">{opportunityTitle}</p>
              <p className="text-xs text-gray-400 mt-1 max-w-md hidden sm:block">
                {onOpenFull ? (locale === 'zh' ? '逐条调整经历。姓名、教育和完整结构请在目标简历中编辑。' : 'Edit experience bullets. Use the full target résumé for identity, education and complete structure.') : t('renovate.subtitle')}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            {savedFlash && !editingId && (
              <span className="inline-flex items-center gap-1 text-[11px] font-medium text-emerald-600">
                <CheckCircle className="w-3.5 h-3.5" aria-hidden="true" />
                {t('renovate.saved')}
              </span>
            )}
            {saveFailed && !saving && ['unknown', 'unavailable'].includes(saveState.status) && (
              <span className="inline-flex flex-wrap items-center gap-1.5 text-[11px] font-medium text-amber-600" data-testid="renovation-save-failed">
                {locale === 'zh' ? '保存结果未确认' : 'Save not confirmed'}
                <button type="button" className="underline hover:text-amber-700" onClick={() => scopeRef.current?.queue?.retry()}>{t('renovate.retrySave')}</button>
              </span>
            )}
            {saving && !savedFlash && (
              <span className="text-[11px] text-gray-400">{t('renovate.saving')}</span>
            )}
            <button
              type="button"
              onClick={() => requestLeave('close')}
              className="p-2 rounded-lg hover:bg-gray-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 transition-colors"
              aria-label={t('renovate.closeAria')}
            >
              <X className="w-5 h-5 text-gray-400" aria-hidden="true" />
            </button>
          </div>
        </div>

        <ProfileRefreshBanner locale={locale} refresh={profileRefresh} targetRefresh={targetRefresh} targetReady={targetMembershipReady ?? targetReady} profileAvailable={profileAvailable} onBeforeReview={() => requestLeave('close')} />

        {(!expectedTargetVersion || targetVersionIssue) && phase !== 'restoring' && <div role="status" data-testid="renovation-target-version" className="mx-4 mt-3 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">
          <p>{t(targetVersionIssue === 'changed' ? 'renovate.targetVersionChanged' : 'renovate.targetVersionUnavailable')}</p>
          {targetRefresh && <button type="button" disabled={targetVersionChecking || targetRefresh.status === 'checking'}
            className="mt-2 underline disabled:opacity-50" onClick={() => { void recheckTargetVersion(); }}>{t('renovate.targetVersionRetry')}</button>}
        </div>}

        {profileAction.busy && <p role="status" data-testid="renovation-action-check" className="px-4 py-2 text-sm text-indigo-700">
          {locale === 'zh' ? (targetRefresh ? '正在核对最新资料及机会，完成后再开始润色…' : '正在核对最新资料，完成后再开始润色…') : (targetRefresh ? 'Checking current profile and opportunity before renovation…' : 'Checking current profile before renovation…')}
        </p>}


        {onOpenFull && <div className="border-b border-gray-100 px-4 py-2 sm:px-6">
          <button type="button" className="text-sm font-medium text-indigo-700 underline"
            onClick={() => requestLeave('full')}>
            {locale === 'zh' ? '打开完整目标简历' : 'Open full target résumé'}
          </button>
        </div>}
        {/* Body */}
        <div className="flex-1 overflow-y-auto min-h-0">
          {phase === 'doc' && <div className="px-4 pt-3"><button type="button" className="text-sm text-indigo-700 underline" onClick={() => { const scope = scopeRef.current; if (isCurrentScope(scope)) setHistoryOwner(owner => owner ? null : scope.owner); }}>{locale === 'zh' ? '历史版本' : 'Version history'}</button></div>}
          {saveState.status === 'conflict' && saveState.current && <section role="alert" data-testid="renovation-save-conflict" className="mx-4 mt-3 rounded-lg border border-amber-300 bg-amber-50 p-3 space-y-3">
            <p>{locale === 'zh' ? '其他设备已保存了新版本。你的本地改动已保留，请比较后选择。' : 'Another device saved a newer version. Your local edits are kept. Compare the saved draft before choosing.'}</p>
            <details><summary>{locale === 'zh' ? '查看已保存版本' : 'View saved version'}</summary><pre className="max-h-60 overflow-auto whitespace-pre-wrap break-words text-sm" data-testid="renovation-conflict-preview">{(saveState.current.doc as unknown as RenovationDoc).sections.map(s => [s.heading, ...s.bullets.map(bulletCurrentText)].join('\n')).join('\n\n')}</pre></details>
            <div className="flex flex-wrap gap-3">
              <button type="button" disabled={!!editingId} className="text-sm underline disabled:text-gray-400" onClick={() => adoptSaved(saveState.current!)}>{locale === 'zh' ? '使用已保存版本' : 'Use saved version'}</button>
              <button type="button" disabled={!!editingId} className="text-sm underline disabled:text-gray-400" onClick={() => {
                const scope = scopeRef.current;
                if (isCurrentScope(scope) && docRef.current && !editingId) scope.queue?.resolveConflict({ doc: docRef.current as unknown as Record<string, unknown>, ...scope.material });
              }}>{locale === 'zh' ? '用我的稿件替换此版本' : 'Save my draft over this version'}</button>
            </div>
          </section>}
          {saveState.status === 'missing' && <p role="alert" className="mx-4 mt-3 rounded-lg bg-amber-50 p-3 text-sm">{locale === 'zh' ? '已保存稿已被移除。请先复制本地内容，再重新打开。当前编辑不会自动重新建稿。' : 'The saved draft was removed. Copy your local text before reopening. These edits will not recreate it automatically.'}</p>}
          {historyOwner && <RenovationHistory opportunityId={opportunityId} owner={historyOwner} locale={locale} disabled={!!editingId || saving || saveFailed || phase !== 'doc'} onRestore={restoreHistory} onClose={() => setHistoryOwner(null)} />}

          {phase !== 'restoring' && (hasResume || doc?.processing) && (
            <div className="px-4 sm:px-6 pt-4">
              <ResumeProcessingNotice
                text={profile.resume_text ?? ''}
                processing={structureResult?.processing ?? doc?.processing}
                warnings={structureResult?.warnings ?? doc?.warnings}
              />
            </div>
          )}
          {phase === 'restoring' && (
            <div className="flex flex-col items-center justify-center py-20 gap-3">
              <Loader2 className="w-7 h-7 text-indigo-500 animate-spin" />
            </div>
          )}

          {phase === 'restore-error' && (
            <div role="alert" className="flex flex-col items-center justify-center py-16 gap-4 px-6 text-center">
              <AlertCircle className="w-8 h-8 text-amber-600" aria-hidden="true" />
              <p className="text-sm text-gray-700">{t('renovate.restoreFailed')}</p>
              <button type="button" onClick={() => setRestoreRevision((revision) => revision + 1)}
                className="text-sm font-semibold text-indigo-600 underline">{t('renovate.restoreRetry')}</button>
            </div>
          )}
          {actionNotice && phase !== 'restoring' && (
            <p role="status" className="mx-4 mt-4 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800"
              data-testid={draftStale || provenanceNotice ? 'renovation-source-review' : 'renovation-action-error'}>{actionNotice}</p>
          )}
          {unknownProfile && phase === 'doc' && !actionNotice && !sharedReadFailure && (
            <p className="mx-4 mt-4 text-sm text-gray-600" data-testid="renovation-profile-unknown">{t('renovate.profileUnknown')}</p>
          )}
          {phase === 'idle' && (
            <div className="flex flex-col items-center justify-center py-16 gap-4 px-6 text-center">
              <Sparkles className="w-8 h-8 text-indigo-300" aria-hidden="true" />
              {hasResume ? (
                <>
                  <p className="text-sm text-gray-600 max-w-md">{t('renovate.intro')}</p>
                  {error && (
                    <p className="text-sm text-red-600 flex items-center gap-1.5">
                      <AlertCircle className="w-4 h-4" aria-hidden="true" />
                      {error}
                    </p>
                  )}
                  <button
                    type="button"
                    disabled={!sourceReady || targetBindingUnavailable || profileAction.busy}
                    onClick={requestGeneration}
                    className="inline-flex items-center gap-2 px-5 py-2.5 text-sm font-semibold text-white bg-gradient-to-r from-indigo-600 to-fuchsia-500 rounded-xl hover:from-indigo-700 hover:to-fuchsia-600 shadow-sm transition-all"
                  >
                    <Wand2 className="w-4 h-4" aria-hidden="true" />
                    {t('renovate.start')}
                  </button>
                </>
              ) : (
                <p className="text-sm text-gray-500 max-w-md">{t('renovate.noResume')}</p>
              )}
            </div>
          )}

          {phase === 'working' && (
            <div className="flex flex-col items-center justify-center py-20 gap-3">
              <Loader2 className="w-7 h-7 text-indigo-500 animate-spin" />
              <p className="text-sm text-gray-500">
                {workingStep === 'structuring'
                  ? t('renovate.structuring')
                  : t('renovate.renovating')}
              </p>
            </div>
          )}

          {phase === 'doc' && doc && (
            <div className="px-4 sm:px-6 py-4 space-y-5">
              {error && <p role="alert" className="text-sm text-red-600">{error}</p>}
              {restoredFromSave && (
                <p className="text-[11.5px] text-indigo-600 bg-indigo-50 inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full">
                  <Info className="w-3.5 h-3.5" aria-hidden="true" />
                  {t('renovate.restored')}
                </p>
              )}
              {warningMessages.length > 0 && (
                <div className="flex items-start gap-2 px-3 py-2 rounded-lg bg-amber-50 border border-amber-200 text-[12.5px] text-amber-800">
                  <Info className="w-4 h-4 text-amber-500 shrink-0 mt-0.5" aria-hidden="true" />
                  <div className="space-y-1">
                    {warningMessages.map((message) => <p key={message}>{message}</p>)}
                  </div>
                </div>
              )}
              <p className="text-[11.5px] text-gray-400">{t('renovate.reviewHint')}</p>

              {doc.sections.map((section: RenovatedSection) => (
                <section key={section.id}>
                  <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">
                    {section.heading || section.kind}
                  </h3>
                  <ul className="space-y-2.5">
                    {section.bullets.map((b) => {
                      const current = bulletCurrentText(b);
                      const showingVariant = b.current >= 0 ? b.variants[b.current] : null;
                      const sourceKey = showingVariant?.source ?? 'base';
                      const isEditing = editingId === b.id;
                      const isOptimizing = optimizingId === b.id;
                      const action = ACTION_CHIP[b.action] ?? ACTION_CHIP.keep;
                      const currentLength = characterCount(current);
                      const overLimit = currentLength > REWRITE_MAX_BULLET_CHARACTERS;
                      const notice = overLimit
                        ? t('renovate.limits.tooLongToOptimize', { actual: currentLength, max: REWRITE_MAX_BULLET_CHARACTERS })
                        : bulletNotices[b.id];
                      const changed = current.trim() !== b.base_text.trim();
                      return (
                        <li
                          key={b.id}
                          className={`bg-white border rounded-xl shadow-sm px-4 py-3 ${
                            b.action === 'demote' ? 'opacity-60 border-dashed border-gray-300' : 'border-gray-200'
                          }`}
                        >
                          <div className="flex items-center justify-between gap-2 mb-1">
                            <div className="flex items-center gap-1.5 min-w-0">
                              <span
                                className={`text-[9.5px] font-semibold uppercase tracking-wide px-1.5 py-px rounded ${SOURCE_CHIP_STYLES[sourceKey] ?? SOURCE_CHIP_STYLES.base}`}
                              >
                                {t(`renovate.source.${sourceKey}`)}
                              </span>
                              {b.action !== 'keep' && (
                                <span
                                  className={`inline-flex items-center gap-0.5 text-[9.5px] font-semibold uppercase tracking-wide px-1.5 py-px rounded ${action.className}`}
                                >
                                  {action.icon === 'up' && <ArrowUpRight className="w-2.5 h-2.5" aria-hidden="true" />}
                                  {action.icon === 'down' && <ArrowDownRight className="w-2.5 h-2.5" aria-hidden="true" />}
                                  {t(`renovate.action.${b.action}`)}
                                </span>
                              )}
                            </div>
                            {!isEditing && (
                              <div className="ml-auto flex items-center gap-0.5 shrink-0">
                                <button
                                  type="button"
                                  onClick={() => handleRollback(b)}
                                  disabled={b.current < 0}
                                  className="inline-flex items-center gap-1 text-[10.5px] font-medium px-1.5 py-0.5 rounded-md text-gray-400 hover:text-indigo-600 hover:bg-indigo-50 disabled:opacity-30 disabled:hover:bg-transparent disabled:hover:text-gray-400 transition-colors"
                                  aria-label={t('renovate.rollbackAria')}
                                >
                                  <RotateCcw className="w-3 h-3" aria-hidden="true" />
                                  {t('renovate.rollback')}
                                </button>
                                {b.current < b.variants.length - 1 && (
                                  <button
                                    type="button"
                                    onClick={() => handleRollForward(b)}
                                    className="inline-flex items-center gap-1 text-[10.5px] font-medium px-1.5 py-0.5 rounded-md text-gray-400 hover:text-indigo-600 hover:bg-indigo-50 transition-colors"
                                    aria-label={t('renovate.rollForwardAria')}
                                  >
                                    <RefreshCw className="w-3 h-3" aria-hidden="true" />
                                    {t('renovate.rollForward')}
                                  </button>
                                )}
                                <button
                                  type="button"
                                  onClick={() => startEdit(b)}
                                  className="inline-flex items-center gap-1 text-[10.5px] font-medium px-1.5 py-0.5 rounded-md text-gray-400 hover:text-indigo-600 hover:bg-indigo-50 transition-colors"
                                  aria-label={t('renovate.editAria')}
                                >
                                  <Pencil className="w-3 h-3" aria-hidden="true" />
                                  {t('renovate.edit')}
                                </button>
                                <button
                                  type="button"
                                  onClick={() => requestOptimization(b)}
                                  disabled={!sourceReady || !docSourceCurrent || profileAction.busy || isOptimizing || optimizingId !== null || overLimit}
                                  className="inline-flex items-center gap-1 text-[10.5px] font-medium px-1.5 py-0.5 rounded-md text-fuchsia-500 hover:text-fuchsia-700 hover:bg-fuchsia-50 disabled:opacity-40 transition-colors"
                                  aria-label={t('renovate.reoptimizeAria')}
                                >
                                  {isOptimizing ? (
                                    <Loader2 className="w-3 h-3 animate-spin" aria-hidden="true" />
                                  ) : (
                                    <Wand2 className="w-3 h-3" aria-hidden="true" />
                                  )}
                                  {t('renovate.reoptimize')}
                                </button>
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
                                aria-label={t('renovate.editAria')}
                              />
                              <div className="flex items-center gap-2 mt-1.5">
                                <button
                                  type="button"
                                  onClick={() => saveEdit(b)}
                                  className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md text-[11.5px] font-semibold text-white bg-indigo-600 hover:bg-indigo-700 transition-colors"
                                >
                                  <CheckCircle className="w-3 h-3" aria-hidden="true" />
                                  {t('renovate.save')}
                                </button>
                                <button
                                  type="button"
                                  onClick={() => {
                                    markUserEdit();
                                    setEditingId(null);
                                    setEditDraft('');
                                  }}
                                  className="px-2.5 py-1 rounded-md text-[11.5px] font-medium text-gray-500 hover:bg-gray-100 transition-colors"
                                >
                                  {t('renovate.cancel')}
                                </button>
                              </div>
                            </div>
                          ) : (
                            <p className="text-[13.5px] leading-relaxed text-gray-800">
                              {changed ? (
                                <DiffLine original={b.base_text} tailored={current} side="tailored" />
                              ) : (
                                current
                              )}
                            </p>
                          )}

                          {showingVariant && !isEditing && !isReviewedVariant(showingVariant, b.base_text) && (
                            <p className="mt-1.5 text-[11.5px] text-amber-700" data-testid="renovation-not-reviewed">
                              {t('renovate.notReviewed')}
                            </p>
                          )}
                          {showingVariant && !isEditing && (
                            <RewriteWhy links={showingVariant.links} ops={showingVariant.ops} t={t} />
                          )}
                          {showingVariant?.alternative && showingVariant.alternative !== current && !isEditing && (
                            <button
                              type="button"
                              onClick={() => applyWithoutTerms(b)}
                              className="mt-1.5 text-[11px] font-medium text-indigo-600 underline underline-offset-2 hover:text-indigo-700"
                            >
                              {t('tailor.useWithoutTerms')}
                            </button>
                          )}
                          {!showingVariant && b.note && !isEditing && keptExplanation(b.note, t) && (
                            <p className="mt-1.5 text-[11.5px] text-gray-500" data-testid="renovation-kept-note">
                              {keptExplanation(b.note, t)!.label} — {keptExplanation(b.note, t)!.reason}
                            </p>
                          )}
                          {showingVariant?.source_evidence && !isEditing && (
                            <p className="mt-1.5 text-[11.5px] text-gray-500 italic">
                              <span className="font-medium not-italic uppercase tracking-wider text-[10px] text-gray-400">
                                {t('renovate.sourceLabel')}:
                              </span>{' '}
                              &quot;{showingVariant.source_evidence}&quot;
                            </p>
                          )}
                          {notice && (
                            <p className="mt-1.5 text-[11.5px] text-amber-700">{notice}</p>
                          )}
                        </li>
                      );
                    })}
                  </ul>
                </section>
              ))}
            </div>
          )}
        </div>

        {/* Footer */}
        {phase === 'doc' && doc && (
          <div className="flex items-center justify-end gap-3 px-6 py-3 border-t border-gray-100 bg-gray-50/50 shrink-0">
            <button
              type="button"
              disabled={!sourceReady || targetBindingUnavailable || profileAction.busy}
              onClick={requestGeneration}
              className="inline-flex items-center gap-2 px-4 py-2 text-sm font-medium text-indigo-700 bg-indigo-50 border border-indigo-100 rounded-xl hover:bg-indigo-100 transition-colors mr-auto"
            >
              <RefreshCw className="w-4 h-4" aria-hidden="true" />
              {t('renovate.rerun')}
            </button>
            <button
              type="button"
              onClick={handleCopyAll}
              className="inline-flex items-center gap-2 px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-200 rounded-xl hover:bg-gray-50 transition-colors"
            >
              {copied ? (
                <>
                  <CheckCircle className="w-4 h-4 text-emerald-500" aria-hidden="true" />
                  {t('renovate.copied')}
                </>
              ) : (
                <>
                  <Copy className="w-4 h-4" aria-hidden="true" />
                  {t('renovate.copyAll')}
                </>
              )}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
