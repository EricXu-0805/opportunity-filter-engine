'use client';

import { useEffect, useLayoutEffect, useRef, useState, useSyncExternalStore } from 'react';
import { useT } from '@/i18n/client';
import { confirmApplicationEvent, getApplicationEvent } from '@/lib/supabase';
import type { InteractionRecord, ConfirmApplicationEventResult } from '@/lib/supabase';
import { ApplicationEventError, applicationEventMatches } from '@/lib/application-ledger';
import type { ApplicationEventInput } from '@/lib/application-ledger';
import { prepareApplicationAttempt, readPendingApplicationAttempts, settleApplicationAttempt } from '@/lib/application-attempt-storage';
import type { ApplicationPendingAttempt } from '@/lib/application-attempt-storage';
import { captureOwnerToken, isOwnerTokenValid, onLocalOwnerStateChange } from '@/lib/identity-owner';
import type { OwnerToken } from '@/lib/identity-owner';

interface Props {
  opportunityId: string;
  ownerReady: boolean;
  onConfirmed: (record: InteractionRecord | null) => void;
}
type Draft = { channel: ApplicationEventInput['channel']; destination: string; submittedAt: string; notes: string; resultNote: string; nextStep: string };
const emptyDraft = (): Draft => ({ channel: 'web_form', destination: '', submittedAt: '', notes: '', resultNote: '', nextStep: '' });
function ownerSnapshot() {
  const token = captureOwnerToken();
  return JSON.stringify([token.uid, token.epoch, token.generation, isOwnerTokenValid(token, token.uid)]);
}
function subscribeOwner(changed: () => void) {
  const stop = onLocalOwnerStateChange(changed);
  window.addEventListener('storage', changed);
  return () => { stop(); window.removeEventListener('storage', changed); };
}
/** A personal record of a past action. This form never sends an application. */
export default function ApplicationRecordForm(props: Props) {
  const scope = useSyncExternalStore(subscribeOwner, ownerSnapshot, () => 'server');
  return <ApplicationRecordEditor key={scope + ':' + props.opportunityId} {...props} />;
}
function ApplicationRecordEditor({ opportunityId, ownerReady, onConfirmed }: Props) {
  const { t, locale } = useT();
  const label = (key: string) => t('applicationRecord.' + key);
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState<Draft>(emptyDraft);
  const [attested, setAttested] = useState(false);
  const [pending, setPending] = useState<ApplicationPendingAttempt | null>(null);
  const [saved, setSaved] = useState<ConfirmApplicationEventResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<'save' | 'check' | null>(null);
  const [loadFailed, setLoadFailed] = useState(false);
  const opener = useRef<HTMLButtonElement>(null);
  const firstField = useRef<HTMLSelectElement>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const mounted = useRef(true);
  const request = useRef<object | null>(null);
  const callback = useRef(onConfirmed);
  useLayoutEffect(() => { callback.current = onConfirmed; }, [onConfirmed]);
  useLayoutEffect(() => { mounted.current = true; return () => { mounted.current = false; request.current = null; }; }, []);
  useEffect(() => { if (open) (pending || saved || loadFailed ? heading.current : firstField.current)?.focus(); }, [open, pending, saved, loadFailed]);
  const token = captureOwnerToken();
  const ready = ownerReady && !!token.uid && isOwnerTokenValid(token, token.uid);
  const valid = (owner: OwnerToken, call: object) => mounted.current && request.current === call && isOwnerTokenValid(owner, owner.uid);

  function openForm() {
    if (!ready) return;
    setOpen(true);
    if (request.current) return;
    setError(null); setLoadFailed(false);
    try {
      const attempts = readPendingApplicationAttempts(token, opportunityId);
      if (attempts.length > 1) throw new Error('ambiguous pending attempts');
      setPending(attempts[0] ?? null);
    } catch { setLoadFailed(true); setError('storageError'); }
  }
  function close() { setOpen(false); opener.current?.focus(); }
  function submittedTime(value: string): string | null {
    if (!value) return null;
    if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(value)) throw new ApplicationEventError('invalid_input');
    const date = new Date(value);
    // Refuse normalized invalid dates and nonexistent local times (DST gaps).
    const local = [date.getFullYear(), String(date.getMonth() + 1).padStart(2, '0'), String(date.getDate()).padStart(2, '0')].join('-')
      + 'T' + String(date.getHours()).padStart(2, '0') + ':' + String(date.getMinutes()).padStart(2, '0');
    if (!Number.isFinite(date.getTime()) || date.getTime() > Date.now() || local !== value) throw new ApplicationEventError('invalid_input');
    return date.toISOString();
  }
  async function accept(result: ConfirmApplicationEventResult, owner: OwnerToken, call: object) {
    if (!valid(owner, call)) return;
    // Publish the verified receipt now: local cleanup may wait for another
    // tab, while the user can already save a newer Tracker state or note.
    callback.current(result.interaction);
    // A failed local cleanup does not undo a successful database receipt. Keep
    // the frozen attempt available for an exact retry; never create another ID.
    try { await settleApplicationAttempt(owner, opportunityId, result.event); }
    catch { if (valid(owner, call)) setError('storageError'); return; }
    if (!valid(owner, call)) return;
    setPending(null); setSaved(result); setError(null);
  }
  async function save() {
    if (!ready || request.current || loadFailed || saved || (!pending && !attested)) return;
    const owner = { ...captureOwnerToken() }; const call = {}; request.current = call;
    setBusy('save'); setError(null);
    let stage: 'prepare' | 'wire' = 'prepare';
    try {
      let attempt = pending;
      if (!attempt) {
        const prepared = await prepareApplicationAttempt(owner, opportunityId, {
          channel: draft.channel, destination: draft.destination,
          submittedAt: submittedTime(draft.submittedAt), notes: draft.notes || null,
          resultNote: draft.resultNote || null, nextStep: draft.nextStep || null,
        });
        if (!valid(owner, call)) return;
        if (prepared.status === 'pending_exists') {
          if (prepared.attempts.length !== 1) { setLoadFailed(true); setError('storageError'); return; }
          setPending(prepared.attempts[0]); setError('pendingExists'); return;
        }
        attempt = prepared.attempt; setPending(attempt);
      }
      if (!valid(owner, call)) return;
      stage = 'wire';
      const result = await confirmApplicationEvent(opportunityId, attempt.input, owner);
      await accept(result, owner, call);
    } catch (cause) {
      if (!valid(owner, call)) return;
      setError(cause instanceof ApplicationEventError && cause.code === 'invalid_input' ? 'invalid'
        : cause instanceof ApplicationEventError && cause.code === 'conflict' ? 'conflict'
          : stage === 'prepare' ? 'storageError' : 'unavailable');
    } finally { if (valid(owner, call)) setBusy(null); if (request.current === call) request.current = null; }
  }
  async function checkSaved() {
    if (!ready || request.current || !pending) return;
    const owner = { ...captureOwnerToken() }; const call = {}; request.current = call;
    setBusy('check'); setError(null);
    try {
      const event = await getApplicationEvent(opportunityId, pending.input.id, owner);
      if (!valid(owner, call)) return;
      if (!event) { setError('notFound'); return; }
      if (!applicationEventMatches(event, pending.input)) { setError('conflict'); return; }
      // The immutable event exists: an exact replay returns today's summary,
      // including null after deletion, without re-creating or advancing it.
      const result = await confirmApplicationEvent(opportunityId, pending.input, owner);
      await accept(result, owner, call);
    } catch { if (valid(owner, call)) setError('unavailable'); }
    finally { if (valid(owner, call)) setBusy(null); if (request.current === call) request.current = null; }
  }
  function another() {
    if (!ready || request.current) return;
    // Recheck storage: another tab may have an uncertain submission already.
    setSaved(null); setDraft(emptyDraft()); setAttested(false); openForm();
  }
  const inputClass = 'mt-1 block w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 focus-visible:ring-2 focus-visible:ring-indigo-500 disabled:opacity-60';
  const buttonClass = 'min-h-10 rounded-lg border border-gray-300 px-3 py-2 text-sm font-medium focus-visible:ring-2 focus-visible:ring-indigo-500 disabled:opacity-50';
  const frozen = pending?.input;
  return <section id="application-record" className="mt-4 min-w-0 px-5 sm:px-8" onKeyDown={event => { if (event.key === 'Escape' && open) { event.stopPropagation(); close(); } }}>
    <button ref={opener} type="button" onClick={openForm} disabled={!ready} aria-expanded={open} aria-controls="application-record-editor" className={buttonClass + ' text-indigo-700'}>{label('open')}</button>
    {!ready && <p className="mt-1 text-xs text-gray-500">{label('ownerUnavailable')}</p>}
    {open && <div id="application-record-editor" className="mt-3 max-w-2xl rounded-xl border border-gray-200 bg-gray-50 p-4">
      <div className="flex items-start justify-between gap-3"><h3 ref={heading} tabIndex={-1} className="font-semibold text-gray-900">{label('title')}</h3><button type="button" onClick={close} className="min-h-9 rounded px-2 text-sm underline focus-visible:ring-2 focus-visible:ring-indigo-500">{label('close')}</button></div>
      <p className="mt-1 text-sm text-gray-600">{label('hint')}</p>
      <p className="mt-1 text-xs text-gray-500">{label('materialsHint')}</p>
      {saved ? <div className="mt-3 space-y-3"><p role="status" className="text-sm text-emerald-800">{label(saved.interaction ? 'saved' : 'savedNoStatus')}</p><button type="button" onClick={another} className={buttonClass}>{label('another')}</button></div>
        : loadFailed ? <button type="button" className={buttonClass + ' mt-3'} onClick={openForm}>{label('retry')}</button>
          : frozen ? <div className="mt-3 space-y-3">
            <p className="font-medium text-gray-800">{label('pendingTitle')}</p><p className="text-sm text-gray-600">{label('pendingHint')}</p>
            <dl className="space-y-2 break-words text-sm [overflow-wrap:anywhere]">
              <div><dt className="font-medium">{label('channel')}</dt><dd>{label('history.channels.' + frozen.channel)}</dd></div>
              <div><dt className="font-medium">{label('destination')}</dt><dd>{frozen.destination}</dd></div>
              <div><dt className="font-medium">{label('submittedAt')}</dt><dd>{frozen.submittedAt ? new Date(frozen.submittedAt).toLocaleString(locale === 'zh' ? 'zh-CN' : 'en-US') : label('history.submittedUnknown')}</dd></div>
              {(['notes', 'resultNote', 'nextStep'] as const).map(key => frozen[key] && <div key={key}><dt className="font-medium">{label(key)}</dt><dd className="whitespace-pre-wrap">{frozen[key]}</dd></div>)}
            </dl>
            <div className="flex flex-wrap gap-2"><button type="button" className={buttonClass} disabled={!!busy || !ready} onClick={() => { void save(); }}>{label(busy === 'save' ? 'saving' : 'retry')}</button><button type="button" className={buttonClass} disabled={!!busy || !ready} onClick={() => { void checkSaved(); }}>{label(busy === 'check' ? 'checking' : 'checkSaved')}</button></div>
          </div> : <form className="mt-3 space-y-3" onSubmit={event => { event.preventDefault(); void save(); }}>
            <label className="block text-sm font-medium">{label('channel')}<select ref={firstField} className={inputClass} disabled={!!busy || !ready} value={draft.channel} onChange={e => setDraft(d => ({ ...d, channel: e.target.value as Draft['channel'] }))}>{(['web_form', 'email', 'other'] as const).map(channel => <option key={channel} value={channel}>{label('history.channels.' + channel)}</option>)}</select></label>
            <label className="block text-sm font-medium">{label('destination')}<input className={inputClass} value={draft.destination} required maxLength={2000} aria-describedby="application-destination-hint" inputMode={draft.channel === 'web_form' ? 'url' : draft.channel === 'email' ? 'email' : 'text'} disabled={!!busy || !ready} onChange={e => setDraft(d => ({ ...d, destination: e.target.value }))} /></label>
            <p id="application-destination-hint" className="text-xs text-gray-500">{label('destinationHints.' + draft.channel)}</p>
            <label className="block text-sm font-medium">{label('submittedAt')}<input className={inputClass} type="datetime-local" aria-describedby="application-submitted-hint" value={draft.submittedAt} disabled={!!busy || !ready} onChange={e => setDraft(d => ({ ...d, submittedAt: e.target.value }))} /></label>
            <p id="application-submitted-hint" className="text-xs text-gray-500">{label('submittedAtHint')}</p>
            <details><summary className="min-h-9 cursor-pointer text-sm font-medium focus-visible:ring-2 focus-visible:ring-indigo-500">{label('moreDetails')}</summary><div className="space-y-3">{(['notes', 'resultNote', 'nextStep'] as const).map(key => <label key={key} className="block text-sm font-medium">{label(key)}<textarea className={inputClass} rows={2} maxLength={4000} value={draft[key]} disabled={!!busy || !ready} onChange={e => setDraft(d => ({ ...d, [key]: e.target.value }))} /></label>)}</div></details>
            <label className="flex items-start gap-2 text-sm"><input className="mt-1 h-4 w-4 shrink-0" type="checkbox" checked={attested} disabled={!!busy || !ready} onChange={e => setAttested(e.target.checked)} /><span>{label('attestation')}</span></label>
            <button type="submit" disabled={!attested || !!busy || !ready} className={buttonClass + ' bg-indigo-600 text-white'}>{label(busy ? 'saving' : 'save')}</button>
          </form>}
      {error && <p role="alert" className="mt-3 text-sm text-amber-800">{label(error)}</p>}
    </div>}
  </section>;
}
