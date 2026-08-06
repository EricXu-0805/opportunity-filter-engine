'use client';

/*
 * /account — the user's own hub: identity, profile snapshot, activity links,
 * and plan. Deliberately does NOT rebuild the dashboard / favorites / tracker —
 * it links out to them. Works for anonymous (device-only) sessions too: instead
 * of a hard redirect, guests get a "save my account" prompt plus whatever local
 * profile they've built.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
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
import { track } from '@/lib/analytics';
import { useAuthModal } from '@/lib/auth-modal-context';
import {
  getAuthState,
  getFavorites,
  getInteractionsFull,
  joinWaitlist,
  onAuthChange,
  type AuthState,
} from '@/lib/supabase';
import { hydrateProfile } from '@/lib/profile-sync';

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

// Sentinel: expectedUidRef starts here before any live auth event has ever
// fired, meaning "no live-confirmed uid to check a load's result against
// yet — trust getAuthState()'s own resolution." Once any live event
// fires, expectedUidRef holds a real uid (or null), never this sentinel
// again — see the load() commit check below.
const UNCONSTRAINED = Symbol('unconstrained');

export default function AccountPage() {
  const { t } = useT();
  const { openModal } = useAuthModal();
  const [auth, setAuth] = useState<AuthState | null>(null);
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [favCount, setFavCount] = useState<number | null>(null);
  const [trackCount, setTrackCount] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);

  // Bumped on EVERY live auth event whose uid differs from the last KNOWN
  // live uid — including the very first event after subscribing. A first
  // event that happens to report a DIFFERENT identity than whatever the
  // mount's own fetch is loading under is a real, authoritative signal
  // that fetch is already stale; treating "first event" as automatically
  // harmless (the original design) let a slow mount-time fetch commit
  // U1's data even after a live switch to U2 arrived before it resolved.
  const generationRef = useRef(0);
  const lastUidRef = useRef<string | null | undefined>(undefined);
  const cancelledRef = useRef(false);
  // UNCONSTRAINED until the first live event fires — the mount's own load
  // has no live-confirmed uid to check itself against yet, so it trusts
  // whatever getAuthState() resolves to. Once ANY live event fires, this
  // becomes the ground truth every subsequent commit must match — even
  // WITHIN the same generation, a load's own getAuthState() call could
  // itself return a stale uid unrelated to this component's generation
  // counter, which would otherwise let a mismatched auth pair with the
  // new owner's profile/favorites/interactions in one commit.
  const expectedUidRef = useRef<string | null | symbol>(UNCONSTRAINED);

  const load = useCallback(async (generation: number) => {
    try {
      const [authState, hydration, favs, interactions] = await Promise.all([
        getAuthState(),
        hydrateProfile(),
        getFavorites(),
        getInteractionsFull(),
      ]);
      if (cancelledRef.current || generationRef.current !== generation) return;
      const expected = expectedUidRef.current;
      if (expected !== UNCONSTRAINED && (authState.user?.id ?? null) !== expected) {
        // Internally inconsistent resolution — getAuthState() reported a
        // DIFFERENT identity than the one this load was triggered for,
        // even though nothing has superseded this generation. Committing
        // anyway would pair one identity's auth with another's
        // profile/favorites/interactions in a single render. Surface as
        // retryable rather than silently leaving stale/cleared state.
        setLoadError(true);
        return;
      }
      setAuth(authState);
      setSnapshot(toSnapshot(hydration.profile as Record<string, unknown> | null));
      setFavCount(favs.size);
      setTrackCount(interactions.size);
      setLoadError(false);
    } catch {
      // A rejected auth/storage promise is NOT the same as "confirmed no
      // profile" — that used to render toSnapshot(null) (a fabricated
      // empty-profile screen). Surface a distinct retry state instead so
      // a transient failure can never look like "you have no data yet."
      if (cancelledRef.current || generationRef.current !== generation) return;
      setLoadError(true);
    } finally {
      if (!cancelledRef.current && generationRef.current === generation) setLoading(false);
    }
  }, []);

  const retry = useCallback(() => {
    setLoading(true);
    load(generationRef.current);
  }, [load]);

  useEffect(() => {
    cancelledRef.current = false;
    load(generationRef.current);
    const unsub = onAuthChange((s) => {
      if (cancelledRef.current) return;
      const uid = s.user?.id ?? null;
      if (uid === lastUidRef.current) {
        // A genuine same-uid re-observation (TOKEN_REFRESHED etc.) — no
        // reset needed, but this DOES confirm the expected uid going
        // forward for any load that hasn't committed yet.
        expectedUidRef.current = uid;
        setAuth(s);
        return;
      }
      // Every uid change — INCLUDING the very first event this component
      // ever observes (lastUidRef.current starts undefined, which never
      // equals a real uid or null) — is authoritative: invalidate
      // whatever is in flight and rehydrate fresh under this identity.
      lastUidRef.current = uid;
      expectedUidRef.current = uid;
      generationRef.current += 1;
      setAuth(s);
      setLoadError(false);
      setLoading(true);
      load(generationRef.current);
    });
    return () => { cancelledRef.current = true; unsub(); };
  }, [load]);

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
      ) : loadError ? (
        // auth stays null on ANY rejected load — rendering the normal
        // identity/profile/activity cards here would show a CONFIRMED
        // "guest"/"no profile" state built from data we never actually
        // resolved. Show only the error + Retry until a load succeeds.
        <div className="flex items-center justify-between gap-4 p-4 rounded-xl bg-red-50 border border-red-200">
          <p className="text-[13px] text-red-700">{t('account.loadError')}</p>
          <button
            type="button"
            onClick={retry}
            className="shrink-0 px-3 py-1.5 rounded-full text-[13px] font-medium text-red-700 bg-white border border-red-200 hover:bg-red-100 transition-colors"
          >
            {t('common.retry')}
          </button>
        </div>
      ) : (
        <div className="space-y-6">
          {/* ── Identity ── */}
          <Card>
            <div className="flex items-start justify-between gap-4">
              <div className="flex items-center gap-4 min-w-0">
                <span className="w-12 h-12 rounded-full bg-indigo-100 text-indigo-700 text-lg font-semibold uppercase flex items-center justify-center shrink-0">
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
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-[13px] font-medium text-indigo-700 bg-indigo-50 hover:bg-indigo-100 transition-colors shrink-0"
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

          {/* ── Plan — pre-LLC release keeps only the no-price request path. ── */}
          <Card>
            <h2 className="text-lg font-bold text-gray-900 mb-5">{t('account.planTitle')}</h2>
            <PlanRow />
            <div className="flex items-center justify-between gap-4 pt-4">
              <div>
                <p className="text-sm font-semibold text-gray-900">{t('account.premiumTitle')}</p>
                <p className="text-[13px] text-gray-500 mt-0.5">{t('account.premiumDesc')}</p>
              </div>
              {/* No explicit key/reset needed: every identity transition
                  round-trips through the `loading` gate above, which
                  unmounts this ENTIRE branch (a different element type at
                  this tree position) and mounts a fresh one once the new
                  owner's load commits — PremiumIntent's internal
                  email/phase state is destroyed and reseeded from the new
                  `email` prop along with everything else here, not carried
                  over. Confirmed via mutation: removing a bespoke key had
                  no effect on any test. */}
              <PremiumIntent defaultEmail={email} />
            </div>
          </Card>
        </div>
      )}
    </div>
  );
}

// Concierge paid-intent CTA. Clicking records the intent (funnel signal);
// submitting an email writes a waitlist row we follow up on by hand. No hard
// price is shown — pricing isn't finalized, so this captures interest only.
function PremiumIntent({ defaultEmail }: { defaultEmail: string }) {
  const { t } = useT();
  const [phase, setPhase] = useState<'idle' | 'form' | 'done'>('idle');
  const [email, setEmail] = useState(defaultEmail);
  const [submitting, setSubmitting] = useState(false);

  if (phase === 'done') {
    return (
      <span className="px-2.5 py-1 rounded-full text-[11px] font-medium bg-emerald-50 text-emerald-700 shrink-0">
        {t('account.intentDone')}
      </span>
    );
  }

  if (phase === 'idle') {
    return (
      <button
        type="button"
        onClick={() => {
          void track('intent_clicked', { source: 'account' });
          setPhase('form');
        }}
        className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-[13px] font-medium text-white bg-indigo-600 hover:bg-indigo-700 transition-colors shrink-0"
      >
        {t('account.intentCta')}
      </button>
    );
  }

  return (
    <form
      onSubmit={async (e) => {
        e.preventDefault();
        if (submitting) return;
        setSubmitting(true);
        const ok = await joinWaitlist(email.trim() || null, { source: 'account' });
        setSubmitting(false);
        if (ok) setPhase('done');
      }}
      className="flex items-center gap-2 shrink-0"
    >
      <input
        type="email"
        required
        value={email}
        onChange={(e) => setEmail(e.target.value)}
        placeholder={t('account.intentEmailPlaceholder')}
        aria-label={t('account.intentEmailPlaceholder')}
        className="w-40 sm:w-48 px-2.5 py-1.5 rounded-lg border border-gray-200 text-[13px] focus:outline-none focus:ring-2 focus:ring-indigo-200"
      />
      <button
        type="submit"
        disabled={submitting}
        className="px-3 py-1.5 rounded-full text-[13px] font-medium text-white bg-indigo-600 hover:bg-indigo-700 disabled:opacity-60 transition-colors"
      >
        {t('account.intentSubmit')}
      </button>
    </form>
  );
}

function PlanRow() {
  const { t } = useT();
  return (
    <div className="flex items-center justify-between gap-4 pb-4 border-b border-gray-100">
      <div>
        <p className="text-sm font-semibold text-gray-900">{t('account.freePlan')}</p>
        <p className="text-[13px] text-gray-500 mt-0.5">{t('account.freePlanDesc')}</p>
      </div>
      <span className="px-2.5 py-1 rounded-full text-[11px] font-medium shrink-0 bg-gray-100 text-gray-600">
        {t('account.currentBadge')}
      </span>
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
