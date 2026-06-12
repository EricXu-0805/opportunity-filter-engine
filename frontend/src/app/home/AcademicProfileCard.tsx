'use client';

import { useEffect, useState } from 'react';
import { ChevronDown, Globe, GraduationCap } from 'lucide-react';
import Card from '@/components/Card';
import SkillTags from '@/components/SkillTags';
import UniversitySwitcherModal from '@/components/UniversitySwitcherModal';
import { useLocale } from '@/i18n/client';
import type { ProfileData } from '@/lib/types';
import { GRADES } from '@/lib/colleges';
import { loadCatalog } from '@/lib/catalogs';
import { bySlug } from '@/lib/schools';
import { translateKey } from './home-utils';
import { FORMAT_OPTIONS, SEEKING_TYPES, type TFunc } from './types';

export function AcademicProfileCard({
  profile,
  update,
  t,
}: {
  profile: ProfileData;
  update: <K extends keyof ProfileData>(key: K, value: ProfileData[K]) => void;
  t: TFunc;
}) {
  const locale = useLocale();
  const [switcherOpen, setSwitcherOpen] = useState(false);
  const homeSchool = profile.home_school ?? 'uiuc';
  const school = bySlug(homeSchool);
  const schoolName = school ? (locale === 'zh' ? school.nameZh : school.name) : homeSchool;
  // Schools with a curated catalog (per the registry) render cascading
  // college/major dropdowns fed by a code-split catalog chunk; schools
  // without one degrade to free-text inputs until their catalog ships.
  const hasCatalog = !!school?.catalog;
  // Keyed by slug so a resolved load for the previously selected school
  // can never paint the current one (rapid switching), even before the
  // cancellation guard drops the stale promise.
  const [loaded, setLoaded] = useState<{
    slug: string;
    data: Record<string, string[]> | null;
  } | null>(null);

  useEffect(() => {
    if (!hasCatalog) return;
    let cancelled = false;
    loadCatalog(homeSchool).then(
      (data) => { if (!cancelled) setLoaded({ slug: homeSchool, data }); },
      () => { if (!cancelled) setLoaded({ slug: homeSchool, data: null }); },
    );
    return () => { cancelled = true; };
  }, [homeSchool, hasCatalog]);

  // undefined = catalog chunk still loading; null = none for this school.
  const catalog = loaded?.slug === homeSchool ? loaded.data : undefined;
  const showCatalog = hasCatalog && catalog !== null;
  const catalogLoading = showCatalog && catalog === undefined;
  const colleges = catalog ? Object.keys(catalog) : [];
  const majors = catalog && profile.college ? catalog[profile.college] ?? [] : [];
  const seeking = profile.seeking_types ?? [];
  const format = profile.format_preference ?? 'any';

  const seekingLabel = {
    research: 'home.form.seekingResearch',
    summer_program: 'home.form.seekingSummer',
    internship: 'home.form.seekingInternship',
    fellowship: 'home.form.seekingFellowship',
  } as const;

  const formatLabel = {
    any: 'home.form.formatAny',
    'in-person': 'home.form.formatInPerson',
    remote: 'home.form.formatRemote',
  } as const;

  return (
    <Card>
      <div className="flex items-center gap-3 mb-8">
        <div className="w-10 h-10 rounded-xl bg-blue-50 flex items-center justify-center">
          <GraduationCap className="w-5 h-5 text-blue-600" />
        </div>
        <div>
          <h2 className="text-xl font-bold text-gray-900">{t('home.cards.academicTitle')}</h2>
          <p className="text-sm text-gray-400">{t('home.cards.academicSubtitle')}</p>
        </div>
      </div>

      <div className="space-y-6">
        <div>
          <label htmlFor="student_name" className="block text-sm font-medium text-gray-700 mb-2">
            {t('home.form.nameLabel')}
          </label>
          <input
            id="student_name"
            type="text"
            value={profile.name ?? ''}
            onChange={(e) => update('name', e.target.value)}
            placeholder={t('home.form.namePlaceholder')}
            className="w-full px-4 py-3 border border-gray-200 rounded-2xl text-sm text-gray-700 placeholder:text-gray-400 focus:ring-2 focus:ring-blue-500/20 focus:border-blue-300 outline-none transition-all duration-300"
          />
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-700 mb-2">
            {t('home.form.institutionLabel')}
          </label>
          <div className="flex items-center gap-3 px-4 py-3 border border-gray-200 rounded-xl bg-gray-50">
            <span className="w-2.5 h-2.5 rounded-full bg-emerald-500 shrink-0" />
            <span className="text-sm font-medium text-gray-700 truncate">
              {schoolName}
            </span>
            <button
              type="button"
              onClick={() => setSwitcherOpen(true)}
              className="ml-auto shrink-0 text-[13px] font-medium text-blue-600 hover:text-blue-700 transition-colors"
            >
              {t('home.form.changeSchool')}
            </button>
          </div>
        </div>

        <div>
          <label htmlFor="college" className="block text-sm font-medium text-gray-700 mb-2">
            {t('home.form.collegeLabel')}
          </label>
          {showCatalog ? (
            <div className="relative">
              <select
                id="college"
                value={profile.college}
                onChange={(e) => update('college', e.target.value)}
                disabled={catalogLoading}
                aria-busy={catalogLoading}
                className="w-full appearance-none px-4 py-3.5 border border-gray-200 rounded-2xl text-sm text-gray-700 bg-white focus:ring-2 focus:ring-blue-500/20 focus:border-blue-300 outline-none transition-all duration-300 pr-10 disabled:bg-gray-50 disabled:text-gray-400 disabled:cursor-wait disabled:animate-pulse"
              >
                <option value="">
                  {catalogLoading
                    ? t('home.form.catalogLoading')
                    : t('home.form.collegePlaceholder')}
                </option>
                {colleges.map((c) => (
                  <option key={c} value={c}>
                    {translateKey(t, 'colleges', c)}
                  </option>
                ))}
              </select>
              <ChevronDown className="absolute right-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400 pointer-events-none" />
            </div>
          ) : (
            <>
              <input
                id="college"
                type="text"
                value={profile.college}
                onChange={(e) => update('college', e.target.value)}
                placeholder={t('home.form.collegeFreeTextPlaceholder')}
                className="w-full px-4 py-3 border border-gray-200 rounded-2xl text-sm text-gray-700 placeholder:text-gray-400 focus:ring-2 focus:ring-blue-500/20 focus:border-blue-300 outline-none transition-all duration-300"
              />
              <p className="text-xs text-gray-400 mt-1.5">{t('home.form.catalogPendingNote')}</p>
            </>
          )}
        </div>

        <div>
          <label htmlFor="major" className="block text-sm font-medium text-gray-700 mb-2">
            {t('home.form.majorLabel')}
          </label>
          {showCatalog ? (
            <div className="relative">
              <select
                id="major"
                value={profile.major}
                onChange={(e) => update('major', e.target.value)}
                disabled={catalogLoading || !profile.college}
                aria-busy={catalogLoading}
                className="w-full appearance-none px-4 py-3 border border-gray-200 rounded-2xl text-sm text-gray-700 bg-white focus:ring-2 focus:ring-blue-500/20 focus:border-blue-300 outline-none transition-all duration-300 pr-10 disabled:bg-gray-100 disabled:text-gray-400 disabled:cursor-not-allowed"
              >
                <option value="">
                  {catalogLoading
                    ? t('home.form.catalogLoading')
                    : profile.college
                      ? t('home.form.majorPlaceholder')
                      : t('home.form.majorPlaceholderNoCollege')}
                </option>
                {majors.map((m) => (
                  <option key={m} value={m}>
                    {translateKey(t, 'majors', m)}
                  </option>
                ))}
              </select>
              <ChevronDown className="absolute right-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400 pointer-events-none" />
            </div>
          ) : (
            <input
              id="major"
              type="text"
              value={profile.major}
              onChange={(e) => update('major', e.target.value)}
              placeholder={t('home.form.majorFreeTextPlaceholder')}
              className="w-full px-4 py-3 border border-gray-200 rounded-2xl text-sm text-gray-700 placeholder:text-gray-400 focus:ring-2 focus:ring-blue-500/20 focus:border-blue-300 outline-none transition-all duration-300"
            />
          )}
        </div>

        <div>
          <label htmlFor="grade" className="block text-sm font-medium text-gray-700 mb-2">
            {t('home.form.gradeLabel')}
          </label>
          <div className="relative">
            <select
              id="grade"
              value={profile.grade}
              onChange={(e) => update('grade', e.target.value)}
              className="w-full appearance-none px-4 py-3 border border-gray-200 rounded-2xl text-sm text-gray-700 bg-white focus:ring-2 focus:ring-blue-500/20 focus:border-blue-300 outline-none transition-all duration-300 pr-10"
            >
              <option value="">{t('home.form.gradePlaceholder')}</option>
              {GRADES.map((g) => (
                <option key={g} value={g}>
                  {translateKey(t, 'grades', g)}
                </option>
              ))}
            </select>
            <ChevronDown className="absolute right-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400 pointer-events-none" />
          </div>
        </div>

        <div className="flex items-center justify-between py-1">
          <div className="flex items-center gap-3">
            <Globe className="w-5 h-5 text-gray-400" />
            <div>
              <span className="text-sm font-medium text-gray-700">
                {t('home.form.internationalLabel')}
              </span>
              <p className="text-xs text-gray-400">{t('home.form.internationalHint')}</p>
            </div>
          </div>
          <button
            type="button"
            role="switch"
            aria-checked={profile.is_international}
            onClick={() => update('is_international', !profile.is_international)}
            className={`relative inline-flex h-7 w-12 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2
              ${profile.is_international ? 'bg-blue-600' : 'bg-gray-200'}`}
          >
            <span
              className={`pointer-events-none inline-block h-6 w-6 transform rounded-full bg-white shadow-lg ring-0 transition duration-200 ease-in-out
                ${profile.is_international ? 'translate-x-5' : 'translate-x-0'}`}
            />
          </button>
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-700 mb-2">
            {t('home.form.seekingLabel')}
          </label>
          <div className="flex flex-wrap gap-2">
            {SEEKING_TYPES.map((type) => {
              const isSelected = seeking.includes(type);
              return (
                <button
                  key={type}
                  type="button"
                  onClick={() => {
                    const next = isSelected ? seeking.filter((tp) => tp !== type) : [...seeking, type];
                    update('seeking_types', next);
                  }}
                  className={`px-3 py-1.5 rounded-full text-[13px] font-medium transition-all duration-200 ${
                    isSelected
                      ? 'bg-blue-600 text-white'
                      : 'bg-black/[0.04] text-gray-500 hover:bg-black/[0.08]'
                  }`}
                >
                  {t(seekingLabel[type])}
                </button>
              );
            })}
          </div>
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-700 mb-2">
            {t('home.form.formatLabel')}
          </label>
          <div className="flex gap-2">
            {FORMAT_OPTIONS.map((fmt) => (
              <button
                key={fmt}
                type="button"
                onClick={() => update('format_preference', fmt)}
                className={`px-3 py-1.5 rounded-full text-[13px] font-medium transition-all duration-200 ${
                  format === fmt
                    ? 'bg-blue-600 text-white'
                    : 'bg-black/[0.04] text-gray-500 hover:bg-black/[0.08]'
                }`}
              >
                {t(formatLabel[fmt])}
              </button>
            ))}
          </div>
        </div>

        <div>
          <label htmlFor="research_interests" className="block text-sm font-medium text-gray-700 mb-2">
            {t('home.form.interestsLabel')}
          </label>
          <textarea
            id="research_interests"
            value={profile.research_interests}
            onChange={(e) => update('research_interests', e.target.value)}
            rows={4}
            placeholder={t('home.form.interestsPlaceholder')}
            className="w-full px-4 py-3 border border-gray-200 rounded-2xl text-sm text-gray-700 placeholder:text-gray-400 focus:ring-2 focus:ring-blue-500/20 focus:border-blue-300 outline-none transition-all duration-300 resize-y leading-relaxed"
          />
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-700 mb-2">
            {t('home.form.skillsLabel')}
          </label>
          <SkillTags
            selected={profile.skills}
            onChange={(skills) => update('skills', skills)}
          />
        </div>
      </div>

      {switcherOpen && (
        <UniversitySwitcherModal
          initialSelectedSlug={homeSchool}
          onCancel={() => setSwitcherOpen(false)}
          onConfirm={(slug) => {
            update('home_school', slug);
            setSwitcherOpen(false);
          }}
        />
      )}
    </Card>
  );
}
