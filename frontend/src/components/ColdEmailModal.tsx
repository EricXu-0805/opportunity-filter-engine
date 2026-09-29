'use client';

import { profileInputMessage } from '@/lib/profile-input';

import { applyEmailReplacement, captureTextareaSelection, type EmailTextSelection } from '@/lib/email-revision';
import { canFallbackColdEmailStream, emailInputTooLargeMessage, isEmailInputTooLarge } from '@/lib/cold-email-stream';
import type { ResumeSupplementDraftSnapshot } from '@/lib/resume-supplement-draft';
import ResumeSupplementPanel from './ResumeSupplementPanel';
import { isEmailPaperReadingCurrent } from '@/lib/email-paper-reading';
import type { ProfileViewSnapshot } from '@/lib/profile-sync';
import ContactInstructionsPanel from './ContactInstructionsPanel';
import EmailTargetConditionsPanel from './EmailTargetConditionsPanel';
import { readEmailTargetConditions, isEmailConditionIssues, emailConditionIssueText, type EmailTargetConditions, type EmailConditionIssue } from '@/lib/email-target-conditions';
import { contactEmailBlock, contactInstructionCopy } from '@/lib/contact-instructions';
import { verifyComposeRecipient } from '@/lib/email-compose';
import { writingTargetVersion } from '@/lib/writing-target-version';
import { isPublicDetail } from '@/lib/public-target-shape';
import { defaultEmailContactContext, serializeEmailContactContext, emailContactContextSignature, requireEmailContactContextReceipt } from '@/lib/email-contact-context';
import type { EmailContactContext } from '@/lib/types';
import EmailContactContextPanel from './EmailContactContextPanel';
import type { EmailContactDraftSnapshot } from '@/lib/email-contact-draft';
import { COLD_EMAIL_DRAFT_LIMITS, type ColdEmailDraftPayload, type ColdEmailDraftSources, type ColdEmailDraftVersion } from '@/lib/cold-email-draft';
import EmailVersionHistory from './EmailVersionHistory';
import { useColdEmailDraftPersistence } from '@/lib/use-cold-email-draft';
import { createContactEventInput, contactMaterialVersion, ContactEventError } from '@/lib/contact-ledger';

import { useState, useEffect, useLayoutEffect, useCallback, useMemo, useRef, type MouseEvent } from 'react';
import Link from 'next/link';
import { captureOwnerToken, isOwnerTokenValid, isTokenOwnerStillCurrent, onLocalOwnerStateChange } from '@/lib/identity-owner';
import { canDeliverReminder } from '@/lib/reminders';
import { getPushStatus, isPushSupported, subscribeToPush } from '@/lib/push';
import { getVapidPublicKey } from '@/lib/api';
import {
  X,
  Copy,
  ExternalLink,
  Loader2,
  CheckCircle,
  AlertCircle,
  BellRing,
  Mail,
  Send,
  Sparkles,
  UserRound,
} from 'lucide-react';
import {
  generateColdEmail,
  generateColdEmailStream,
  getEmailVariants,
  refineEmail,
  validateEmailDraft,
  type ColdEmailStage,
} from '@/lib/api';
import {
  confirmContactEvent,
  onAuthChange,
  updateInteractionDetails,
} from '@/lib/supabase';
import type { InteractionRecord, InteractionType } from '@/lib/supabase';
import { useAuthModal } from '@/lib/auth-modal-context';
import { isActiveExperience, sourceDigest, validateExperienceEntries } from '@/lib/experience-evidence';
import type { Opportunity, ProfileData, EmailVariant, LabType, EmailStyle, ColdEmailFallbackReason, ColdEmailResponse, ContactEmailStatus, ExperienceUsage } from '@/lib/types';
import { useT } from '@/i18n/client';
import type { ProfileRefreshState } from '@/lib/use-profile-refresh';
import type { WritingTargetState } from '@/lib/use-writing-target';
import { profileActionKey, useProfileAction } from '@/lib/use-profile-action';
import ProfileRefreshBanner, { profileRefreshReady } from './ProfileRefreshBanner';
import LabTypeBadge from './LabTypeBadge';
import EmailTipsPanel from './EmailTipsPanel';
import styles from './ColdEmailModal.module.css';

type ComposeProvider = 'default' | 'gmail' | 'outlook' | 'copy';
type ComposeFailure = 'popup' | 'unavailable' | 'recipient' | 'conditions';
type PendingCompose = {
  id: number; popup: Window | null; owner: ReturnType<typeof captureOwnerToken>;
  key: string; provider: ComposeProvider; phase: 'sources' | 'recipient';
  controller: AbortController; deadline: ReturnType<typeof setTimeout>;
};

type EmailEditBase = {
  body: string; subject: string; recipient: string; revision: number; session: number;
  material: string; owner: ReturnType<typeof captureOwnerToken>;
};
type EmailEditRequest = { base: EmailEditBase; selection: EmailTextSelection | null };
type EmailEditProposal = EmailEditRequest & {
  id: number; afterBody: string; usage: ExperienceUsage | null; conditions?: EmailTargetConditions | null; instruction?: string;
};
type EmailEditUndo = {
  base: EmailEditBase; beforeBody: string; usage: ExperienceUsage | null; conditions: EmailTargetConditions | null;
  sources: { profile: string; target: string | null; contact: string } | null;
  origin: string | null; restored: ColdEmailDraftSources | null;
};

const AI_VARIANT_ID = 'ai';
const NO_DRAFT_SOURCES: ColdEmailDraftSources = { profile_sig: null, target_version: null, contact_sig: null };
async function emailDraftDigest(value: string): Promise<string> {
  const result = await globalThis.crypto.subtle.digest('SHA-256', new TextEncoder().encode(value));
  return Array.from(new Uint8Array(result), byte => byte.toString(16).padStart(2, '0')).join('');
}
// W12: a cached AI draft is re-served for at most this long — beyond it the
// professor record may have moved (email nulled, works revoked) and the
// draft must regenerate from the live corpus.
export const AI_CACHE_TTL_MS = 30 * 60 * 1000;

/** In-tab reuse needs the pipeline version freshly returned by variants.
 *  Missing versions cannot establish compatibility. Corpus changes and the
 *  TTL still expire an otherwise compatible draft. Exported for tests. */
export function aiCacheEntryIsStale(
  entry: { response: { corpus_version?: string | null; pipeline_version?: string | null; target_version?: string | null }; at: number },
  nowMs: number,
  currentCorpusVersion: string | null,
  currentPipelineVersion: string | null,
  currentTargetVersion: string | null,
): boolean {
  if (!currentTargetVersion || entry.response.target_version !== currentTargetVersion) return true;
  if (nowMs - entry.at > AI_CACHE_TTL_MS) return true;
  if (!entry.response.pipeline_version?.trim() || !currentPipelineVersion?.trim()
    || entry.response.pipeline_version !== currentPipelineVersion) return true;
  return (
    !!entry.response.corpus_version &&
    !!currentCorpusVersion &&
    entry.response.corpus_version !== currentCorpusVersion
  );
}
function readingChanged(error: unknown): boolean {
  return !!error && typeof error === 'object' && 'code' in error && error.code === 'EMAIL_READING_CHANGED';
}
type TargetVersionFailure = 'unavailable' | 'changed';
function targetVersionFailure(error: unknown): TargetVersionFailure | null {
  if (!error || typeof error !== 'object' || !('code' in error)) return null;
  return error.code === 'WRITING_TARGET_CHANGED' || error.code === 'EMAIL_CONTACT_INSTRUCTIONS' ? 'changed'
    : error.code === 'INVALID_WRITING_TARGET_RECEIPT' || error.code === 'INVALID_EMAIL_TARGET_CONDITIONS' ? 'unavailable' : null;
}
function requireTargetReceipt(response: unknown, id: string, version: string) {
  readEmailTargetConditions(response);
  if (response && typeof response === 'object' && 'variants' in response && Array.isArray(response.variants)) response.variants.forEach(readEmailTargetConditions);
  if (!response || typeof response !== 'object' || Array.isArray(response)
    || !('opportunity_id' in response) || response.opportunity_id !== id
    || !('target_version' in response) || response.target_version !== version) {
    throw Object.assign(new Error('Invalid writing target receipt'), { code: 'INVALID_WRITING_TARGET_RECEIPT' });
  }
}
async function requireContactReceipt(response: unknown, context: EmailContactContext) {
  const expected = { purpose: context.purpose, context_sig: await emailContactContextSignature(context) };
  requireEmailContactContextReceipt(response, expected);
  if (response && typeof response === 'object' && 'variants' in response && Array.isArray(response.variants)) {
    for (const variant of response.variants) requireEmailContactContextReceipt(variant, expected);
  }
}
const STYLE_KEYS: readonly EmailStyle[] = ['professional', 'warm', 'friendly', 'lively'];

interface ColdEmailModalProps {
  isOpen: boolean;
  targetReady?: boolean;
  targetChecking?: boolean;
  /** False keeps the open draft; the retained profile is not current material. */
  profileAvailable?: boolean;
  profileRefresh?: ProfileRefreshState;
  target?: Opportunity | null;
  targetRefresh?: WritingTargetState;
  targetMembershipReady?: boolean;
  onClose: () => void;
  profile: ProfileData;
  opportunityId: string;
  opportunityTitle: string;
  /** Slug of the opportunity's host school — lets the no-email explainer link
   *  the student to their campus' official self-lookup directory. */
  opportunitySchool?: string | null;
  /**
   * The canonical record this dialog is about, as the caller currently sees
   * it — used for one thing only: deciding whether a follow-up reminder would
   * actually be delivered.
   *
   * Optional, and `undefined` FAILS CLOSED — no chips, no write. That is the
   * honest reading of "the caller cannot presently prove anything about this
   * target": a results refetch in flight, the row gone from the page, or a
   * caller that never supplied one. All three production call sites pass it
   * explicitly; a test that omits it simply gets no follow-up controls, which
   * is the correct default rather than something to paper over.
   *
   * `id` is required and must equal `opportunityId`. A caller resolving the
   * row by a stale id — a results list mid-swap, a favorites page whose
   * modal id moved on — would otherwise hand over a perfectly live record
   * that describes a DIFFERENT target, and this dialog would write a
   * reminder for it.
   */
  reminderTarget?: NonNullable<Parameters<typeof canDeliverReminder>[0]> & { id: string };
  /**
   * Called with the row the confirmation actually wrote, so the surface that
   * opened this dialog can stop contradicting it.
   *
   * The write is atomic and this dialog owns it, but the host page's own
   * interaction read re-runs only on mount and on a real identity change —
   * closing the modal triggers neither. Without this the detail page shows
   * "Pick a status above first" and a disabled notes box for a contact it just
   * recorded, and the results list keeps the pre-contact chip for the session.
   *
   * Fires only inside the same post-await ownership check that paints the
   * confirmed state, so a confirmation released after the owner moved tells
   * the caller nothing, exactly as it paints nothing.
   */
  onContactConfirmed?: (record: InteractionRecord | null) => void;
  /** The follow-up chips write remind_at straight to the row. Without this the
   *  page that owns the tracker panel never learns, so its date field renders
   *  empty and its status-change suggestion — gated on remind_at being unset —
   *  offers to set a reminder that already exists, overwriting it on one
   *  click. */
  onReminderSet?: (date: string) => void;
}

/*
 * Schools whose faculty emails we cannot (or may not) harvest, but whose
 * OFFICIAL directory lets the student look one up themselves — with their own
 * campus login where required. Individual lookup is exactly the use these
 * directories permit (UW's directory ToS restricts bulk/commercial use, which
 * is why we don't harvest it — but the student searching one professor is the
 * intended use).
 */
const SELF_LOOKUP_DIRECTORIES: Record<string, { name: string; url: string }> = {
  uw: { name: 'UW Directory', url: 'https://directory.uw.edu/' },
  umich: { name: 'MCommunity', url: 'https://mcommunity.umich.edu/' },
  princeton: { name: 'Princeton Directory', url: 'https://directory.princeton.edu/' },
  stanford: { name: 'Stanford Directory', url: 'https://stanfordwho.stanford.edu/' },
};

interface ChatMessage {
  requestId?: number;
  role: 'user' | 'assistant';
  content: string;
}

const QUICK_ACTION_KEYS = ['formal', 'shorter', 'enthusiastic', 'coursework'] as const;
type QuickActionKey = typeof QUICK_ACTION_KEYS[number];

// Pipeline-stage labels shown inside the AI pill while streaming — the
// multi-call pipeline takes noticeably longer than the old single call, so
// the UI says WHICH stage is running instead of one opaque spinner.
const STAGE_LABEL_KEYS: Record<ColdEmailStage, string> = {
  drafting: 'coldEmail.stageDrafting',
  judging: 'coldEmail.stageJudging',
  critiquing: 'coldEmail.stageCritiquing',
  revising: 'coldEmail.stageRevising',
};

type Replier = (path: string, vars?: Record<string, string | number>) => string;

// The backend 422s every cold-email entry point with this error code when the
// profile has no name (emails must never go out addressed from "Student").
// Structured API errors retain the Pydantic error code without exposing the
// full validation body to the UI. Legacy/custom callers are tolerated too.
function isStudentNameRequiredError(err: unknown): boolean {
  return (
    typeof err === 'object'
    && err !== null
    && 'code' in err
    && err.code === 'student_name_required'
  ) || (
    err instanceof Error
    && err.message.includes('student_name_required')
  );
}

// R72-A: pick the truthful fallback outcome for both generation and refine.
// 'fabrication' means a model result was rejected; 'insufficient_evidence'
// means the evidence gate rebuilt a safe template without running AI. Neither
// may be described as a provider outage or a routine local tone edit.
function aiFallbackMessage(
  reason: ColdEmailFallbackReason | null | undefined,
  t: Replier,
): string {
  if (reason === 'fabrication') return t('coldEmail.aiFallbackFabrication');
  if (reason === 'insufficient_evidence') return t('coldEmail.aiFallbackInsufficientEvidence');
  if (reason === 'not_configured') return t('coldEmail.aiFallback');
  return t('coldEmail.aiFallbackGeneric');
}

// Tone quick-actions (formal / shorter / enthusiastic) are canned refine
// instructions routed through POST /cold-email/refine — the backend's
// email_modes.EDIT_OPS registry is the single source of tone truth (LLM when
// configured, its deterministic edit ops otherwise). Keeping a client-side
// tone table here was the third copy of those semantics and had already
// drifted from the backend's.
const QUICK_ACTION_INSTRUCTIONS: Record<Exclude<QuickActionKey, 'coursework'>, string> = {
  formal: 'Make it more formal and professional',
  shorter: 'Make it shorter and more concise',
  enthusiastic: 'Make it more enthusiastic',
};

// Pre-W10b cached/skewed responses lack recipient_status; a present address
// means it was revealed, an absent one means there is nothing to offer.
function statusOf(
  status: ContactEmailStatus | undefined,
  email: string,
): ContactEmailStatus {
  return status ?? (email ? 'revealed' : 'unavailable');
}

// Coursework stays client-side: it inserts the student's own courses verbatim
// (naturally grounded), so a network round-trip buys nothing.
function applyQuickEdit(
  body: string,
  action: QuickActionKey,
  profile: ProfileData,
  t: Replier,
): { body: string; reply: string } {
  switch (action) {
    case 'coursework': {
      const courses = profile.coursework ?? [];
      if (courses.length === 0) {
        return { body, reply: t('coldEmail.replies.courseworkNone') };
      }
      const courseStr = courses.join(', ');
      const insertion = `\n\nI have completed relevant coursework including ${courseStr}.`;
      if (body.length + insertion.length > COLD_EMAIL_DRAFT_LIMITS.body) {
        return { body, reply: t('profileInput.courseworkTooLarge') };
      }
      // FE-4: insert before the sign-off. The template closes with "Best
      // regards"/"Respectfully", but an AI draft can drift to "Sincerely",
      // "Warm regards", etc. — matching only Best/Respectfully appended the line
      // BELOW the signature in that case. Match a broad set of closings and use
      // the last one.
      const closingRe = /\n\n(?:Best regards|Best|Sincerely|Respectfully|Warm(?:est)? regards|Warmly|Kind regards|Regards|Thank you|Thanks|Cheers)\b/gi;
      let insertAt = -1;
      for (const m of body.matchAll(closingRe)) {
        if (m.index !== undefined) insertAt = m.index;
      }
      const reply = t('coldEmail.replies.courseworkAdded', { list: courseStr });
      if (insertAt > 0) {
        return {
          body: body.slice(0, insertAt) + insertion + body.slice(insertAt),
          reply,
        };
      }
      return { body: body + insertion, reply };
    }
    default:
      return { body, reply: t('coldEmail.replies.noChanges') };
  }
}

export default function ColdEmailModal({
  isOpen,
  onClose,
  profile: incomingProfile,
  opportunityId,
  opportunityTitle,
  opportunitySchool,
  reminderTarget,
  onContactConfirmed,
  onReminderSet,
  targetReady = true,
  targetChecking = false,
  profileAvailable = true,
  profileRefresh,
  target,
  targetRefresh,
  targetMembershipReady,
}: ColdEmailModalProps) {
  const { t, locale } = useT();
  const incomingProfileKey = profileActionKey(incomingProfile);
  const [supplementProfile, setSupplementProfile] = useState<{ view: ProfileViewSnapshot; inputKey: string | null; targetId: string } | null>(null);
  const profile = profileAvailable && supplementProfile && supplementProfile.inputKey === incomingProfileKey
    && supplementProfile.targetId === opportunityId && isOwnerTokenValid(supplementProfile.view.token, supplementProfile.view.token.uid)
    ? supplementProfile.view.renderedProfile : incomingProfile;
  const [supplementSession, setSupplementSession] = useState<{ owner: ReturnType<typeof captureOwnerToken>; targetId: string; inputKey: string | null } | null>(null);
  const [supplementExpanded, setSupplementExpanded] = useState(false);
  const supplementScopeRef = useRef(supplementSession);
  const supplementInputRef = useRef({ key: incomingProfileKey, available: profileAvailable && isOpen, targetId: opportunityId });
  useLayoutEffect(() => {
    if (!profileAvailable || supplementInputRef.current.key !== incomingProfileKey) setSupplementProfile(null);
    supplementScopeRef.current = supplementSession;
    supplementInputRef.current = { key: incomingProfileKey, available: profileAvailable && isOpen, targetId: opportunityId };
  }, [supplementSession, incomingProfileKey, profileAvailable, isOpen, opportunityId]);

  const contactPolicyBlock = contactEmailBlock(target);
  const expectedTargetVersion = isPublicDetail(target, opportunityId) ? writingTargetVersion(target) : null;
  const sourceReady = profileAvailable && targetReady && profileRefreshReady(profileRefresh) && (!targetRefresh || targetRefresh.status === 'ready');
  const sourceReadyRef = useRef(sourceReady);
  useLayoutEffect(() => { sourceReadyRef.current = sourceReady; }, [sourceReady]);
  const { openModal } = useAuthModal();
  // Bind requests and cache lifetime to all factual inputs, including entry
  // status/revision/source changes and an in-place profile update by a caller.
  const profileFingerprint = JSON.stringify(profile);
  // A list refresh may temporarily withdraw the target. That is unknown,
  // not a change to its facts. Keep the last observed content for comparison.
  const [knownTarget, setKnownTarget] = useState({ id: opportunityId, fingerprint: JSON.stringify(target ?? reminderTarget ?? null) });
  const targetFingerprint = target || reminderTarget ? JSON.stringify(target ?? reminderTarget)
    : knownTarget.id === opportunityId ? knownTarget.fingerprint : 'null';
  if (knownTarget.id !== opportunityId || knownTarget.fingerprint !== targetFingerprint) {
    setKnownTarget({ id: opportunityId, fingerprint: targetFingerprint });
  }
  const [contactState, setContactState] = useState(() => ({
    id: opportunityId, value: defaultEmailContactContext(), revision: 0, dirty: false,
  }));
  // Stamp private background to its target before the new target can request.
  const effectiveContact = contactState.id === opportunityId ? contactState : {
    id: opportunityId, value: defaultEmailContactContext(), revision: 0, dirty: false,
  };
  if (contactState.id !== opportunityId) setContactState(effectiveContact);
  const contactSerialized = serializeEmailContactContext(effectiveContact.value);
  const requestContactContext = useMemo(() => JSON.parse(contactSerialized) as EmailContactContext, [contactSerialized]);
  const paperReadingCurrent = isEmailPaperReadingCurrent(requestContactContext, target);
  const contextDirty = effectiveContact.dirty;
  const contextDirtyRef = useRef(contextDirty);
  useLayoutEffect(() => { contextDirtyRef.current = contextDirty; }, [contextDirty]);
  // Once the user opens a background edit, only an explicit new-draft action
  // may generate, including when the first response has not arrived yet.
  const contextEditedRef = useRef(false);
  const [contextChanged, setContextChanged] = useState(false);
  const [readingReview, setReadingReview] = useState(0);
  const [readingReviewRequired, setReadingReviewRequired] = useState(false);
  const retireContactDraftRef = useRef<() => void>(() => {});
  const reportReadingChange = useCallback(() => {
    retireContactDraftRef.current();
    setReadingReviewRequired(true); setReadingReview(value => value + 1);
  }, []);
  const contactFingerprint = `${effectiveContact.revision}\n${contactSerialized}`;
  const materialFingerprint = `${profileFingerprint}\n${targetFingerprint}\n${contactFingerprint}`;
  const requestProfile = useMemo(() => JSON.parse(profileFingerprint) as ProfileData, [profileFingerprint]);
  const draftSourcesRef = useRef<{ profile: string; target: string | null; contact: string } | null>(null);
  const draftPayloadRef = useRef<ColdEmailDraftPayload>(null!);
  const userActionRevisionRef = useRef(0);
  const versionSaveBaseRef = useRef<{ edit: number; draft: number; material: string } | null>(null);
  const draftPersistence = useColdEmailDraftPersistence();
  const { open: openPersistedDraft, persist: persistDraft, flush: flushDraft, clear: clearPersistedDraft,
    detach: detachDraft, abandon: abandonDraft, markUnsaved: markDraftUnsaved, commit: commitDraft } = draftPersistence;
  const [draftResetKey, setDraftResetKey] = useState(0);
  const [draftRestored, setDraftRestored] = useState(false);
  const [metadataRefreshing, setMetadataRefreshing] = useState(false);
  const metadataRefreshingRef = useRef(false);
  const [savedVersions, setSavedVersions] = useState<ColdEmailDraftVersion[]>([]);
  const [versionBusy, setVersionBusy] = useState(false);
  const versionBusyRef = useRef(false);
  const versionActionRef = useRef(0);
  const versionPendingRef = useRef<Promise<void> | null>(null);
  const [versionError, setVersionError] = useState<string | null>(null);
  const [versionCompare, setVersionCompare] = useState<{ version: ColdEmailDraftVersion; base: EmailEditBase } | null>(null);
  const [sourceReview, setSourceReview] = useState<'pending' | 'matched' | 'changed' | 'unknown'>('pending');
  const changeDraftRef = useRef<(next: Partial<ColdEmailDraftPayload>, reason: ColdEmailDraftVersion['reason'], current: () => boolean, apply: () => void) => Promise<boolean>>(async () => false);
  const [draftClosing, setDraftClosing] = useState(false);
  const [persistenceSession, setPersistenceSession] = useState(0);
  const persistenceSessionRef = useRef(0);
  const [pendingPanel, setPendingPanel] = useState<EmailContactDraftSnapshot | null>(null);
  const [panelSavable, setPanelSavable] = useState(true);
  const lastSupplementSnapshotRef = useRef<string | null>(null);
  const [pendingSupplement, setPendingSupplement] = useState<ResumeSupplementDraftSnapshot | null>(null);
  const [supplementSavable, setSupplementSavable] = useState(true);
  const [restoredSources, setRestoredSources] = useState<ColdEmailDraftSources | null>(null);
  const [originKey, setOriginKey] = useState<string | null>(null);
  const [sourceSignatures, setSourceSignatures] = useState<{ key: string; value: ColdEmailDraftSources } | null>(null);
  const persistCurrentRef = useRef<() => void>(() => {});
  const readyNavigationRef = useRef<HTMLAnchorElement | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [targetVersionError, setTargetVersionError] = useState<TargetVersionFailure | null>(null);
  // Missing sender identity is its own state (not a generic error): the fix is
  // "add your name to your profile", so the UI links there instead of offering
  // a pointless retry.
  const [nameRequired, setNameRequired] = useState(false);
  const missingStudentName = !(profile.name ?? '').trim();
  const [variants, setVariants] = useState<EmailVariant[]>([]);
  const [aiVariant, setAiVariant] = useState<EmailVariant | null>(null);
  const [aiLoading, setAiLoading] = useState(false);
  // Which pipeline stage the streaming generation is in (null = not streaming
  // or stage unknown); drives the AI pill's progress label.
  const [aiStage, setAiStage] = useState<ColdEmailStage | null>(null);
  const [activeVariant, setActiveVariant] = useState(0);
  const [labType, setLabType] = useState<LabType | null>(null);
  // Voice overlay for the AI draft. `selectedStyle` seeds from the lab-type
  // recommendation once variants load; the picker re-generates on change.
  const [selectedStyle, setSelectedStyle] = useState<EmailStyle>('professional');
  const [recommendedStyle, setRecommendedStyle] = useState<EmailStyle | null>(null);

  const [subject, setSubject] = useState('');
  const [subjectFormatConfirmation, setSubjectFormatConfirmation] = useState<{ subject: string; version: string } | null>(null);
  const subjectFormatConfirmed = !!subjectFormatConfirmation && subjectFormatConfirmation.subject === subject
    && subjectFormatConfirmation.version === expectedTargetVersion;
  if (subjectFormatConfirmation && !subjectFormatConfirmed) setSubjectFormatConfirmation(null);
  const [body, setBody] = useState('');
  const [recipient, setRecipient] = useState('');
  const recipientEditedRef = useRef(false);
  const [actualSentAt, setActualSentAt] = useState('');
  // W10b contact bar: why the To field is (or isn't) prefilled. 'sign_in_required'
  // renders the sign-in-to-reveal affordance; 'unavailable' the honest
  // no-verified-address state. Pre-W10b cached responses lack the field —
  // derive from whether an address arrived.
  const [recipientStatus, setRecipientStatus] = useState<ContactEmailStatus>('unavailable');
  // Evidence honesty (one value per opportunity, from the backend): when the
  // posting carries no research signal at all, every draft is necessarily
  // generic, and presenting one as tailored would be a lie. Absent field
  // (older cached responses) ⇒ 'specific', the pre-existing behaviour.
  const [grounding, setGrounding] = useState<'specific' | 'no_target_data'>('specific');
  // How current the corpus record behind this draft is. The backend has
  // always computed and shipped it ("the UI must not present the draft as
  // current outreach" — _source_freshness) and nothing read it, so a draft to
  // a professor whose record was retired looked identical to one to a
  // currently-listed professor. Default 'unknown' shows nothing: an older
  // cached response without the field must not manufacture a warning OR a
  // false all-clear.
  const [experienceUsage, setExperienceUsage] = useState<ExperienceUsage | null>(null);
  const [targetConditions, setTargetConditions] = useState<EmailTargetConditions | null>(null);
  const [conditionCheck, setConditionCheck] = useState<{ key: string; issues: EmailConditionIssue[]; message?: string } | null>(null);
  const [experienceNeedsReview, setExperienceNeedsReview] = useState(false);
  const experienceBudgetOmission = experienceUsage?.notices.some((notice) =>
    notice === 'experience_prompt_budget_omission' || notice === 'experience_template_budget_omission',
  ) ?? false;
  const experienceReceiptLimited = experienceUsage?.notices.includes('experience_usage_receipt_limit') ?? false;
  const [freshness, setFreshness] =
    useState<'fresh' | 'stale' | 'inactive' | 'unknown'>('unknown');
  const [copiedFor, setCopiedFor] = useState<{ contents: string; backup: boolean } | null>(null);
  const [copyFailedFor, setCopyFailedFor] = useState<string | null>(null);
  // Copying/opening a draft only REVEALS the follow-up strip — it is not
  // evidence the email was sent (the user may close the compose window), so
  // nothing is recorded yet. Only the explicit "I sent it" confirmation below
  // creates the interaction — as 'contacted', since a send is outreach and
  // not an application claim made on the student's behalf; the reminder chips
  // then follow, when the returned status is one the cron actually sends for.
  const [contacted, setContacted] = useState(false);
  const contactedOwnerRef = useRef<ReturnType<typeof captureOwnerToken> | null>(null);
  // Same stamping as confirmedForId below, for the same reason: the
  // copy/open strip must not carry A's "did you send it?" question onto B.
  const [contactedForId, setContactedForId] = useState<string | null>(null);
  const [sendDraftEpoch, setSendDraftEpoch] = useState(0);
  const sendDraftEpochRef = useRef(0);
  // Clipboard feedback belongs to the exact displayed draft, independently
  // of whether an edit starts a new send-confirmation epoch.
  const copyContentKey = JSON.stringify([subject, body, recipient, sendDraftEpoch]);
  const copyContentKeyRef = useRef(copyContentKey);
  useLayoutEffect(() => { copyContentKeyRef.current = copyContentKey; }, [copyContentKey]);
  const copied = copiedFor?.contents === copyContentKey && !copiedFor.backup;
  const backupCopied = copiedFor?.contents === copyContentKey && copiedFor.backup;
  const copyFailed = copyFailedFor === copyContentKey;
  const [contactedDraftEpoch, setContactedDraftEpoch] = useState<number | null>(null);
  const [confirmedDraftEpoch, setConfirmedDraftEpoch] = useState<number | null>(null);
  const [contactedContentKey, setContactedContentKey] = useState<string | null>(null);
  const [confirmedContentKey, setConfirmedContentKey] = useState<string | null>(null);
  const confirmationKey = JSON.stringify([copyContentKey, actualSentAt]);
  const confirmationKeyRef = useRef(confirmationKey);
  useLayoutEffect(() => { confirmationKeyRef.current = confirmationKey; }, [confirmationKey]);
  const contactedHere = contacted && contactedForId === opportunityId && contactedDraftEpoch === sendDraftEpoch
    && contactedContentKey === copyContentKey;
  const [sendConfirmed, setSendConfirmed] = useState(false);
  const [followUpDate, setFollowUpDate] = useState<string | null>(null);
  // The reminders cron has a third filter the reminder controls never checked:
  // a channel to reach this student. push.py counts `no_channel` when there is
  // no push_subscriptions row for the device AND _account_email returns None,
  // which is always true for an anonymous one. Those students still get the
  // reminder — it renders on the Tracker card and flips to "Follow-up due" —
  // but nothing arrives outside the app, and nothing offered to change that.
  // null = not determined yet; the offer stays hidden until it is known.
  const [pushOffer, setPushOffer] = useState<'available' | 'subscribed' | null>(null);
  const [pushBusy, setPushBusy] = useState(false);
  // The status the confirm RPC actually landed on. It is an upsert that
  // PRESERVES an existing status, so a row already marked rejected or
  // dismissed stays that way — and the reminders cron never selects those.
  // Assuming 'contacted' here is how a confirmed send still produced a
  // reminder nothing would ever deliver.
  const [confirmedStatus, setConfirmedStatus] = useState<InteractionType | undefined>();
  // Which opportunity that status belongs to. The reset below is a passive
  // effect, so between a rerender onto target B and that cleanup flushing,
  // A's confirmation would already have painted B's chips — and the handler
  // would have written against them. Stamping the id at creation makes the
  // state unusable for anyone else by construction rather than by timing.
  const [confirmedForId, setConfirmedForId] = useState<string | null>(null);
  const confirmedHere = sendConfirmed && confirmedForId === opportunityId && confirmedDraftEpoch === sendDraftEpoch
    && confirmedContentKey === confirmationKey;
  // Identity first, then deliverability. A live record for a different id is
  // still a live record — canDeliverReminder would happily say yes to it.
  const followUpDeliverable = confirmedHere
    && reminderTarget?.id === opportunityId
    && canDeliverReminder(reminderTarget, confirmedStatus);
  const [confirming, setConfirming] = useState(false);
  // Which persistence outcome could not be confirmed. A rejected response
  // does not prove that the server wrote nothing; a failed reminder also does
  // not undo a confirmed contact. An owner move must not report the old
  // operation as success for the current account. Errors belong to this session AND
  // draft epoch: rebuilding clears them, and old writers cannot restore them.
  type SendError = 'confirm' | 'reminder' | 'owner-changed' | 'invalid-contact' | 'contact-conflict';
  const [sendFailure, setSendFailure] = useState<{ key: string; error: SendError } | null>(null);
  const sendError = sendFailure?.key === confirmationKey ? sendFailure.error : null;
  const setSendError = useCallback((error: SendError | null) => {
    setSendFailure(error ? { key: confirmationKeyRef.current, error } : null);
  }, []);

  const allVariants: EmailVariant[] = aiVariant ? [...variants, aiVariant] : variants;

  const bodyInputRef = useRef<HTMLTextAreaElement>(null);
  const [invalidSelection, setInvalidSelection] = useState(false);
  const [scopeNeedsChoice, setScopeNeedsChoice] = useState(false);
  const [selection, setSelection] = useState<{ body: string; range: EmailTextSelection } | null>(null);
  const [editProposal, setEditProposal] = useState<EmailEditProposal | null>(null);
  const proposalRef = useRef<EmailEditProposal | null>(null);
  const [editUndo, setEditUndo] = useState<EmailEditUndo | null>(null);
  const undoRef = useRef<EmailEditUndo | null>(null);
  const clearEmailRevisions = useCallback(() => {
    proposalRef.current = null; undoRef.current = null;
    setEditProposal(null); setEditUndo(null); setSelection(null); setInvalidSelection(false); setScopeNeedsChoice(false);
  }, []);
  const discardProposal = () => { proposalRef.current = null; setEditProposal(null); };

  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
  const [chatInput, setChatInput] = useState('');
  const [userEditRevision, setUserEditRevision] = useState(0);
  const [composeBusy, setComposeBusy] = useState(false);
  const [composeFailure, setComposeFailure] = useState<ComposeFailure | null>(null);
  const composeRef = useRef<PendingCompose | null>(null);
  const composeSequence = useRef(0);
  const composeActionCancelRef = useRef<() => void>(() => {});
  const composeKey = JSON.stringify([opportunityId, materialFingerprint, copyContentKey, userEditRevision]);
  const composeKeyRef = useRef(composeKey);
  const cancelCompose = useCallback((failure: ComposeFailure | null = null) => {
    const pending = composeRef.current;
    if (pending) {
      composeRef.current = null;
      clearTimeout(pending.deadline); pending.controller.abort();
      composeActionCancelRef.current();
      try { pending.popup?.close(); } catch { /* Already closed or inaccessible. */ }
    }
    setComposeBusy(false); setComposeFailure(failure);
  }, []);
  useLayoutEffect(() => {
    composeKeyRef.current = composeKey;
    if (composeRef.current && composeRef.current.key !== composeKey) cancelCompose();
  }, [composeKey, cancelCompose]);
  useEffect(() => () => cancelCompose(), [cancelCompose]);
  const noteUserEdit = () => { userActionRevisionRef.current += 1; discardProposal(); cancelCompose(); setUserEditRevision((value) => value + 1); };
  const [refining, setRefining] = useState(false);
  const [retired, setRetired] = useState(false);
  const [profileChanged, setProfileChanged] = useState(false);
  // Layout can flush a queued intent before its state update is rendered.
  // Retire the old draft synchronously before that executor can consume it.
  const profileChangedRef = useRef(false);
  const [profileRegenerating, setProfileRegenerating] = useState(false);
  const [profileRegenerateError, setProfileRegenerateError] = useState<'failed' | 'edited' | 'name-required' | null>(null);
  const chatHistoryRef = useRef<HTMLDivElement>(null);
  const modalRef = useRef<HTMLDivElement>(null);
  const previouslyFocusedRef = useRef<HTMLElement | null>(null);
  // AI is the default engine: one automatic pipeline run per open, kicked off
  // once the template variants land. Reset on close.
  const autoFiredRef = useRef(false);
  // A failed receipt may be checked again without spending generation or
  // replacing a draft. Only an explicit generation intent clears this fence.
  const targetCheckOnlyRef = useRef(false);
  // Real AI drafts per (opportunity, style): reopening the same opportunity
  // reuses the draft instead of re-billing the pipeline. Fallback responses
  // are never cached (they retry on the next open). Cleared when the profile
  // prop changes — a draft must not outlive a profile edit. W12: entries
  // also expire after AI_CACHE_TTL_MS and whenever the backend's
  // corpus_version or pipeline_version moves, so a long-lived tab does not
  // reuse superseded research or writing rules.
  const aiCacheRef = useRef<Map<string, { response: ColdEmailResponse; at: number }>>(new Map());
  const corpusVersionRef = useRef<string | null>(null);
  // Only the current session's variants may set the comparison version. An
  // AI response may come from an older worker; it cannot certify itself.
  const pipelineVersionRef = useRef<string | null>(null);
  // A target change flushes old passive effects after layout cleanup. They
  // must not start AI from the previous render's variants/loading values.
  const variantsReadyRef = useRef(false);
  // Which send session an in-flight persistence belongs to. Bumped on every
  // close and every target change, so a completion that comes back after the
  // modal moved on can be identified as belonging to a session that no longer
  // exists. An immutable number, not object identity: the modal stays mounted
  // across open/close and target switches, so there is no object to compare.
  const sendSessionRef = useRef(0);
  // Material changes retire writing, but are not a new contact/target session.
  const profileSessionRef = useRef(0);
  const sessionProfileRef = useRef(materialFingerprint);
  // Which confirmation attempt within that session. A retry supersedes the
  // attempt it retried, so a straggler cannot paint over the newer answer.
  const confirmAttemptRef = useRef(0);
  // One atomic call per attestation: held for the duration of the round trip
  // and released by whoever set it, so a double click cannot open a second.
  const confirmInFlightRef = useRef(false);
  const draftRevisionRef = useRef(0);
  const editorUsedRef = useRef(false);
  const variantRequestRef = useRef(0);
  const aiRequestRef = useRef(0);
  const aiInFlightRef = useRef(false);
  const refineRequestRef = useRef(0);
  const refineInFlightRef = useRef<number | null>(null);

  const editLiveRef = useRef({ body, subject, recipient, material: materialFingerprint });
  useLayoutEffect(() => { editLiveRef.current = { body, subject, recipient, material: materialFingerprint }; });
  const captureEditBase = (): EmailEditBase => ({ body, subject, recipient, material: materialFingerprint,
    revision: draftRevisionRef.current, session: sendSessionRef.current, owner: captureOwnerToken() });
  const editBaseCurrent = (base: EmailEditBase) => {
    const live = editLiveRef.current;
    return isOpen && !retired && isOwnerTokenValid(base.owner, base.owner.uid)
      && base.session === sendSessionRef.current && base.revision === draftRevisionRef.current
      && base.material === live.material && base.body === live.body && base.subject === live.subject && base.recipient === live.recipient;
  };
  /* eslint-disable react-hooks/set-state-in-effect, react-hooks/exhaustive-deps --
     Retire edit capabilities on every committed render, including owner-storage
     notifications and ref-only lifecycle counters. Each guard clears its ref
     before setting state, so retirement schedules at most one extra render. */
  useLayoutEffect(() => {
    // Comparing revisions also rejects editing away and back to the same text.
    if (proposalRef.current && (!editBaseCurrent(proposalRef.current.base) || contextDirty || targetVersionError)) {
      proposalRef.current = null; setEditProposal(null);
    }
    if (undoRef.current && (!editBaseCurrent(undoRef.current.base) || contextDirty)) {
      undoRef.current = null; setEditUndo(null);
    }
    if (selection && selection.body !== body) { setSelection(null); setScopeNeedsChoice(true); }
    if (versionCompare && !editBaseCurrent(versionCompare.base)) setVersionCompare(null);
  });
  /* eslint-enable react-hooks/set-state-in-effect, react-hooks/exhaustive-deps */

  const captureDraftSession = useCallback(() => {
    const session = sendSessionRef.current;
    const materials = profileSessionRef.current;
    const owner = captureOwnerToken();
    return () => sourceReadyRef.current && !contextDirtyRef.current && sendSessionRef.current === session && profileSessionRef.current === materials && isTokenOwnerStillCurrent(owner);
  }, []);

  const finishClose = useCallback(() => {
    cancelCompose();
    sendSessionRef.current += 1;
    setRetired(true);
    onClose();
  }, [onClose, cancelCompose]);
  const pauseWritingForNavigation = useCallback(() => {
    // Save the scope before retiring in-flight capabilities. A navigation attempt
    // must not silently turn a selected request into a whole-body request.
    persistCurrentRef.current();
    versionActionRef.current += 1; versionBusyRef.current = false; setVersionBusy(false);
    proposalRef.current = null; undoRef.current = null;
    setEditProposal(null); setEditUndo(null); setVersionCompare(null);
    supplementScopeRef.current = null;
    composeActionCancelRef.current();
    cancelCompose();
    profileSessionRef.current += 1;
    variantRequestRef.current += 1; aiRequestRef.current += 1;
    aiInFlightRef.current = false;
    const refine = refineInFlightRef.current; refineInFlightRef.current = null;
    setAiLoading(false); setAiStage(null); setRefining(false); setProfileRegenerating(false);
    if (refine !== null) setChatMessages(messages => messages.map(message =>
      message.requestId === refine ? { ...message, content: t('coldEmail.profileEditRetired') } : message));
  }, [cancelCompose, t]);
  const closeDraft = useCallback(() => {
    pauseWritingForNavigation();
    persistCurrentRef.current();
    const owner = captureOwnerToken();
    const revision = draftRevisionRef.current;
    const session = sendSessionRef.current;
    setDraftClosing(true);
    void Promise.resolve(versionPendingRef.current).then(() => flushDraft()).then(saved => {
      if (session !== sendSessionRef.current || !isTokenOwnerStillCurrent(owner)) return;
      setDraftClosing(false);
      if (saved && revision === draftRevisionRef.current) finishClose();
      else supplementScopeRef.current = supplementSession;
    });
  }, [flushDraft, finishClose, pauseWritingForNavigation, supplementSession]);
  const leaveForProfile = useCallback((event: MouseEvent<HTMLAnchorElement>) => {
    const anchor = event.currentTarget;
    if (readyNavigationRef.current === anchor) {
      readyNavigationRef.current = null; finishClose(); return true;
    }
    event.preventDefault();
    pauseWritingForNavigation();
    persistCurrentRef.current();
    const owner = captureOwnerToken();
    const session = sendSessionRef.current;
    const revision = draftRevisionRef.current;
    setDraftClosing(true);
    void Promise.resolve(versionPendingRef.current).then(() => flushDraft()).then(saved => {
      if (session !== sendSessionRef.current || !isTokenOwnerStillCurrent(owner)) return;
      setDraftClosing(false);
      if (saved && revision === draftRevisionRef.current && anchor.isConnected) {
        readyNavigationRef.current = anchor; anchor.click();
      } else supplementScopeRef.current = supplementSession;
    });
    return false;
  }, [flushDraft, finishClose, pauseWritingForNavigation, supplementSession]);

  // The epoch changes synchronously, before a parent's new profile reaches
  // this dialog. End the old draft session instead of generating with that
  // old profile under the next account. Same-owner token refresh is harmless.
  useEffect(() => {
    const owner = captureOwnerToken();
    return onLocalOwnerStateChange(() => {
      if (isTokenOwnerStillCurrent(owner)) return;
      sendSessionRef.current += 1;
      aiCacheRef.current.clear();
      if (isOpen) {
        abandonDraft(); finishClose();
      }
    });
  }, [isOpen, finishClose, abandonDraft]);

  useLayoutEffect(() => { aiCacheRef.current.clear(); }, [materialFingerprint]);

  const reportTargetVersionFailure = useCallback((failure: TargetVersionFailure) => {
    // Reveal can fail concurrently with AI/refine. Retire every writing
    // callback synchronously, not the human editor or confirmed send state.
    profileSessionRef.current += 1;
    variantRequestRef.current += 1; aiRequestRef.current += 1;
    const retiredRefine = refineInFlightRef.current;
    refineInFlightRef.current = null; aiInFlightRef.current = false;
    setLoading(false); setAiLoading(false); setAiStage(null);
    setRefining(false); setProfileRegenerating(false);
    if (retiredRefine !== null) setChatMessages(messages => messages.map(message =>
      message.requestId === retiredRefine ? { ...message, content: t('coldEmail.editFailed') } : message));
    targetCheckOnlyRef.current = true;
    variantsReadyRef.current = false;
    aiCacheRef.current.clear();
    setTargetVersionError(failure);
  }, [t]);

  const fetchVariants = useCallback(async (preserveDraft = false, keepEditor = false) => {
    if (!sourceReadyRef.current || contextDirtyRef.current) return;
    if (contactPolicyBlock) { setError(contactInstructionCopy[locale][contactPolicyBlock]); setLoading(false); return; }
    if (!paperReadingCurrent) { setError(locale === 'zh' ? '已确认的论文不再属于当前资料，请重新核对阅读信息。' : 'The confirmed paper is no longer in the current source. Review your reading details.'); setLoading(false); return; }
    const sessionCurrent = captureDraftSession();
    const request = ++variantRequestRef.current;
    const current = () => sessionCurrent() && request === variantRequestRef.current;
    const revision = draftRevisionRef.current;
    if (!preserveDraft) variantsReadyRef.current = false;
    if (!expectedTargetVersion) { reportTargetVersionFailure('unavailable'); setLoading(false); return; }
    if (missingStudentName) {
      setLoading(false);
      if (keepEditor) setProfileRegenerateError('name-required');
      else setNameRequired(true);
      return;
    }
    if (keepEditor) { setProfileRegenerating(true); setProfileRegenerateError(null); }
    else if (!preserveDraft) setLoading(true);
    setError(null);
    setNameRequired(false);
    try {
      const data = await getEmailVariants(requestProfile, opportunityId, undefined, { expectedTargetVersion, contactContext: requestContactContext });
      if (!current()) return;
      requireTargetReceipt(data, opportunityId, expectedTargetVersion);
      await requireContactReceipt(data, requestContactContext);
      if (!current()) return;
      if (data.variants.length === 0) throw new Error(t('coldEmail.failedGenerate'));
      if (keepEditor && revision !== draftRevisionRef.current) {
        setProfileRegenerateError('edited');
        return;
      }
      if (keepEditor) {
        const first = data.variants[0];
        if (!await changeDraftRef.current({ subject: first.subject, body: first.body, selectedStyle: data.recommended_style ?? draftPayloadRef.current.selectedStyle },
          'regenerated', () => current() && revision === draftRevisionRef.current, () => {})) return;
        if (!current() || revision !== draftRevisionRef.current) return;
      }
      variantsReadyRef.current = true;
      setTargetVersionError(null);
      setVariants(data.variants.map(variant => ({ ...variant, target_conditions: variant.target_conditions ?? data.target_conditions })));
      const inferredLabType =
        data.lab_type
        ?? (data.variants.find((v) => v.lab_type)?.lab_type ?? null);
      setLabType(inferredLabType);
      const rec = data.recommended_style ?? null;
      setRecommendedStyle(rec);
      if (rec && !preserveDraft) setSelectedStyle(rec);
      setRecipientStatus(
        statusOf(data.recipient_status, data.variants[0]?.recipient_email ?? ''),
      );
      setGrounding(data.grounding ?? 'specific');
      setFreshness(data.source_freshness ?? 'unknown');
      // W12: variants regenerate on every open, so their corpus_version is
      // the "current" mark that decides whether a cached AI draft survives.
      if (data.corpus_version) corpusVersionRef.current = data.corpus_version;
      pipelineVersionRef.current = data.pipeline_version ?? null;
      if (!preserveDraft && revision === draftRevisionRef.current && data.variants.length > 0) {
        const first = data.variants[0];
        setSubject(first.subject);
        setBody(first.body);
        draftSourcesRef.current = { profile: JSON.stringify(requestProfile), target: expectedTargetVersion, contact: serializeEmailContactContext(requestContactContext) };
        setOriginKey(JSON.stringify(draftSourcesRef.current));
        setRestoredSources(null);
        if (!keepEditor) setRecipient(first.recipient_email);
        editorUsedRef.current = true;
        setActiveVariant(0);
        setExperienceUsage(first.experience_usage ?? null);
        setTargetConditions(readEmailTargetConditions(first) ?? readEmailTargetConditions(data));
        profileChangedRef.current = false;
        setProfileChanged(false);
        contextEditedRef.current = false;
        setContextChanged(false);
        // Explicit regeneration runs the normal AI pipeline after fresh templates.
        if (keepEditor) {
          autoFiredRef.current = false;
          // A newly built draft needs its own explicit send attestation.
          // Keep the historical contact/reminder record and allow its pending
          // receipt to update the parent, without confirming this new draft.
          sendDraftEpochRef.current += 1;
          setSendDraftEpoch(sendDraftEpochRef.current);
          setActualSentAt('');
          setCopiedFor(null); setCopyFailedFor(null);
          setSendError(null);
        }
      }
      if (preserveDraft && !recipientEditedRef.current) setRecipient(data.variants[0]?.recipient_email ?? '');
      if (!preserveDraft) setChatMessages([
        { role: 'assistant', content: t('coldEmail.generated', { count: data.variants.length }) },
      ]);
    } catch (err) {
      if (!current()) return;
      const targetFailure = targetVersionFailure(err);
      const profileIssue = profileInputMessage(err, t);
      if (profileIssue) {
        if (keepEditor || preserveDraft) setChatMessages(messages => [...messages, { role: 'assistant', content: profileIssue }]);
        else setError(profileIssue);
      }
      else if (isEmailInputTooLarge(err)) {
        if (keepEditor || preserveDraft) setChatMessages(messages => [...messages, { role: 'assistant', content: emailInputTooLargeMessage(locale) }]);
        else setError(emailInputTooLargeMessage(locale));
      }
      else if (readingChanged(err)) { reportReadingChange(); }
      else if (targetFailure) { reportTargetVersionFailure(targetFailure); }
      else if (keepEditor) {
        setProfileRegenerateError(isStudentNameRequiredError(err) ? 'name-required' : 'failed');
      } else if (isStudentNameRequiredError(err)) {
        setNameRequired(true);
      } else {
        setError(err instanceof Error ? err.message : t('coldEmail.failedGenerate'));
      }
    } finally {
      if (current()) {
        if (preserveDraft || keepEditor) { metadataRefreshingRef.current = false; setMetadataRefreshing(false); }
        if (keepEditor) setProfileRegenerating(false);
        else if (!preserveDraft) setLoading(false);
      }
    }
  }, [contactPolicyBlock, paperReadingCurrent, locale, requestProfile, requestContactContext, opportunityId, expectedTargetVersion, t, missingStudentName, captureDraftSession, reportTargetVersionFailure, reportReadingChange, setSendError]);

  type WritingIntent = { kind: 'variants'; preserveDraft?: boolean; keepEditor?: boolean }
    | { kind: 'ai'; style: EmailStyle; selectExisting?: boolean }
    | { kind: 'refine'; instruction: string; typed?: boolean; label?: string; edit: EmailEditRequest }
    | { kind: 'accept-edit'; id: number }
    | { kind: 'coursework'; edit: EmailEditRequest }
    | { kind: 'compose'; id: number };
  const action = useProfileAction<WritingIntent>({
    isOpen: isOpen && !retired, profile: requestProfile, profileAvailable,
    scopeKey: `${opportunityId}\n${targetFingerprint}\n${contactFingerprint}`, editRevision: userEditRevision, refresh: profileRefresh, target, targetRefresh,
    readiness: contextDirty ? 'blocked' : sourceReady ? 'ready'
      : profileAvailable && (targetChecking || profileRefresh?.status === 'checking') ? 'waiting' : 'blocked',
    execute: (intent) => {
      if (contextDirtyRef.current) return;
      if (intent.kind === 'compose') { void finishCompose(intent.id); return; }
      if (contactPolicyBlock) { setError(contactInstructionCopy[locale][contactPolicyBlock]); setLoading(false); return; }
      if (!paperReadingCurrent) return;
      if (intent.kind === 'variants') { targetCheckOnlyRef.current = false; void fetchVariants(intent.preserveDraft, intent.keepEditor); return; }
      if (intent.kind !== 'coursework' && !expectedTargetVersion) { reportTargetVersionFailure('unavailable'); return; }
      if (intent.kind !== 'coursework' && targetVersionError) return;
      // A source change keeps the existing manual draft. Its user must choose
      // to rebuild it before new generation or refinement can use that draft.
      if (profileChangedRef.current || profileChanged || profileRegenerating) return;
      if (intent.kind === 'accept-edit') { void acceptEdit(intent.id); return; }
      if (intent.kind === 'ai') {
        if (intent.selectExisting && aiVariant) selectVariant(variants.length);
        else void generateAi(intent.style);
        return;
      }
      if (intent.kind === 'coursework') {
        if (!editBaseCurrent(intent.edit.base) || intent.edit.selection) return;
        const { body: next, reply } = applyQuickEdit(intent.edit.base.body, 'coursework', requestProfile, t);
        if (next !== intent.edit.base.body) {
          const proposed: EmailEditProposal = { ...intent.edit, id: ++refineRequestRef.current,
            afterBody: next, usage: experienceUsage };
          proposalRef.current = proposed; setEditProposal(proposed);
        }
        setChatMessages((messages) => [...messages, { role: 'user', content: t('coldEmail.quickActions.coursework') },
          { role: 'assistant', content: next === intent.edit.base.body ? reply
            : locale === 'zh' ? '已准备课程补充建议，请比较后接受或拒绝。' : 'Coursework suggestion ready. Compare it, then accept or reject.' }]);
        return;
      }
      if (!editBaseCurrent(intent.edit.base)) return;
      setChatMessages((messages) => [...messages, { role: 'user', content: intent.label ?? intent.instruction }]);
      void runRefine(intent.instruction, intent.edit, intent.typed);
    },
  });
  useLayoutEffect(() => { composeActionCancelRef.current = action.cancel; }, [action.cancel]);
  useEffect(() => {
    if (!action.busy && composeRef.current?.phase === 'sources') cancelCompose(action.error ? 'unavailable' : null);
  }, [action.busy, action.error, cancelCompose]);
  const retireContactDraft = () => {
    cancelCompose();
    action.cancel();
    contextDirtyRef.current = true;
    contextEditedRef.current = true;
    profileChangedRef.current = true;
    profileSessionRef.current += 1;
    variantRequestRef.current += 1; aiRequestRef.current += 1;
    draftRevisionRef.current += 1;
    variantsReadyRef.current = false;
    const retiredRefine = refineInFlightRef.current;
    if (retiredRefine !== null) setChatMessages(messages => messages.map(message =>
      message.requestId === retiredRefine ? { ...message, content: t('coldEmail.profileEditRetired') } : message));
    aiInFlightRef.current = false; refineInFlightRef.current = null;
    aiCacheRef.current.clear(); autoFiredRef.current = true;
    setLoading(false); setAiLoading(false); setAiStage(null); setRefining(false);
    setProfileRegenerating(false); setProfileChanged(true); setContextChanged(true);
    setContactState(previous => ({ ...previous, dirty: true, revision: previous.revision + 1 }));
  };
  useLayoutEffect(() => { retireContactDraftRef.current = retireContactDraft; });
  const applyContactContext = (value: EmailContactContext) => {
    setReadingReviewRequired(false);
    action.cancel();
    contextDirtyRef.current = false;
    setContactState(previous => ({ id: opportunityId, value, dirty: false, revision: previous.revision + 1 }));
  };
  const requestAction = action.request;
  const fetchVariantsRef = useRef<(preserveDraft?: boolean, keepEditor?: boolean) => void>(() => {});
  useLayoutEffect(() => {
    fetchVariantsRef.current = (preserveDraft, keepEditor) => requestAction({ kind: 'variants', preserveDraft, keepEditor });
  }, [requestAction]);

  useLayoutEffect(() => {
    /* eslint-disable react-hooks/set-state-in-effect --
       Modal-lifecycle effect. Open path calls fetchVariants() whose
       sync prefix flips setLoading(true) before any await. Cleanup
       path resets every internal state slice so the next open()
       starts from a known-empty surface — splitting this into two
       effects would race the next open's fetchVariants() with stale
       residue from the previous session. */
    setRetired(false);
    sessionProfileRef.current = materialFingerprint;
    persistenceSessionRef.current += 1;
    const nextSession = persistenceSessionRef.current;
    if (isOpen) {
      const stored = openPersistedDraft(opportunityId);
      setPersistenceSession(nextSession);
      if (stored.draft) {
        const value = stored.draft;
        autoFiredRef.current = true; editorUsedRef.current = true;
        contextEditedRef.current = true;
        setDraftRestored(true); setLoading(false); metadataRefreshingRef.current = true; setMetadataRefreshing(true);
        setSubject(value.subject); setBody(value.body);
        setRecipient(value.manualRecipient ?? ''); recipientEditedRef.current = value.manualRecipient !== undefined;
        setSelectedStyle(value.selectedStyle); setChatInput(value.pendingEdit); setActiveVariant(-1);
        setSavedVersions(value.history); setSourceReview('pending');
        setScopeNeedsChoice(value.editScope === 'reselect');
        setSelection(typeof value.editScope === 'object' ? { body: value.body, range: value.editScope } : null);
        setContactState({ id: opportunityId, value: value.context, revision: 1, dirty: value.pendingPanel?.pending ?? false });
        contextDirtyRef.current = value.pendingPanel?.pending ?? false;
        setPendingPanel(value.pendingPanel ?? null); setPanelSavable(true);
        setPendingSupplement(value.pendingSupplement ?? null); setSupplementSavable(true);
        if (value.pendingSupplement) { setSupplementExpanded(true); setSupplementSession({ owner: captureOwnerToken(), targetId: opportunityId, inputKey: incomingProfileKey }); }
        setRestoredSources(value.sources);
        profileChangedRef.current = true; setProfileChanged(true);
      } else { void fetchVariantsRef.current(); }
    }
    return () => {
      versionActionRef.current += 1;
      // Persist the last rendered editing snapshot before teardown resets it.
      persistCurrentRef.current();
      clearEmailRevisions(); setSavedVersions([]); setVersionCompare(null); setVersionError(null);
      setVersionBusy(false); versionBusyRef.current = false; setSourceReview('pending');
      persistenceSessionRef.current += 1;
      detachDraft();
      setDraftRestored(false); setDraftClosing(false); metadataRefreshingRef.current = false; setMetadataRefreshing(false); setPendingPanel(null); setPanelSavable(true); setPendingSupplement(null); setSupplementSavable(true); lastSupplementSnapshotRef.current = null;
      setRestoredSources(null); setSourceSignatures(null);
      cancelCompose();
      autoFiredRef.current = false;
      contextDirtyRef.current = false; contextEditedRef.current = false;
      supplementScopeRef.current = null;
      setSupplementSession(null); setSupplementExpanded(false); setSupplementProfile(null);
      setReadingReview(0); setReadingReviewRequired(false);
      setContactState({ id: opportunityId, value: defaultEmailContactContext(), revision: 0, dirty: false });
      setContextChanged(false);
      targetCheckOnlyRef.current = false;
      pipelineVersionRef.current = null;
      variantsReadyRef.current = false;
      // Close or target change ends the send session. Bumping the id first
      // means any persistence still in flight can no longer reach this
      // component's state, so the resets below cannot be undone by a
      // straggler landing a moment later.
      sendSessionRef.current += 1;
      profileSessionRef.current += 1;
      aiInFlightRef.current = false;
      refineInFlightRef.current = null;
      draftRevisionRef.current += 1;
      confirmInFlightRef.current = false;
      sendDraftEpochRef.current = 0; setSendDraftEpoch(0);
      setContactedDraftEpoch(null); setConfirmedDraftEpoch(null);
      setContactedContentKey(null); setConfirmedContentKey(null); setActualSentAt('');
      setContacted(false);
      setContactedForId(null);
      setSendConfirmed(false);
      setFollowUpDate(null);
      setPushOffer(null);
      setPushBusy(false);
      // Reset with the rest: a status confirmed for the previous target must
      // never decide whether the NEXT one may take a reminder. The id stamps
      // make that true from the first render rather than from this cleanup.
      setConfirmedStatus(undefined);
      setConfirmedForId(null);
      setConfirming(false);
      setSendError(null);
      setVariants([]);
      setAiVariant(null);
      setAiLoading(false);
      setAiStage(null);
      setRefining(false);
      setLabType(null);
      setSelectedStyle('professional');
      setRecommendedStyle(null);
      editorUsedRef.current = false;
      setSubject(''); setSubjectFormatConfirmation(null);
      setBody('');
      setRecipient(''); recipientEditedRef.current = false;
      draftSourcesRef.current = null; setOriginKey(null);
      setRecipientStatus('unavailable');
      setGrounding('specific');
      setFreshness('unknown');
      setExperienceUsage(null); setTargetConditions(null);
      setExperienceNeedsReview(false);
      setCopiedFor(null);
      setCopyFailedFor(null);
      setError(null);
      setTargetVersionError(null);
      setNameRequired(false);
      setChatMessages([]);
      setChatInput('');
      profileChangedRef.current = false;
      setProfileChanged(false); setProfileRegenerating(false); setProfileRegenerateError(null);
    };
    /* eslint-enable react-hooks/set-state-in-effect */
    // Full reset belongs only to the open/target lifetime. The latest callback
    // is read through a layout-updated ref; material changes are handled below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOpen, opportunityId, draftResetKey]);

  useEffect(() => {
    if (!isOpen || !originKey) return;
    const origin = JSON.parse(originKey) as { profile: string; target: string | null; contact: string };
    const owner = captureOwnerToken(); let live = true;
    void Promise.all([emailDraftDigest(origin.profile), emailDraftDigest(origin.contact)]).then(([profile_sig, contact_sig]) => {
      if (live && isOwnerTokenValid(owner, owner.uid)) setSourceSignatures({ key: originKey,
        value: { profile_sig, target_version: origin.target, contact_sig } });
    }).catch(() => { /* Text still saves with an explicitly unknown source binding. */ });
    return () => { live = false; };
  }, [isOpen, originKey]);

  useEffect(() => {
    if (!isOpen || !restoredSources) return;
    if (!sourceReady) return;
    const owner = captureOwnerToken(); let live = true;
    void Promise.all([emailDraftDigest(profileFingerprint), emailDraftDigest(contactSerialized)]).then(([profile_sig, contact_sig]) => {
      if (!live || !isOwnerTokenValid(owner, owner.uid)) return;
      const unchanged = restoredSources.profile_sig === profile_sig && restoredSources.contact_sig === contact_sig
        && !!expectedTargetVersion && restoredSources.target_version === expectedTargetVersion;
      profileChangedRef.current = !unchanged; setProfileChanged(!unchanged);
      setSourceReview(unchanged ? 'matched' : restoredSources.profile_sig && restoredSources.contact_sig && restoredSources.target_version ? 'changed' : 'unknown');
      if (unchanged) {
        // Reattach only after comparing the saved original binding to fresh materials.
        draftSourcesRef.current = { profile: profileFingerprint, target: expectedTargetVersion, contact: contactSerialized };
        setOriginKey(JSON.stringify(draftSourcesRef.current));
        setSourceSignatures({ key: JSON.stringify(draftSourcesRef.current), value: restoredSources });
      }
    }).catch(() => { if (live) setSourceReview('unknown'); });
    return () => { live = false; };
  }, [isOpen, sourceReady, restoredSources, profileFingerprint, contactSerialized, expectedTargetVersion]);

  const restoredMetadataRef = useRef(false);
  useEffect(() => {
    if (!draftRestored) { restoredMetadataRef.current = false; return; }
    if (!isOpen || !sourceReady || contextDirty || profileChanged || !paperReadingCurrent || restoredMetadataRef.current) return;
    restoredMetadataRef.current = true;
    // Refresh verified recipient/metadata only; keep the editor and suppress automatic AI.
    void fetchVariantsRef.current(true);
  }, [draftRestored, isOpen, sourceReady, contextDirty, profileChanged, paperReadingCurrent]);

  const panelSnapshotChanged = useCallback((snapshot: EmailContactDraftSnapshot | null) => {
    setPanelSavable(snapshot !== null);
    if (snapshot?.pending && !contextDirtyRef.current) retireContactDraftRef.current();
    if (snapshot) setPendingPanel({ ...snapshot, opportunityId });
    else markDraftUnsaved('too_large');
  }, [markDraftUnsaved, opportunityId]);
  const supplementSnapshotChanged = useCallback((snapshot: ResumeSupplementDraftSnapshot | null) => {
    const key = snapshot ? JSON.stringify(snapshot) : 'invalid';
    if (lastSupplementSnapshotRef.current !== null && lastSupplementSnapshotRef.current !== key) userActionRevisionRef.current += 1;
    lastSupplementSnapshotRef.current = key;
    setSupplementSavable(snapshot !== null);
    if (snapshot) setPendingSupplement({ ...snapshot, opportunityId });
    else markDraftUnsaved('too_large');
  }, [markDraftUnsaved, opportunityId]);
  const draftPayload: ColdEmailDraftPayload = {
    subject, body, selectedStyle, pendingEdit: chatInput, context: requestContactContext,
    history: savedVersions, editScope: scopeNeedsChoice || invalidSelection ? 'reselect' : selection?.body === body ? selection.range : 'full',
    pendingPanel, pendingSupplement,
    sources: originKey && sourceSignatures?.key === originKey ? sourceSignatures.value : restoredSources ?? NO_DRAFT_SOURCES,
  };
  const draftPayloadKey = JSON.stringify(draftPayload);
  useLayoutEffect(() => { draftPayloadRef.current = recipientEditedRef.current ? { ...draftPayload, manualRecipient: recipient } : draftPayload; });
  useLayoutEffect(() => {
    changeDraftRef.current = async (next, reason, valid, apply) => {
      if (versionBusyRef.current || !panelSavable || !supplementSavable || !valid()) return false;
      const before = JSON.parse(JSON.stringify(draftPayloadRef.current)) as ColdEmailDraftPayload;
      const base = captureEditBase(); const editEpoch = userActionRevisionRef.current;
      const saveBase = { edit: editEpoch, draft: base.revision, material: base.material }; versionSaveBaseRef.current = saveBase;
      const operation = ++versionActionRef.current;
      const current = () => operation === versionActionRef.current && valid() && editBaseCurrent(base)
        && userActionRevisionRef.current === editEpoch;
      versionBusyRef.current = true; setVersionBusy(true); setVersionError(null);
      let settle!: () => void; const pending = new Promise<void>(resolve => { settle = resolve; }); versionPendingRef.current = pending;
      try {
        if (before.history.length >= COLD_EMAIL_DRAFT_LIMITS.historyItems) {
          setVersionError(locale === 'zh' ? '已保存 10 个版本。请先删除不需要的旧版；当前稿未替换。' : 'There are 10 saved versions. Delete an unwanted version first. Your current draft is unchanged.');
          return false;
        }
        let previousSources = before.sources;
        if (originKey) {
          const origin = JSON.parse(originKey) as { profile: string; contact: string; target: string | null };
          const [profile_sig, contact_sig] = await Promise.all([emailDraftDigest(origin.profile), emailDraftDigest(origin.contact)]);
          previousSources = { profile_sig, contact_sig, target_version: origin.target };
        }
        const sources = next.sources ?? { profile_sig: await emailDraftDigest(profileFingerprint),
          contact_sig: await emailDraftDigest(contactSerialized), target_version: expectedTargetVersion };
        if (!current()) return false;
        const variant = allVariants[activeVariant];
        const saved: ColdEmailDraftVersion = { id: crypto.randomUUID(), createdAt: new Date().toISOString(), reason,
          subject: before.subject, body: before.body, selectedStyle: before.selectedStyle, sources: previousSources,
          origin: activeVariant < 0 || (variant && (variant.body !== before.body || variant.subject !== before.subject))
            ? 'manual' : variant?.method === 'ai' ? 'ai' : variant ? 'template' : 'unknown', variantId: variant?.id ?? null };
        const candidate: ColdEmailDraftPayload = { ...before, ...next, sources, history: [...before.history, saved], editScope: next.editScope ?? 'full' };
        if (JSON.stringify(candidate).length > COLD_EMAIL_DRAFT_LIMITS.total) {
          setVersionError(locale === 'zh' ? '版本内容已超过本地保存容量。请删除不需要的旧版；当前稿未替换。' : 'The versions exceed local storage capacity. Delete an unwanted version first. Your current draft is unchanged.');
          return false;
        }
        if (!await commitDraft(candidate, current) || !current()) {
          if (editBaseCurrent(base)) setVersionError(locale === 'zh' ? '版本未能保存，当前稿未替换。请检查保存状态后重试。' : 'The version could not be saved, so your draft was not replaced. Check the save status and try again.');
          return false;
        }
        setSavedVersions(candidate.history); apply(); return true;
      } catch {
        if (current()) setVersionError(locale === 'zh' ? '版本未能保存，当前稿未替换。请重试。' : 'The version could not be saved. Your draft is unchanged. Please try again.');
        return false;
      } finally {
        if (versionSaveBaseRef.current === saveBase) versionSaveBaseRef.current = null;
        settle(); if (versionPendingRef.current === pending) versionPendingRef.current = null;
        if (operation === versionActionRef.current) { versionBusyRef.current = false; setVersionBusy(false); }
      }
    };
  });

  async function deleteSavedVersion(id: string) {
    if (versionBusyRef.current || !panelSavable || !supplementSavable || !savedVersions.some(v => v.id === id)) return;
    if (!window.confirm(locale === 'zh' ? '删除这个历史版本？当前草稿会保留。' : 'Delete this saved version? Your current draft is kept.')) return;
    const base = captureEditBase(); const editEpoch = userActionRevisionRef.current;
    const saveBase = { edit: editEpoch, draft: base.revision, material: base.material }; versionSaveBaseRef.current = saveBase;
    const operation = ++versionActionRef.current;
    const current = () => operation === versionActionRef.current && editBaseCurrent(base) && userActionRevisionRef.current === editEpoch;
    const candidate = { ...draftPayloadRef.current, history: savedVersions.filter(v => v.id !== id) };
    versionBusyRef.current = true; setVersionBusy(true); setVersionError(null);
    let settle!: () => void; const pending = new Promise<void>(resolve => { settle = resolve; }); versionPendingRef.current = pending;
    try {
      if (await commitDraft(candidate, current) && current()) { setSavedVersions(candidate.history); setVersionCompare(null); }
      else if (current()) setVersionError(locale === 'zh' ? '删除未保存，旧版仍保留。请重试。' : 'Deletion was not saved. The version is kept. Please try again.');
    } finally { if (versionSaveBaseRef.current === saveBase) versionSaveBaseRef.current = null; settle(); if (versionPendingRef.current === pending) versionPendingRef.current = null; if (operation === versionActionRef.current) { versionBusyRef.current = false; setVersionBusy(false); } }
  }

  async function restoreSavedVersion() {
    const comparison = versionCompare;
    if (!comparison || !editBaseCurrent(comparison.base) || !savedVersions.some(v => v.id === comparison.version.id)) return;
    const version = comparison.version;
    const scope = draftPayloadRef.current.editScope === 'full' ? 'full' : 'reselect';
    await changeDraftRef.current({ subject: version.subject, body: version.body, selectedStyle: version.selectedStyle, sources: version.sources, editScope: scope }, 'restored',
      () => editBaseCurrent(comparison.base) && savedVersions.some(v => v.id === version.id), () => {
        clearEmailRevisions(); action.cancel(); cancelCompose();
        aiRequestRef.current += 1; variantRequestRef.current += 1; refineInFlightRef.current = null; aiInFlightRef.current = false;
        setAiLoading(false); setAiStage(null); setRefining(false); autoFiredRef.current = true;
        draftRevisionRef.current += 1; setUserEditRevision(value => value + 1);
        setSubject(version.subject); setBody(version.body); setSelectedStyle(version.selectedStyle); setActiveVariant(-1);
        setScopeNeedsChoice(scope === 'reselect'); setVersionCompare(null);
        draftSourcesRef.current = null; setOriginKey(null); setRestoredSources(version.sources); setSourceReview('pending');
        setDraftRestored(true); metadataRefreshingRef.current = true; setMetadataRefreshing(true); restoredMetadataRef.current = false;
        profileChangedRef.current = true; setProfileChanged(true); setExperienceUsage(null); setTargetConditions(null);
        setSubjectFormatConfirmation(null); setActualSentAt(''); setCopiedFor(null); setCopyFailedFor(null); setSendError(null);
        sendDraftEpochRef.current += 1; setSendDraftEpoch(sendDraftEpochRef.current);
        setChatMessages(messages => [...messages, { role: 'assistant', content: locale === 'zh' ? '已恢复旧版；替换前的稿件也已保存。' : 'Version restored. The draft it replaced was also saved.' }]);
      });
  }

  useLayoutEffect(() => {
    const current = () => {
      if (!isOpen || persistenceSession !== persistenceSessionRef.current || !panelSavable || !supplementSavable) return;
      // Derived source hashes/panel receipts can settle during a checkpoint.
      // They are included in that atomic snapshot, not a competing user edit.
      const checkpoint = versionSaveBaseRef.current;
      if (versionBusyRef.current && checkpoint?.edit === userActionRevisionRef.current
        && checkpoint.draft === draftRevisionRef.current && checkpoint.material === editLiveRef.current.material) return;
      if (!(subject || body || recipientEditedRef.current || chatInput || contextEditedRef.current || pendingPanel?.pending || pendingSupplement)) return;
      const payload = JSON.parse(draftPayloadKey) as ColdEmailDraftPayload;
      if (recipientEditedRef.current) payload.manualRecipient = recipient;
      persistDraft(payload);
    };
    persistCurrentRef.current = current;
    current();
  }, [isOpen, persistenceSession, panelSavable, supplementSavable, pendingSupplement, subject, body, recipient, chatInput, pendingPanel, draftPayloadKey, persistDraft, versionBusy]);
  useEffect(() => {
    if (!isOpen || !['saving', 'failed', 'conflict'].includes(draftPersistence.status)) return;
    const warn = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = ''; };
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  }, [isOpen, draftPersistence.status]);
  async function clearSavedDraft() {
    if (!window.confirm(locale === 'zh' ? '删除这份草稿并重新开始？' : 'Delete this draft and start again?')) return;
    const owner = captureOwnerToken();
    const session = sendSessionRef.current;
    const persistence = persistenceSessionRef.current;
    persistCurrentRef.current();
    if (!await clearPersistedDraft() || session !== sendSessionRef.current
      || persistence !== persistenceSessionRef.current || !isTokenOwnerStillCurrent(owner)) return;
    // Retire the old snapshot before reset cleanup can enqueue it again.
    persistenceSessionRef.current += 1;
    persistCurrentRef.current = () => {};
    detachDraft();
    // Reset invalidates old provider callbacks before a deliberate new draft starts.
    sendSessionRef.current += 1;
    setDraftResetKey(value => value + 1);
  }

  useLayoutEffect(() => {
    if (!isOpen || sessionProfileRef.current === materialFingerprint) return;
    sessionProfileRef.current = materialFingerprint;
    profileSessionRef.current += 1;
    variantRequestRef.current += 1; aiRequestRef.current += 1;
    const retiredRefine = refineInFlightRef.current;
    refineInFlightRef.current = null; aiInFlightRef.current = false;
    draftRevisionRef.current += 1;
    variantsReadyRef.current = false; pipelineVersionRef.current = null; corpusVersionRef.current = null;
    aiCacheRef.current.clear();
    const hasDraft = contextEditedRef.current || editorUsedRef.current || !!(subject || body || recipient);
    profileChangedRef.current = hasDraft;
    autoFiredRef.current = hasDraft;
    // New material must not erase an editor or let an old response overwrite it.
    setVariants([]); setAiVariant(null); setAiLoading(false); setAiStage(null); setRefining(false);
    setLoading(!hasDraft); setError(null); if (!targetCheckOnlyRef.current) setTargetVersionError(null); setNameRequired(false); setExperienceUsage(null); setTargetConditions(null);
    setProfileRegenerating(false); setProfileRegenerateError(null); setProfileChanged(hasDraft);
    if (retiredRefine !== null) setChatMessages((messages) => messages.map((message) =>
      message.requestId === retiredRefine ? { ...message, content: t('coldEmail.profileEditRetired') } : message));
    // Initial material arriving before any draft may use the normal open flow.
    if (!hasDraft && !targetCheckOnlyRef.current) void fetchVariantsRef.current();
  }, [isOpen, materialFingerprint, subject, body, recipient, t]);

  const wasSourceReadyRef = useRef(sourceReady);
  useLayoutEffect(() => {
    const wasReady = wasSourceReadyRef.current;
    wasSourceReadyRef.current = sourceReady;
    if (!isOpen) return;
    if (!sourceReady) {
      // Retire every writing callback at the START of a read, including a
      // check that later returns unchanged data. Keep the editable fields.
      if (wasReady) {
        profileSessionRef.current += 1;
        variantRequestRef.current += 1; aiRequestRef.current += 1;
        const retiredRefine = refineInFlightRef.current;
        if (retiredRefine !== null) setChatMessages((messages) => messages.map((message) =>
          message.requestId === retiredRefine ? { ...message, content: t('coldEmail.sourceCheckRetired') } : message));
      }
      refineInFlightRef.current = null; aiInFlightRef.current = false;
      // A check may retire generation, but it is not a completed first draft.
      // Only an existing editor is kept visible while its source is checked.
      setLoading(!editorUsedRef.current && !(subject || body || recipient));
      setAiLoading(false); setAiStage(null); setRefining(false); setProfileRegenerating(false);
    } else if (!targetCheckOnlyRef.current && !profileRefresh?.checkForAction && !wasReady && !variantsReadyRef.current && !profileChanged) {
      void fetchVariantsRef.current(editorUsedRef.current);
    }
  }, [isOpen, sourceReady, profileChanged, profileRefresh?.checkForAction, subject, body, recipient, t]);

  useEffect(() => {
    if (!isOpen) return;
    const current = captureDraftSession();
    // This only supplies a review hint. Send the complete envelope unchanged;
    // the backend independently validates confirmation and current provenance.
    void Promise.resolve().then(async () => {
      const parsed = validateExperienceEntries(requestProfile.experience_entries);
      if (!parsed.ok) {
        if (current()) setExperienceNeedsReview(true);
        return;
      }
      const entries = parsed.value;
      const rawText = requestProfile.resume_text ?? '';
      let needsReview = entries.some((entry) => entry.status === 'candidate')
        || (rawText.trim().length > 0 && entries.length === 0);
      const sourced = entries.filter((entry) => entry.status === 'confirmed' && entry.source.kind === 'resume');
      if (sourced.length > 0) {
        try {
          const expectedDigest = await sourceDigest(rawText);
          needsReview ||= sourced.some((entry) => !isActiveExperience(entry, { rawText, expectedDigest }));
        } catch {
          needsReview = true;
        }
      }
      if (current()) setExperienceNeedsReview(needsReview);
    });
  }, [isOpen, requestProfile, captureDraftSession]);

  useEffect(() => {
    if (!isOpen || retired) return;
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
        closeDraft();
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
  }, [isOpen, retired, closeDraft]);

  useEffect(() => {
    if (isOpen && !retired) document.body.style.overflow = 'hidden';
    return () => { document.body.style.overflow = ''; };
  }, [isOpen, retired]);

  useEffect(() => {
    // Only the history follows new messages; never scroll the workspace,
    // editor, or page away from the field the user is editing.
    const history = chatHistoryRef.current;
    if (history) history.scrollTop = history.scrollHeight;
  }, [chatMessages]);

  // W10b: once the user signs in from the reveal affordance, fetch the
  // recipient once via the (cheap) variants endpoint and fill the To field —
  // WITHOUT regenerating or touching the draft they may have edited. The
  // subscription also fires with the current session on mount, which
  // self-heals the stale-token case where the api-level refresh-retry failed.
  useEffect(() => {
    if (contextDirty || contextChanged || !sourceReady || !isOpen || !expectedTargetVersion || targetVersionError || recipientStatus !== 'sign_in_required') return;
    const current = captureDraftSession();
    const unsubscribe = onAuthChange((state) => {
      if (!current() || !state.session || state.isAnonymous) return;
      void (async () => {
        try {
          const data = await getEmailVariants(profile, opportunityId, undefined, { expectedTargetVersion, contactContext: requestContactContext });
          if (!current()) return;
          requireTargetReceipt(data, opportunityId, expectedTargetVersion);
          await requireContactReceipt(data, requestContactContext);
          if (!current()) return;
          const email = data.variants[0]?.recipient_email ?? '';
          setRecipientStatus(statusOf(data.recipient_status, email));
          if (email) setRecipient((prev) => prev || email);
        } catch (error) {
          const failure = targetVersionFailure(error);
          if (current() && profileInputMessage(error, t)) {
            setChatMessages(messages => [...messages, { role: 'assistant', content: profileInputMessage(error, t)! }]);
          } else if (current() && isEmailInputTooLarge(error)) {
            setChatMessages(messages => [...messages, { role: 'assistant', content: emailInputTooLargeMessage(locale) }]);
          } else if (current() && readingChanged(error)) reportReadingChange();
          else if (current() && failure) reportTargetVersionFailure(failure);
          // Other reveal failures keep the existing sign-in affordance.
        }
      })();
    });
    return unsubscribe;
  }, [t, locale, contextDirty, contextChanged, requestContactContext, sourceReady, isOpen, recipientStatus, profile, opportunityId, expectedTargetVersion, targetVersionError, captureDraftSession, reportTargetVersionFailure, reportReadingChange]);

  async function selectVariant(idx: number) {
    const v = allVariants[idx];
    if (!sourceReadyRef.current || contextDirtyRef.current || targetVersionError || profileChanged || profileRegenerating || !v) return;
    const base = captureEditBase();
    await changeDraftRef.current({ subject: v.subject, body: v.body }, 'variant', () => editBaseCurrent(base), () => {
    draftRevisionRef.current += 1;
    noteUserEdit();
    clearEmailRevisions();
    setActiveVariant(idx);
    setSubject(v.subject);
    setBody(v.body);
    draftSourcesRef.current = { profile: JSON.stringify(requestProfile), target: expectedTargetVersion, contact: serializeEmailContactContext(requestContactContext) };
    setOriginKey(JSON.stringify(draftSourcesRef.current));
    setRestoredSources(null);
    setExperienceUsage(v.experience_usage ?? null);
    setTargetConditions(readEmailTargetConditions(v));
    // Variants share one server-resolved recipient; when the reveal is locked
    // they carry "" — never wipe an address the user typed themselves.
    setRecipient((prev) => prev || v.recipient_email);
    setChatMessages((prev) => [
      ...prev,
      { role: 'assistant', content: t('coldEmail.switched', { label: v.label }) },
    ]);
    });
  }

  // Generate (or re-generate) the AI draft in a given voice. Used by the
  // automatic run on open (AI is the default engine; `auto: true`), the ✨ AI
  // pill, and the tone picker. Auto mode differs in three ways: it reports
  // nothing until it succeeds (a fallback the user never asked for stays
  // silent), it never clobbers a draft the user has meanwhile edited or
  // switched away from, and it seeds/serves the per-open cache.
  const generateAi = useCallback(async (style: EmailStyle, opts?: { auto?: boolean }) => {
    if (!sourceReadyRef.current || contextDirtyRef.current || !paperReadingCurrent || contactPolicyBlock || profileChanged || profileRegenerating || !variantsReadyRef.current || aiInFlightRef.current || refineInFlightRef.current !== null || missingStudentName) return;
    if (!expectedTargetVersion) { reportTargetVersionFailure('unavailable'); return; }
    if (targetVersionError) return;
    const sessionCurrent = captureDraftSession();
    const request = ++aiRequestRef.current;
    const current = () => sessionCurrent() && request === aiRequestRef.current;
    const revision = draftRevisionRef.current;
    const auto = opts?.auto ?? false;
    const aiIdx = variants.length;
    if (auto) setSelectedStyle(style);

    const applyResponse = async (
      resp: ColdEmailResponse,
      select: boolean,
      contactIsCurrent = true,
    ) => {
      const v: EmailVariant = {
        id: AI_VARIANT_ID,
        label: t('coldEmail.aiVariantLabel'),
        subject: resp.subject,
        body: resp.body,
        recipient_email: resp.recipient_email,
        mailto_link: resp.mailto_link,
        lab_type: resp.lab_type ?? labType ?? null,
        method: resp.method,
        fallback_reason: resp.fallback_reason,
        experience_usage: resp.experience_usage,
        target_conditions: resp.target_conditions,
      };
      if (select && !auto && !await changeDraftRef.current({ subject: v.subject, body: v.body, selectedStyle: style }, 'regenerated',
        () => current() && draftRevisionRef.current === revision, () => {})) return false;
      if (!current() || (select && draftRevisionRef.current !== revision)) return false;
      setAiVariant(v);
      if (contactIsCurrent) {
        setRecipientStatus(statusOf(resp.recipient_status, resp.recipient_email));
      }
      if (resp.lab_type && resp.lab_type !== labType) setLabType(resp.lab_type);
      if (select) {
        clearEmailRevisions();
        setSelectedStyle(style); setActiveVariant(aiIdx);
        setSubject(v.subject);
        setBody(v.body);
        draftSourcesRef.current = { profile: JSON.stringify(requestProfile), target: expectedTargetVersion, contact: serializeEmailContactContext(requestContactContext) };
        setOriginKey(JSON.stringify(draftSourcesRef.current));
        setRestoredSources(null);
        setExperienceUsage(v.experience_usage ?? null);
    setTargetConditions(readEmailTargetConditions(v));
        if (contactIsCurrent) {
          setRecipient((prev) => prev || v.recipient_email);
        }
      }
      return true;
    };

    // W12 draft freshness: a cached AI draft is only re-served while young
    // AND while variants confirms the same writing pipeline. A superseded
    // professor record or pipeline must not keep personalizing from cache.
    const cached = aiCacheRef.current.get(`${opportunityId}|${style}|${contactFingerprint}`);
    if (cached) {
      if (cached.response.opportunity_id !== opportunityId || aiCacheEntryIsStale(cached, Date.now(), corpusVersionRef.current, pipelineVersionRef.current, expectedTargetVersion)) {
        aiCacheRef.current.delete(`${opportunityId}|${style}|${contactFingerprint}`);
      } else {
        // Cache only the AI writing value. Recipient truth was refreshed by
        // getEmailVariants for the current auth session and must never be
        // overwritten by a reveal cached before logout/token expiry.
        if (!await applyResponse(cached.response, true, false)) return;
        setChatMessages((prev) => [...prev, { role: 'assistant', content: t('coldEmail.aiGenerated') }]);
        return;
      }
    }

    aiInFlightRef.current = true;
    setAiLoading(true);
    if (!auto) {
      setChatMessages((prev) => [
        ...prev,
        { role: 'assistant', content: t('coldEmail.tone.generating', { style: t(`coldEmail.tone.${style}`) }) },
      ]);
    }
    try {
      // Confirmed entries travel in the API's evidence envelope. The modal
      // never extracts raw strings or confirms an imported experience itself.
      const opts = { engine: 'ai' as const, style, expectedTargetVersion, contactContext: requestContactContext };
      let resp;
      try {
        // A definite old backend may use the blocking compatibility route.
        // Timeouts/disconnects may already have generated a draft: never replay.
        resp = await generateColdEmailStream(requestProfile, opportunityId, opts, (stage) => {
          if (current()) setAiStage(stage);
        });
      } catch (streamError) {
        if (!current()) return;
        if (!canFallbackColdEmailStream(streamError)) throw streamError;
        setAiStage(null);
        resp = await generateColdEmail(requestProfile, opportunityId, opts);
      }
      if (!current()) return;
      requireTargetReceipt(resp, opportunityId, expectedTargetVersion);
      await requireContactReceipt(resp, requestContactContext);
      if (!current()) return;
      if (resp.method === 'ai') {
        aiCacheRef.current.set(`${opportunityId}|${style}|${contactFingerprint}`, {
          // Recipient truth stripped before caching — same reason as the
          // cached-serve path above.
          response: {
            ...resp,
            recipient_email: '',
            recipient_status: 'unavailable',
            mailto_link: '',
          },
          at: Date.now(),
        });
        if (resp.corpus_version) corpusVersionRef.current = resp.corpus_version;
      }
      if (auto && resp.method !== 'ai') return; // silent — the user never asked
      if (!await applyResponse(resp, draftRevisionRef.current === revision)) return;
      setChatMessages((prev) => [
        ...prev,
        {
          role: 'assistant',
          content: resp.method === 'ai' ? t('coldEmail.aiGenerated') : aiFallbackMessage(resp.fallback_reason, t),
        },
      ]);
    } catch (error) {
      const failure = targetVersionFailure(error);
      if (current() && profileInputMessage(error, t)) {
        setChatMessages(messages => [...messages, { role: 'assistant', content: profileInputMessage(error, t)! }]);
      } else if (current() && isEmailInputTooLarge(error)) {
        setChatMessages(messages => [...messages, { role: 'assistant', content: emailInputTooLargeMessage(locale) }]);
      } else if (current() && readingChanged(error)) reportReadingChange();
      else if (current() && failure) reportTargetVersionFailure(failure);
      else if (current() && !auto) {
        setChatMessages((prev) => [
          ...prev,
          { role: 'assistant', content: t('coldEmail.aiFailed') },
        ]);
      }
    } finally {
      if (current()) {
        aiInFlightRef.current = false;
        setAiLoading(false);
        setAiStage(null);
      }
    }
  }, [locale, contactPolicyBlock, paperReadingCurrent, profileChanged, profileRegenerating, missingStudentName, variants.length, requestProfile, requestContactContext, contactFingerprint, opportunityId, expectedTargetVersion, targetVersionError, labType, t, captureDraftSession, reportTargetVersionFailure, reportReadingChange, clearEmailRevisions]);

  // AI is the default engine: once the template variants land, run the
  // pipeline once automatically. The template is the instant placeholder; the
  // AI draft takes over on success (unless the user already started editing).
  useEffect(() => {
    if (!sourceReady || !isOpen || profileChanged || profileRegenerating || !variantsReadyRef.current || loading || variants.length === 0 || autoFiredRef.current) return;
    autoFiredRef.current = true;
    generateAi(selectedStyle, { auto: true });
  }, [sourceReady, isOpen, profileChanged, profileRegenerating, loading, variants.length, selectedStyle, generateAi]);

  function handleAiPillClick() {
    if (metadataRefreshingRef.current || versionBusyRef.current || aiLoading || action.busy) return;
    action.request({ kind: 'ai', style: selectedStyle, selectExisting: true });
  }

  function handleToneClick(style: EmailStyle) {
    if (metadataRefreshingRef.current || versionBusyRef.current || aiLoading || action.busy) return;
    action.request({ kind: 'ai', style });
  }

  function refineLimitMessage(field: string, max: number): string {
    const label = locale === 'zh' ? ({ current_body: '正文', instruction: '修改要求', subject: '主题' } as Record<string, string>)[field]
      : ({ current_body: 'Body', instruction: 'Request', subject: 'Subject' } as Record<string, string>)[field];
    return locale === 'zh' ? `${label}超过精修上限（${max.toLocaleString()} 个文本单位，部分 emoji 占两个）。请缩短后再试；全文和要求已保留，未截断。`
      : `${label} exceeds the editing limit (${max.toLocaleString()} text units; some emoji count as two). Shorten it and try again. Your complete draft and request are kept, with no truncation.`;
  }
  function checkRefineLimits(edit: EmailEditRequest, instruction: string): boolean {
    const over = ([["current_body", edit.base.body, 5000], ["instruction", instruction, 500], ["subject", edit.base.subject, 2000]] as const).find(([, value, limit]) => value.length > limit);
    if (!over) return true;
    setChatMessages(messages => [...messages, { role: 'assistant', content: refineLimitMessage(over[0], over[2]) }]);
    return false;
  }

  // A suggestion is inert until an explicit accept passes fresh source checks.
  async function runRefine(instruction: string, edit: EmailEditRequest, typed = false) {
    if (!editBaseCurrent(edit.base) || !sourceReadyRef.current || contextDirtyRef.current || !paperReadingCurrent || contactPolicyBlock || profileChanged || profileRegenerating || refineInFlightRef.current !== null) return;
    if (!expectedTargetVersion) { reportTargetVersionFailure('unavailable'); return; }
    if (targetVersionError) return;
    if (!checkRefineLimits(edit, instruction)) return;
    discardProposal();
    // Retire automatic generation without pretending the user edited the body.
    // Starting or failing another request must leave the last accepted undo intact.
    aiRequestRef.current += 1; aiInFlightRef.current = false;
    setAiLoading(false); setAiStage(null);
    const sessionCurrent = captureDraftSession();
    const requestId = ++refineRequestRef.current;
    refineInFlightRef.current = requestId;
    const current = () => sessionCurrent() && isOwnerTokenValid(edit.base.owner, edit.base.owner.uid) && refineInFlightRef.current === requestId;
    setRefining(true);
    const reply = (content: string) => setChatMessages((prev) => prev.map((msg) =>
      msg.requestId === requestId ? { ...msg, content } : msg));
    setChatMessages((prev) => [...prev, { requestId, role: 'assistant', content: t('coldEmail.editing') }]);
    try {
      const result = await refineEmail(edit.base.body, instruction, requestProfile, opportunityId, {
        expectedTargetVersion, contactContext: requestContactContext,
        subject: edit.base.subject, ...(edit.selection ? { selection: edit.selection } : {}),
      });
      if (!current()) return;
      if (!editBaseCurrent(edit.base)) { reply(t('coldEmail.editSuperseded')); return; }
      requireTargetReceipt(result, opportunityId, expectedTargetVersion);
      await requireContactReceipt(result, requestContactContext);
      if (!current()) return;
      if (!editBaseCurrent(edit.base)) { reply(t('coldEmail.editSuperseded')); return; }
      if (result.outcome === 'no_change' && result.reason === 'target_conditions') {
        if (!isEmailConditionIssues(result.condition_issues) || result.condition_issues.length === 0) throw new Error('Invalid condition issue receipt');
        reply(result.condition_issues.map(issue => emailConditionIssueText(issue, locale)).join(' ') + (locale === 'zh' ? ' 原稿和修改要求已保留。' : ' Your draft and request are kept.'));
        return;
      }
      let afterBody = result.body;
      if (edit.selection) {
        if (result.scope !== 'selection') throw new Error('Invalid selection response');
        if (result.outcome === 'no_change') {
          const reasons = locale === 'zh' ? {
            target_conditions: '请对照来源核对申请条件。原稿和要求已保留。',
            provider_unavailable: '修改服务暂不可用。原稿和要求已保留，请稍后重试。',
            insufficient_evidence: '机会资料不足，暂时无法给出可靠的修改建议。原稿已保留。',
            review_required: '请先检查原稿中的称呼和邮箱地址。原稿和要求已保留。',
            invalid_output: '返回的建议不符合选段要求，未采用。原稿和要求已保留。',
            fabrication: '建议含有无法核实的内容，未采用。原稿和要求已保留。',
            unchanged: '所选内容没有变化。修改要求已保留。',
          } : {
            target_conditions: 'Review the application conditions against the source. Your draft and request are kept.',
            provider_unavailable: 'The editing service is unavailable. Your draft and request are kept. Try again later.',
            insufficient_evidence: 'The opportunity has too little source evidence for a reliable edit. Your draft is kept.',
            review_required: 'Review the greeting and email addresses in the body first. Your draft and request are kept.',
            invalid_output: 'The suggestion did not meet the selection requirements. Your draft and request are kept.',
            fabrication: 'The suggestion contained unsupported claims and was rejected. Your draft and request are kept.',
            unchanged: 'The selected text is unchanged. Your request is kept.',
          };
          reply(result.reason && reasons[result.reason] || (locale === 'zh' ? '未生成可用建议。原稿和要求已保留。' : 'No usable suggestion. Your draft and request are kept.'));
          return;
        }
        const proposed = result.proposal;
        if (result.outcome !== 'proposal' || !proposed || proposed.start_utf16 !== edit.selection.start_utf16
          || proposed.end_utf16 !== edit.selection.end_utf16 || proposed.original_text !== edit.selection.text
          || typeof proposed.replacement !== 'string' || proposed.base_body_sha256 !== await emailDraftDigest(edit.base.body)) throw new Error('Invalid selection receipt');
        const applied = applyEmailReplacement(edit.base.body, edit.selection, proposed.replacement);
        if (applied === null) throw new Error('Invalid selection');
        afterBody = applied;
      }
      if (!current()) return;
      if (!editBaseCurrent(edit.base)) { reply(t('coldEmail.editSuperseded')); return; }
      if (typeof afterBody !== 'string') throw new Error('Invalid refinement');
      if (afterBody === edit.base.body) {
        reply(result.fallback_reason === 'fabrication' ? t('coldEmail.refineFabrication')
          : result.fallback_reason === 'insufficient_evidence' ? aiFallbackMessage('insufficient_evidence', t)
          : locale === 'zh' ? '正文没有变化。修改要求已保留。' : 'The body is unchanged. Your request is kept.');
        return;
      }
      const proposed: EmailEditProposal = { ...edit, id: requestId, afterBody,
        usage: result.experience_usage ?? null, conditions: readEmailTargetConditions(result), ...(typed ? { instruction } : {}) };
      proposalRef.current = proposed; setEditProposal(proposed);
      reply(result.fallback_reason === 'fabrication' ? t('coldEmail.refineFabrication')
        : result.fallback_reason === 'insufficient_evidence' ? aiFallbackMessage('insufficient_evidence', t)
        : locale === 'zh' ? (result.method === 'llm' ? '建议已准备好，请比较后接受或拒绝。' : '已生成基础修改建议，请比较后接受或拒绝。')
          : result.method === 'llm' ? 'Suggestion ready. Compare it, then accept or reject.' : 'Basic edit suggestion ready. Compare it, then accept or reject.');
    } catch (error) {
      if (current()) {
        const failure = targetVersionFailure(error);
        if (profileInputMessage(error, t)) reply(profileInputMessage(error, t)!);
        else if (isEmailInputTooLarge(error)) reply(emailInputTooLargeMessage(locale));
        else if (readingChanged(error)) { reportReadingChange(); reply(locale === 'zh' ? '原稿已保留。请在“联系目的与背景”中核对或跳过论文阅读。' : 'Your draft is kept. Review or skip paper reading in Contact purpose and background.'); }
        else if (failure) { reportTargetVersionFailure(failure); reply(t('coldEmail.editFailed')); }
        else {
          const detail = error && typeof error === 'object' && 'detail' in error ? error.detail : null;
          if (detail && typeof detail === 'object' && 'code' in detail && detail.code === 'EMAIL_REFINE_LIMIT'
            && 'field' in detail && ['current_body', 'instruction', 'subject'].includes(String(detail.field))
            && 'max_utf16' in detail && Number.isSafeInteger(detail.max_utf16)) reply(refineLimitMessage(String(detail.field), Number(detail.max_utf16)));
          else reply(t('coldEmail.editFailed'));
        }
      }
    } finally {
      if (current()) { refineInFlightRef.current = null; setRefining(false); }
    }
  }

  async function acceptEdit(id: number) {
    const proposal = proposalRef.current;
    if (!proposal || proposal.id !== id || !editBaseCurrent(proposal.base) || !sourceReadyRef.current
      || contextDirtyRef.current || profileChangedRef.current || targetVersionError) return;
    const pendingEdit = proposal.instruction && chatInput.trim() === proposal.instruction ? '' : chatInput;
    await changeDraftRef.current({ body: proposal.afterBody, pendingEdit }, 'accepted_edit',
      () => proposalRef.current === proposal && editBaseCurrent(proposal.base) && sourceReadyRef.current && !contextDirtyRef.current, () => {
    // Consume after durable save; a repeated click cannot apply it twice.
    proposalRef.current = null; setEditProposal(null); setSelection(null);
    cancelCompose();
    const revision = ++draftRevisionRef.current;
    const undo: EmailEditUndo = { base: { ...proposal.base, body: proposal.afterBody, revision },
      beforeBody: proposal.base.body, usage: experienceUsage, conditions: targetConditions, sources: draftSourcesRef.current,
      origin: originKey, restored: restoredSources };
    undoRef.current = undo; setEditUndo(undo);
    editorUsedRef.current = true;
    setBody(proposal.afterBody); setActiveVariant(-1);
    draftSourcesRef.current = { profile: JSON.stringify(requestProfile), target: expectedTargetVersion, contact: serializeEmailContactContext(requestContactContext) };
    setOriginKey(JSON.stringify(draftSourcesRef.current)); setRestoredSources(null);
    setExperienceUsage(proposal.usage); setTargetConditions(proposal.conditions ?? null);
    if (proposal.instruction && chatInput.trim() === proposal.instruction) setChatInput('');
    setChatMessages(messages => [...messages, { role: 'assistant', content: locale === 'zh' ? '已应用建议，可撤销本次修改。' : 'Suggestion applied. You can undo this edit.' }]);
    });
  }

  async function undoEdit() {
    const undo = undoRef.current;
    if (!undo || !editBaseCurrent(undo.base) || contextDirtyRef.current) return;
    const sources = undo.sources ? { profile_sig: await emailDraftDigest(undo.sources.profile),
      target_version: undo.sources.target, contact_sig: await emailDraftDigest(undo.sources.contact) } : undo.restored ?? NO_DRAFT_SOURCES;
    if (!editBaseCurrent(undo.base)) return;
    await changeDraftRef.current({ body: undo.beforeBody, sources }, 'undo', () => undoRef.current === undo && editBaseCurrent(undo.base), () => {
    clearEmailRevisions(); cancelCompose(); action.cancel();
    draftRevisionRef.current += 1; setUserEditRevision(value => value + 1);
    setBody(undo.beforeBody); setExperienceUsage(undo.usage); setTargetConditions(undo.conditions);
    draftSourcesRef.current = undo.sources; setOriginKey(undo.origin); setRestoredSources(undo.restored);
    setChatMessages(messages => [...messages, { role: 'assistant', content: locale === 'zh' ? '已撤销刚才接受的修改。' : 'Undid the last accepted edit.' }]);
    });
  }

  function currentEdit(): EmailEditRequest {
    return { base: captureEditBase(), selection: selection?.body === body ? selection.range : null };
  }
  function handleQuickAction(key: QuickActionKey) {
    if (invalidSelection || scopeNeedsChoice || versionBusyRef.current || metadataRefreshingRef.current || !sourceReadyRef.current || action.busy || profileChanged || profileRegenerating || refineInFlightRef.current !== null) return;
    if (key === 'coursework') {
      if (selection?.body === body) return;
      action.request({ kind: 'coursework', edit: currentEdit() }); return;
    }
    action.request({ kind: 'refine', instruction: QUICK_ACTION_INSTRUCTIONS[key], label: t(`coldEmail.quickActions.${key}`), edit: currentEdit() });
  }
  function handleChatSubmit() {
    const msg = chatInput.trim();
    if (invalidSelection || scopeNeedsChoice || versionBusyRef.current || metadataRefreshingRef.current || !sourceReadyRef.current || action.busy || !msg || profileChanged || profileRegenerating || refineInFlightRef.current !== null) return;
    // Keep the request through provider failure, rejection and close/reopen.
    action.request({ kind: 'refine', instruction: msg, typed: true, edit: currentEdit() });
  }

  // Reveal the strip without recording anything — a draft opened/copied is
  // not a verified send. No evidence = no tracking event.
  const markContacted = useCallback(() => {
    contactedOwnerRef.current = captureOwnerToken();
    setContacted(true);
    setContactedDraftEpoch(sendDraftEpochRef.current);
    setContactedForId(opportunityId);
    setContactedContentKey(copyContentKeyRef.current);
    // opportunityId is now READ here, so it has to be a dep. An empty array
    // would freeze the stamp at whatever id existed on first mount, and a
    // copy on target B would file itself under target A forever.
  }, [opportunityId]);

  // An attestation saves one immutable email snapshot. Generating, copying,
  // and opening an external composer never write an event.
  const confirmSent = useCallback(async () => {
    if (confirmInFlightRef.current || !contactedHere || confirmedHere || contactedContentKey !== copyContentKeyRef.current
      || !contactedOwnerRef.current || !isTokenOwnerStillCurrent(contactedOwnerRef.current)) return;
    // Captured at the click, before any await: the capability belongs to the
    // identity that attested, not to whoever owns the browser by the time the
    // round trip finishes.
    const token = captureOwnerToken();
    const session = sendSessionRef.current;
    const confirmedEpoch = sendDraftEpochRef.current;
    const confirmedContents = confirmationKeyRef.current;
    const attempt = (confirmAttemptRef.current += 1);
    confirmInFlightRef.current = true;
    setSendError(null);
    setConfirming(true);
    // Same session, same attempt: this completion is still the current one.
    // A newer attempt, a target change or a close all retire it.
    const stillCurrent = () =>
      sendSessionRef.current === session && confirmAttemptRef.current === attempt;
    // A real historical write can still update the parent after rebuilding,
    // but its failure must never be attributed to the replacement draft.
    const sameDraft = () => stillCurrent() && sendDraftEpochRef.current === confirmedEpoch
      && confirmationKeyRef.current === confirmedContents;
    try {
      const sentTime = actualSentAt ? new Date(actualSentAt) : null;
      if (!recipient.trim() || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(recipient.trim())
        || !subject.trim() || !body.trim()
        || (sentTime && (!Number.isFinite(sentTime.getTime()) || sentTime.getTime() > Date.now()))) {
        setSendError('invalid-contact'); return;
      }
      // These are the source versions used when this text was last generated
      // or refined. A profile refresh can preserve an older manual draft.
      const sources = draftSourcesRef.current;
      const materialRefs = sources ? [
        { kind: 'profile' as const, version: await contactMaterialVersion(sources.profile) },
        ...(sources.target ? [{ kind: 'target' as const, version: sources.target }] : []),
        { kind: 'contact_context' as const, version: await contactMaterialVersion(sources.contact) },
      ] : [
        ...(restoredSources?.profile_sig ? [{ kind: 'profile' as const, version: restoredSources.profile_sig }] : []),
        ...(restoredSources?.target_version ? [{ kind: 'target' as const, version: restoredSources.target_version }] : []),
        ...(restoredSources?.contact_sig ? [{ kind: 'contact_context' as const, version: restoredSources.contact_sig }] : []),
      ];
      if (!sameDraft() || !isTokenOwnerStillCurrent(token)) return;
      const input = await createContactEventInput(token.uid!, opportunityId, {
        recipient: recipient.trim(), subject, body, actualSentAt: sentTime?.toISOString() ?? null,
        materialRefs,
      });
      if (!sameDraft() || !isTokenOwnerStillCurrent(token)) return;
      const { interaction: record } = await confirmContactEvent(opportunityId, input, token);
      // The owner check is re-read AFTER the await, against the token captured
      // BEFORE it. Same uid at a new epoch is a different capability.
      if (!stillCurrent()) return;
      if (isTokenOwnerStillCurrent(token)) {
        setConfirmedStatus(record?.type);
        setConfirmedForId(opportunityId);
        setSendConfirmed(true);
        setConfirmedDraftEpoch(confirmedEpoch);
        setConfirmedContentKey(confirmedContents);
        onContactConfirmed?.(record ?? null);
      }
      else if (sameDraft()) setSendError('owner-changed');
    } catch (error) {
      if (!sameDraft()) return;
      // A confirmation whose identity moved cannot establish success for
      // this account. Its old-account write outcome may be unknown; show the
      // identity boundary without painting a U1 outcome into U2's session.
      setSendError(!isTokenOwnerStillCurrent(token) ? 'owner-changed'
        : error instanceof ContactEventError && error.code === 'conflict' ? 'contact-conflict'
          : error instanceof ContactEventError && error.code === 'invalid_input' ? 'invalid-contact' : 'confirm');
    } finally {
      if (stillCurrent()) {
        confirmInFlightRef.current = false;
        setConfirming(false);
      }
    }
  }, [opportunityId, onContactConfirmed, actualSentAt, recipient, subject, body, restoredSources, setSendError, contactedHere, contactedContentKey, confirmedHere]);

  // Only asked once a reminder actually exists, so nobody is prompted about
  // notifications for a thing they have not done. 'subscribed' hides the offer;
  // an unsupported browser or a denied permission leaves it null, because
  // neither can be fixed by a button here.
  useEffect(() => {
    if (!followUpDate || pushOffer !== null) return;
    if (!isPushSupported()) return;
    let cancelled = false;
    getPushStatus().then((status) => {
      if (cancelled) return;
      if (status === 'subscribed') setPushOffer('subscribed');
      else if (status === 'default') setPushOffer('available');
    }).catch(() => { /* leave it unknown rather than offer on a guess */ });
    return () => { cancelled = true; };
  }, [followUpDate, pushOffer]);

  const enableNotifications = useCallback(async () => {
    if (!sourceReadyRef.current) return;
    // Two bindings: the draft session (closed / retargeted / re-profiled
    // ends it) and the account that clicked — the permission dialog is a long
    // window, and the endpoint must not be written under whoever is signed in
    // when it closes. The writer refuses on a switch; current() gates paints.
    const current = captureDraftSession();
    const token = captureOwnerToken();
    setPushBusy(true);
    try {
      const key = await getVapidPublicKey();
      if (!current()) return;
      if (key && await subscribeToPush(key, token) && current()) setPushOffer('subscribed');
    } catch { /* a session change, an owner change or a refused write: the offer simply stays; nothing was promised */ } finally {
      // A busy flag carries no account data; reset either way.
      setPushBusy(false);
    }
  }, [captureDraftSession]);

  // Reminder-only. It must never call the contact recorder: that would move
  // last_contacted_at and record a second outreach the student never made.
  const setFollowUp = useCallback(async (days: number) => {
    // Both halves of the reminders cron's predicate, checked here and not
    // only where the chips render. Hiding a button stops a click; it does
    // nothing about a retained handler or a status that changed between the
    // render and the click.
    // Re-derived here rather than reading `followUpDeliverable`: this is the
    // sink, and it must hold even when the DOM gate above passed against an
    // older render of the same target object.
    if (!sourceReadyRef.current || confirmedForId !== opportunityId) return;
    if (reminderTarget?.id !== opportunityId) return;
    if (!canDeliverReminder(reminderTarget, confirmedStatus)) return;
    const token = captureOwnerToken();
    const session = sendSessionRef.current;
    const draftEpoch = sendDraftEpochRef.current;
    const reminderContents = confirmationKeyRef.current;
    // The student's own calendar day, not UTC's. After 7pm in Chicago the UTC
    // date has already rolled over, so "in 1 week" landed on the eighth day —
    // the same arithmetic the tracker's presets had.
    const d = new Date();
    d.setDate(d.getDate() + days);
    const date = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
    const stillCurrent = () =>
      sendSessionRef.current === session && isTokenOwnerStillCurrent(token);
    try {
      await updateInteractionDetails(opportunityId, { remind_at: date }, token);
    } catch {
      if (stillCurrent() && sendDraftEpochRef.current === draftEpoch && confirmationKeyRef.current === reminderContents) setSendError('reminder');
      return;
    }
    if (stillCurrent()) {
      // Preserve the opportunity-level reminder receipt without clearing a
      // confirmation error belonging to a draft built while this write waited.
      if (sendDraftEpochRef.current === draftEpoch && confirmationKeyRef.current === reminderContents) setSendError(null);
      setFollowUpDate(date);
      onReminderSet?.(date);
    }
  }, [opportunityId, reminderTarget, confirmedStatus, confirmedForId, onReminderSet, setSendError]);

  async function handleCopy(checked = false) {
    const owner = captureOwnerToken();
    const session = sendSessionRef.current;
    const draft = sendDraftEpochRef.current;
    const revision = draftRevisionRef.current;
    const contents = copyContentKey;
    const sameContents = () => sendSessionRef.current === session && sendDraftEpochRef.current === draft
      && copyContentKeyRef.current === contents && isTokenOwnerStillCurrent(owner);
    const current = () => sameContents() && draftRevisionRef.current === revision;
    try { await navigator.clipboard.writeText(`Subject: ${subject}\n\n${body}`); }
    catch { if (current()) setCopyFailedFor(contents); return false; }
    if (!current()) return false;
    setCopyFailedFor(null);
    const feedback = { contents, backup: !checked };
    setCopiedFor(feedback);
    setTimeout(() => setCopiedFor(currentFeedback => currentFeedback === feedback ? null : currentFeedback), 2000);
    // A backup copy has no contact/attestation side effect.
    if (checked && sourceReadyRef.current) markContacted();
    return true;
  }

  function startCompose(provider: ComposeProvider) {
    if (composeRef.current || action.busy) return;
    if (!sourceReadyRef.current || contextDirtyRef.current || !paperReadingCurrent || profileChangedRef.current
      || profileChanged || profileRegenerating || targetVersionError || contactEmailBlock(target, subject, { subjectFormatConfirmed })
      || (provider !== 'copy' && !recipient.trim())) {
      if (provider === 'copy') setConditionCheck({ key: composeKeyRef.current, issues: [], message: locale === 'zh'
        ? '当前资料尚未核对。可选择“仅复制草稿”备份，原稿仍保留。'
        : 'The current information has not been checked. Use Copy draft only to keep a backup. Your draft is kept.' });
      return;
    }
    // External composition reserves a blank window during user activation.
    // Copy uses the same bounded checks but does not create a window.
    let popup: Window | null = null;
    if (provider !== 'copy') {
      try { popup = window.open('about:blank', '_blank'); if (popup) popup.opener = null; }
      catch { try { popup?.close(); } catch { /* Inaccessible window. */ } popup = null; }
      if (!popup) { setComposeFailure('popup'); return; }
    }
    const id = ++composeSequence.current;
    const controller = new AbortController();
    const pending: PendingCompose = { id, popup, owner: captureOwnerToken(), key: composeKeyRef.current,
      provider, phase: 'sources', controller, deadline: setTimeout(() => {
        if (composeRef.current?.id === id) cancelCompose('unavailable');
      }, 30_000) };
    composeRef.current = pending; setComposeBusy(true); setComposeFailure(null); setConditionCheck(null);
    action.request({ kind: 'compose', id });
  }

  async function finishCompose(id: number) {
    const pending = composeRef.current;
    if (!pending || pending.id !== id) return;
    const current = () => composeRef.current === pending && pending.key === composeKeyRef.current
      && isTokenOwnerStillCurrent(pending.owner) && !pending.controller.signal.aborted;
    if (!current() || !sourceReadyRef.current || contextDirtyRef.current || !paperReadingCurrent || profileChangedRef.current
      || profileChanged || profileRegenerating || targetVersionError || contactEmailBlock(target, subject, { subjectFormatConfirmed }) || !expectedTargetVersion) {
      cancelCompose(); return;
    }
    pending.phase = 'recipient';
    try {
      const over = ([['current_body', body, 5000], ['subject', subject, 2000]] as const).find(([, value, limit]) => value.length > limit);
      if (over) {
        setConditionCheck({ key: pending.key, issues: [], message: locale === 'zh'
          ? `${over[0] === 'subject' ? '主题' : '正文'}超过核对上限（${over[2]} 个文本单位，部分 emoji 占两个）。全文已保留，可缩短后重试或仅复制草稿。`
          : `${over[0] === 'subject' ? 'Subject' : 'Body'} exceeds the checking limit (${over[2]} text units; some emoji count as two). Your complete draft is kept. Shorten it and retry, or copy the draft only.` });
        cancelCompose('conditions'); return;
      }
      const validation = await validateEmailDraft(subject, body, requestProfile, opportunityId, {
        expectedTargetVersion, contactContext: requestContactContext, signal: pending.controller.signal,
      });
      if (!current()) return;
      requireTargetReceipt(validation, opportunityId, expectedTargetVersion);
      await requireContactReceipt(validation, requestContactContext);
      if (!current()) return;
      const conditions = readEmailTargetConditions(validation);
      if (!conditions || !isEmailConditionIssues(validation.issues)
        || !['ready', 'review_required'].includes(validation.outcome)
        || (validation.outcome === 'ready') !== (validation.issues.length === 0)) throw new Error('Invalid draft check');
      setTargetConditions(conditions);
      if (validation.outcome === 'review_required') {
        setConditionCheck({ key: pending.key, issues: validation.issues }); cancelCompose('conditions'); return;
      }
      if (pending.provider === 'copy') {
        await handleCopy(true);
        if (!current()) return;
      } else {
        if (!recipientEditedRef.current) await verifyComposeRecipient(opportunityId, expectedTargetVersion, recipient.trim(), pending.controller.signal);
        if (!current()) return;
        if (!pending.popup || pending.popup.closed) { cancelCompose(); return; }
        pending.popup.location.href = getMailtoLink(pending.provider);
        markContacted();
      }
      composeRef.current = null; clearTimeout(pending.deadline);
      setComposeBusy(false); setComposeFailure(null); setConditionCheck(null);
    } catch (error) {
      if (!current()) return;
      const failure = targetVersionFailure(error);
      if (failure) reportTargetVersionFailure(failure);
      setConditionCheck({ key: pending.key, issues: [], message: profileInputMessage(error, t) ?? (locale === 'zh'
        ? '本次核对未完成。原稿仍保留；请重试，或选择“仅复制草稿”备份。'
        : 'The check did not finish. Your draft is kept. Retry, or use Copy draft only to keep a backup.') });
      cancelCompose(error instanceof Error && error.message === 'recipient_changed' ? 'recipient' : 'unavailable');
    }
  }

  function getMailtoLink(provider: Exclude<ComposeProvider, 'copy'> = 'default'): string {
    const to = encodeURIComponent(recipient || '');
    const subj = encodeURIComponent(subject);
    const b = encodeURIComponent(body);
    if (provider === 'gmail') return `https://mail.google.com/mail/?view=cm&to=${to}&su=${subj}&body=${b}`;
    if (provider === 'outlook') return `https://outlook.office365.com/mail/deeplink/compose?to=${to}&subject=${subj}&body=${b}`;
    return `mailto:${to}?subject=${subj}&body=${b}`;
  }

  if (!isOpen || retired) return null;

  const hasEditor = variants.length > 0 || profileChanged || !!(subject || body || recipient);
  const showInitialWait = loading && !error && !targetVersionError && !nameRequired && !action.error && profileAvailable
    && (targetReady || targetChecking) && profileRefresh?.status !== 'failed' && profileRefresh?.status !== 'conflict';

  return (
    <div
      className="fixed inset-0 z-[55] flex sm:items-center sm:justify-center"
      role="dialog"
      aria-modal="true"
      aria-labelledby="email-modal-title"
    >
      <div className="absolute inset-0 bg-gray-900/60 backdrop-blur-sm" onClick={closeDraft} aria-hidden="true" />

      <div
        ref={modalRef}
        className="relative w-full sm:max-w-5xl sm:mx-4 bg-white sm:rounded-2xl shadow-2xl h-[100dvh] max-h-[100dvh] sm:h-[90dvh] sm:max-h-[90dvh] min-w-0 flex flex-col overflow-hidden animate-in"
      >
        {/* Header */}
        <div className="flex items-start justify-between gap-2 px-4 sm:px-6 py-3 sm:py-4 border-b border-gray-100 shrink-0">
          <div className="flex min-w-0 items-center gap-3">
            <div className="w-9 h-9 shrink-0 rounded-xl bg-indigo-50 flex items-center justify-center" aria-hidden="true">
              <Mail className="w-5 h-5 text-indigo-600" />
            </div>
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <h2 id="email-modal-title" className="text-lg font-bold text-gray-900">{t('coldEmail.title')}</h2>
                <LabTypeBadge labType={labType} />
              </div>
              <p className="text-sm text-gray-500 truncate max-w-md">{opportunityTitle}</p>
            </div>
          </div>
          <button
            type="button"
            onClick={closeDraft}
            className="shrink-0 p-2 rounded-lg hover:bg-gray-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 transition-colors"
            aria-label={t('coldEmail.closeAria')}
          >
            <X className="w-5 h-5 text-gray-400" aria-hidden="true" />
          </button>
        </div>

        <details className="shrink-0 max-h-[30dvh] overflow-y-auto border-b border-gray-100 px-4 py-2" open={!!contactPolicyBlock}>
          <summary className="cursor-pointer text-sm font-medium text-gray-700">{contactInstructionCopy[locale].title}</summary>
          <ContactInstructionsPanel target={target} subject={subject} subjectFormatConfirmed={subjectFormatConfirmed}
            onConfirmSubjectFormat={(confirmed) => {
              cancelCompose();
              setSubjectFormatConfirmation(confirmed && expectedTargetVersion ? { subject, version: expectedTargetVersion } : null);
            }} onUseSubject={(value) => {
            editorUsedRef.current = true; draftRevisionRef.current += 1; noteUserEdit(); setSubject(value);
          }} />
        </details>
        <ProfileRefreshBanner locale={locale} refresh={profileRefresh} targetRefresh={targetRefresh} targetReady={targetMembershipReady ?? targetReady} profileAvailable={profileAvailable} onBeforeReview={leaveForProfile} />
      <div data-testid="cold-email-draft-status" role={draftPersistence.status === 'failed' || draftPersistence.status === 'conflict' ? 'alert' : 'status'}
        className="shrink-0 border-b border-gray-100 px-5 py-2 text-xs text-gray-600">
        {draftPersistence.status === 'saving' ? (locale === 'zh' ? '正在保存到此浏览器…' : 'Saving on this browser…')
          : draftPersistence.status === 'saved' ? (locale === 'zh' ? (draftRestored ? '已恢复草稿，已保存在此浏览器。' : '已保存在此浏览器。') : (draftRestored ? 'Restored draft. Saved on this browser.' : 'Saved on this browser.'))
          : draftPersistence.status === 'conflict' ? (locale === 'zh' ? '另一窗口修改了草稿。当前内容仍保留，尚未保存；请先复制。' : 'Another window changed the saved draft. Your current text is kept but not saved. Copy it before leaving.')
          : draftPersistence.status === 'failed' ? (locale === 'zh' ? '草稿未能保存。当前内容仍保留，请先复制；重新打开可能只显示上次保存的内容。' : 'Could not save this draft. Your text is kept. Copy it before leaving; reopening may show the last saved version.')
          : (locale === 'zh' ? '草稿只保存在此浏览器。' : 'Drafts are saved only on this browser.')}
        <button type="button" data-testid="cold-email-draft-clear" className="ml-3 underline disabled:opacity-50"
          disabled={versionBusy || draftClosing || ['saving', 'conflict'].includes(draftPersistence.status)} onClick={() => void clearSavedDraft()}>
          {locale === 'zh' ? '删除草稿并重写' : 'Delete draft and start again'}
        </button>
        {draftPersistence.status === 'failed' && <button type="button" data-testid="cold-email-draft-retry"
          disabled={!panelSavable || !supplementSavable || draftClosing} className="ml-3 underline disabled:opacity-50"
          onClick={() => { persistCurrentRef.current(); void draftPersistence.retry(); }}>
          {locale === 'zh' ? '重试保存' : 'Retry saving'}
        </button>}
        {(draftPersistence.status === 'failed' || draftPersistence.status === 'conflict') && <button type="button" className="ml-3 underline"
          onClick={() => { if (window.confirm(locale === 'zh' ? '当前修改未保存。仍然关闭？' : 'Your latest changes are not saved. Close anyway?')) { abandonDraft(); finishClose(); } }}>
          {locale === 'zh' ? '不保存并关闭' : 'Close without saving'}
        </button>}
      </div>
      {metadataRefreshing && sourceReady && !profileChanged && <p role="status" className="shrink-0 px-5 py-2 text-xs text-gray-600">{locale === 'zh' ? '正在核对邮件信息，原稿仍保留。' : 'Checking email details. Your draft is kept.'}</p>}
      {versionError && <div role="alert" className="shrink-0 border-b border-amber-200 bg-amber-50 px-5 py-2 text-sm text-amber-950">{versionError}</div>}
      {action.error && <div role="alert" className="shrink-0 border-b border-amber-200 bg-amber-50 px-5 py-2 text-sm text-amber-950">
        {locale === 'zh' ? (targetRefresh ? '本次操作未执行。草稿和请求仍保留，请核对资料及机会后重试。' : '本次操作未执行。草稿和请求仍保留，请核对资料后重试。') : (targetRefresh ? 'This action did not run. Your draft and request are kept. Review your profile and opportunity and try again.' : 'This action did not run. Your draft and request are kept. Review your profile and try again.')}
        {variants.length === 0 && !profileChanged && <button type="button" className="ml-2 font-semibold underline" disabled={action.busy || !profileAvailable}
          onClick={() => action.request({ kind: 'variants' })}>{t('coldEmail.tryAgain')}</button>}
      </div>}

        {readingReviewRequired && <div role="alert" data-testid="cold-email-reading-changed" className="shrink-0 border-b border-amber-200 bg-amber-50 px-5 py-2 text-sm text-amber-950">{locale === 'zh' ? '论文资料已变化。当前邮件保留，请在“联系目的与背景”中重新确认阅读信息或跳过。' : 'The paper information changed. Your email is kept. Review or skip the reading details in Contact purpose and background.'}</div>}
        {targetVersionError && <div role="alert" className="shrink-0 border-b border-amber-200 bg-amber-50 px-5 py-2 text-sm text-amber-950">
          <p>{t(targetVersionError === 'changed' ? 'coldEmail.targetVersionChanged' : 'coldEmail.targetVersionUnavailable')}</p>
          <button type="button" disabled={action.busy || profileRegenerating || !targetRefresh || targetRefresh.status === 'checking'}
            className="mt-1 font-semibold underline disabled:opacity-50"
            onClick={() => { targetCheckOnlyRef.current = true; void targetRefresh?.refresh().catch(() => false); }}>{t('coldEmail.targetVersionRetry')}</button>
          {!profileChanged && <button type="button" disabled={action.busy || profileRegenerating || !sourceReady}
            className="ml-3 mt-1 font-semibold underline disabled:opacity-50"
            onClick={() => action.request({ kind: 'variants', keepEditor: hasEditor })}>
            {t(hasEditor ? 'coldEmail.regenerateFromProfile' : 'coldEmail.tryAgain')}</button>}
        </div>}

        {/* Loading / Error: each state has the same reachable short-screen
            scroll boundary as the editor. The inner panel grows with text. */}
        {showInitialWait && (
          <div className={styles.statePanel}>
            <div className="min-h-full flex flex-col items-center justify-center px-6 py-10 sm:py-20 gap-4 text-center">
              <Loader2 className="w-8 h-8 shrink-0 text-indigo-500 animate-spin" />
              <p className="text-sm text-gray-500">{t('coldEmail.generating')}</p>
            </div>
          </div>
        )}
        {nameRequired && !loading && (
          <div className={styles.statePanel} data-testid="cold-email-name-required">
            <div className="min-h-full flex flex-col items-center justify-center py-10 sm:py-20 gap-4 px-6 text-center">
              <div className="w-12 h-12 shrink-0 rounded-2xl bg-amber-50 flex items-center justify-center">
                <UserRound className="w-6 h-6 text-amber-600" aria-hidden="true" />
              </div>
              <p className="text-base font-semibold text-gray-900">{t('coldEmail.nameRequiredTitle')}</p>
              <p className="text-sm text-gray-500 max-w-md">{t('coldEmail.nameRequiredBody')}</p>
              <Link
                href="/"
                onClick={leaveForProfile}
                className="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-indigo-600 text-white text-sm font-medium hover:bg-indigo-700 transition-colors"
              >
                {t('coldEmail.nameRequiredCta')}
              </Link>
            </div>
          </div>
        )}
        {error && !nameRequired && (
          <div className={styles.statePanel}>
            <div className="min-h-full flex flex-col items-center justify-center px-6 py-10 sm:py-20 gap-4 text-center">
              <AlertCircle className="w-8 h-8 shrink-0 text-red-500" />
              <p className="text-sm text-red-600 break-words max-w-full">{error}</p>
              {experienceNeedsReview && (
                <Link href="/#experience-library" onClick={leaveForProfile} className="text-sm font-medium text-indigo-600 underline">
                  {t('coldEmail.experienceReviewCta')}
                </Link>
              )}
              <button type="button" onClick={() => action.request({ kind: 'variants' })} className="text-sm text-indigo-600 underline hover:text-indigo-700">{t('coldEmail.tryAgain')}</button>
            </div>
          </div>
        )}

        {/* Two-panel layout */}
        {hasEditor && !loading && !error && !nameRequired && (
          <div className={styles.workspace} data-testid="cold-email-workspace">
            <div className={styles.panels}>
              <div className={`${styles.editorPane} lg:border-r border-gray-100`} data-testid="cold-email-editor">
                {profileChanged && <div role="status" className="mx-5 mt-4 rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
                  <p>{contextChanged ? (locale === 'zh' ? '联系背景已更改。先确认背景，再生成新稿；当前草稿仍保留。' : 'Contact background changed. Confirm it, then generate a new draft. Your current draft is kept.') : draftRestored && (!sourceReady || sourceReview === 'pending') ? (locale === 'zh' ? '尚未核对原稿所用资料。草稿仍保留，联网后会重新核对。' : 'The sources for this draft have not been checked yet. Your draft is kept; they will be checked when online.') : draftRestored && sourceReview === 'unknown' ? (locale === 'zh' ? '无法确认这份旧稿所用的资料。草稿仍保留；请核对后再生成新稿。' : 'The sources for this saved draft could not be confirmed. Your draft is kept; review them before generating a new draft.') : t('coldEmail.profileChanged')}</p>
                  {profileRegenerateError && <p role="alert" className="mt-2">{t(profileRegenerateError === 'edited'
                    ? 'coldEmail.editSuperseded' : profileRegenerateError === 'name-required'
                      ? 'coldEmail.nameRequiredBody' : 'coldEmail.profileRegenerateFailed')}</p>}
                  {profileRegenerateError === 'name-required' && <Link href="/" onClick={leaveForProfile}
                    className="mt-1 inline-block font-medium underline">{t('coldEmail.nameRequiredCta')}</Link>}
                  <button type="button" className="mt-2 rounded-lg border border-amber-300 bg-white px-3 py-2 font-medium disabled:opacity-50"
                    disabled={versionBusy || contextDirty || !sourceReady || action.busy || profileRegenerating} onClick={() => action.request({ kind: 'variants', keepEditor: true })}>
                    {profileRegenerating ? t('coldEmail.generating') : t('coldEmail.regenerateFromProfile')}
                  </button>
                </div>}
                {/* Variant tabs */}
                <div className="flex flex-wrap items-center gap-1 px-5 pt-4 pb-2 shrink-0">
                  {variants.map((v, i) => (
                    <button
                      key={v.id}
                      type="button"
                      disabled={versionBusy} onClick={() => void selectVariant(i)}
                      className={`px-3 py-1.5 rounded-full text-[12px] font-medium transition-all duration-200 ${
                        activeVariant === i
                          ? 'bg-indigo-600 text-white'
                          : 'bg-black/[0.04] text-gray-500 hover:bg-black/[0.08]'
                      }`}
                    >
                      {v.label}
                    </button>
                  ))}
                  <button
                    type="button"
                    onClick={handleAiPillClick}
                    disabled={metadataRefreshing || versionBusy || !sourceReady || !paperReadingCurrent || !!contactPolicyBlock || action.busy || profileChanged || profileRegenerating || aiLoading || refining}
                    title={t('coldEmail.aiVariantTitle')}
                    className={`inline-flex items-center gap-1 px-3 py-1.5 rounded-full text-[12px] font-medium transition-all duration-200 disabled:opacity-60 disabled:cursor-wait ${
                      activeVariant === variants.length && aiVariant
                        ? 'bg-gradient-to-r from-indigo-600 to-fuchsia-500 text-white shadow-sm'
                        : 'bg-indigo-50 text-indigo-600 hover:bg-indigo-100'
                    }`}
                  >
                    {aiLoading ? (
                      <Loader2 className="w-3 h-3 animate-spin" aria-hidden="true" />
                    ) : null}
                    {aiLoading && aiStage
                      ? t(STAGE_LABEL_KEYS[aiStage])
                      : t('coldEmail.aiVariantLabel')}
                  </button>
                </div>

                {/* Tone picker — drives the AI draft's voice. The recommended
                    tone is derived from the detected lab type (no scraping). */}
                <div className="flex items-center gap-1.5 px-5 pb-2 shrink-0 flex-wrap">
                  <span className="text-[11px] font-semibold text-gray-400 uppercase tracking-wider mr-0.5">
                    {t('coldEmail.tone.label')}
                  </span>
                  {STYLE_KEYS.map((s) => {
                    const isActive = activeVariant === variants.length && aiVariant != null && selectedStyle === s;
                    const isRecommended = recommendedStyle === s;
                    return (
                      <button
                        key={s}
                        type="button"
                        onClick={() => handleToneClick(s)}
                        disabled={metadataRefreshing || versionBusy || !sourceReady || !paperReadingCurrent || !!contactPolicyBlock || action.busy || profileChanged || profileRegenerating || aiLoading || refining}
                        className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-[11px] font-medium transition-all duration-200 disabled:opacity-60 disabled:cursor-wait ${
                          isActive
                            ? 'bg-indigo-600 text-white shadow-sm'
                            : 'bg-indigo-50/70 text-indigo-600 hover:bg-indigo-100'
                        }`}
                      >
                        {t(`coldEmail.tone.${s}`)}
                        {isRecommended && (
                          <span
                            className={`text-[9px] font-semibold uppercase tracking-wide px-1 py-px rounded ${
                              isActive ? 'bg-white/25 text-white' : 'bg-indigo-100 text-indigo-500'
                            }`}
                          >
                            {t('coldEmail.tone.recommended')}
                          </span>
                        )}
                      </button>
                    );
                  })}
                </div>

                <div className={`${styles.editorFields} px-5 pb-4 space-y-4`} data-testid="cold-email-editor-fields">
                  <EmailContactContextPanel initialDraft={pendingPanel} onDraftSnapshotChange={panelSnapshotChanged} opportunity={target} targetKey={expectedTargetVersion ?? targetFingerprint} reviewRequested={readingReview} context={requestContactContext} resetKey={`${opportunityId}:${isOpen}:${draftResetKey}`}
                    language={locale === 'zh' ? 'zh' : 'en'} onDraftChange={retireContactDraft} onApply={applyContactContext} />
                  <details className="rounded-xl border border-gray-200 bg-gray-50 p-3" data-testid="cold-email-supplement" open={supplementExpanded}
                    onToggle={(event) => { setSupplementExpanded(event.currentTarget.open); if (event.currentTarget.open && !supplementSession) setSupplementSession({ owner: captureOwnerToken(), targetId: opportunityId, inputKey: incomingProfileKey }); }}>
                    <summary className="cursor-pointer text-sm font-semibold text-gray-800">{locale === 'zh' ? '补充本人贡献（可跳过）' : 'Add your personal contribution (optional)'}</summary>
                    {supplementSession && supplementSession.targetId === opportunityId && <div className="mt-3">
                      <ResumeSupplementPanel opportunityId={opportunityId} initialDraft={pendingSupplement} onDraftSnapshotChange={supplementSnapshotChanged} owner={supplementSession.owner} targetKey={targetFingerprint} purpose="cold_email" profileAvailable={profileAvailable}
                        onAcceptedProfile={(view, againstView) => {
                          const current = supplementInputRef.current, scope = supplementScopeRef.current;
                          if (!current.available || scope !== supplementSession || current.targetId !== scope.targetId
                            || !isTokenOwnerStillCurrent(scope.owner) || !isOwnerTokenValid(view.token, view.token.uid)
                            || !isOwnerTokenValid(againstView.token, againstView.token.uid)
                            || [view.token, againstView.token].some(token => token.uid !== scope.owner.uid || token.epoch !== scope.owner.epoch || token.generation !== scope.owner.generation)) return;
                          if (scope.inputKey === current.key || profileActionKey(againstView.renderedProfile) === current.key) {
                            setSupplementProfile({ view, inputKey: current.key, targetId: scope.targetId });
                          }
                        }} />
                    </div>}
                  </details>
                  <EmailTargetConditionsPanel receipt={targetConditions} current={sourceReady && !profileChanged && !targetVersionError && !contextDirty} />
                  <section className="rounded-xl border border-gray-200 bg-gray-50 p-3 text-xs text-gray-600" data-testid="cold-email-experience">
                    <details>
                      <summary className="cursor-pointer font-semibold text-gray-800">{t('coldEmail.experienceTitle')}</summary>
                      <p className="mt-2">{t('coldEmail.experienceExplanation')}</p>
                      {!experienceUsage ? (
                        <p className="mt-2">{t('coldEmail.experienceUnavailable')}</p>
                      ) : experienceUsage.selected.length === 0 ? (
                        !experienceBudgetOmission && !experienceReceiptLimited && <p className="mt-2">{t('coldEmail.experienceNone')}</p>
                      ) : (
                        <ul className="mt-2 space-y-2">
                          {experienceUsage.selected.map((entry) => (
                            <li key={`${entry.id}:${entry.revision}`} className="break-words">
                              <p className="whitespace-pre-wrap">{entry.excerpt}</p>
                              {entry.context === null && <p className="mt-1 text-gray-500">{locale === 'zh' ? '未指定项目或经历；仅使用这条原文。' : 'No activity assigned; only this original entry is used.'}</p>}
                              {entry.context && <div className="mt-1 whitespace-pre-wrap" data-testid="email-experience-activity">{['title', 'institution', 'organization', 'venue', 'start', 'end', 'date'].map(key => entry.context?.fields[key]).filter(Boolean).map(fact => <p key={fact!.id}>{fact!.value}</p>)}</div>}
                              <span className="text-gray-500">{t(entry.source.kind === 'resume' ? 'coldEmail.experienceSourceResume' : 'coldEmail.experienceSourceManual')}</span>
                            </li>
                          ))}
                        </ul>
                      )}
                    </details>
                    {experienceReceiptLimited && <p className="mt-2">{t('coldEmail.experienceReceiptLimit')}</p>}
                    {(experienceBudgetOmission || experienceNeedsReview || experienceUsage?.needs_review) && (
                      <div className="mt-2 border-t border-gray-200 pt-2" data-testid="cold-email-experience-review">
                        {experienceBudgetOmission && <p>{t('coldEmail.experienceBudgetNote')}</p>}
                        {(experienceNeedsReview || experienceUsage?.needs_review) && <p>{t('coldEmail.experienceReviewNeeded')}</p>}
                        <Link href="/#experience-library" onClick={leaveForProfile} className="mt-1 inline-block font-medium text-indigo-600 underline">
                          {t('coldEmail.experienceReviewCta')}
                        </Link>
                      </div>
                    )}
                  </section>
                  <div>
                    <label htmlFor="cold-email-to" className="block text-xs font-semibold text-gray-500 uppercase tracking-wider mb-1.5">
                      {t('coldEmail.to')}
                    </label>
                    <input
                      id="cold-email-to"
                      type="email"
                      value={recipient}
                      onChange={(e) => { recipientEditedRef.current = true; editorUsedRef.current = true; draftRevisionRef.current += 1; noteUserEdit(); setRecipient(e.target.value); }}
                      placeholder={t('coldEmail.toPlaceholder')}
                      className={`w-full min-w-0 px-3.5 py-2.5 border rounded-xl text-sm text-gray-900 placeholder:text-gray-400 focus:ring-2 focus:ring-indigo-500/30 focus:border-indigo-400 outline-none transition-all ${!recipient ? 'border-amber-300 bg-amber-50/30' : 'border-gray-200'}`}
                    />
                    {!recipient && recipientStatus === 'sign_in_required' ? (
                      /* W10b: a verified address exists behind the sign-in
                         gate — offer sign-in instead of the "we couldn't find
                         one" state, which would be a lie here. */
                      <div className="mt-2 rounded-lg bg-indigo-50 border border-indigo-200 px-3 py-2" data-testid="recipient-sign-in">
                        <p className="text-[12px] font-medium text-indigo-900">
                          {t('coldEmail.signInToRevealTitle')}
                        </p>
                        <p className="mt-0.5 text-[12px] leading-snug text-indigo-700">
                          {t('coldEmail.signInToRevealBody')}
                        </p>
                        <button
                          type="button"
                          onClick={() => openModal({ reason: 'contact-reveal' })}
                          className="mt-1.5 inline-flex items-center px-3 py-1.5 rounded-lg bg-indigo-600 text-white text-[12px] font-semibold hover:bg-indigo-700 transition-colors"
                        >
                          {t('coldEmail.signInToRevealCta')}
                        </button>
                      </div>
                    ) : !recipient ? (
                      <div className="mt-2 rounded-lg bg-amber-50 border border-amber-200 px-3 py-2">
                        <p className="text-[12px] font-medium text-amber-800">
                          {t('coldEmail.emailUnavailableTitle')}
                        </p>
                        <p className="mt-0.5 text-[12px] leading-snug text-amber-700">
                          {t('coldEmail.emailUnavailableBody')}
                        </p>
                        {opportunitySchool && SELF_LOOKUP_DIRECTORIES[opportunitySchool] && (
                          <a
                            href={SELF_LOOKUP_DIRECTORIES[opportunitySchool].url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="mt-1 inline-block text-[12px] font-medium text-amber-800 underline underline-offset-2 hover:text-amber-900"
                          >
                            {t('coldEmail.emailLookupDirectory', {
                              directory: SELF_LOOKUP_DIRECTORIES[opportunitySchool].name,
                            })}
                          </a>
                        )}
                      </div>
                    ) : (
                      <p className="mt-1.5 text-[11px] text-gray-400">
                        {t('coldEmail.verifyBeforeSend')}
                      </p>
                    )}
                  </div>
                  <div>
                    {/* Above the grounding notice: whether the person still
                        holds this post outranks how well-tailored the draft
                        is. 'inactive' is red because the record was actually
                        retired (departed faculty, expired posting); 'stale' is
                        amber because it is only past the re-verification TTL. */}
                    {(freshness === 'inactive' || freshness === 'stale') && (
                      <div
                        className={`mb-3 rounded-lg border px-3 py-2 ${
                          freshness === 'inactive'
                            ? 'bg-red-50 border-red-200'
                            : 'bg-amber-50 border-amber-200'
                        }`}
                        data-testid="freshness-notice"
                      >
                        <p className={`text-[12px] font-medium ${
                          freshness === 'inactive' ? 'text-red-800' : 'text-amber-800'
                        }`}>
                          {freshness === 'inactive'
                            ? t('coldEmail.sourceInactiveTitle')
                            : t('coldEmail.sourceStaleTitle')}
                        </p>
                        <p className={`mt-0.5 text-[12px] leading-snug ${
                          freshness === 'inactive' ? 'text-red-700' : 'text-amber-700'
                        }`}>
                          {freshness === 'inactive'
                            ? t('coldEmail.sourceInactiveBody')
                            : t('coldEmail.sourceStaleBody')}
                        </p>
                      </div>
                    )}
                    {grounding === 'no_target_data' && (
                      /* Evidence honesty: nothing in this record could
                         personalize a draft, so say so instead of letting a
                         generic email pass as tailored homework. */
                      <div className="mb-3 rounded-lg bg-amber-50 border border-amber-200 px-3 py-2" data-testid="grounding-notice">
                        <p className="text-[12px] font-medium text-amber-800">
                          {t('coldEmail.noTargetDataTitle')}
                        </p>
                        <p className="mt-0.5 text-[12px] leading-snug text-amber-700">
                          {t('coldEmail.noTargetDataBody')}
                        </p>
                      </div>
                    )}
                    <label htmlFor="cold-email-subject" className="block text-xs font-semibold text-gray-500 uppercase tracking-wider mb-1.5">{t('coldEmail.subject')}</label>
                    <input
                      id="cold-email-subject"
                      type="text"
                      value={subject}
                      onChange={(e) => { editorUsedRef.current = true; draftRevisionRef.current += 1; noteUserEdit(); setSubject(e.target.value); }}
                      className="w-full min-w-0 px-3.5 py-2.5 border border-gray-200 rounded-xl text-sm font-medium text-gray-900 focus:ring-2 focus:ring-indigo-500/30 focus:border-indigo-400 outline-none transition-all"
                    />
                  </div>
                  <div className="flex-1 flex flex-col">
                    <div className="flex items-center gap-2 mb-1.5">
                      <label htmlFor="cold-email-body" className="block text-xs font-semibold text-gray-500 uppercase tracking-wider">{t('coldEmail.body')}</label>
                      {/* FE-5: durable provenance — the active variant is the AI
                          pill but the backend served the template; say so here so
                          the signal survives chat-scroll and reopen. */}
                      {activeVariant === variants.length && aiVariant && aiVariant.method !== 'ai' && (
                        <span className="text-[10px] font-semibold uppercase tracking-wider px-2 py-0.5 rounded-full bg-amber-50 text-amber-700">
                          {t('coldEmail.templateFallbackBadge')}
                        </span>
                      )}
                    </div>
                    {editUndo && <div className="mb-2 flex flex-wrap items-center gap-2 text-xs text-gray-600">
                      <button type="button" disabled={versionBusy} onClick={() => void undoEdit()} className="rounded-lg border border-gray-300 px-3 py-1.5 font-medium text-gray-800 hover:bg-gray-50">
                        {locale === 'zh' ? '撤销上次接受的修改' : 'Undo last accepted edit'}
                      </button>
                      <span>{locale === 'zh' ? '仅在本次编辑中保留；手改后不再撤销。' : 'Available in this editing session, until a manual edit.'}</span>
                    </div>}
                    <textarea
                      id="cold-email-body"
                      ref={bodyInputRef}
                      onSelect={(event) => {
                        const field = event.currentTarget;
                        const range = captureTextareaSelection(body, field.value, field.selectionStart, field.selectionEnd);
                        if (range) { userActionRevisionRef.current += 1; setSelection({ body, range }); setInvalidSelection(false); setScopeNeedsChoice(false); }
                        else if (field.selectionStart !== field.selectionEnd) { userActionRevisionRef.current += 1; setSelection(null); setInvalidSelection(true); setScopeNeedsChoice(true); }
                      }}
                      value={body}
                      onChange={(e) => { editorUsedRef.current = true; draftRevisionRef.current += 1; noteUserEdit();
                        if (selection || invalidSelection) { setSelection(null); setScopeNeedsChoice(true); }
                        setBody(e.target.value); }}
                      rows={12}
                      className="w-full min-w-0 min-h-64 flex-1 px-3.5 py-2.5 border border-gray-200 rounded-xl text-sm text-gray-700 leading-relaxed focus:ring-2 focus:ring-indigo-500/30 focus:border-indigo-400 outline-none transition-all resize-y"
                    />
                  </div>
                  <EmailVersionHistory locale={locale} versions={savedVersions} busy={versionBusy} error={versionError}
                    comparison={versionCompare ? { version: versionCompare.version, subject: versionCompare.base.subject, body: versionCompare.base.body } : null}
                    onCompare={version => { setVersionError(null); setVersionCompare({ version, base: captureEditBase() }); }}
                    onRestore={() => void restoreSavedVersion()} onCancel={() => setVersionCompare(null)} onDelete={id => void deleteSavedVersion(id)} />
                  <details className="rounded-xl border border-gray-200 px-3.5 py-3 text-xs text-gray-600" data-testid="contact-record-details">
                    <summary className="cursor-pointer font-semibold text-gray-700">{t('coldEmail.contactRecordTitle')}</summary>
                    <p className="mt-2 leading-relaxed">{t('coldEmail.contactRecordHint')}</p>
                    <label className="mt-3 block" htmlFor="cold-email-sent-at">{t('coldEmail.actualSentAt')}</label>
                    <input id="cold-email-sent-at" type="datetime-local" value={actualSentAt}
                      onChange={(event) => setActualSentAt(event.target.value)}
                      className="mt-1 w-full min-w-0 rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm" />
                    <p className="mt-1.5 leading-relaxed">{t('coldEmail.actualSentAtHint')}</p>
                  </details>
                </div>
              </div>

              <div className={`${styles.refinePane} bg-gray-50/60 border-t lg:border-t-0 border-gray-100`} data-has-guidelines={!!labType}>
                {labType && (
                  <div className={`${styles.guidelines} border-b border-gray-100`}>
                    <h3 id="cold-email-guidelines-heading" className="px-4 py-3 text-sm font-semibold text-gray-700 shrink-0">
                      {t('coldEmail.guidelinesTitle')}
                    </h3>
                    <div
                      className={`${styles.guidelinesScroll} px-4 pb-3 focus-visible:outline focus-visible:outline-2 focus-visible:outline-indigo-500`}
                      role="region"
                      aria-labelledby="cold-email-guidelines-heading"
                      tabIndex={0}
                      data-testid="cold-email-guidelines"
                    >
                      <EmailTipsPanel labType={labType} />
                    </div>
                  </div>
                )}

                <section className={styles.conversation} aria-labelledby="cold-email-requests-heading">
                  <h3 id="cold-email-requests-heading" className="flex items-center gap-2 px-4 py-3 border-b border-gray-100 shrink-0 text-sm font-semibold text-gray-700">
                    <Sparkles className="w-4 h-4 shrink-0 text-indigo-500" aria-hidden="true" />
                    {t('coldEmail.aiRequestsTitle')}
                  </h3>

                {/* Chat messages */}
                <div
                  ref={chatHistoryRef}
                  className={`${styles.history} px-4 py-3 space-y-3 focus-visible:outline focus-visible:outline-2 focus-visible:outline-indigo-500`}
                  role="log"
                  aria-label={t('coldEmail.aiRequestsTitle')}
                  tabIndex={0}
                  data-testid="cold-email-chat-history"
                >
                  {chatMessages.map((msg, i) => (
                    <div key={i} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                      <div
                        className={`min-w-0 max-w-[90%] whitespace-pre-wrap break-words px-3 py-2 rounded-xl text-[13px] leading-relaxed ${
                          msg.role === 'user'
                            ? 'bg-indigo-600 text-white rounded-br-sm'
                            : 'bg-white text-gray-700 border border-gray-200 rounded-bl-sm shadow-sm'
                        }`}
                      >
                        {msg.content}
                      </div>
                    </div>
                  ))}
                  {editProposal && <section aria-label={locale === 'zh' ? '待确认的修改建议' : 'Pending edit suggestion'} className="rounded-xl border border-indigo-200 bg-white p-3 space-y-3 text-sm">
                    <p className="font-semibold text-gray-900">{editProposal.selection ? (locale === 'zh' ? '修改所选内容' : 'Edit selected text') : (locale === 'zh' ? '修改整封正文' : 'Edit the full body')}</p>
                    <div><p className="font-semibold text-gray-600">{locale === 'zh' ? '原文' : 'Original'}</p>
                      <p className="whitespace-pre-wrap break-words border-l-2 border-gray-300 pl-2">{editProposal.selection?.text ?? editProposal.base.body}</p></div>
                    <div><p className="font-semibold text-indigo-700">{locale === 'zh' ? '建议' : 'Suggestion'}</p>
                      <p className="whitespace-pre-wrap break-words border-l-2 border-indigo-400 pl-2">{editProposal.selection
                        ? editProposal.afterBody.slice(editProposal.selection.start_utf16, editProposal.afterBody.length - (editProposal.base.body.length - editProposal.selection.end_utf16)) || (locale === 'zh' ? '（删除所选内容）' : '(Delete selected text)')
                        : editProposal.afterBody}</p></div>
                    <div className="flex flex-wrap gap-2">
                      <button type="button" disabled={versionBusy || !sourceReady || action.busy || refining} onClick={() => action.request({ kind: 'accept-edit', id: editProposal.id })}
                        className="rounded-lg bg-indigo-600 px-3 py-2 font-medium text-white disabled:opacity-40">{locale === 'zh' ? '接受建议' : 'Accept suggestion'}</button>
                      <button type="button" onClick={() => { action.cancel(); discardProposal(); }} className="rounded-lg border border-gray-300 px-3 py-2 text-gray-800">{locale === 'zh' ? '拒绝建议' : 'Reject suggestion'}</button>
                    </div>
                  </section>}
                </div>

                <div className="px-4 py-2 text-xs text-gray-600" role="status">
                  {invalidSelection || scopeNeedsChoice ? <>
                    <span data-testid="cold-email-edit-scope-review">{locale === 'zh' ? '请重新选择要修改的段落，或明确改为整封。原稿和要求仍保留。' : 'Select the passage again, or explicitly use the full body. Your draft and request are kept.'}</span>
                    <button type="button" onClick={() => { userActionRevisionRef.current += 1; setSelection(null); setInvalidSelection(false); setScopeNeedsChoice(false); }} className="ml-2 underline text-indigo-700">{locale === 'zh' ? '改为整封' : 'Use full body'}</button>
                  </> : selection?.body === body ? <>
                    <span>{locale === 'zh' ? '本次只修改选中的内容；加入课程需切回整封。' : 'This request edits only the selected text. Use full body to add coursework.'}</span>
                    <button type="button" onClick={() => { userActionRevisionRef.current += 1; setSelection(null); setInvalidSelection(false); setScopeNeedsChoice(false); }} className="ml-2 rounded underline underline-offset-2 text-indigo-700">{locale === 'zh' ? '改为整封' : 'Use full body'}</button>
                  </> : (locale === 'zh' ? '修改整封正文；在正文中选中一段可只改该段。' : 'Edit the full body, or select a passage in the body to edit only that passage.')}
                </div>
                {/* Quick actions */}
                <div className="px-4 pb-2 shrink-0">
                  <div className="flex flex-wrap gap-1.5">
                    {QUICK_ACTION_KEYS.map((key) => (
                      <button
                        key={key}
                        type="button"
                        onClick={() => handleQuickAction(key)}
                        disabled={metadataRefreshing || versionBusy || scopeNeedsChoice || invalidSelection || (key === 'coursework' && selection?.body === body) || !sourceReady || !paperReadingCurrent || !!contactPolicyBlock || action.busy || profileChanged || profileRegenerating || refining}
                        className="px-2.5 py-1 rounded-full text-[11px] font-medium bg-white border border-gray-200 text-gray-600 hover:bg-gray-100 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                      >
                        {t(`coldEmail.quickActions.${key}`)}
                      </button>
                    ))}
                  </div>
                </div>

                {/* Chat input */}
                <div className="px-4 pb-4 pt-2 shrink-0">
                  <form
                    onSubmit={(e) => { e.preventDefault(); handleChatSubmit(); }}
                    className="flex items-center gap-2"
                  >
                    <input
                      type="text"
                      value={chatInput}
                      onChange={(e) => { noteUserEdit(); setChatInput(e.target.value); }}
                      placeholder={t('coldEmail.refinePlaceholder')}
                      aria-label={t('coldEmail.requestLabel')}
                      className="min-w-0 flex-1 px-3 py-2 border border-gray-200 rounded-xl text-sm bg-white placeholder:text-gray-400 focus:ring-2 focus:ring-indigo-500/20 outline-none transition-all"
                    />
                    <button
                      type="submit"
                      aria-label={t('coldEmail.submitRequest')}
                      disabled={metadataRefreshing || versionBusy || scopeNeedsChoice || invalidSelection || !sourceReady || !paperReadingCurrent || !!contactPolicyBlock || action.busy || !chatInput.trim() || profileChanged || profileRegenerating || refining}
                      className="p-2 rounded-xl bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors shrink-0"
                    >
                      <Send className="w-4 h-4" />
                    </button>
                  </form>
                </div>
                </section>
              </div>
            </div>

            {/* Post-draft strip — appears once the email is copied/opened.
                First asks for explicit confirmation that the email was
                actually sent (copying/opening a draft is not a send); only
                after the user confirms is the contact recorded and the
                follow-up reminder offered. */}
            {contactedHere && (
              <div className="flex flex-wrap items-center gap-2 px-6 py-2.5 border-t border-gray-100 bg-amber-50/60 shrink-0 text-sm">
                {!confirmedHere ? (
                  <>
                    <span className="inline-flex items-center gap-1.5 text-gray-600">
                      <Send className="w-4 h-4 text-amber-500" />
                      {t('coldEmail.sentQuestion')}
                    </span>
                    <button
                      type="button"
                      onClick={() => { void confirmSent(); }}
                      disabled={confirming}
                      data-testid="cold-email-confirm-sent"
                      className="px-2.5 py-1 rounded-lg border border-amber-200 bg-white text-[12px] font-medium text-amber-700 hover:bg-amber-100 transition-colors disabled:opacity-60 disabled:cursor-wait"
                    >
                      {confirming
                        ? t('coldEmail.confirming')
                        : sendError === 'confirm'
                          ? t('coldEmail.confirmRetry')
                          : t('coldEmail.confirmSent')}
                    </button>
                    {(sendError === 'confirm' || sendError === 'owner-changed' || sendError === 'invalid-contact' || sendError === 'contact-conflict') && (
                      <span className="inline-flex items-center gap-1.5 text-red-600" role="status">
                        <AlertCircle className="w-4 h-4 shrink-0" aria-hidden="true" />
                        {t(sendError === 'confirm' ? 'coldEmail.confirmFailed'
                          : sendError === 'invalid-contact' ? 'coldEmail.contactInvalid'
                          : sendError === 'contact-conflict' ? 'coldEmail.contactConflict'
                          : 'coldEmail.confirmOwnerChanged')}
                      </span>
                    )}
                  </>
                ) : confirmedStatus === undefined ? (
                  <span className="text-gray-600">{t('coldEmail.contactRecordedNoStatus')}</span>
                ) : confirmedStatus === 'dismissed' || confirmedStatus === 'rejected' ? (
                  // The confirm RPC never downgrades a status, so a row the
                  // student had already marked reaches here after a perfectly
                  // real send and comes back unchanged. Saying only that a
                  // reminder is unavailable left them believing the outreach
                  // was on their board — and for 'dismissed' the tracker omits
                  // the row from every column, so it is nowhere at all.
                  <span className="inline-flex items-center gap-1.5 text-gray-500">
                    <BellRing className="w-4 h-4 text-gray-400" />
                    {t(
                      confirmedStatus === 'dismissed'
                        ? 'coldEmail.confirmedKeptDismissed'
                        : 'coldEmail.confirmedKeptStatus',
                    )}
                  </span>
                ) : !followUpDeliverable ? (
                  // The whole reminder block, not just the chips. Offering
                  // "want a reminder?" and then having nothing to offer is
                  // the same false capability one step earlier.
                  <span className="inline-flex items-center gap-1.5 text-gray-500">
                    <BellRing className="w-4 h-4 text-gray-400" />
                    {t('coldEmail.reminderUnavailable')}
                  </span>
                ) : (
                  <>
                    {followUpDate ? (
                      <span className="inline-flex items-center gap-1.5 font-medium text-amber-700">
                        <BellRing className="w-4 h-4" />
                        {t('coldEmail.reminderSet', { date: followUpDate })}
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1.5 text-gray-600">
                        <BellRing className="w-4 h-4 text-amber-500" />
                        {t('coldEmail.remindPrompt')}
                      </span>
                    )}
                    {/* The chips stay after a date is chosen: a reminder is
                        changeable, and changing it must go through the same
                        reminder-only write rather than another confirmation. */}
                    {([['coldEmail.remind3', 3], ['coldEmail.remind7', 7], ['coldEmail.remind14', 14]] as const).map(
                      ([key, days]) => (
                        <button
                          key={days}
                          type="button"
                          disabled={!sourceReady}
                          onClick={() => { void setFollowUp(days); }}
                          className="px-2.5 py-1 rounded-lg border border-amber-200 bg-white text-[12px] font-medium text-amber-700 hover:bg-amber-100 transition-colors"
                        >
                          {t(key)}
                        </button>
                      ),
                    )}
                    {followUpDate && pushOffer === 'available' && (
                      <span className="inline-flex items-center gap-1.5 text-[12px] text-gray-500">
                        {t('coldEmail.reminderInAppOnly')}
                        <button
                          type="button"
                          disabled={!sourceReady || pushBusy}
                          onClick={() => { void enableNotifications(); }}
                          className="font-semibold text-indigo-600 hover:text-indigo-700 underline underline-offset-2 disabled:opacity-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 rounded"
                        >
                          {t('coldEmail.reminderEnablePush')}
                        </button>
                      </span>
                    )}
                    {sendError === 'reminder' && (
                      <span className="inline-flex items-center gap-1.5 text-red-600" role="status">
                        <AlertCircle className="w-4 h-4" aria-hidden="true" />
                        {t('coldEmail.reminderFailed')}
                      </span>
                    )}
                  </>
                )}
              </div>
            )}

            {/* Footer */}
            <div className="flex flex-wrap items-center justify-end gap-2 px-4 sm:px-6 py-3 border-t border-gray-100 bg-gray-50/50 shrink-0" data-testid="cold-email-footer">
              {conditionCheck?.key === composeKey && <div role="status" data-testid="email-condition-review" className="w-full max-h-[18dvh] overflow-y-auto text-xs text-amber-900">
                {conditionCheck.message && <p>{conditionCheck.message}</p>}
                {conditionCheck.issues.length > 0 && <ul className="list-disc pl-4 space-y-1">{conditionCheck.issues.map(issue => <li key={issue}>{emailConditionIssueText(issue, locale)}</li>)}</ul>}
              </div>}
              {(composeBusy || composeFailure) && <p role="status" data-testid="cold-email-compose-status" className="w-full text-xs text-amber-900">
                {composeBusy ? (locale === 'zh' ? '正在核对草稿、资料和目标条件…' : 'Checking your draft, profile and target conditions…')
                  : composeFailure === 'conditions' ? (locale === 'zh' ? '请核对提示内容。原稿保留，邮件尚未打开。' : 'Review the flagged points. Your draft is kept; no email was opened.')
                  : composeFailure === 'popup' ? (locale === 'zh' ? '浏览器阻止了新窗口。请允许弹窗后重试；邮件尚未打开。' : 'The browser blocked the new window. Allow popups and try again; no email was opened.')
                  : composeFailure === 'recipient' ? (locale === 'zh' ? '官网收件地址已改变或无法确认。草稿仍保留，请核对收件人后重试。' : 'The source email address changed or could not be verified. Your draft is kept; review the recipient before trying again.')
                  : (locale === 'zh' ? '本次核对未完成，邮件尚未打开。草稿仍保留，请重试。' : 'The check did not finish, so no email was opened. Your draft is kept; try again.')}
              </p>}
              {copyFailed && (
                <span className="inline-flex items-center gap-1.5 text-[12px] text-red-600" role="status">
                  <AlertCircle className="w-4 h-4 shrink-0" aria-hidden="true" />
                  {t('coldEmail.copyFailed')}
                </span>
              )}
              <button
                type="button"
                onClick={() => startCompose('copy')}
                disabled={composeBusy || action.busy}
                className="inline-flex items-center gap-2 px-4 py-2.5 text-sm font-medium text-gray-700 bg-white border border-gray-200 rounded-xl hover:bg-gray-50 transition-colors"
              >
                {copied ? (
                  <><CheckCircle className="w-4 h-4 text-emerald-500" />{t('coldEmail.copied')}</>
                ) : (
                  <><Copy className="w-4 h-4" />{t('coldEmail.copy')}</>
                )}
              </button>
              <button type="button" onClick={() => { cancelCompose(); void handleCopy(false); }}
                className="px-2 py-2 text-xs text-gray-600 underline" data-testid="copy-draft-only">
                {backupCopied ? (locale === 'zh' ? '草稿已复制' : 'Draft copied') : (locale === 'zh' ? '仅复制草稿' : 'Copy draft only')}
              </button>
              {!contactedHere && <button type="button" onClick={() => { cancelCompose(); markContacted(); }} disabled={confirming}
                className="px-2 py-2 text-xs text-gray-600 underline disabled:opacity-50" data-testid="record-sent-email">
                {locale === 'zh' ? '记录已发送的邮件' : 'Record an email already sent'}
              </button>}
              {/* FE-2: the deep-link send buttons open a real compose window, so
                  disable them when no recipient is resolved — otherwise the user
                  is dropped into a draft addressed to nobody with no warning. The
                  amber "To" hint above guides them to add an address; the Copy
                  button stays enabled since pasting elsewhere is still useful. */}
              <div
                className="grid w-full min-w-0 grid-cols-2 rounded-xl overflow-hidden shadow-sm sm:flex sm:w-auto"
                title={!recipient.trim() ? t('coldEmail.toHint') : undefined}
              >
                <button
                  type="button"
                  disabled={!sourceReady || !paperReadingCurrent || !!contactEmailBlock(target, subject, { subjectFormatConfirmed }) || action.busy || composeBusy || contextDirty || profileChanged || profileRegenerating || !!targetVersionError || !recipient.trim()}
                  onClick={() => startCompose('default')}
                  className="col-span-2 inline-flex items-center justify-center gap-2 px-5 py-2.5 text-sm font-semibold text-white bg-gradient-to-r from-indigo-600 to-indigo-500 hover:from-indigo-700 hover:to-indigo-600 transition-all disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  <ExternalLink className="w-4 h-4" />
                  {t('coldEmail.openInEmail')}
                </button>
                <div className="hidden w-px bg-indigo-400 sm:block" />
                <button
                  type="button"
                  disabled={!sourceReady || !paperReadingCurrent || !!contactEmailBlock(target, subject, { subjectFormatConfirmed }) || action.busy || composeBusy || contextDirty || profileChanged || profileRegenerating || !!targetVersionError || !recipient.trim()}
                  onClick={() => startCompose('gmail')}
                  className="inline-flex items-center justify-center px-3 py-2.5 text-[11px] font-semibold text-indigo-100 bg-indigo-600 hover:bg-indigo-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                  title={t('coldEmail.openGmailTitle')}
                >
                  {t('coldEmail.gmail')}
                </button>
                <button
                  type="button"
                  disabled={!sourceReady || !paperReadingCurrent || !!contactEmailBlock(target, subject, { subjectFormatConfirmed }) || action.busy || composeBusy || contextDirty || profileChanged || profileRegenerating || !!targetVersionError || !recipient.trim()}
                  onClick={() => startCompose('outlook')}
                  className="inline-flex items-center justify-center px-3 py-2.5 text-[11px] font-semibold text-indigo-100 bg-indigo-600 hover:bg-indigo-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                  title={t('coldEmail.openOutlookTitle')}
                >
                  {t('coldEmail.outlook')}
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
