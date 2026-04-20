'use client';

import { useState, useCallback, useEffect, useRef, Suspense } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import {
  GraduationCap,
  Globe,
  FileText,
  SlidersHorizontal,
  Sparkles,
  ChevronDown,
  CheckCircle2,
  Upload,
  Github,
  Linkedin,
  Loader2,
  Cloud,
  Share2,
  Check,
} from 'lucide-react';
import dynamic from 'next/dynamic';
import { useT } from '@/i18n/client';
import Card from '@/components/Card';
import SkillTags from '@/components/SkillTags';

const ResumeUpload = dynamic(() => import('@/components/ResumeUpload'), {
  ssr: false,
  loading: () => (
    <div className="h-24 rounded-xl bg-gray-50 border border-dashed border-gray-200 animate-pulse" />
  ),
});
import type { ProfileData, ResumeParseResponse, SkillWithLevel } from '@/lib/types';
import { getStats, parseGitHubProfile } from '@/lib/api';
import { saveProfile, loadProfile } from '@/lib/supabase';
import { COLLEGES, COLLEGE_MAJORS, GRADES } from '@/lib/colleges';
import { decodeProfile, buildShareUrl } from '@/lib/profile-share';

function formatRelativeAge(iso: string): string {
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return '';
  const diffSec = Math.max(0, Math.floor((Date.now() - then) / 1000));
  if (diffSec < 60) return 'just now';
  if (diffSec < 3600) return `${Math.floor(diffSec / 60)}m ago`;
  if (diffSec < 86400) return `${Math.floor(diffSec / 3600)}h ago`;
  return `${Math.floor(diffSec / 86400)}d ago`;
}

function translateKey(t: (p: string) => string, namespace: string, name: string): string {
  const key = `${namespace}.${name}`;
  const out = t(key);
  return out === key ? name : out;
}

const DEFAULT_PROFILE: ProfileData = {
  institution: 'UIUC - University of Illinois Urbana-Champaign',
  college: '',
  major: '',
  grade: '',
  is_international: false,
  research_interests: '',
  skills: [],
  search_weight: 50,
};

export default function HomePage() {
  return (
    <Suspense fallback={null}>
      <HomePageInner />
    </Suspense>
  );
}

function HomePageInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { t } = useT();
  const [profile, setProfile] = useState<ProfileData>(DEFAULT_PROFILE);
  const [searchWeight, setSearchWeight] = useState(50);
  const [oppCount, setOppCount] = useState<number | null>(null);
  const [lastUpdated, setLastUpdated] = useState<string | null>(null);
  const [ghLoading, setGhLoading] = useState(false);
  const [ghStatus, setGhStatus] = useState<string | null>(null);
  const [sharedBanner, setSharedBanner] = useState<string | null>(null);
  const [shareCopied, setShareCopied] = useState(false);

  const [saveStatus, setSaveStatus] = useState<'idle' | 'saving' | 'saved'>('idle');
  const saveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const isInitialLoad = useRef(true);

  useEffect(() => {
    getStats().then(s => {
      setOppCount(s.total);
      setLastUpdated(s.last_updated_at ?? null);
    }).catch(() => {});

    const shareParam = searchParams.get('share');
    if (shareParam) {
      const shared = decodeProfile(shareParam);
      if (shared) {
        setProfile(prev => ({ ...prev, ...shared } as ProfileData));
        if (typeof shared.search_weight === 'number') setSearchWeight(shared.search_weight);
        setSharedBanner(t('home.sharedBanner'));
        setTimeout(() => { isInitialLoad.current = false; }, 500);
        return;
      }
    }

    loadProfile().then(saved => {
      if (saved) {
        const raw = saved as Record<string, unknown>;
        if (Array.isArray(raw.skills) && raw.skills.length > 0 && typeof raw.skills[0] === 'string') {
          raw.skills = (raw.skills as string[]).map((name) => ({ name, level: 'beginner' as const }));
        }
        setProfile(prev => ({ ...prev, ...raw } as ProfileData));
        if (typeof raw.search_weight === 'number') setSearchWeight(raw.search_weight);
      }
      setTimeout(() => { isInitialLoad.current = false; }, 500);
    }).catch(() => {
      isInitialLoad.current = false;
    });
  }, [searchParams, t]);

  const handleShare = useCallback(async () => {
    const url = buildShareUrl({ ...profile, search_weight: searchWeight });
    try {
      await navigator.clipboard.writeText(url);
      setShareCopied(true);
      setTimeout(() => setShareCopied(false), 2000);
    } catch {
      window.prompt('Copy this share URL:', url);
    }
  }, [profile, searchWeight]);

  useEffect(() => {
    if (isInitialLoad.current) return;
    if (saveTimerRef.current) clearTimeout(saveTimerRef.current);

    setSaveStatus('saving');
    saveTimerRef.current = setTimeout(() => {
      const toSave = { ...profile, search_weight: searchWeight };
      localStorage.setItem('ofe_profile', JSON.stringify(toSave));
      saveProfile(toSave)
        .then(() => {
          setSaveStatus('saved');
          setTimeout(() => setSaveStatus('idle'), 2000);
        })
        .catch(() => setSaveStatus('idle'));
    }, 1500);

    return () => {
      if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
    };
  }, [profile, searchWeight]);

  function update<K extends keyof ProfileData>(key: K, value: ProfileData[K]) {
    setProfile((prev) => ({ ...prev, [key]: key === 'college' ? value : value, ...(key === 'college' ? { major: '' } : {}) }));
  }

  const majors = profile.college ? COLLEGE_MAJORS[profile.college] ?? [] : [];

  const handleResumeParsed = useCallback(
    (data: ResumeParseResponse) => {
      setProfile((prev) => {
        const existingNames = new Set(prev.skills.map((s) => s.name));
        const newSkills: SkillWithLevel[] = data.extracted_skills
          .filter((name) => !existingNames.has(name))
          .map((name) => ({ name, level: 'experienced' as const }));
        return {
          ...prev,
          skills: [...prev.skills, ...newSkills],
          resume_text: data.raw_text,
          coursework: data.extracted_coursework,
        };
      });
    },
    [],
  );

  async function handleGitHubImport() {
    const url = profile.github_url?.trim();
    if (!url) return;
    const match = url.match(/github\.com\/([^/\s?#]+)/);
    const username = match ? match[1] : url;
    setGhLoading(true);
    setGhStatus(null);
    try {
      const data = await parseGitHubProfile(username);
      setProfile((prev) => {
        const existingNames = new Set(prev.skills.map((s) => s.name));
        const newSkills: SkillWithLevel[] = data.extracted_skills
          .filter((name) => !existingNames.has(name))
          .map((name) => ({ name, level: 'experienced' as const }));
        return { ...prev, skills: [...prev.skills, ...newSkills] };
      });
      setGhStatus(t('home.form.githubImportSuccess', { skills: data.extracted_skills.length, repos: data.repo_count }));
    } catch {
      setGhStatus('__fail__' + t('home.form.githubImportFail'));
    } finally {
      setGhLoading(false);
    }
  }

  function handleSubmit() {
    if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
    const profileToSave = { ...profile, search_weight: searchWeight };
    localStorage.setItem('ofe_profile', JSON.stringify(profileToSave));
    sessionStorage.removeItem('ofe_match_results');
    saveProfile(profileToSave).catch(() => {});
    router.push('/results');
  }

  const isValid = profile.college && profile.major && profile.grade;

  useEffect(() => {
    if (isValid) router.prefetch('/results');
  }, [isValid, router]);

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-16">
      {sharedBanner && (
        <div className="max-w-3xl mx-auto mb-8 flex items-start gap-3 px-4 py-3 bg-blue-50 border border-blue-200 rounded-xl">
          <Share2 className="w-4 h-4 text-blue-600 mt-0.5 shrink-0" />
          <p className="text-[13px] text-blue-800 leading-relaxed">{sharedBanner}</p>
          <button
            type="button"
            onClick={() => setSharedBanner(null)}
            className="text-blue-600 hover:text-blue-800 text-[12px] font-medium shrink-0"
          >
            {t('common.dismiss')}
          </button>
        </div>
      )}
      <div className="text-center mb-16">
        <div className="inline-flex items-center gap-2 px-4 py-1.5 rounded-full bg-blue-600/[0.08] text-blue-600 text-[13px] font-medium mb-6">
          <Sparkles className="w-3.5 h-3.5" />
          {t('home.hero.tagline')}
        </div>
        <h1 className="text-5xl sm:text-6xl font-bold text-gray-900 tracking-tight leading-[1.1]">
          {t('home.hero.title')}{' '}
          <span className="bg-gradient-to-r from-blue-600 to-blue-400 bg-clip-text text-transparent">
            {t('home.hero.titleAccent')}
          </span>
        </h1>
        <p className="mt-5 text-lg text-gray-400 max-w-xl mx-auto leading-relaxed">
          {t('home.hero.subtitle')}
        </p>
      </div>

      {/* Two-column form */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-8">
        {/* ── Left column: Academic Profile ── */}
        <div className="lg:col-span-7">
          <Card>
            <div className="flex items-center gap-3 mb-8">
              <div className="w-10 h-10 rounded-xl bg-blue-50 flex items-center justify-center">
                <GraduationCap className="w-5 h-5 text-blue-600" />
              </div>
              <div>
                <h2 className="text-xl font-bold text-gray-900">
                  {t('home.cards.academicTitle')}
                </h2>
                <p className="text-sm text-gray-400">
                  {t('home.cards.academicSubtitle')}
                </p>
              </div>
            </div>

            <div className="space-y-6">
              {/* Institution (locked) */}
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">
                  {t('home.form.institutionLabel')}
                </label>
                <div className="flex items-center gap-3 px-4 py-3 border border-gray-200 rounded-xl bg-gray-50">
                  <span className="w-2.5 h-2.5 rounded-full bg-emerald-500 animate-pulse" />
                  <span className="text-sm font-medium text-gray-700">
                    {t('home.form.institutionLocked')}
                  </span>
                  <CheckCircle2 className="w-4 h-4 text-emerald-500 ml-auto" />
                </div>
              </div>

              {/* College */}
              <div>
                <label
                  htmlFor="college"
                  className="block text-sm font-medium text-gray-700 mb-2"
                >
                  {t('home.form.collegeLabel')}
                </label>
                <div className="relative">
                  <select
                    id="college"
                    value={profile.college}
                    onChange={(e) => update('college', e.target.value)}
                    className="w-full appearance-none px-4 py-3.5 border border-gray-200 rounded-2xl text-sm text-gray-700 bg-white focus:ring-2 focus:ring-blue-500/20 focus:border-blue-300 outline-none transition-all duration-300 pr-10"
                  >
                    <option value="">{t('home.form.collegePlaceholder')}</option>
                    {COLLEGES.map((c) => (
                      <option key={c} value={c}>
                        {translateKey(t, 'colleges', c)}
                      </option>
                    ))}
                  </select>
                  <ChevronDown className="absolute right-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400 pointer-events-none" />
                </div>
              </div>

              {/* Major */}
              <div>
                <label
                  htmlFor="major"
                  className="block text-sm font-medium text-gray-700 mb-2"
                >
                  {t('home.form.majorLabel')}
                </label>
                <div className="relative">
                  <select
                    id="major"
                    value={profile.major}
                    onChange={(e) => update('major', e.target.value)}
                    disabled={!profile.college}
                    className="w-full appearance-none px-4 py-3 border border-gray-200 rounded-2xl text-sm text-gray-700 bg-white focus:ring-2 focus:ring-blue-500/20 focus:border-blue-300 outline-none transition-all duration-300 pr-10 disabled:bg-gray-100 disabled:text-gray-400 disabled:cursor-not-allowed"
                  >
                    <option value="">
                      {profile.college
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
              </div>

              {/* Grade */}
              <div>
                <label
                  htmlFor="grade"
                  className="block text-sm font-medium text-gray-700 mb-2"
                >
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

              {/* International Student Toggle */}
              <div className="flex items-center justify-between py-1">
                <div className="flex items-center gap-3">
                  <Globe className="w-5 h-5 text-gray-400" />
                  <div>
                    <span className="text-sm font-medium text-gray-700">
                      {t('home.form.internationalLabel')}
                    </span>
                    <p className="text-xs text-gray-400">
                      {t('home.form.internationalHint')}
                    </p>
                  </div>
                </div>
                <button
                  type="button"
                  role="switch"
                  aria-checked={profile.is_international}
                  onClick={() =>
                    update('is_international', !profile.is_international)
                  }
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
                  {(['research', 'summer_program', 'internship', 'fellowship'] as const).map((type) => {
                    const selected = profile.seeking_types ?? [];
                    const isSelected = selected.includes(type);
                    const labelKey = {
                      research: 'home.form.seekingResearch',
                      summer_program: 'home.form.seekingSummer',
                      internship: 'home.form.seekingInternship',
                      fellowship: 'home.form.seekingFellowship',
                    }[type];
                    return (
                      <button
                        key={type}
                        type="button"
                        onClick={() => {
                          const prev = profile.seeking_types ?? [];
                          const next = isSelected ? prev.filter((tp) => tp !== type) : [...prev, type];
                          update('seeking_types', next);
                        }}
                        className={`px-3 py-1.5 rounded-full text-[13px] font-medium transition-all duration-200 ${
                          isSelected
                            ? 'bg-blue-600 text-white'
                            : 'bg-black/[0.04] text-gray-500 hover:bg-black/[0.08]'
                        }`}
                      >
                        {t(labelKey)}
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
                  {(['any', 'in-person', 'remote'] as const).map((fmt) => {
                    const current = profile.format_preference ?? 'any';
                    const labelKey = { any: 'home.form.formatAny', 'in-person': 'home.form.formatInPerson', remote: 'home.form.formatRemote' }[fmt];
                    return (
                      <button
                        key={fmt}
                        type="button"
                        onClick={() => update('format_preference', fmt)}
                        className={`px-3 py-1.5 rounded-full text-[13px] font-medium transition-all duration-200 ${
                          current === fmt
                            ? 'bg-blue-600 text-white'
                            : 'bg-black/[0.04] text-gray-500 hover:bg-black/[0.08]'
                        }`}
                      >
                        {t(labelKey)}
                      </button>
                    );
                  })}
                </div>
              </div>

              <div>
                <label
                  htmlFor="research_interests"
                  className="block text-sm font-medium text-gray-700 mb-2"
                >
                  {t('home.form.interestsLabel')}
                </label>
                <textarea
                  id="research_interests"
                  value={profile.research_interests}
                  onChange={(e) =>
                    update('research_interests', e.target.value)
                  }
                  rows={4}
                  placeholder={t('home.form.interestsPlaceholder')}
                  className="w-full px-4 py-3 border border-gray-200 rounded-2xl text-sm text-gray-700 placeholder:text-gray-400 focus:ring-2 focus:ring-blue-500/20 focus:border-blue-300 outline-none transition-all duration-300 resize-y leading-relaxed"
                />
              </div>

              {/* Technical Skills */}
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
          </Card>
        </div>

        {/* ── Right column: Documents + Search Focus ── */}
        <div className="lg:col-span-5 space-y-8">
          {/* Documents */}
          <Card>
            <div className="flex items-center gap-3 mb-6">
              <div className="w-10 h-10 rounded-xl bg-orange-50 flex items-center justify-center">
                <FileText className="w-5 h-5 text-uiuc-orange" />
              </div>
              <div>
                <h2 className="text-xl font-bold text-gray-900">{t('home.cards.documentsTitle')}</h2>
                <p className="text-sm text-gray-400">
                  {t('home.cards.documentsSubtitle')}
                </p>
              </div>
            </div>

            <ResumeUpload onParsed={handleResumeParsed} alreadyUploaded={!!profile.resume_text} />

            <div className="mt-4 flex items-start gap-2 px-3 py-2.5 rounded-lg bg-blue-50/60">
              <Upload className="w-4 h-4 text-blue-500 mt-0.5 shrink-0" />
              <p className="text-xs text-blue-600 leading-relaxed">
                {t('home.cards.resumePrivacy')}
              </p>
            </div>
          </Card>

          {/* Online Profiles */}
          <Card>
            <div className="flex items-center gap-3 mb-6">
              <div className="w-10 h-10 rounded-xl bg-gray-100 flex items-center justify-center">
                <Globe className="w-5 h-5 text-gray-600" />
              </div>
              <div>
                <h2 className="text-xl font-bold text-gray-900">{t('home.cards.onlineProfilesTitle')}</h2>
                <p className="text-sm text-gray-400">{t('home.cards.onlineProfilesSubtitle')}</p>
              </div>
            </div>

            <div className="space-y-4">
              <div>
                <label htmlFor="linkedin_url" className="flex items-center gap-1.5 text-sm font-medium text-gray-700 mb-2">
                  <Linkedin className="w-4 h-4 text-[#0A66C2]" />
                  {t('home.form.linkedinLabel')}
                </label>
                <input
                  id="linkedin_url"
                  type="url"
                  value={profile.linkedin_url ?? ''}
                  onChange={(e) => update('linkedin_url', e.target.value)}
                  placeholder={t('home.form.linkedinPlaceholder')}
                  className="w-full px-4 py-3 border border-gray-200 rounded-2xl text-sm text-gray-700 placeholder:text-gray-400 focus:ring-2 focus:ring-blue-500/20 focus:border-blue-300 outline-none transition-all duration-300"
                />
              </div>

              <div>
                <label htmlFor="github_url" className="flex items-center gap-1.5 text-sm font-medium text-gray-700 mb-2">
                  <Github className="w-4 h-4" />
                  GitHub
                </label>
                <div className="flex gap-2">
                  <input
                    id="github_url"
                    type="url"
                    value={profile.github_url ?? ''}
                    onChange={(e) => update('github_url', e.target.value)}
                    placeholder={t('home.form.githubPlaceholder')}
                    className="flex-1 px-4 py-3 border border-gray-200 rounded-2xl text-sm text-gray-700 placeholder:text-gray-400 focus:ring-2 focus:ring-blue-500/20 focus:border-blue-300 outline-none transition-all duration-300"
                  />
                  <button
                    type="button"
                    disabled={!profile.github_url?.trim() || ghLoading}
                    onClick={handleGitHubImport}
                    className="px-4 py-3 text-sm font-medium text-white bg-gray-800 rounded-2xl hover:bg-gray-900 disabled:opacity-40 disabled:cursor-not-allowed transition-colors shrink-0"
                  >
                    {ghLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : t('home.form.githubImport')}
                  </button>
                </div>
                {ghStatus && (
                  <p className={`mt-2 text-xs ${ghStatus.startsWith('__fail__') ? 'text-red-500' : 'text-emerald-600'}`}>
                    {ghStatus.replace(/^__fail__/, '')}
                  </p>
                )}
              </div>
            </div>
          </Card>

          {/* Search Focus */}
          <Card>
            <div className="flex items-center gap-3 mb-6">
              <div className="w-10 h-10 rounded-xl bg-indigo-50 flex items-center justify-center">
                <SlidersHorizontal className="w-5 h-5 text-indigo-600" />
              </div>
              <div>
                <h2 className="text-xl font-bold text-gray-900">
                  {t('home.cards.searchFocusTitle')}
                </h2>
                <p className="text-sm text-gray-400">
                  {t('home.cards.searchFocusSubtitle')}
                </p>
              </div>
            </div>

            <div>
              <div className="flex items-center justify-between text-xs font-medium text-gray-500 mb-3">
                <span className={searchWeight < 50 ? 'text-blue-600 font-semibold' : ''}>
                  {t('home.form.searchWeightLeft')}
                </span>
                <span className={searchWeight > 50 ? 'text-blue-600 font-semibold' : ''}>
                  {t('home.form.searchWeightRight')}
                </span>
              </div>
              <input
                type="range"
                min={0}
                max={100}
                value={searchWeight}
                onChange={(e) => setSearchWeight(Number(e.target.value))}
                className="w-full h-2 rounded-full appearance-none cursor-pointer accent-blue-600 bg-gray-200"
              />
              <p className="mt-2 text-xs text-gray-400 text-center">
                {searchWeight < 40
                  ? t('home.form.searchWeightInterests')
                  : searchWeight > 60
                    ? t('home.form.searchWeightExperience')
                    : t('home.form.searchWeightBalanced')}
              </p>
            </div>
          </Card>

          {/* Quick Stats Teaser */}
          <Card className="bg-gradient-to-br from-blue-600 to-blue-500 border-blue-500 text-white">
            <div className="flex items-center gap-3 mb-3">
              <Sparkles className="w-5 h-5 text-blue-200" />
              <span className="text-sm font-semibold text-blue-100">
                {t('home.cards.liveDatabase')}
              </span>
            </div>
            <p className="text-3xl font-extrabold">{oppCount ?? '...'}</p>
            <p className="text-sm text-blue-200 mt-1">
              {t('home.cards.liveDatabaseHint')}
            </p>
            {lastUpdated && (
              <p className="text-[11px] text-blue-200/70 mt-1.5">
                {t('home.cards.updatedPrefix')} {formatRelativeAge(lastUpdated)}
              </p>
            )}
          </Card>
        </div>
      </div>

      {isValid && (
        <ProfileStrength profile={profile} hasResume={!!profile.resume_text} t={t} />
      )}

      <div className="flex flex-col sm:flex-row items-center justify-center mt-8 gap-3">
        <button
          type="button"
          disabled={!isValid}
          onClick={handleSubmit}
          className="group inline-flex items-center justify-center gap-2.5 w-full sm:w-auto px-8 py-3.5 text-[15px] font-semibold text-white bg-blue-600 rounded-full hover:bg-blue-700 transition-all duration-300 disabled:opacity-40 disabled:cursor-not-allowed shadow-[0_2px_12px_rgba(37,99,235,0.25)] hover:shadow-[0_4px_20px_rgba(37,99,235,0.35)]"
        >
          <Sparkles className="w-4 h-4 group-hover:rotate-12 transition-transform duration-300" />
          {t('home.actions.generate')}
        </button>
        {isValid && (
          <button
            type="button"
            onClick={handleShare}
            className="inline-flex items-center justify-center gap-2 w-full sm:w-auto px-5 py-3.5 text-[13px] font-medium text-gray-600 bg-white border border-gray-200 rounded-full hover:bg-gray-50 transition-colors"
            title={t('home.actions.shareProfile')}
          >
            {shareCopied ? (
              <>
                <Check className="w-4 h-4 text-emerald-500" />
                {t('home.actions.shareCopied')}
              </>
            ) : (
              <>
                <Share2 className="w-4 h-4" />
                {t('home.actions.shareProfile')}
              </>
            )}
          </button>
        )}
      </div>

      {!isValid ? (
        <p className="text-center text-[13px] text-gray-400 mt-4">
          {t('home.validation.requiredFields')}
        </p>
      ) : (
        <div className="flex justify-center items-center gap-2 mt-4 h-5" role="status" aria-live="polite">
          {saveStatus === 'saving' && (
            <span className="inline-flex items-center gap-1.5 text-[12px] text-gray-400 animate-pulse">
              <Cloud className="w-3.5 h-3.5" aria-hidden="true" />
              {t('common.saving')}
            </span>
          )}
          {saveStatus === 'saved' && (
            <span className="inline-flex items-center gap-1.5 text-[12px] text-emerald-500">
              <CheckCircle2 className="w-3.5 h-3.5" aria-hidden="true" />
              {t('home.actions.profileSaved')}
            </span>
          )}
        </div>
      )}
    </div>
  );
}


function ProfileStrength({
  profile,
  hasResume,
  t,
}: {
  profile: ProfileData;
  hasResume: boolean;
  t: (path: string, vars?: Record<string, string | number>) => string;
}) {
  const checks = [
    { done: !!profile.college && !!profile.major && !!profile.grade, label: t('home.cards.checkAcademic') },
    { done: profile.skills.length >= 2, label: t('home.cards.checkSkills') },
    { done: !!profile.research_interests?.trim(), label: t('home.cards.checkInterests') },
    { done: hasResume, label: t('home.cards.checkResume') },
    { done: !!(profile.seeking_types && profile.seeking_types.length > 0), label: t('home.cards.checkType') },
  ];

  const completed = checks.filter((c) => c.done).length;
  const total = checks.length;
  const pct = Math.round((completed / total) * 100);
  const color = pct >= 80 ? 'emerald' : pct >= 60 ? 'blue' : 'amber';

  const colorMap = { emerald: 'bg-emerald-400', blue: 'bg-blue-400', amber: 'bg-amber-400' };
  const textMap = { emerald: 'text-emerald-600', blue: 'text-blue-600', amber: 'text-amber-600' };

  if (completed === total) return null;

  return (
    <div className="max-w-md mx-auto mt-12 px-6 py-5 bg-white rounded-2xl shadow-[0_1px_6px_rgba(0,0,0,0.04)]">
      <div className="flex items-center justify-between mb-3">
        <span className="text-[13px] font-semibold text-gray-700">{t('home.cards.profileStrength')}</span>
        <span className={`text-[13px] font-bold tabular-nums ${textMap[color]}`}>{completed}/{total}</span>
      </div>
      <div className="h-1.5 bg-gray-100 rounded-full overflow-hidden mb-3">
        <div
          className={`h-full rounded-full ${colorMap[color]} transition-all duration-500`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <div className="flex flex-wrap gap-x-4 gap-y-1">
        {checks.filter((c) => !c.done).map((c) => (
          <span key={c.label} className="text-[11px] text-gray-400">+ {c.label}</span>
        ))}
      </div>
    </div>
  );
}
