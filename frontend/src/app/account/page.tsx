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
import { track, trackOnce } from '@/lib/analytics';
import { useAuthModal } from '@/lib/auth-modal-context';
import { formatPrice, PACKAGES, paymentsEnabled, payQrEnabled, type PricingPackage } from '@/lib/pricing';
import {
  claimOrderPaid,
  createOrder,
  getAuthState,
  getFavorites,
  getInteractionsFull,
  getMyOrders,
  joinWaitlist,
  loadProfile,
  onAuthChange,
  type AuthState,
  type OrderRow,
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
  const [orders, setOrders] = useState<OrderRow[] | null>(null);
  const payments = paymentsEnabled();
  // Concierge QR (scan-to-pay, hand-fulfilled) runs the WTP test without the
  // package/order flow; only shown when the order flow itself is off.
  const payQr = !payments && payQrEnabled();

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
    if (payments) {
      getMyOrders()
        .then((rows) => { if (!cancelled) setOrders(rows); })
        .catch(() => {});
    }
    const unsub = onAuthChange((s) => { if (!cancelled) setAuth(s); });
    return () => { cancelled = true; unsub(); };
  }, [payments]);

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

          {/* ── Plan (flag off = waitlist placeholder; flag on = manual-payment order flow) ── */}
          <Card>
            <h2 className="text-lg font-bold text-gray-900 mb-5">{t('account.planTitle')}</h2>
            <PlanRow orders={payments ? orders : null} />
            <div className="flex items-center justify-between gap-4 pt-4">
              <div>
                <p className="text-sm font-semibold text-gray-900">{t('account.premiumTitle')}</p>
                <p className="text-[13px] text-gray-500 mt-0.5">{t('account.premiumDesc')}</p>
              </div>
              {!payments && !payQr && <PremiumIntent defaultEmail={email} />}
            </div>
            {payments && <OrderFlow orders={orders} />}
            {payQr && <ConciergePayPanel defaultEmail={email} />}
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

// Concierge QR panel (NEXT_PUBLIC_PAY_QR): the willingness-to-pay test with no
// pricing and no order rows — just the WeChat/Alipay codes and a hand-fulfilled
// follow-up. Reuses PremiumIntent for the lead/contact capture. Prices aren't
// shown (they're deferred), so the exact amount is settled in the follow-up.
function ConciergePayPanel({ defaultEmail }: { defaultEmail: string }) {
  const { t } = useT();
  useEffect(() => { void trackOnce('pay_qr_view', { source: 'account' }); }, []);
  return (
    <div className="mt-4 rounded-2xl border border-indigo-100 bg-indigo-50/30 p-4">
      <p className="text-sm font-semibold text-gray-900">{t('account.payQrTitle')}</p>
      <p className="text-[13px] text-gray-600 mt-1">{t('account.payQrDesc')}</p>
      <div className="flex flex-wrap gap-4 mt-4">
        <figure className="text-center">
          <img
            src="/pay/wechat.png"
            alt={t('account.payWechat')}
            className="w-36 h-36 rounded-xl border border-gray-200 bg-white"
          />
          <figcaption className="text-[12px] text-gray-500 mt-1">{t('account.payWechat')}</figcaption>
        </figure>
        <figure className="text-center">
          <img
            src="/pay/alipay.png"
            alt={t('account.payAlipay')}
            className="w-36 h-36 rounded-xl border border-gray-200 bg-white"
          />
          <figcaption className="text-[12px] text-gray-500 mt-1">{t('account.payAlipay')}</figcaption>
        </figure>
      </div>
      <p className="text-[12px] text-gray-500 mt-3">{t('account.payQrContact')}</p>
      <div className="mt-3">
        <PremiumIntent defaultEmail={defaultEmail} />
      </div>
    </div>
  );
}

function packageLabel(t: ReturnType<typeof useT>['t'], pkgId: string): string {
  if (pkgId === 'single_email') return t('account.packageSingleEmail');
  if (pkgId === 'full_package') return t('account.packageFullPackage');
  return pkgId;
}

// Current-plan row: a confirmed paid order shows its package as the active
// plan; otherwise the free tier (also whenever payments are flagged off —
// callers pass orders=null then, so the markup is byte-identical to before).
function PlanRow({ orders }: { orders: OrderRow[] | null }) {
  const { t } = useT();
  const paid = orders?.find((o) => o.status === 'paid') ?? null;
  return (
    <div className="flex items-center justify-between gap-4 pb-4 border-b border-gray-100">
      <div>
        <p className="text-sm font-semibold text-gray-900">
          {paid ? packageLabel(t, paid.package) : t('account.freePlan')}
        </p>
        <p className="text-[13px] text-gray-500 mt-0.5">
          {paid ? t('account.paidPlanDesc') : t('account.freePlanDesc')}
        </p>
      </div>
      <span
        className={`px-2.5 py-1 rounded-full text-[11px] font-medium shrink-0 ${
          paid ? 'bg-emerald-50 text-emerald-700' : 'bg-gray-100 text-gray-600'
        }`}
      >
        {t('account.currentBadge')}
      </span>
    </div>
  );
}

// Manual-payment order flow (NEXT_PUBLIC_PAYMENTS only): pick a package →
// insert a pending order under RLS → show static QR codes → the user claims
// payment → awaiting operator confirmation. No payment aggregator involved.
function OrderFlow({ orders }: { orders: OrderRow[] | null }) {
  const { t } = useT();
  const [localOrder, setLocalOrder] = useState<OrderRow | null>(null);
  const [localPhase, setLocalPhase] = useState<'pay' | 'claimed'>('pay');
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);

  // Resume an in-flight order after a reload (derived, no effect): a
  // claimed-but-unconfirmed order shows the waiting state, an unclaimed
  // pending one re-opens the QR step. Local actions take precedence.
  const resumed =
    orders?.find((o) => o.status === 'awaiting_confirm')
    ?? orders?.find((o) => o.status === 'pending')
    ?? null;
  const order = localOrder ?? resumed;
  const phase: 'choose' | 'pay' | 'claimed' = localOrder
    ? localPhase
    : resumed
      ? (resumed.status === 'awaiting_confirm' ? 'claimed' : 'pay')
      : 'choose';

  const choose = async (pkg: PricingPackage) => {
    if (busy) return;
    setBusy(true);
    setFailed(false);
    void track('order_created', { source: 'account', package: pkg.id });
    const row = await createOrder(pkg);
    setBusy(false);
    if (!row) { setFailed(true); return; }
    setLocalOrder(row);
    setLocalPhase('pay');
  };

  const claim = async () => {
    if (busy || !order) return;
    setBusy(true);
    setFailed(false);
    const ok = await claimOrderPaid(order.id);
    setBusy(false);
    if (!ok) { setFailed(true); return; }
    setLocalOrder(order);
    setLocalPhase('claimed');
  };

  if (phase === 'claimed' && order) {
    return (
      <div className="mt-4 rounded-2xl bg-emerald-50 border border-emerald-100 p-4">
        <p className="text-sm font-semibold text-emerald-800">
          {t('account.orderAwaitingConfirm')}
        </p>
        <p className="text-[12px] text-emerald-700 mt-1 font-mono break-all">
          {t('account.orderId')}: {order.id}
        </p>
      </div>
    );
  }

  if (phase === 'pay' && order) {
    return (
      <div className="mt-4 rounded-2xl border border-gray-100 p-4">
        <p className="text-sm font-semibold text-gray-900">
          {packageLabel(t, order.package)} · {formatPrice(order.amount_cents)}
        </p>
        <p className="text-[13px] text-gray-500 mt-1">{t('account.payHint')}</p>
        <div className="flex flex-wrap gap-4 mt-4">
          <figure className="text-center">
            <img
              src="/pay/wechat.png"
              alt={t('account.payWechat')}
              className="w-36 h-36 rounded-xl border border-gray-200"
            />
            <figcaption className="text-[12px] text-gray-500 mt-1">
              {t('account.payWechat')}
            </figcaption>
          </figure>
          <figure className="text-center">
            <img
              src="/pay/alipay.png"
              alt={t('account.payAlipay')}
              className="w-36 h-36 rounded-xl border border-gray-200"
            />
            <figcaption className="text-[12px] text-gray-500 mt-1">
              {t('account.payAlipay')}
            </figcaption>
          </figure>
        </div>
        <p className="text-[11px] text-gray-400 mt-3 font-mono break-all">
          {t('account.orderId')}: {order.id}
        </p>
        <button
          type="button"
          onClick={claim}
          disabled={busy}
          className="mt-3 px-4 py-2 rounded-xl text-sm font-medium text-white bg-indigo-600 hover:bg-indigo-700 disabled:opacity-60 transition-colors"
        >
          {t('account.paidClaimCta')}
        </button>
        {failed && <p className="text-[12px] text-red-600 mt-2">{t('account.orderError')}</p>}
      </div>
    );
  }

  return (
    <div className="mt-4">
      <p className="text-[13px] font-medium text-gray-700 mb-2">{t('account.choosePackage')}</p>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        {PACKAGES.map((pkg) => (
          <button
            key={pkg.id}
            type="button"
            onClick={() => choose(pkg)}
            disabled={busy}
            className="rounded-2xl border border-gray-200 p-4 text-left hover:border-indigo-300 hover:bg-indigo-50/30 disabled:opacity-60 transition-colors"
          >
            <p className="text-sm font-semibold text-gray-800">{packageLabel(t, pkg.id)}</p>
            <p className="text-lg font-bold text-indigo-600 mt-1">{formatPrice(pkg.amountCents)}</p>
          </button>
        ))}
      </div>
      {failed && <p className="text-[12px] text-red-600 mt-2">{t('account.orderError')}</p>}
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
