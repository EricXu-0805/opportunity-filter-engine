'use client';

import { useState, useCallback, useEffect } from 'react';
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
} from 'lucide-react';
import Card from '@/components/Card';
import SkillTags from '@/components/SkillTags';
import ResumeUpload from '@/components/ResumeUpload';
import type { ProfileData, ResumeParseResponse } from '@/lib/types';
import { getStats } from '@/lib/api';
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

  useEffect(() => {
    getStats().then(s => setOppCount(s.total)).catch(() => {});
  }, []);

  function update<K extends keyof ProfileData>(key: K, value: ProfileData[K]) {
    setProfile((prev) => ({ ...prev, [key]: key === 'college' ? value : value, ...(key === 'college' ? { major: '' } : {}) }));
  }

  const majors = profile.college ? COLLEGE_MAJORS[profile.college] ?? [] : [];

  const handleResumeParsed = useCallback(
    (data: ResumeParseResponse) => {
      setProfile((prev) => ({
        ...prev,
        skills: Array.from(new Set([...prev.skills, ...data.extracted_skills])),
        resume_text: data.raw_text,
        coursework: data.extracted_coursework,
      }));
    },
    [],
  );

  function handleSubmit() {
    const profileToSave = { ...profile, search_weight: searchWeight };
    localStorage.setItem('ofe_profile', JSON.stringify(profileToSave));
    router.push('/results');
  }

  const isValid = profile.college && profile.major && profile.grade;

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-10">
      {/* Hero */}
      <div className="text-center mb-12">
        <div className="inline-flex items-center gap-2 px-4 py-1.5 rounded-full bg-blue-50 text-blue-700 text-sm font-medium mb-5">
          <Sparkles className="w-4 h-4" />
          AI-Powered Opportunity Matching
        </div>
        <h1 className="text-4xl sm:text-5xl font-extrabold text-gray-900 tracking-tight leading-tight">
          Find Your Perfect{' '}
          <span className="bg-gradient-to-r from-blue-600 to-blue-400 bg-clip-text text-transparent">
            Research Match
          </span>
        </h1>
        <p className="mt-4 text-lg text-gray-500 max-w-2xl mx-auto">
          Tell us about your background and interests. Our engine matches you
          with research positions, internships, and opportunities at UIUC.
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
                    className="w-full appearance-none px-4 py-3 border border-gray-300 rounded-xl text-sm text-gray-700 bg-white focus:ring-2 focus:ring-blue-500/30 focus:border-blue-400 outline-none transition-all pr-10"
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
                    className="w-full appearance-none px-4 py-3 border border-gray-300 rounded-xl text-sm text-gray-700 bg-white focus:ring-2 focus:ring-blue-500/30 focus:border-blue-400 outline-none transition-all pr-10 disabled:bg-gray-100 disabled:text-gray-400 disabled:cursor-not-allowed"
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
                  Current Grade
                </label>
                <div className="relative">
                  <select
                    id="grade"
                    value={profile.grade}
                    onChange={(e) => update('grade', e.target.value)}
                    className="w-full appearance-none px-4 py-3 border border-gray-300 rounded-xl text-sm text-gray-700 bg-white focus:ring-2 focus:ring-blue-500/30 focus:border-blue-400 outline-none transition-all pr-10"
                  >
                    <option value="">Select grade level...</option>
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

              {/* Research Interests */}
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
                  className="w-full px-4 py-3 border border-gray-300 rounded-xl text-sm text-gray-700 placeholder:text-gray-400 focus:ring-2 focus:ring-blue-500/30 focus:border-blue-400 outline-none transition-all resize-y leading-relaxed"
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

            <ResumeUpload onParsed={handleResumeParsed} />

            <div className="mt-4 flex items-start gap-2 px-3 py-2.5 rounded-lg bg-blue-50/60">
              <Upload className="w-4 h-4 text-blue-500 mt-0.5 shrink-0" />
              <p className="text-xs text-blue-600 leading-relaxed">
                Your resume is processed locally and used only for matching.
                It&apos;s never stored permanently.
              </p>
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

      {/* CTA Button */}
      <div className="flex justify-center mt-12">
        <button
          type="button"
          disabled={!isValid}
          onClick={handleSubmit}
          className="group relative inline-flex items-center gap-3 px-10 py-4 text-lg font-bold text-white bg-gradient-to-r from-blue-600 to-blue-500 rounded-2xl shadow-lg shadow-blue-500/25 hover:shadow-xl hover:shadow-blue-500/30 hover:from-blue-700 hover:to-blue-600 transition-all duration-200 disabled:opacity-50 disabled:cursor-not-allowed disabled:shadow-none"
        >
          <Sparkles className="w-5 h-5 group-hover:rotate-12 transition-transform" />
          Generate Matches
          <span className="absolute -top-2 -right-2 flex h-5 w-5">
            {isValid && (
              <>
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-blue-400 opacity-75" />
                <span className="relative inline-flex rounded-full h-5 w-5 bg-blue-500 items-center justify-center">
                  <CheckCircle2 className="w-3 h-3 text-white" />
                </span>
              </>
            )}
          </span>
        </button>
      </div>

      {!isValid && (
        <p className="text-center text-sm text-gray-400 mt-3">
          Please select your college, major, and grade to continue
        </p>
      )}
    </div>
  );
}
