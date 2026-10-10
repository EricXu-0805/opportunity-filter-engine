'use client';

import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from 'react';
import { captureOwnerToken, isOwnerTokenValid, isTokenOwnerStillCurrent, onLocalOwnerStateChange } from '@/lib/identity-owner';
import { AttachmentRequestError } from '@/lib/attachment-request';
import { Paperclip, Trash2, Upload, ExternalLink, Loader2 } from 'lucide-react';
import { ATTACHMENTS_ALLOWED_MIME, ATTACHMENTS_MAX_BYTES, deleteAttachment, getAttachmentSignedUrl,
  listAttachments, onAuthChange, uploadAttachment, type Attachment } from '@/lib/supabase';
import { useT } from '@/i18n/client';

type Replier = (path: string, vars?: Record<string, string | number>) => string;
type Message = { key: string; vars?: Record<string, string | number> };
interface Props { opportunityId: string }
function formatBytes(n: number, t: Replier): string {
  if (n < 1024) return t('detail.attachments.sizeBytes', { n });
  if (n < 1024 * 1024) return t('detail.attachments.sizeKB', { n: Math.round(n / 1024) });
  return t('detail.attachments.sizeMB', { n: (n / 1024 / 1024).toFixed(1) });
}
function ownerSnapshot() {
  const token = captureOwnerToken();
  return JSON.stringify([token.uid, token.epoch, token.generation, isOwnerTokenValid(token, token.uid)]);
}
function subscribeOwner(changed: () => void) {
  const stopOwner = onLocalOwnerStateChange(changed);
  const stopAuth = onAuthChange(changed);
  window.addEventListener('storage', changed);
  return () => { stopOwner(); stopAuth(); window.removeEventListener('storage', changed); };
}

/** Files and in-flight operations belong to one account generation and target. */
export default function AttachmentsPanel({ opportunityId }: Props) {
  const owner = useSyncExternalStore(subscribeOwner, ownerSnapshot, () => 'server');
  return <AttachmentFiles key={JSON.stringify([owner, opportunityId])} opportunityId={opportunityId} />;
}

function AttachmentFiles({ opportunityId }: Props) {
  const { t } = useT();
  const [ownerToken] = useState(captureOwnerToken);
  const [files, setFiles] = useState<Attachment[]>([]);
  const [status, setStatus] = useState<'loading' | 'ready' | 'error' | 'signed-out'>('loading');
  const [action, setAction] = useState<{ kind: 'upload' | 'delete' | 'open'; name: string } | null>(null);
  const [error, setError] = useState<Message | null>(null);
  const [notice, setNotice] = useState<Message | null>(null);
  // Files live under the session's uid. Signing a guest in to an account it
  // already has merges its rows but not these files, so say so up front.
  const [guest, setGuest] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const active = useRef(false);
  const pendingAction = useRef(false);
  const controllers = useRef(new Set<AbortController>());
  const listRequest = useRef<AbortController | null>(null);
  const current = useCallback((controller: AbortController, token: ReturnType<typeof captureOwnerToken>) =>
    active.current && !controller.signal.aborted && isTokenOwnerStillCurrent(token)
      && token.generation === captureOwnerToken().generation, []);

  const refresh = useCallback(async () => {
    listRequest.current?.abort();
    const controller = new AbortController();
    listRequest.current = controller;
    controllers.current.add(controller);
    const token = ownerToken;
    setStatus('loading');
    try {
      const next = await listAttachments(opportunityId, token, { signal: controller.signal });
      if (!current(controller, token)) return;
      setFiles(next);
      setStatus('ready');
    } catch (cause) {
      if (!current(controller, token)) return;
      if (cause instanceof AttachmentRequestError && cause.code === 'unauthenticated') {
        setFiles([]);
        setStatus('signed-out');
      } else setStatus('error');
    } finally { controllers.current.delete(controller); }
  }, [current, opportunityId, ownerToken]);

  useEffect(() => onAuthChange(state => setGuest(!!state.session && state.isAnonymous)), []);

  useEffect(() => {
    active.current = true;
    const requests = controllers.current;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- same bounded read serves mount and explicit retry; owner/target changes remount the private state
    void refresh();
    return () => { active.current = false; requests.forEach(controller => controller.abort()); requests.clear(); };
  }, [refresh]);

  const runAction = async (kind: 'upload' | 'delete' | 'open', name: string, file?: File) => {
    if (pendingAction.current || status !== 'ready' || !isTokenOwnerStillCurrent(ownerToken)
      || ownerToken.generation !== captureOwnerToken().generation) return;
    pendingAction.current = true;
    const controller = new AbortController();
    controllers.current.add(controller);
    const token = ownerToken;
    setAction({ kind, name });
    setError(null);
    setNotice(null);
    try {
      if (kind === 'open') {
        const url = await getAttachmentSignedUrl(opportunityId, name, 300, token, { signal: controller.signal });
        if (!current(controller, token)) return;
        if (!url) throw new Error('No file URL');
        window.open(url, '_blank', 'noopener,noreferrer');
      } else if (kind === 'upload' && file) {
        const result = await uploadAttachment(opportunityId, file, token, { signal: controller.signal });
        if (!current(controller, token)) return;
        if (!result.ok) {
          const key = { too_large: 'errTooLarge', wrong_type: 'errWrongType', duplicate: 'errDuplicate',
            unauthenticated: 'errUnauth', unknown: 'uploadUnknown' }[result.reason];
          setError({ key, vars: { name } });
          if (result.reason === 'unknown') setStatus('error');
          else if (result.reason === 'unauthenticated') { setFiles([]); setStatus('signed-out'); }
          return;
        }
        setNotice({ key: 'uploaded', vars: { name: result.name } });
        await refresh();
      } else if (kind === 'delete') {
        const ok = await deleteAttachment(opportunityId, name, token, { signal: controller.signal });
        if (!current(controller, token)) return;
        if (!ok) throw new Error('No deletion receipt');
        setFiles(previous => previous.filter(item => item.name !== name));
        setNotice({ key: 'deleted', vars: { name } });
        await refresh();
      }
    } catch (cause) {
      if (!current(controller, token)) return;
      const unauthenticated = cause instanceof AttachmentRequestError && cause.code === 'unauthenticated';
      setError({ key: unauthenticated ? 'errUnauth' : kind === 'open' ? 'errOpen' : kind === 'upload' ? 'uploadUnknown' : 'deleteUnknown', vars: { name } });
      if (unauthenticated) { setFiles([]); setStatus('signed-out'); }
      else if (kind !== 'open') setStatus('error');
    } finally {
      controllers.current.delete(controller);
      if (current(controller, token)) { pendingAction.current = false; setAction(null); }
    }
  };

  const disabled = status !== 'ready' || !!action;
  const buttonClass = 'inline-flex min-h-9 items-center gap-1 rounded-md px-2 py-1 text-[12px] font-medium text-indigo-700 bg-indigo-50 hover:bg-indigo-100 disabled:opacity-50 disabled:cursor-wait';
  return (
    <section className="space-y-2 min-w-0" data-testid="tracker-attachments" aria-label={t('detail.attachments.label')}>
      <div className="flex flex-wrap items-center gap-2 text-[12px] text-gray-600">
        <Paperclip className="w-3.5 h-3.5 text-gray-400" aria-hidden="true" />
        <span className="font-medium">{t('detail.attachments.label')}</span>
        <span className="text-[10px] text-gray-500">{t('detail.attachments.hint', { mb: Math.round(ATTACHMENTS_MAX_BYTES / 1024 / 1024) })}</span>
        <button type="button" onClick={() => input.current?.click()} disabled={disabled} className={`${buttonClass} ml-auto`}>
          {action?.kind === 'upload' ? <Loader2 className="w-3 h-3 animate-spin" aria-hidden="true" /> : <Upload className="w-3 h-3" aria-hidden="true" />}
          {action?.kind === 'upload' ? t('detail.attachments.uploading', { name: action.name }) : t('detail.attachments.addButton')}
        </button>
        <input ref={input} type="file" accept={Array.from(ATTACHMENTS_ALLOWED_MIME).join(',')} disabled={disabled}
          aria-label={t('detail.attachments.addButton')} className="hidden" onChange={event => {
            const file = event.target.files?.[0]; event.target.value = '';
            if (file) void runAction('upload', file.name, file);
          }} />
      </div>
      {guest && <p data-testid="tracker-attachments-guest" className="text-[11px] text-amber-700 break-words">{t('detail.attachments.guestNotice')}</p>}
      {notice && <p role="status" data-testid="tracker-attachments-notice" className="text-[12px] text-green-700 break-words">{t(`detail.attachments.${notice.key}`, notice.vars)}</p>}
      {error && <p role="alert" className="text-[12px] text-red-700 break-words">{t(`detail.attachments.${error.key}`, error.vars)}</p>}
      {status === 'loading' && <p role="status" data-testid="tracker-attachments-loading" className="text-[12px] text-gray-500">{t('detail.attachments.loading')}</p>}
      {(status === 'error' || status === 'signed-out') && <div className="space-y-1">
        <p role={status === 'error' ? 'alert' : 'status'} data-testid={status === 'error' ? 'tracker-attachments-error' : 'tracker-attachments-signed-out'} className="text-[12px] text-gray-700">
          {t(status === 'error' ? 'detail.attachments.listError' : 'detail.attachments.signIn')}
        </p>
        <button type="button" className={buttonClass} disabled={!!action} onClick={() => { setError(null); void refresh(); }}>
          {t(status === 'error' ? 'detail.attachments.retryList' : 'detail.attachments.checkAgain')}
        </button>
      </div>}
      {status === 'ready' && files.length === 0 && <p data-testid="tracker-attachments-empty" className="text-[12px] text-gray-500">{t('detail.attachments.empty')}</p>}
      {files.length > 0 && <ul className="space-y-1" aria-label={t('detail.attachments.label')}>
        {files.map(file => <li key={file.name} className="flex items-center gap-2 px-2 py-1.5 text-[12px] bg-white border border-gray-100 rounded-md min-w-0">
          <button type="button" onClick={() => void runAction('open', file.name)} disabled={disabled}
            className="flex-1 flex items-center gap-2 min-w-0 min-h-9 text-left disabled:opacity-50" aria-label={t('detail.attachments.openAria', { name: file.name })}>
            {action?.kind === 'open' && action.name === file.name ? <Loader2 className="w-3 h-3 animate-spin shrink-0" aria-hidden="true" /> : <ExternalLink className="w-3 h-3 shrink-0" aria-hidden="true" />}
            <span className="truncate text-gray-700">{file.name}</span>
            <span className="ml-auto text-[10px] text-gray-500 shrink-0 tabular-nums">{formatBytes(file.sizeBytes, t)}</span>
          </button>
          <button type="button" onClick={() => void runAction('delete', file.name)} disabled={disabled}
            className="text-gray-500 hover:text-red-500 p-2 min-h-9 rounded disabled:opacity-50" aria-label={t('detail.attachments.deleteAria', { name: file.name })}>
            {action?.kind === 'delete' && action.name === file.name ? <Loader2 className="w-3 h-3 animate-spin" aria-hidden="true" /> : <Trash2 className="w-3 h-3" aria-hidden="true" />}
          </button>
        </li>)}
      </ul>}
    </section>
  );
}
