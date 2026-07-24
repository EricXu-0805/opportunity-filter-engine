'use client';

import { useEffect, useState } from 'react';
import { ArrowLeft, GraduationCap, Loader2 } from 'lucide-react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';

import { getRoadmap, type RoadmapResult } from '@/lib/api';
import { STORAGE_KEYS } from '@/lib/storage-keys';
import { getFavorites } from '@/lib/supabase';
import { useLocalStorageJSON } from '@/lib/use-local-storage-json';
import type { ProfileData } from '@/lib/types';
import { useT } from '@/i18n/client';

function CenteredCard({ title, body, cta, href }: { title: string; body: string; cta: string; href: string }) {
  return (
    <div className="rounded-2xl border border-dashed border-gray-200 px-6 py-16 text-center">
      <p className="text-sm font-medium text-gray-600">{title}</p>
      <p className="mt-1 text-[13px] text-gray-400">{body}</p>
      <Link
        href={href}
        className="mt-5 inline-flex items-center rounded-xl bg-gray-900 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-gray-800"
      >
        {cta}
      </Link>
    </div>
  );
}

function CourseSuggestions({ skill }: { skill: RoadmapResult['skills'][number] }) {
  const { t } = useT();
  // Course codes are UIUC catalog entries — never suggest them to students at
  // another school as if they were local courses.
  if (skill.course_catalog !== 'uiuc' || skill.courses.length === 0) return null;
  return (
    <div className="mt-2 flex flex-wrap gap-1.5">
      <span className="text-[11px] text-gray-400">{t('roadmap.uiucCoursesLabel')}</span>
      {skill.courses.map((c) => (
        <span key={c} className="rounded-md bg-teal-50 px-1.5 py-0.5 text-[11px] font-medium text-teal-700">
          {c}
        </span>
      ))}
    </div>
  );
}

function TargetActivityNotice({ data }: { data: RoadmapResult }) {
  const { t } = useT();
  const inactive = data.inactive_targets ?? 0;
  const unverified = data.unverified_targets ?? 0;
  if (inactive === 0 && unverified === 0) return null;
  return (
    <div
      role="status"
      className="mb-6 rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-amber-900"
    >
      <p className="text-sm font-semibold">{t('roadmap.activityExcludedTitle')}</p>
      <p className="mt-1 text-[13px] text-amber-800">
        {t('roadmap.activityExcludedBody', { inactive, unverified })}
      </p>
    </div>
  );
}

function PartialResolutionNotice({ data }: { data: RoadmapResult }) {
  const { t } = useT();
  if (!data.unresolved_targets) return null;
  return (
    <div
      role="status"
      className="mb-6 rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-amber-900"
    >
      <p className="text-sm font-semibold">{t('roadmap.unresolvedPartialTitle')}</p>
      <p className="mt-1 text-[13px] text-amber-800">
        {t('roadmap.unresolvedPartialBody', {
          unresolved: data.unresolved_targets,
          resolved: data.resolved_targets ?? data.total_labs,
        })}
      </p>
    </div>
  );
}

function SkillEvidenceNotice({ data }: { data: RoadmapResult }) {
  const { t } = useT();
  if (!data.targets_without_skill_evidence) return null;
  return (
    <div
      role="status"
      className="mb-6 rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-amber-900"
    >
      <p className="text-sm font-semibold">{t('roadmap.skillEvidenceIncompleteTitle')}</p>
      <p className="mt-1 text-[13px] text-amber-800">
        {t('roadmap.skillEvidenceIncompleteBody', {
          analyzed: data.targets_with_skill_evidence ?? 0,
          unknown: data.targets_without_skill_evidence,
        })}
      </p>
    </div>
  );
}

export default function RoadmapPage() {
  const router = useRouter();
  const { t } = useT();
  const profile = useLocalStorageJSON<ProfileData>(STORAGE_KEYS.PROFILE);

  const [data, setData] = useState<RoadmapResult | null>(null);
  const [favCount, setFavCount] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [retryToken, setRetryToken] = useState(0);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      if (!profile) { setLoading(false); return; }
      try {
        const ids = Array.from(await getFavorites());
        if (cancelled) return;
        setFavCount(ids.length);
        if (ids.length > 0) {
          const r = await getRoadmap(profile, ids);
          if (!cancelled) setData(r);
        }
      } catch {
        if (!cancelled) setError(true);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    return () => { cancelled = true; };
  }, [profile, retryToken]);

  const retry = () => {
    setError(false);
    setData(null);
    setLoading(true);
    setRetryToken((n) => n + 1);
  };

  const header = (
    <>
      <button
        type="button"
        onClick={() => router.back()}
        className="mb-8 inline-flex items-center gap-2 text-[13px] text-gray-400 transition-colors duration-300 hover:text-gray-600"
      >
        <ArrowLeft className="h-4 w-4" />
        {t('roadmap.back')}
      </button>
      <div className="mb-8 flex items-center gap-3">
        <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gray-100">
          <GraduationCap className="h-5 w-5 text-gray-600" />
        </div>
        <div>
          <h1 className="text-xl font-bold text-gray-900">{t('roadmap.title')}</h1>
          <p className="text-sm text-gray-400">{t('roadmap.subtitle')}</p>
        </div>
      </div>
    </>
  );

  const errorCard = (
    <div className="rounded-2xl border border-dashed border-gray-200 px-6 py-16 text-center">
      <p className="text-sm font-medium text-gray-600">{t('roadmap.errorTitle')}</p>
      <p className="mt-1 text-[13px] text-gray-400">{t('roadmap.errorBody')}</p>
      <button
        type="button"
        onClick={retry}
        className="mt-5 inline-flex items-center rounded-xl bg-gray-900 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-gray-800"
      >
        {t('roadmap.errorRetry')}
      </button>
    </div>
  );

  let inner: React.ReactNode;
  if (loading) {
    inner = (
      <div className="flex min-h-[40vh] flex-col items-center justify-center gap-4">
        <Loader2 className="h-6 w-6 animate-spin text-gray-400" />
        <p className="text-[13px] text-gray-400">{t('roadmap.loading')}</p>
      </div>
    );
  } else if (!profile) {
    inner = <CenteredCard title={t('roadmap.needProfileTitle')} body={t('roadmap.needProfileBody')} cta={t('roadmap.needProfileCta')} href="/" />;
  } else if (error) {
    inner = errorCard;
  } else if (!favCount) {
    inner = <CenteredCard title={t('roadmap.needFavoritesTitle')} body={t('roadmap.needFavoritesBody')} cta={t('roadmap.needFavoritesCta')} href="/results" />;
  } else if (!data) {
    inner = errorCard;
  } else if ((data.resolved_targets ?? data.total_labs) === 0) {
    inner = (
      <>
        <TargetActivityNotice data={data} />
        <CenteredCard
          title={t('roadmap.noCurrentTargetsTitle')}
          body={t('roadmap.noCurrentTargetsBody', {
            missing: data.unresolved_targets ?? 0,
            inactive: data.inactive_targets ?? 0,
            unverified: data.unverified_targets ?? 0,
          })}
          cta={t('roadmap.noCurrentTargetsCta')}
          href="/favorites"
        />
      </>
    );
  } else if ((data.targets_with_skill_evidence ?? 0) === 0) {
    // Every resolved target exposes no skill requirements — the honest answer
    // is "insufficient evidence", never "already competitive".
    inner = (
      <>
        <TargetActivityNotice data={data} />
        <PartialResolutionNotice data={data} />
        <CenteredCard
          title={t('roadmap.noSkillEvidenceTitle')}
          body={t('roadmap.noSkillEvidenceBody', {
            count: data.targets_without_skill_evidence ?? data.total_labs,
          })}
          cta={t('roadmap.noSkillEvidenceCta')}
          href="/favorites"
        />
      </>
    );
  } else if (data.skills.length === 0) {
    const unknownRemainder = (data.targets_without_skill_evidence ?? 0) > 0;
    inner = (
      <>
        <TargetActivityNotice data={data} />
        <PartialResolutionNotice data={data} />
        <SkillEvidenceNotice data={data} />
        <div className={`rounded-2xl px-6 py-12 text-center ${
          unknownRemainder
            ? 'border border-amber-200 bg-amber-50/50'
            : 'border border-emerald-200 bg-emerald-50/50'
        }`}>
          <p className={`text-sm font-medium ${
            unknownRemainder ? 'text-amber-800' : 'text-emerald-700'
          }`}>
            {t(unknownRemainder ? 'roadmap.evidenceCoveredTitle' : 'roadmap.allSetTitle')}
          </p>
          <p className={`mt-1 text-[13px] ${
            unknownRemainder ? 'text-amber-700' : 'text-emerald-600/80'
          }`}>
            {t(
              unknownRemainder ? 'roadmap.evidenceCoveredBody' : 'roadmap.allSetBody',
              { count: data.targets_with_skill_evidence ?? data.total_labs },
            )}
          </p>
        </div>
      </>
    );
  } else {
    const evidenceTotal = data.targets_with_skill_evidence ?? data.total_labs;
    inner = (
      <>
        <TargetActivityNotice data={data} />
        <PartialResolutionNotice data={data} />
        <SkillEvidenceNotice data={data} />
        <p className="mb-4 text-[13px] text-gray-500">
          {t('roadmap.summary', { skills: data.skills.length, labs: evidenceTotal })}
        </p>
        <ol className="space-y-3">
          {data.skills.map((s, i) => (
            <li key={s.skill} className="rounded-2xl border border-gray-200 bg-white p-4 shadow-sm">
              <div className="flex items-start justify-between gap-3">
                <div className="flex items-baseline gap-2">
                  <span className="text-xs font-semibold text-gray-300">{i + 1}</span>
                  <span className="text-sm font-semibold text-gray-900">{s.skill}</span>
                </div>
                <span
                  className={`shrink-0 rounded-full px-2 py-0.5 text-[11px] font-medium ${
                    s.priority === 'high'
                      ? 'bg-red-50 text-red-600'
                      : 'bg-amber-50 text-amber-600'
                  }`}
                >
                  {s.priority === 'high' ? t('roadmap.priorityHigh') : t('roadmap.priorityMedium')}
                </span>
              </div>
              <p className="mt-1.5 pl-5 text-xs text-gray-500">
                {t('roadmap.neededBy', { count: s.needed_by, total: evidenceTotal })} · {s.estimated_time}
              </p>
              <div className="pl-5">
                <CourseSuggestions skill={s} />
              </div>
            </li>
          ))}
        </ol>
      </>
    );
  }

  return (
    <div className="mx-auto max-w-2xl px-4 py-16 sm:px-6 lg:px-8">
      {header}
      {inner}
    </div>
  );
}
