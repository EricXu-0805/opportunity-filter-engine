'use client';

import { useCallback, useEffect, useId, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { useLocale } from '@/i18n/client';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import type { ProfileViewSnapshot } from '@/lib/profile-sync';
import ResumeSupplementPanel from './ResumeSupplementPanel';
import TargetResumeAiPanel from './TargetResumeAiPanel';
import type { Opportunity, ProfileData } from '@/lib/types';
import { sourceDigest, validateExperienceEntries } from '@/lib/experience-evidence';
import { buildResumeMasterPreview, validateResumeMaster } from '@/lib/resume-master';
import {
  createTargetResume, suggestTargetResumeOrder, targetResumeContextFromOpportunity,
  targetResumeContextSignature, targetResumeProfileSignature, validateTargetResume,
  type LoadedTargetResume, type TargetResumeLine, type TargetResumeV1,
} from '@/lib/target-resume';
import {
  loadTargetResume, loadTargetResumeHistory, loadTargetResumeVersion, saveTargetResume,
  type TargetResumeVersionSummary,
} from '@/lib/target-resume-storage';
import {
  captureOwnerToken, isOwnerTokenValid, isTokenOwnerStillCurrent, onLocalOwnerStateChange, type OwnerToken,
} from '@/lib/identity-owner';

type Scope = { active: boolean; owner: OwnerToken; targetId: string; context: string; creation: number; historyRequest: number; historyGeneration: number; historyListRequest: number };
type Session = {
  scope: Scope; phase: 'loading' | 'load-error' | 'idle' | 'creating' | 'doc';
  doc: TargetResumeV1 | null; revision: number; savedJson: string | null; editRevision: number;
  saving: boolean; reloading: boolean; conflict: LoadedTargetResume | null;
  error: 'create' | 'invalid' | 'save' | 'missing' | 'unavailable' | 'reload' | 'context' | null;
  history: TargetResumeVersionSummary[] | null; historyBusy: boolean; historyError: boolean; historyHasMore: boolean;
  selectedRevision: number | null; selectedVersion: LoadedTargetResume | null; versionBusy: boolean; versionError: boolean;
};
type LeaveAction = 'close' | 'legacy' | 'master' | 'rebuild';
const clone = <T,>(value: T): T => JSON.parse(JSON.stringify(value)) as T;
// Synchronous content equality retires creation before a late digest completes.
function canonical(value: unknown): string {
  return JSON.stringify(value, (_key, item: unknown) => !item || typeof item !== 'object' || Array.isArray(item)
    ? item : Object.fromEntries(Object.entries(item as Record<string, unknown>).sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0)));
}
const button = 'rounded-lg border border-gray-300 px-3 py-2 text-sm disabled:opacity-40';
const isDirty = (session: Session) => !!session.doc && canonical(session.doc) !== session.savedJson;

export default function FullTargetResumeModal({ isOpen, onClose, profile, opportunity, onOpenLegacy, onCloseRequestChange }: {
  isOpen: boolean; onClose: () => void; profile: ProfileData; opportunity: Opportunity; onOpenLegacy?: () => void;
  onCloseRequestChange?: (request: (() => boolean) | null) => void;
}) {
  const locale = useLocale();
  const copy = (en: string, zh: string) => locale === 'zh' ? zh : en;
  const domId = useId();
  const router = useRouter();
  const incomingProfileKey = canonical(profile);
  const [supplementProfile, setSupplementProfile] = useState<{ view: ProfileViewSnapshot; inputKey: string } | null>(null);
  const acceptedProfile = supplementProfile && supplementProfile.inputKey === incomingProfileKey
    && isOwnerTokenValid(supplementProfile.view.token, supplementProfile.view.token.uid)
    ? supplementProfile.view.renderedProfile : profile;
  const profileKey = canonical(acceptedProfile);
  const target = targetResumeContextFromOpportunity(opportunity);
  const targetKey = canonical(target);
  const contextKey = `${profileKey}\n${targetKey}`;
  const profileSnapshot = useMemo<ProfileData>(() => JSON.parse(profileKey), [profileKey]);
  const targetSnapshot = useMemo(() => JSON.parse(targetKey) as typeof target, [targetKey]);
  const [checks, setChecks] = useState<{ key: string; profile: string; target: string; source: string; canCreate: boolean } | null>(null);
  const [session, setSession] = useState<Session | null>(null);
  const [lifecycle, setLifecycle] = useState(0);
  const [leave, setLeave] = useState<LeaveAction | null>(null);
  const [supplementOpen, setSupplementOpen] = useState(false);
  const [supplementMounted, setSupplementMounted] = useState(false);
  const [supplementDirty, setSupplementDirty] = useState(false);
  const [aiDirty, setAiDirty] = useState(false);
  const supplementInputRef = useRef<string | null>(null);
  const incomingProfileRef = useRef(incomingProfileKey);
  const routerRef = useRef(router);
  useLayoutEffect(() => {
    if (incomingProfileRef.current !== incomingProfileKey) {
      // A newly rendered parent profile replaces this temporary accepted view.
      setSupplementProfile(null);
    }
    incomingProfileRef.current = incomingProfileKey; routerRef.current = router;
  }, [incomingProfileKey, router]);
  const scopeRef = useRef<Scope | null>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef(onClose);
  const legacyRef = useRef(onOpenLegacy);
  useLayoutEffect(() => { closeRef.current = onClose; legacyRef.current = onOpenLegacy; }, [onClose, onOpenLegacy]);
  const current = useCallback((scope: Scope) => scope.active && scopeRef.current === scope
    && isTokenOwnerStillCurrent(scope.owner) && captureOwnerToken().generation === scope.owner.generation, []);
  const update = useCallback((scope: Scope, change: (old: Session) => Session) => {
    if (!current(scope)) return;
    setSession((old) => old?.scope === scope ? change(old) : old);
  }, [current]);
  const exit = useCallback((action: 'close' | 'legacy' | 'master') => {
    if (scopeRef.current) scopeRef.current.active = false;
    setLeave(null);
    if (action === 'legacy') legacyRef.current?.();
    else { closeRef.current(); if (action === 'master') routerRef.current.push('/#resume-master'); }
  }, []);

  useEffect(() => {
    if (!isOpen) return;
    let active = true;
    void Promise.all([
      targetResumeProfileSignature(profileSnapshot), targetResumeContextSignature(targetSnapshot),
      sourceDigest(profileSnapshot.resume_text ?? ''),
    ]).then(([profileSignature, targetSignature, source]) => {
      const master = validateResumeMaster(profileSnapshot.resume_master);
      const entries = validateExperienceEntries(profileSnapshot.experience_entries);
      const preview = master.ok && master.value && entries.ok ? buildResumeMasterPreview(master.value, entries.value,
        { rawText: profileSnapshot.resume_text ?? '', expectedDigest: source }) : null;
      if (active) setChecks({ key: contextKey, profile: profileSignature, target: targetSignature, source,
        canCreate: !!preview?.sections.some((section) => section.blocks.some((block) => block.lines.length > 0)) });
    }).catch(() => { if (active) setChecks(null); });
    return () => { active = false; };
  }, [isOpen, contextKey, profileSnapshot, targetSnapshot]);

  useLayoutEffect(() => {
    if (!isOpen) {
      // Closing the whole workspace retires its private answer buffer.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setSupplementDirty(false); setAiDirty(false); setSupplementMounted(false); setSupplementOpen(false);
      supplementInputRef.current = null;
      return;
    }
    const previous = scopeRef.current;
    const scope: Scope = { active: true, owner: captureOwnerToken(), targetId: opportunity.id,
      context: contextKey, creation: 0, historyRequest: 0, historyGeneration: 0, historyListRequest: 0 };
    scopeRef.current = scope;
    // A target-document read retry does not discard independent answers.
    if (!previous || previous.targetId !== scope.targetId || previous.owner.uid !== scope.owner.uid
      || previous.owner.epoch !== scope.owner.epoch || previous.owner.generation !== scope.owner.generation) {
      setSupplementDirty(false); setAiDirty(false); setSupplementMounted(false); setSupplementOpen(false);
      supplementInputRef.current = null;
    }
    // Opening/retrying/target replacement defines a new private document scope.
    setSession({ scope, phase: 'loading', doc: null, revision: 0, savedJson: null, editRevision: 0,
      saving: false, reloading: false, conflict: null, error: null, history: null, historyBusy: false,
      historyError: false, historyHasMore: false, selectedRevision: null, selectedVersion: null, versionBusy: false, versionError: false });
    setLeave(null);
    const unsubscribe = onLocalOwnerStateChange(() => {
      if (!scope.active) return;
      const next = captureOwnerToken();
      if (!isTokenOwnerStillCurrent(scope.owner)) {
        scope.active = false; setSession(null); setLeave(null); closeRef.current(); return;
      }
      if (next.generation !== scope.owner.generation && isOwnerTokenValid(next, next.uid)) {
        scope.active = false; setLifecycle((old) => old + 1);
      }
    });
    void loadTargetResume(opportunity.id, scope.owner).then((loaded) => {
      update(scope, (old) => loaded === null ? { ...old, phase: 'idle' }
        : { ...old, phase: 'doc', doc: clone(loaded.doc), revision: loaded.revision, savedJson: canonical(loaded.doc) });
    }).catch(() => update(scope, (old) => ({ ...old, phase: 'load-error' })));
    return () => { scope.active = false; unsubscribe(); };
    // Content-only changes preserve local work and retire creation below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOpen, opportunity.id, lifecycle, update]);

  useLayoutEffect(() => {
    const scope = scopeRef.current;
    if (!isOpen || !scope?.active || scope.context === contextKey) return;
    scope.context = contextKey; scope.creation += 1;
    update(scope, (old) => ({ ...old, phase: old.phase === 'creating' ? old.doc ? 'doc' : 'idle' : old.phase,
      error: old.phase === 'creating' ? 'context' : old.error }));
  }, [isOpen, contextKey, update]);

  const activeSession = isOpen && session?.scope.targetId === opportunity.id
    && isTokenOwnerStillCurrent(session.scope.owner) ? session : null;
  const ownerReady = !!activeSession && isOwnerTokenValid(activeSession.scope.owner, activeSession.scope.owner.uid);
  const dirty = !!activeSession && isDirty(activeSession);
  const doc = activeSession?.doc ?? null;
  const comparable = checks?.key === contextKey ? checks : null;
  const outdated = !!doc && !!comparable && (doc.base.profile_signature !== comparable.profile
    || doc.base.target_signature !== comparable.target || doc.base.source_signature !== comparable.source);
  const creating = activeSession?.phase === 'creating';
  const canEdit = ownerReady && !!doc && !creating && !activeSession?.reloading;
  const askLeave = useCallback((action: 'close' | 'legacy' | 'master') => {
    if (supplementDirty || aiDirty || (session && isDirty(session))) { setLeave(action); return false; }
    exit(action); return true;
  }, [session, supplementDirty, aiDirty, exit]);

  const leaveRef = useRef(askLeave);
  useLayoutEffect(() => { leaveRef.current = askLeave; }, [askLeave]);
  useLayoutEffect(() => {
    if (!isOpen) return;
    onCloseRequestChange?.(() => leaveRef.current('close'));
    return () => onCloseRequestChange?.(null);
  }, [isOpen, onCloseRequestChange]);
  useEffect(() => {
    if (!isOpen) return;
    const previousFocus = document.activeElement as HTMLElement | null;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    panelRef.current?.querySelector<HTMLButtonElement>('button')?.focus();
    const keydown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') { event.preventDefault(); leaveRef.current('close'); return; }
      if (event.key !== 'Tab') return;
      const items = Array.from(panelRef.current?.querySelectorAll<HTMLElement>('button:not([disabled]), a[href], input:not([disabled]), textarea:not([disabled]), select:not([disabled]), summary') ?? [])
        .filter((item) => !item.closest('[hidden]') && (!item.closest('details:not([open])') || item.tagName === 'SUMMARY'));
      if (!items.length) return;
      if (event.shiftKey && document.activeElement === items[0]) { event.preventDefault(); items.at(-1)?.focus(); }
      else if (!event.shiftKey && document.activeElement === items.at(-1)) { event.preventDefault(); items[0].focus(); }
    };
    document.addEventListener('keydown', keydown);
    return () => { document.body.style.overflow = previousOverflow; document.removeEventListener('keydown', keydown); previousFocus?.focus(); };
  }, [isOpen]);

  const edit = (change: (draft: TargetResumeV1) => void) => {
    if (!activeSession || !canEdit) return;
    update(activeSession.scope, (old) => {
      if (!old.doc) return old;
      const next = clone(old.doc); change(next);
      return { ...old, doc: next, editRevision: old.editRevision + 1, error: null };
    });
  };
  const create = async () => {
    if (!activeSession || !ownerReady || !comparable?.canCreate || activeSession.saving || activeSession.reloading || activeSession.conflict) return;
    const scope = scopeRef.current;
    if (!scope || scope !== activeSession.scope || !current(scope)) return;
    const creation = ++scope.creation;
    scope.historyGeneration += 1; scope.historyRequest += 1;
    update(scope, (old) => ({ ...old, phase: 'creating', error: null, history: null, historyBusy: false, historyHasMore: false,
      selectedVersion: null, selectedRevision: null, versionBusy: false, versionError: false }));
    setLeave(null);
    try {
      const next = await createTargetResume(profileSnapshot, targetSnapshot, activeSession.doc?.id);
      if (!current(scope) || scope.creation !== creation) return;
      update(scope, (old) => ({ ...old, phase: 'doc', doc: next, editRevision: old.editRevision + 1, error: null }));
    } catch {
      if (current(scope) && scope.creation === creation) update(scope, (old) => ({ ...old, phase: old.doc ? 'doc' : 'idle', error: 'create' }));
    }
  };
  const persist = async (payload: TargetResumeV1) => {
    if (!activeSession || !ownerReady || activeSession.saving || activeSession.reloading || activeSession.conflict) return;
    const validation = validateTargetResume(payload);
    if (!validation.ok) { update(activeSession.scope, (old) => ({ ...old, error: 'invalid' })); return; }
    const { revision, editRevision } = activeSession;
    const scope = scopeRef.current;
    if (!scope || scope !== activeSession.scope || !current(scope)) return;
    const snapshot = clone(validation.value);
    update(scope, (old) => ({ ...old, saving: true, error: null }));
    try {
      const result = await saveTargetResume(snapshot, revision, scope.owner);
      if (!current(scope)) return;
      if (result.status === 'saved' || result.status === 'unchanged') {
        scope.historyGeneration += 1; scope.historyRequest += 1; setLeave(null);
        update(scope, (old) => ({ ...old,
        doc: old.editRevision === editRevision ? clone(result.value.doc) : old.doc,
        phase: 'doc', revision: result.value.revision, savedJson: canonical(result.value.doc), saving: false,
        conflict: null, error: null, history: null, historyBusy: false, historyHasMore: false, versionBusy: false,
        selectedVersion: null, selectedRevision: null }));
      } else if (result.status === 'conflict') update(scope, (old) => ({ ...old, saving: false, conflict: result.current }));
      else update(scope, (old) => ({ ...old, saving: false,
        error: result.status === 'missing' ? 'missing' : result.status === 'unavailable' || result.status === 'abandoned' ? 'unavailable' : 'save' }));
    } catch { update(scope, (old) => ({ ...old, saving: false, error: 'save' })); }
  };
  const reloadServer = async () => {
    if (!activeSession || !ownerReady || activeSession.saving || activeSession.reloading) return;
    const scope = scopeRef.current;
    if (!scope || scope !== activeSession.scope || !current(scope)) return;
    update(scope, (old) => ({ ...old, reloading: true, error: null }));
    try {
      const loaded = await loadTargetResume(opportunity.id, scope.owner);
      if (!loaded) { update(scope, (old) => ({ ...old, reloading: false, error: 'missing' })); return; }
      if (!current(scope)) return;
      scope.historyGeneration += 1; scope.historyRequest += 1;
      update(scope, (old) => ({ ...old, phase: 'doc', doc: clone(loaded.doc), revision: loaded.revision,
        savedJson: canonical(loaded.doc), editRevision: old.editRevision + 1, conflict: null, reloading: false,
        selectedVersion: null, selectedRevision: null, history: null, historyBusy: false, historyHasMore: false, versionBusy: false }));
    } catch { update(scope, (old) => ({ ...old, reloading: false, error: 'reload' })); }
  };
  const history = async (older = false) => {
    if (!activeSession || !ownerReady || activeSession.historyBusy) return;
    const scope = scopeRef.current;
    if (!scope || scope !== activeSession.scope || !current(scope)) return;
    const before = older ? activeSession.history?.at(-1)?.revision : undefined;
    if (older && (!before || !activeSession.historyHasMore)) return;
    if (!older) scope.historyGeneration += 1;
    const generation = scope.historyGeneration;
    const request = ++scope.historyListRequest;
    update(scope, (old) => ({ ...old, historyBusy: true, historyError: false,
      ...(!older ? { selectedRevision: null, selectedVersion: null, versionBusy: false, versionError: false } : {}) }));
    try {
      const versions = await loadTargetResumeHistory(opportunity.id, scope.owner, before);
      if (current(scope) && scope.historyGeneration === generation && scope.historyListRequest === request) update(scope, (old) => {
        const combined = older ? [...(old.history ?? []), ...versions] : versions;
        return { ...old, history: combined.filter((version, index) => combined.findIndex((item) => item.revision === version.revision) === index),
          historyBusy: false, historyHasMore: versions.length === 20 };
      });
    } catch {
      if (current(scope) && scope.historyGeneration === generation && scope.historyListRequest === request)
        update(scope, (old) => ({ ...old, historyBusy: false, historyError: true }));
    }
  };
  const selectVersion = async (revision: number) => {
    if (!activeSession || !ownerReady) return;
    const scope = scopeRef.current;
    if (!scope || scope !== activeSession.scope || !current(scope)) return;
    const request = ++scope.historyRequest;
    const generation = scope.historyGeneration;
    update(scope, (old) => ({ ...old, selectedRevision: revision, selectedVersion: null, versionBusy: true, versionError: false }));
    try {
      const loaded = await loadTargetResumeVersion(opportunity.id, revision, scope.owner);
      if (current(scope) && scope.historyRequest === request && scope.historyGeneration === generation) update(scope, (old) => ({ ...old, selectedVersion: loaded, versionBusy: false, versionError: !loaded }));
    } catch { if (current(scope) && scope.historyRequest === request && scope.historyGeneration === generation) update(scope, (old) => ({ ...old, versionBusy: false, versionError: true })); }
  };
  const labels: Record<string, string> = {
    name: copy('Full name', '姓名'), email: copy('Email', '邮箱'), phone: copy('Phone', '电话'), location: copy('Location', '地点'),
    url: copy('URL', '链接'), school: copy('School', '学校'), degree: copy('Degree', '学位'), field: copy('Field of study', '专业'),
    start: copy('Start date', '开始日期'), end: copy('End date', '结束日期'), title: copy('Title', '名称'), organization: copy('Organization', '组织'),
    authors: copy('Authors in exact order', '作者及准确顺序'), venue: copy('Journal / conference', '期刊／会议'), date: copy('Date', '日期'),
    publication_status: copy('Publication status', '发表状态'), doi: 'DOI', skill: copy('Skill', '技能'), other: copy('Detail', '内容'), experience: copy('Experience detail', '经历详情'),
  };
  const label = (line: TargetResumeLine) => line.label || labels[line.role] || copy('Detail', '内容');
  const sectionTitle = (section: TargetResumeV1['document']['sections'][number]) => section.heading || ({
    basics: copy('Contact and identity', '姓名与联系方式'), education: copy('Education', '教育'), activities: copy('Experience and projects', '经历与项目'),
    publications: copy('Publications', '论文与出版物'), skills: copy('Skills', '技能'), other: copy('Other', '其他'),
  })[section.kind];
  const renderPreview = (draft: TargetResumeV1, title: string) => <section aria-label={title} className="rounded-xl border border-indigo-100 bg-indigo-50/30 p-4">
    <h3 className="font-semibold">{title}</h3>
    {draft.document.sections.filter((section) => section.included).map((section) => <div key={section.id} className="mt-4">
      <h4 className="font-medium">{sectionTitle(section)}</h4>
      {section.blocks.filter((block) => block.included).map((block) => <dl key={block.id} className="mt-3 space-y-2">
        {block.lines.filter((line) => line.included).map((line) => <div key={line.id}>
          <dt className="text-xs text-gray-500">{label(line)}</dt>
          <dd className="whitespace-pre-wrap break-words text-sm">{line.text || copy('[Empty selected field]', '［已选字段为空］')}</dd>
        </div>)}
      </dl>)}
    </div>)}
  </section>;
  const errors = {
    create: copy('Could not create a draft from confirmed materials. Review the master résumé and try again. Your existing work remains here.', '无法从已确认材料创建文稿，请核对母版后重试。原有编辑仍保留。'),
    invalid: copy('This draft cannot be saved yet. Check its structure and size limits. Your complete input is still here.', '此文稿暂不能保存，请检查结构与篇幅限制。输入全文仍保留。'),
    save: copy('The save was not confirmed. Your local edits remain here; retry saving.', '保存尚未确认。本地编辑仍保留，请重试保存。'),
    missing: copy('The saved document is unavailable. Your local edits have not been replaced.', '已保存文稿暂不可用，本地编辑未被替换。'),
    unavailable: copy('Cloud saving is unavailable for this session. Your local edits remain here.', '本次会话暂不能保存到云端，本地编辑仍保留。'),
    reload: copy('The server version could not be read. Your local edits remain here; retry loading.', '无法读取服务器版本，本地编辑仍保留，请重试读取。'),
    context: copy('Your profile or target changed while creating the draft. The late result was discarded; create again from the current materials.', '创建时资料或目标已变更，迟到结果已作废，请使用当前材料重新创建。'),
  };
  if (!isOpen) return null;
  return <div role="dialog" aria-modal="true" aria-labelledby={`${domId}-title`} className="fixed inset-0 z-[55] flex sm:items-center sm:justify-center">
    <div className="absolute inset-0 bg-gray-900/60" aria-hidden="true" onClick={() => askLeave('close')} />
    <div ref={panelRef} className="relative flex h-full w-full flex-col overflow-hidden bg-white shadow-xl sm:mx-4 sm:h-auto sm:max-h-[92vh] sm:max-w-6xl sm:rounded-2xl">
      <header className="flex items-start justify-between gap-3 border-b p-4 sm:px-6">
        <div className="min-w-0"><h2 id={`${domId}-title`} className="text-lg font-bold">{copy('Target résumé', '目标简历')}</h2><p className="mt-1 break-words text-sm text-gray-600">{opportunity.title}</p></div>
        <div className="ml-3 flex shrink-0 items-start gap-2">
          <button type="button" className={button} disabled={!ownerReady} aria-expanded={supplementOpen} aria-controls={`${domId}-supplement`}
            onClick={() => { if (!supplementMounted) supplementInputRef.current = incomingProfileKey; setSupplementMounted(true); setSupplementOpen((old) => !old); }}>
            {copy('Add experience details', '补充经历')}
          </button>
          <button type="button" className={button} onClick={() => askLeave('close')} aria-label={copy('Close target résumé', '关闭目标简历')}>×</button>
        </div>
      </header>
        {leave && <div role="alert" className="mx-4 my-2 max-h-[35vh] shrink-0 overflow-y-auto rounded-xl border border-amber-300 bg-amber-50 p-3">
          <p>{leave === 'rebuild'
            ? copy('Create a new draft from your current master? Existing edits will not carry over. Saved versions remain in history; any unsaved target edits will be replaced. Your answers in the side panel stay here.', '要根据当前母版创建新稿吗？原有手改不会自动带入；已保存版本仍在历史中，未保存的目标稿编辑将被替换。侧栏答案会保留。')
            : copy('You have unsaved edits, suggestions or answers. Keep editing, or discard them to leave. A save already in progress may still finish.', '有未保存的编辑、建议或答案。可以继续编辑，或放弃后离开；已经发出的保存仍可能完成。')}</p>
          <div className="mt-2 flex flex-wrap gap-2"><button type="button" className={button} onClick={() => setLeave(null)}>{copy('Keep editing', '继续编辑')}</button>
            <button type="button" className={button} disabled={leave === 'rebuild' && (!comparable?.canCreate || activeSession?.saving || activeSession?.reloading || !!activeSession?.conflict)} onClick={() => { if (leave === 'rebuild') void create(); else exit(leave); }}>{leave === 'rebuild' ? copy('Create new draft', '创建新稿') : copy('Discard unsaved edits and continue', '放弃未保存编辑并继续')}</button></div>
        </div>}
      <div className={`min-h-0 overflow-y-auto p-4 sm:p-6 ${supplementOpen ? 'lg:grid lg:grid-cols-[minmax(0,1fr)_22rem] lg:items-start lg:gap-6' : ''}`}>
        {supplementMounted && activeSession && <aside id={`${domId}-supplement`} hidden={!supplementOpen}
          className="mb-5 min-w-0 rounded-xl border bg-gray-50 p-4 lg:order-2 lg:sticky lg:top-0 lg:mb-0 lg:max-h-[calc(92vh-10rem)] lg:overflow-y-auto">
          <ResumeSupplementPanel key={`${activeSession.scope.owner.uid}:${activeSession.scope.owner.epoch}:${activeSession.scope.owner.generation}`}
            owner={activeSession.scope.owner} targetKey={targetKey}
            onDirtyChange={(value) => { if (current(activeSession.scope)) setSupplementDirty(value); }}
            onOpenProfile={() => askLeave('master')}
            onAcceptedProfile={(view, againstView) => {
              if (current(activeSession.scope) && isOwnerTokenValid(view.token, view.token.uid)
                && view.token.uid === activeSession.scope.owner.uid && view.token.epoch === activeSession.scope.owner.epoch
                && view.token.generation === activeSession.scope.owner.generation
                && isOwnerTokenValid(againstView.token, againstView.token.uid)
                && (supplementInputRef.current === incomingProfileRef.current
                  || canonical(againstView.renderedProfile) === incomingProfileRef.current)) {
                setSupplementProfile({ view, inputKey: incomingProfileRef.current });
              }
            }} />
        </aside>}
        <div className="min-w-0 lg:order-1">
        <p className="mb-2 text-sm font-medium">{copy('Uses only confirmed items linked to your master résumé.', '只使用母版中已确认并关联的内容。')}</p>
        <p className="text-sm text-gray-600">{copy('Choose and edit content for this opportunity. Review AI suggestions before applying them. PDF and DOCX export is not available yet.', '选择并编辑适合该机会的内容。AI 建议经核对后再应用，暂不支持 PDF 或 DOCX 导出。')}</p>
        {(!activeSession || activeSession.phase === 'loading') && <p role="status" className="mt-4">{copy('Loading saved target résumé…', '正在读取已保存的目标简历…')}</p>}
        {activeSession?.phase === 'load-error' && <div role="alert" className="mt-4 rounded-xl bg-red-50 p-4 text-sm text-red-800">
          <p>{copy('The saved résumé could not be read. Nothing has been replaced, and creating a new draft is paused.', '无法读取已保存简历，未替换任何内容，暂不创建新稿。')}</p>
          <button type="button" className={`${button} mt-2`} onClick={() => setLifecycle((old) => old + 1)}>{copy('Retry reading saved résumé', '重试读取已保存简历')}</button>
        </div>}
        {activeSession?.error && <p role="alert" className="mt-4 rounded-xl bg-amber-50 p-3 text-sm text-amber-900">{errors[activeSession.error]}</p>}
        {doc && <>
          {!comparable && <p role="status" className="mt-3 text-sm text-amber-800">{copy('Current source comparison is unavailable or still loading. This draft keeps its original source snapshots.', '当前来源对比尚未完成或不可用，此稿仍保留原始来源快照。')}</p>}
          {outdated && <p role="status" className="mt-3 rounded-xl bg-amber-50 p-3 text-sm text-amber-900">{copy('This draft was created from different profile or target materials. Your edits and original source remain intact; they were not rebound to the current profile.', '此稿基于不同版本的资料或目标。编辑与原始来源均已保留，没有改绑到当前资料。')}</p>}
          <details className="mt-4 rounded-xl border p-3"><summary className="cursor-pointer font-medium">{copy('Target requirements and original materials', '目标要求与原始材料')}</summary>
            <p className="mt-2 font-medium">{doc.target_snapshot.title} · {doc.target_snapshot.organization}</p>
            <p className="mt-2 whitespace-pre-wrap break-words text-sm">{doc.target_snapshot.description}</p>
            <ul className="mt-2 list-inside list-disc text-sm">{doc.target_snapshot.requirements.map((requirement, index) => <li key={index} className="whitespace-pre-wrap break-words">{requirement}</li>)}</ul>
            {doc.target_snapshot.source_url && <p className="mt-2 break-all text-xs text-gray-500">{copy('Source', '来源')}: {doc.target_snapshot.source_url}</p>}
            <details className="mt-3"><summary className="cursor-pointer text-sm">{copy('Complete original résumé text', '原始简历全文')}</summary><pre className="mt-2 max-h-80 overflow-auto whitespace-pre-wrap break-words font-sans text-sm">{doc.base_snapshot.resume_text || copy('No imported résumé text; this draft uses confirmed master fields.', '没有导入的简历原文，此稿使用已确认母版字段。')}</pre></details>
          </details>
        </>}
        {activeSession && activeSession.phase !== 'loading' && activeSession.phase !== 'load-error' && <div className="mt-4 flex flex-wrap items-center gap-3">
          <button type="button" className={`${button} bg-indigo-600 text-white`} disabled={!ownerReady || !comparable?.canCreate || creating || activeSession.saving || activeSession.reloading || !!activeSession.conflict}
            onClick={() => { if (doc) setLeave('rebuild'); else void create(); }}>{creating ? copy('Creating draft…', '正在创建文稿…') : doc ? copy('Rebuild from current confirmed master', '从当前已确认母版重新创建') : copy('Create from confirmed master', '从已确认母版创建')}</button>
          {!comparable?.canCreate && ((dirty || supplementDirty)
            ? <p className="text-sm text-amber-800">{copy('Save this draft or close it before opening the master résumé, so your local edits are not lost.', '请先保存或关闭此稿，再打开简历母版，以免丢失本地编辑。')}</p>
            : <Link href="/#resume-master" className="text-sm text-indigo-700 underline">{copy('Confirm your master résumé first', '先确认简历母版')}</Link>)}
        </div>}
        {doc && activeSession && <>
          <div className="my-4 flex flex-wrap items-center gap-3">
            <button type="button" className={button} disabled={!canEdit} onClick={() => {
              try { const ordered = suggestTargetResumeOrder(doc); edit((next) => { next.document = ordered.document; }); }
              catch { update(activeSession.scope, (old) => ({ ...old, error: 'invalid' })); }
            }}>{copy('Suggest order of whole blocks', '建议完整内容块的顺序')}</button>
            <button type="button" className={`${button} bg-indigo-600 text-white`} disabled={!ownerReady || !dirty || activeSession.saving || activeSession.reloading || creating || !!activeSession.conflict} onClick={() => void persist(doc)}>{activeSession.saving ? copy('Saving…', '正在保存…') : copy('Save target draft', '保存目标文稿')}</button>
            <p role="status" className="text-sm text-gray-600">{activeSession.saving ? copy('Waiting for the cloud save result.', '正在等待云端保存结果。') : dirty ? copy('Unsaved local edits', '本地编辑尚未保存') : `${copy('Saved version', '已保存版本')} ${activeSession.revision}`}</p>
          </div>
          {activeSession.conflict && <div role="alert" className="my-4 rounded-xl border border-amber-300 bg-amber-50 p-3 text-sm">
            <p>{copy('A newer server version exists. Your local edits are preserved and have not overwritten it. Loading the server version will discard your local edits.', '服务器已有更新版本。本地编辑仍保留，未覆盖服务器；载入服务器版本会放弃本地编辑。')}</p>
            <button type="button" className={`${button} mt-2`} disabled={activeSession.reloading || activeSession.saving || !ownerReady} onClick={() => void reloadServer()}>{copy('Discard local edits and load server version', '放弃本地编辑并载入服务器版本')}</button>
          </div>}
          <TargetResumeAiPanel key={`${activeSession.scope.owner.uid}:${activeSession.scope.owner.epoch}:${activeSession.scope.owner.generation}:${doc.id}`}
            draft={doc} owner={activeSession.scope.owner} contextKey={contextKey}
            currentContext={comparable ? { profile_signature: comparable.profile, source_signature: comparable.source, target_signature: comparable.target } : null}
            enabled={canEdit && !!comparable && !outdated && !activeSession.conflict}
            onDirtyChange={(value) => { if (current(activeSession.scope)) setAiDirty(value); }}
            onApply={(expectedCanonical, next) => {
              if (!canEdit || !comparable || outdated || activeSession.conflict || !current(activeSession.scope)) return;
              const checked = validateTargetResume(next);
              if (!checked.ok) return;
              update(activeSession.scope, (old) => {
                if (!old.doc || canonical(old.doc) !== expectedCanonical || old.scope.context !== contextKey) return old;
                return { ...old, doc: clone(checked.value), editRevision: old.editRevision + 1, error: null };
              });
            }} />
          <div className="space-y-4">
            {doc.document.sections.map((section, sectionIndex) => <fieldset key={section.id} className="min-w-0 rounded-xl border p-3" disabled={!canEdit}>
              <legend className="px-1 font-semibold">{sectionTitle(section)}</legend>
              <label className="flex items-start gap-2 text-sm"><input type="checkbox" checked={section.included} onChange={(event) => edit((next) => { next.document.sections[sectionIndex].included = event.target.checked; })} />{copy('Include this section', '选用此章节')}</label>
              {section.blocks.map((block, blockIndex) => <div key={block.id} data-testid={`target-block-${block.id}`} className="mt-3 min-w-0 rounded-xl bg-gray-50 p-3">
                <div className="flex flex-wrap items-center gap-2">
                  <label className="mr-auto flex items-center gap-2 text-sm"><input type="checkbox" checked={block.included} onChange={(event) => edit((next) => { next.document.sections[sectionIndex].blocks[blockIndex].included = event.target.checked; })} />{copy('Include whole block', '选用完整内容块')} {blockIndex + 1}</label>
                  {[-1, 1].map((direction) => <button key={direction} type="button" className={button} disabled={!canEdit || blockIndex + direction < 0 || blockIndex + direction >= section.blocks.length}
                    aria-label={`${direction < 0 ? copy('Move block up', '上移内容块') : copy('Move block down', '下移内容块')} ${blockIndex + 1} ${sectionTitle(section)}`}
                    onClick={() => edit((next) => { const blocks = next.document.sections[sectionIndex].blocks; [blocks[blockIndex], blocks[blockIndex + direction]] = [blocks[blockIndex + direction], blocks[blockIndex]]; })}>{direction < 0 ? copy('Move up', '上移') : copy('Move down', '下移')}</button>)}
                </div>
                {block.lines.map((line, lineIndex) => {
                  const inputId = `${domId}-${line.id}`;
                  return <div key={line.id} className="mt-3 min-w-0 rounded-xl border bg-white p-3">
                    <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={line.included} onChange={(event) => edit((next) => { next.document.sections[sectionIndex].blocks[blockIndex].lines[lineIndex].included = event.target.checked; })} />{copy('Include field', '选用字段')}: {label(line)}</label>
                    <div className="mt-3 grid min-w-0 gap-3 md:grid-cols-2">
                      <div className="min-w-0"><p className="text-xs font-medium text-gray-500">{copy('Confirmed original', '已确认原文')}</p><p className="mt-1 whitespace-pre-wrap break-words text-sm">{line.original}</p></div>
                      <div className="min-w-0"><label htmlFor={inputId} className="text-xs font-medium text-gray-500">{copy('Edit', '编辑')} {label(line)}</label><textarea id={inputId} value={line.text} rows={4} className="mt-1 w-full rounded-lg border p-2 text-sm"
                        onChange={(event) => edit((next) => { next.document.sections[sectionIndex].blocks[blockIndex].lines[lineIndex].text = event.target.value; })} /></div>
                    </div>
                    <p className="mt-2 text-xs text-gray-500">{line.text === line.original ? copy('Kept exactly from the confirmed source.', '与已确认来源完全一致。') : copy('Edited from the confirmed source. Check the original and target requirements; this wording has not been fully fact-checked.', '已修改。请对照原文和目标要求核对；此表述尚未完成事实核查。')}</p>
                    <button type="button" className={`${button} mt-2`} disabled={!canEdit || line.text === line.original} aria-label={`${copy('Restore original', '恢复原文')} ${label(line)}`}
                      onClick={() => edit((next) => { next.document.sections[sectionIndex].blocks[blockIndex].lines[lineIndex].text = line.original; })}>{copy('Restore original', '恢复原文')}</button>
                  </div>;
                })}
              </div>)}
            </fieldset>)}
          </div>
          <div className="mt-6">{renderPreview(doc, copy('Current target draft preview', '当前目标文稿预览'))}</div>
          <details className="mt-6 rounded-xl border p-3"><summary className="cursor-pointer font-medium">{copy('Version history', '版本历史')}</summary>
            <p className="mt-2 text-xs text-gray-600">{copy('Load 20 version summaries at a time, then view a selected document. Restoring creates a new saved version; older versions remain unchanged.', '每次读取 20 个版本摘要，再按需查看具体文稿。恢复时另存为新版本，不修改旧版本。')}</p>
            <button type="button" className={`${button} mt-2`} disabled={!ownerReady || activeSession.historyBusy} onClick={() => void history()}>{activeSession.historyBusy ? copy('Loading history…', '正在读取历史…') : copy('Load latest 20 versions', '读取最近 20 个版本')}</button>
            {activeSession.historyError && <p role="alert" className="mt-2 text-sm text-red-700">{copy('History could not be read. Your current draft is unchanged; retry loading.', '无法读取历史版本，当前文稿未变，请重试。')}</p>}
            {activeSession.history?.length === 0 && <p className="mt-2 text-sm">{copy('No saved history yet.', '暂无已保存历史。')}</p>}
            <div className="mt-3 flex flex-wrap gap-2">{activeSession.history?.map((version) => <button type="button" key={version.revision} className={button} aria-pressed={activeSession.selectedRevision === version.revision} disabled={!ownerReady}
              onClick={() => void selectVersion(version.revision)}>{copy('View version', '查看版本')} {version.revision} · {version.updated_at}</button>)}</div>
            {activeSession.historyHasMore && <button type="button" className={`${button} mt-3`} disabled={!ownerReady || activeSession.historyBusy} onClick={() => void history(true)}>{copy('Load older versions', '读取更早版本')}</button>}
            {activeSession.versionBusy && <p role="status" className="mt-2 text-sm">{copy('Reading selected version…', '正在读取所选版本…')}</p>}
            {activeSession.versionError && <p role="alert" className="mt-2 text-sm text-red-700">{copy('The selected version could not be read. Select it again to retry; your current draft is unchanged.', '无法读取所选版本，可再次选择重试，当前文稿未变。')}</p>}
            {activeSession.selectedVersion && <div className="mt-4">
              {renderPreview(activeSession.selectedVersion.doc, copy('Selected historical version preview', '所选历史版本预览'))}
              <p className="mt-2 text-sm text-amber-800">{copy('Restoring replaces the current working draft, including unsaved edits, after the new save succeeds.', '恢复成功保存为新版本后，会替换当前工作稿，包括未保存编辑。')}</p>
              <button type="button" className={`${button} mt-2`} disabled={!ownerReady || activeSession.saving || activeSession.reloading || !!activeSession.conflict || creating}
                onClick={() => void persist(activeSession.selectedVersion!.doc)}>{copy('Restore selected version as a new save', '将所选版本另存为新版本')}</button>
            </div>}
          </details>
        </>}
        {onOpenLegacy && <button type="button" className={`${button} mt-6`} onClick={() => askLeave('legacy')}>{copy('Edit résumé bullets', '编辑经历条目')}</button>}
        </div>
      </div>
    </div>
  </div>;
}
