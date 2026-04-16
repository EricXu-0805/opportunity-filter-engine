'use client';

import { useState, useCallback, useEffect, useRef } from 'react';
import { useRouter } from 'next/navigation';
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
  CloudOff,
} from 'lucide-react';
import Card from '@/components/Card';
import SkillTags from '@/components/SkillTags';
import ResumeUpload from '@/components/ResumeUpload';
import type { ProfileData, ResumeParseResponse, SkillWithLevel } from '@/lib/types';
import { getStats, parseGitHubProfile } from '@/lib/api';
import { saveProfile, loadProfile } from '@/lib/supabase';
import { COLLEGES, COLLEGE_MAJORS, GRADES } from '@/lib/colleges';

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
  const router = useRouter();
  const [profile, setProfile] = useState<ProfileData>(DEFAULT_PROFILE);
  const [searchWeight, setSearchWeight] = useState(50);
  const [oppCount, setOppCount] = useState<number | null>(null);
  const [ghLoading, setGhLoading] = useState(false);
  const [ghStatus, setGhStatus] = useState<string | null>(null);

  const [saveStatus, setSaveStatus] = useState<'idle' | 'saving' | 'saved'>('idle');
  const saveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const isInitialLoad = useRef(true);

  useEffect(() => {
    getStats().then(s => setOppCount(s.total)).catch(() => {});
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
  }, []);

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
      setGhStatus(`Imported ${data.extracted_skills.length} skills from ${data.repo_count} repos`);
    } catch {
      setGhStatus('Could not fetch GitHub profile');
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

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-16">
      <div className="text-center mb-16">
        <div className="inline-flex items-center gap-2 px-4 py-1.5 rounded-full bg-blue-600/[0.08] text-blue-600 text-[13px] font-medium mb-6">
          <Sparkles className="w-3.5 h-3.5" />
          AI-Powered Opportunity Matching
        </div>
        <h1 className="text-5xl sm:text-6xl font-bold text-gray-900 tracking-tight leading-[1.1]">
          Find Your Perfect{' '}
          <span className="bg-gradient-to-r from-blue-600 to-blue-400 bg-clip-text text-transparent">
            Research Match
          </span>
        </h1>
        <p className="mt-5 text-lg text-gray-400 max-w-xl mx-auto leading-relaxed">
          Tell us about yourself. We match you with research, internships,
          and opportunities at UIUC.
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
                  Academic Profile
                </h2>
                <p className="text-sm text-gray-400">
                  Build your profile for personalized matching
                </p>
              </div>
            </div>

            <div className="space-y-6">
              {/* Institution (locked) */}
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">
                  Institution
                </label>
                <div className="flex items-center gap-3 px-4 py-3 border border-gray-200 rounded-xl bg-gray-50">
                  <span className="w-2.5 h-2.5 rounded-full bg-emerald-500 animate-pulse" />
                  <span className="text-sm font-medium text-gray-700">
                    UIUC — University of Illinois Urbana-Champaign
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
                  College
                </label>
                <div className="relative">
                  <select
                    id="college"
                    value={profile.college}
                    onChange={(e) => update('college', e.target.value)}
                    className="w-full appearance-none px-4 py-3.5 border border-gray-200 rounded-2xl text-sm text-gray-700 bg-white focus:ring-2 focus:ring-blue-500/20 focus:border-blue-300 outline-none transition-all duration-300 pr-10"
                  >
                    <option value="">Select your college...</option>
                    {COLLEGES.map((c) => (
                      <option key={c} value={c}>
                        {c}
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
                  Major / Department
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
                        ? 'Select your major...'
                        : 'Choose a college first'}
                    </option>
                    {majors.map((m) => (
                      <option key={m} value={m}>
                        {m}
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
                  Anticipated Grade When Starting
                </label>
                <div className="relative">
                  <select
                    id="grade"
                    value={profile.grade}
                    onChange={(e) => update('grade', e.target.value)}
                    className="w-full appearance-none px-4 py-3 border border-gray-200 rounded-2xl text-sm text-gray-700 bg-white focus:ring-2 focus:ring-blue-500/20 focus:border-blue-300 outline-none transition-all duration-300 pr-10"
                  >
                    <option value="">Grade when you'd start...</option>
                    {GRADES.map((g) => (
                      <option key={g} value={g}>
                        {g}
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
                      International Student
                    </span>
                    <p className="text-xs text-gray-400">
                      We&apos;ll filter for visa-friendly positions
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
                  Preferred Opportunity Type
                </label>
                <div className="flex flex-wrap gap-2">
                  {['research', 'summer_program', 'internship', 'fellowship'].map((type) => {
                    const selected = profile.seeking_types ?? [];
                    const isSelected = selected.includes(type);
                    return (
                      <button
                        key={type}
                        type="button"
                        onClick={() => {
                          const prev = profile.seeking_types ?? [];
                          const next = isSelected ? prev.filter((t) => t !== type) : [...prev, type];
                          update('seeking_types', next);
                        }}
                        className={`px-3 py-1.5 rounded-full text-[13px] font-medium transition-all duration-200 ${
                          isSelected
                            ? 'bg-blue-600 text-white'
                            : 'bg-black/[0.04] text-gray-500 hover:bg-black/[0.08]'
                        }`}
                      >
                        {type.replace('_', ' ')}
                      </button>
                    );
                  })}
                </div>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">
                  Format Preference
                </label>
                <div className="flex gap-2">
                  {['any', 'in-person', 'remote'].map((fmt) => {
                    const current = profile.format_preference ?? 'any';
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
                        {fmt === 'any' ? 'No preference' : fmt === 'remote' ? 'Remote / Online' : 'In-person'}
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
                  Research Interests
                </label>
                <textarea
                  id="research_interests"
                  value={profile.research_interests}
                  onChange={(e) =>
                    update('research_interests', e.target.value)
                  }
                  rows={4}
                  placeholder="e.g., I'm interested in machine learning applications in healthcare, particularly medical image analysis using deep learning. I've taken courses in probability, data structures, and intro ML..."
                  className="w-full px-4 py-3 border border-gray-200 rounded-2xl text-sm text-gray-700 placeholder:text-gray-400 focus:ring-2 focus:ring-blue-500/20 focus:border-blue-300 outline-none transition-all duration-300 resize-y leading-relaxed"
                />
              </div>

              {/* Technical Skills */}
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">
                  Technical Skills
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
                <h2 className="text-xl font-bold text-gray-900">Documents</h2>
                <p className="text-sm text-gray-400">
                  Upload for automatic skill extraction
                </p>
              </div>
            </div>

            <ResumeUpload onParsed={handleResumeParsed} alreadyUploaded={!!profile.resume_text} />

            <div className="mt-4 flex items-start gap-2 px-3 py-2.5 rounded-lg bg-blue-50/60">
              <Upload className="w-4 h-4 text-blue-500 mt-0.5 shrink-0" />
              <p className="text-xs text-blue-600 leading-relaxed">
                Your resume is processed locally and used only for matching.
                It&apos;s never stored permanently.
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
                <h2 className="text-xl font-bold text-gray-900">Online Profiles</h2>
                <p className="text-sm text-gray-400">Optional — helps enrich your match</p>
              </div>
            </div>

            <div className="space-y-4">
              <div>
                <label htmlFor="linkedin_url" className="flex items-center gap-1.5 text-sm font-medium text-gray-700 mb-2">
                  <Linkedin className="w-4 h-4 text-[#0A66C2]" />
                  LinkedIn
                </label>
                <input
                  id="linkedin_url"
                  type="url"
                  value={profile.linkedin_url ?? ''}
                  onChange={(e) => update('linkedin_url', e.target.value)}
                  placeholder="https://linkedin.com/in/your-profile"
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
                    placeholder="https://github.com/username"
                    className="flex-1 px-4 py-3 border border-gray-200 rounded-2xl text-sm text-gray-700 placeholder:text-gray-400 focus:ring-2 focus:ring-blue-500/20 focus:border-blue-300 outline-none transition-all duration-300"
                  />
                  <button
                    type="button"
                    disabled={!profile.github_url?.trim() || ghLoading}
                    onClick={handleGitHubImport}
                    className="px-4 py-3 text-sm font-medium text-white bg-gray-800 rounded-2xl hover:bg-gray-900 disabled:opacity-40 disabled:cursor-not-allowed transition-colors shrink-0"
                  >
                    {ghLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : 'Import'}
                  </button>
                </div>
                {ghStatus && (
                  <p className={`mt-2 text-xs ${ghStatus.startsWith('Could not') ? 'text-red-500' : 'text-emerald-600'}`}>
                    {ghStatus}
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
                  Search Focus
                </h2>
                <p className="text-sm text-gray-400">
                  Balance between interests & experience
                </p>
              </div>
            </div>

            <div>
              <div className="flex items-center justify-between text-xs font-medium text-gray-500 mb-3">
                <span className={searchWeight < 50 ? 'text-blue-600 font-semibold' : ''}>
                  Research Interests
                </span>
                <span className={searchWeight > 50 ? 'text-blue-600 font-semibold' : ''}>
                  Resume / Experience
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
                  ? 'Prioritizing your research interests'
                  : searchWeight > 60
                    ? 'Prioritizing your resume & experience'
                    : 'Balanced between interests & experience'}
              </p>
            </div>
          </Card>

          {/* Quick Stats Teaser */}
          <Card className="bg-gradient-to-br from-blue-600 to-blue-500 border-blue-500 text-white">
            <div className="flex items-center gap-3 mb-3">
              <Sparkles className="w-5 h-5 text-blue-200" />
              <span className="text-sm font-semibold text-blue-100">
                Live Database
              </span>
            </div>
            <p className="text-3xl font-extrabold">{oppCount ?? '...'}</p>
            <p className="text-sm text-blue-200 mt-1">
              Active research & internship opportunities at UIUC
            </p>
          </Card>
        </div>
      </div>

      <div className="flex justify-center mt-16">
        <button
          type="button"
          disabled={!isValid}
          onClick={handleSubmit}
          className="group inline-flex items-center gap-2.5 px-8 py-3.5 text-[15px] font-semibold text-white bg-blue-600 rounded-full hover:bg-blue-700 transition-all duration-300 disabled:opacity-40 disabled:cursor-not-allowed shadow-[0_2px_12px_rgba(37,99,235,0.25)] hover:shadow-[0_4px_20px_rgba(37,99,235,0.35)]"
        >
          <Sparkles className="w-4 h-4 group-hover:rotate-12 transition-transform duration-300" />
          Generate Matches
        </button>
      </div>

      {!isValid ? (
        <p className="text-center text-[13px] text-gray-400 mt-4">
          Please select your college, major, and grade to continue
        </p>
      ) : (
        <div className="flex justify-center items-center gap-2 mt-4 h-5">
          {saveStatus === 'saving' && (
            <span className="inline-flex items-center gap-1.5 text-[12px] text-gray-400 animate-pulse">
              <Cloud className="w-3.5 h-3.5" />
              Saving...
            </span>
          )}
          {saveStatus === 'saved' && (
            <span className="inline-flex items-center gap-1.5 text-[12px] text-emerald-500">
              <CheckCircle2 className="w-3.5 h-3.5" />
              Profile saved
            </span>
          )}
        </div>
      )}
    </div>
  );
}
