'use client';

import { useEffect, useRef, useState } from 'react';
import { captureOwnerToken, isOwnerTokenValid } from '@/lib/identity-owner';
import { fields, listShares, previewShare, publishShare, revokeShare, shareFieldLabels, type PublishedShare, type ShareField } from '@/lib/managed-profile-share';
import { ShareFields } from './ShareFields';

const button = 'rounded-lg border border-gray-300 px-3 py-2 font-medium disabled:opacity-50';
const primary = 'rounded-lg bg-indigo-700 px-3 py-2 font-medium text-white disabled:opacity-50';
function localDate(date: Date) {
  return new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
}
function nextWeek() { return localDate(new Date(Date.now() + 7 * 86400000)); }
function shareUrl(token: string) { return window.location.origin + '/share#' + token; }

export function ShareManager({ uid, zh }: { uid: string; zh: boolean }) {
  const txt = (en: string, cn: string) => zh ? cn : en;
  const [clock, setClock] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => setClock(Date.now()), 60_000);
    return () => clearInterval(timer);
  }, []);
  const [links, setLinks] = useState<PublishedShare[] | null>(null);
  const [load, setLoad] = useState(0);
  const [readFailed, setReadFailed] = useState(false);
  const [edit, setEdit] = useState<PublishedShare | null>(null);
  const [selected, setSelected] = useState<ShareField[]>([]);
  const [expiry, setExpiry] = useState(nextWeek);
  const [preview, setPreview] = useState<Awaited<ReturnType<typeof previewShare>> | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState('');
  const [published, setPublished] = useState('');
  const pendingToken = useRef<string | null>(null);

  useEffect(() => {
    const owner = captureOwnerToken();
    let live = true;
    listShares(uid).then(items => {
      if (live && isOwnerTokenValid(owner, uid)) { setLinks(items); setReadFailed(false); }
    }).catch(() => { if (live && isOwnerTokenValid(owner, uid)) setReadFailed(true); });
    return () => { live = false; };
  }, [uid, load]);

  function reset(item: PublishedShare | null) {
    setEdit(item); setSelected(item?.fields ?? []); setExpiry(item ? localDate(new Date(item.expires_at)) : nextWeek());
    setPreview(null); setPublished(''); setNotice(''); pendingToken.current = null;
  }
  async function run(task: (current: () => boolean) => Promise<void>) {
    if (busy) return;
    const owner = captureOwnerToken();
    const current = () => isOwnerTokenValid(owner, uid);
    if (!current()) return;
    setBusy(true); setNotice('');
    try { await task(current); }
    catch { if (current()) setNotice(txt('Could not complete that request. Your choices are kept. Try again.', '操作未完成，已保留选择，请重试。')); }
    finally { if (current()) setBusy(false); }
  }
  function checkPreview() {
    void run(async current => {
      const reviewed = await previewShare(uid, selected);
      if (current()) setPreview(reviewed);
    });
  }
  function save() {
    if (!preview) return;
    void run(async current => {
      const token = edit?.token ?? (pendingToken.current ??= crypto.randomUUID());
      const status = await publishShare(uid, token, edit?.version ?? 0, selected, new Date(expiry).toISOString(), preview.profileRevision);
      if (!current()) return;
      if (status === 'published') { reset(null); setPublished(shareUrl(token)); setLoad(n => n + 1); return; }
      setPreview(null);
      if (status === 'profile_changed') setNotice(txt('Your saved profile changed. Preview the updated fields.', '已保存的资料有变化，请重新预览。'));
      else { reset(null); setNotice(txt('This link changed. Select its current version below.', '分享链接有变化，请从下方选择最新版本。')); setLoad(n => n + 1); }
    });
  }
  function revoke(item: PublishedShare) {
    void run(async current => {
      const status = await revokeShare(item);
      if (!current()) return;
      if (edit?.token === item.token) reset(null);
      if (published === shareUrl(item.token)) setPublished('');
      setNotice(status === 'revoked' ? txt('Link revoked.', '已撤销链接。') : txt('This link changed. Review its current version.', '链接有变化，请核对最新版本。'));
      setLoad(n => n + 1);
    });
  }
  const end = Date.parse(expiry);
  return (
    <div className="space-y-7">
      <section className="space-y-4">
        <h1 className="text-2xl font-semibold">{edit ? txt('Replace shared profile', '替换已分享的资料') : txt('Share your profile', '分享我的资料')}</h1>
        <p>{txt('Choose fields from your saved profile. Anyone with the link can view them until it expires or you revoke it.', '选择已保存资料的字段。拿到链接的人可在到期或撤销之前查看。')}</p>
        <fieldset disabled={busy} className="grid gap-2 sm:grid-cols-2">
          <legend className="mb-2 font-medium">{txt('Fields to share', '要分享的字段')}</legend>
          {fields.map(field => <label key={field} className="flex gap-2">
            <input type="checkbox" checked={selected.includes(field)} onChange={e => {
              setPreview(null); setSelected(e.target.checked ? [...selected, field] : selected.filter(k => k !== field));
            }} />{shareFieldLabels[field][zh ? 1 : 0]}
          </label>)}
        </fieldset>
        <label className="block">{txt('Expiry in your local time', '到期时间（本地时间）')}
          <input className="ml-3 rounded border px-2 py-1" type="datetime-local" value={expiry} disabled={busy}
            onChange={e => { setExpiry(e.target.value); setPreview(null); }} />
        </label>
        {preview && <ShareFields snapshot={preview.snapshot} zh={zh} />}
        <div className="flex flex-wrap gap-3">
          {!preview ? <button type="button" className={primary} disabled={busy || !selected.length || !(end > clock)} onClick={checkPreview}>{txt('Preview selected fields', '预览所选字段')}</button>
            : <button type="button" className={primary} disabled={busy || !(end > clock)} onClick={save}>{edit ? txt('Replace at the same link', '替换原链接内容') : txt('Create share link', '创建分享链接')}</button>}
          {edit && <button type="button" className={button} disabled={busy} onClick={() => reset(null)}>{txt('Cancel replacement', '取消替换')}</button>}
        </div>
        {published && <label className="block">{txt('Share link', '分享链接')}<input className="mt-1 w-full rounded border px-2 py-2" readOnly value={published} onFocus={e => e.target.select()} /></label>}
        {notice && <p role="status">{notice}</p>}
      </section>
      <section className="space-y-3">
        <h2 className="text-lg font-semibold">{txt('Your links', '我的分享链接')}</h2>
        {readFailed ? <button className={button} type="button" onClick={() => setLoad(n => n + 1)}>{txt('Could not load links. Retry', '读取失败，重试')}</button>
          : links === null ? <p>{txt('Loading links…', '正在读取链接…')}</p> : !links.length ? <p>{txt('No published links.', '尚未发布分享链接。')}</p> : null}
        {links?.map(item => <div key={item.token} className="space-y-2 border-t py-3">
          <p>{item.fields.map(k => shareFieldLabels[k][zh ? 1 : 0]).join(' · ')} · {txt('Version', '版本')} {item.version}</p>
          <p className="text-sm">{item.revoked_at ? txt('Revoked', '已撤销') : new Date(item.expires_at).toLocaleString(zh ? 'zh' : 'en') + ' · ' + (Date.parse(item.expires_at) <= clock ? txt('Expired', '已到期') : txt('Expires', '到期'))}</p>
          {!item.revoked_at && <div className="flex flex-wrap gap-2">
            <button type="button" className={button} disabled={busy} onClick={() => setPublished(shareUrl(item.token))}>{txt('Show link', '显示链接')}</button>
            <button type="button" className={button} disabled={busy} onClick={() => reset(item)}>{txt('Replace version', '替换版本')}</button>
            <button type="button" className={button} disabled={busy} onClick={() => revoke(item)}>{txt('Revoke link', '撤销链接')}</button>
          </div>}
        </div>)}
      </section>
    </div>
  );
}
