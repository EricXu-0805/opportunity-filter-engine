'use client';

import { useEffect, useState } from 'react';
import { useT } from '@/i18n/client';
import { getAuthState, onAuthChange, type AuthState } from '@/lib/supabase';
import { managedSharesEnabled } from '@/lib/managed-profile-share';
import { useAuthModal } from '@/lib/auth-modal-context';
import { ShareManager } from './ShareManager';
import { ShareRecipient } from './ShareRecipient';

export function SharePage() {
  const { locale } = useT();
  const zh = locale === 'zh';
  const { openModal } = useAuthModal();
  const [fragment, setFragment] = useState<string | null>(null);
  const [auth, setAuth] = useState<AuthState | null>(null);
  useEffect(() => {
    const changed = () => setFragment(window.location.hash.slice(1));
    changed(); window.addEventListener('hashchange', changed);
    let active = true, observed = false;
    const stop = onAuthChange(state => { observed = true; if (active) setAuth(state); });
    void getAuthState().then(state => { if (active && !observed) setAuth(state); }).catch(() => undefined);
    return () => { active = false; stop(); window.removeEventListener('hashchange', changed); };
  }, []);
  if (fragment === null) return null;
  if (managedSharesEnabled && /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(fragment)) {
    return <ShareRecipient key={fragment} token={fragment} zh={zh} />;
  }
  return <main className="mx-auto max-w-2xl px-5 py-10">
    {!managedSharesEnabled || fragment ? <p>{zh ? '此分享入口暂不可用。' : 'This share link is unavailable.'}</p>
      : !auth ? <p>{zh ? '正在读取账号…' : 'Checking your account…'}</p>
      : auth.user && !auth.isAnonymous ? <ShareManager key={auth.user.id} uid={auth.user.id} zh={zh} />
      : <section className="space-y-4"><h1 className="text-2xl font-semibold">{zh ? '分享我的资料' : 'Share your profile'}</h1>
        <p>{zh ? '请登录后选择分享字段，并管理链接的到期时间、版本和撤销。' : 'Sign in to select the fields you share and manage link expiry, versions and revocation.'}</p>
        <button type="button" className="rounded-lg bg-indigo-700 px-4 py-2 text-white" onClick={() => openModal({phase:'signin'})}>{zh ? '登录' : 'Sign in'}</button>
      </section>}
  </main>;
}
