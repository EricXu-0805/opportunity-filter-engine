'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import dynamic from 'next/dynamic';
import {
  ArrowLeft,
  Building2,
  MapPin,
  Calendar,
  Clock,
  DollarSign,
  Globe,
  Star,
  ExternalLink,
  Mail,
  Share2,
  Check,
  GraduationCap,
  Briefcase,
  Users,
  AlertTriangle,
  StickyNote,
  BellRing,
  Sparkles,
} from 'lucide-react';
import {
  getFavorites,
  toggleFavorite,
  trackInteraction,
  removeInteraction,
  getInteractionDetail,
  updateInteractionDetails,
} from '@/lib/supabase';
import type { InteractionType, InteractionRecord } from '@/lib/supabase';
import type { Opportunity, ProfileData } from '@/lib/types';
import type { SimilarOpportunity } from '@/lib/api-server';
import { getDeadlineUrgency, daysUntil } from '@/lib/match-utils';
import { useT } from '@/i18n/client';

const ColdEmailModal = dynamic(() => import('@/components/ColdEmailModal'), { ssr: false });
const OpportunityChatbot = dynamic(() => import('@/components/OpportunityChatbot'), { ssr: false });

const INTERACTION_PILL: Record<InteractionType, string> = {
  applied: 'bg-blue-50 text-blue-700 border-blue-200',
  replied: 'bg-emerald-50 text-emerald-700 border-emerald-200',
  interviewing: 'bg-violet-50 text-violet-700 border-violet-200',
  rejected: 'bg-gray-100 text-gray-500 border-gray-200',
  dismissed: 'bg-gray-100 text-gray-400 border-gray-200',
};
const INTERACTION_OPTIONS: InteractionType[] = ['applied', 'replied', 'interviewing', 'rejected', 'dismissed'];

export default function OpportunityDetail({
  opp,
  similar = [],
}: {
  opp: Opportunity;
  similar?: SimilarOpportunity[];
}) {
  const { t } = useT();
  const [isFavorited, setIsFavorited] = useState(false);
  const [interactionDetail, setInteractionDetail] = useState<InteractionRecord | null>(null);
  const [profile, setProfile] = useState<ProfileData | null>(null);
  const [emailModalOpen, setEmailModalOpen] = useState(false);
  const [shareCopied, setShareCopied] = useState(false);
  const [chatDrawerOpen, setChatDrawerOpen] = useState(false);

  const interaction = interactionDetail?.type;

  useEffect(() => {
    getFavorites().then(set => setIsFavorited(set.has(opp.id))).catch(() => {});
    getInteractionDetail(opp.id).then(setInteractionDetail).catch(() => {});
    try {
      const raw = localStorage.getItem('ofe_profile');
      if (raw) setProfile(JSON.parse(raw) as ProfileData);
    } catch { /* malformed */ }
  }, [opp.id]);

  const applyUrl = opp.application?.application_url || opp.url || opp.source_url;

  const handleStar = useCallback(async () => {
    const wasFav = isFavorited;
    setIsFavorited(!wasFav);
    try {
      await toggleFavorite(opp.id, wasFav);
    } catch {
      setIsFavorited(wasFav);
    }
  }, [opp.id, isFavorited]);

  const handleTrack = useCallback(async (type: InteractionType) => {
    const prev = interaction;
    if (prev === type) {
      setInteractionDetail(null);
      await removeInteraction(opp.id).catch(() => {});
    } else {
      setInteractionDetail(d => ({
        ...(d ?? {}),
        type,
        last_contacted_at: new Date().toISOString(),
      }));
      await trackInteraction(opp.id, type).catch(() => {});
    }
  }, [opp.id, interaction]);

  const saveDetails = useCallback(
    async (patch: { notes?: string | null; remind_at?: string | null }) => {
      if (!interaction) {
        await trackInteraction(opp.id, 'applied').catch(() => {});
      }
      setInteractionDetail((prev) => {
        const base: InteractionRecord = prev ?? { type: 'applied' };
        return {
          ...base,
          notes: patch.notes === null ? undefined : patch.notes ?? base.notes,
          remind_at: patch.remind_at === null ? undefined : patch.remind_at ?? base.remind_at,
        };
      });
      await updateInteractionDetails(opp.id, patch).catch(() => {});
    },
    [opp.id, interaction],
  );

  const handleShare = useCallback(async () => {
    const url = typeof window !== 'undefined' ? window.location.href : '';
    try {
      if (navigator.share) {
        await navigator.share({ title: opp.title, url });
      } else {
        await navigator.clipboard.writeText(url);
        setShareCopied(true);
        setTimeout(() => setShareCopied(false), 2000);
      }
    } catch {
      /* user canceled */
    }
  }, [opp.title]);

  const urgency = getDeadlineUrgency(opp.deadline);
  const days = daysUntil(opp.deadline);

  const deadlineBadge = useMemo(() => {
    if (!opp.deadline || days === null) return null;
    if (urgency === 'passed') {
      return <Badge tone="gray" icon={<AlertTriangle className="w-3 h-3" />}>{t('badges.pastDeadline')}</Badge>;
    }
    if (urgency === 'urgent') {
      return <Badge tone="red" icon={<Clock className="w-3 h-3" />}>{days === 1 ? t('deadline.urgentSingle') : t('deadline.urgent', { days })}</Badge>;
    }
    if (urgency === 'soon') {
      return <Badge tone="amber" icon={<Clock className="w-3 h-3" />}>{t('deadline.soon', { days })}</Badge>;
    }
    return null;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [opp.deadline, urgency, days]);

  const description = opp.description_raw || opp.description_clean || '';

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6 sm:py-10">
      <Link
        href="/results"
        className="inline-flex items-center gap-2 text-sm text-gray-500 hover:text-gray-700 mb-6 transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 rounded"
      >
        <ArrowLeft className="w-4 h-4" aria-hidden="true" />
        {t('detail.backToMatches')}
      </Link>

      <div className="flex flex-col lg:flex-row lg:gap-6 lg:items-start">
      <main className="flex-1 min-w-0 lg:max-w-3xl">

      <div className="bg-white rounded-2xl shadow-[0_1px_8px_rgba(0,0,0,0.05)] overflow-hidden mb-6">
        <div className="p-5 sm:p-8">
          <div className="flex items-start justify-between gap-4 mb-4">
            <div className="flex-1 min-w-0">
              <div className="flex flex-wrap items-center gap-2 mb-3">
                <Badge tone="blue">{formatType(opp.opportunity_type)}</Badge>
                {opp.paid === 'yes' && <Badge tone="emerald" icon={<DollarSign className="w-3 h-3" />}>{t('badges.paid')}</Badge>}
                {opp.paid === 'stipend' && <Badge tone="emerald">{t('badges.stipend')}</Badge>}
                {opp.paid === 'no' && <Badge tone="gray">{t('badges.unpaid')}</Badge>}
                {opp.on_campus && <Badge tone="gray">{t('badges.onCampus')}</Badge>}
                {opp.remote_option === 'yes' && <Badge tone="gray">{t('badges.remoteOk')}</Badge>}
                {opp.eligibility?.international_friendly === 'yes' && (
                  <Badge tone="indigo" icon={<Globe className="w-3 h-3" />}>{t('badges.internationalFriendly')}</Badge>
                )}
                {deadlineBadge}
              </div>
              <h1 className="text-2xl sm:text-3xl font-bold text-gray-900 leading-tight tracking-tight">
                {opp.title}
              </h1>
              <div className="flex flex-wrap items-center gap-x-4 gap-y-1 mt-3 text-[13px] sm:text-sm text-gray-500">
                {opp.organization && (
                  <span className="inline-flex items-center gap-1.5">
                    <Building2 className="w-3.5 h-3.5" aria-hidden="true" />
                    {opp.organization}
                  </span>
                )}
                {opp.department && <span>· {opp.department}</span>}
                {opp.location && (
                  <span className="inline-flex items-center gap-1.5">
                    <MapPin className="w-3.5 h-3.5" aria-hidden="true" />
                    {opp.location}
                  </span>
                )}
              </div>
            </div>
            <button
              type="button"
              onClick={handleStar}
              className="shrink-0 p-2 -mr-2 rounded-xl hover:bg-amber-50 transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-amber-500"
              aria-label={isFavorited ? t('detail.favoriteRemove') : t('detail.favoriteAdd')}
              aria-pressed={isFavorited}
            >
              <Star className={`w-6 h-6 ${isFavorited ? 'fill-amber-400 text-amber-400' : 'text-gray-300'}`} />
            </button>
          </div>

          <div className="flex flex-wrap gap-2 mt-4">
            {applyUrl && (
              <a
                href={applyUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-2 px-4 py-2.5 rounded-xl bg-blue-600 text-white text-[14px] font-semibold hover:bg-blue-700 transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
              >
                <ExternalLink className="w-4 h-4" aria-hidden="true" />
                {t('detail.apply')}
              </a>
            )}
            {profile && (
              <button
                type="button"
                onClick={() => setEmailModalOpen(true)}
                className="inline-flex items-center gap-2 px-4 py-2.5 rounded-xl bg-white border border-gray-200 text-gray-700 text-[14px] font-medium hover:bg-gray-50 transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
              >
                <Mail className="w-4 h-4" aria-hidden="true" />
                {t('detail.draftEmail')}
              </button>
            )}
            <button
              type="button"
              onClick={handleShare}
              className="inline-flex items-center gap-2 px-4 py-2.5 rounded-xl bg-white border border-gray-200 text-gray-700 text-[14px] font-medium hover:bg-gray-50 transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
            >
              {shareCopied ? <Check className="w-4 h-4 text-emerald-500" aria-hidden="true" /> : <Share2 className="w-4 h-4" aria-hidden="true" />}
              {shareCopied ? t('detail.shareCopied') : t('detail.share')}
            </button>
          </div>
        </div>

        <div className="border-t border-gray-100 px-5 sm:px-8 py-4 bg-gray-50/50">
          <div className="flex flex-wrap items-center gap-2" role="group" aria-label={t('detail.trackAriaLabel')}>
            <span className="text-[12px] text-gray-500 mr-1">{t('detail.track')}</span>
            {INTERACTION_OPTIONS.map(type => {
              const active = interaction === type;
              return (
                <button
                  key={type}
                  type="button"
                  aria-pressed={active}
                  onClick={() => handleTrack(type)}
                  className={`px-2.5 py-1 rounded-lg text-[11px] font-medium border transition-all focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 ${
                    active ? INTERACTION_PILL[type] : 'bg-white border-gray-200 text-gray-400 hover:border-gray-300'
                  }`}
                >
                  {t(`detail.interactions.${type}`)}
                </button>
              );
            })}
          </div>
        </div>

        <TrackerPanel
          detail={interactionDetail}
          onSave={saveDetails}
          t={t}
        />
      </div>

      {description && (
        <Section title={t('detail.sections.description')}>
          <p className="text-[14px] sm:text-[15px] text-gray-700 leading-relaxed whitespace-pre-wrap">
            {description}
          </p>
        </Section>
      )}

      <Section title={t('detail.sections.atGlance')}>
        <dl className="grid grid-cols-1 sm:grid-cols-2 gap-y-4 gap-x-6">
          {opp.deadline && (
            <DetailRow
              icon={<Calendar />}
              label={t('detail.fields.deadline')}
              value={opp.deadline_is_estimate
                ? `${opp.deadline} ${t('detail.fields.deadlineEstimate')}`
                : opp.deadline}
            />
          )}
          {!opp.deadline && opp.is_rolling && (
            <DetailRow
              icon={<Calendar />}
              label={t('detail.fields.deadline')}
              value={t('detail.fields.rollingBasis')}
            />
          )}
          {opp.start_date && (
            <DetailRow icon={<Calendar />} label={t('detail.fields.startDate')} value={opp.start_date} />
          )}
          {opp.duration && (
            <DetailRow icon={<Clock />} label={t('detail.fields.duration')} value={opp.duration} />
          )}
          {opp.compensation_details && (
            <DetailRow icon={<DollarSign />} label={t('detail.fields.compensation')} value={opp.compensation_details} />
          )}
          {opp.posted_date && (
            <DetailRow icon={<Calendar />} label={t('detail.fields.posted')} value={opp.posted_date} />
          )}
          {opp.lab_or_program && (
            <DetailRow icon={<Briefcase />} label={t('detail.fields.lab')} value={opp.lab_or_program} />
          )}
          {opp.pi_name && (
            <DetailRow icon={<Users />} label={t('detail.fields.pi')} value={opp.pi_name} />
          )}
        </dl>
      </Section>

      {opp.eligibility && (
        <Section title={t('detail.sections.eligibility')}>
          <dl className="grid grid-cols-1 sm:grid-cols-2 gap-y-4 gap-x-6">
            {opp.eligibility.preferred_year?.length > 0 && (
              <DetailRow
                icon={<GraduationCap />}
                label={t('detail.fields.preferredYear')}
                value={opp.eligibility.preferred_year.join(', ')}
              />
            )}
            {opp.eligibility.majors?.length > 0 && (
              <DetailRow
                icon={<GraduationCap />}
                label={t('detail.fields.majors')}
                value={opp.eligibility.majors.join(', ')}
              />
            )}
            {opp.eligibility.skills_required?.length > 0 && (
              <DetailRow
                icon={<Briefcase />}
                label={t('detail.fields.skills')}
                value={opp.eligibility.skills_required.join(', ')}
              />
            )}
            <DetailRow
              icon={<Globe />}
              label={t('detail.fields.international')}
              value={friendlyLabel(opp.eligibility.international_friendly, t)}
            />
            {opp.eligibility.citizenship_required && (
              <DetailRow
                icon={<AlertTriangle />}
                label={t('detail.fields.citizenship')}
                value={t('detail.fields.citizenshipNote')}
                warn
              />
            )}
          </dl>
        </Section>
      )}

      {opp.application && (
        <Section title={t('detail.sections.application')}>
          <dl className="grid grid-cols-1 sm:grid-cols-2 gap-y-4 gap-x-6">
            {opp.application.contact_method && (
              <DetailRow icon={<Mail />} label={t('detail.fields.contactMethod')} value={opp.application.contact_method} />
            )}
            {opp.application.requires_resume && (
              <DetailRow icon={<Briefcase />} label={t('detail.fields.resume')} value={friendlyLabel(opp.application.requires_resume, t)} />
            )}
            {opp.application.requires_cover_letter && (
              <DetailRow icon={<Briefcase />} label={t('detail.fields.coverLetter')} value={friendlyLabel(opp.application.requires_cover_letter, t)} />
            )}
            {opp.application.requires_recommendation && (
              <DetailRow icon={<Users />} label={t('detail.fields.recommendation')} value={friendlyLabel(opp.application.requires_recommendation, t)} />
            )}
            {opp.application.application_effort && (
              <DetailRow icon={<Clock />} label={t('detail.fields.effort')} value={opp.application.application_effort} />
            )}
          </dl>
        </Section>
      )}

      {opp.keywords?.length > 0 && (
        <Section title={t('detail.sections.keywords')}>
          <div className="flex flex-wrap gap-1.5">
            {opp.keywords.map(k => (
              <span key={k} className="px-2.5 py-1 rounded-full text-[11px] font-medium bg-gray-100 text-gray-600">
                {k}
              </span>
            ))}
          </div>
        </Section>
      )}

      {similar.length > 0 && (
        <section className="mt-8 mb-4" aria-labelledby="similar-heading">
          <h2 id="similar-heading" className="text-[14px] font-semibold text-gray-900 mb-4 tracking-tight">
            {t('detail.sections.similar')}
          </h2>
          <ul className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            {similar.map(s => (
              <li key={s.id}>
                <Link
                  href={`/opportunities/${encodeURIComponent(s.id)}`}
                  className="group block bg-white rounded-2xl shadow-[0_1px_8px_rgba(0,0,0,0.05)] hover:shadow-[0_4px_20px_rgba(0,0,0,0.08)] transition-shadow p-4 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
                >
                  <div className="flex items-start gap-2 mb-2">
                    <Badge tone="blue">{formatType(s.opportunity_type)}</Badge>
                    {s.paid === 'yes' && <Badge tone="emerald">{t('badges.paid')}</Badge>}
                    {s.paid === 'stipend' && <Badge tone="emerald">{t('badges.stipend')}</Badge>}
                  </div>
                  <h3 className="text-[14px] font-semibold text-gray-900 leading-snug line-clamp-2 group-hover:text-blue-600 transition-colors">
                    {s.title}
                  </h3>
                  {s.organization && (
                    <p className="text-[12px] text-gray-400 mt-1.5 truncate">
                      <Building2 className="w-3 h-3 inline mr-1" aria-hidden="true" />
                      {s.organization}
                    </p>
                  )}
                </Link>
              </li>
            ))}
          </ul>
        </section>
      )}

      <div className="mt-8 pt-6 border-t border-gray-100 text-[11px] text-gray-400 space-y-1">
        {opp.source && <p>{t('detail.source', { source: opp.source })}</p>}
        {(opp.metadata as { last_verified?: string } | undefined)?.last_verified && (
          <p>{t('detail.lastVerified', { date: (opp.metadata as { last_verified?: string }).last_verified ?? '' })}</p>
        )}
      </div>

      </main>

      <aside className="hidden lg:block lg:w-[360px] xl:w-[400px] lg:sticky lg:top-6 lg:self-start lg:shrink-0">
        <div className="bg-white rounded-2xl shadow-[0_1px_8px_rgba(0,0,0,0.05)] border border-gray-100 overflow-hidden h-[calc(100vh-6rem)] max-h-[760px]">
          <OpportunityChatbot opportunity={opp} profile={profile} />
        </div>
      </aside>
      </div>

      {!chatDrawerOpen && (
        <button
          type="button"
          onClick={() => setChatDrawerOpen(true)}
          className="lg:hidden fixed bottom-6 right-6 z-30 inline-flex items-center justify-center w-14 h-14 rounded-full bg-indigo-600 text-white shadow-[0_4px_20px_rgba(79,70,229,0.4)] hover:bg-indigo-700 active:scale-95 transition-all"
          aria-label={t('chatbot.openAria')}
        >
          <Sparkles className="w-6 h-6" aria-hidden="true" />
        </button>
      )}

      {chatDrawerOpen && (
        <div className="lg:hidden fixed inset-0 z-50" role="dialog" aria-modal="true">
          <div
            className="absolute inset-0 bg-gray-900/50 backdrop-blur-sm"
            onClick={() => setChatDrawerOpen(false)}
            aria-hidden="true"
          />
          <div className="absolute bottom-0 left-0 right-0 bg-white rounded-t-2xl shadow-2xl flex flex-col max-h-[88vh] h-[88vh] animate-in">
            <OpportunityChatbot
              opportunity={opp}
              profile={profile}
              onClose={() => setChatDrawerOpen(false)}
            />
          </div>
        </div>
      )}

      {profile && (
        <ColdEmailModal
          isOpen={emailModalOpen}
          onClose={() => setEmailModalOpen(false)}
          profile={profile}
          opportunityId={opp.id}
          opportunityTitle={opp.title}
        />
      )}
    </div>
  );
}

function TrackerPanel({
  detail,
  onSave,
  t,
}: {
  detail: InteractionRecord | null;
  onSave: (patch: { notes?: string | null; remind_at?: string | null }) => Promise<void>;
  t: (path: string, vars?: Record<string, string | number>) => string;
}) {
  const [open, setOpen] = useState(!!(detail?.notes || detail?.remind_at));
  const [notes, setNotes] = useState(detail?.notes ?? '');
  const [remindAt, setRemindAt] = useState(detail?.remind_at ?? '');
  const [saveStatus, setSaveStatus] = useState<'idle' | 'saving' | 'saved'>('idle');

  useEffect(() => {
    setNotes(detail?.notes ?? '');
    setRemindAt(detail?.remind_at ?? '');
  }, [detail?.notes, detail?.remind_at]);

  useEffect(() => {
    if (notes === (detail?.notes ?? '') && remindAt === (detail?.remind_at ?? '')) return;
    setSaveStatus('saving');
    const timer = setTimeout(async () => {
      await onSave({
        notes: notes.trim() ? notes.trim().slice(0, 2000) : null,
        remind_at: remindAt || null,
      });
      setSaveStatus('saved');
      setTimeout(() => setSaveStatus('idle'), 1500);
    }, 600);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [notes, remindAt]);

  const hasContent = !!(notes || remindAt);

  return (
    <div className="border-t border-gray-100 px-5 sm:px-8 py-3">
      <button
        type="button"
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center gap-2 text-[12px] text-gray-500 hover:text-gray-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 rounded"
        aria-expanded={open}
      >
        <StickyNote className="w-3.5 h-3.5" aria-hidden="true" />
        <span className="font-medium">
          {hasContent ? t('detail.tracker.openButton') : t('detail.tracker.addButton')}
        </span>
        {hasContent && !open && (
          <span className="ml-auto text-[11px] text-gray-400">
            {notes && <span>{notes.length > 40 ? notes.slice(0, 40) + '…' : notes}</span>}
            {remindAt && (
              <span className="ml-2 inline-flex items-center gap-1 text-amber-600">
                <BellRing className="w-3 h-3" aria-hidden="true" />
                {remindAt}
              </span>
            )}
          </span>
        )}
        <span className="ml-auto text-[11px] text-gray-400" aria-live="polite">
          {saveStatus === 'saving' && t('common.saving')}
          {saveStatus === 'saved' && t('common.saved')}
        </span>
      </button>
      {open && (
        <div className="mt-3 space-y-3 animate-in">
          {detail?.type && detail?.updated_at && (
            <StatusTimeline type={detail.type} updatedAt={detail.updated_at} t={t} />
          )}
          <label className="block">
            <span className="sr-only">{t('detail.sections.description')}</span>
            <textarea
              value={notes}
              onChange={e => setNotes(e.target.value)}
              maxLength={2000}
              rows={3}
              placeholder={t('detail.tracker.notesPlaceholder')}
              className="w-full px-3 py-2 text-[13px] bg-white border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500/40 focus:border-blue-400 resize-y"
            />
            <div className="flex justify-between mt-1 text-[10px] text-gray-400">
              <span className="italic">{t('detail.tracker.markdownHint')}</span>
              <span>{notes.length} / 2000</span>
            </div>
          </label>
          <label className="flex items-center gap-2 text-[12px] text-gray-600">
            <BellRing className="w-3.5 h-3.5 text-amber-500" aria-hidden="true" />
            <span className="font-medium">{t('detail.tracker.remindLabel')}</span>
            <input
              type="date"
              value={remindAt}
              onChange={e => setRemindAt(e.target.value)}
              className="px-2 py-1 text-[12px] bg-white border border-gray-200 rounded focus:outline-none focus:ring-2 focus:ring-blue-500/40"
            />
            {remindAt && (
              <button
                type="button"
                onClick={() => setRemindAt('')}
                className="text-[11px] text-gray-400 hover:text-red-500 transition-colors"
              >
                {t('common.clear')}
              </button>
            )}
          </label>
        </div>
      )}
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="bg-white rounded-2xl shadow-[0_1px_8px_rgba(0,0,0,0.05)] p-5 sm:p-7 mb-4">
      <h2 className="text-[14px] font-semibold text-gray-900 mb-4 tracking-tight">{title}</h2>
      {children}
    </section>
  );
}

function DetailRow({
  icon,
  label,
  value,
  warn,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  warn?: boolean;
}) {
  return (
    <div className="flex items-start gap-3">
      <span className={`shrink-0 mt-0.5 text-gray-400 ${warn ? 'text-amber-500' : ''}`} aria-hidden="true">
        {icon}
      </span>
      <div className="min-w-0">
        <dt className="text-[11px] text-gray-400 uppercase tracking-wider mb-0.5">{label}</dt>
        <dd className={`text-[14px] break-words ${warn ? 'text-amber-700' : 'text-gray-800'}`}>{value}</dd>
      </div>
    </div>
  );
}

function Badge({
  tone,
  icon,
  children,
}: {
  tone: 'blue' | 'emerald' | 'amber' | 'red' | 'gray' | 'indigo';
  icon?: React.ReactNode;
  children: React.ReactNode;
}) {
  const cls = {
    blue: 'bg-blue-50 text-blue-700',
    emerald: 'bg-emerald-50 text-emerald-700',
    amber: 'bg-amber-50 text-amber-700',
    red: 'bg-red-50 text-red-700',
    gray: 'bg-gray-100 text-gray-600',
    indigo: 'bg-indigo-50 text-indigo-700',
  }[tone];
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium ${cls}`}>
      {icon}
      {children}
    </span>
  );
}

function formatType(t: string): string {
  return t.replace(/_/g, ' ').replace(/\b\w/g, m => m.toUpperCase());
}

function formatRelativeAge(iso: string): string {
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return '';
  const diffSec = Math.max(0, Math.floor((Date.now() - then) / 1000));
  if (diffSec < 60) return 'just now';
  if (diffSec < 3600) return `${Math.floor(diffSec / 60)}m ago`;
  if (diffSec < 86400) return `${Math.floor(diffSec / 3600)}h ago`;
  return `${Math.floor(diffSec / 86400)}d ago`;
}

function StatusTimeline({
  type,
  updatedAt,
  t,
}: {
  type: 'applied' | 'replied' | 'rejected' | 'interviewing' | 'dismissed';
  updatedAt: string;
  t: (path: string) => string;
}) {
  const statusColors: Record<string, string> = {
    applied: 'bg-blue-50 text-blue-700',
    replied: 'bg-violet-50 text-violet-700',
    interviewing: 'bg-amber-50 text-amber-700',
    rejected: 'bg-gray-100 text-gray-600',
    dismissed: 'bg-gray-50 text-gray-400',
  };
  const cls = statusColors[type] ?? 'bg-gray-50 text-gray-500';
  const label = t(`detail.tracker.statusLabels.${type}`);
  return (
    <div className="flex items-center gap-2 text-[11px]">
      <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full font-medium ${cls}`}>
        {label === `detail.tracker.statusLabels.${type}` ? formatType(type) : label}
      </span>
      <span className="text-gray-400">· {formatRelativeAge(updatedAt)}</span>
    </div>
  );
}

function friendlyLabel(v: string, t: (p: string) => string): string {
  if (v === 'yes') return t('common.yes');
  if (v === 'no') return t('common.no');
  if (v === 'unknown') return t('common.notSpecified');
  return v;
}
