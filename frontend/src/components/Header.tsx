'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useCallback, useEffect, useRef, useState } from 'react';
import { Menu, Sparkles, X } from 'lucide-react';
import { useT } from '@/i18n/client';
import { hasMatchCache as readHasMatchCache } from '@/lib/match-cache';
import { onLocalOwnerStateChange } from '@/lib/identity-owner';
import { RELEASE_SCOPE } from '@/lib/release-scope';
import { useNewMatchCount } from '@/lib/use-new-match-count';
import AccountMenu from './AccountMenu';
import LanguageSwitcher from './LanguageSwitcher';

const NAV_ITEMS = [
  { href: '/', labelKey: 'nav.findMatches', shortKey: 'nav.findShort' },
  ...(RELEASE_SCOPE.fellowships
    ? [{ href: '/fellowships', labelKey: 'nav.fellowships', shortKey: 'nav.fellowshipsShort' }]
    : []),
  { href: '/favorites', labelKey: 'nav.favorites', shortKey: 'nav.favShort' },
  { href: '/tracker', labelKey: 'nav.tracker', shortKey: 'nav.trackerShort' },
  ...(RELEASE_SCOPE.roadmap
    ? [{ href: '/roadmap', labelKey: 'nav.roadmap', shortKey: 'nav.roadmapShort' }]
    : []),
  { href: '/dashboard', labelKey: 'nav.dashboard', shortKey: 'nav.dashShort' },
  { href: '/import', labelKey: 'nav.import', shortKey: 'nav.importShort' },
  { href: '/resources', labelKey: 'nav.resources', shortKey: 'nav.resourcesShort' },
  { href: '/about', labelKey: 'nav.about', shortKey: 'nav.aboutShort' },
] as const;

function NewMatchBadge({
  count,
  t,
}: {
  count: number;
  t: (key: string, vars?: Record<string, string | number>) => string;
}) {
  return (
    <span
      aria-label={t('nav.newMatchesAria', { count })}
      className="ml-1.5 inline-flex items-center justify-center min-w-[16px] h-4 px-1 rounded-full bg-orange-500 text-white text-[10px] font-semibold align-middle"
    >
      {count > 99 ? '99+' : count}
    </span>
  );
}

export default function Header() {
  const pathname = usePathname();
  const { t } = useT();
  const newMatchCount = useNewMatchCount();
  const [open, setOpen] = useState(false);
  const headerRef = useRef<HTMLElement | null>(null);

  // R67 problem #3: "Find Matches" should take users back to /results
  // when they have a generated match set cached in sessionStorage. The
  // previous behavior — always routing to / — meant tab-switching away
  // and back made the matches appear to "disappear", because the user
  // was looking at the profile form, not their results. The cache
  // itself in the versioned match-results cache is never invalidated by navigation;
  // it only invalidates on profile-hash mismatch inside useResultsData.
  //
  // We re-check on every pathname change so the link target stays in
  // sync as the user generates new matches mid-session. sessionStorage
  // is window-only so the initial state has to start false to avoid
  // SSR/hydration mismatch; useEffect runs after the first paint and
  // upgrades to the real value before any user interaction.
  //
  // Pathname alone misses an identity change on the SAME page (sign-out
  // from the account menu without navigating): the cache is USER_SCOPED,
  // so a switch can make it newly blocked (still-loading identity) or
  // newly present/absent for the new owner, yet the link would keep
  // pointing at whatever was true for the PREVIOUS identity until the
  // next navigation. Re-check on 'storage' (writeMatchCache/clearMatchCache
  // dispatch it THEMSELVES, only after their own write/remove is confirmed —
  // writeUserScopedRaw/removeUserScopedRaw never dispatch anything on their
  // own) and on identity-owner's own readiness transitions too.
  const [hasMatchCache, setHasMatchCache] = useState(false);
  useEffect(() => {
    const recheck = () => {
      try { setHasMatchCache(readHasMatchCache()); }
      catch { setHasMatchCache(false); }
    };
    recheck();
    window.addEventListener('storage', recheck);
    const unsubscribeOwner = onLocalOwnerStateChange(recheck);
    return () => {
      window.removeEventListener('storage', recheck);
      unsubscribeOwner();
    };
  }, [pathname]);

  const close = useCallback(() => setOpen(false), []);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false);
    };
    /* Click-outside close (R47): a mousedown anywhere outside the <header>
       element collapses the mobile panel. mousedown (not click) fires
       before any nested link click handler, so the close happens even if
       the user taps a non-nav element on the page below. Listener only
       lives while the panel is open — the cleanup removes it on close,
       so no stale handlers leak. */
    const onMouseDown = (e: MouseEvent) => {
      const target = e.target as Node | null;
      if (target && headerRef.current && !headerRef.current.contains(target)) {
        setOpen(false);
      }
    };
    window.addEventListener('keydown', onKey);
    document.addEventListener('mousedown', onMouseDown);
    return () => {
      window.removeEventListener('keydown', onKey);
      document.removeEventListener('mousedown', onMouseDown);
    };
  }, [open]);

  const isActive = (href: string) =>
    href === '/'
      ? pathname === '/' || pathname === '/results'
      : pathname.startsWith(href);

  return (
    <header
      ref={headerRef}
      className="fixed top-0 left-0 right-0 z-50 bg-white/70 backdrop-blur-xl backdrop-saturate-150 border-b border-black/[0.06]"
    >
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex items-center justify-between h-12">
          <Link href="/" className="flex items-center gap-2 group shrink-0" onClick={close}>
            <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-indigo-600 to-indigo-500 flex items-center justify-center shrink-0">
              <Sparkles className="w-3.5 h-3.5 text-white" strokeWidth={2.5} aria-hidden="true" />
            </div>
            <span className="hidden sm:inline text-[15px] font-semibold text-gray-900 tracking-tight">
              JoinA<span className="text-indigo-600">Lab</span>
            </span>
          </Link>

          <nav className="hidden sm:flex items-center gap-0.5 min-w-0" aria-label={t('nav.primary')}>
            {NAV_ITEMS.map(({ href: originalHref, labelKey }) => {
              const href = originalHref === '/' && hasMatchCache ? '/results' : originalHref;
              const showBadge = originalHref === '/favorites' && newMatchCount > 0;
              return (
                <Link
                  key={originalHref}
                  href={href}
                  className={`px-3.5 py-1.5 rounded-full text-[13px] font-medium shrink-0 transition-all duration-300
                    ${
                      isActive(originalHref)
                        ? 'bg-black/[0.06] text-gray-900'
                        : 'text-gray-500 hover:text-gray-900 hover:bg-black/[0.04]'
                    }`}
                >
                  {t(labelKey)}
                  {showBadge && <NewMatchBadge count={newMatchCount} t={t} />}
                </Link>
              );
            })}
            <AccountMenu />
            <LanguageSwitcher />
          </nav>

          <div className="flex sm:hidden items-center gap-1">
            <AccountMenu />
            <LanguageSwitcher />
            <button
              type="button"
              onClick={() => setOpen((o) => !o)}
              aria-label={open ? t('nav.menuClose') : t('nav.menuOpen')}
              aria-expanded={open}
              aria-controls="mobile-nav-panel"
              data-testid="mobile-nav-toggle"
              className="inline-flex items-center justify-center w-9 h-7 rounded-full text-gray-600 hover:text-gray-900 hover:bg-black/[0.04] focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 transition-colors"
            >
              {open ? <X className="w-4 h-4" /> : <Menu className="w-4 h-4" />}
            </button>
          </div>
        </div>

        <div
          id="mobile-nav-panel"
          aria-hidden={!open}
          className={`sm:hidden overflow-hidden transition-[max-height,opacity] duration-300 ease-out ${
            open ? 'max-h-96 opacity-100' : 'max-h-0 opacity-0'
          }`}
        >
          <nav className="flex flex-col pb-3 pt-1 gap-0.5" aria-label={t('nav.mobile')}>
            {NAV_ITEMS.map(({ href: originalHref, labelKey }) => {
              const href = originalHref === '/' && hasMatchCache ? '/results' : originalHref;
              const showBadge = originalHref === '/favorites' && newMatchCount > 0;
              return (
                <Link
                  key={originalHref}
                  href={href}
                  onClick={close}
                  tabIndex={open ? 0 : -1}
                  className={`px-3.5 py-2 rounded-xl text-[14px] font-medium transition-colors
                    ${
                      isActive(originalHref)
                        ? 'bg-black/[0.06] text-gray-900'
                        : 'text-gray-600 hover:text-gray-900 hover:bg-black/[0.04]'
                    }`}
                >
                  {t(labelKey)}
                  {showBadge && <NewMatchBadge count={newMatchCount} t={t} />}
                </Link>
              );
            })}
            <AccountMenu variant="mobile" onActivate={close} tabIndex={open ? 0 : -1} />
          </nav>
        </div>
      </div>
    </header>
  );
}
