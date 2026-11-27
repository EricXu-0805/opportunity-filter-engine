'use client';

import Link from 'next/link';
import { useEffect, useRef, useState } from 'react';
import HomePage from '@/app/home/HomePage';
import type { AcceptedProfileShare } from '@/app/home/use-profile-form';
import { captureOwnerToken, isOwnerTokenValid, onLocalOwnerStateChange } from '@/lib/identity-owner';
import { decodeSelectedShare } from '@/lib/profile-share';
import { migrateProfile, type LegacyProfileShape } from '@/lib/profile-compat';
import { resolveShare } from '@/lib/managed-profile-share';
import { loadProfile } from '@/lib/supabase';
import { ShareFields } from './ShareFields';

export function ShareRecipient({ token, zh }: { token: string; zh: boolean }) {
  const txt = (en: string, cn: string) => zh ? cn : en;
  const [view, setView] = useState<Awaited<ReturnType<typeof resolveShare>> | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [failed, setFailed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [changed, setChanged] = useState(false);
  const [accepted, setAccepted] = useState<AcceptedProfileShare | null>(null);
  const live = useRef(false);
  useEffect(() => {
    live.current = true;
    return () => { live.current = false; };
  }, []);
  useEffect(() => {
    let current = true;
    resolveShare(token).then(result => {
      if (current) { setView(result); setFailed(false); }
    }).catch(() => { if (current) setFailed(true); });
    return () => { current = false; };
  }, [token, attempt]);
  useEffect(() => {
    if (!accepted) return;
    return onLocalOwnerStateChange(() => {
      if (!isOwnerTokenValid(accepted.owner, accepted.owner.uid)) {
        setAccepted(null); setAttempt(n => n + 1);
      }
    });
  }, [accepted]);

  async function accept() {
    if (busy || view?.status !== 'active') return;
    const initial = captureOwnerToken();
    setBusy(true); setFailed(false);
    try {
      const own = await loadProfile();
      if (!live.current || (initial.uid && (initial.uid !== own.token.uid || initial.epoch !== own.token.epoch))) return;
      if (own.source === 'local-only' || !isOwnerTokenValid(own.token, own.token.uid)) throw new Error('profile_unavailable');
      const checked = await resolveShare(token, view.version);
      if (!live.current || !isOwnerTokenValid(own.token, own.token.uid)) return;
      if (checked.status !== 'active') {
        setView(checked);
        if (checked.status === 'changed') { setChanged(true); setAttempt(n => n + 1); }
        return;
      }
      const selected = decodeSelectedShare(checked.snapshot);
      const existing = migrateProfile(own.profile as LegacyProfileShape | null);
      setAccepted({ key: token + '/' + checked.version, owner: own.token, profile: { ...existing, ...selected.profile }, keys: selected.keys });
    } catch { if (live.current) setFailed(true); }
    finally { if (live.current) setBusy(false); }
  }
  if (accepted && isOwnerTokenValid(accepted.owner, accepted.owner.uid)) return <HomePage acceptedShare={accepted} />;
  return (
    <main className="mx-auto max-w-2xl space-y-4 px-5 py-10">
      <h1 className="text-2xl font-semibold">{txt('Shared profile', '分享的资料')}</h1>
      {failed && <div role="alert">{txt('Could not read the current version. Your profile is unchanged.', '未能读取当前版本，你的资料保持原样。')}
        <button className="ml-2 underline" onClick={() => { setFailed(false); setView(null); setAttempt(n => n + 1); }}>{txt('Retry', '重试')}</button></div>}
      {!view && !failed && <p>{txt('Loading shared fields…', '正在读取分享字段…')}</p>}
      {view?.status === 'unavailable' && <p>{txt('This link is unavailable or has expired.', '此链接已失效或到期。')}</p>}
      {changed && view?.status === 'active' && <p role="status">{txt('The author published a new version. Review the updated fields before accepting.', '发布者替换了版本。请先核对更新后的字段。')}</p>}
      {view?.status === 'active' && <>
        <p>{txt('Version', '版本')} {view.version} · {txt('Expires', '到期')} {new Date(view.expiresAt).toLocaleString(zh ? 'zh' : 'en')}</p>
        <ShareFields snapshot={view.snapshot} zh={zh} />
        <p>{txt('Accept to review these fields in your profile. Your edits are saved when you generate matches.', '接受后可在个人资料中核对这些字段，点击生成匹配后保存。')}</p>
        <button type="button" disabled={busy || failed} className="rounded-lg bg-indigo-700 px-4 py-2 text-white disabled:opacity-50" onClick={() => void accept()}>{txt('Accept selected fields', '接受所选字段')}</button>
      </>}
      <Link href="/" className="ml-3 underline">{view?.status === 'active' ? txt('Decline and return to my profile', '拒绝并返回我的资料') : txt('Return to my profile', '返回我的资料')}</Link>
    </main>
  );
}
