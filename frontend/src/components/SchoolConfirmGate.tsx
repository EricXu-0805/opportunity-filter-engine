'use client';

import { useCallback, useEffect, useState } from 'react';
import UniversitySwitcherModal from '@/components/UniversitySwitcherModal';
import { useT } from '@/i18n/client';
import { track } from '@/lib/analytics';
import {
  isSchoolConfirmed,
  persistHomeSchool,
  recordSchoolConfirmation,
} from '@/lib/school-confirmation';
import { HOME_SCHOOL_EVENT, STORAGE_KEYS } from '@/lib/storage-keys';

// Session-scoped soft-gate dismissal: closing the prompt parks it until the
// next browser session instead of nagging every navigation. Deliberately NOT
// the confirmation itself — matching keeps running on the unconfirmed school
// meanwhile (honest, not hostage-taking).
const SESSION_DEFER_KEY = 'ofe_school_confirm_deferred';

/**
 * W10b one-time school re-confirmation. Existing users (tour already seen)
 * whose profile school carries no confirmation receipt see the school picker
 * ONCE, pre-selected on their current campus: one click confirms (or changes)
 * and writes the receipt, and every other school-choosing flow (onboarding
 * finish, profile switcher) writes the same receipt — so nobody is asked
 * twice. New users never see this: their tour's school gate confirms.
 */
export default function SchoolConfirmGate() {
  const { t } = useT();
  const [pendingSlug, setPendingSlug] = useState<string | null>(null);

  const evaluate = useCallback((): string | null => {
    try {
      // The first-visit tour still owns brand-new users (it ends on its own
      // school gate, which records the confirmation).
      if (localStorage.getItem(STORAGE_KEYS.ONBOARDING_SEEN) !== '1') return null;
      if (sessionStorage.getItem(SESSION_DEFER_KEY) === '1') return null;
      const raw = localStorage.getItem(STORAGE_KEYS.PROFILE);
      if (!raw) return null; // no profile yet — nothing to confirm
      const parsed: unknown = JSON.parse(raw);
      if (!parsed || typeof parsed !== 'object') return null;
      const stored = (parsed as { home_school?: unknown }).home_school;
      // Pre-school-gate profiles have no home_school; they have been matched
      // as UIUC all along (the api-layer default), so that is what the user
      // is asked to confirm or correct.
      const slug = typeof stored === 'string' && stored ? stored : 'uiuc';
      return isSchoolConfirmed(slug) ? null : slug;
    } catch {
      return null;
    }
  }, []);

  useEffect(() => {
    /* eslint-disable-next-line react-hooks/set-state-in-effect --
       gate decision reads localStorage (window-only), so it must run after
       mount to avoid an SSR/hydration mismatch (same as OnboardingIntro) */
    setPendingSlug(evaluate());
    const reevaluate = () => setPendingSlug(evaluate());
    // HOME_SCHOOL_EVENT: the tour just confirmed, or the school changed live.
    // 'storage': an account switch cleared SCHOOL_CONFIRMED (identity-owner
    // dispatches a synthetic StorageEvent per cleared key) or another tab
    // confirmed — both must re-run the decision.
    window.addEventListener(HOME_SCHOOL_EVENT, reevaluate);
    window.addEventListener('storage', reevaluate);
    return () => {
      window.removeEventListener(HOME_SCHOOL_EVENT, reevaluate);
      window.removeEventListener('storage', reevaluate);
    };
  }, [evaluate]);

  if (!pendingSlug) return null;

  return (
    <UniversitySwitcherModal
      initialSelectedSlug={pendingSlug}
      title={t('schoolConfirm.title')}
      note={t('schoolConfirm.note')}
      confirmLabel={t('schoolConfirm.confirm')}
      onCancel={() => {
        try { sessionStorage.setItem(SESSION_DEFER_KEY, '1'); } catch { /* ignore */ }
        setPendingSlug(null);
      }}
      onConfirm={(slug) => {
        // Receipt before persist: persistHomeSchool broadcasts
        // HOME_SCHOOL_EVENT, and re-evaluation must already see it confirmed.
        recordSchoolConfirmation(slug);
        persistHomeSchool(slug);
        track('school_confirmed', { school: slug, changed: slug !== pendingSlug });
        setPendingSlug(null);
      }}
    />
  );
}
