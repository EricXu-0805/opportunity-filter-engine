'use client';

import { useEffect, useId, useLayoutEffect, useRef, useState, useSyncExternalStore } from 'react';
import { useT } from '@/i18n/client';
import { getAuthState, onAuthChange, type AuthState } from '@/lib/supabase';
import { useAuthModal } from '@/lib/auth-modal-context';
import { captureOwnerToken, isOwnerTokenValid, onLocalOwnerStateChange, type OwnerToken } from '@/lib/identity-owner';
import { MaterialError, type MaterialEventField, type MaterialAttempt, type MaterialCursor,
  type MaterialDeletion, type MaterialRecord, type MaterialScope } from '@/lib/material-core';
import type { MaterialApi } from '@/lib/material-api';
import type { MaterialStorage } from '@/lib/material-storage';

type MaterialServices<F extends MaterialEventField> = MaterialApi<F> & Pick<MaterialStorage<F>,
  'readPendingMaterialAttempts' | 'readPendingMaterialDeletions' | 'prepareMaterialAttempt' | 'settleMaterialAttempt' | 'settleMaterialDeletion'>;
type MaterialProps<F extends MaterialEventField> = { scope: MaterialScope<F>; kind: 'application' | 'contact'; services: MaterialServices<F> };
const contactText = new Set(['open', 'title', 'hint', 'signInHint', 'empty', 'fileLabel', 'fileHint', 'attestation', 'saved', 'recordedAt', 'another']);
const textKey = (kind: 'application' | 'contact', key: string) =>
  (kind === 'contact' && contactText.has(key) ? 'contactMaterials.' : 'applicationRecord.materials.') + key;
export const MATERIAL_AUTH_TIMEOUT_MS = 15_000;

function ownerSnapshot() {
  const owner = captureOwnerToken();
  return JSON.stringify([owner.uid, owner.epoch, owner.generation, isOwnerTokenValid(owner, owner.uid)]);
}
function subscribeOwner(changed: () => void) {
  const stop = onLocalOwnerStateChange(changed); window.addEventListener('storage', changed);
  return () => { stop(); window.removeEventListener('storage', changed); };
}
const buttonClass = 'min-h-9 rounded-lg border border-gray-300 px-3 py-2 text-xs font-medium focus-visible:ring-2 focus-visible:ring-indigo-500 disabled:opacity-50';

/** Records a user-selected past submission. It never selects a current resume. */
export default function RecordedMaterials<F extends MaterialEventField>({ scope, kind, services }: MaterialProps<F>) {
  const owner = useSyncExternalStore(subscribeOwner, ownerSnapshot, () => 'server');
  return <MaterialDisclosure key={JSON.stringify([owner, kind, scope])} scope={scope} kind={kind} services={services} />;
}
function MaterialDisclosure<F extends MaterialEventField>({ scope, kind, services }: MaterialProps<F>) {
  const { t } = useT(); const id = useId(); const [open, setOpen] = useState(false);
  return <div className="mt-3 min-w-0 border-t border-gray-100 pt-2" data-testid={`${kind}-materials`}>
    <button type="button" aria-expanded={open} aria-controls={id} className={buttonClass} onClick={() => setOpen(value => !value)}>
      {t(textKey(kind, open ? 'close' : 'open'))}
    </button>
    {open && <div id={id} className="mt-3 min-w-0"><MaterialAuth scope={scope} kind={kind} services={services} /></div>}
  </div>;
}
function MaterialAuth<F extends MaterialEventField>({ scope, kind, services }: MaterialProps<F>) {
  const { t } = useT(); const authModal = useAuthModal();
  const [auth, setAuth] = useState<{ value: AuthState | null; revision: number } | null>(null);
  const [authError, setAuthError] = useState(false); const [retry, setRetry] = useState(0);
  useEffect(() => {
    let active = true; let revision = 0; let initialDone = false;
    const timer = setTimeout(() => { if (active && !initialDone) { initialDone = true; setAuthError(true); } }, MATERIAL_AUTH_TIMEOUT_MS);
    const stop = onAuthChange(value => {
      revision += 1; initialDone = true; clearTimeout(timer);
      if (active) { setAuthError(false); setAuth(previous => {
        const sameAccount = previous && previous.value?.user?.id === value.user?.id
          && !!previous.value?.session === !!value.session && previous.value?.isAnonymous === value.isAnonymous;
        return { value, revision: sameAccount ? previous.revision : revision };
      }); }
    });
    const initial = revision;
    void getAuthState({ throwOnError: true }).then(value => {
      if (active && !initialDone && revision === initial) { initialDone = true; clearTimeout(timer); setAuth({ value, revision }); }
    }, () => {
      if (active && !initialDone && revision === initial) { initialDone = true; clearTimeout(timer); setAuthError(true); }
    });
    return () => { active = false; clearTimeout(timer); stop(); };
  }, [retry]);
  if (authError) return <div className="space-y-2 text-xs text-amber-800">
    <p role="alert">{t(textKey(kind, 'authError'))}</p>
    <button type="button" className={buttonClass} onClick={() => { setAuth(null); setAuthError(false); setRetry(value => value + 1); }}>{t(textKey(kind, 'retry'))}</button>
  </div>;
  if (!auth) return <p role="status" className="text-xs text-gray-500">{t(textKey(kind, 'authLoading'))}</p>;
  const owner = captureOwnerToken();
  const registered = !!auth.value?.session && !auth.value.isAnonymous;
  if (!registered) return <div className="space-y-2 text-xs text-gray-600">
    <p>{t(textKey(kind, 'signInHint'))}</p>
    <button type="button" className={buttonClass} onClick={() => authModal.openModal({ phase: 'signin' })}>{t(textKey(kind, 'signIn'))}</button>
  </div>;
  if (!owner.uid || auth.value?.user?.id !== owner.uid || !isOwnerTokenValid(owner, owner.uid)) return <p className="text-xs text-gray-500">{t(textKey(kind, 'ownerUnavailable'))}</p>;
  return <MaterialPanel key={auth.revision} scope={scope} kind={kind} services={services} owner={owner}
    onAuthRequired={() => setAuth(value => ({ value: null, revision: (value?.revision ?? 0) + 1 }))} />;
}

function MaterialPanel<F extends MaterialEventField>({ scope, kind, services, owner, onAuthRequired }: MaterialProps<F> & { owner: OwnerToken; onAuthRequired: () => void }) {
  const { getMaterials, getMaterial, uploadMaterial, downloadMaterial, deleteMaterial,
    readPendingMaterialAttempts, readPendingMaterialDeletions, prepareMaterialAttempt, settleMaterialAttempt, settleMaterialDeletion } = services;
  const { t, locale } = useT();
  const label = (key: string, vars?: Record<string, string | number>) => t(textKey(kind, key), vars);
  const [items, setItems] = useState<MaterialRecord<F>[]>([]);
  const [cursor, setCursor] = useState<MaterialCursor | null>(null);
  const [loading, setLoading] = useState(true); const [loadError, setLoadError] = useState(false);
  const [more, setMore] = useState<'idle' | 'loading' | 'error'>('idle');
  const [pending, setPending] = useState<MaterialAttempt<F> | null>(null);
  const [deletions, setDeletions] = useState<MaterialDeletion<F>[]>([]);
  const [localError, setLocalError] = useState(false);
  const [file, setFile] = useState<File | null>(null); const [attested, setAttested] = useState(false);
  const [pendingState, setPendingState] = useState<{ recordId: string; value: 'unknown' | 'staged' | 'ready' } | null>(null);
  const [busy, setBusy] = useState<'save' | 'check' | 'delete' | 'download' | null>(null);
  const [error, setError] = useState<string | null>(null); const [success, setSuccess] = useState<{ recordId: string; label: 'saved' | 'deleted' | 'cancelled' } | null>(null);
  const title = useRef<HTMLHeadingElement>(null); const [knownDeleted, setKnownDeleted] = useState<Set<string>>(() => new Set());
  const alive = useRef(true); const request = useRef<AbortController | null>(null); const reads = useRef(new Set<AbortController>());
  const listRevision = useRef(0); const pagePending = useRef(false);
  const origin = useRef({ ...owner }).current;
  const scopeRef = useRef(scope).current;
  const valid = () => alive.current && isOwnerTokenValid(origin, origin.uid);
  useLayoutEffect(() => { alive.current = true; const controllers = reads.current; return () => { alive.current = false; request.current?.abort(); for (const controller of controllers) controller.abort(); }; }, []);

  function showError(cause: unknown, fallback = 'unavailable') {
    if (!valid()) return;
    if (cause instanceof MaterialError && cause.code === 'sign_in_required') { onAuthRequired(); return; }
    const codes: Record<string, string> = { invalid_input: 'invalidFile', invalid_pdf: 'invalidFile', file_too_large: 'tooLarge', file_mismatch: 'fileMismatch', conflict: 'conflict', storage_unavailable: 'storageError', invalid_pending: 'storageError' };
    setError(cause instanceof MaterialError ? codes[cause.code] ?? fallback : fallback);
  }
  function localSnapshot() {
    const attempts = readPendingMaterialAttempts(origin, scopeRef);
    const intents = readPendingMaterialDeletions(origin, scopeRef);
    if (attempts.length > 1) throw new MaterialError('invalid_pending');
    if (valid()) { setPending(attempts[0] ?? null); setDeletions(intents); setLocalError(false); }
    return { pending: attempts[0] ?? null, deletions: intents };
  }
  function updateRecord(record: MaterialRecord<F>) {
    if (!valid()) return;
    // A write or reconciliation invalidates older list responses immediately.
    listRevision.current += 1;
    setItems(current => {
      const rest = current.filter(item => item.recordId !== record.recordId);
      return record.linkedAt ? [record, ...rest].sort((a, b) => b.linkedAt!.localeCompare(a.linkedAt!) || b.recordId.localeCompare(a.recordId)) : rest;
    });
  }
  async function load(older = false) {
    if (!valid() || (older && (!cursor || pagePending.current))) return;
    const controller = new AbortController(); reads.current.add(controller);
    const revision = older ? listRevision.current : ++listRevision.current;
    let recovery: ReturnType<typeof localSnapshot> | undefined;
    if (older) { pagePending.current = true; setMore('loading'); } else { setLoading(true); setLoadError(false); }
    try {
      if (!older) { try { recovery = localSnapshot(); } catch (cause) { setLocalError(true); showError(cause, 'storageError'); } }
      const page = await getMaterials(scopeRef, { owner: origin, signal: controller.signal, ...(older ? { cursor: cursor! } : {}) });
      if (!valid() || controller.signal.aborted || revision !== listRevision.current) return;
      setItems(current => older ? [...current, ...page.items.filter(item => !current.some(existing => existing.recordId === item.recordId))] : page.items);
      setCursor(page.nextCursor); setMore('idle');
      const restored = recovery?.pending;
      const row = restored && page.items.find(item => item.recordId === restored.input.recordId && item.materialId === restored.input.materialId);
      if (row?.status === 'deleted') setKnownDeleted(current => new Set([...current, row.recordId]));
      else if (row?.status === 'ready' && (['filename', 'mimeType', 'byteLength', 'bytesSha256'] as const).every(key => row[key] === restored!.input[key])) setPendingState({ recordId: row.recordId, value: 'ready' });
    } catch (cause) {
      if (!valid() || controller.signal.aborted || revision !== listRevision.current) return;
      if (cause instanceof MaterialError && cause.code === 'sign_in_required') onAuthRequired();
      else if (older) setMore('error'); else setLoadError(true);
    } finally { reads.current.delete(controller); if (older) pagePending.current = false; if (valid() && !older && revision === listRevision.current) setLoading(false); }
  }
  useEffect(() => {
    const changed = () => {
      if (!valid()) return;
      try { localSnapshot(); } catch (cause) { setLocalError(true); showError(cause, 'storageError'); }
    };
    window.addEventListener('storage', changed);
    return () => window.removeEventListener('storage', changed);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Only the selected event's disclosure mounts its file panel.
  useEffect(() => { void Promise.resolve().then(() => load()); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  async function operate(kind: NonNullable<typeof busy>, run: (controller: AbortController) => Promise<void>, failure?: string) {
    if (!valid() || request.current) return;
    const controller = new AbortController(); request.current = controller; setBusy(kind); setError(null); setSuccess(null);
    try { await run(controller); }
    catch (cause) { if (valid() && !controller.signal.aborted) showError(cause, failure ?? (kind === 'download' ? 'downloadError' : kind === 'delete' ? 'deleteUnknown' : 'unavailable')); }
    finally {
      if (request.current === controller) { request.current = null; if (valid()) { setBusy(null); try { localSnapshot(); } catch (cause) { setLocalError(true); showError(cause, 'storageError'); } } }
    }
  }
  async function accept(record: MaterialRecord<F>) {
    if (!valid()) return;
    const attempt = pending?.input.recordId === record.recordId ? pending.input : null;
    const deleting = deletions.find(item => item.recordId === record.recordId);
    if ((attempt && (attempt.materialId !== record.materialId || (record.status !== 'deleted' && ((['filename', 'mimeType', 'byteLength'] as const).some(key => attempt[key] !== record[key]) || (record.status === 'ready' && attempt.bytesSha256 !== record.bytesSha256)))))
      || (deleting && deleting.materialId !== record.materialId)) throw new MaterialError('conflict');
    if (record.status === 'deleted') setKnownDeleted(current => new Set([...current, record.recordId]));
    if (record.status === 'staged') { setPendingState({ recordId: record.recordId, value: 'staged' }); return; }
    updateRecord(record);
    setPendingState({ recordId: record.recordId, value: 'ready' }); setSuccess({ recordId: record.recordId, label: record.status === 'deleted' ? (record.archivedAt ? 'deleted' : 'cancelled') : 'saved' }); setFile(null); setAttested(false);
    try {
      await settleMaterialAttempt(origin, scopeRef, record);
      if (!valid()) return;
      if (record.status === 'deleted') await settleMaterialDeletion(origin, scopeRef, record);
      if (valid()) localSnapshot();
    } finally { if (valid()) void load(); }
  }
  function save() {
    if (!file || localError || (!pending && !attested)) return;
    void operate('save', async controller => {
      const prepared = await prepareMaterialAttempt(origin, scopeRef, file, true, controller.signal);
      if (!valid() || controller.signal.aborted) return;
      if (prepared.status === 'pending_exists') {
        if (prepared.attempts.length !== 1) throw new MaterialError('invalid_pending');
        setPending(prepared.attempts[0]); setFile(null); setAttested(false); setError('fileMismatch'); return;
      }
      setPending(prepared.attempt); setPendingState({ recordId: prepared.attempt.input.recordId, value: 'unknown' });
      const result = await uploadMaterial(prepared.attempt, file, { owner: origin, signal: controller.signal });
      if (valid() && !controller.signal.aborted) await accept(result.record);
    });
  }
  function check(recordId: string, deleting = false) {
    const unknown = pending?.input.recordId === recordId ? 'cancelUnknown' : 'deleteUnknown';
    void operate('check', async controller => {
      const record = await getMaterial(scopeRef, recordId, { owner: origin, signal: controller.signal });
      if (!valid() || controller.signal.aborted) return;
      if (!record) { setError(deleting ? unknown : 'notFound'); return; }
      if (deleting && record.status !== 'deleted') { setError(unknown); return; }
      await accept(record);
    }, deleting ? unknown : undefined);
  }
  function remove(record: Pick<MaterialRecord<F>, 'recordId' | 'materialId'>) {
    title.current?.focus();
    void operate('delete', async controller => {
      try {
        const result = await deleteMaterial(scopeRef, record, { owner: origin, signal: controller.signal });
        if (valid() && !controller.signal.aborted) await accept(result);
      } finally { if (valid()) localSnapshot(); }
    }, pending?.input.recordId === record.recordId ? 'cancelUnknown' : 'deleteUnknown');
  }
  const dateLabel = (value: string) => new Date(value).toLocaleString(locale === 'zh' ? 'zh-CN' : 'en-US', { dateStyle: 'medium', timeStyle: 'short' });
  const isDeleting = (recordId: string) => deletions.some(item => item.recordId === recordId);
  const canEdit = !busy && !localError;
  const pendingDeletion = !!pending && isDeleting(pending.input.recordId);
  const pendingRemoved = !!pending && knownDeleted.has(pending.input.recordId);
  const pendingLabel = pendingState?.recordId === pending?.input.recordId ? pendingState?.value : 'unknown';
  const scopedSuccess = success && (!pending || success.recordId === pending.input.recordId) ? success.label : null;
  return <section aria-label={label('title')} className="min-w-0 space-y-3 text-xs text-gray-700" data-testid={`${kind}-material-panel`}>
    <h4 ref={title} tabIndex={-1} className="font-semibold">{label('title')}</h4><p className="text-gray-500">{label('hint')}</p>
    {error && <p role="alert" className="text-amber-800">{label(error)}</p>}
    {scopedSuccess && <p role="status" className="text-emerald-800">{label(scopedSuccess)}</p>}
    {localError && <button type="button" className={buttonClass} disabled={!!busy} onClick={() => { void load(); }}>{label('retry')}</button>}
    {pending && !pendingDeletion && <div className="space-y-2 rounded-lg border border-amber-200 bg-amber-50 p-3" data-testid={`${kind}-material-pending`}>
      <p>{label(pendingRemoved ? 'deleted' : pendingLabel === 'staged' ? 'staged' : pendingLabel === 'ready' ? 'cleanupPending' : 'unknown')}</p>
      {!pendingRemoved && <><p className="break-words [overflow-wrap:anywhere]">{pending.input.filename}</p><p>{label('needFile')}</p></>}
      <div className="flex flex-wrap gap-2"><button type="button" className={buttonClass} disabled={!canEdit} onClick={() => check(pending.input.recordId)}>{label(busy === 'check' ? 'checking' : 'check')}</button>
        {!pendingRemoved && <DeleteMaterial disabled={!canEdit} label={key => label(({ delete: 'cancelUpload', deleteTitle: 'cancelUploadTitle', deleteHint: 'cancelUploadHint', confirmDelete: 'confirmCancelUpload', cancel: 'keepUpload' } as Record<string, string>)[key] ?? key)} onConfirm={() => remove(pending.input)} />}
      </div>
    </div>}
    {(!scopedSuccess || pending) && !pendingDeletion && !pendingRemoved && <form className="space-y-2 rounded-lg border border-gray-200 p-3" onSubmit={event => { event.preventDefault(); save(); }}>
      <label className="block font-medium">{label('fileLabel')}<input type="file" accept="application/pdf,.pdf" disabled={!canEdit}
        className="mt-2 block w-full min-w-0 text-xs file:mr-2 file:min-h-9 file:rounded file:border file:border-gray-300 file:bg-white file:px-2 file:text-gray-700"
        onChange={event => { const selected = event.target.files?.[0] ?? null; event.target.value = ''; setFile(selected); setAttested(false); setError(null); }} /></label>
      <p className="text-gray-500">{label('fileHint')}</p>
      {file && <p className="break-words [overflow-wrap:anywhere]">{file.name} · {(file.size / 1024).toFixed(1)} KiB</p>}
      {!pending && <label className="flex items-start gap-2"><input type="checkbox" className="mt-0.5 h-4 w-4 shrink-0" checked={attested} disabled={!canEdit} onChange={event => setAttested(event.target.checked)} /><span>{label('attestation')}</span></label>}
      <button type="submit" disabled={!canEdit || !file || (!pending && !attested)} className={buttonClass + ' bg-indigo-600 text-white'}>{label(busy === 'save' ? 'saving' : pending ? 'retrySave' : 'save')}</button>
    </form>}
    {scopedSuccess && !pending && <button type="button" className={buttonClass} disabled={!canEdit} onClick={() => { setSuccess(null); setFile(null); setAttested(false); }}>{label('another')}</button>}
    {deletions.map(intent => <div key={intent.recordId} className="space-y-2 rounded-lg border border-amber-200 p-3" data-testid={`${kind}-material-delete-pending`}>
      <p>{label(pending?.input.recordId === intent.recordId ? 'cancelUnknown' : 'deleteUnknown')}</p><div className="flex flex-wrap gap-2">
        <button type="button" disabled={!canEdit} className={buttonClass} onClick={() => check(intent.recordId, true)}>{label('check')}</button>
        <button type="button" disabled={!canEdit} className={buttonClass} onClick={() => remove(intent)}>{label(busy === 'delete' ? 'deleting' : pending?.input.recordId === intent.recordId ? 'retryCancelUpload' : 'retryDelete')}</button>
      </div>
    </div>)}
    {loading ? <p role="status">{label('loading')}</p> : loadError ? <div role="alert"><p>{label('loadError')}</p><button type="button" className={buttonClass} disabled={!!busy} onClick={() => { void load(); }}>{label('retry')}</button></div>
      : items.length === 0 ? <p>{label('empty')}</p> : <>
        <p className="text-gray-500">{label(cursor ? 'loadedMore' : 'loadedAll', { count: items.length })}</p>
        <ul className="space-y-2">{items.filter(item => !isDeleting(item.recordId)).map(record => <li key={record.recordId} className="min-w-0 rounded-lg border border-gray-200 p-3" data-testid={`${kind}-material-record`}>
          <p className="break-words font-medium [overflow-wrap:anywhere]">{record.status === 'deleted' ? label('deleted') : record.filename}</p>
          {record.status === 'ready' && record.byteLength !== null && <p className="mt-1 text-gray-500" data-testid={`${kind}-material-size`}>{record.byteLength < 1024 * 1024 ? `${(record.byteLength / 1024).toFixed(1)} KiB` : `${(record.byteLength / (1024 * 1024)).toFixed(1)} MiB`}</p>}
          <dl className="mt-2 space-y-1">{(['archivedAt', 'linkedAt', 'deletedAt'] as const).map(field => record[field] && <div key={field}>
            <dt className="text-gray-500">{label(field === 'linkedAt' ? 'recordedAt' : field)}</dt><dd><time dateTime={record[field]!}>{dateLabel(record[field]!)}</time></dd>
          </div>)}</dl>
          {record.status === 'ready' && <div className="mt-2 flex flex-wrap gap-2">
            <button type="button" className={buttonClass} disabled={!canEdit} onClick={() => { void operate('download', async controller => { await downloadMaterial(scopeRef, record, { owner: origin, signal: controller.signal }); }); }}>{label(busy === 'download' ? 'downloading' : 'download')}</button>
            <DeleteMaterial disabled={!canEdit} label={label} onConfirm={() => remove(record)} />
          </div>}
        </li>)}</ul>
      </>}
    {more === 'error' && <p role="alert">{label('moreError')}</p>}
    {cursor && <button type="button" className={buttonClass} disabled={more === 'loading' || !!busy} onClick={() => { void load(true); }}>{label(more === 'loading' ? 'loadingMore' : 'loadMore')}</button>}
  </section>;
}
function DeleteMaterial({ disabled, label, onConfirm }: { disabled: boolean; label: (key: string) => string; onConfirm: () => void }) {
  const [confirming, setConfirming] = useState(false); const id = useId();
  const opener = useRef<HTMLButtonElement>(null); const cancel = useRef<HTMLButtonElement>(null);
  useEffect(() => { if (confirming) cancel.current?.focus(); }, [confirming]);
  const close = () => { setConfirming(false); opener.current?.focus(); };
  return <><button ref={opener} type="button" className={buttonClass} disabled={disabled} onClick={() => setConfirming(true)}>{label('delete')}</button>
    {confirming && <div role="alertdialog" aria-labelledby={id} className="w-full space-y-2 rounded-lg border border-amber-200 bg-amber-50 p-3" onKeyDown={event => { if (event.key === 'Escape') { event.stopPropagation(); close(); } }}>
      <h5 id={id} className="font-medium">{label('deleteTitle')}</h5><p>{label('deleteHint')}</p><div className="flex flex-wrap gap-2">
        <button ref={cancel} type="button" className={buttonClass} onClick={close}>{label('cancel')}</button>
        <button type="button" disabled={disabled} className={buttonClass} onClick={() => { setConfirming(false); onConfirm(); }}>{label('confirmDelete')}</button>
      </div>
    </div>}
  </>;
}
