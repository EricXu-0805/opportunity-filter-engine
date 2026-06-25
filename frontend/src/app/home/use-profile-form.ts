'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import type { ProfileData, ResumeParseResponse, SkillWithLevel } from '@/lib/types';
import { getStats, parseGitHubProfile } from '@/lib/api';
import { clearMatchCache } from '@/lib/match-cache';
import { STORAGE_KEYS, HOME_SCHOOL_EVENT } from '@/lib/storage-keys';
import { bySlug } from '@/lib/schools';
import { loadProfile, onAuthChange, saveProfile } from '@/lib/supabase';
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

/** Append skills whose names aren't already present (case-sensitive match,
 * mirroring the existing import handlers). Pure — defined at module scope so it
 * isn't a hook dependency. */
function mergeSkills(existing: SkillWithLevel[], incoming: SkillWithLevel[]): SkillWithLevel[] {
  const names = new Set(existing.map((s) => s.name));
  return [...existing, ...incoming.filter((s) => !names.has(s.name))];
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

  // R67 problem #4 (cross-device sync, code-side portion):
  //
  // Without this effect, the home form snapshots whatever the database
  // returned at mount time. If the user then signs in on this browser
  // (anon → permanent) or switches to a different account on the same
  // device, the form keeps showing the OLD profile until they hard-
  // reload the page. The same is true if a different device has saved
  // updates to the user's profile after this tab opened.
  //
  // Fix: subscribe to onAuthChange. On every auth.uid() transition
  // (after the first event, which fires synchronously with the current
  // state and is already handled by the mount effect above), re-fetch
  // the profile from Supabase under the NEW auth context. We flip
  // `isInitialLoad` for ~500ms during the reload so the auto-save
  // effect doesn't fire and immediately overwrite the just-reloaded
  // data with what's currently in state.
  //
  // Tracking via a ref avoids re-subscribing on every render; the ref
  // also lets us skip the very first event without racing the mount
  // effect (which is already loading under the same uid).
  const lastUidRef = useRef<string | null | undefined>(undefined);
  useEffect(() => {
    const unsub = onAuthChange((s) => {
      const uid = s.user?.id ?? null;
      if (lastUidRef.current === undefined) {
        // First event after subscribe — mount effect already handled this uid.
        lastUidRef.current = uid;
        return;
      }
      if (uid === lastUidRef.current) return;
      lastUidRef.current = uid;
      // Pause auto-save during reload so the in-flight state doesn't
      // clobber the freshly fetched data.
      isInitialLoad.current = true;
      loadProfile().then((saved) => {
        if (saved) {
          const raw = saved as Record<string, unknown>;
          if (Array.isArray(raw.skills) && raw.skills.length > 0 && typeof raw.skills[0] === 'string') {
            raw.skills = (raw.skills as string[]).map((name) => ({ name, level: 'beginner' as const }));
          }
          setProfile((prev) => ({ ...prev, ...raw } as ProfileData));
          if (typeof raw.search_weight === 'number') setSearchWeight(raw.search_weight);
        }
        setTimeout(() => { isInitialLoad.current = false; }, 500);
      }).catch(() => {
        isInitialLoad.current = false;
      });
    });
    return () => unsub();
  }, []);

  // The onboarding school gate (a layout-level overlay) finishes *after* this
  // form has already mounted and loaded its profile, so its localStorage write
  // alone would never be reflected here. It also broadcasts the chosen campus on
  // a window event; apply it live so the Institution field updates immediately.
  // The form's own auto-save then persists the full profile.
  useEffect(() => {
    const onHomeSchool = (e: Event) => {
      const slug = (e as CustomEvent<string>).detail;
      if (typeof slug !== 'string' || !slug) return;
      setProfile((prev) => (prev.home_school === slug ? prev : { ...prev, home_school: slug }));
    };
    window.addEventListener(HOME_SCHOOL_EVENT, onHomeSchool);
    return () => window.removeEventListener(HOME_SCHOOL_EVENT, onHomeSchool);
  }, []);

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
      localStorage.setItem(STORAGE_KEYS.PROFILE, JSON.stringify(toSave));
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
        localStorage.setItem(STORAGE_KEYS.PROFILE, JSON.stringify(pending));
      } catch { /* quota or SSR */ }
      saveProfile(pending as unknown as Record<string, unknown>).catch(() => {});
      pendingSaveRef.current = null;
    };
  }, []);

  const update = useCallback(<K extends keyof ProfileData>(key: K, value: ProfileData[K]) => {
    setProfile((prev) => {
      // Picking a different college from a school's catalog invalidates the
      // major (the cascading dropdown). Schools without a catalog edit
      // college as free text, where clearing the major on every keystroke
      // would wipe the user's input.
      const clearMajor =
        key === 'college' && bySlug(prev.home_school ?? 'uiuc')?.catalog != null;
      return {
        ...prev,
        [key]: value,
        ...(clearMajor ? { major: '' } : {}),
      };
    });
  }, []);

  const handleResumeParsed = useCallback((data: ResumeParseResponse) => {
    setProfile((prev) => {
      const newSkills: SkillWithLevel[] = data.extracted_skills.map(
        (name) => ({ name, level: 'experienced' as const }),
      );
      return {
        ...prev,
        skills: mergeSkills(prev.skills, newSkills),
        resume_text: data.raw_text,
        coursework: data.extracted_coursework,
        // Seed the interests box (the only semantic-match lever the form sends)
        // from the resume when the user hasn't typed their own — never overwrite.
        research_interests: prev.research_interests?.trim()
          ? prev.research_interests
          : (data.suggested_interests ?? ''),
      };
    });
  }, []);

  // Imports GitHub-derived skills and returns them (without mutating profile),
  // so both the manual button and submit-time auto-import can reuse it without a
  // stale-state race. Tracks the imported URL so submit won't re-import.
  const githubImportedUrlRef = useRef<string | null>(null);
  const importGitHubSkills = useCallback(async (): Promise<SkillWithLevel[] | null> => {
    const url = profile.github_url?.trim();
    if (!url) return null;
    const match = url.match(/github\.com\/([^/\s?#]+)/);
    const username = match ? match[1] : url;
    setGhLoading(true);
    setGhStatus(null);
    try {
      const data = await parseGitHubProfile(username);
      githubImportedUrlRef.current = url;
      setGhStatus(t('home.form.githubImportSuccess', { skills: data.extracted_skills.length, repos: data.repo_count }));
      return data.extracted_skills.map((name) => ({ name, level: 'experienced' as const }));
    } catch {
      setGhStatus('__fail__' + t('home.form.githubImportFail'));
      return null;
    } finally {
      setGhLoading(false);
    }
  }, [profile.github_url, t]);

  const handleGitHubImport = useCallback(async () => {
    const newSkills = await importGitHubSkills();
    if (newSkills) {
      setProfile((prev) => ({ ...prev, skills: mergeSkills(prev.skills, newSkills) }));
    }
  }, [importGitHubSkills]);

  const handleSubmit = useCallback(async () => {
    if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
    let profileToSave = { ...profile, search_weight: searchWeight };
    // Auto-import GitHub when a URL is present but its skills weren't imported
    // yet, so a pasted-but-not-imported URL isn't silently dropped. Bounded by a
    // short timeout so a slow GitHub API can never block reaching the results.
    const url = profile.github_url?.trim();
    if (url && githubImportedUrlRef.current !== url) {
      const newSkills = await Promise.race([
        importGitHubSkills(),
        new Promise<null>((resolve) => setTimeout(() => resolve(null), 3500)),
      ]);
      if (newSkills?.length) {
        profileToSave = { ...profileToSave, skills: mergeSkills(profileToSave.skills, newSkills) };
      }
    }
    localStorage.setItem(STORAGE_KEYS.PROFILE, JSON.stringify(profileToSave));
    clearMatchCache();
    saveProfile(profileToSave).catch(() => {});
    router.push('/results');
  }, [profile, searchWeight, router, importGitHubSkills]);

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
