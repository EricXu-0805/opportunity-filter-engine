'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import type { ProfileData, ResumeParseResponse, SkillWithLevel } from '@/lib/types';
import { getStats, parseGitHubProfile } from '@/lib/api';
import { saveProfile, loadProfile } from '@/lib/supabase';
import { decodeProfile, buildShareUrl } from '@/lib/profile-share';
import { DEFAULT_PROFILE, type SaveStatus, type TFunc } from './types';

const VALID_GRADES = new Set(['Freshman', 'Sophomore', 'Junior', 'Senior']);
const VALID_SEEKING = new Set(['research', 'summer_program', 'internship', 'fellowship']);

function applyPrefillFromQuery(
  params: URLSearchParams | ReadonlyURLSearchParams,
  setProfile: React.Dispatch<React.SetStateAction<ProfileData>>,
): void {
  const grade = params.get('prefill_year');
  const seeking = params.get('prefill_seeking');
  if (!grade && !seeking) return;

  setProfile((prev) => {
    const next = { ...prev };
    if (grade && VALID_GRADES.has(grade) && !prev.grade) {
      next.grade = grade;
    }
    if (seeking && VALID_SEEKING.has(seeking)) {
      const existing = prev.seeking_types ?? [];
      if (!existing.includes(seeking)) {
        next.seeking_types = [...existing, seeking];
      }
    }
    return next;
  });
}

type ReadonlyURLSearchParams = ReturnType<typeof useSearchParams>;

export interface UseProfileFormResult {
  profile: ProfileData;
  setProfile: React.Dispatch<React.SetStateAction<ProfileData>>;
  searchWeight: number;
  setSearchWeight: (v: number) => void;
  oppCount: number | null;
  lastUpdated: string | null;
  ghLoading: boolean;
  ghStatus: string | null;
  sharedBanner: string | null;
  dismissSharedBanner: () => void;
  shareCopied: boolean;
  saveStatus: SaveStatus;
  isValid: boolean;
  update: <K extends keyof ProfileData>(key: K, value: ProfileData[K]) => void;
  handleSubmit: () => void;
  handleShare: () => Promise<void>;
  handleResumeParsed: (data: ResumeParseResponse) => void;
  handleGitHubImport: () => Promise<void>;
}

export function useProfileForm(t: TFunc): UseProfileFormResult {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [profile, setProfile] = useState<ProfileData>(DEFAULT_PROFILE);
  const [searchWeight, setSearchWeight] = useState(50);
  const [oppCount, setOppCount] = useState<number | null>(null);
  const [lastUpdated, setLastUpdated] = useState<string | null>(null);
  const [ghLoading, setGhLoading] = useState(false);
  const [ghStatus, setGhStatus] = useState<string | null>(null);
  const [sharedBanner, setSharedBanner] = useState<string | null>(null);
  const [shareCopied, setShareCopied] = useState(false);
  const [saveStatus, setSaveStatus] = useState<SaveStatus>('idle');
  const saveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pendingSaveRef = useRef<ProfileData & { search_weight: number } | null>(null);
  const isInitialLoad = useRef(true);

  useEffect(() => {
    getStats().then((s) => {
      setOppCount(s.total);
      setLastUpdated(s.last_updated_at ?? null);
    }).catch(() => {});

    const shareParam = searchParams.get('share');
    if (shareParam) {
      const shared = decodeProfile(shareParam);
      if (shared) {
        /* eslint-disable react-hooks/set-state-in-effect --
           One-shot URL-share import on mount. setProfile + setSearchWeight
           + setSharedBanner must all flush in the same effect tick so the
           form renders pre-filled from the share link before any user
           interaction; otherwise the home page would flash empty fields. */
        setProfile((prev) => ({ ...prev, ...shared } as ProfileData));
        if (typeof shared.search_weight === 'number') setSearchWeight(shared.search_weight);
        setSharedBanner(t('home.sharedBanner'));
        /* eslint-enable react-hooks/set-state-in-effect */
        setTimeout(() => { isInitialLoad.current = false; }, 500);
        return;
      }
    }

    loadProfile().then((saved) => {
      if (saved) {
        const raw = saved as Record<string, unknown>;
        if (Array.isArray(raw.skills) && raw.skills.length > 0 && typeof raw.skills[0] === 'string') {
          raw.skills = (raw.skills as string[]).map((name) => ({ name, level: 'beginner' as const }));
        }
        setProfile((prev) => ({ ...prev, ...raw } as ProfileData));
        if (typeof raw.search_weight === 'number') setSearchWeight(raw.search_weight);
      }
      applyPrefillFromQuery(searchParams, setProfile);
      setTimeout(() => { isInitialLoad.current = false; }, 500);
    }).catch(() => {
      applyPrefillFromQuery(searchParams, setProfile);
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

    const toSave = { ...profile, search_weight: searchWeight };
    pendingSaveRef.current = toSave;
    setSaveStatus('saving');

    saveTimerRef.current = setTimeout(() => {
      pendingSaveRef.current = null;
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

  useEffect(() => {
    return () => {
      const pending = pendingSaveRef.current;
      if (!pending) return;
      try {
        localStorage.setItem('ofe_profile', JSON.stringify(pending));
      } catch { /* quota or SSR */ }
      saveProfile(pending as unknown as Record<string, unknown>).catch(() => {});
      pendingSaveRef.current = null;
    };
  }, []);

  const update = useCallback(<K extends keyof ProfileData>(key: K, value: ProfileData[K]) => {
    setProfile((prev) => ({
      ...prev,
      [key]: key === 'college' ? value : value,
      ...(key === 'college' ? { major: '' } : {}),
    }));
  }, []);

  const handleResumeParsed = useCallback((data: ResumeParseResponse) => {
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
  }, []);

  const handleGitHubImport = useCallback(async () => {
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
  }, [profile.github_url, t]);

  const handleSubmit = useCallback(() => {
    if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
    const profileToSave = { ...profile, search_weight: searchWeight };
    localStorage.setItem('ofe_profile', JSON.stringify(profileToSave));
    sessionStorage.removeItem('ofe_match_results');
    saveProfile(profileToSave).catch(() => {});
    router.push('/results');
  }, [profile, searchWeight, router]);

  const isValid = !!(profile.college && profile.major && profile.grade);

  useEffect(() => {
    if (isValid) router.prefetch('/results');
  }, [isValid, router]);

  const dismissSharedBanner = useCallback(() => setSharedBanner(null), []);

  return {
    profile,
    setProfile,
    searchWeight,
    setSearchWeight,
    oppCount,
    lastUpdated,
    ghLoading,
    ghStatus,
    sharedBanner,
    dismissSharedBanner,
    shareCopied,
    saveStatus,
    isValid,
    update,
    handleSubmit,
    handleShare,
    handleResumeParsed,
    handleGitHubImport,
  };
}
