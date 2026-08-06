'use client';

/*
 * SaveFavoritesAnchor — the lone R66 anchor prompt.
 *
 * Trigger rule (Pinterest 3-pin research adapted):
 *   - User is currently anonymous (no email tied)
 *   - User has 3+ favorites locally/remotely
 *   - User has NOT dismissed this anchor on this device
 *
 * Why only one anchor in R66: we'll see how this performs before
 * adding more (profile-complete, first-tracker). Adding all five
 * anchors at once means we can't attribute conversion lift.
 *
 * Why localStorage (not sessionStorage) for the dismiss flag: a
 * dismissed-but-still-anon user shouldn't re-see the prompt on
 * tomorrow's session — they made their choice. They can still sign in
 * via the header any time.
 */

import { Sparkles, X } from 'lucide-react';
import { useEffect, useState } from 'react';
import {
  getAuthState,
  onAuthChange,
  type AuthState,
} from '@/lib/supabase';
import { STORAGE_KEYS } from '@/lib/storage-keys';
import {
  captureOwnerToken,
  onLocalOwnerStateChange,
  readUserScopedRaw,
  writeUserScopedRaw,
} from '@/lib/identity-owner';
import { useAuthModal } from '@/lib/auth-modal-context';
import { useT } from '@/i18n/client';

const DISMISS_KEY = STORAGE_KEYS.ANCHOR_3FAV_DISMISSED;
const THRESHOLD = 3;

interface SaveFavoritesAnchorProps {
  /** Current favorites count, from caller (favorites page already has it). */
  favoriteCount: number;
}

// A `null` read (genuinely never dismissed, OR local ownership not yet
// confirmed for the current identity) is treated as "not dismissed" — the
// worst case is the anchor briefly shows during the readiness window before
// self-correcting on the next owner-state notification, not a data leak.
function readDismissed(): boolean {
  if (typeof window === 'undefined') return true;
  return readUserScopedRaw(DISMISS_KEY) === '1';
}

// `token` MUST be captured at the moment the caller's own dismiss click
// happened — see writeUserScopedRaw's own doc comment. Returns whether it
// actually landed.
function writeDismissed(token: ReturnType<typeof captureOwnerToken>): boolean {
  if (typeof window === 'undefined') return false;
  return writeUserScopedRaw(DISMISS_KEY, '1', token);
}

export default function SaveFavoritesAnchor({ favoriteCount }: SaveFavoritesAnchorProps) {
  const { t } = useT();
  const { openModal } = useAuthModal();
  const [authState, setAuthState] = useState<AuthState | null>(null);
  // Lazy initializer reads localStorage exactly once at mount. Avoids
  // the `react-hooks/set-state-in-effect` lint warning we'd get by
  // calling setState() in the useEffect below.
  const [dismissedLocal, setDismissedLocal] = useState<boolean>(() => readDismissed());

  useEffect(() => {
    let cancelled = false;
    getAuthState().then(s => { if (!cancelled) setAuthState(s); });
    const unsub = onAuthChange(s => { if (!cancelled) setAuthState(s); });
    // Re-read on every readiness transition too: an identity switch (e.g.
    // signing out into a DIFFERENT anon session) must not carry the
    // previous identity's dismiss decision forward.
    const unsubOwner = onLocalOwnerStateChange(() => { if (!cancelled) setDismissedLocal(readDismissed()); });
    return () => { cancelled = true; unsub(); unsubOwner(); };
  }, []);

  // We only render once we've actually read the auth state (else we'd
  // briefly show the anchor for a freshly-signed-in user during the
  // first paint, which looks like a glitch).
  const isAnon = authState !== null && (!authState.user || authState.isAnonymous);
  const shouldShow = isAnon && favoriteCount >= THRESHOLD && !dismissedLocal;

  const handleDismiss = () => {
    if (writeDismissed(captureOwnerToken())) setDismissedLocal(true);
  };

  if (!shouldShow) return null;

  return (
    <div
      role="region"
      data-testid="save-favorites-anchor"
      className="mb-6 rounded-2xl border border-indigo-200 bg-gradient-to-br from-indigo-50 to-indigo-50 px-5 py-4"
    >
      <div className="flex items-start gap-3">
        <div className="w-10 h-10 rounded-xl bg-white shrink-0 flex items-center justify-center shadow-sm">
          <Sparkles className="w-5 h-5 text-indigo-600" aria-hidden="true" />
        </div>
        <div className="flex-1 min-w-0">
          <h3 className="text-[14px] font-semibold text-gray-900">
            {t('auth.anchor.favorites3.title', { count: favoriteCount })}
          </h3>
          <p className="text-[12.5px] text-gray-600 mt-0.5 leading-relaxed">
            {t('auth.anchor.favorites3.body')}
          </p>
          <div className="mt-3 flex items-center gap-2 flex-wrap">
            <button
              type="button"
              onClick={() => openModal({ reason: 'save-favorites-anchor' })}
              className="px-3.5 py-1.5 rounded-full bg-indigo-600 text-white text-[12px] font-medium hover:bg-indigo-700 transition-colors"
            >
              {t('auth.anchor.favorites3.cta')}
            </button>
            <button
              type="button"
              onClick={handleDismiss}
              className="px-3 py-1.5 rounded-full text-[12px] text-gray-500 hover:text-gray-700 hover:bg-white transition-colors"
            >
              {t('auth.anchor.favorites3.dismiss')}
            </button>
          </div>
        </div>
        <button
          type="button"
          onClick={handleDismiss}
          aria-label={t('common.dismiss')}
          className="shrink-0 p-1 rounded-lg hover:bg-white transition-colors"
        >
          <X className="w-4 h-4 text-gray-400" />
        </button>
      </div>
    </div>
  );
}
