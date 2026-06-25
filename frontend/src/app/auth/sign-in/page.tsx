'use client';

/*
 * R66: /auth/sign-in is no longer the primary sign-in surface.
 * The AuthModal (opened from the Header AccountMenu, the "Save to
 * account" CTA, anchors, etc.) does the real work.
 *
 * This route remains for:
 *   - Deep links in email signatures, About page footer, etc.
 *   - Old bookmarks / shared URLs from R65
 *   - Direct navigation by power users
 *
 * Behavior: on mount, open the modal automatically and show a thin
 * fallback page (helps users who load this page with JS disabled or
 * before hydration completes — they at least see what's happening).
 */

import Link from 'next/link';
import { useEffect } from 'react';
import { useAuthModal } from '@/lib/auth-modal-context';
import { useT } from '@/i18n/client';

export default function SignInDeepLinkPage() {
  const { t } = useT();
  const { open, openModal } = useAuthModal();

  // Open the modal once after mount. Subsequent re-renders shouldn't
  // re-open it (so the user can close it without it instantly
  // re-opening).
  useEffect(() => {
    openModal({ reason: 'deep-link' });
    // openModal is stable (useCallback in provider); leave it out of
    // deps to avoid spurious reopens.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="max-w-md mx-auto px-4 py-16 text-center">
      <h1 className="text-[18px] font-semibold text-gray-900">
        {t('auth.deepLink.title')}
      </h1>
      <p className="mt-2 text-sm text-gray-500">
        {t('auth.deepLink.body')}
      </p>
      {!open && (
        <button
          type="button"
          onClick={() => openModal({ reason: 'deep-link' })}
          className="mt-6 inline-flex items-center justify-center px-4 py-2 rounded-full bg-indigo-600 text-white text-sm font-medium hover:bg-indigo-700 transition-colors"
        >
          {t('auth.deepLink.reopen')}
        </button>
      )}
      <div className="mt-8 text-center">
        <Link href="/" className="text-xs text-gray-400 hover:text-gray-600">
          {t('auth.deepLink.backHome')}
        </Link>
      </div>
    </div>
  );
}
