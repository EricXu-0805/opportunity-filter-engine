'use client';

/*
 * /account — the user's own hub: identity, profile snapshot, activity links,
 * and plan. Deliberately does NOT rebuild the dashboard / favorites / tracker —
 * it links out to them. Works for anonymous (device-only) sessions too: instead
 * of a hard redirect, guests get a "save my account" prompt plus whatever local
 * profile they've built.
 */

import { useEffect, useState } from 'react';
import Link from 'next/link';
import {
  BookmarkCheck,
  ClipboardList,
  Compass,
  LayoutDashboard,
  LogOut,
  Pencil,
  Sparkles,
  UserRound,
} from 'lucide-react';
import Card from '@/components/Card';
import { useT } from '@/i18n/client';
import { useAuthModal } from '@/lib/auth-modal-context';
import {
  getAuthState,
  getFavorites,
  getInteractionsFull,
  loadProfile,
  onAuthChange,
  type AuthState,
} from '@/lib/supabase';

interface Snapshot {
  name: string;
  school: string;
  major: string;
  year: string;
  interests: string;
  skillCount: number;
  hasProfile: boolean;
}

function toSnapshot(raw: Record<string, unknown> | null): Snapshot {
  const str = (v: unknown) => (typeof v === 'string' ? v.trim() : '');
  const skills = Array.isArray(raw?.skills) ? raw!.skills : [];
  const name = str(raw?.name);
  const school = str(raw?.institution) || str(raw?.home_school);
  const major = str(raw?.major);
  const year = str(raw?.grade);
  const interests = str(raw?.research_interests);
  return {
    name,
    school,
    major,
    year,
    interests,
    skillCount: skills.length,
    hasProfile: Boolean(major || interests || skills.length || school || year),
  };
}

export default function AccountPage() {
  const { t } = useT();
  const { openModal } = useAuthModal();
  const [auth, setAuth] = useState<AuthState | null>(null);
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [favCount, setFavCount] = useState<number | null>(null);
  const [trackCount, setTrackCount] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const [authState, profile, favs, interactions] = await Promise.all([
          getAuthState(),
          loadProfile(),
          getFavorites(),
          getInteractionsFull(),
        ]);
        if (cancelled) return;
        setAuth(authState);
        setSnapshot(toSnapshot(profile));
        setFavCount(favs.size);
        setTrackCount(interactions.size);
      } catch {
        // A rejected auth/storage promise must never strand the page on the
        // loading spinner — fall through to render the guest + empty-profile
        // state instead of an infinite "Loading…".
        if (!cancelled) setSnapshot(toSnapshot(null));
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    const unsub = onAuthChange((s) => { if (!cancelled) setAuth(s); });
    return () => { cancelled = true; unsub(); };
  }, []);

  const isPermanent = Boolean(auth?.user && !auth.isAnonymous);
  const email = auth?.email ?? '';
  const empty = t('account.empty');

  return (
    <div className="max-w-3xl mx-auto px-4 sm:px-6 lg:px-8 py-10 sm:py-16">
      <div className="mb-8">
        <h1 className="text-2xl sm:text-3xl font-bold text-gray-900">{t('account.title')}</h1>
        <p className="text-sm text-gray-400 mt-1">{t('account.subtitle')}</p>
      </div>

      {loading ? (
        <p className="text-sm text-gray-400">{t('account.loading')}</p>
      ) : (
        <div className="space-y-6">
          {/* ── Identity ── */}
          <Card>
            <div className="flex items-start justify-between gap-4">
              <div className="flex items-center gap-4 min-w-0">
                <span className="w-12 h-12 rounded-full bg-blue-100 text-blue-700 text-lg font-semibold uppercase flex items-center justify-center shrink-0">
                  {email ? email[0].toUpperCase() : <UserRound className="w-6 h-6" aria-hidden="true" />}
                </span>
                <div className="min-w-0">
                  <p className="text-base font-semibold text-gray-900 truncate">
                    {email || t('account.guestBadge')}
                  </p>
                  <span
                    className={`inline-block mt-1 px-2 py-0.5 rounded-full text-[11px] font-medium ${
                      isPermanent ? 'bg-emerald-50 text-emerald-700' : 'bg-amber-50 text-amber-700'
                    }`}
                  >
                    {isPermanent ? t('account.signedInBadge') : t('account.guestBadge')}
                  </span>
                </div>
              </div>
              {isPermanent ? (
                <button
                  type="button"
                  onClick={() => openModal({ reason: 'header', phase: 'signout-confirm' })}
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-[13px] font-medium text-gray-600 hover:bg-gray-50 border border-gray-200 transition-colors shrink-0"
                >
                  <LogOut className="w-3.5 h-3.5" aria-hidden="true" />
                  {t('account.signOut')}
                </button>
              ) : (
                <button
                  type="button"
                  onClick={() => openModal({ reason: 'header' })}
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-[13px] font-medium text-blue-700 bg-blue-50 hover:bg-blue-100 transition-colors shrink-0"
                >
                  <Sparkles className="w-3.5 h-3.5" aria-hidden="true" />
                  {t('account.saveAccount')}
                </button>
              )}
            </div>
            {!isPermanent && (
              <p className="mt-4 text-[13px] text-gray-500">{t('account.guestHint')}</p>
            )}
          </Card>

          {/* ── Profile snapshot ── */}
          <Card>
            <div className="flex items-center justify-between mb-5">
              <h2 className="text-lg font-bold text-gray-900">{t('account.profileTitle')}</h2>
              <Link
                href="/"
                className="inline-flex items-center gap-1.5 text-[13px] font-medium text-indigo-600 hover:text-indigo-700 transition-colors"
              >
                <Pencil className="w-3.5 h-3.5" aria-hidden="true" />
                {t('account.editProfile')}
              </Link>
            </div>
            {snapshot?.hasProfile ? (
              <dl className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <Field label={t('account.fieldSchool')} value={snapshot.school || empty} />
                <Field label={t('account.fieldMajor')} value={snapshot.major || empty} />
                <Field label={t('account.fieldYear')} value={snapshot.year || empty} />
                <Field
                  label={t('account.fieldSkills')}
                  value={snapshot.skillCount ? String(snapshot.skillCount) : empty}
                />
                <div className="sm:col-span-2">
                  <Field label={t('account.fieldInterests')} value={snapshot.interests || empty} />
                </div>
              </dl>
            ) : (
              <div className="text-center py-6">
                <p className="text-sm text-gray-500 mb-4">{t('account.noProfile')}</p>
                <Link
                  href="/"
                  className="inline-flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-medium text-white bg-indigo-600 hover:bg-indigo-700 transition-colors"
                >
                  <Compass className="w-4 h-4" aria-hidden="true" />
                  {t('account.createProfile')}
                </Link>
              </div>
            )}
          </Card>

          {/* ── Activity (links out — does NOT rebuild these) ── */}
          <Card>
            <h2 className="text-lg font-bold text-gray-900 mb-5">{t('account.activityTitle')}</h2>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
              <ActivityTile
                href="/favorites"
                icon={BookmarkCheck}
                label={t('account.favorites')}
                desc={t('account.favoritesDesc')}
                count={favCount}
              />
              <ActivityTile
                href="/tracker"
                icon={ClipboardList}
                label={t('account.tracker')}
                desc={t('account.trackerDesc')}
                count={trackCount}
              />
              <ActivityTile
                href="/dashboard"
                icon={LayoutDashboard}
                label={t('account.dashboard')}
                desc={t('account.dashboardDesc')}
                count={null}
              />
            </div>
          </Card>

          {/* ── Plan (deferred billing placeholder — no pricing yet) ── */}
          <Card>
            <h2 className="text-lg font-bold text-gray-900 mb-5">{t('account.planTitle')}</h2>
            <div className="flex items-center justify-between gap-4 pb-4 border-b border-gray-100">
              <div>
                <p className="text-sm font-semibold text-gray-900">{t('account.freePlan')}</p>
                <p className="text-[13px] text-gray-500 mt-0.5">{t('account.freePlanDesc')}</p>
              </div>
              <span className="px-2.5 py-1 rounded-full text-[11px] font-medium bg-gray-100 text-gray-600 shrink-0">
                {t('account.currentBadge')}
              </span>
            </div>
            <div className="flex items-center justify-between gap-4 pt-4 opacity-70">
              <div>
                <p className="text-sm font-semibold text-gray-900">{t('account.premiumTitle')}</p>
                <p className="text-[13px] text-gray-500 mt-0.5">{t('account.premiumDesc')}</p>
              </div>
              <span className="px-2.5 py-1 rounded-full text-[11px] font-medium bg-indigo-50 text-indigo-600 shrink-0">
                {t('account.comingSoon')}
              </span>
            </div>
          </Card>
        </div>
      )}
    </div>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-[11px] font-medium uppercase tracking-wide text-gray-400">{label}</dt>
      <dd className="text-sm text-gray-800 mt-1 break-words">{value}</dd>
    </div>
  );
}

function ActivityTile({
  href,
  icon: Icon,
  label,
  desc,
  count,
}: {
  href: string;
  icon: React.ElementType;
  label: string;
  desc: string;
  count: number | null;
}) {
  return (
    <Link
      href={href}
      className="block rounded-2xl border border-gray-100 p-4 hover:border-indigo-200 hover:bg-indigo-50/30 transition-colors"
    >
      <div className="flex items-center justify-between mb-2">
        <Icon className="w-5 h-5 text-indigo-500" aria-hidden="true" />
        {count !== null && (
          <span className="text-lg font-bold text-gray-900">{count}</span>
        )}
      </div>
      <p className="text-sm font-semibold text-gray-800">{label}</p>
      <p className="text-[12px] text-gray-400 mt-0.5">{desc}</p>
    </Link>
  );
}
